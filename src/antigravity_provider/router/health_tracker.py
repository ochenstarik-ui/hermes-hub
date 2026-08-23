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
    auth_error_at: Optional[float] = None
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


class _FileLock:
    """Interprocess file lock supporting Windows (msvcrt) and Unix (fcntl)."""

    def __init__(self, lock_path: Path):
        self.lock_path = lock_path
        self._fd: Optional[int] = None

    def __enter__(self):
        try:
            self.lock_path.parent.mkdir(parents=True, exist_ok=True)
            self._fd = os.open(str(self.lock_path), os.O_CREAT | os.O_RDWR)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self._fd, msvcrt.LK_LOCK, 1)
            else:
                import fcntl
                fcntl.flock(self._fd, fcntl.LOCK_EX)
        except Exception:
            if self._fd is not None:
                try:
                    os.close(self._fd)
                except Exception:
                    pass
                self._fd = None
            raise
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._fd is not None:
            try:
                if os.name == "nt":
                    import msvcrt
                    try:
                        msvcrt.locking(self._fd, msvcrt.LK_UNLCK, 1)
                    except Exception:
                        pass
                else:
                    import fcntl
                    try:
                        fcntl.flock(self._fd, fcntl.LOCK_UN)
                    except Exception:
                        pass
                os.close(self._fd)
            except Exception:
                pass
            self._fd = None


class HealthTracker:
    """Thread-safe health tracker for router profiles and model families with atomic disk persistence and interprocess locking."""

    def __init__(self, state_file: Optional[Path] = None):
        if state_file is None:
            state_file = paths.get_router_state_path()

        self.state_file = state_file
        self.lock_file = self.state_file.with_suffix(".lock")
        self._lock = threading.RLock()
        self._profiles: dict[str, ProfileHealthRecord] = {}
        self._load_state()

        try:
            from antigravity_provider.router.event_bus import (
                EVENT_ACCOUNT_ADDED,
                EVENT_ACCOUNT_AUTH_CHANGED,
                EventBus,
            )
            EventBus.get().subscribe(EVENT_ACCOUNT_ADDED, self._on_account_event)
            EventBus.get().subscribe(EVENT_ACCOUNT_AUTH_CHANGED, self._on_account_event)
        except Exception:
            pass

    def _on_account_event(self, _event_name: str, payload: Any) -> None:
        """Handle account lifecycle events by recovering profile from AUTH_REQUIRED state."""
        profile_id = None
        if isinstance(payload, dict):
            profile_id = payload.get("profile_id")
        elif hasattr(payload, "profile_id"):
            profile_id = getattr(payload, "profile_id")
        if not profile_id:
            return
        profile_id = str(profile_id)
        with self._lock:
            if profile_id in self._profiles:
                rec = self._profiles[profile_id]
                rec.overall_state = HEALTHY
                rec.last_error = None
                rec.auth_error_at = None
                for frec in rec.families.values():
                    if frec.state == AUTH_REQUIRED:
                        frec.state = HEALTHY
                        frec.reset_at = None
                        frec.reason = None
                        frec.last_error = None
                self._save_state()

    def _find_profile_auth_files(self, profile_id: str) -> list[Path]:
        """Locate credentials and auth files for the specified profile."""
        files: list[Path] = []
        try:
            pdir = paths.get_profile_dir(profile_id)
            for cand in (pdir / "auth.json", pdir / ".gemini" / "oauth_creds.json", pdir / "oauth_creds.json"):
                if cand.is_file():
                    files.append(cand)
        except Exception:
            pass

        try:
            hermes_home = paths.get_hermes_home()
            if hermes_home.is_dir():
                for pdir in hermes_home.glob(f"*_profiles/{profile_id}"):
                    if pdir.is_dir():
                        for cand in (pdir / "auth.json", pdir / ".gemini" / "oauth_creds.json", pdir / "oauth_creds.json"):
                            if cand.is_file() and cand not in files:
                                files.append(cand)
        except Exception:
            pass
        return files

    def _check_and_recover_auth(self, record: ProfileHealthRecord) -> bool:
        """Check if auth files exist, are valid, and were modified after an auth failure."""
        auth_files = self._find_profile_auth_files(record.profile_id)
        if not auth_files:
            return False

        recovered = False
        for f in auth_files:
            try:
                stat = f.stat()
                if stat.st_size == 0:
                    continue
                if record.auth_error_at is not None and stat.st_mtime <= record.auth_error_at:
                    continue
                content = json.loads(f.read_text(encoding="utf-8"))
                if isinstance(content, dict) and len(content) > 0:
                    recovered = True
                    break
            except Exception:
                continue

        if recovered:
            record.overall_state = HEALTHY
            record.last_error = None
            record.auth_error_at = None
            for frec in record.families.values():
                if frec.state == AUTH_REQUIRED:
                    frec.state = HEALTHY
                    frec.reset_at = None
                    frec.reason = None
                    frec.last_error = None
            self._save_state()
            return True
        return False

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
                    auth_error_at=pdata.get("auth_error_at"),
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
        """Atomically persist health state to disk with interprocess locking and temporary file replace."""
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            data: dict[str, Any] = {"profiles": {}}
            for pid, precord in self._profiles.items():
                pdict = {
                    "overall_state": precord.overall_state,
                    "last_used": precord.last_used,
                    "last_success": precord.last_success,
                    "last_error": precord.last_error,
                    "auth_error_at": precord.auth_error_at,
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

            with _FileLock(self.lock_file):
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
            rec = self._profiles[profile_id]
            try:
                from .session_affinity import LeaseManager
                rec.active_leases = LeaseManager.get().active_count(profile_id)
            except Exception:
                pass
            return rec

    def is_healthy(self, profile_id: str, model_name: Optional[str] = None) -> bool:
        """Check if profile (and specified model family) is healthy and ready for requests."""
        with self._lock:
            record = self.get_or_create(profile_id)
            now = time.time()

            if record.overall_state == DISABLED:
                return False

            if record.overall_state == AUTH_REQUIRED:
                self._check_and_recover_auth(record)

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
            record.auth_error_at = None
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

    def reconcile_measured_quota(self, profile_id: str, remaining_by_family: Dict[str, float]) -> bool:
        """Clear stale quota-exhausted flags when the provider reports live capacity.

        A successful quota read is authoritative for quota exhaustion, but it
        must not erase unrelated authentication or runtime failures.
        """
        measured = {family: float(value) for family, value in remaining_by_family.items()}
        if not measured:
            return False
        with self._lock:
            record = self.get_or_create(profile_id)
            changed = False
            for family, remaining in measured.items():
                family_record = record.families.get(family)
                if remaining > 0 and family_record and family_record.state == QUOTA_EXHAUSTED:
                    family_record.state = HEALTHY
                    family_record.reset_at = None
                    family_record.reason = None
                    family_record.last_error = None
                    family_record.simulated = False
                    changed = True
            if all(value > 0 for value in measured.values()) and record.overall_state == QUOTA_EXHAUSTED:
                record.overall_state = HEALTHY
                record.last_error = None
                record.simulated = False
                changed = True
            if changed:
                self._save_state()
            return changed

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
            record.auth_error_at = time.time()
            self._save_state()

    def clear_cooldown(self, profile_id: Optional[str] = None, model_name: Optional[str] = None) -> None:
        with self._lock:
            if profile_id is None:
                for rec in self._profiles.values():
                    rec.overall_state = HEALTHY
                    rec.last_error = None
                    rec.auth_error_at = None
                    rec.simulated = False
                    for frec in rec.families.values():
                        frec.state = HEALTHY
                        frec.reset_at = None
                        frec.reason = None
                        frec.last_error = None
                        frec.simulated = False
                self._save_state()
                return

            if profile_id not in self._profiles:
                return
            record = self._profiles[profile_id]
            record.overall_state = HEALTHY
            record.last_error = None
            record.auth_error_at = None
            record.simulated = False
            if model_name:
                family = extract_model_family(model_name)
                if family in record.families:
                    record.families[family].state = HEALTHY
                    record.families[family].reset_at = None
                    record.families[family].reason = None
                    record.families[family].last_error = None
                    record.families[family].simulated = False
            else:
                for frec in record.families.values():
                    frec.state = HEALTHY
                    frec.reset_at = None
                    frec.reason = None
                    frec.last_error = None
                    frec.simulated = False
            self._save_state()
