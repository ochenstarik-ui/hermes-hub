"""Core routing engine for Hermes multi-provider account router."""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional, Tuple

from .adapters import get_adapter
from .adapters.base_adapter import ErrorCategory
from .health_tracker import HealthTracker, extract_model_family
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
        self.affinity = affinity or SessionAffinityTracker()
        self.leases = leases or LeaseManager()

    def reload_config(self) -> None:
        self.config = load_router_config()

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
        family = extract_model_family(requested_model)

        # 1. Check Session Affinity
        candidate_profiles: list[str] = []
        if target_session and role_policy.session_affinity_enabled:
            aff_rec = self.affinity.get_affinity(target_session)
            if aff_rec and aff_rec.profile_id in self.config.profiles:
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
        attempts = 0
        max_attempts = min(role_policy.max_failover_attempts, len(candidate_profiles))

        for pid in candidate_profiles:
            if attempts >= max_attempts:
                break

            pconfig = self.config.get_profile(pid)
            if not pconfig or not pconfig.enabled:
                continue

            # Check health and quota
            if not self.health.is_healthy(pid, requested_model):
                failover_trail.append({
                    "profile_id": pid,
                    "provider": pconfig.provider,
                    "status": "skipped_unhealthy",
                })
                continue

            # Try to acquire concurrency lease
            if not self.leases.acquire(pid, pconfig.max_concurrency):
                failover_trail.append({
                    "profile_id": pid,
                    "provider": pconfig.provider,
                    "status": "skipped_concurrency_limit",
                })
                continue

            attempts += 1
            adapter = get_adapter(pconfig.provider)

            try:
                # Prepare profile-specific model selection
                exec_request = dict(request)
                if not exec_request.get("model") or exec_request["model"] == "default":
                    if pconfig.preferred_models:
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

                # Set / update session affinity
                if target_session and role_policy.session_affinity_enabled:
                    self.affinity.set_affinity(target_session, target_role, pid, exec_request.get("model"))

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
                    })

                return response

            except Exception as exc:
                self.leases.release(pid)
                err_class = adapter.classify_error(exc)

                if err_class.category == ErrorCategory.QUOTA_EXHAUSTED:
                    self.health.mark_quota_exhausted(
                        profile_id=pid,
                        model_name=requested_model,
                        duration=err_class.reset_duration_seconds,
                        reason=err_class.message,
                    )
                elif err_class.category == ErrorCategory.RATE_LIMITED:
                    self.health.mark_rate_limited(
                        profile_id=pid,
                        model_name=requested_model,
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

                # If non-fatal and more profiles remain in chain, continue loop (failover!)
                continue

        # All attempts in chain failed
        summary_errors = "; ".join(f"[{t.get('profile_id')}]: {t.get('error', t.get('status'))}" for t in failover_trail)
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
        }


# Global singleton instance for runtime middleware
_ROUTER_ENGINE: Optional[RouterEngine] = None


def get_router_engine() -> RouterEngine:
    global _ROUTER_ENGINE
    if _ROUTER_ENGINE is None:
        _ROUTER_ENGINE = RouterEngine()
    return _ROUTER_ENGINE
