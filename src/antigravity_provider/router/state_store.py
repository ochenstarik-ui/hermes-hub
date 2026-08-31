"""Hermes Hub — Unified HubStateStore & Immutable HubSnapshot Layer.

Provides normalized state management, single-scan snapshot generation,
request deduplication, generation tracking, and delta event publishing.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field, replace
from typing import Any, Dict, List, Optional, Tuple

from antigravity_provider.router.event_bus import (
    EventBus,
    EVENT_ACCOUNT_UPDATED,
    EVENT_ACCOUNT_ADDED,
    EVENT_ACCOUNT_REMOVED,
    EVENT_ACCOUNT_AUTH_CHANGED,
    EVENT_QUOTA_UPDATED,
    EVENT_ROUTING_UPDATED,
    EVENT_AGENT_UPDATED,
    EVENT_SYSTEM_READINESS_CHANGED,
    EVENT_REFRESH_STARTED,
    EVENT_REFRESH_COMPLETED,
    EVENT_REFRESH_FAILED,
)
from antigravity_provider.router.unified_health import (
    UnifiedHealthService,
    ProfileViewModel,
    SystemReadiness,
    AgentViewModel,
    ProviderSummary,
    RolePipeline,
)
from antigravity_provider.router.quota_collector import AccountQuotaService
from antigravity_provider.router.router_config import load_router_config
from antigravity_provider.router.auto_assigner import AutoAssigner

logger = logging.getLogger("hermes.router.state_store")


@dataclass(frozen=True)
class HubSnapshot:
    """Immutable normalized snapshot of the entire Hermes Hub state at a specific generation."""
    generation: int
    seq: int
    timestamp: float
    profiles_by_provider: Dict[str, List[ProfileViewModel]]
    all_profiles: Dict[str, ProfileViewModel]
    readiness: SystemReadiness
    agents: List[AgentViewModel]
    providers: List[ProviderSummary]
    routing: Dict[str, RolePipeline]
    quotas: Dict[str, Any]
    metrics: Dict[str, Any] = field(default_factory=dict)
    is_stale: bool = False
    workflow: Dict[str, Any] = field(default_factory=dict)

    def get_profile(self, profile_id: str) -> Optional[ProfileViewModel]:
        return self.all_profiles.get(profile_id)

    def get_provider_profiles(self, provider: str) -> List[ProfileViewModel]:
        return list(self.profiles_by_provider.get(provider, []))

    def get_role_pipeline(self, role_id: str) -> Optional[RolePipeline]:
        return self.routing.get(role_id)


class HubStateStore:
    """Thread-safe central state store managing the canonical HubSnapshot and delta updates."""

    _instance: Optional[HubStateStore] = None
    _instance_lock = threading.Lock()

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._removed_accounts: set[str] = set()
        self._generation: int = 0
        self._current_snapshot: Optional[HubSnapshot] = None
        self._pending_refreshes: Dict[str, float] = {}
        self._latest_applied_seq: int = 0
        self._seq_counter: int = 0

        # Observability counters
        self.refresh_runs_total: int = 0
        self.refresh_skipped_total: int = 0
        self.refresh_deduplicated_total: int = 0
        self.refresh_failures_total: int = 0
        self.account_updates_total: int = 0
        self.quota_updates_total: int = 0

    @classmethod
    def get(cls) -> HubStateStore:
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def next_seq(self) -> int:
        with self._lock:
            self._seq_counter += 1
            return self._seq_counter

    def get_snapshot(self) -> HubSnapshot:
        """Return the current cached snapshot. Generates an initial snapshot if none exists."""
        with self._lock:
            if self._current_snapshot is not None:
                if (time.time() - self._current_snapshot.timestamp > 300.0) and not self._current_snapshot.is_stale:
                    self._current_snapshot = replace(self._current_snapshot, is_stale=True)
                # Provider/account scans are intentionally cached, while LIVE
                # workflow checkpoints are small local state and must never lag
                # behind an action until the next expensive provider refresh.
                try:
                    from .workflow_service import WorkflowService

                    live_workflow = WorkflowService.get().snapshot()
                    role_views = {agent.role_id: agent for agent in self._current_snapshot.agents}
                    for workflow_agent in live_workflow.get("agents", []):
                        role_view = role_views.get(workflow_agent.get("role"))
                        generic_name = str(workflow_agent.get("role") or "").replace("-", " ").title()
                        if role_view and workflow_agent.get("name") == generic_name:
                            workflow_agent["name"] = role_view.role_name_ru
                        if role_view and not workflow_agent.get("description"):
                            workflow_agent["description"] = role_view.role_description_ru
                    self._current_snapshot = replace(self._current_snapshot, workflow=live_workflow)
                except Exception:
                    pass
                return self._current_snapshot
        return self.refresh(force_scan=False)

    def refresh(self, force_scan: bool = True, seq: Optional[int] = None) -> HubSnapshot:
        """Build outside the store lock, then atomically apply only the newest result."""
        request_seq = seq if seq is not None else self.next_seq()
        t0 = time.time()

        # Slow disk/provider reads must not hold the store lock. More recent
        # requests may complete while this build is running.
        uh_service = UnifiedHealthService.get()
        profiles_by_prov = uh_service.scan_all(force=force_scan)
        with self._lock:
            removed = set(self._removed_accounts)
        profiles_by_prov = {provider: [p for p in profiles if p.profile_id not in removed] for provider, profiles in profiles_by_prov.items()}
        all_profs = {
            profile.profile_id: profile
            for profiles in profiles_by_prov.values()
            for profile in profiles
        }
        readiness = uh_service.get_system_readiness()
        agents = uh_service.get_agent_view_models()
        providers = uh_service.get_provider_summaries()
        routing = uh_service.get_routing_pipelines()
        quota_service = AccountQuotaService.get()
        quotas_map = {
            profile_id: quota_service.get_snapshot(profile.provider, profile_id)
            for profile_id, profile in all_profs.items()
            if profile.auth_state == "AUTHENTICATED"
        }

        with self._lock:
            self.refresh_runs_total += 1
            if request_seq < self._latest_applied_seq:
                logger.info(
                    "Discarding late refresh result (seq %d < applied %d)",
                    request_seq,
                    self._latest_applied_seq,
                )
                self.refresh_skipped_total += 1
                return self._current_snapshot or self._build_empty_snapshot()

            self._latest_applied_seq = request_seq
            self._generation += 1
            gen = self._generation
            try:
                from .telemetry_service import TelemetryService
                known_provs = list(profiles_by_prov.keys())
                known_roles = list(routing.keys())
                telemetry_data = TelemetryService.get().get_breakdown(
                    window_seconds=86400,
                    known_providers=known_provs,
                    known_roles=known_roles,
                )
            except Exception:
                telemetry_data = {"source": "own_measurement", "has_data": False}

            try:
                from .host_metrics import HostMetricsService
                host_data = HostMetricsService.collect().to_dict()
            except Exception:
                host_data = {"source": "host_measurement", "has_data": False}

            try:
                from .router_engine import get_router_engine
                engine = get_router_engine()
                active_leases_total = engine.leases.total_active_count()
                active_leases_by_profile = engine.leases.all_active_counts()
            except Exception:
                try:
                    from .session_affinity import LeaseManager
                    active_leases_total = LeaseManager.get().total_active_count()
                    active_leases_by_profile = LeaseManager.get().all_active_counts()
                except Exception:
                    active_leases_total = 0
                    active_leases_by_profile = {}

            try:
                from .settings_service import get_hermes_config_status, get_hub_settings
                hermes_cfg = get_hermes_config_status()
                hub_settings = get_hub_settings()
                default_role = hub_settings.get("default_role", "manager")
            except Exception:
                hermes_cfg = {"exists": False, "model": None, "provider": None}
                default_role = "manager"

            metrics = {
                "generation": gen,
                "seq": request_seq,
                "duration_ms": round((time.time() - t0) * 1000, 2),
                "total_profiles": len(all_profs),
                "authenticated_profiles": sum(
                    1 for profile in all_profs.values() if profile.auth_state == "AUTHENTICATED"
                ),
                "refresh_runs_total": self.refresh_runs_total,
                "refresh_deduplicated_total": self.refresh_deduplicated_total,
                "telemetry": telemetry_data,
                "host": host_data,
                "active_calls_total": active_leases_total,
                "active_calls_by_profile": active_leases_by_profile,
                "hermes_config": hermes_cfg,
                "default_role": default_role,
            }
            try:
                from .workflow_service import WorkflowService

                workflow_data = WorkflowService.get().snapshot()
                role_views = {agent.role_id: agent for agent in agents}
                for workflow_agent in workflow_data.get("agents", []):
                    role_view = role_views.get(workflow_agent.get("role"))
                    generic_name = str(workflow_agent.get("role") or "").replace("-", " ").title()
                    if role_view and workflow_agent.get("name") == generic_name:
                        workflow_agent["name"] = role_view.role_name_ru
                    if role_view and not workflow_agent.get("description"):
                        workflow_agent["description"] = role_view.role_description_ru
            except Exception as exc:
                workflow_data = {
                    "agents": [],
                    "definition": {},
                    "run": {"status": "unavailable"},
                    "events": [],
                    "is_loading": False,
                    "unavailable_reason": f"Workflow state unavailable: {exc}",
                }
            snapshot = HubSnapshot(
                generation=gen,
                seq=request_seq,
                timestamp=time.time(),
                profiles_by_provider=profiles_by_prov,
                all_profiles=all_profs,
                readiness=readiness,
                agents=agents,
                providers=providers,
                routing=routing,
                quotas=quotas_map,
                metrics=metrics,
                is_stale=False,
                workflow=workflow_data,
            )
            self._current_snapshot = snapshot

        # Emit snapshot update on EventBus
        EventBus.get().publish(EVENT_SYSTEM_READINESS_CHANGED, readiness)
        EventBus.get().publish(
            EVENT_REFRESH_COMPLETED,
            {"generation": gen, "seq": request_seq, "duration_ms": metrics["duration_ms"]},
        )
        return snapshot

    def _build_empty_snapshot(self) -> HubSnapshot:
        try:
            from .host_metrics import HostMetricsService
            host_data = HostMetricsService.collect().to_dict()
        except Exception:
            host_data = {"source": "host_measurement", "has_data": False}

        try:
            from .telemetry_service import TelemetryService
            telemetry_data = TelemetryService.get().get_breakdown(window_seconds=86400)
        except Exception:
            telemetry_data = {"source": "own_measurement", "has_data": False}

        return HubSnapshot(
            generation=0,
            seq=0,
            timestamp=time.time(),
            profiles_by_provider={},
            all_profiles={},
            readiness=SystemReadiness(
                state="LIMITED",
                title_ru="Инициализация",
                summary_ru="Состояние ещё не загружено",
                accounts_connected_count=0,
                total_accounts=0,
                roles_ready_count=0,
                total_roles=0,
                providers_ready_count=0,
                total_providers=0,
            ),
            agents=[],
            providers=[],
            routing={},
            quotas={},
            metrics={
                "generation": 0,
                "seq": 0,
                "telemetry": telemetry_data,
                "host": host_data,
                "active_calls_total": 0,
                "active_calls_by_profile": {},
            },
            is_stale=True,
            workflow={
                "agents": [],
                "definition": {},
                "run": {"status": "loading"},
                "events": [],
                "is_loading": True,
            },
        )

    def _apply_profile_delta(self, profile: ProfileViewModel) -> HubSnapshot:
        """Copy-on-write replacement of exactly one profile in the snapshot."""
        with self._lock:
            current = self._current_snapshot or self._build_empty_snapshot()
            all_profiles = dict(current.all_profiles)
            all_profiles[profile.profile_id] = profile
            grouped = {provider: list(items) for provider, items in current.profiles_by_provider.items()}
            provider_profiles = grouped.setdefault(profile.provider, [])
            for index, existing in enumerate(provider_profiles):
                if existing.profile_id == profile.profile_id:
                    provider_profiles[index] = profile
                    break
            else:
                provider_profiles.append(profile)
            self._generation += 1
            seq = self.next_seq()
            self._latest_applied_seq = seq
            updated = replace(
                current,
                generation=self._generation,
                seq=seq,
                timestamp=time.time(),
                profiles_by_provider=grouped,
                all_profiles=all_profiles,
            )
            self._current_snapshot = updated
            return updated

    def apply_delta_account_updated(
        self,
        profile_id: str,
        profile: Optional[ProfileViewModel] = None,
        provider: Optional[str] = None,
    ) -> None:
        """Update one account and publish a profile-keyed event without a global scan."""
        self.account_updates_total += 1
        if profile is None:
            current = self._current_snapshot or self._build_empty_snapshot()
            current_profile = current.get_profile(profile_id)
            provider = provider or (current_profile.provider if current_profile else "")
            if provider:
                profile = UnifiedHealthService.get().refresh_profile(provider, profile_id)
        if profile is None:
            logger.warning("Cannot apply account delta for unknown profile %s", profile_id)
            return
        snapshot = self._apply_profile_delta(profile)
        EventBus.get().publish(
            EVENT_ACCOUNT_UPDATED,
            {
                "provider": profile.provider,
                "profile_id": profile_id,
                "profile": profile,
                "generation": snapshot.generation,
                "seq": snapshot.seq,
            },
        )

    def apply_delta_account_added(
        self,
        profile: ProfileViewModel | str,
        profile_id: Optional[str] = None,
    ) -> None:
        with self._lock:
            self._removed_accounts.discard(profile_id if isinstance(profile, str) else profile.profile_id)
        if isinstance(profile, str):
            provider = profile
            if profile_id is None:
                raise ValueError("profile_id is required when provider is passed")
            refreshed = UnifiedHealthService.get().refresh_profile(provider, profile_id)
            if refreshed is None:
                EventBus.get().publish(
                    EVENT_ACCOUNT_ADDED,
                    {"provider": provider, "profile_id": profile_id},
                )
                return
            profile = refreshed
        snapshot = self._apply_profile_delta(profile)
        EventBus.get().publish(
            EVENT_ACCOUNT_ADDED,
            {
                "provider": profile.provider,
                "profile_id": profile.profile_id,
                "profile": profile,
                "generation": snapshot.generation,
                "seq": snapshot.seq,
            },
        )

    def apply_delta_profile_preferences(self, profile_id: str, models: list[str]) -> None:
        # A configuration change does not require quota/identity network requests.
        with self._lock:
            profile = self._current_snapshot.get_profile(profile_id) if self._current_snapshot else None
            if profile:
                self._apply_profile_delta(replace(profile, preferred_models=list(models)))

    def apply_delta_account_removed(self, provider: str, profile_id: str) -> None:
        with self._lock:
            self._removed_accounts.add(profile_id)
            current = self._current_snapshot or self._build_empty_snapshot()
            all_profiles = dict(current.all_profiles)
            all_profiles.pop(profile_id, None)
            grouped = {key: list(value) for key, value in current.profiles_by_provider.items()}
            grouped[provider] = [item for item in grouped.get(provider, []) if item.profile_id != profile_id]
            quotas = dict(current.quotas)
            quotas.pop(profile_id, None)
            self._generation += 1
            seq = self.next_seq()
            self._latest_applied_seq = seq
            updated = replace(
                current,
                generation=self._generation,
                seq=seq,
                timestamp=time.time(),
                profiles_by_provider=grouped,
                all_profiles=all_profiles,
                quotas=quotas,
            )
            self._current_snapshot = updated
        EventBus.get().publish(
            EVENT_ACCOUNT_REMOVED,
            {"provider": provider, "profile_id": profile_id, "generation": updated.generation, "seq": seq},
        )

    def publish_auth_changed(self, profile: ProfileViewModel) -> None:
        snapshot = self._apply_profile_delta(profile)
        EventBus.get().publish(
            EVENT_ACCOUNT_AUTH_CHANGED,
            {
                "provider": profile.provider,
                "profile_id": profile.profile_id,
                "auth_state": profile.auth_state,
                "profile": profile,
                "generation": snapshot.generation,
                "seq": snapshot.seq,
            },
        )

    def apply_delta_quota_updated(self, provider: str, profile_id: str, quota_snap: Any) -> None:
        """Apply instant runtime quota change (e.g. 429 received during inference)."""
        with self._lock:
            self.quota_updates_total += 1
            current = self._current_snapshot or self._build_empty_snapshot()
            quotas = dict(current.quotas)
            quotas[profile_id] = quota_snap
            all_profiles = dict(current.all_profiles)
            profile = all_profiles.get(profile_id)
            grouped = {provider_key: list(items) for provider_key, items in current.profiles_by_provider.items()}
            if profile is not None:
                updated_profile = replace(profile, quota_snapshot=quota_snap)
                all_profiles[profile_id] = updated_profile
                grouped[profile.provider] = [
                    updated_profile if item.profile_id == profile_id else item
                    for item in grouped.get(profile.provider, [])
                ]
            self._generation += 1
            seq = self.next_seq()
            self._latest_applied_seq = seq
            updated = replace(
                current,
                generation=self._generation,
                seq=seq,
                timestamp=time.time(),
                profiles_by_provider=grouped,
                quotas=quotas,
                all_profiles=all_profiles,
            )
            self._current_snapshot = updated

        EventBus.get().publish(
            EVENT_QUOTA_UPDATED,
            {
                "provider": provider,
                "profile_id": profile_id,
                "snapshot": quota_snap,
                "quota_snapshot": quota_snap,
                "generation": updated.generation,
                "seq": updated.seq,
            },
        )

    def apply_delta_route_changed(
        self,
        role_id: str,
        active_profile_id: Optional[str] = None,
        failover_reason: Optional[str] = None,
    ) -> None:
        """Apply targeted route change and publish EVENT_ROUTING_UPDATED and EVENT_AGENT_UPDATED."""
        uh_service = UnifiedHealthService.get()
        routing = uh_service.get_routing_pipelines()
        agents = uh_service.get_agent_view_models()
        readiness = uh_service.get_system_readiness()

        with self._lock:
            current = self._current_snapshot or self._build_empty_snapshot()
            self._generation += 1
            seq = self.next_seq()
            self._latest_applied_seq = seq
            updated = replace(
                current,
                generation=self._generation,
                seq=seq,
                timestamp=time.time(),
                routing=routing,
                agents=agents,
                readiness=readiness,
            )
            self._current_snapshot = updated

        pipeline = updated.get_role_pipeline(role_id)
        EventBus.get().publish(
            EVENT_ROUTING_UPDATED,
            {
                "role_id": role_id,
                "active_profile_id": active_profile_id or (pipeline.active_profile_id if pipeline else None),
                "pipeline": pipeline,
                "failover_reason": failover_reason,
                "generation": updated.generation,
                "seq": updated.seq,
            },
        )
        agent = next((a for a in agents if a.role_id == role_id), None)
        if agent:
            EventBus.get().publish(
                EVENT_AGENT_UPDATED,
                {
                    "role_id": role_id,
                    "agent": agent,
                    "generation": updated.generation,
                    "seq": updated.seq,
                },
            )

    def apply_delta_agent_updated(self, role_id: str) -> None:
        """Publish updated agent view model for a specific role."""
        uh_service = UnifiedHealthService.get()
        agents = uh_service.get_agent_view_models()
        agent = next((a for a in agents if a.role_id == role_id), None)
        if agent:
            with self._lock:
                current = self._current_snapshot or self._build_empty_snapshot()
                self._generation += 1
                seq = self.next_seq()
                self._latest_applied_seq = seq
                updated = replace(
                    current,
                    generation=self._generation,
                    seq=seq,
                    timestamp=time.time(),
                    agents=agents,
                )
                self._current_snapshot = updated

            EventBus.get().publish(
                EVENT_AGENT_UPDATED,
                {
                    "role_id": role_id,
                    "agent": agent,
                    "generation": updated.generation,
                    "seq": updated.seq,
                },
            )
