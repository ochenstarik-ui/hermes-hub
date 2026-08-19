"""Health state and quota tracking per profile and model family."""
from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

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
    """Thread-safe health tracker for router profiles and model families."""

    def __init__(self, state_file: Optional[Path] = None):
        if state_file is None:
            hermes_home = Path(os.environ.get("HERMES_HOME", "~/.hermes")).expanduser()
            if os.name == "nt" and "HERMES_HOME" not in os.environ:
                local_app = os.environ.get("LOCALAPPDATA", "")
                if local_app and (Path(local_app) / "hermes").exists():
                    hermes_home = Path(local_app) / "hermes"
            state_file = hermes_home / "router_state.json"

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
            self.state_file.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
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

            # Check overall reset_at expiration
            if record.overall_state in (QUOTA_EXHAUSTED, RATE_LIMITED, COOLDOWN):
                pass  # Family check will evaluate expiration

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

            if record.overall_state in (AUTH_REQUIRED, UNHEALTHY, DISABLED):
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
            if family not in record.families:
                record.families[family] = FamilyHealthRecord(family=family)
            frec = record.families[family]
            frec.state = HEALTHY
            frec.reset_at = None
            frec.success_count += 1
            frec.simulated = False
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
            reset_at = now + duration
            record.last_used = now
            record.last_error = reason or "Quota exhausted"
            record.simulated = simulated

            family = extract_model_family(model_name)
            if family not in record.families:
                record.families[family] = FamilyHealthRecord(family=family)
            frec = record.families[family]
            frec.state = QUOTA_EXHAUSTED
            frec.reset_at = reset_at
            frec.reason = reason or "Quota exhausted"
            frec.error_count += 1
            frec.simulated = simulated

            # If default/primary family exhausted, reflect in overall state
            record.overall_state = QUOTA_EXHAUSTED
            self._save_state()

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
            reset_at = now + duration
            record.last_used = now
            record.last_error = reason or "Rate limited"

            family = extract_model_family(model_name)
            if family not in record.families:
                record.families[family] = FamilyHealthRecord(family=family)
            frec = record.families[family]
            frec.state = RATE_LIMITED
            frec.reset_at = reset_at
            frec.reason = reason or "Rate limited (HTTP 429)"
            frec.error_count += 1

            record.overall_state = RATE_LIMITED
            self._save_state()

    def mark_auth_required(self, profile_id: str, reason: Optional[str] = None) -> None:
        with self._lock:
            record = self.get_or_create(profile_id)
            record.overall_state = AUTH_REQUIRED
            record.last_error = reason or "Authentication required"
            self._save_state()

    def simulate_quota(
        self,
        profile_id: str,
        model_family: Optional[str] = None,
        duration: int = 600,
    ) -> None:
        """Simulate quota exhaustion for testing without consuming real quota."""
        self.mark_quota_exhausted(
            profile_id=profile_id,
            model_name=model_family,
            duration=duration,
            reason="[SIMULATED] Mock quota exhaustion",
            simulated=True,
        )

    def clear_cooldown(self, profile_id: Optional[str] = None) -> None:
        """Clear all cooldowns, rate limits, and simulated quota states."""
        with self._lock:
            if profile_id:
                if profile_id in self._profiles:
                    precord = self._profiles[profile_id]
                    precord.overall_state = HEALTHY
                    precord.simulated = False
                    for frec in precord.families.values():
                        frec.state = HEALTHY
                        frec.reset_at = None
                        frec.simulated = False
            else:
                for precord in self._profiles.values():
                    precord.overall_state = HEALTHY
                    precord.simulated = False
                    for frec in precord.families.values():
                        frec.state = HEALTHY
                        frec.reset_at = None
                        frec.simulated = False
            self._save_state()

    def get_status_summary(self) -> list[dict[str, Any]]:
        """Return structured summary for all tracked profiles."""
        with self._lock:
            summary = []
            now = time.time()
            for pid, prec in sorted(self._profiles.items()):
                families_list = []
                for fname, frec in sorted(prec.families.items()):
                    remaining = ""
                    if frec.reset_at and frec.reset_at > now:
                        rem_sec = int(frec.reset_at - now)
                        mins = rem_sec // 60
                        secs = rem_sec % 60
                        remaining = f"{mins}m{secs}s"
                    families_list.append({
                        "family": fname,
                        "state": frec.state,
                        "reset_in": remaining,
                        "simulated": frec.simulated,
                    })

                summary.append({
                    "profile_id": pid,
                    "overall_state": prec.overall_state,
                    "active_leases": prec.active_leases,
                    "last_error": prec.last_error,
                    "simulated": prec.simulated,
                    "families": families_list,
                })
            return summary
