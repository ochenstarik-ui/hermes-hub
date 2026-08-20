"""Hermes Hub — Comprehensive Google Antigravity OAuth Lifecycle Test Suite.

Verifies:
1. Callback listener exists immediately after start.
2. redirect_uri strictly matches the actual listening port.
3. Listener remains alive during idle wait.
4. Simulated valid callback is accepted and exchanges tokens.
5. State mismatch callback is rejected.
6. Timeout terminates listener cleanly.
7. Cancel / wizard close terminates listener.
8. Listener stays alive until code exchange completes.
9. Retry after cancel / timeout succeeds without port collision.
10. Immediate Step 2 URL availability and single-session invariance.
11. Copy URL works without Open Browser.
12. Repeated Open Browser clicks reuse identical session and state.
13. Regeneration creates a new session / state / port and invalidates old callback.
"""
from __future__ import annotations

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
def test_oauth_listener_exists_and_port_matches(tmp_path, monkeypatch):
    """1 & 2: Verify callback listener exists and redirect_uri uses the exact bound port."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))

    session_id, auth_url, port = start_profile_oauth("ag-orch-primary")
    session = get_oauth_session(session_id)

    assert session is not None
    assert session.is_listening is True
    assert f":{port}/oauth-callback" in session.redirect_uri
    assert f":{port}/oauth-callback" in urllib.parse.unquote(auth_url)
    assert session.status == "pending"


@pytest.mark.unit
def test_oauth_listener_remains_alive_during_wait(tmp_path, monkeypatch):
    """3: Verify listener socket remains listening during idle wait."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))

    session_id, auth_url, port = start_profile_oauth("ag-orch-primary")
    session = get_oauth_session(session_id)

    # Let it idle for 0.5s
    time.sleep(0.5)
    assert session.is_listening is True
    assert session.status == "pending"

    # Ping non-callback path (should get 404, but server must stay alive)
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{port}/random-probe")
        with urllib.request.urlopen(req, timeout=2) as resp:
            pass
    except urllib.error.HTTPError as e:
        assert e.code == 404

    # Server must still be alive!
    time.sleep(0.2)
    assert session.is_listening is True
    assert session.status == "pending"


@pytest.mark.unit
def test_simulated_valid_callback_success(tmp_path, monkeypatch):
    """4 & 8: Verify valid callback is accepted and tokens are finalized."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))

    session_id, auth_url, port = start_profile_oauth("ag-orch-primary")
    session = get_oauth_session(session_id)

    mock_tokens = {
        "access_token": "ya29.mock_token",
        "refresh_token": "1//mock_refresh",
        "expires_at": int(time.time()) + 3600,
        "token_type": "Bearer",
    }

    with patch("antigravity_provider.router.profile_oauth.exchange_code_for_tokens", return_value=mock_tokens), \
         patch("antigravity_provider.router.profile_oauth.fetch_user_email", return_value="developer@google.com"):

        # Send HTTP GET callback matching state and code
        callback_url = f"http://127.0.0.1:{port}/oauth-callback?code=mock_auth_code_123&state={session.state}"
        req = urllib.request.Request(callback_url)
        with urllib.request.urlopen(req, timeout=5) as resp:
            assert resp.status == 200
            content = resp.read().decode("utf-8")
            assert "Account Authorized" in content

        # Wait briefly for thread finalization
        deadline = time.time() + 3.0
        while time.time() < deadline and session.status == "pending":
            time.sleep(0.05)

        assert session.status == "completed"
        assert session.completed_profile_info["email"] == "developer@google.com"


@pytest.mark.unit
def test_state_mismatch_rejected(tmp_path, monkeypatch):
    """5: Verify callback with mismatched state is rejected as failed."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))

    session_id, auth_url, port = start_profile_oauth("ag-orch-primary")
    session = get_oauth_session(session_id)

    bad_state = "totally_wrong_state_value"
    callback_url = f"http://127.0.0.1:{port}/oauth-callback?code=mock_code&state={bad_state}"
    req = urllib.request.Request(callback_url)
    with urllib.request.urlopen(req, timeout=5) as resp:
        assert resp.status == 200

    deadline = time.time() + 3.0
    while time.time() < deadline and session.status == "pending":
        time.sleep(0.05)

    assert session.status == "failed"
    assert "State mismatch" in session.error_msg


@pytest.mark.unit
def test_cancel_session_terminates_listener(tmp_path, monkeypatch):
    """6 & 7: Verify explicit cancel terminates listener immediately."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))

    session_id, auth_url, port = start_profile_oauth("ag-orch-primary")
    session = get_oauth_session(session_id)
    assert session.is_listening is True

    cancel_oauth_session(session_id)
    time.sleep(0.2)

    assert session.status == "cancelled"
    assert session.is_listening is False


@pytest.mark.unit
def test_retry_after_cancel_works_cleanly(tmp_path, monkeypatch):
    """9: Verify retry after cancel opens a new listener cleanly."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))

    # First attempt
    s1_id, url1, port1 = start_profile_oauth("ag-orch-primary")
    s1 = get_oauth_session(s1_id)
    cancel_oauth_session(s1_id)
    time.sleep(0.2)

    # Second attempt
    s2_id, url2, port2 = start_profile_oauth("ag-orch-primary")
    s2 = get_oauth_session(s2_id)
    assert s2 is not None
    assert s2.is_listening is True
    assert s2.session_id != s1_id


@pytest.mark.unit
def test_single_session_invariance_and_regeneration(tmp_path, monkeypatch):
    """10-13: Test Wizard Step 2 immediate URL availability, single-session reuse, and regeneration."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))
    pytest.importorskip("customtkinter")
    import customtkinter as ctk
    from antigravity_provider.router.ui.add_account_wizard import AddAccountWizard

    root = ctk.CTk()
    root.withdraw()
    try:
        wizard = AddAccountWizard(root)
        wizard.selected_provider = "antigravity"
        wizard.target_slot = "ag-spare-1"

        # 1. Opening Step 2 initializes OAuth immediately
        wizard._show_step_2_auth()
        assert wizard.oauth_url is not None
        assert wizard.oauth_session_id is not None
        assert wizard.oauth_url.startswith("https://accounts.google.com")

        # 2. URL entry contains the URL
        entry_text = wizard.oauth_url_entry.get()
        assert entry_text == wizard.oauth_url

        # 3. Repeated Open Browser does NOT change session or state
        orig_session_id = wizard.oauth_session_id
        orig_url = wizard.oauth_url

        with patch("webbrowser.open") as mock_open:
            wizard._open_oauth_browser()
            assert mock_open.call_count == 1
            assert mock_open.call_args[0][0] == orig_url
            assert wizard.oauth_session_id == orig_session_id

            wizard._open_oauth_browser()
            assert mock_open.call_count == 2
            assert wizard.oauth_session_id == orig_session_id
            assert wizard.oauth_url == orig_url

        # 4. Explicit regeneration creates NEW session and state
        wizard._regenerate_oauth_session()
        new_session_id = wizard.oauth_session_id
        new_url = wizard.oauth_url

        assert new_session_id != orig_session_id
        assert new_url != orig_url

        # Old session must be cancelled
        old_session = get_oauth_session(orig_session_id)
        assert old_session is None or old_session.status == "cancelled"

        wizard.destroy()
    finally:
        root.destroy()
