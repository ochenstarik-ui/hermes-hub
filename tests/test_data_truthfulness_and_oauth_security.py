"""Tests for Data Truthfulness (P0-1) and OAuth Security Fail-Closed Invariants (P0-2).

Verifies:
1. Quota snapshots without live provider metrics are honestly marked as source='baseline' (never '*_api').
2. Quota buckets do not return fabricated percentages when unmeasured by API.
3. Quota snapshots report is_estimated=True.
4. Codex and Grok OAuth device flows fail immediately on network errors when not in DEV_MODE.
5. Zero background polling is launched on device flow initialization failure.
6. Fake code generation is strictly gated behind HERMES_HUB_DEV_MODE=1.
7. Claude token exchange returns failure on invalid codes rather than silently accepting them.
"""
from __future__ import annotations

import os
from unittest.mock import patch, MagicMock
import pytest

from antigravity_provider.router.quota_collector import AccountQuotaService
from antigravity_provider.router.account_identity import QuotaSnapshot, QuotaBucket
from antigravity_provider.router.codex_oauth import CodexOAuthSession
from antigravity_provider.router.grok_oauth import GrokOAuthSession
from antigravity_provider.router.claude_oauth import ClaudeOAuthSession


# ── TEST P0-1: Data Truthfulness in Quota Collection ──

def test_quota_collector_never_fakes_api_source_without_network():
    """P0-1: Quota snapshots without live network endpoints must NOT claim '*_api' sources."""
    service = AccountQuotaService.get()

    providers = ["antigravity", "openai-codex", "opencode-go", "claude", "grok"]
    for prov in providers:
        with patch("antigravity_provider.router.profile_manager.ProfileAuthManager.load_profile_auth", return_value={"token": "mock_tok"}):
            snap = service.fetch_account_quota(prov, f"{prov}-slot-1", force=True)

            # Invariant: source must be 'baseline' or 'estimated', never '*_api'
            assert not snap.source.endswith("_api"), f"Provider {prov} falsely claimed API source '{snap.source}'"
            assert snap.source in ("baseline", "estimated", "unconfigured", "runtime_event")
            assert snap.is_estimated is True

            # Invariant: no fabricated non-zero used percentages
            for b in snap.buckets:
                if b.status == "healthy":
                    assert b.used_percent is None or b.used_percent == 0.0, (
                        f"Bucket {b.id} returned fabricated used_percent {b.used_percent}"
                    )


def test_quota_bucket_formatted_remaining_honesty():
    """P0-1: Bucket formatted_remaining returns honest availability when percentages are None."""
    b = QuotaBucket(
        id="test.bucket",
        display_name="Test Bucket",
        used_percent=None,
        remaining_percent=None,
        status="healthy",
    )
    assert b.formatted_remaining() == "Доступна"
    assert b.status == "healthy"


# ── TEST P0-2: OAuth Fail-Closed & DEV_MODE Gating ──

def test_codex_oauth_fails_immediately_on_network_error(monkeypatch):
    """P0-2: Codex device flow must fail immediately on network error without HERMES_HUB_DEV_MODE."""
    monkeypatch.delenv("HERMES_HUB_DEV_MODE", raising=False)

    session = CodexOAuthSession("codex-slot-1")

    with patch("antigravity_provider.router.codex_oauth._post_json", side_effect=ConnectionError("DNS failure")):
        url, code = session.start()

        # Must fail immediately
        assert url == ""
        assert code == ""
        assert session.status == "failed"
        assert session.error_msg is not None
        assert "DNS failure" in session.error_msg or "Не удалось подключиться" in session.error_msg
        # Must NOT launch background polling thread
        assert session.poll_thread is None
        assert session.user_code is None
        assert session.is_dev_mode is False


def test_codex_oauth_dev_mode_fallback(monkeypatch):
    """P0-2: Codex device flow allows local mock session ONLY when HERMES_HUB_DEV_MODE=1."""
    monkeypatch.setenv("HERMES_HUB_DEV_MODE", "1")

    session = CodexOAuthSession("codex-slot-1")

    with patch("antigravity_provider.router.codex_oauth._post_json", side_effect=ConnectionError("Offline")):
        url, code = session.start()

        assert code.startswith("CDX-")
        assert session.status == "pending"
        assert session.is_dev_mode is True
        assert session.poll_thread is not None
        session.cancel()


def test_grok_oauth_fails_immediately_on_network_error(monkeypatch):
    """P0-2: Grok device flow must fail immediately on network error without HERMES_HUB_DEV_MODE."""
    monkeypatch.delenv("HERMES_HUB_DEV_MODE", raising=False)

    session = GrokOAuthSession("grok-slot-1")

    with patch("antigravity_provider.router.grok_oauth._post_form", side_effect=TimeoutError("xAI unreachable")):
        url, code = session.start()

        assert url == ""
        assert code == ""
        assert session.status == "failed"
        assert session.error_msg is not None
        assert "xAI unreachable" in session.error_msg or "Не удалось подключиться" in session.error_msg
        assert session.poll_thread is None
        assert session.user_code is None
        assert session.is_dev_mode is False


def test_grok_oauth_dev_mode_fallback(monkeypatch):
    """P0-2: Grok device flow allows local mock session ONLY when HERMES_HUB_DEV_MODE=1."""
    monkeypatch.setenv("HERMES_HUB_DEV_MODE", "1")

    session = GrokOAuthSession("grok-slot-1")

    with patch("antigravity_provider.router.grok_oauth._post_form", side_effect=TimeoutError("Offline")):
        url, code = session.start()

        assert code.startswith("GRK-")
        assert session.status == "pending"
        assert session.is_dev_mode is True
        assert session.poll_thread is not None
        session.cancel()


def test_claude_oauth_rejects_invalid_code_on_network_failure(monkeypatch):
    """P0-2: Claude OAuth rejects invalid raw code when token endpoint fails."""
    monkeypatch.delenv("HERMES_HUB_DEV_MODE", raising=False)

    session = ClaudeOAuthSession("claude-slot-1")

    with patch("urllib.request.urlopen", side_effect=ConnectionRefusedError("Endpoint down")):
        ok, msg = session.handle_auth_code("fake_temporary_auth_code_1234567890")

        assert ok is False
        assert session.status == "failed"
        assert "Ошибка обмена кода" in msg
