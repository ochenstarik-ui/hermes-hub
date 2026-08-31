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
        self.last_tick = None
        self.error = None
        self._profile_locks = {}
        self._closed = False
        self._cloud_next = 0.0
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

    def _profile_lock(self, profile_id: str):
        with self._lock:
            return self._profile_locks.setdefault(profile_id, threading.Lock())

    def _mark_checking(self, provider, profile_id):
        with self._lock:
            self._states[profile_id] = {
                **self._states.get(profile_id, {}), "state": "checking",
                "provider": provider, "started_at": time.time(),
                "message": "Идёт запрос к провайдеру",
            }

    def schedule(self, provider: str, profile_id: str, *, force: bool = False) -> bool:
        if not self.enabled or self._closed:
            return False
        lock = self._profile_lock(profile_id)
        if not lock.acquire(blocking=False):
            return False
        current = self.state(profile_id)
        if not force and time.time() - current.get("checked_at", 0) < 30:
            lock.release()
            return False
        self._mark_checking(provider, profile_id)
        try:
            future = self._pool.submit(self._run, provider, profile_id)
            def cancelled(done):
                if done.cancelled():
                    with self._lock:
                        self._states[profile_id] = {"state": "failed", "message": "Проверка отменена при завершении сервера"}
                    lock.release()
            future.add_done_callback(cancelled)
        except Exception:
            with self._lock:
                self._states[profile_id] = current
            lock.release()
            raise
        return True

    def check_now(self, provider: str, profile_id: str, models_only: bool = False) -> dict:
        # Periodic scheduling can be disabled without disabling a manual request.
        if self._closed:
            return {"ok": False, "message": "Сервер завершает работу"}
        lock = self._profile_lock(profile_id)
        if not lock.acquire(timeout=90):
            return {"ok": False, "message": "Проверка этого аккаунта ещё выполняется; повторите позже"}
        try:
            if self._closed:
                return {"ok": False, "message": "Сервер завершает работу"}
            self._mark_checking(provider, profile_id)
            return self._probe(provider, profile_id, models_only)
        finally:
            lock.release()

    def record_validation(self, provider: str, profile_id: str, result: dict) -> None:
        with self._lock:
            self._states[profile_id] = {
                "state": "working", "provider": provider, "checked_at": time.time(),
                "message": result["message"], "models": result["data"]["models"],
                "check_kind": "credentials_and_catalog",
            }

    def status(self) -> dict:
        return {"enabled": self.enabled, "last_tick": self.last_tick, "error": self.error}

    def tick(self, now: Optional[float] = None) -> int:
        from .settings_service import get_hub_settings
        now = time.monotonic() if now is None else now
        if not self.enabled or now < self._next_check:
            return 0
        try:
            count = self.schedule_all(force=True)
            self._next_check = now + get_hub_settings()["account_check_interval_seconds"]
            self.last_tick, self.error = time.time(), None
            return count
        except Exception as exc:
            self.error = str(exc).strip() or type(exc).__name__
            return 0

    def shutdown(self) -> None:
        self.enabled, self._closed = False, True
        self._pool.shutdown(wait=False, cancel_futures=True)

    def schedule_all(self, *, force: bool = False) -> int:
        from .profile_manager import ProfileAuthManager
        from .router_config import load_router_config
        count = 0
        has_ollama = False
        for pid, pcfg in load_router_config().profiles.items():
            if pcfg.enabled and ProfileAuthManager.get_profile_status(pcfg.provider, pid).get("authenticated"):
                count += int(self.schedule(pcfg.provider, pid, force=force))
                has_ollama |= pcfg.provider == "ollama"
        if self.enabled and has_ollama and time.monotonic() >= self._cloud_next:
            from .model_discovery_service import ModelDiscoveryService
            self._cloud_next = time.monotonic() + 3600
            self._pool.submit(ModelDiscoveryService.get().discover_ollama_cloud)
        return count

    def _run(self, provider: str, profile_id: str) -> None:
        try:
            self._probe(provider, profile_id)
        finally:
            self._profile_lock(profile_id).release()

    def _probe(self, provider: str, profile_id: str, models_only: bool = False) -> dict:
        from .action_handler import do_test_profile
        from .model_discovery_service import ModelDiscoveryService
        models, meta = None, {}
        try:
            discovery = ModelDiscoveryService.get()
            models = discovery.discover_models_sync(provider, timeout=65 if provider == "antigravity" else 20, profile_id=profile_id)
            meta = discovery.get_models_with_metadata(provider, profile_id)
            if models is None and meta.get("error"):
                success, message = False, meta["error"]
            elif models_only:
                success = models is not None and not meta.get("error")
                message = meta.get("error") or (f"Получено моделей: {len(models)}" if success else "Провайдер не вернул каталог моделей")
            else:
                result = do_test_profile(provider, profile_id, timeout=60, discovered_models=models)
                success = bool(result.get("success"))
                message = result.get("response") or result.get("error") or "Провайдер не сообщил причину результата проверки"
            state = "working" if success else "failed"
        except Exception as exc:
            success, state, message = False, "failed", str(exc).strip() or type(exc).__name__
        record = {
            "state": state, "provider": provider, "checked_at": time.time(),
            "message": message, "models": models, "model_error": meta.get("error"),
            "models_discovered_at": meta.get("discovered_at"), "models_only": models_only,
        }
        with self._lock:
            self._states[profile_id] = record
        return {"ok": success, "message": message, "data": record}
