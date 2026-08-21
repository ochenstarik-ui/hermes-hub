"""Hermes Hub — Unified Health Model & Presentation Layer.

Single Source of Truth for:
- ProfileViewModel
- SystemReadiness
- AgentViewModel
- ProviderSummary
- RolePipeline
- EventLogService
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from antigravity_provider.router.router_config import RouterConfig, load_router_config
from antigravity_provider.router.profile_manager import ProfileAuthManager
from antigravity_provider.router.auto_assigner import AutoAssigner
from antigravity_provider.router.router_engine import get_router_engine
from antigravity_provider.router.health_tracker import (
    HEALTHY,
    QUOTA_EXHAUSTED,
    RATE_LIMITED,
    COOLDOWN,
    AUTH_REQUIRED as HT_AUTH_REQUIRED,
    DISABLED as HT_DISABLED,
    UNHEALTHY as HT_UNHEALTHY,
    extract_model_family,
)

logger = logging.getLogger("hermes.hub.unified_health")

# ── Normalized Status Constants ──
STATUS_HEALTHY = "healthy"
STATUS_QUOTA_LOW = "quota_low"
STATUS_QUOTA_EXHAUSTED = "quota_exhausted"
STATUS_COOLDOWN = "cooldown"
STATUS_RATE_LIMITED = "rate_limited"
STATUS_NOT_CONFIGURED = "not_configured"
STATUS_AUTH_REQUIRED = "auth_required"
STATUS_AUTH_EXPIRED = "auth_expired"
STATUS_DISABLED = "disabled"
STATUS_COLD_SPARE = "cold_spare"
STATUS_UNHEALTHY = "unhealthy"
STATUS_NOT_TESTED = "not_tested"

# ── System Readiness Levels ──
READINESS_HEALTHY = "healthy"
READINESS_LIMITED = "limited"
READINESS_DEGRADED = "degraded"
READINESS_CRITICAL = "critical"


@dataclass
class ModelFamilyHealth:
    family: str
    display_name: str
    status: str
    status_label_ru: str
    cooldown_remaining_sec: int = 0
    reset_at: Optional[float] = None
    reason: Optional[str] = None


@dataclass
class ProfileViewModel:
    profile_id: str
    display_name: str
    account_identity: str
    provider: str
    provider_display_name: str
    assigned_roles: List[str]
    primary_role: Optional[str]
    is_main_account: bool
    is_main_orchestrator: bool
    auth_state: str  # AUTHENTICATED | AUTH_REQUIRED | AUTH_EXPIRED | NOT_CONFIGURED
    health_state: str
    health_label_ru: str
    model_states: Dict[str, ModelFamilyHealth]
    cooldown_remaining_sec: int
    last_checked_at: Optional[str]
    enabled: bool
    is_cold_spare: bool
    is_empty_slot: bool
    email: str = ""
    plan: str = "Тариф: неизвестен"
    plan_code: str = "UNKNOWN"
    plan_source: str = "unknown"
    quota_snapshot: Optional[Any] = None
    preferred_models: List[str] = field(default_factory=list)
    active_leases: int = 0


@dataclass
class AgentViewModel:
    role_id: str
    role_name_ru: str
    role_description_ru: str
    assigned_profile_id: Optional[str]
    assigned_display_name: Optional[str]
    provider: str
    provider_display_name: str
    model: str
    account_identity: str
    routing_position: str  # Primary | Fallback 1 | Fallback 2
    status: str
    status_label_ru: str
    is_active: bool
    is_main_orchestrator: bool
    cooldown_remaining_sec: int = 0
    session_id: Optional[str] = None
    active_quota_status: str = "healthy"
    active_quota_label: str = ""


@dataclass
class PipelineNode:
    profile_id: str
    display_name: str
    provider: str
    model: str
    status: str
    status_label_ru: str
    is_active: bool
    cooldown_remaining_sec: int = 0
    account_identity: str = ""
    quota_status: str = "healthy"
    failover_reason: Optional[str] = None


@dataclass
class RolePipeline:
    role_id: str
    role_name_ru: str
    default_model: str
    max_failover: int
    session_affinity: bool
    active_profile_id: str
    nodes: List[PipelineNode]


@dataclass
class ProviderSummary:
    provider_id: str
    provider_name: str
    total_slots: int
    connected_count: int
    online_count: int
    auth_required_count: int
    quota_exhausted_count: int
    cold_spare_count: int
    discovered_models: List[str]
    last_refresh_at: str


@dataclass
class SystemReadiness:
    state: str  # HEALTHY | LIMITED | DEGRADED | CRITICAL
    title_ru: str
    summary_ru: str
    roles_ready_count: int
    total_roles: int
    accounts_connected_count: int
    total_accounts: int
    providers_ready_count: int
    total_providers: int
    warnings: List[str] = field(default_factory=list)


# ═══════════════════════════════════════════════════════════════
#  Event Log Service
# ═══════════════════════════════════════════════════════════════

@dataclass
class HubEvent:
    timestamp: str
    category: str  # account | quota | routing | auth | system
    message: str
    details: Optional[str] = None
    level: str = "info"  # info | warning | error | success


class EventLogService:
    _instance: Optional[EventLogService] = None
    _instance_lock = threading.Lock()
    _events: List[HubEvent] = []
    _lock = threading.RLock()

    def __init__(self):
        self._load_recent()

    @classmethod
    def get(cls) -> EventLogService:
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def log(self, category: str, message: str, details: Optional[str] = None, level: str = "info"):
        ts = time.strftime("%H:%M:%S")
        event = HubEvent(timestamp=ts, category=category, message=message, details=details, level=level)
        with self._lock:
            self._events.append(event)
            # Cap at last 200 events
            if len(self._events) > 200:
                self._events = self._events[-200:]
        # Append to hermes-hub.log outside lock
        self._append_to_file(event)

    def get_events(self, limit: int = 50, category: Optional[str] = None) -> List[HubEvent]:
        with self._lock:
            evs = self._events
            if category:
                evs = [e for e in evs if e.category == category]
            return list(reversed(evs[-limit:]))

    def _append_to_file(self, event: HubEvent):
        try:
            from antigravity_provider import paths
            from antigravity_provider.sanitizer import sanitize_text
            log_file = paths.get_log_file()
            clean_msg = sanitize_text(event.message)
            clean_details = sanitize_text(event.details) if event.details else None
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(f"[{event.timestamp}] [{event.category.upper()}] [{event.level.upper()}] {clean_msg}\n")
                if clean_details:
                    f.write(f"    Details: {clean_details}\n")
        except Exception:
            pass

    def _load_recent(self):
        # Initialize with baseline startup event
        self.log("system", "Hermes Hub запущен в нативном режиме Windows.", level="info")


# ═══════════════════════════════════════════════════════════════
#  Unified Health Service
# ═══════════════════════════════════════════════════════════════

class UnifiedHealthService:
    _instance: Optional[UnifiedHealthService] = None
    _instance_lock = threading.Lock()

    def __init__(self):
        self._last_scan_time: Optional[float] = None
        self._cached_profiles: Dict[str, ProfileViewModel] = {}
        self._lock = threading.RLock()

    @classmethod
    def get(cls) -> UnifiedHealthService:
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def scan_all(
        self,
        force: bool = False,
        profile_id: Optional[str] = None,
    ) -> Dict[str, List[ProfileViewModel]]:
        """Query router config, ProfileAuthManager, HealthTracker and build unified presentation models (cached)."""
        with self._lock:
            if (
                profile_id is None
                and not force
                and self._cached_profiles
                and self._last_scan_time
                and (time.time() - self._last_scan_time < 30)
            ):
                # Return cached by provider instantly without disk I/O
                result: Dict[str, List[ProfileViewModel]] = {"antigravity": [], "openai-codex": [], "opencode-go": []}
                for p in self._cached_profiles.values():
                    if p.provider in result:
                        result[p.provider].append(p)
                    else:
                        result[p.provider] = [p]
                return result

            config = load_router_config()
            engine = get_router_engine()
            main_ag = ProfileAuthManager.get_main_profile("antigravity")
            main_codex = ProfileAuthManager.get_main_profile("openai-codex")

            role_assignments: Dict[str, List[str]] = {}
            for rname, rpol in config.roles.items():
                for idx, pid in enumerate(rpol.preferred_chain):
                    tag = f"{rname} (primary)" if idx == 0 else f"{rname} (fallback {idx})"
                    role_assignments.setdefault(pid, []).append(tag)

            orch_primary = config.roles.get("orchestrator", None)
            orch_primary_id = orch_primary.preferred_chain[0] if orch_primary and orch_primary.preferred_chain else ""

            now = time.time()
            now_str = time.strftime("%H:%M:%S")
            if profile_id is None:
                self._last_scan_time = now

            result: Dict[str, List[ProfileViewModel]] = {
                "antigravity": [],
                "openai-codex": [],
                "opencode-go": [],
            }

            for pid, pcfg in sorted(config.profiles.items()):
                if profile_id is not None and pid != profile_id:
                    continue
                prov = pcfg.provider
                if prov not in result:
                    result[prov] = []

                precord = engine.health.get_or_create(pid)
                is_main_acc = (pid == main_ag and prov == "antigravity") or (pid == main_codex and prov == "openai-codex")
                is_main_orch = (pid == orch_primary_id)

                # Auth status check
                auth_status = ProfileAuthManager.get_profile_status(prov, pid)
                is_authenticated = auth_status.get("authenticated", False)
                auth_error = auth_status.get("error")

                is_cold = "cold" in pid.lower() or not pcfg.enabled
                is_empty = not is_authenticated and not auth_error

                # Identity determination
                if is_authenticated:
                    auth_state = "AUTHENTICATED"
                    identity = (
                        auth_status.get("email_masked")
                        or auth_status.get("account_id_masked")
                        or "Подключён"
                    )
                elif auth_error:
                    auth_state = "AUTH_EXPIRED"
                    identity = "Требуется повторная авторизация"
                else:
                    auth_state = "NOT_CONFIGURED"
                    identity = "Холодный резерв" if is_cold else "Аккаунт не добавлен"

                # Calculate per-family model states
                model_states: Dict[str, ModelFamilyHealth] = {}
                max_cd = 0

                for pref_m in pcfg.preferred_models:
                    fam = extract_model_family(pref_m)
                    frec = precord.families.get(fam)

                    f_cd = 0
                    if is_authenticated and frec and frec.reset_at and frec.reset_at > now:
                        f_cd = int(frec.reset_at - now)
                        max_cd = max(max_cd, f_cd)

                    if not is_authenticated:
                        if auth_error:
                            f_status = STATUS_AUTH_EXPIRED
                            f_lbl = "Требуется авторизация"
                        else:
                            f_status = STATUS_NOT_CONFIGURED
                            f_lbl = "Аккаунт не добавлен"
                    elif f_cd > 0:
                        f_status = STATUS_QUOTA_EXHAUSTED
                        f_lbl = f"Квота исчерпана ({f_cd}s)"
                    elif frec and frec.state == QUOTA_EXHAUSTED:
                        f_status = STATUS_QUOTA_EXHAUSTED
                        f_lbl = "Квота исчерпана"
                    elif frec and frec.state == RATE_LIMITED:
                        f_status = STATUS_RATE_LIMITED
                        f_lbl = "Лимит запросов"
                    elif frec and frec.state == HT_UNHEALTHY:
                        f_status = STATUS_UNHEALTHY
                        f_lbl = "Ошибка"
                    else:
                        f_status = STATUS_HEALTHY
                        f_lbl = "Работает"

                    model_states[fam] = ModelFamilyHealth(
                        family=fam,
                        display_name=pref_m,
                        status=f_status,
                        status_label_ru=f_lbl,
                        cooldown_remaining_sec=f_cd,
                        reset_at=frec.reset_at if frec and is_authenticated else None,
                        reason=frec.reason if frec and is_authenticated else None,
                    )

                # UNIFIED HEALTH DETERMINATION (Strict Priority Resolver)
                # 1. Disabled
                if not pcfg.enabled:
                    health_state = STATUS_DISABLED
                    health_lbl = "Отключён"
                # 2. No credentials -> NOT_CONFIGURED (never QUOTA_EXHAUSTED or HEALTHY)
                elif not is_authenticated:
                    if auth_error:
                        health_state = STATUS_AUTH_EXPIRED
                        health_lbl = "Требуется повторная авторизация"
                    elif is_cold:
                        health_state = STATUS_COLD_SPARE
                        health_lbl = "Холодный резерв"
                    else:
                        health_state = STATUS_NOT_CONFIGURED
                        health_lbl = "Аккаунт не добавлен"
                # 3. Active Cooldown / Quota exhausted
                elif max_cd > 0 or precord.overall_state == QUOTA_EXHAUSTED:
                    health_state = STATUS_QUOTA_EXHAUSTED
                    health_lbl = "Квота исчерпана"
                # 4. Rate limited
                elif precord.overall_state == RATE_LIMITED:
                    health_state = STATUS_RATE_LIMITED
                    health_lbl = "Лимит запросов"
                # 5. Unhealthy probe error
                elif precord.overall_state == HT_UNHEALTHY:
                    health_state = STATUS_UNHEALTHY
                    health_lbl = "Ошибка"
                # 6. Live healthy
                else:
                    health_state = STATUS_HEALTHY
                    health_lbl = "Работает"

                from .quota_collector import AccountQuotaService
                ident = AccountQuotaService.get().get_identity(prov, pid)
                snap = AccountQuotaService.get().get_snapshot(prov, pid)

                display_name, log_role, tier = AutoAssigner.get_display_name_and_role(pid)
                prov_display = {
                    "antigravity": "Google Antigravity",
                    "openai-codex": "OpenAI Codex",
                    "codex": "OpenAI Codex",
                    "opencode-go": "OpenCode Go",
                    "opencode": "OpenCode Go",
                    "claude": "Claude",
                    "anthropic": "Claude",
                    "grok": "Grok",
                    "xai": "Grok",
                }.get(prov.lower(), prov)

                vm = ProfileViewModel(
                    profile_id=pid,
                    display_name=display_name,
                    account_identity=ident.primary_identifier() if is_authenticated else identity,
                    provider=prov,
                    provider_display_name=prov_display,
                    assigned_roles=role_assignments.get(pid, [log_role]),
                    primary_role=log_role,
                    is_main_account=is_main_acc,
                    is_main_orchestrator=is_main_orch,
                    auth_state=auth_state,
                    health_state=health_state,
                    health_label_ru=health_lbl,
                    model_states=model_states,
                    cooldown_remaining_sec=max_cd,
                    last_checked_at=now_str,
                    enabled=pcfg.enabled,
                    is_cold_spare=is_cold,
                    is_empty_slot=is_empty,
                    email=ident.email or "",
                    plan=ident.plan.display_name if is_authenticated else "Тариф: неизвестен",
                    plan_code=ident.plan.code if is_authenticated else "UNKNOWN",
                    plan_source=ident.plan.source if is_authenticated else "unknown",
                    quota_snapshot=snap,
                    preferred_models=pcfg.preferred_models,
                    active_leases=precord.active_leases,
                )

                result.setdefault(prov, []).append(vm)
                self._cached_profiles[pid] = vm

            return result

    def refresh_profile(self, provider: str, profile_id: str) -> Optional[ProfileViewModel]:
        """Rebuild exactly one profile ViewModel after an auth or quota change."""
        profiles = self.scan_all(force=True, profile_id=profile_id).get(provider, [])
        return next((profile for profile in profiles if profile.profile_id == profile_id), None)

    def get_cached_profiles(self) -> Dict[str, List[ProfileViewModel]]:
        """Return currently cached profiles grouped by provider without disk I/O."""
        with self._lock:
            if not self._cached_profiles:
                return self.scan_all(force=False)
            res: Dict[str, List[ProfileViewModel]] = {}
            for p in self._cached_profiles.values():
                res.setdefault(p.provider, []).append(p)
            return res

    def get_profile_status(self, provider: str, profile_id: str) -> Dict[str, Any]:
        """Return authentication status for a specific profile."""
        with self._lock:
            p = self._cached_profiles.get(profile_id)
            if p:
                return {
                    "authenticated": p.auth_state == "AUTHENTICATED",
                    "auth_mode": "oauth" if "ChatGPT" in p.account_identity or "Google" in p.provider_display_name or "Claude" in p.provider_display_name else "api_key",
                    "email": p.email or p.account_identity,
                    "profile_id": profile_id,
                }
        return ProfileAuthManager.get_profile_status(provider, profile_id)

    def get_system_readiness(self) -> SystemReadiness:
        """Calculate aggregate system readiness based on real routing availability."""
        profiles_by_prov = self.scan_all(force=False)
        config = load_router_config()

        total_roles = len(config.roles)
        roles_ready = 0
        degraded_roles = 0
        dead_roles = 0
        warnings: List[str] = []

        total_accounts = sum(len(profs) for profs in profiles_by_prov.values())
        connected_accounts = sum(
            1 for profs in profiles_by_prov.values() for p in profs if p.auth_state == "AUTHENTICATED"
        )

        providers_online = sum(
            1 for profs in profiles_by_prov.values() if any(p.health_state == STATUS_HEALTHY for p in profs)
        )

        for rname, rpol in config.roles.items():
            chain = rpol.preferred_chain
            if not chain:
                dead_roles += 1
                warnings.append(f"Роль '{rname}' не имеет настроенных профилей.")
                continue

            primary_pid = chain[0]
            primary_vm = self._cached_profiles.get(primary_pid)

            if primary_vm and primary_vm.health_state == STATUS_HEALTHY:
                roles_ready += 1
            else:
                # Check if any fallback is healthy
                has_working_fallback = False
                for fb_pid in chain[1:]:
                    fb_vm = self._cached_profiles.get(fb_pid)
                    if fb_vm and fb_vm.health_state == STATUS_HEALTHY:
                        has_working_fallback = True
                        break

                if has_working_fallback:
                    degraded_roles += 1
                    warnings.append(f"Роль '{rname}' работает через резервный аккаунт (Primary недоступен).")
                else:
                    dead_roles += 1
                    warnings.append(f"Роль '{rname}' не имеет рабочих аккаунтов (все исчерпаны).")

        # Determine overall state
        if dead_roles > 0:
            state = READINESS_CRITICAL
            title_ru = "Критическое состояние"
            summary_ru = f"Есть {dead_roles} ролей без рабочего маршрута!"
        elif degraded_roles > 0:
            state = READINESS_DEGRADED
            title_ru = "Деградация маршрутов"
            summary_ru = f"{degraded_roles} ролей работают через резерв."
        elif connected_accounts < total_accounts:
            state = READINESS_LIMITED
            title_ru = "Ограниченная готовность"
            summary_ru = f"{roles_ready}/{total_roles} ролей доступны. {connected_accounts}/{total_accounts} аккаунтов подключено."
        else:
            state = READINESS_HEALTHY
            title_ru = "Полная готовность"
            summary_ru = "Все системы и резервы в строю."

        return SystemReadiness(
            state=state,
            title_ru=title_ru,
            summary_ru=summary_ru,
            roles_ready_count=roles_ready,
            total_roles=total_roles,
            accounts_connected_count=connected_accounts,
            total_accounts=total_accounts,
            providers_ready_count=providers_online,
            total_providers=3,
            warnings=warnings,
        )

    def get_agent_view_models(self) -> List[AgentViewModel]:
        """Build logical agent representations."""
        config = load_router_config()
        self.scan_all(force=False)

        ROLE_META = {
            "orchestrator": ("Главный оркестратор", "Управление командой, планирование, контроль исполнения"),
            "coder-primary": ("Кодер 1", "Основная разработка кода и исправление дефектов"),
            "coder-secondary": ("Кодер 2", "Параллельная разработка и вспомогательные модули"),
            "reviewer": ("Ревьюер", "Независимое fail-closed ревью и валидация diff"),
            "research": ("Исследователь", "Read-only поиск в кодовой базе и сбор фактов"),
            "fast": ("Быстрый агент", "Оперативные вызовы, вспомогательные проверки"),
            "universal": ("Универсальный агент", "Широкий спектр общих задач"),
        }

        agents: List[AgentViewModel] = []

        for rname, rpol in config.roles.items():
            rname_ru, rdesc_ru = ROLE_META.get(rname, (rname, ""))
            chain = rpol.preferred_chain
            if not chain:
                continue

            primary_pid = chain[0]
            pvm = self._cached_profiles.get(primary_pid)

            active_pos = "Primary"
            active_pvm = pvm
            if pvm and pvm.health_state != STATUS_HEALTHY:
                # Find fallback
                for idx, fb_pid in enumerate(chain[1:], start=1):
                    fb_vm = self._cached_profiles.get(fb_pid)
                    if fb_vm and fb_vm.health_state == STATUS_HEALTHY:
                        active_pvm = fb_vm
                        active_pos = f"Fallback {idx}"
                        break

            if active_pvm:
                model_name = active_pvm.preferred_models[0] if active_pvm.preferred_models else "default"
                active_quota_st = "healthy"
                active_quota_lbl = "Доступна"
                if active_pvm.quota_snapshot:
                    bucket = active_pvm.quota_snapshot.get_bucket_for_model(model_name)
                    if bucket:
                        active_quota_st = bucket.status
                        active_quota_lbl = bucket.formatted_remaining()
                elif active_pvm.health_state == STATUS_QUOTA_EXHAUSTED:
                    active_quota_st = "exhausted"
                    active_quota_lbl = "Исчерпана (429)"

                agents.append(AgentViewModel(
                    role_id=rname,
                    role_name_ru=rname_ru,
                    role_description_ru=rdesc_ru,
                    assigned_profile_id=active_pvm.profile_id,
                    assigned_display_name=active_pvm.display_name,
                    provider=active_pvm.provider,
                    provider_display_name=active_pvm.provider_display_name,
                    model=model_name,
                    account_identity=active_pvm.account_identity,
                    routing_position=active_pos,
                    status=active_pvm.health_state,
                    status_label_ru=active_pvm.health_label_ru,
                    is_active=(active_pvm.health_state == STATUS_HEALTHY),
                    is_main_orchestrator=(rname == "orchestrator"),
                    cooldown_remaining_sec=active_pvm.cooldown_remaining_sec,
                    session_id=None,
                    active_quota_status=active_quota_st,
                    active_quota_label=active_quota_lbl,
                ))

        return agents

    def get_provider_summaries(self) -> List[ProviderSummary]:
        """Build real summaries per provider."""
        profiles_by_prov = self.scan_all(force=False)
        summaries: List[ProviderSummary] = []
        now_str = time.strftime("%H:%M:%S")

        for prov_id, prov_name in [
            ("antigravity", "Google Antigravity"),
            ("openai-codex", "OpenAI Codex"),
            ("opencode-go", "OpenCode Go"),
            ("claude", "Claude"),
            ("grok", "Grok"),
        ]:
            profs = profiles_by_prov.get(prov_id, [])
            total = len(profs)
            connected = sum(1 for p in profs if p.auth_state == "AUTHENTICATED")
            online = sum(1 for p in profs if p.health_state == STATUS_HEALTHY)
            auth_req = sum(1 for p in profs if p.auth_state in ("AUTH_REQUIRED", "AUTH_EXPIRED"))
            quota = sum(1 for p in profs if p.health_state in (STATUS_QUOTA_EXHAUSTED, STATUS_RATE_LIMITED))
            cold = sum(1 for p in profs if p.is_cold_spare)

            # Extract unique models
            models_set = set()
            for p in profs:
                for m in p.preferred_models:
                    models_set.add(m)

            summaries.append(ProviderSummary(
                provider_id=prov_id,
                provider_name=prov_name,
                total_slots=total,
                connected_count=connected,
                online_count=online,
                auth_required_count=auth_req,
                quota_exhausted_count=quota,
                cold_spare_count=cold,
                discovered_models=sorted(list(models_set)),
                last_refresh_at=now_str,
            ))

        return summaries

    def get_routing_pipelines(self) -> Dict[str, RolePipeline]:
        """Build visual pipeline representation per role without redundant disk scans."""
        config = load_router_config()
        self.scan_all(force=False)
        pipelines: Dict[str, RolePipeline] = {}

        ROLE_NAMES = {
            "orchestrator": "Главный оркестратор",
            "coder-primary": "Кодер 1 (Primary)",
            "coder-secondary": "Кодер 2 (Secondary)",
            "reviewer": "Ревьюер",
            "research": "Исследователь",
            "fast": "Быстрый агент",
            "universal": "Универсальный агент",
        }

        for rname, rpol in config.roles.items():
            nodes: List[PipelineNode] = []
            active_pid = ""
            for pid in rpol.preferred_chain:
                pvm = self._cached_profiles.get(pid)
                if pvm and pvm.health_state == STATUS_HEALTHY:
                    active_pid = pid
                    break

            for idx, pid in enumerate(rpol.preferred_chain):
                pvm = self._cached_profiles.get(pid)
                if pvm:
                    is_act = (pid == active_pid)
                    failover_reason = None
                    if not is_act and active_pid and pid in rpol.preferred_chain:
                        active_idx = rpol.preferred_chain.index(active_pid)
                        if idx < active_idx:
                            if pvm.health_state == STATUS_QUOTA_EXHAUSTED:
                                failover_reason = "Исчерпана квота (429)"
                            elif pvm.health_state in (STATUS_AUTH_REQUIRED, STATUS_AUTH_EXPIRED):
                                failover_reason = "Требуется авторизация"
                            elif pvm.health_state == STATUS_DISABLED:
                                failover_reason = "Отключён"
                            else:
                                failover_reason = f"Недоступен ({pvm.health_label_ru})"

                    quota_st = "healthy"
                    if pvm.quota_snapshot:
                        bucket = pvm.quota_snapshot.get_bucket_for_model(
                            pvm.preferred_models[0] if pvm.preferred_models else "default"
                        )
                        if bucket:
                            quota_st = bucket.status
                    elif pvm.health_state == STATUS_QUOTA_EXHAUSTED:
                        quota_st = "exhausted"

                    nodes.append(PipelineNode(
                        profile_id=pid,
                        display_name=pvm.display_name,
                        provider=pvm.provider_display_name,
                        model=pvm.preferred_models[0] if pvm.preferred_models else "default",
                        status=pvm.health_state,
                        status_label_ru=pvm.health_label_ru,
                        is_active=is_act,
                        cooldown_remaining_sec=pvm.cooldown_remaining_sec,
                        account_identity=pvm.account_identity,
                        quota_status=quota_st,
                        failover_reason=failover_reason,
                    ))

            pipelines[rname] = RolePipeline(
                role_id=rname,
                role_name_ru=ROLE_NAMES.get(rname, rname),
                default_model=rpol.default_model or "auto",
                max_failover=rpol.max_failover_attempts,
                session_affinity=rpol.session_affinity_enabled,
                active_profile_id=active_pid,
                nodes=nodes,
            )

        return pipelines
