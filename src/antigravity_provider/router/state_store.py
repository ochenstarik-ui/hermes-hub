"""Hermes Hub — Unified HubStateStore & Immutable HubSnapshot Layer.

Provides normalized state management, single-scan snapshot generation,
request deduplication, generation tracking, and delta event publishing.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from antigravity_provider.router.event_bus import (
    EventBus,
    EVENT_ACCOUNT_UPDATED,
    EVENT_ACCOUNT_ADDED,
    EVENT_ACCOUNT_REMOVED,
    EVENT_QUOTA_UPDATED,
    EVENT_ROUTING_UPDATED,
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
                return self._current_snapshot
        return self.refresh(force_scan=False)

    def refresh(self, force_scan: bool = True, seq: Optional[int] = None) -> HubSnapshot:
        """Execute a single unified state build cycle and publish an updated HubSnapshot."""
        with self._lock:
            if seq is not None and seq < self._latest_applied_seq:
                logger.warning("Rejecting stale refresh result (seq %d < applied %d)", seq, self._latest_applied_seq)
                self.refresh_skipped_total += 1
                return self._current_snapshot or self._build_empty_snapshot()

            self.refresh_runs_total += 1
            if seq is not None:
                self._latest_applied_seq = max(self._latest_applied_seq, seq)

            t0 = time.time()
            self._generation += 1
            gen = self._generation

            # Single unified scan
            uh_service = UnifiedHealthService.get()
            profiles_by_prov = uh_service.scan_all(force=force_scan)

            all_profs: Dict[str, ProfileViewModel] = {}
            for prov, profs in profiles_by_prov.items():
                for p in profs:
                    all_profs[p.profile_id] = p

            readiness = uh_service.get_system_readiness()
            agents = uh_service.get_agent_view_models()
            providers = uh_service.get_provider_summaries()
            routing = uh_service.get_routing_pipelines()

            # Quotas map
            quota_service = AccountQuotaService.get()
            quotas_map: Dict[str, Any] = {}
            for pid, p in all_profs.items():
                if p.auth_state == "AUTHENTICATED":
                    quotas_map[pid] = quota_service.get_snapshot(p.provider, pid)

            metrics = {
                "generation": gen,
                "duration_ms": round((time.time() - t0) * 1000, 2),
                "total_profiles": len(all_profs),
                "authenticated_profiles": sum(1 for p in all_profs.values() if p.auth_state == "AUTHENTICATED"),
                "refresh_runs_total": self.refresh_runs_total,
                "refresh_deduplicated_total": self.refresh_deduplicated_total,
            }

            snapshot = HubSnapshot(
                generation=gen,
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
            )

            self._current_snapshot = snapshot

        # Emit snapshot update on EventBus
        EventBus.get().publish(EVENT_SYSTEM_READINESS_CHANGED, readiness)
        EventBus.get().publish(EVENT_REFRESH_COMPLETED, {"generation": gen, "duration_ms": metrics["duration_ms"]})
        return snapshot

    def _build_empty_snapshot(self) -> HubSnapshot:
        return HubSnapshot(
            generation=0,
            timestamp=time.time(),
            profiles_by_provider={},
            all_profiles={},
            readiness=SystemReadiness(state="limited", title_ru="Инициализация", description_ru="", accounts_connected_count=0, total_accounts=0, roles_ready_count=0, total_roles=0, providers_ready_count=0, total_providers=0),
            agents=[],
            providers=[],
            routing={},
            quotas={},
            metrics={},
            is_stale=True,
        )

    def apply_delta_account_updated(self, profile_id: str) -> None:
        """Apply targeted account delta update and notify UI without global scan."""
        with self._lock:
            self.account_updates_total += 1
            # Invalidate cached view model for targeted profile
            uh_service = UnifiedHealthService.get()
            with uh_service._lock:
                uh_service._cached_profiles.pop(profile_id, None)

        # Refresh snapshot and notify
        snap = self.refresh(force_scan=False)
        updated_profile = snap.get_profile(profile_id)
        if updated_profile:
            EventBus.get().publish(EVENT_ACCOUNT_UPDATED, {
                "profile_id": profile_id,
                "profile": updated_profile,
                "generation": snap.generation,
            })

    def apply_delta_account_added(self, provider: str, profile_id: str) -> None:
        """Apply account added delta, refresh targeted profile, and emit EVENT_ACCOUNT_ADDED."""
        self.apply_delta_account_updated(profile_id)
        EventBus.get().publish(EVENT_ACCOUNT_ADDED, {
            "provider": provider,
            "profile_id": profile_id,
        })

    def apply_delta_account_removed(self, provider: str, profile_id: str) -> None:
        """Apply account removed delta and emit EVENT_ACCOUNT_REMOVED."""
        with self._lock:
            uh_service = UnifiedHealthService.get()
            with uh_service._lock:
                uh_service._cached_profiles.pop(profile_id, None)
        self.refresh(force_scan=False)
        EventBus.get().publish(EVENT_ACCOUNT_REMOVED, {
            "provider": provider,
            "profile_id": profile_id,
        })

    def apply_delta_route_changed(self, role_id: str, active_profile_id: Optional[str] = None) -> None:
        """Apply routing delta change and emit EVENT_ROUTING_UPDATED."""
        snap = self.refresh(force_scan=False)
        pipeline = snap.get_role_pipeline(role_id)
        EventBus.get().publish(EVENT_ROUTING_UPDATED, {
            "role_id": role_id,
            "active_profile_id": active_profile_id,
            "pipeline": pipeline,
            "generation": snap.generation,
        })

    def apply_delta_quota_updated(self, provider: str, profile_id: str, quota_snap: Any) -> None:
        """Apply instant runtime quota change (e.g. 429 received during inference)."""
        with self._lock:
            self.quota_updates_total += 1
            if self._current_snapshot is not None:
                # Update snapshot in place atomically
                if hasattr(self._current_snapshot, "quotas") and isinstance(self._current_snapshot.quotas, dict):
                    self._current_snapshot.quotas[profile_id] = quota_snap
                prof = self._current_snapshot.get_profile(profile_id)
                if prof and hasattr(prof, "quota_snapshot"):
                    prof.quota_snapshot = quota_snap

        EventBus.get().publish(EVENT_QUOTA_UPDATED, {
            "provider": provider,
            "profile_id": profile_id,
            "snapshot": quota_snap,
            "quota_snapshot": quota_snap,
        })
