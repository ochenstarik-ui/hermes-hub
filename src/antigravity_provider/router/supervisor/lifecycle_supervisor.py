"""Lifecycle Supervisor & Process Registry with strict process ownership metadata.

Invariant: Never use generic killall / taskkill python. Process cleanup only targets
verified child processes registered with an active UUID lease.
"""
from __future__ import annotations

import json
import logging
import os
import psutil
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from antigravity_provider.router.unified_health import EventLogService

logger = logging.getLogger("hermes.router.supervisor")


@dataclass
class ProcessEntry:
    process_uuid: str
    pid: int
    name: str
    cmdline: List[str]
    owner_app: str
    spawn_time: float
    lease_ttl_sec: float
    last_heartbeat: float
    status: str = "running"  # running | stopped | dead | zombie


@dataclass
class LeaseRecord:
    lease_id: str
    profile_id: str
    consumer: str
    acquired_at: float
    ttl_sec: float
    expires_at: float
    metadata: Dict[str, Any] = field(default_factory=dict)


class LifecycleSupervisor:
    """Central supervisor managing process lifecycle, heartbeat, and ownership leases."""

    _instance: Optional[LifecycleSupervisor] = None
    _lock = threading.RLock()

    def __init__(self, state_dir: Optional[Path] = None):
        if state_dir is None:
            local_app = os.environ.get("LOCALAPPDATA", "")
            state_dir = Path(local_app) / "hermes" / "supervisor"
        self.state_dir = state_dir
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.registry_file = self.state_dir / "process_registry.json"

        self._processes: Dict[str, ProcessEntry] = {}
        self._leases: Dict[str, LeaseRecord] = {}
        self._running = True
        self._supervisor_thread: Optional[threading.Thread] = None

        self._load_registry()
        self._start_supervisor()

    @classmethod
    def get(cls) -> LifecycleSupervisor:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def register_process(
        self,
        pid: int,
        name: str,
        cmdline: List[str],
        owner_app: str = "HermesHub",
        ttl_sec: float = 300.0,
    ) -> ProcessEntry:
        """Register a new child process with explicit ownership metadata."""
        with self._lock:
            p_uuid = str(uuid.uuid4())
            now = time.time()
            entry = ProcessEntry(
                process_uuid=p_uuid,
                pid=pid,
                name=name,
                cmdline=cmdline,
                owner_app=owner_app,
                spawn_time=now,
                lease_ttl_sec=ttl_sec,
                last_heartbeat=now,
                status="running",
            )
            self._processes[p_uuid] = entry
            self._save_registry()
            EventLogService.get().log("system", f"Процесс зарегистрирован: {name} (PID: {pid}, UUID: {p_uuid[:8]})", level="info")
            return entry

    def heartbeat(self, process_uuid: str) -> bool:
        """Update heartbeat for an active process."""
        with self._lock:
            if process_uuid in self._processes:
                self._processes[process_uuid].last_heartbeat = time.time()
                return True
            return False

    def acquire_lease(self, profile_id: str, consumer: str, ttl_sec: float = 60.0) -> Optional[LeaseRecord]:
        """Acquire a temporary exclusive usage lease for a profile."""
        with self._lock:
            now = time.time()
            # Clean expired leases
            self._leases = {lid: l for lid, l in self._leases.items() if l.expires_at > now}

            # Check existing active lease
            for l in self._leases.values():
                if l.profile_id == profile_id and l.expires_at > now:
                    return None  # Profile currently leased

            lease_id = str(uuid.uuid4())
            record = LeaseRecord(
                lease_id=lease_id,
                profile_id=profile_id,
                consumer=consumer,
                acquired_at=now,
                ttl_sec=ttl_sec,
                expires_at=now + ttl_sec,
            )
            self._leases[lease_id] = record
            return record

    def release_lease(self, lease_id: str) -> bool:
        with self._lock:
            if lease_id in self._leases:
                del self._leases[lease_id]
                return True
            return False

    def terminate_owned_process(self, process_uuid: str) -> bool:
        """Safely terminate a verified owned process without collateral damage."""
        with self._lock:
            entry = self._processes.get(process_uuid)
            if not entry:
                return False

            pid = entry.pid
            try:
                if psutil.pid_exists(pid):
                    p = psutil.Process(pid)
                    # Verify command line matches ownership record
                    p_cmd = p.cmdline() if hasattr(p, "cmdline") else []
                    if entry.name.lower() in p.name().lower() or (p_cmd and p_cmd[0] in entry.cmdline[0]):
                        p.terminate()
                        try:
                            p.wait(timeout=3)
                        except psutil.TimeoutExpired:
                            p.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

            entry.status = "stopped"
            self._save_registry()
            EventLogService.get().log("system", f"Процесс остановлен: {entry.name} (PID: {pid})", level="info")
            return True

    def cleanup_expired_processes(self) -> int:
        """Clean up strictly owned orphaned processes that missed heartbeats past TTL."""
        with self._lock:
            now = time.time()
            cleaned = 0
            for p_uuid, entry in list(self._processes.items()):
                if entry.status == "running":
                    if now - entry.last_heartbeat > entry.lease_ttl_sec:
                        # Process timed out
                        self.terminate_owned_process(p_uuid)
                        cleaned += 1
            return cleaned

    def shutdown_all_owned(self):
        """Clean shutdown of all registered child processes."""
        with self._lock:
            self._running = False
            for p_uuid, entry in list(self._processes.items()):
                if entry.status == "running":
                    self.terminate_owned_process(p_uuid)

    def _start_supervisor(self):
        def _loop():
            while self._running:
                time.sleep(5)
                try:
                    self.cleanup_expired_processes()
                except Exception:
                    pass

        self._supervisor_thread = threading.Thread(target=_loop, daemon=True)
        self._supervisor_thread.start()

    def _save_registry(self):
        try:
            data = {k: asdict(v) for k, v in self._processes.items()}
            self.registry_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception:
            pass

    def _load_registry(self):
        if self.registry_file.exists():
            try:
                data = json.loads(self.registry_file.read_text(encoding="utf-8"))
                for k, v in data.items():
                    # Validate if process still running
                    p_entry = ProcessEntry(**v)
                    if p_entry.status == "running" and not psutil.pid_exists(p_entry.pid):
                        p_entry.status = "dead"
                    self._processes[k] = p_entry
            except Exception:
                pass
