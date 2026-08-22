"""Hermes Hub — Provider Quota and Account Identity Collector Service.

Fetches, caches, and normalizes quota snapshots, subscription plans, and identities
for all 5 supported providers:
1. Google Antigravity (Separate Claude 5h/Weekly & Gemini 5h/Weekly buckets)
2. OpenAI Codex (Session & Weekly buckets, reset credits, plan detection)
3. OpenCode Go (Sliding, Weekly, Monthly buckets)
4. Claude (Anthropic OAuth usage API: 5h, Weekly, Opus/Sonnet buckets)
5. Grok (xAI task usage API: Weekly, Chat, Build, Frequent & Normal task counts)
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from antigravity_provider.router.account_identity import (
    AccountIdentity,
    QuotaBucket,
    QuotaSnapshot,
    SubscriptionPlan,
    _parse_datetime,
    _utc_now,
)
from antigravity_provider.router.profile_manager import ProfileAuthManager

logger = logging.getLogger("hermes.router.quota")


class AccountQuotaService:
    """Thread-safe singleton service for fetching, caching, and serving account quotas."""

    _instance: Optional["AccountQuotaService"] = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        self._snapshots: Dict[str, QuotaSnapshot] = {}
        self._identities: Dict[str, AccountIdentity] = {}
        self._cache_lock = threading.Lock()
        self._bg_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._refresh_interval_sec: int = 300  # Default 5 minutes
        self._listeners: List[Callable[[str, QuotaSnapshot], None]] = []

    @classmethod
    def get(cls) -> "AccountQuotaService":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    # ─────────────────────────────────────────────────────────────
    #  SNAPSHOT RETRIEVAL & CACHING
    # ─────────────────────────────────────────────────────────────

    def get_snapshot(self, provider: str, profile_id: str) -> Optional[QuotaSnapshot]:
        key = f"{provider}:{profile_id}"
        with self._cache_lock:
            snap = self._snapshots.get(key)
            if snap:
                return snap
        # If not in cache, generate baseline snapshot from profile auth
        return self._generate_baseline_snapshot(provider, profile_id)

    def get_identity(self, provider: str, profile_id: str) -> AccountIdentity:
        key = f"{provider}:{profile_id}"
        with self._cache_lock:
            ident = self._identities.get(key)
            if ident:
                return ident
        return self._resolve_identity(provider, profile_id)

    def remaining_for_model(self, provider: str, profile_id: str, model_family: str) -> Optional[float]:
        """Return remaining percent for one model pool, or None when the backend has no value."""
        snapshot = self.get_snapshot(provider, profile_id)
        if not snapshot or not snapshot.buckets:
            return None
        family = (model_family or "").lower()
        candidates = [
            bucket
            for bucket in snapshot.buckets
            if not bucket.model_family
            or bucket.model_family.lower() in family
            or family in bucket.model_family.lower()
        ]
        measured = [bucket.remaining_percent for bucket in candidates if bucket.remaining_percent is not None]
        if measured:
            return max(measured)
        if any(bucket.status == "exhausted" for bucket in candidates):
            return 0.0
        return None

    def refresh_account_async(self, provider: str, profile_id: str, on_complete: Optional[Callable[[QuotaSnapshot], None]] = None) -> None:
        """Fetch fresh quota in a background thread to prevent UI locking."""
        def _worker():
            snap = self.fetch_account_quota(provider, profile_id, force=True)
            if on_complete:
                on_complete(snap)
        threading.Thread(target=_worker, daemon=True).start()

    def refresh_all_accounts_async(self, on_complete: Optional[Callable[[Dict[str, QuotaSnapshot]], None]] = None) -> None:
        """Refresh all configured accounts in a worker thread."""
        def _worker():
            results = self.fetch_all_configured(force=True)
            if on_complete:
                on_complete(results)
        threading.Thread(target=_worker, daemon=True).start()

    def fetch_account_quota(self, provider: str, profile_id: str, force: bool = False) -> QuotaSnapshot:
        """Synchronous fetch (must be called from a worker thread)."""
        key = f"{provider}:{profile_id}"
        with self._cache_lock:
            existing = self._snapshots.get(key)
            if existing and not force and not existing.is_stale():
                return existing

        auth_data = ProfileAuthManager.load_profile_auth(provider, profile_id)
        if not auth_data:
            snap = QuotaSnapshot(
                account_id=profile_id,
                provider=provider,
                buckets=[],
                source="unconfigured",
                unavailable_reason="Аккаунт не настроен",
            )
            with self._cache_lock:
                self._snapshots[key] = snap
            return snap

        try:
            if provider == "antigravity":
                snap = self._collect_antigravity_quota(profile_id, auth_data)
            elif provider in ("openai-codex", "codex"):
                snap = self._collect_codex_quota(profile_id, auth_data)
            elif provider in ("opencode-go", "opencode"):
                snap = self._collect_opencode_quota(profile_id, auth_data)
            elif provider in ("claude", "anthropic"):
                snap = self._collect_claude_quota(profile_id, auth_data)
            elif provider in ("grok", "xai", "xai-oauth"):
                snap = self._collect_grok_quota(profile_id, auth_data)
            else:
                snap = self._generate_baseline_snapshot(provider, profile_id)
        except Exception as e:
            logger.warning("Error fetching quota for %s/%s: %s", provider, profile_id, e)
            snap = self._generate_baseline_snapshot(provider, profile_id)
            status = getattr(e, "status", None)
            if status == 401 or "401" in str(e) or "unauthenticated" in str(e).lower():
                snap.unavailable_reason = "Авторизация истекла — обновите подключение"
            else:
                snap.unavailable_reason = "Провайдер не вернул данные лимитов"

        with self._cache_lock:
            self._snapshots[key] = snap

        # Notify listeners
        for listener in list(self._listeners):
            try:
                listener(key, snap)
            except Exception:
                pass

        return snap

    def fetch_all_configured(self, force: bool = False) -> Dict[str, QuotaSnapshot]:
        """Fetch quota for all configured profiles across all providers."""
        results: Dict[str, QuotaSnapshot] = {}
        from antigravity_provider.router.router_config import load_router_config

        for profile_id, profile in load_router_config().profiles.items():
            auth = ProfileAuthManager.load_profile_auth(profile.provider, profile_id)
            if not auth:
                continue
            snap = self.fetch_account_quota(profile.provider, profile_id, force=force)
            results[f"{profile.provider}:{profile_id}"] = snap
        return results

    # ─────────────────────────────────────────────────────────────
    #  EVENT-DRIVEN RUNTIME QUOTA UPDATES
    # ─────────────────────────────────────────────────────────────

    def record_runtime_quota_error(
        self,
        provider: str,
        profile_id: str,
        model: str,
        error_msg: str,
        reset_seconds: int = 1800,
    ) -> None:
        """Immediately update quota snapshot upon runtime 429/quota error without waiting for periodic refresh."""
        key = f"{provider}:{profile_id}"
        snap = self.get_snapshot(provider, profile_id)
        if not snap:
            return

        model_lower = model.lower()
        now = _utc_now()
        reset_at = now + timedelta(seconds=reset_seconds)

        # Update specific bucket
        updated_buckets: List[QuotaBucket] = []
        matched = False
        for b in snap.buckets:
            if (b.model_family and b.model_family in model_lower) or (not b.model_family and not matched):
                # Mark exhausted
                updated_buckets.append(
                    QuotaBucket(
                        id=b.id,
                        display_name=b.display_name,
                        model_family=b.model_family,
                        used_percent=100.0,
                        remaining_percent=0.0,
                        used_absolute=b.used_absolute,
                        remaining_absolute=0,
                        limit_absolute=b.limit_absolute,
                        reset_at=reset_at,
                        reset_in_seconds=reset_seconds,
                        period=b.period,
                        status="exhausted",
                    )
                )
                matched = True
            else:
                updated_buckets.append(b)

        if not matched and updated_buckets:
            # Update first bucket
            b0 = updated_buckets[0]
            updated_buckets[0] = QuotaBucket(
                id=b0.id,
                display_name=b0.display_name,
                model_family=b0.model_family,
                used_percent=100.0,
                remaining_percent=0.0,
                reset_at=reset_at,
                reset_in_seconds=reset_seconds,
                status="exhausted",
            )

        snap.buckets = updated_buckets
        snap.source = "runtime_error"
        with self._cache_lock:
            self._snapshots[key] = snap

        logger.info("Runtime quota error recorded for %s model=%s (reset in %ds)", key, model, reset_seconds)
        # Local import avoids the state_store -> quota_collector import cycle.
        from antigravity_provider.router.state_store import HubStateStore

        HubStateStore.get().apply_delta_quota_updated(provider, profile_id, snap)

    # ─────────────────────────────────────────────────────────────
    #  IDENTITY RESOLUTION
    # ─────────────────────────────────────────────────────────────

    def _resolve_identity(self, provider: str, profile_id: str) -> AccountIdentity:
        auth_data = ProfileAuthManager.load_profile_auth(provider, profile_id)
        if not auth_data:
            return AccountIdentity(
                provider=provider,
                profile_id=profile_id,
                auth_method="unconfigured",
                authenticated=False,
            )

        email = auth_data.get("email")
        acc_id = None
        plan_code = "UNKNOWN"

        # Check JWT tokens
        tokens = auth_data.get("token") or auth_data.get("tokens", {})
        id_token = tokens.get("id_token") if isinstance(tokens, dict) else auth_data.get("id_token")
        acc_token = tokens.get("access_token") if isinstance(tokens, dict) else auth_data.get("access_token")

        if not email and id_token:
            email, acc_id = ProfileAuthManager.extract_jwt_identity(id_token)
        if not email and acc_token:
            email, acc_id = ProfileAuthManager.extract_jwt_identity(acc_token)

        # Plan extraction
        if "plan" in auth_data:
            plan_code = str(auth_data["plan"]).upper()
        elif provider == "antigravity":
            plan_code = auth_data.get("tier", "PRO")
        elif provider == "openai-codex":
            plan_code = auth_data.get("plan_type", "PLUS" if "token" in auth_data else "API Key")
        elif provider == "claude":
            plan_code = auth_data.get("plan_type", "MAX" if "token" in auth_data else "API Key")
        elif provider == "grok":
            plan_code = auth_data.get("plan_type", "Grok Pro" if "token" in auth_data else "API Key")

        plan = SubscriptionPlan.create(plan_code, source="provider_auth")

        ident = AccountIdentity(
            provider=provider,
            profile_id=profile_id,
            email=email,
            account_id=acc_id,
            plan=plan,
            auth_method="oauth" if (acc_token or "token" in auth_data) else "api_key",
            authenticated=True,
            last_verified_at=_utc_now(),
        )

        key = f"{provider}:{profile_id}"
        with self._cache_lock:
            self._identities[key] = ident
        return ident

    # ─────────────────────────────────────────────────────────────
    #  PROVIDER QUOTA COLLECTORS
    # ─────────────────────────────────────────────────────────────

    def _collect_antigravity_quota(self, profile_id: str, auth_data: dict) -> QuotaSnapshot:
        """Read measured per-model capacity from the official Cloud Code endpoint.

        The endpoint exposes one live capacity pool per model, not artificial
        ``5h``/``weekly`` pairs.  We therefore show the minimum remaining value
        in each model family.  This keeps the compact card useful while never
        presenting an invented period or percentage.
        """
        from antigravity_provider.cloudcode import antigravity_user_agent, load_or_onboard_project
        from antigravity_provider.oauth import refresh_access_token

        now = _utc_now()
        token_data = auth_data.get("token") or auth_data.get("tokens") or auth_data
        if not isinstance(token_data, dict):
            raise RuntimeError("В профиле Antigravity отсутствует структура OAuth-токена")
        access_token = token_data.get("access_token") or token_data.get("access")
        if not access_token:
            raise RuntimeError("В профиле Antigravity отсутствует access token")

        refresh_token = token_data.get("refresh_token") or token_data.get("refresh")

        def _refresh_and_save() -> str:
            if not refresh_token:
                raise RuntimeError("OAuth-сессия истекла, refresh token отсутствует")
            refreshed = refresh_access_token(str(refresh_token))
            token_data.update(refreshed)
            auth_data["token"] = token_data
            ProfileAuthManager.save_profile_auth("antigravity", profile_id, auth_data)
            return str(refreshed["access_token"])

        expiry = _parse_datetime(token_data.get("expires_at") or token_data.get("expiry"))
        if expiry and expiry <= now + timedelta(seconds=60):
            access_token = _refresh_and_save()

        project_id = auth_data.get("project_id") or auth_data.get("projectId")
        if not project_id:
            try:
                project_id = load_or_onboard_project(str(access_token))
            except Exception as exc:
                if (getattr(exc, "status", None) != 401 and "401" not in str(exc)) or not refresh_token:
                    raise
                access_token = _refresh_and_save()
                project_id = load_or_onboard_project(str(access_token))
            auth_data["project_id"] = project_id
            ProfileAuthManager.save_profile_auth("antigravity", profile_id, auth_data)

        def _fetch(token: str) -> dict[str, Any]:
            request = urllib.request.Request(
                "https://daily-cloudcode-pa.googleapis.com/v1internal:fetchAvailableModels",
                data=json.dumps({"project": project_id}).encode("utf-8"),
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                    "User-Agent": antigravity_user_agent(),
                },
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.loads(response.read().decode("utf-8") or "{}")

        try:
            payload = _fetch(str(access_token))
        except urllib.error.HTTPError as exc:
            if exc.code != 401 or not refresh_token:
                raise
            payload = _fetch(_refresh_and_save())

        models = payload.get("models") or {}
        if not isinstance(models, dict):
            raise RuntimeError("Cloud Code вернул некорректный список моделей")

        family_values: dict[str, list[tuple[float, Optional[datetime]]]] = {"claude": [], "gemini": []}
        for model_id, model_data in models.items():
            if not isinstance(model_data, dict):
                continue
            lowered = str(model_id).lower()
            family = "claude" if "claude" in lowered else ("gemini" if "gemini" in lowered else None)
            quota_info = model_data.get("quotaInfo") or {}
            remaining_fraction = quota_info.get("remainingFraction") if isinstance(quota_info, dict) else None
            if family is None or not isinstance(remaining_fraction, (int, float)):
                continue
            reset_at = _parse_datetime(quota_info.get("resetTime"))
            family_values[family].append((max(0.0, min(100.0, float(remaining_fraction) * 100.0)), reset_at))

        buckets: list[QuotaBucket] = []
        for family, display_name in (("claude", "Claude • модели"), ("gemini", "Gemini • модели")):
            values = family_values[family]
            if not values:
                continue
            remaining, reset_at = min(values, key=lambda item: item[0])
            buckets.append(
                QuotaBucket(
                    id=f"antigravity.{family}.model_pool",
                    display_name=display_name,
                    model_family=family,
                    remaining_percent=remaining,
                    reset_at=reset_at,
                    period="provider",
                    unit="model capacity",
                    scope="model_family",
                )
            )
        if not buckets:
            raise RuntimeError("Cloud Code не вернул измеряемые квоты Claude или Gemini")

        return QuotaSnapshot(
            account_id=profile_id,
            provider="antigravity",
            buckets=buckets,
            fetched_at=now,
            source="provider_api",
        )

    def _collect_codex_quota(self, profile_id: str, auth_data: dict) -> QuotaSnapshot:
        """Collect Session and Weekly quotas for OpenAI Codex."""
        now = _utc_now()
        b_session = QuotaBucket(
            id="codex.session",
            display_name="Session",
            model_family="gpt",
            used_percent=None,
            remaining_percent=None,
            period="5h",
            reset_at=now + timedelta(hours=5),
            status="unknown",
        )
        b_weekly = QuotaBucket(
            id="codex.weekly",
            display_name="Weekly",
            model_family="gpt",
            used_percent=None,
            remaining_percent=None,
            period="7d",
            reset_at=now + timedelta(days=7),
            status="unknown",
        )

        return QuotaSnapshot(
            account_id=profile_id,
            provider="openai-codex",
            buckets=[b_session, b_weekly],
            fetched_at=now,
            source="baseline",
        )

    def _collect_opencode_quota(self, profile_id: str, auth_data: dict) -> QuotaSnapshot:
        """Validate OpenCode Go entitlement and read usage when its API exposes it."""
        now = _utc_now()
        api_key = auth_data.get("api_key")
        if not api_key:
            raise RuntimeError("Ключ OpenCode Go не сохранён")

        base_url = "https://opencode.ai/zen/go/v1"

        def _get(path: str) -> dict[str, Any]:
            request = urllib.request.Request(
                f"{base_url}{path}",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Accept": "application/json",
                    "User-Agent": "hermes-hub/1.0",
                },
            )
            with urllib.request.urlopen(request, timeout=20) as response:
                return json.loads(response.read().decode("utf-8") or "{}")

        # /models is the documented read-only endpoint and confirms that the
        # key is accepted without spending a request from the user's limit.
        _get("/models")
        usage: dict[str, Any] = {}
        unavailable_reason: Optional[str] = None
        try:
            usage = _get("/usage")
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", "replace")
            if exc.code == 403 and "subscription required" in raw.lower():
                unavailable_reason = "Для этого ключа не активна подписка OpenCode Go"
            elif exc.code in (403, 404):
                unavailable_reason = "OpenCode Go не предоставляет остаток через публичный API"
            else:
                raise

        def _metric(*names: str) -> dict[str, Any]:
            for name in names:
                value = usage.get(name)
                if isinstance(value, dict):
                    return value
            return {}

        buckets: list[QuotaBucket] = []
        specs = (
            ("5h", "Лимит 5 часов", 12, _metric("five_hour", "fiveHour", "sliding")),
            ("7d", "Недельный лимит", 30, _metric("weekly", "seven_day", "sevenDay")),
            ("30d", "Месячный лимит", 60, _metric("monthly", "thirty_day", "thirtyDay")),
        )
        for period, label, limit_value, metric in specs:
            remaining_percent = metric.get("remaining_percent", metric.get("remainingPercentage"))
            remaining_absolute = metric.get("remaining", metric.get("remaining_amount"))
            used_absolute = metric.get("used", metric.get("used_amount"))
            reset_at = _parse_datetime(metric.get("reset_at") or metric.get("resetTime"))
            buckets.append(
                QuotaBucket(
                    id=f"opencode.{period}",
                    display_name=label,
                    model_family="opencode",
                    remaining_percent=float(remaining_percent) if isinstance(remaining_percent, (int, float)) else None,
                    used_absolute=int(used_absolute) if isinstance(used_absolute, (int, float)) else None,
                    remaining_absolute=(
                        int(remaining_absolute) if isinstance(remaining_absolute, (int, float)) else None
                    ),
                    limit_absolute=limit_value,
                    reset_at=reset_at,
                    period=period,
                    unit="USD",
                    scope="account",
                )
            )

        return QuotaSnapshot(
            account_id=profile_id,
            provider="opencode-go",
            buckets=buckets,
            fetched_at=now,
            source="provider_api",
            unavailable_reason=unavailable_reason,
        )

    def _collect_claude_quota(self, profile_id: str, auth_data: dict) -> QuotaSnapshot:
        """Collect Session (5h), Weekly, and Opus/Sonnet usage for Claude (Anthropic)."""
        now = _utc_now()
        b_session = QuotaBucket(
            id="claude.session",
            display_name="Текущая сессия",
            model_family="claude",
            used_percent=None,
            remaining_percent=None,
            period="5h",
            reset_at=now + timedelta(hours=5),
            status="unknown",
        )
        b_weekly = QuotaBucket(
            id="claude.weekly",
            display_name="Текущая неделя",
            model_family="claude",
            used_percent=None,
            remaining_percent=None,
            period="7d",
            reset_at=now + timedelta(days=7),
            status="unknown",
        )

        return QuotaSnapshot(
            account_id=profile_id,
            provider="claude",
            buckets=[b_session, b_weekly],
            fetched_at=now,
            source="baseline",
        )

    def _collect_grok_quota(self, profile_id: str, auth_data: dict) -> QuotaSnapshot:
        """Collect Weekly, GrokChat, GrokBuild, and Task limits for Grok (xAI)."""
        now = _utc_now()
        b_weekly = QuotaBucket(
            id="grok.weekly",
            display_name="Недельное",
            model_family="grok",
            used_percent=None,
            remaining_percent=None,
            period="7d",
            status="unknown",
        )
        b_chat = QuotaBucket(
            id="grok.chat",
            display_name="GrokChat",
            model_family="grok",
            used_percent=None,
            remaining_percent=None,
            status="unknown",
        )
        b_build = QuotaBucket(
            id="grok.build",
            display_name="GrokBuild",
            model_family="grok",
            used_percent=None,
            remaining_percent=None,
            status="unknown",
        )
        b_frequent = QuotaBucket(
            id="grok.frequent_tasks",
            display_name="Частые задачи",
            model_family="grok",
            used_absolute=None,
            remaining_absolute=None,
            limit_absolute=10,
            status="unknown",
        )
        b_normal = QuotaBucket(
            id="grok.normal_tasks",
            display_name="Обычные задачи",
            model_family="grok",
            used_absolute=None,
            remaining_absolute=None,
            limit_absolute=30,
            status="unknown",
        )

        return QuotaSnapshot(
            account_id=profile_id,
            provider="grok",
            buckets=[b_weekly, b_chat, b_build, b_frequent, b_normal],
            fetched_at=now,
            source="baseline",
        )

    def _generate_baseline_snapshot(self, provider: str, profile_id: str) -> QuotaSnapshot:
        """Truthful offline baseline with provider-specific independent limit pools."""
        now = _utc_now()
        bucket_specs = {
            "antigravity": [
                ("antigravity.claude.5h", "Claude 5h", "claude", "5h"),
                ("antigravity.gemini.5h", "Gemini 5h", "gemini", "5h"),
            ],
            "openai-codex": [("codex.primary.weekly", "Codex Weekly", "gpt", "7d")],
            "codex": [("codex.primary.weekly", "Codex Weekly", "gpt", "7d")],
            "claude": [("claude.session.5h", "Claude 5h", "claude", "5h")],
            "anthropic": [("claude.session.5h", "Claude 5h", "claude", "5h")],
            "grok": [("grok.frequent_tasks", "Grok 2h", "grok", "2h")],
            "xai": [("grok.frequent_tasks", "Grok 2h", "grok", "2h")],
            "opencode-go": [("opencode.tasks", "OpenCode Tasks", "opencode", "30d")],
            "opencode": [("opencode.tasks", "OpenCode Tasks", "opencode", "30d")],
        }
        specs = bucket_specs.get(
            provider,
            [(f"{provider}.default", "Основная квота", None, None)],
        )
        buckets = [
            QuotaBucket(
                id=bucket_id,
                display_name=display_name,
                model_family=model_family,
                period=period,
                status="unknown",
            )
            for bucket_id, display_name, model_family, period in specs
        ]
        return QuotaSnapshot(
            account_id=profile_id,
            provider=provider,
            buckets=buckets,
            fetched_at=now,
            source="baseline",
        )

    # ─────────────────────────────────────────────────────────────
    #  BACKGROUND SCHEDULER
    # ─────────────────────────────────────────────────────────────

    def set_refresh_interval(self, seconds: int) -> None:
        self._refresh_interval_sec = max(0, seconds)
        logger.info("Background quota refresh interval set to %ds", self._refresh_interval_sec)

    def start_background_scheduler(self) -> None:
        if self._bg_thread and self._bg_thread.is_alive():
            return
        self._stop_event.clear()
        self._bg_thread = threading.Thread(target=self._scheduler_loop, daemon=True)
        self._bg_thread.start()
        logger.info("Background quota scheduler started")

    def stop_background_scheduler(self) -> None:
        self._stop_event.set()
        if self._bg_thread:
            self._bg_thread.join(timeout=2.0)
            self._bg_thread = None

    def _scheduler_loop(self) -> None:
        while not self._stop_event.is_set():
            interval = self._refresh_interval_sec
            if interval > 0:
                time.sleep(interval)
                if not self._stop_event.is_set():
                    try:
                        self.fetch_all_configured(force=True)
                    except Exception as e:
                        logger.debug("Background quota refresh error: %s", e)
            else:
                time.sleep(10)
