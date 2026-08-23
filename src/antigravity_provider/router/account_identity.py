"""Hermes Hub — Unified Account Identity and Quota Abstraction Models.

Defines normalized models for:
- SubscriptionPlan (plan code, display name, source, expiry)
- AccountIdentity (email, display name, org, plan, auth method, status)
- QuotaBucket (percentages, absolute counts, model family, reset time windows)
- QuotaSnapshot (collection of quota buckets, freshness, caching)
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_datetime(val: Any) -> Optional[datetime]:
    if val in (None, ""):
        return None
    if isinstance(val, datetime):
        return val if val.tzinfo else val.replace(tzinfo=timezone.utc)
    if isinstance(val, (int, float)):
        # Handle milliseconds vs seconds
        ts = float(val) / 1000.0 if float(val) > 1e11 else float(val)
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    if isinstance(val, str):
        s = val.strip()
        if not s:
            return None
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(s)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except Exception:
            return None
    return None


@dataclass
class SubscriptionPlan:
    """Normalized subscription plan details."""
    code: str = "UNKNOWN"  # e.g. "PRO", "PLUS", "ULTRA", "MAX", "TEAM", "FREE", "UNKNOWN"
    display_name: str = "Тариф: неизвестен"
    source: str = "provider_api"  # "provider_api", "jwt_claim", "inferred", "unknown"
    expires_at: Optional[datetime] = None
    renews_at: Optional[datetime] = None

    @classmethod
    def create(
        cls,
        raw_code: Optional[str],
        source: str = "provider_api",
        expires_at: Any = None,
        renews_at: Any = None,
    ) -> SubscriptionPlan:
        if not raw_code or not str(raw_code).strip():
            return cls(code="UNKNOWN", display_name="Тариф: неизвестен", source="unknown")

        cleaned = str(raw_code).strip().upper().replace("_", " ").replace("-", " ")
        code_upper = cleaned.split()[0] if cleaned else "UNKNOWN"

        # Standard display names
        display_map = {
            "PRO": "PRO",
            "PLUS": "PLUS",
            "ULTRA": "ULTRA",
            "MAX": "MAX",
            "TEAM": "TEAM",
            "BUSINESS": "BUSINESS",
            "ENTERPRISE": "ENTERPRISE",
            "FREE": "FREE",
            "TIER1": "TIER 1",
            "TIER2": "TIER 2",
            "SUPERGROK": "SUPERGROK",
            "GROK PRO": "GROK PRO",
        }
        disp = display_map.get(cleaned, display_map.get(code_upper, cleaned))
        return cls(
            code=code_upper,
            display_name=disp,
            source=source,
            expires_at=_parse_datetime(expires_at),
            renews_at=_parse_datetime(renews_at),
        )

    def is_known(self) -> bool:
        return self.code != "UNKNOWN"


@dataclass
class AccountIdentity:
    """Normalized account identity across all providers."""
    provider: str
    profile_id: str
    email: Optional[str] = None
    display_name: Optional[str] = None
    account_id: Optional[str] = None
    organization: Optional[str] = None
    plan: SubscriptionPlan = field(default_factory=SubscriptionPlan)
    auth_method: str = "oauth"  # "oauth", "api_key", "imported", "unconfigured"
    authenticated: bool = False
    last_verified_at: Optional[datetime] = None

    def primary_identifier(self) -> str:
        """Resolve highest priority identifier for UI presentation.
        Priority: email -> display_name -> account_id -> profile_id.
        """
        if self.email and self.email.strip():
            return self.email.strip()
        if self.display_name and self.display_name.strip():
            return self.display_name.strip()
        if self.account_id and self.account_id.strip():
            return self.account_id.strip()
        return self.profile_id

    def masked_identifier(self) -> str:
        """Return privacy-safe masked identifier."""
        raw = self.primary_identifier()
        if "@" in raw:
            parts = raw.split("@")
            user, domain = parts[0], parts[1]
            if len(user) <= 2:
                masked_user = user[0] + "***"
            else:
                masked_user = user[0] + "***" + user[-1]
            return f"{masked_user}@{domain}"
        if len(raw) > 10:
            return f"{raw[:4]}...{raw[-4:]}"
        return raw


@dataclass
class QuotaBucket:
    """Normalized quota bucket representing a single limit pool."""
    id: str  # e.g. "antigravity.claude.5h", "codex.weekly", "grok.frequent_tasks"
    display_name: str  # e.g. "5h", "Weekly", "Частые задачи"
    model_family: Optional[str] = None  # "claude", "gemini", "gpt", "grok", "opencode"
    used_percent: Optional[float] = None
    remaining_percent: Optional[float] = None
    used_absolute: Optional[int] = None
    remaining_absolute: Optional[int] = None
    limit_absolute: Optional[int] = None
    reset_at: Optional[datetime] = None
    reset_in_seconds: Optional[int] = None
    period: Optional[str] = None  # "5h", "7d", "30d", "sliding"
    unit: Optional[str] = None  # requests, tokens, tasks, currency, or provider-defined
    scope: Optional[str] = None  # account, model_family, organization, or provider-defined
    status: str = "unknown"  # "healthy", "warning", "exhausted", "unknown"

    @property
    def label(self) -> str:
        return self.display_name

    @property
    def used(self) -> Optional[int]:
        return self.used_absolute

    @property
    def limit(self) -> Optional[int]:
        return self.limit_absolute

    def __post_init__(self):
        # Auto-reconcile percentages
        if self.remaining_percent is None and self.used_percent is not None:
            self.remaining_percent = max(0.0, min(100.0, 100.0 - float(self.used_percent)))
        elif self.used_percent is None and self.remaining_percent is not None:
            self.used_percent = max(0.0, min(100.0, 100.0 - float(self.remaining_percent)))

        # Auto-determine status
        if self.remaining_percent is not None:
            if self.remaining_percent <= 0.0 or (self.used_percent is not None and self.used_percent >= 100.0):
                self.status = "exhausted"
            elif self.remaining_percent < 15.0:
                self.status = "warning"
            else:
                self.status = "healthy"
        elif self.remaining_absolute is not None and self.limit_absolute is not None:
            if self.remaining_absolute <= 0:
                self.status = "exhausted"
            elif self.remaining_absolute / max(1, self.limit_absolute) < 0.15:
                self.status = "warning"
            else:
                self.status = "healthy"

    @property
    def is_exhausted(self) -> bool:
        return self.status == "exhausted"

    def formatted_remaining(self) -> str:
        """User-facing unambiguous string."""
        if self.remaining_absolute is not None and self.limit_absolute is not None:
            used = self.used_absolute if self.used_absolute is not None else (self.limit_absolute - self.remaining_absolute)
            rem_pct_str = f" · Осталось {self.remaining_percent:.0f}%" if self.remaining_percent is not None else ""
            return f"{used}/{self.limit_absolute}{rem_pct_str}"
        if self.remaining_percent is not None:
            return f"Осталось {self.remaining_percent:.0f}%"
        if self.used_percent is not None:
            return f"Использовано {self.used_percent:.0f}%"
        return "Н/Д"

    def formatted_reset(self) -> Optional[str]:
        """User-facing reset time string."""
        if self.reset_at:
            delta = self.reset_at - _utc_now()
            tot_sec = int(delta.total_seconds())
            if tot_sec <= 0:
                return "Сброс: сейчас"
            hrs, rem = divmod(tot_sec, 3600)
            mins = rem // 60
            if hrs >= 24:
                days, hrs = divmod(hrs, 24)
                return f"Сброс через {days}д {hrs}ч"
            if hrs > 0:
                return f"Сброс через {hrs}ч {mins}м"
            return f"Сброс через {max(1, mins)}м"
        if self.reset_in_seconds and self.reset_in_seconds > 0:
            hrs, rem = divmod(self.reset_in_seconds, 3600)
            mins = rem // 60
            if hrs > 0:
                return f"Сброс через {hrs}ч {mins}м"
            return f"Сброс через {max(1, mins)}м"
        return None


@dataclass
class QuotaSnapshot:
    """Normalized snapshot of all quota buckets for a provider profile."""
    account_id: str
    provider: str
    buckets: List[QuotaBucket] = field(default_factory=list)
    fetched_at: datetime = field(default_factory=_utc_now)
    stale_after_seconds: int = 300
    source: str = "baseline"
    unavailable_reason: Optional[str] = None
    is_loading: bool = False

    @property
    def is_estimated(self) -> bool:
        """True if values are baseline or locally estimated rather than measured by live server API."""
        return self.source in (
            "baseline",
            "estimated",
            "unconfigured",
            "local_heuristic",
            "runtime_error",
        )

    def is_stale(self) -> bool:
        delta = _utc_now() - self.fetched_at
        return delta.total_seconds() > self.stale_after_seconds

    def freshness_label(self) -> str:
        delta = _utc_now() - self.fetched_at
        sec = int(delta.total_seconds())
        if sec < 45:
            return "Обновлено: только что"
        mins = sec // 60
        if mins < 60:
            return f"Обновлено: {mins} мин назад"
        hrs = mins // 60
        return f"Обновлено: {hrs} ч назад"

    def get_bucket_for_model(self, model_or_family: str) -> Optional[QuotaBucket]:
        """Find the most constraining quota bucket for a model family."""
        target = model_or_family.lower()
        matches = [b for b in self.buckets if b.model_family and b.model_family.lower() in target]
        if matches:
            measured = [b for b in matches if b.remaining_percent is not None]
            if measured:
                return min(measured, key=lambda bucket: float(bucket.remaining_percent or 0.0))
            return matches[0]
        # Fallback to first available bucket
        return self.buckets[0] if self.buckets else None

    def is_model_available(self, model_or_family: str) -> bool:
        """True if the quota bucket governing this model is healthy."""
        bucket = self.get_bucket_for_model(model_or_family)
        if not bucket:
            return True  # If no bucket defined, assume available
        return not bucket.is_exhausted
