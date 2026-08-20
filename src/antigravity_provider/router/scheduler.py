"""Hermes Hub — Central Refresh Scheduler with Concurrency Throttling, Dedup, & Stale Protection.

Implements Cockpit-style architectural refresh scheduling natively in Python:
- Configurable per-provider & per-scope refresh intervals (full vs current vs single)
- Deterministic initial delay distribution to eliminate API startup storms
- max_concurrent_refresh_tasks = 1 default to protect provider rate limits
- Request deduplication with in-flight future/token reuse
- Overlap skip policy (no redundant queues)
- Sequence generation tokens for stale response rejection
"""
from __future__ import annotations

import hashlib
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set

from antigravity_provider.router.event_bus import (
    EventBus,
    EVENT_ACCOUNT_ADDED,
    EVENT_ACCOUNT_AUTH_CHANGED,
    EVENT_REFRESH_STARTED,
    EVENT_REFRESH_COMPLETED,
    EVENT_REFRESH_FAILED,
)
from antigravity_provider.router.state_store import HubStateStore
from antigravity_provider.router.quota_collector import AccountQuotaService
from antigravity_provider.router.unified_health import UnifiedHealthService

logger = logging.getLogger("hermes.router.scheduler")


@dataclass
class RefreshTask:
    """Descriptor for a scheduled refresh task."""
    key: str
    provider: str
    scope: str  # "full" | "current" | "single"
    profile_id: Optional[str] = None
    interval_seconds: int = 600  # Default 10 min
    next_run_at: float = 0.0
    running: bool = False
    last_run_at: Optional[float] = None
    last_success_at: Optional[float] = None
    last_error: Optional[str] = None
    priority: int = 10  # Lower number = higher priority


def stable_initial_delay(key: str, min_sec: float = 1.0, max_sec: float = 4.5) -> float:
    """Generate a deterministic spread delay from a task key to prevent startup API storms."""
    h = int(hashlib.md5(key.encode("utf-8")).hexdigest()[:8], 16)
    fraction = (h % 1000) / 1000.0
    return min_sec + fraction * (max_sec - min_sec)


class HermesRefreshScheduler:
    """Central daemon scheduler for background provider state & quota synchronization."""

    _instance: Optional[HermesRefreshScheduler] = None
    _instance_lock = threading.Lock()

    def __init__(
        self,
        tick_interval_sec: float = 5.0,
        max_concurrent_tasks: int = 1,
        startup_delay_sec: float = 2.0,
    ) -> None:
        self.tick_interval_sec = tick_interval_sec
        self.max_concurrent_tasks = max_concurrent_tasks
        self.startup_delay_sec = startup_delay_sec

        self._lock = threading.RLock()
        self._tasks: Dict[str, RefreshTask] = {}
        self._active_task_keys: Set[str] = set()
        self._in_flight_refreshes: Dict[str, threading.Event] = {}

        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._running = False

        # Metrics
        self.total_ticks: int = 0
        self.tasks_executed_total: int = 0
        self.tasks_skipped_overlap: int = 0
        self.tasks_deduplicated_total: int = 0

        self._init_default_tasks()
        EventBus.get().subscribe(EVENT_ACCOUNT_ADDED, self._on_account_event)
        EventBus.get().subscribe(EVENT_ACCOUNT_AUTH_CHANGED, self._on_account_event)

    def _on_account_event(self, _event_name: str, payload: Any) -> None:
        """Refresh only the account mentioned by an OAuth/auth lifecycle event."""
        if not isinstance(payload, dict):
            return
        provider = payload.get("provider")
        profile_id = payload.get("profile_id")
        if provider and profile_id:
            self.trigger_refresh_account(str(provider), str(profile_id))

    @classmethod
    def get(cls) -> HermesRefreshScheduler:
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def _init_default_tasks(self):
        """Register default scheduled provider and global refresh tasks."""
        providers = ["antigravity", "openai-codex", "opencode-go", "claude", "grok"]
        now = time.time()

        for prov in providers:
            # 1. Full provider refresh (every 10 min, spread out at start)
            f_key = f"{prov}:full"
            self._tasks[f_key] = RefreshTask(
                key=f_key,
                provider=prov,
                scope="full",
                interval_seconds=600,
                next_run_at=now + self.startup_delay_sec + stable_initial_delay(f_key, 1.0, 5.0),
                priority=20,
            )

            # 2. Current / active account refresh (every 2 min, spread out)
            c_key = f"{prov}:current"
            self._tasks[c_key] = RefreshTask(
                key=c_key,
                provider=prov,
                scope="current",
                interval_seconds=120,
                next_run_at=now + self.startup_delay_sec + stable_initial_delay(c_key, 0.5, 3.0),
                priority=10,
            )

    def apply_settings(self, settings: Optional[Dict[str, Any]] = None) -> None:
        """Apply monitoring settings from hub_settings.json."""
        if settings is None:
            try:
                from antigravity_provider.router.settings_service import get_hub_settings
                settings = get_hub_settings()
            except Exception:
                settings = {}

        auto_mon = settings.get("auto_monitoring", True)
        interval = max(5, int(settings.get("monitoring_interval_seconds", 30)))

        with self._lock:
            for task in self._tasks.values():
                if task.scope == "current":
                    task.interval_seconds = interval
                elif task.scope == "full":
                    task.interval_seconds = max(interval * 4, 120)
                if not auto_mon:
                    task.next_run_at = float("inf")

    def set_provider_interval(self, provider: str, interval_seconds: int) -> None:
        """Update refresh interval for a specific provider (e.g. from settings view)."""
        with self._lock:
            for task in self._tasks.values():
                if task.provider == provider and task.scope == "full":
                    task.interval_seconds = interval_seconds
                    if interval_seconds <= 0:
                        task.next_run_at = float("inf")  # Disabled

    def start(self) -> None:
        """Start the background scheduler daemon thread."""
        with self._lock:
            if self._running:
                return
            self._running = True
            self._stop_event.clear()
            self._thread = threading.Thread(target=self._run_loop, name="HermesRefreshScheduler", daemon=True)
            self._thread.start()
            logger.info("HermesRefreshScheduler started (tick=%.1fs, max_concurrent=%d)", self.tick_interval_sec, self.max_concurrent_tasks)

    def stop(self) -> None:
        """Gracefully stop the background scheduler."""
        with self._lock:
            if not self._running:
                return
            self._running = False
            self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        logger.info("HermesRefreshScheduler stopped")

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._tick()
            except Exception as e:
                logger.error("Error in HermesRefreshScheduler tick: %s", e)

            self._stop_event.wait(timeout=self.tick_interval_sec)

    def _tick(self) -> None:
        """Evaluate scheduled tasks and launch eligible background refresh jobs."""
        with self._lock:
            self.total_ticks += 1
            now = time.time()

            # Find ready tasks
            ready_tasks: List[RefreshTask] = []
            for task in self._tasks.values():
                if task.interval_seconds > 0 and task.next_run_at <= now:
                    ready_tasks.append(task)

            # Sort by priority
            ready_tasks.sort(key=lambda t: t.priority)

            for task in ready_tasks:
                if len(self._active_task_keys) >= self.max_concurrent_tasks:
                    # Concurrency saturated for this tick
                    break

                if task.key in self._active_task_keys or task.running:
                    self.tasks_skipped_overlap += 1
                    continue

                # Schedule next run immediately to prevent double-dispatch
                task.next_run_at = now + task.interval_seconds
                task.running = True
                self._active_task_keys.add(task.key)

                # Launch in separate background worker thread
                threading.Thread(
                    target=self._execute_task,
                    args=(task,),
                    name=f"RefreshWorker-{task.key}",
                    daemon=True,
                ).start()

    def _execute_task(self, task: RefreshTask) -> None:
        """Execute a single refresh task in a background worker thread."""
        key = task.key
        seq = HubStateStore.get().next_seq()
        t0 = time.time()
        EventBus.get().publish(EVENT_REFRESH_STARTED, {"key": key, "seq": seq})

        try:
            # Check for NOT_CONFIGURED profiles before network calls
            uh_service = UnifiedHealthService.get()
            quota_service = AccountQuotaService.get()

            if task.scope == "single" and task.profile_id:
                status = uh_service.get_profile_status(task.provider, task.profile_id)
                if status.get("authenticated"):
                    quota_snapshot = quota_service.fetch_account_quota(
                        task.provider,
                        task.profile_id,
                        force=True,
                    )
                    HubStateStore.get().apply_delta_quota_updated(
                        task.provider,
                        task.profile_id,
                        quota_snapshot,
                    )

            elif task.scope in ("full", "current"):
                # Refresh quota snapshots for configured accounts of this provider
                profs = uh_service.get_cached_profiles().get(task.provider, [])
                for p in profs:
                    if p.auth_state == "AUTHENTICATED":
                        quota_snapshot = quota_service.fetch_account_quota(
                            task.provider,
                            p.profile_id,
                            force=True,
                        )
                        HubStateStore.get().apply_delta_quota_updated(
                            task.provider,
                            p.profile_id,
                            quota_snapshot,
                        )

            # Rebuild unified snapshot
            HubStateStore.get().refresh(force_scan=True, seq=seq)

            with self._lock:
                task.last_success_at = time.time()
                task.last_error = None
                self.tasks_executed_total += 1

        except Exception as ex:
            logger.error("Error executing refresh task %s: %s", key, ex)
            with self._lock:
                task.last_error = str(ex)
            EventBus.get().publish(EVENT_REFRESH_FAILED, {"key": key, "error": str(ex)})

        finally:
            with self._lock:
                task.running = False
                task.last_run_at = time.time()
                self._active_task_keys.discard(key)

    def trigger_refresh_account(self, provider: str, profile_id: str, on_complete: Optional[Callable] = None) -> None:
        """Trigger an instant non-blocking refresh for a single specific account."""
        key = f"account:{profile_id}"
        with self._lock:
            if key in self._in_flight_refreshes:
                self.tasks_deduplicated_total += 1
                logger.info("Deduplicating in-flight refresh for %s", key)
                return

            event = threading.Event()
            self._in_flight_refreshes[key] = event

        def _worker():
            try:
                quota_service = AccountQuotaService.get()
                quota_snapshot = quota_service.fetch_account_quota(provider, profile_id, force=True)
                HubStateStore.get().apply_delta_quota_updated(provider, profile_id, quota_snapshot)
                HubStateStore.get().apply_delta_account_updated(profile_id)
            finally:
                with self._lock:
                    self._in_flight_refreshes.pop(key, None)
                    event.set()
                if on_complete:
                    on_complete()

        threading.Thread(target=_worker, name=f"SingleRefresh-{profile_id}", daemon=True).start()

    def trigger_refresh_all(self, on_complete: Optional[Callable] = None) -> None:
        """Trigger non-blocking refresh of all configured profiles across all providers."""
        key = "all_accounts:full"
        with self._lock:
            if key in self._in_flight_refreshes:
                self.tasks_deduplicated_total += 1
                logger.info("Deduplicating in-flight full refresh")
                return

            event = threading.Event()
            self._in_flight_refreshes[key] = event

        def _worker():
            try:
                quota_service = AccountQuotaService.get()
                results = quota_service.fetch_all_configured(force=True)
                store = HubStateStore.get()
                for key, quota_snapshot in results.items():
                    provider, profile_id = key.split(":", 1)
                    store.apply_delta_quota_updated(provider, profile_id, quota_snapshot)
                store.refresh(force_scan=True)
            finally:
                with self._lock:
                    self._in_flight_refreshes.pop(key, None)
                    event.set()
                if on_complete:
                    on_complete()

        threading.Thread(target=_worker, name="FullRefreshAll", daemon=True).start()
