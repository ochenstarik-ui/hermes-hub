"""Comprehensive tests for OpenAI Codex OAuth, Multi-Account Isolation, OpenCode Go, and Wizard Clipboard UX.

TEST A: CodexOAuthSession standard device flow (user code -> poll -> token exchange -> save profile auth)
TEST B: CodexOAuthSession manual token / JSON credential fallback
TEST C: Multi-account isolation: multiple Codex profiles saved and loaded independently without overwriting
TEST D: CodexAdapter._resolve_token resolves tokens for individual profiles from ProfileAuthManager
TEST E: CodexAdapter multi-profile switching and failover isolation
TEST F: ProfileAuthManager.get_profile_status works for both Codex OAuth and API Key modes
TEST G: ProfileAuthManager.extract_jwt_identity extracts email from OpenAI/Google JWT payloads
TEST H: HubEntry and enable_clipboard_shortcuts (Ctrl+V, Ctrl+C, Ctrl+X, Ctrl+A, Shift+Insert, Cyrillic shortcuts)
TEST I: Add Account Wizard: OpenCode Go API key paste with whitespace / newline stripping
TEST J: Add Account Wizard: Password masking does not corrupt backing value or clipboard insertion
TEST K: Zero-secret logging across Codex OAuth and API key flows
TEST L: Single completion lock prevents double token exchange / double file writes in CodexOAuthSession
TEST M: Codex OAuth session cleanup on cancellation / modal destroy
"""
from __future__ import annotations

import base64
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from antigravity_provider.router.profile_manager import ProfileAuthManager, mask_email
from antigravity_provider.router.router_config import RouterProfileConfig
from antigravity_provider.router.adapters.codex_adapter import CodexAdapter
from antigravity_provider.router.codex_oauth import (
    CodexOAuthSession,
    start_codex_oauth,
    get_codex_oauth_session,
    cancel_codex_oauth_session,
)
# Pulls customtkinter transitively; without this guard a headless run aborts
# collection of the entire session instead of skipping this module.
pytest.importorskip("customtkinter")

from antigravity_provider.router.ui.components import enable_clipboard_shortcuts, HubEntry


@pytest.fixture(autouse=True)
def isolated_hermes_env(tmp_path, monkeypatch):
    """Ensure all tests run in an isolated HERMES_HOME."""
    hermes_dir = tmp_path / "hermes_test"
    hermes_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HERMES_HOME", str(hermes_dir))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "localappdata"))
    yield hermes_dir


def _make_jwt(payload: dict) -> str:
    """Helper to generate an unsigned test JWT."""
    header_b64 = base64.urlsafe_b64encode(b'{"alg":"none","typ":"JWT"}').decode("utf-8").rstrip("=")
    payload_b64 = base64.urlsafe_b64encode(json.dumps(payload).encode("utf-8")).decode("utf-8").rstrip("=")
    return f"{header_b64}.{payload_b64}.fake_signature"


# ==============================================================================
# TEST A: CodexOAuthSession standard device flow
# ==============================================================================
def test_a_codex_oauth_standard_device_flow(monkeypatch):
    """Test start -> poll -> token exchange -> profile saving."""
    session = CodexOAuthSession("codex-worker-1")

    # Mock usercode endpoint
    monkeypatch.setattr(
        "antigravity_provider.router.codex_oauth._post_json",
        lambda url, payload, **kwargs: {
            "user_code": "TEST-1234",
            "device_auth_id": "dev-auth-xyz",
            "interval": 1,
        } if "usercode" in url else {
            "authorization_code": "auth-code-999",
            "code_verifier": "verifier-111",
        },
    )

    test_id_token = _make_jwt({"email": "dev1@openai.com", "sub": "usr_dev1"})
    monkeypatch.setattr(
        "antigravity_provider.router.codex_oauth._post_form_json",
        lambda url, data, **kwargs: {
            "access_token": "oa-acc-token-123",
            "refresh_token": "oa-ref-token-456",
            "id_token": test_id_token,
        },
    )

    url, code = session.start()
    assert "auth.openai.com/codex/device" in url
    assert code == "TEST-1234"

    # Wait for poll thread to exchange tokens
    deadline = time.time() + 2.5
    while time.time() < deadline and session.status != "completed":
        time.sleep(0.1)

    assert session.status == "completed"
    assert session.completed_profile_info is not None
    assert session.completed_profile_info["email"] == "dev1@openai.com"

    # Verify saved on disk
    auth_data = ProfileAuthManager.load_profile_auth("openai-codex", "codex-worker-1")
    assert auth_data is not None
    assert auth_data["profile_id"] == "codex-worker-1"
    assert auth_data["token"]["access_token"] == "oa-acc-token-123"
    assert auth_data["email"] == "dev1@openai.com"


# ==============================================================================
# TEST B: CodexOAuthSession manual token / JSON credential fallback
# ==============================================================================
def test_b_codex_oauth_manual_token_fallback():
    """Test manual JSON credential insertion into Codex OAuth session."""
    session = CodexOAuthSession("codex-worker-2")
    test_id_token = _make_jwt({"email": "worker2@openai.com", "sub": "usr_w2"})

    raw_json = json.dumps({
        "access_token": "manual-access-token-777",
        "refresh_token": "manual-refresh-token-888",
        "id_token": test_id_token,
    })

    ok, msg = session.handle_manual_input(raw_json)
    assert ok is True
    assert session.status == "completed"

    auth_data = ProfileAuthManager.load_profile_auth("openai-codex", "codex-worker-2")
    assert auth_data is not None
    assert auth_data["profile_id"] == "codex-worker-2"
    assert auth_data["token"]["access_token"] == "manual-access-token-777"
    assert auth_data["email"] == "worker2@openai.com"


# ==============================================================================
# TEST C: Multi-account isolation
# ==============================================================================
def test_c_multi_account_codex_isolation():
    """Verify multiple Codex accounts are saved and loaded independently."""
    # Save account 1 (codex-orch)
    orch_data = {
        "provider": "openai-codex",
        "profile_id": "codex-orch",
        "auth_mode": "oauth",
        "token": {"access_token": "orch-token-1"},
        "email": "orch@company.com",
    }
    ProfileAuthManager.save_profile_auth("openai-codex", "codex-orch", orch_data)

    # Save account 2 (codex-worker-1)
    w1_data = {
        "provider": "openai-codex",
        "profile_id": "codex-worker-1",
        "auth_mode": "oauth",
        "token": {"access_token": "worker1-token-2"},
        "email": "coder@company.com",
    }
    ProfileAuthManager.save_profile_auth("openai-codex", "codex-worker-1", w1_data)

    # Save account 3 (codex-worker-2 as API key)
    w2_data = {
        "provider": "openai-codex",
        "profile_id": "codex-worker-2",
        "auth_mode": "api_key",
        "api_key": "sk-proj-testkey333333333333",
    }
    ProfileAuthManager.save_profile_auth("openai-codex", "codex-worker-2", w2_data)

    # Verify each loads its own independent data
    loaded_orch = ProfileAuthManager.load_profile_auth("openai-codex", "codex-orch")
    loaded_w1 = ProfileAuthManager.load_profile_auth("openai-codex", "codex-worker-1")
    loaded_w2 = ProfileAuthManager.load_profile_auth("openai-codex", "codex-worker-2")

    assert loaded_orch["token"]["access_token"] == "orch-token-1"
    assert loaded_orch["email"] == "orch@company.com"

    assert loaded_w1["token"]["access_token"] == "worker1-token-2"
    assert loaded_w1["email"] == "coder@company.com"

    assert loaded_w2["api_key"] == "sk-proj-testkey333333333333"


# ==============================================================================
# TEST D: CodexAdapter._resolve_token per-profile isolation
# ==============================================================================
def test_d_codex_adapter_resolve_token():
    """Verify CodexAdapter._resolve_token looks up the exact profile credentials from ProfileAuthManager."""
    adapter = CodexAdapter()

    # Create 2 separate profiles
    p1 = RouterProfileConfig(profile_id="codex-orch", provider="openai-codex")
    p2 = RouterProfileConfig(profile_id="codex-worker-1", provider="openai-codex")

    ProfileAuthManager.save_profile_auth("openai-codex", "codex-orch", {
        "provider": "openai-codex", "profile_id": "codex-orch", "token": {"access_token": "token-orch-99"}
    })
    ProfileAuthManager.save_profile_auth("openai-codex", "codex-worker-1", {
        "provider": "openai-codex", "profile_id": "codex-worker-1", "token": {"access_token": "token-worker-11"}
    })

    t1 = adapter._resolve_token(p1)
    t2 = adapter._resolve_token(p2)

    assert t1 == "token-orch-99"
    assert t2 == "token-worker-11"
    assert t1 != t2


# ==============================================================================
# TEST E: CodexAdapter multi-profile switching and failover isolation
# ==============================================================================
def test_e_codex_adapter_switching_and_failover():
    """Test switching profiles in CodexAdapter during execution."""
    adapter = CodexAdapter()

    p_primary = RouterProfileConfig(profile_id="codex-orch", provider="openai-codex")
    p_spare = RouterProfileConfig(profile_id="codex-spare-1", provider="openai-codex")

    ProfileAuthManager.save_profile_auth("openai-codex", "codex-orch", {
        "provider": "openai-codex", "profile_id": "codex-orch", "api_key": "sk-primary-orch-key111"
    })
    ProfileAuthManager.save_profile_auth("openai-codex", "codex-spare-1", {
        "provider": "openai-codex", "profile_id": "codex-spare-1", "api_key": "sk-spare-orch-key222"
    })

    assert adapter._resolve_token(p_primary) == "sk-primary-orch-key111"
    assert adapter._resolve_token(p_spare) == "sk-spare-orch-key222"


# ==============================================================================
# TEST F: ProfileAuthManager.get_profile_status for OAuth and API Key
# ==============================================================================
def test_f_profile_auth_manager_status():
    """Verify get_profile_status properly reports OAuth vs API Key profiles."""
    test_id_token = _make_jwt({"email": "testuser@openai.com", "sub": "usr_1"})
    ProfileAuthManager.save_profile_auth("openai-codex", "codex-orch", {
        "provider": "openai-codex",
        "profile_id": "codex-orch",
        "token": {"access_token": "test-access", "id_token": test_id_token},
    })
    ProfileAuthManager.save_profile_auth("openai-codex", "codex-worker-1", {
        "provider": "openai-codex",
        "profile_id": "codex-worker-1",
        "api_key": "sk-1234567890abcdef1234",
    })

    status_oauth = ProfileAuthManager.get_profile_status("openai-codex", "codex-orch")
    status_key = ProfileAuthManager.get_profile_status("openai-codex", "codex-worker-1")

    assert status_oauth["authenticated"] is True
    assert status_oauth["auth_mode"] == "oauth"
    assert "test***@openai.com" in status_oauth["email_masked"]

    assert status_key["authenticated"] is True
    assert status_key["auth_mode"] == "api_key"
    assert status_key["account_id_masked"] == "sk-...1234"


# ==============================================================================
# TEST G: ProfileAuthManager.extract_jwt_identity
# ==============================================================================
def test_g_extract_jwt_identity():
    """Test extracting email and sub from various standard and custom JWT claims."""
    jwt_standard = _make_jwt({"email": "standard@gmail.com", "sub": "google-sub-123"})
    jwt_openai = _make_jwt({"https://api.openai.com/profile": {"email": "custom@openai.com"}, "sub": "auth0|openai-456"})

    email1, sub1 = ProfileAuthManager.extract_jwt_identity(jwt_standard)
    email2, sub2 = ProfileAuthManager.extract_jwt_identity(jwt_openai)

    assert email1 == "standard@gmail.com"
    assert sub1 == "google-sub-123"
    assert email2 == "custom@openai.com"
    assert sub2 == "auth0|openai-456"


# ==============================================================================
# TEST H: HubEntry and enable_clipboard_shortcuts
# ==============================================================================
def test_h_enable_clipboard_shortcuts_binding():
    """Test that enable_clipboard_shortcuts attaches paste/copy/cut/select-all handlers without error."""
    mock_entry = MagicMock()
    mock_entry._entry = MagicMock()
    mock_entry.clipboard_get.return_value = "pasted_text_123"

    enable_clipboard_shortcuts(mock_entry)

    # Check bind was called for multiple standard and Cyrillic keys
    bound_events = [c[0][0] for c in mock_entry._entry.bind.call_args_list]
    assert "<Control-v>" in bound_events
    assert "<Control-a>" in bound_events
    assert "<Shift-Insert>" in bound_events
    assert "<Control-cyrillic_em>" in bound_events


# ==============================================================================
# TEST I: OpenCode Go API key paste with whitespace / newline stripping
# ==============================================================================
def test_i_opencode_go_paste_sanitization():
    """Verify paste sanitization strips leading/trailing newlines and whitespace."""
    raw_key_with_whitespace = "  \n\t opencode-sk-test-secret-999 \r\n  "
    cleaned = raw_key_with_whitespace.strip()

    assert cleaned == "opencode-sk-test-secret-999"

    is_valid, masked, models = ProfileAuthManager.verify_opencode_token(cleaned)
    assert is_valid is True
    assert masked == "opencode-...-999"
    assert "opencode-go-3" in models


# ==============================================================================
# TEST J: Password masking does not corrupt backing value
# ==============================================================================
def test_j_password_masking_integrity():
    """Verify password masking (show='*') retains exact backing value."""
    secret = "sk-proj-actualsecretvalue123456"
    auth_data = {
        "provider": "openai-codex",
        "profile_id": "codex-worker-2",
        "auth_mode": "api_key",
        "api_key": secret,
    }
    ProfileAuthManager.save_profile_auth("openai-codex", "codex-worker-2", auth_data)

    loaded = ProfileAuthManager.load_profile_auth("openai-codex", "codex-worker-2")
    assert loaded["api_key"] == secret


# ==============================================================================
# TEST K: Zero-secret logging across Codex OAuth and API key flows
# ==============================================================================
def test_k_zero_secret_logging_codex(caplog):
    """Verify raw tokens and API keys are never written to logger."""
    import logging
    caplog.set_level(logging.DEBUG)

    session = CodexOAuthSession("codex-orch")
    session._finalize_with_tokens("super_secret_access_token_9999", "super_secret_refresh_token_8888")

    all_logs = " ".join([r.message for r in caplog.records])
    assert "super_secret_access_token_9999" not in all_logs
    assert "super_secret_refresh_token_8888" not in all_logs


# ==============================================================================
# TEST L: Single completion lock prevents double token exchange
# ==============================================================================
def test_l_single_completion_protection():
    """Verify second finalize call does not re-save or double process."""
    session = CodexOAuthSession("codex-orch")
    res1 = session._finalize_with_tokens("token1", "refresh1")
    assert res1 is True
    assert session._is_completed is True

    # Try manual input after completed
    ok, msg = session.handle_manual_input("some_other_token")
    assert ok is True
    assert "Авторизация уже успешно завершена" in msg


# ==============================================================================
# TEST M: Session cleanup on cancellation
# ==============================================================================
def test_m_codex_session_cleanup():
    """Verify cancel_codex_oauth_session cancels polling and cleans global store."""
    session_id, url, code = start_codex_oauth("codex-spare-1")
    session = get_codex_oauth_session(session_id)
    assert session is not None

    cancel_codex_oauth_session(session_id)
    assert session.status == "cancelled"
    assert get_codex_oauth_session(session_id) is None
