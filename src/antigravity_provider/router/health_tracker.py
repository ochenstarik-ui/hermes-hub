"""Health state and quota tracking per profile and model family.

Features:
- Atomic file write + temporary file replace for router_state.json.
- Thread-safe in-memory cache and automatic cooldown expiration.
- Model family vs profile-level status tracking.
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

from antigravity_provider import paths

HEALTHY = "healthy"
IN_USE = "in-use"
QUOTA_EXHAUSTED = "quota-exhausted"
RATE_LIMITED = "rate-limited"
COOLDOWN = "cooldown"
AUTH_REQUIRED = "auth-required"
DISABLED = "disabled"
UNHEALTHY = "unhealthy"


@dataclass
class FamilyHealthRecord:
    family: str
    state: str = HEALTHY
    reset_at: Optional[float] = None
    reason: Optional[str] = None
    last_error: Optional[str] = None
    error_count: int = 0
    success_count: int = 0
    simulated: bool = False


@dataclass
class ProfileHealthRecord:
    profile_id: str
    overall_state: str = HEALTHY
    families: dict[str, FamilyHealthRecord] = field(default_factory=dict)
    active_leases: int = 0
    last_used: Optional[float] = None
    last_success: Optional[float] = None
    last_error: Optional[str] = None
    simulated: bool = False


def extract_model_family(model_name: Optional[str]) -> str:
    """Extract model family prefix (e.g. gemini, claude, gpt, deepseek, kimi, qwen, grok, glm)."""
    if not model_name:
        return "default"
    m = model_name.lower().replace("google-antigravity/", "").replace("openai/", "").replace("moonshotai/", "")
    for family in ("gemini", "claude", "gpt", "o3", "o1", "deepseek", "kimi", "qwen", "grok", "glm", "mimo", "minimax"):
        if family in m:
            return family
    return "default"


class HealthTracker:
    """Thread-safe health tracker for router profiles and model families with atomic disk persistence."""

    def __init__(self, state_file: Optional[Path] = None):
        if state_file is None:
            state_file = paths.get_router_state_path()

        self.state_file = state_file
        self._lock = threading.RLock()
        self._profiles: dict[str, ProfileHealthRecord] = {}
        self._load_state()

    def _load_state(self) -> None:
        if not self.state_file.is_file():
            return
        try:
            raw = json.loads(self.state_file.read_text(encoding="utf-8"))
            for pid, pdata in raw.get("profiles", {}).items():
                record = ProfileHealthRecord(
                    profile_id=pid,
                    overall_state=pdata.get("overall_state", HEALTHY),
                    last_used=pdata.get("last_used"),
                    last_success=pdata.get("last_success"),
                    last_error=pdata.get("last_error"),
                    simulated=pdata.get("simulated", False),
                )
                for fname, fdata in pdata.get("families", {}).items():
                    record.families[fname] = FamilyHealthRecord(
                        family=fname,
                        state=fdata.get("state", HEALTHY),
                        reset_at=fdata.get("reset_at"),
                        reason=fdata.get("reason"),
                        last_error=fdata.get("last_error"),
                        error_count=fdata.get("error_count", 0),
                        success_count=fdata.get("success_count", 0),
                        simulated=fdata.get("simulated", False),
                    )
                self._profiles[pid] = record
        except Exception:
            pass

    def _save_state(self) -> None:
        """Atomically persist health state to disk using temporary file + atomic rename."""
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            data: dict[str, Any] = {"profiles": {}}
            for pid, precord in self._profiles.items():
                pdict = {
                    "overall_state": precord.overall_state,
                    "last_used": precord.last_used,
                    "last_success": precord.last_success,
                    "last_error": precord.last_error,
                    "simulated": precord.simulated,
                    "families": {},
                }
                for fname, frecord in precord.families.items():
                    pdict["families"][fname] = {
                        "state": frecord.state,
                        "reset_at": frecord.reset_at,
                        "reason": frecord.reason,
                        "last_error": frecord.last_error,
                        "error_count": frecord.error_count,
                        "success_count": frecord.success_count,
                        "simulated": frecord.simulated,
                    }
                data["profiles"][pid] = pdict

            serialized = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
            
            # Atomic file replace
            tmp_fd, tmp_path = tempfile.mkstemp(
                dir=str(self.state_file.parent),
                prefix="router_state_",
                suffix=".tmp",
            )
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                f.write(serialized)
            
            # Atomic replace (works on Windows & POSIX in Python 3.3+)
            os.replace(tmp_path, str(self.state_file))
        except Exception:
            pass

    def get_or_create(self, profile_id: str) -> ProfileHealthRecord:
        with self._lock:
            if profile_id not in self._profiles:
                self._profiles[profile_id] = ProfileHealthRecord(profile_id=profile_id)
            return self._profiles[profile_id]

    def is_healthy(self, profile_id: str, model_name: Optional[str] = None) -> bool:
        """Check if profile (and specified model family) is healthy and ready for requests."""
        with self._lock:
            record = self.get_or_create(profile_id)
            now = time.time()

            if record.overall_state == DISABLED:
                return False

            # Check profile-level default family
            if "default" in record.families:
                def_rec = record.families["default"]
                if def_rec.state in (QUOTA_EXHAUSTED, RATE_LIMITED, COOLDOWN):
                    if def_rec.reset_at and now >= def_rec.reset_at:
                        def_rec.state = HEALTHY
                        def_rec.reset_at = None
                        def_rec.simulated = False
                    else:
                        return False

            family = extract_model_family(model_name)
            if family in record.families:
                frec = record.families[family]
                if frec.state == QUOTA_EXHAUSTED:
                    if frec.reset_at and now >= frec.reset_at:
                        # Expired cooldown -> reset to healthy
                        frec.state = HEALTHY
                        frec.reset_at = None
                        frec.simulated = False
                        self._save_state()
                        return True
                    return False
                if frec.state in (RATE_LIMITED, COOLDOWN):
                    if frec.reset_at and now >= frec.reset_at:
                        frec.state = HEALTHY
                        frec.reset_at = None
                        frec.simulated = False
                        self._save_state()
                        return True
                    return False
                if frec.state in (AUTH_REQUIRED, UNHEALTHY, DISABLED):
                    return False

            if record.overall_state in (AUTH_REQUIRED, UNHEALTHY, DISABLED, QUOTA_EXHAUSTED, RATE_LIMITED):
                return False

            return True

    def mark_success(self, profile_id: str, model_name: Optional[str] = None) -> None:
        with self._lock:
            record = self.get_or_create(profile_id)
            now = time.time()
            record.last_used = now
            record.last_success = now
            record.overall_state = HEALTHY
            record.simulated = False

            family = extract_model_family(model_name)
            if family in record.families:
                frec = record.families[family]
                frec.state = HEALTHY
                frec.reset_at = None
                frec.success_count += 1
                frec.simulated = False
            if "default" in record.families:
                record.families["default"].state = HEALTHY
                record.families["default"].reset_at = None
                record.families["default"].simulated = False

            self._save_state()

    def mark_quota_exhausted(
        self,
        profile_id: str,
        model_name: Optional[str] = None,
        duration: int = 1800,
        reason: Optional[str] = None,
        simulated: bool = False,
    ) -> None:
        with self._lock:
            record = self.get_or_create(profile_id)
            now = time.time()
            record.last_used = now
            record.last_error = reason
            record.simulated = simulated
            if not model_name or model_name == "default":
                record.overall_state = QUOTA_EXHAUSTED

            family = extract_model_family(model_name)
            if family not in record.families:
                record.families[family] = FamilyHealthRecord(family=family)
            frec = record.families[family]
            frec.state = QUOTA_EXHAUSTED
            frec.reset_at = now + duration
            frec.reason = reason
            frec.last_error = reason
            frec.error_count += 1
            frec.simulated = simulated

            self._save_state()

    def simulate_quota(
        self,
        profile_id: str,
        duration: int = 1800,
        model_family: Optional[str] = None,
    ) -> None:
        """Simulate quota exhaustion on a profile for testing."""
        self.mark_quota_exhausted(
            profile_id=profile_id,
            model_name=model_family,
            duration=duration,
            reason="Simulated Quota Exhaustion",
            simulated=True,
        )

    def mark_rate_limited(
        self,
        profile_id: str,
        model_name: Optional[str] = None,
        duration: int = 60,
        reason: Optional[str] = None,
    ) -> None:
        with self._lock:
            record = self.get_or_create(profile_id)
            now = time.time()
            record.last_used = now
            record.last_error = reason

            family = extract_model_family(model_name)
            if family not in record.families:
                record.families[family] = FamilyHealthRecord(family=family)
            frec = record.families[family]
            frec.state = RATE_LIMITED
            frec.reset_at = now + duration
            frec.reason = reason
            frec.last_error = reason
            frec.error_count += 1

            self._save_state()

    def mark_auth_required(self, profile_id: str, reason: Optional[str] = None) -> None:
        with self._lock:
            record = self.get_or_create(profile_id)
            record.overall_state = AUTH_REQUIRED
            record.last_error = reason
            self._save_state()

    def clear_cooldown(self, profile_id: Optional[str] = None, model_name: Optional[str] = None) -> None:
        with self._lock:
            if profile_id is None:
                for rec in self._profiles.values():
                    rec.overall_state = HEALTHY
                    rec.simulated = False
                    for frec in rec.families.values():
                        frec.state = HEALTHY
                        frec.reset_at = None
                        frec.simulated = False
                self._save_state()
                return

            if profile_id not in self._profiles:
                return
            record = self._profiles[profile_id]
            record.overall_state = HEALTHY
            record.simulated = False
            if model_name:
                family = extract_model_family(model_name)
                if family in record.families:
                    record.families[family].state = HEALTHY
                    record.families[family].reset_at = None
                    record.families[family].simulated = False
            else:
                for frec in record.families.values():
                    frec.state = HEALTHY
                    frec.reset_at = None
                    frec.simulated = False
            self._save_state()
