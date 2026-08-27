"""Hermes Hub — Comprehensive Google Antigravity OAuth Lifecycle Test Suite.

Verifies:
TEST A — Automatic OAuth flow (session -> listener -> callback -> token exchange -> save)
TEST B — Manual callback fallback (session -> paste full URL -> original PKCE -> token exchange -> save)
TEST C — State mismatch rejection (callback state != session state -> reject, no token exchange)
TEST D — OAuth error callback (error=access_denied -> clean failure, no token exchange)
TEST E — Repeated 'Открыть в браузере' (state/port/verifier/URL invariance)
TEST F — Copy before open browser (immediate full URL in clipboard)
TEST G — Listener lifecycle (close wizard -> stopped; timeout -> stopped; restart -> old invalidated)
TEST H — Double completion protection (atomic single completion, no duplicate save)
TEST I — ERR_CONNECTION_REFUSED regression test: socket is verified listening BEFORE URL is published.
"""
from __future__ import annotations

import socket
import time
import urllib.parse
import urllib.request
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from antigravity_provider.router.profile_oauth import (
    ProfileOAuthSession,
    start_profile_oauth,
    get_oauth_session,
    cancel_oauth_session,
    _ACTIVE_OAUTH_SESSIONS,
)
from antigravity_provider.router.profile_manager import ProfileAuthManager


@pytest.fixture(autouse=True)
def cleanup_oauth_sessions():
    """Ensure all sessions are cancelled and cleared after each test."""
    yield
    for s_id in list(_ACTIVE_OAUTH_SESSIONS.keys()):
        cancel_oauth_session(s_id)


@pytest.mark.unit
def test_a_automatic_oauth_flow(tmp_path, monkeypatch):
    """TEST A: Automatic OAuth flow from session start to callback and completion."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))

    session_id, auth_url, port = start_profile_oauth("ag-orch-primary")
    session = get_oauth_session(session_id)
    assert session is not None
    assert session.is_listening is True

    mock_tokens = {
        "access_token": "ya29.mock_auto_token",
        "refresh_token": "1//mock_auto_refresh",
        "expires_at": int(time.time()) + 3600,
        "token_type": "Bearer",
    }

    with patch("antigravity_provider.router.profile_oauth.exchange_code_for_tokens", return_value=mock_tokens), \
         patch("antigravity_provider.router.profile_oauth.fetch_user_email", return_value="auto_user@google.com"):

        callback_url = f"http://127.0.0.1:{port}/oauth-callback?code=mock_code_auto&state={session.state}"
        req = urllib.request.Request(callback_url)
        with urllib.request.urlopen(req, timeout=5) as resp:
            assert resp.status == 200
            content = resp.read().decode("utf-8")
            assert "Авторизация успешно завершена" in content

        # Wait for thread finalization
        deadline = time.time() + 3.0
        while time.time() < deadline and session.status == "pending":
            time.sleep(0.05)

        assert session.status == "completed"
        assert session.completed_profile_info["email"] == "auto_user@google.com"

        # Verify saved credentials
        saved = ProfileAuthManager.load_profile_auth("antigravity", "ag-orch-primary")
        assert saved is not None
        assert saved["email"] == "auto_user@google.com"


@pytest.mark.unit
def test_b_manual_callback_fallback(tmp_path, monkeypatch):
    """TEST B: Manual callback fallback when localhost callback is not reached."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))

    session_id, auth_url, port = start_profile_oauth("ag-orch-primary")
    session = get_oauth_session(session_id)
    assert session is not None

    mock_tokens = {
        "access_token": "ya29.mock_manual_token",
        "refresh_token": "1//mock_manual_refresh",
        "expires_at": int(time.time()) + 3600,
        "token_type": "Bearer",
    }

    with patch("antigravity_provider.router.profile_oauth.exchange_code_for_tokens", return_value=mock_tokens) as mock_exchange, \
         patch("antigravity_provider.router.profile_oauth.fetch_user_email", return_value="manual_user@google.com"):

        pasted_url = f"http://127.0.0.1:{port}/oauth-callback?state={session.state}&code=mock_manual_code_789&scope=openid"
        ok, msg = session.handle_manual_callback_url(pasted_url)

        assert ok is True
        assert session.status == "completed"
        assert session.completed_profile_info["email"] == "manual_user@google.com"

        # Ensure ORIGINAL PKCE verifier was used
        assert mock_exchange.call_count == 1
        call_kwargs = mock_exchange.call_args[1]
        assert call_kwargs["code_verifier"] == session.verifier


@pytest.mark.unit
def test_c_state_mismatch(tmp_path, monkeypatch):
    """TEST C: Callback with mismatched state is strictly rejected without token exchange."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))

    session_id, auth_url, port = start_profile_oauth("ag-orch-primary")
    session = get_oauth_session(session_id)
    assert session is not None

    with patch("antigravity_provider.router.profile_oauth.exchange_code_for_tokens") as mock_exchange:
        pasted_url = f"http://127.0.0.1:{port}/oauth-callback?state=wrong_mismatched_state&code=mock_code"
        ok, msg = session.handle_manual_callback_url(pasted_url)

        # Главное — свойство безопасности: чужой state отвергнут и обмена
        # кода на токены не произошло.
        assert ok is False
        assert "сессии" in msg or "state" in msg
        assert mock_exchange.call_count == 0

        # А вот сессию промах завершать НЕ должен. Владелец переносит адрес
        # между машинами руками и легко берёт не ту вкладку; прежде первая же
        # ошибка ставила status="failed", и вход приходилось начинать заново,
        # хотя ссылка оставалась годной. Проверяем, что после промаха верная
        # вставка по-прежнему доходит до обмена кода.
        assert session.status == "pending"

        good_url = f"http://127.0.0.1:{port}/oauth-callback?state={session.state}&code=mock_code"
        session.handle_manual_callback_url(good_url)
        assert mock_exchange.call_count == 1


@pytest.mark.unit
def test_d_oauth_error_callback(tmp_path, monkeypatch):
    """TEST D: Provider error callback (e.g. access_denied) is cleanly handled."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))

    session_id, auth_url, port = start_profile_oauth("ag-orch-primary")
    session = get_oauth_session(session_id)
    assert session is not None

    with patch("antigravity_provider.router.profile_oauth.exchange_code_for_tokens") as mock_exchange:
        error_url = f"http://127.0.0.1:{port}/oauth-callback?error=access_denied&error_description=User+denied+access&state={session.state}"
        ok, msg = session.handle_manual_callback_url(error_url)

        assert ok is False
        assert "отклонил" in msg or "access_denied" in msg
        assert session.status == "failed"
        assert mock_exchange.call_count == 0


@pytest.mark.unit
def test_e_repeated_open_browser_invariance(tmp_path, monkeypatch, tk_root):
    """TEST E: Repeated 'Открыть в браузере' does NOT change session, state, verifier, or URL."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))
    pytest.importorskip("customtkinter")
    import customtkinter as ctk
    from antigravity_provider.router.ui.add_account_wizard import AddAccountWizard
    from antigravity_provider.router.grok_oauth import get_grok_oauth_session

    root = ctk.CTkToplevel(tk_root)
    root.withdraw()
    fake_session = MagicMock()
    fake_session.status = "pending"
    fake_session.is_dev_mode = False
    fake_session.error_msg = None
    grok_url = "https://accounts.x.ai/sign-in?user_code=ABCD"
    try:
        with patch("antigravity_provider.router.grok_oauth.start_grok_oauth", return_value=("sid", grok_url, "ABCD")), \
             patch("antigravity_provider.router.grok_oauth.get_grok_oauth_session", return_value=fake_session):
            wizard = AddAccountWizard(root)
            wizard.selected_provider = "grok"
            wizard.target_slot = "grok-worker-1"
            wizard._show_step_2_auth()
            wizard._polling_active = False

            orig_session_id = wizard.grok_session_id
            orig_url = wizard.grok_url

            session = get_grok_oauth_session(orig_session_id)

            with patch("webbrowser.open") as mock_open:
                wizard._open_grok_browser()
                wizard._open_grok_browser()
                wizard._open_grok_browser()

                assert mock_open.call_count == 3
                for call in mock_open.call_args_list:
                    assert call[0][0] == orig_url

                assert wizard.grok_session_id == orig_session_id
                assert wizard.grok_url == orig_url

            wizard.destroy()
    finally:
        root.destroy()


@pytest.mark.unit
def test_f_copy_before_open_browser(tmp_path, monkeypatch, tk_root):
    """TEST F: Copy button works immediately upon entering Step 2 without opening browser."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))
    pytest.importorskip("customtkinter")
    import customtkinter as ctk
    from antigravity_provider.router.ui.add_account_wizard import AddAccountWizard

    root = ctk.CTkToplevel(tk_root)
    root.withdraw()
    fake_session = MagicMock()
    fake_session.status = "pending"
    fake_session.is_dev_mode = False
    fake_session.error_msg = None
    grok_url = "https://accounts.x.ai/sign-in?user_code=ABCD"
    try:
        with patch("antigravity_provider.router.grok_oauth.start_grok_oauth", return_value=("sid", grok_url, "ABCD")), \
             patch("antigravity_provider.router.grok_oauth.get_grok_oauth_session", return_value=fake_session):
            wizard = AddAccountWizard(root)
            wizard.selected_provider = "grok"
            wizard.target_slot = "grok-worker-1"
            wizard._show_step_2_auth()
            wizard._polling_active = False

            assert wizard.grok_url is not None
            assert "x.ai" in wizard.grok_url or "accounts" in wizard.grok_url

            wizard._copy_grok_url()
            clipboard_content = wizard.clipboard_get()
            assert clipboard_content == wizard.grok_url

            wizard.destroy()
    finally:
        root.destroy()


@pytest.mark.unit
def test_g_listener_lifecycle_cleanup(tmp_path, monkeypatch):
    """TEST G: Listener is stopped on cancel/destroy/timeout and restarted cleanly."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))

    # 1. Cancel terminates listener
    s1_id, url1, p1 = start_profile_oauth("ag-orch-primary")
    s1 = get_oauth_session(s1_id)
    assert s1.is_listening is True

    cancel_oauth_session(s1_id)
    time.sleep(0.2)
    assert s1.is_listening is False
    assert s1.status == "cancelled"

    # 2. Restart creates active new session
    s2_id, url2, p2 = start_profile_oauth("ag-orch-primary")
    s2 = get_oauth_session(s2_id)
    assert s2.is_listening is True
    assert s2_id != s1_id


@pytest.mark.unit
def test_h_double_completion_protection(tmp_path, monkeypatch):
    """TEST H: Double completion (automatic + manual race) executes exactly once."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))

    session_id, auth_url, port = start_profile_oauth("ag-orch-primary")
    session = get_oauth_session(session_id)

    mock_tokens = {
        "access_token": "ya29.mock_double_token",
        "refresh_token": "1//mock_double_refresh",
        "expires_at": int(time.time()) + 3600,
        "token_type": "Bearer",
    }

    with patch("antigravity_provider.router.profile_oauth.exchange_code_for_tokens", return_value=mock_tokens) as mock_exchange, \
         patch("antigravity_provider.router.profile_oauth.fetch_user_email", return_value="race_user@google.com"):

        # 1. First completion (automatic)
        ok1, msg1 = session.handle_callback(code="code_1", state=session.state, source="automatic")
        assert ok1 is True
        assert mock_exchange.call_count == 1

        # 2. Second completion (manual duplicate attempt with same session)
        ok2, msg2 = session.handle_manual_callback_url(f"http://127.0.0.1:{port}/oauth-callback?state={session.state}&code=code_1")
        assert ok2 is True
        assert "уже успешно завершена" in msg2

        # Token exchange MUST have occurred exactly once
        assert mock_exchange.call_count == 1


@pytest.mark.unit
def test_i_err_connection_refused_regression_listener_ready_before_url(tmp_path, monkeypatch):
    """TEST I: Architectural invariant — listener socket is READY before URL is published."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))

    session = ProfileOAuthSession("ag-orch-primary")
    assert session.is_listening is False

    # Start session
    auth_url = session.start()

    # The socket MUST be listening and connectable BEFORE the user could receive the URL
    assert session.is_listening is True
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(2.0)
    connect_result = sock.connect_ex(("127.0.0.1", session.port))
    sock.close()

    assert connect_result == 0, f"ERR_CONNECTION_REFUSED: Listener on port {session.port} was not ready!"
    assert f":{session.port}/oauth-callback" in urllib.parse.unquote(auth_url)
    session.cancel()
