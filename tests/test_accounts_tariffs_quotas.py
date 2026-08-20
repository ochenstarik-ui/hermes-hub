"""Comprehensive tests for Accounts, Tariffs/Plans, Quota Buckets, Claude, and Grok in Hermes Hub."""
from __future__ import annotations

import json
import os
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from antigravity_provider.router.account_identity import (
    AccountIdentity,
    QuotaBucket,
    QuotaSnapshot,
    SubscriptionPlan,
)
from antigravity_provider.router.quota_collector import AccountQuotaService
from antigravity_provider.router.adapters.claude_adapter import ClaudeAdapter
from antigravity_provider.router.adapters.grok_adapter import GrokAdapter
from antigravity_provider.router.claude_oauth import (
    ClaudeOAuthSession,
    start_claude_oauth,
    get_claude_oauth_session,
    cancel_claude_oauth_session,
)
from antigravity_provider.router.grok_oauth import (
    GrokOAuthSession,
    start_grok_oauth,
    get_grok_oauth_session,
    cancel_grok_oauth_session,
)
from antigravity_provider.router.health_tracker import (
    HealthTracker,
    HEALTHY,
    QUOTA_EXHAUSTED,
    extract_model_family,
)
from antigravity_provider.router.router_config import (
    RolePolicy,
    RouterConfig,
    RouterProfileConfig,
)
from antigravity_provider.router.router_engine import RouterEngine
from antigravity_provider.router.profile_manager import ProfileAuthManager


# ─────────────────────────────────────────────────────────────
# 1. SUBSCRIPTION PLAN TESTS
# ─────────────────────────────────────────────────────────────

def test_subscription_plan_known_codes():
    p1 = SubscriptionPlan.create("PRO")
    assert p1.code == "PRO"
    assert p1.display_name == "PRO"
    assert p1.is_known() is True

    p2 = SubscriptionPlan.create("plus")
    assert p2.code == "PLUS"
    assert p2.display_name == "PLUS"

    p3 = SubscriptionPlan.create("SuperGrok")
    assert p3.code == "SUPERGROK"
    assert p3.display_name == "SUPERGROK"

    p4 = SubscriptionPlan.create("grok_pro")
    assert p4.code == "GROK"
    assert p4.display_name == "GROK PRO"


def test_subscription_plan_unknown_fallback():
    p = SubscriptionPlan.create(None)
    assert p.code == "UNKNOWN"
    assert p.display_name == "Тариф: неизвестен"
    assert p.is_known() is False

    p_empty = SubscriptionPlan.create("")
    assert p_empty.code == "UNKNOWN"
    assert p_empty.display_name == "Тариф: неизвестен"


# ─────────────────────────────────────────────────────────────
# 2. ACCOUNT IDENTITY TESTS
# ─────────────────────────────────────────────────────────────

def test_account_identity_priority():
    # Priority: email -> display_name -> account_id -> profile_id
    ident1 = AccountIdentity(
        provider="antigravity",
        profile_id="ag-w1",
        email="developer@gmail.com",
        display_name="Dev Account",
        account_id="acc_12345",
    )
    assert ident1.primary_identifier() == "developer@gmail.com"

    ident2 = AccountIdentity(
        provider="openai-codex",
        profile_id="codex-worker-1",
        display_name="OpenAI Team",
        account_id="acc_67890",
    )
    assert ident2.primary_identifier() == "OpenAI Team"

    ident3 = AccountIdentity(
        provider="claude",
        profile_id="claude-worker-1",
        account_id="org_abcde",
    )
    assert ident3.primary_identifier() == "org_abcde"

    ident4 = AccountIdentity(
        provider="grok",
        profile_id="grok-worker-1",
    )
    assert ident4.primary_identifier() == "grok-worker-1"


def test_account_identity_masking():
    ident = AccountIdentity(provider="antigravity", profile_id="ag-1", email="john.doe@example.com")
    masked = ident.masked_identifier()
    assert "@example.com" in masked
    assert "john.doe" not in masked


# ─────────────────────────────────────────────────────────────
# 3. QUOTA BUCKET & SNAPSHOT TESTS
# ─────────────────────────────────────────────────────────────

def test_quota_bucket_percentage_reconciliation():
    b1 = QuotaBucket(id="b1", display_name="Session", used_percent=20.0)
    assert b1.remaining_percent == 80.0
    assert b1.status == "healthy"
    assert b1.formatted_remaining() == "Осталось 80%"

    b2 = QuotaBucket(id="b2", display_name="Weekly", remaining_percent=10.0)
    assert b2.used_percent == 90.0
    assert b2.status == "warning"

    b3 = QuotaBucket(id="b3", display_name="5h", remaining_percent=0.0)
    assert b3.status == "exhausted"
    assert b3.is_exhausted is True


def test_quota_bucket_absolute_counts():
    b = QuotaBucket(
        id="grok.tasks",
        display_name="Частые задачи",
        used_absolute=2,
        remaining_absolute=8,
        limit_absolute=10,
    )
    assert b.status == "healthy"
    assert "2/10" in b.formatted_remaining()


def test_quota_bucket_reset_formatting():
    now = datetime.now(timezone.utc)
    b = QuotaBucket(
        id="b1",
        display_name="5h",
        reset_at=now + timedelta(hours=3, minutes=25),
    )
    res_str = b.formatted_reset()
    assert res_str is not None
    assert "Сброс через 3ч" in res_str


def test_quota_snapshot_model_availability():
    b_claude = QuotaBucket(id="c1", display_name="Claude", model_family="claude", remaining_percent=0.0)
    b_gemini = QuotaBucket(id="g1", display_name="Gemini", model_family="gemini", remaining_percent=90.0)

    snap = QuotaSnapshot(
        account_id="ag-w1",
        provider="antigravity",
        buckets=[b_claude, b_gemini],
    )

    assert snap.is_model_available("claude-3-7-sonnet") is False
    assert snap.is_model_available("gemini-2.5-pro") is True


# ─────────────────────────────────────────────────────────────
# 4. ANTIGRAVITY SEPARATE CLAUDE & GEMINI QUOTA TESTS
# ─────────────────────────────────────────────────────────────

def test_antigravity_separate_claude_and_gemini_buckets():
    service = AccountQuotaService()
    snap = service._collect_antigravity_quota("ag-w1", {"tokens": {}})

    bucket_ids = [b.id for b in snap.buckets]
    assert "antigravity.claude.5h" in bucket_ids
    assert "antigravity.claude.weekly" in bucket_ids
    assert "antigravity.gemini.5h" in bucket_ids
    assert "antigravity.gemini.weekly" in bucket_ids

    # Claude bucket and Gemini bucket are independent
    b_c = snap.get_bucket_for_model("claude-3-7-sonnet")
    b_g = snap.get_bucket_for_model("gemini-2.5-pro")

    assert b_c is not None and b_c.model_family == "claude"
    assert b_g is not None and b_g.model_family == "gemini"


def test_health_tracker_antigravity_claude_exhaustion_does_not_block_gemini(tmp_path):
    state_file = tmp_path / "router_state.json"
    tracker = HealthTracker(state_file=state_file)

    # Mark claude exhausted on ag-w1
    tracker.mark_quota_exhausted(profile_id="ag-w1", model_name="claude-3-7-sonnet", duration=1800)

    # Claude should be unhealthy
    assert tracker.is_healthy("ag-w1", "claude-3-7-sonnet") is False
    assert tracker.is_healthy("ag-w1", "claude-3-5-sonnet") is False

    # Gemini should remain healthy!
    assert tracker.is_healthy("ag-w1", "gemini-2.5-pro") is True
    assert tracker.is_healthy("ag-w1", "gemini-2.5-flash") is True


# ─────────────────────────────────────────────────────────────
# 5. ROUTER SAME-ACCOUNT MODEL FALLBACK TESTS
# ─────────────────────────────────────────────────────────────

def test_router_same_account_model_fallback(tmp_path):
    state_file = tmp_path / "router_state.json"
    tracker = HealthTracker(state_file=state_file)

    # Profile ag-w1 supports both claude and gemini
    p_ag = RouterProfileConfig(
        profile_id="ag-w1",
        provider="antigravity",
        preferred_models=["claude-3-7-sonnet", "gemini-2.5-pro"],
        capabilities=["code", "reasoning"],
    )

    config = RouterConfig(
        profiles={"ag-w1": p_ag},
        roles={
            "coder": RolePolicy(
                role_name="coder",
                preferred_chain=["ag-w1"],
                default_model="claude-3-7-sonnet",
            )
        },
    )

    # Mark claude quota exhausted on ag-w1
    tracker.mark_quota_exhausted("ag-w1", "claude-3-7-sonnet", duration=1800)

    engine = RouterEngine(config=config, health=tracker)

    # Mock adapter invocation
    mock_adapter = MagicMock()
    mock_adapter.invoke.return_value = {"choices": [{"message": {"content": "ok"}}]}

    with patch("antigravity_provider.router.router_engine.get_adapter", return_value=mock_adapter), \
         patch("antigravity_provider.router.settings_service.get_hub_settings", return_value={"prefer_same_account_model_fallback": True}):

        req = {"model": "claude-3-7-sonnet", "messages": [{"role": "user", "content": "hello"}]}
        resp = engine.route_request(req, role="coder")

        # Engine should fall back to gemini-2.5-pro on the same ag-w1 profile!
        assert "router_metadata" in resp
        assert resp["router_metadata"]["profile_id"] == "ag-w1"
        called_model = mock_adapter.invoke.call_args[0][1]["model"]
        assert called_model == "gemini-2.5-pro"


# ─────────────────────────────────────────────────────────────
# 6. CLAUDE & GROK ADAPTERS & ERROR CLASSIFICATION TESTS
# ─────────────────────────────────────────────────────────────

def test_claude_adapter_error_classification():
    adapter = ClaudeAdapter()
    
    # Quota / rate limit error
    err_quota = RuntimeError("Claude API Error (429): You have exceeded your current quota, please check your plan")
    c1 = adapter.classify_error(err_quota)
    assert c1.category == "quota-exhausted"

    # Auth error
    err_auth = RuntimeError("Claude API Error (401): Invalid API Key provided")
    c2 = adapter.classify_error(err_auth)
    assert c2.category == "auth-required"


def test_grok_adapter_error_classification():
    adapter = GrokAdapter()

    # Quota error
    err_quota = RuntimeError("Grok API Error (429): insufficient_quota for this billing period")
    c1 = adapter.classify_error(err_quota)
    assert c1.category == "quota-exhausted"

    # Auth error
    err_auth = RuntimeError("Grok API Error (403): Unauthorized access token")
    c2 = adapter.classify_error(err_auth)
    assert c2.category == "auth-required"


# ─────────────────────────────────────────────────────────────
# 7. CLAUDE & GROK OAUTH SESSIONS TESTS
# ─────────────────────────────────────────────────────────────

def test_claude_oauth_session_lifecycle(tmp_path):
    session_id, auth_url = start_claude_oauth("claude-test-slot")
    assert "claude.ai/oauth/authorize" in auth_url
    assert "code_challenge=" in auth_url

    session = get_claude_oauth_session(session_id)
    assert session is not None
    assert session.status == "pending"

    # Test direct token insertion fallback
    with patch("antigravity_provider.router.profile_manager.ProfileAuthManager.save_profile_auth") as mock_save:
        ok, msg = session.handle_auth_code('{"access_token": "sk-ant-test-token-1234567890"}')
        assert ok is True
        assert session.status == "completed"
        assert mock_save.called

    cancel_claude_oauth_session(session_id)


def test_grok_oauth_session_lifecycle(tmp_path):
    mock_dev_resp = {
        "device_code": "dev-12345",
        "user_code": "GRK-1234",
        "verification_uri": "https://auth.x.ai/device",
        "interval": 1,
        "expires_in": 300,
    }
    with patch("antigravity_provider.router.grok_oauth._post_form", return_value=mock_dev_resp):
        session_id, verify_url, code = start_grok_oauth("grok-test-slot", start_poll=False)
        assert "x.ai" in verify_url
        assert code == "GRK-1234"

        session = get_grok_oauth_session(session_id)
        assert session is not None

        # Test manual token fallback
        with patch("antigravity_provider.router.profile_manager.ProfileAuthManager.save_profile_auth") as mock_save:
            ok, msg = session.handle_manual_input('{"access_token": "xai-test-access-token-1234567890"}')
            assert ok is True
            assert session.status == "completed"
            assert mock_save.called

        cancel_grok_oauth_session(session_id)


# ─────────────────────────────────────────────────────────────
# 8. VERIFY PROFILE MANAGER TOKEN RESOLVERS
# ─────────────────────────────────────────────────────────────

def test_profile_manager_verify_claude_and_grok_tokens():
    ok, masked, models = ProfileAuthManager.verify_claude_token("sk-ant-api03-abcdef1234567890")
    assert ok is True
    assert "sk-ant" in masked
    assert "claude-3-7-sonnet" in models

    ok2, masked2, models2 = ProfileAuthManager.verify_grok_token("xai-abcdef1234567890123456")
    assert ok2 is True
    assert "xai" in masked2
    assert "grok-3" in models2
