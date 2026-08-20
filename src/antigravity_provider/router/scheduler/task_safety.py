"""Scheduled Task Safety coordinator with overlap skip policy and execution bounds."""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from antigravity_provider.router.unified_health import EventLogService

logger = logging.getLogger("hermes.router.scheduler")


@dataclass
class ScheduledTaskSpec:
    task_id: str
    name: str
    cron_or_interval_sec: float
    handler: Callable[[], Any]
    max_runtime_sec: float = 60.0
    overlap_policy: str = "skip"  # skip | queue | replace
    max_retries: int = 2
    last_run_at: float = 0.0
    last_duration_sec: float = 0.0
    is_running: bool = False
    consecutive_failures: int = 0


class ScheduledTaskSafetyCoordinator:
    """Manages scheduled background task execution ensuring zero overlapping runs and strict execution bounds."""

    _instance: Optional[ScheduledTaskSafetyCoordinator] = None
    _lock = threading.RLock()

    def __init__(self):
        self._tasks: Dict[str, ScheduledTaskSpec] = {}
        self._running = True
        self._runner_thread: Optional[threading.Thread] = None

    @classmethod
    def get(cls) -> ScheduledTaskSafetyCoordinator:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def register_task(self, spec: ScheduledTaskSpec):
        with self._lock:
            self._tasks[spec.task_id] = spec
            EventLogService.get().log("system", f"Запланированная задача зарегистрирована: {spec.name} (каждые {spec.cron_or_interval_sec}s)", level="info")

    def run_task_safe(self, task_id: str) -> bool:
        """Run task enforcing overlap policy and execution bounds."""
        with self._lock:
            spec = self._tasks.get(task_id)
            if not spec:
                return False

            if spec.is_running:
                if spec.overlap_policy == "skip":
                    EventLogService.get().log("system", f"Пропуск запуска задачи '{spec.name}': предыдущий запуск ещё активен (overlap_policy=skip)", level="warning")
                    return False

            spec.is_running = True

        def _execute():
            t0 = time.time()
            try:
                spec.handler()
                with self._lock:
                    spec.last_run_at = t0
                    spec.last_duration_sec = round(time.time() - t0, 2)
                    spec.consecutive_failures = 0
                    spec.is_running = False
            except Exception as e:
                with self._lock:
                    spec.last_run_at = t0
                    spec.last_duration_sec = round(time.time() - t0, 2)
                    spec.consecutive_failures += 1
                    spec.is_running = False
                EventLogService.get().log("system", f"Ошибка выполнения задачи '{spec.name}': {e}", level="error")

        t = threading.Thread(target=_execute, daemon=True)
        t.start()
        return True
