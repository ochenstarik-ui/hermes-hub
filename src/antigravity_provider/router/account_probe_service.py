"""Non-blocking, de-duplicated health and model probes for configured accounts."""
from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Optional


class AccountProbeService:
    _instance: Optional["AccountProbeService"] = None
    _singleton_lock = threading.Lock()

    def __init__(self) -> None:
        self.enabled = False
        self._next_check = 0.0
        self._states: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="account-probe")

    @classmethod
    def get(cls) -> "AccountProbeService":
        with cls._singleton_lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def state(self, profile_id: str) -> dict[str, Any]:
        with self._lock:
            return dict(self._states.get(profile_id, {"state": "never_checked"}))

    def schedule(self, provider: str, profile_id: str, *, force: bool = False) -> bool:
        if not self.enabled:
            return False
        with self._lock:
            current = self._states.get(profile_id, {})
            if current.get("state") == "checking":
                return False
            if not force and current.get("checked_at") and time.time() - current["checked_at"] < 30:
                return False
            self._states[profile_id] = {
                **current, "state": "checking", "provider": provider,
                "started_at": time.time(), "message": "Идёт опрос провайдера — это может занять до минуты",
            }
        self._pool.submit(self._run, provider, profile_id)
        return True

    def tick(self, now: Optional[float] = None) -> int:
        from .settings_service import get_hub_settings
        now = time.monotonic() if now is None else now
        if not self.enabled or now < self._next_check:
            return 0
        self._next_check = now + get_hub_settings()["account_check_interval_seconds"]
        return self.schedule_all(force=True)

    def schedule_all(self, *, force: bool = False) -> int:
        from .profile_manager import ProfileAuthManager
        from .router_config import load_router_config
        count = 0
        for pid, pcfg in load_router_config().profiles.items():
            if pcfg.enabled and ProfileAuthManager.get_profile_status(pcfg.provider, pid).get("authenticated"):
                count += int(self.schedule(pcfg.provider, pid, force=force))
        return count

    def _run(self, provider: str, profile_id: str) -> None:
        from .action_handler import do_test_profile
        from .model_discovery_service import ModelDiscoveryService
        try:
            from .state_store import HubStateStore
            HubStateStore.get().refresh(force_scan=True)
            models = ModelDiscoveryService.get().discover_models_sync(provider, timeout=20, profile_id=profile_id)
            HubStateStore.get().refresh(force_scan=True)
            if provider == "ollama":
                cloud = ModelDiscoveryService.get().get_models_with_metadata("ollama-cloud-catalog")
                if cloud.get("is_stale"):
                    ModelDiscoveryService.get().discover_ollama_cloud()
            result = do_test_profile(provider, profile_id, timeout=60, discovered_models=models)
            meta = ModelDiscoveryService.get().get_models_with_metadata(provider, profile_id)
            success = bool(result.get("success"))
            message = result.get("response") or result.get("error") or "Проверка завершена без пояснения"
            state = "working" if success else "failed"
        except Exception as exc:
            models, meta, state, message = None, {}, "failed", str(exc)
        with self._lock:
            self._states[profile_id] = {
                "state": state, "provider": provider, "checked_at": time.time(),
                "message": message, "models": models, "model_error": meta.get("error"),
                "models_discovered_at": meta.get("discovered_at"),
            }
        try:
            from .state_store import HubStateStore
            HubStateStore.get().refresh(force_scan=True)
        except Exception:
            pass
