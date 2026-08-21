"""Core routing engine for Hermes multi-provider account router."""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional, Tuple

from .adapters import get_adapter
from .adapters.base_adapter import ErrorCategory
from .health_tracker import HealthTracker, extract_model_family
from .profile_manager import ProfileAuthManager
from .router_config import RolePolicy, RouterConfig, RouterProfileConfig, load_router_config
from .session_affinity import LeaseManager, SessionAffinityTracker

logger = logging.getLogger("hermes.router")


class RouterEngine:
    """Central router managing role-based chains, session affinity, leases, and failover."""

    def __init__(
        self,
        config: Optional[RouterConfig] = None,
        health: Optional[HealthTracker] = None,
        affinity: Optional[SessionAffinityTracker] = None,
        leases: Optional[LeaseManager] = None,
    ) -> None:
        self.config = config or load_router_config()
        self.health = health or HealthTracker()
        self.affinity = affinity or SessionAffinityTracker(ttl_seconds=self.config.session_affinity_ttl_seconds)
        self.leases = leases if leases is not None else LeaseManager.get()

    def reload_config(self) -> None:
        self.config = load_router_config()
        if self.affinity and hasattr(self.affinity, "ttl_seconds"):
            self.affinity.ttl_seconds = self.config.session_affinity_ttl_seconds

    def resolve_role(self, request: Dict[str, Any], explicit_role: Optional[str] = None) -> str:
        """Determine logical role from explicit parameter, request payload, or personality."""
        if explicit_role:
            return explicit_role.strip().lower()
        if "role" in request and request["role"]:
            return str(request["role"]).strip().lower()
        if "personality" in request and request["personality"]:
            return str(request["personality"]).strip().lower()
        # Inspect system message or metadata for subagent role hints
        messages = request.get("messages", [])
        if messages and isinstance(messages, list):
            first = messages[0]
            if isinstance(first, dict) and first.get("role") == "system":
                sys_content = str(first.get("content", "")).lower()
                if "role: coder" in sys_content or "developer" in sys_content or "coding agent" in sys_content:
                    return "coder-primary"
                if "role: reviewer" in sys_content or "code-reviewer" in sys_content or "review agent" in sys_content:
                    return "reviewer"
                if "role: researcher" in sys_content or "research agent" in sys_content:
                    return "research"
        return self.config.default_role

    def resolve_session_id(self, request: Dict[str, Any], explicit_session_id: Optional[str] = None) -> Optional[str]:
        if explicit_session_id:
            return explicit_session_id
        if "session_id" in request and request["session_id"]:
            return str(request["session_id"])
        # Check custom headers or metadata
        metadata = request.get("metadata", {})
        if isinstance(metadata, dict) and "session_id" in metadata:
            return str(metadata["session_id"])
        return None

    def route_request(
        self,
        request: Dict[str, Any],
        role: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Execute request with session affinity and role-aware failover."""
        target_role = self.resolve_role(request, role)
        target_session = self.resolve_session_id(request, session_id)
        role_policy = self.config.get_role_policy(target_role)

        requested_model = request.get("model")
        # Read runtime settings from hub_settings.json
        from .settings_service import get_hub_settings
        hub_settings = get_hub_settings()

        affinity_enabled = bool(hub_settings.get("session_affinity", True)) and role_policy.session_affinity_enabled
        auto_failover = bool(hub_settings.get("auto_failover", True))
        auto_return_primary = bool(hub_settings.get("auto_return_primary", True))

        # 1. Check Session Affinity
        candidate_profiles: list[str] = []
        if target_session and affinity_enabled:
            aff_rec = self.affinity.get_affinity(target_session)
            if aff_rec and aff_rec.profile_id in self.config.profiles:
                # If auto_return_primary is active, check if primary chain slot is healthy again
                primary_pid = role_policy.preferred_chain[0] if role_policy.preferred_chain else None
                if auto_return_primary and primary_pid and primary_pid != aff_rec.profile_id and self.health.is_healthy(primary_pid, requested_model):
                    # Return to primary account
                    pass
                else:
                    aff_profile = self.config.profiles[aff_rec.profile_id]
                    if aff_profile.enabled and self.health.is_healthy(aff_rec.profile_id, requested_model):
                        candidate_profiles.append(aff_rec.profile_id)

        # 2. Add remaining preferred chain candidates
        for pid in role_policy.preferred_chain:
            if pid not in candidate_profiles:
                candidate_profiles.append(pid)

        # 3. Add any matching capability fallbacks if chain exhausted
        for pid, pconfig in self.config.profiles.items():
            if pid not in candidate_profiles and pconfig.enabled:
                if any(cap in pconfig.capabilities for cap in role_policy.fallback_capabilities):
                    candidate_profiles.append(pid)

        failover_trail: list[dict[str, Any]] = []
        evaluated_candidates: list[dict[str, Any]] = []
        attempts = 0
        if auto_failover:
            configured_attempts = hub_settings.get("failover_attempts", role_policy.max_failover_attempts)
            max_attempts = min(int(configured_attempts), len(candidate_profiles))
        else:
            max_attempts = 1

        from .model_registry import ModelRegistry, RouterSelectionTrace
        registry = ModelRegistry.get()
        role_reqs = registry.get_role_requirements(target_role)

        for pid in candidate_profiles:
            if attempts >= max_attempts:
                break

            pconfig = self.config.get_profile(pid)
            if not pconfig:
                evaluated_candidates.append({
                    "profile_id": pid,
                    "provider": "unknown",
                    "status": "skipped",
                    "reason": "Profile configuration not found",
                })
                continue
            if not pconfig.enabled:
                evaluated_candidates.append({
                    "profile_id": pid,
                    "provider": pconfig.provider,
                    "status": "skipped",
                    "reason": "Profile is disabled (cold spare)",
                })
                continue

            # Model selection with capability evaluation & same-account fallback support
            selected_model = requested_model
            prefer_same_account = bool(hub_settings.get("prefer_same_account_model_fallback", False)) or getattr(role_policy, "allow_model_fallback", False)

            # Determine viable model list for this profile
            viable_models = list(pconfig.preferred_models) if pconfig.preferred_models else []
            if requested_model and requested_model not in viable_models:
                viable_models.insert(0, requested_model)
            if role_policy.default_model and role_policy.default_model not in viable_models:
                viable_models.append(role_policy.default_model)

            # Score and filter models by capability
            scored_candidates: list[tuple[float, str]] = []
            for m_candidate in viable_models:
                m_desc = registry.get_model(m_candidate)
                if m_desc:
                    from .quota_collector import AccountQuotaService

                    quota_remaining = AccountQuotaService.get().remaining_for_model(
                        pconfig.provider,
                        pid,
                        m_desc.family,
                    )
                    ok, score, _ = registry.evaluate_model_score(
                        m_desc,
                        role_reqs,
                        quota_remaining_percent=quota_remaining,
                    )
                    if ok:
                        scored_candidates.append((score, m_candidate))
                else:
                    # Model not in registry -> allow with baseline score
                    scored_candidates.append((0.5, m_candidate))

            scored_candidates.sort(key=lambda x: x[0], reverse=True)

            # Find first healthy model
            chosen_model = None
            if requested_model and self.health.is_healthy(pid, requested_model):
                chosen_model = requested_model
            elif prefer_same_account and scored_candidates:
                for _, m_cand in scored_candidates:
                    if m_cand != requested_model and self.health.is_healthy(pid, m_cand):
                        chosen_model = m_cand
                        logger.info("Router same-account model fallback for %s: %s -> %s", pid, requested_model, m_cand)
                        break
            elif not requested_model and scored_candidates:
                for _, m_cand in scored_candidates:
                    if self.health.is_healthy(pid, m_cand):
                        chosen_model = m_cand
                        break
            elif self.health.is_healthy(pid, None):
                chosen_model = requested_model or (scored_candidates[0][1] if scored_candidates else "default")

            if not chosen_model:
                failover_trail.append({
                    "profile_id": pid,
                    "provider": pconfig.provider,
                    "status": "skipped_unhealthy",
                })
                evaluated_candidates.append({
                    "profile_id": pid,
                    "provider": pconfig.provider,
                    "status": "rejected",
                    "reason": "All models in quota exhaustion or cooldown",
                })
                continue

            selected_model = chosen_model

            # Try to acquire concurrency lease
            if not self.leases.acquire(pid, pconfig.max_concurrency):
                failover_trail.append({
                    "profile_id": pid,
                    "provider": pconfig.provider,
                    "status": "skipped_concurrency_limit",
                })
                evaluated_candidates.append({
                    "profile_id": pid,
                    "provider": pconfig.provider,
                    "status": "rejected",
                    "reason": f"Concurrency limit reached ({pconfig.max_concurrency}/{pconfig.max_concurrency} active leases)",
                })
                continue

            attempts += 1
            adapter = get_adapter(pconfig.provider)

            try:
                # Prepare profile-specific model selection
                exec_request = dict(request)
                if "timeout" not in exec_request:
                    from antigravity_provider.router.settings_service import get_hub_settings
                    exec_request["timeout"] = get_hub_settings().get("model_timeout_seconds", 60)

                if selected_model and selected_model != "default":
                    exec_request["model"] = selected_model
                elif pconfig.preferred_models:
                    exec_request["model"] = pconfig.preferred_models[0]
                elif role_policy.default_model:
                    exec_request["model"] = role_policy.default_model

                t0 = time.time()
                response = adapter.invoke(pconfig, exec_request)
                elapsed = time.time() - t0

                # Check if response payload contains an error object
                if isinstance(response, dict) and "error" in response:
                    err_val = response["error"]
                    raise RuntimeError(f"Provider Error: {err_val}")

                # Success!
                self.health.mark_success(pid, exec_request.get("model"))
                self.leases.release(pid)

                # Record successful evaluation in matrix
                evaluated_candidates.append({
                    "profile_id": pid,
                    "provider": pconfig.provider,
                    "status": "selected",
                    "reason": f"Selected for execution with model '{exec_request.get('model')}'",
                    "score": scored_candidates[0][0] if scored_candidates else 0.5,
                    "models_evaluated": [m[1] for m in scored_candidates],
                })

                # Record in TelemetryService (extract usage ONLY if reported by provider)
                prompt_tok = None
                comp_tok = None
                tot_tok = None
                if isinstance(response, dict) and isinstance(response.get("usage"), dict):
                    u = response["usage"]
                    prompt_tok = u.get("prompt_tokens") or u.get("input_tokens")
                    comp_tok = u.get("completion_tokens") or u.get("output_tokens")
                    tot_tok = u.get("total_tokens")
                    if tot_tok is None and prompt_tok is not None and comp_tok is not None:
                        tot_tok = prompt_tok + comp_tok

                try:
                    from .telemetry_service import TelemetryService
                    TelemetryService.get().record_call(
                        role=target_role,
                        profile_id=pid,
                        provider=pconfig.provider,
                        model=exec_request.get("model") or selected_model or "",
                        outcome="failover" if failover_trail else "success",
                        latency_seconds=elapsed,
                        prompt_tokens=prompt_tok,
                        completion_tokens=comp_tok,
                        total_tokens=tot_tok,
                        failover_count=attempts - 1,
                        error_category=None,
                    )
                except Exception:
                    pass

                # Set / update session affinity
                if target_session and affinity_enabled:
                    self.affinity.set_affinity(target_session, target_role, pid, exec_request.get("model"))

                # Selection trace
                selection_trace = {
                    "role": target_role,
                    "required_capabilities": role_reqs.required_capabilities,
                    "candidates_evaluated": len(candidate_profiles),
                    "selected_profile_id": pid,
                    "selected_provider": pconfig.provider,
                    "selected_model": exec_request.get("model"),
                    "decision_rationale": f"Selected '{pid}' ({pconfig.provider}) for role '{target_role}'. Matched capabilities {role_reqs.required_capabilities}.",
                    "evaluation_matrix": evaluated_candidates,
                }

                # Attach router telemetry
                if isinstance(response, dict):
                    response.setdefault("router_metadata", {
                        "role": target_role,
                        "profile_id": pid,
                        "provider": pconfig.provider,
                        "session_id": target_session,
                        "failover_count": attempts - 1,
                        "elapsed_seconds": round(elapsed, 3),
                        "failover_trail": failover_trail,
                        "selection_trace": selection_trace,
                    })

                if failover_trail:
                    prev_failed = failover_trail[-1]
                    logger.warning(
                        "Router failover for role '%s': switched from failed profile '%s' to '%s'",
                        target_role,
                        prev_failed.get("profile_id"),
                        pid,
                    )
                    try:
                        from antigravity_provider.router.unified_health import EventLogService
                        EventLogService.get().log(
                            category="routing",
                            message=f"Успешное переключение роли '{target_role}': резервный профиль '{pid}'",
                            details=f"Предыдущий профиль '{prev_failed.get('profile_id')}' не ответил: {prev_failed.get('error')}",
                            level="info",
                        )
                    except Exception:
                        pass

                return response

            except Exception as exc:
                self.leases.release(pid)
                err_class = adapter.classify_error(exc)

                # Record failed call in TelemetryService
                try:
                    from .telemetry_service import TelemetryService
                    cat_name = err_class.category.value if hasattr(err_class.category, "value") else str(err_class.category)
                    TelemetryService.get().record_call(
                        role=target_role,
                        profile_id=pid,
                        provider=pconfig.provider,
                        model=exec_request.get("model") or requested_model or "",
                        outcome=cat_name,
                        latency_seconds=time.time() - t0,
                        prompt_tokens=None,
                        completion_tokens=None,
                        total_tokens=None,
                        failover_count=len(failover_trail),
                        error_category=cat_name,
                    )
                except Exception:
                    pass

                if err_class.category == ErrorCategory.QUOTA_EXHAUSTED:
                    self.health.mark_quota_exhausted(
                        profile_id=pid,
                        model_name=exec_request.get("model") or requested_model,
                        duration=err_class.reset_duration_seconds,
                        reason=err_class.message,
                    )
                    # Immediate update to QuotaSnapshot
                    try:
                        from .quota_collector import AccountQuotaService
                        AccountQuotaService.get().record_runtime_quota_error(
                            provider=pconfig.provider,
                            profile_id=pid,
                            model=exec_request.get("model") or requested_model or "",
                            error_msg=err_class.message,
                            reset_seconds=err_class.reset_duration_seconds,
                        )
                    except Exception:
                        pass
                elif err_class.category == ErrorCategory.RATE_LIMITED:
                    self.health.mark_rate_limited(
                        profile_id=pid,
                        model_name=exec_request.get("model") or requested_model,
                        duration=err_class.retry_delay_seconds,
                        reason=err_class.message,
                    )
                elif err_class.category == ErrorCategory.AUTH_REQUIRED:
                    self.health.mark_auth_required(profile_id=pid, reason=err_class.message)

                failover_trail.append({
                    "profile_id": pid,
                    "provider": pconfig.provider,
                    "status": "failed",
                    "category": err_class.category,
                    "error": err_class.message[:200],
                })
                evaluated_candidates.append({
                    "profile_id": pid,
                    "provider": pconfig.provider,
                    "status": "failed",
                    "reason": f"Execution failed ({err_class.category}): {err_class.message[:150]}",
                })

                try:
                    from antigravity_provider.router.unified_health import EventLogService
                    EventLogService.get().log(
                        category="routing",
                        message=f"Переключение маршрута для роли '{target_role}': сбой профиля '{pid}' ({pconfig.provider})",
                        details=f"Причина: {err_class.message[:180]}",
                        level="warning",
                    )
                except Exception:
                    pass

                # If non-fatal and more profiles remain in chain, continue loop (failover!)
                continue

        # All attempts in chain failed
        summary_errors = "; ".join(f"[{t.get('profile_id')}]: {t.get('error', t.get('status'))}" for t in failover_trail)
        selection_trace = {
            "role": target_role,
            "required_capabilities": role_reqs.required_capabilities,
            "candidates_evaluated": len(candidate_profiles),
            "selected_profile_id": None,
            "selected_provider": None,
            "selected_model": None,
            "decision_rationale": f"All {attempts} candidate profiles failed or were rejected.",
            "evaluation_matrix": evaluated_candidates,
        }
        try:
            from antigravity_provider.router.unified_health import EventLogService
            EventLogService.get().log(
                category="routing",
                message=f"Все маршруты для роли '{target_role}' исчерпаны ({attempts} попыток)",
                details=summary_errors,
                level="error",
            )
        except Exception:
            pass

        return {
            "id": f"router-fail-{int(time.time())}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": requested_model or "router-failover",
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": (
                            f"⚠️ Hermes Router Failover Exhausted for role '{target_role}'.\n"
                            f"All {attempts} attempted provider profiles failed or exceeded quota.\n"
                            f"Trail: {summary_errors}\n"
                            "Use `hermes router status` to inspect quota reset times or clear cooldowns."
                        ),
                    },
                    "finish_reason": "error",
                }
            ],
            "router_error": True,
            "failover_trail": failover_trail,
            "selection_trace": selection_trace,
        }


# Global singleton instance for runtime middleware
_ROUTER_ENGINE: Optional[RouterEngine] = None


def get_router_engine() -> RouterEngine:
    global _ROUTER_ENGINE
    if _ROUTER_ENGINE is None:
        _ROUTER_ENGINE = RouterEngine()
    return _ROUTER_ENGINE
