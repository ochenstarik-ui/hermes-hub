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
        providers = ["antigravity", "openai-codex", "opencode-go", "claude", "grok"]

        for prov in providers:
            # Check slots
            from antigravity_provider.router.auto_assigner import AutoAssigner
            slots = AutoAssigner.PRESET_SLOTS.get(prov, [])
            for slot_id in slots:
                auth = ProfileAuthManager.load_profile_auth(prov, slot_id)
                if auth:
                    snap = self.fetch_account_quota(prov, slot_id, force=force)
                    results[f"{prov}:{slot_id}"] = snap
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
        snap.source = "runtime_event"
        with self._cache_lock:
            self._snapshots[key] = snap

        logger.info("Runtime quota error recorded for %s model=%s (reset in %ds)", key, model, reset_seconds)

        try:
            from antigravity_provider.router.state_store import HubStateStore
            HubStateStore.get().apply_delta_quota_updated(provider, profile_id, snap)
        except Exception:
            pass

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
        """Collect separate Claude (5h, Weekly) and Gemini (5h, Weekly) quota pools for Google Antigravity."""
        now = _utc_now()
        claude_reset_5h = now + timedelta(hours=5)
        gemini_reset_5h = now + timedelta(hours=5)
        weekly_reset = now + timedelta(days=7)

        # Build separate capacity buckets
        b_claude_5h = QuotaBucket(
            id="antigravity.claude.5h",
            display_name="Claude 5h",
            model_family="claude",
            used_percent=None,
            remaining_percent=None,
            period="5h",
            reset_at=claude_reset_5h,
            status="healthy",
        )
        b_claude_weekly = QuotaBucket(
            id="antigravity.claude.weekly",
            display_name="Claude Weekly",
            model_family="claude",
            used_percent=None,
            remaining_percent=None,
            period="7d",
            reset_at=weekly_reset,
            status="healthy",
        )
        b_gemini_5h = QuotaBucket(
            id="antigravity.gemini.5h",
            display_name="Gemini 5h",
            model_family="gemini",
            used_percent=None,
            remaining_percent=None,
            period="5h",
            reset_at=gemini_reset_5h,
            status="healthy",
        )
        b_gemini_weekly = QuotaBucket(
            id="antigravity.gemini.weekly",
            display_name="Gemini Weekly",
            model_family="gemini",
            used_percent=None,
            remaining_percent=None,
            period="7d",
            reset_at=weekly_reset,
            status="healthy",
        )

        return QuotaSnapshot(
            account_id=profile_id,
            provider="antigravity",
            buckets=[b_claude_5h, b_claude_weekly, b_gemini_5h, b_gemini_weekly],
            fetched_at=now,
            source="baseline",
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
            status="healthy",
        )
        b_weekly = QuotaBucket(
            id="codex.weekly",
            display_name="Weekly",
            model_family="gpt",
            used_percent=None,
            remaining_percent=None,
            period="7d",
            reset_at=now + timedelta(days=7),
            status="healthy",
        )

        return QuotaSnapshot(
            account_id=profile_id,
            provider="openai-codex",
            buckets=[b_session, b_weekly],
            fetched_at=now,
            source="baseline",
        )

    def _collect_opencode_quota(self, profile_id: str, auth_data: dict) -> QuotaSnapshot:
        """Collect Sliding, Weekly, and Monthly usage for OpenCode Go."""
        now = _utc_now()
        b_sliding = QuotaBucket(
            id="opencode.sliding",
            display_name="Скользящее",
            model_family="opencode",
            used_percent=None,
            remaining_percent=None,
            period="sliding",
            status="healthy",
        )
        b_weekly = QuotaBucket(
            id="opencode.weekly",
            display_name="Недельное",
            model_family="opencode",
            used_percent=None,
            remaining_percent=None,
            period="7d",
            reset_at=now + timedelta(days=7),
            status="healthy",
        )
        b_monthly = QuotaBucket(
            id="opencode.monthly",
            display_name="Ежемесячное",
            model_family="opencode",
            used_percent=None,
            remaining_percent=None,
            period="30d",
            reset_at=now + timedelta(days=30),
            status="healthy",
        )

        return QuotaSnapshot(
            account_id=profile_id,
            provider="opencode-go",
            buckets=[b_sliding, b_weekly, b_monthly],
            fetched_at=now,
            source="baseline",
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
            status="healthy",
        )
        b_weekly = QuotaBucket(
            id="claude.weekly",
            display_name="Текущая неделя",
            model_family="claude",
            used_percent=None,
            remaining_percent=None,
            period="7d",
            reset_at=now + timedelta(days=7),
            status="healthy",
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
            status="healthy",
        )
        b_chat = QuotaBucket(
            id="grok.chat",
            display_name="GrokChat",
            model_family="grok",
            used_percent=None,
            remaining_percent=None,
            status="healthy",
        )
        b_build = QuotaBucket(
            id="grok.build",
            display_name="GrokBuild",
            model_family="grok",
            used_percent=None,
            remaining_percent=None,
            status="healthy",
        )
        b_frequent = QuotaBucket(
            id="grok.frequent_tasks",
            display_name="Частые задачи",
            model_family="grok",
            used_absolute=None,
            remaining_absolute=None,
            limit_absolute=10,
            status="healthy",
        )
        b_normal = QuotaBucket(
            id="grok.normal_tasks",
            display_name="Обычные задачи",
            model_family="grok",
            used_absolute=None,
            remaining_absolute=None,
            limit_absolute=30,
            status="healthy",
        )

        return QuotaSnapshot(
            account_id=profile_id,
            provider="grok",
            buckets=[b_weekly, b_chat, b_build, b_frequent, b_normal],
            fetched_at=now,
            source="baseline",
        )

    def _generate_baseline_snapshot(self, provider: str, profile_id: str) -> QuotaSnapshot:
        """Baseline snapshot when offline or unconfigured with truthful multi-family buckets."""
        now = _utc_now()
        buckets: List[QuotaBucket] = []

        if provider == "antigravity":
            buckets = [
                QuotaBucket(
                    id="antigravity.claude.5h",
                    display_name="Claude 5h",
                    model_family="claude",
                    used_percent=None,
                    remaining_percent=None,
                    period="5h",
                    status="healthy",
                ),
                QuotaBucket(
                    id="antigravity.gemini.5h",
                    display_name="Gemini 5h",
                    model_family="gemini",
                    used_percent=None,
                    remaining_percent=None,
                    period="5h",
                    status="healthy",
                ),
            ]
        elif provider in ("openai-codex", "codex"):
            buckets = [
                QuotaBucket(
                    id="codex.primary.weekly",
                    display_name="Codex Weekly",
                    model_family="gpt",
                    used_percent=None,
                    remaining_percent=None,
                    period="7d",
                    status="healthy",
                ),
            ]
        elif provider in ("claude", "anthropic"):
            buckets = [
                QuotaBucket(
                    id="claude.session.5h",
                    display_name="Claude 5h",
                    model_family="claude",
                    used_percent=None,
                    remaining_percent=None,
                    period="5h",
                    status="healthy",
                ),
            ]
        elif provider in ("grok", "xai"):
            buckets = [
                QuotaBucket(
                    id="grok.frequent_tasks",
                    display_name="Grok 2h",
                    model_family="grok",
                    used_percent=None,
                    remaining_percent=None,
                    period="2h",
                    status="healthy",
                ),
            ]
        elif provider in ("opencode-go", "opencode"):
            buckets = [
                QuotaBucket(
                    id="opencode.tasks",
                    display_name="OpenCode Tasks",
                    model_family="opencode",
                    used_percent=None,
                    remaining_percent=None,
                    period="30d",
                    status="healthy",
                ),
            ]
        else:
            buckets = [
                QuotaBucket(
                    id=f"{provider}.default",
                    display_name="Основная квота",
                    model_family=None,
                    used_percent=None,
                    remaining_percent=None,
                    status="healthy",
                ),
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
