"""Session affinity and lease management for Hermes multi-provider router."""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Optional


@dataclass
class SessionAffinityRecord:
    session_id: str
    role: str
    profile_id: str
    model: Optional[str] = None
    created_at: float = 0.0
    updated_at: float = 0.0


class SessionAffinityTracker:
    """Thread-safe tracker maintaining session affinity across conversation turns."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._sessions: dict[str, SessionAffinityRecord] = {}

    def get_affinity(self, session_id: Optional[str]) -> Optional[SessionAffinityRecord]:
        if not session_id:
            return None
        with self._lock:
            return self._sessions.get(session_id)

    def set_affinity(
        self,
        session_id: Optional[str],
        role: str,
        profile_id: str,
        model: Optional[str] = None,
    ) -> None:
        if not session_id:
            return
        with self._lock:
            now = time.time()
            if session_id in self._sessions:
                rec = self._sessions[session_id]
                rec.role = role
                rec.profile_id = profile_id
                rec.model = model
                rec.updated_at = now
            else:
                self._sessions[session_id] = SessionAffinityRecord(
                    session_id=session_id,
                    role=role,
                    profile_id=profile_id,
                    model=model,
                    created_at=now,
                    updated_at=now,
                )

    def clear_session(self, session_id: str) -> None:
        with self._lock:
            self._sessions.pop(session_id, None)

    def clear_all(self) -> None:
        with self._lock:
            self._sessions.clear()


class LeaseManager:
    """Manages concurrent leases per profile to prevent process saturation."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._active_leases: dict[str, int] = {}

    def acquire(self, profile_id: str, max_concurrency: int = 1) -> bool:
        with self._lock:
            current = self._active_leases.get(profile_id, 0)
            if current >= max_concurrency:
                return False
            self._active_leases[profile_id] = current + 1
            return True

    def release(self, profile_id: str) -> None:
        with self._lock:
            current = self._active_leases.get(profile_id, 0)
            if current > 0:
                self._active_leases[profile_id] = current - 1

    def active_count(self, profile_id: str) -> int:
        with self._lock:
            return self._active_leases.get(profile_id, 0)
