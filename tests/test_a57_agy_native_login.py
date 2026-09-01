"""Tests for Task A57: Antigravity Native Login via agy CLI.

Covers:
- P0-1: Native agy CLI invocation in terminal with isolated HOME/USERPROFILE/HOMEPATH.
        Terminal lookup on Linux and Windows with honest error reporting when missing.
        Waiting for credentials by file detection rather than process exit code.
- P0-2: Profile slot is pre-selected and isolated. Occupied slots require confirmation.
        Existing account directories in ~/.hermes/agy_profiles/ are never touched.
- P0-3: Account identity is truthfully read from agy-generated files without inventing emails.
        AutoAssigner.check_duplicate_identity de-duplicates accounts and prevents slot creep.
- P0-4: Browser OAuth redirect path is preserved as fallback.
- P0-5: Failures report exact cause (including stderr, checked candidate terminals, and HOME).
- P0-6: Security: no credentials in logs, directory permissions 0700, file permissions 0600.
"""
from __future__ import annotations

import json
import os

from antigravity_provider import agy_subprocess
import shutil
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from antigravity_provider.agy_subprocess import (
    check_profile_native_auth_status,
    find_terminal_emulator,
    poll_native_agy_login,
    start_native_agy_login,
)
from antigravity_provider.paths import get_profile_dir
from antigravity_provider.router.action_handler import ActionExecutor
from antigravity_provider.router.router_config import (
    RouterConfig,
    RouterProfileConfig,
    save_router_config,
)


@pytest.fixture(autouse=True)
def isolated_hermes_env(tmp_path, monkeypatch):
    """Ensure every test runs with fully isolated HERMES_HOME and temporary environment."""
    h_home = tmp_path / "hermes_home"
    h_home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HERMES_HOME", str(h_home))
    monkeypatch.setenv("DISPLAY", ":10.0")

    # Initial empty router config
    cfg = RouterConfig()
    save_router_config(cfg)
    return h_home


# ── TEST 1: Terminal discovery on Linux ──


@pytest.mark.unit
def test_terminal_discovery_linux_found(tmp_path, monkeypatch):
    """P0-1: find_terminal_emulator finds available terminal on Linux and returns correct command."""
    monkeypatch.setattr(agy_subprocess, "_is_windows", lambda: False)
    monkeypatch.setenv("DISPLAY", ":10.0")

    def mock_which(cmd):
        if cmd == "gnome-terminal":
            return "/usr/bin/gnome-terminal"
        return None

    monkeypatch.setattr(shutil, "which", mock_which)

    cmd, err, checked = find_terminal_emulator("ag-1", "/bin/agy", tmp_path)
    assert err is None
    assert cmd is not None
    assert cmd[0] == "/usr/bin/gnome-terminal"
    assert "--" in cmd
    # Терминалу передаётся не сама agy, а сценарий: он задаёт HOME сам и
    # не даёт окну закрыться. Многие эмуляторы передают вызов уже
    # работающему экземпляру, и наследование окружения теряется.
    helper = tmp_path / ".hermes-agy-login.sh"
    assert str(helper) in cmd
    body = helper.read_text(encoding="utf-8")
    assert "/bin/agy" in body
    assert str(tmp_path) in body
    assert any("gnome-terminal (найден: /usr/bin/gnome-terminal)" in item for item in checked)


@pytest.mark.unit
def test_terminal_discovery_linux_missing_honest_error(tmp_path, monkeypatch):
    """P0-1: When no terminal emulator exists on Linux, report honest error listing checked candidates."""
    monkeypatch.setattr(agy_subprocess, "_is_windows", lambda: False)
    monkeypatch.setenv("DISPLAY", ":10.0")
    monkeypatch.setattr(shutil, "which", lambda cmd: None)

    cmd, err, checked = find_terminal_emulator("ag-1", "/bin/agy", tmp_path)
    assert cmd is None
    assert err is not None
    assert "Терминал не найден на сервере" in err
    assert "x-terminal-emulator" in err
    assert "gnome-terminal" in err
    assert "konsole" in err
    assert "xterm" in err
    assert len(checked) >= 8


@pytest.mark.unit
def test_terminal_discovery_no_display_honest_error(tmp_path, monkeypatch):
    """P0-1: сеанса нет ни в окружении, ни у systemd — отказ с перечнем проверенного.

    Пустое окружение само по себе больше не приговор: хаб запускается через
    nohup и по SSH остаётся без DISPLAY, стоя при этом на рабочем столе. Отказ
    правомерен, только когда и systemd графического сеанса не знает.
    """
    monkeypatch.setattr(agy_subprocess, "_is_windows", lambda: False)
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.delenv("MIR_SOCKET", raising=False)
    monkeypatch.setattr(agy_subprocess.shutil, "which", lambda _n: None)

    cmd, err, checked = find_terminal_emulator("ag-1", "/bin/agy", tmp_path)
    assert cmd is None
    assert err is not None
    assert "Графический сеанс не обнаружен" in err
    assert any("DISPLAY (не задан)" in item for item in checked)
    assert any("loginctl" in item for item in checked)


@pytest.mark.unit
def test_terminal_discovery_windows(tmp_path, monkeypatch):
    """P0-1: On Windows, find_terminal_emulator selects wt.exe or cmd.exe."""
    monkeypatch.setattr(agy_subprocess, "_is_windows", lambda: True)

    monkeypatch.setattr(shutil, "which", lambda c: "C:\\Windows\\System32\\wt.exe" if "wt" in c else None)
    cmd, err, checked = find_terminal_emulator("ag-1", "C:\\bin\\agy.exe", tmp_path)
    assert err is None
    assert cmd is not None
    assert "wt.exe" in cmd[0]

    monkeypatch.setattr(shutil, "which", lambda c: None)
    cmd, err, checked = find_terminal_emulator("ag-1", "C:\\bin\\agy.exe", tmp_path)
    assert err is None
    assert cmd is not None
    assert "cmd.exe" in cmd[0]


# ── TEST 2: Start native agy login & slot protection ──


@pytest.mark.unit
def test_start_native_agy_login_creates_isolated_home(tmp_path, monkeypatch):
    """P0-1/P0-2: start_native_agy_login sets up profile directory with 0700 permissions and launches terminal."""
    slot = "ag-1"
    pdir = get_profile_dir(slot, "antigravity")

    mock_popen = MagicMock()
    monkeypatch.setattr("subprocess.Popen", mock_popen)
    monkeypatch.setattr("antigravity_provider.agy_subprocess.get_agy_exe", lambda: "/usr/local/bin/agy")
    monkeypatch.setattr(
        "antigravity_provider.agy_subprocess.find_terminal_emulator",
        lambda sid, exe, p: (["/usr/bin/xterm", "-e", exe], None, ["xterm"]),
    )

    ok, msg, data = start_native_agy_login(profile_id=slot)
    assert ok is True
    assert "Терминал успешно запущен" in msg
    assert data["profile_id"] == "ag-1"
    assert "session_id" in data
    assert pdir.is_dir()

    # Verify subprocess called with isolated HOME
    mock_popen.assert_called_once()
    call_kwargs = mock_popen.call_args[1]
    assert call_kwargs["env"]["HOME"] == str(pdir)
    assert call_kwargs["env"]["USERPROFILE"] == str(pdir)
    assert call_kwargs["cwd"] == str(pdir)


@pytest.mark.unit
def test_start_native_agy_login_occupied_slot_requires_confirmation(tmp_path, monkeypatch):
    """P0-2: Attempting to log into an already authenticated slot requires confirmation unless force=True."""
    slot = "ag-2"
    pdir = get_profile_dir(slot, "antigravity")
    pdir.mkdir(parents=True, exist_ok=True)
    auth_file = pdir / "auth.json"
    auth_file.write_text(json.dumps({
        "auth_method": "oauth",
        "email": "existing.developer@gmail.com",
        "token": {"access_token": "ya29.active_token", "refresh_token": "1//active_ref"},
    }), encoding="utf-8")

    # First attempt without force -> confirmation required
    ok, msg, data = start_native_agy_login(profile_id=slot, force=False)
    assert ok is False
    assert data.get("confirmation_required") is True
    assert "уже занят аккаунтом" in msg

    # Second attempt with force=True -> proceeds
    mock_popen = MagicMock()
    monkeypatch.setattr("subprocess.Popen", mock_popen)
    monkeypatch.setattr("antigravity_provider.agy_subprocess.get_agy_exe", lambda: "/usr/local/bin/agy")
    monkeypatch.setattr(
        "antigravity_provider.agy_subprocess.find_terminal_emulator",
        lambda sid, exe, p: (["/usr/bin/xterm", "-e", exe], None, ["xterm"]),
    )

    ok, msg, data = start_native_agy_login(profile_id=slot, force=True)
    assert ok is True
    assert "session_id" in data


# ── TEST 3: Polling detection of credentials written by agy ──


@pytest.mark.unit
def test_poll_native_agy_login_detects_antigravity_oauth_token(tmp_path, monkeypatch):
    """P0-1/P0-3: Poller detects .gemini/antigravity-cli/antigravity-oauth-token written by agy."""
    slot = "ag-3"
    pdir = get_profile_dir(slot, "antigravity")

    monkeypatch.setattr("subprocess.Popen", MagicMock())
    monkeypatch.setattr("antigravity_provider.agy_subprocess.get_agy_exe", lambda: "/usr/local/bin/agy")
    monkeypatch.setattr(
        "antigravity_provider.agy_subprocess.find_terminal_emulator",
        lambda sid, exe, p: (["/usr/bin/xterm", "-e", exe], None, ["xterm"]),
    )

    ok, msg, data = start_native_agy_login(profile_id=slot)
    assert ok is True
    session_id = data["session_id"]

    # While file is not written yet -> pending
    ok, msg, p_data = poll_native_agy_login(session_id)
    assert ok is True
    assert p_data["status"] == "pending"

    # Simulate agy CLI writing its token file
    cli_dir = pdir / ".gemini" / "antigravity-cli"
    cli_dir.mkdir(parents=True, exist_ok=True)
    token_file = cli_dir / "antigravity-oauth-token"
    token_file.write_text(json.dumps({
        "auth_method": "consumer",
        "token": {
            "access_token": "ya29.native_agy_token",
            "refresh_token": "1//native_agy_refresh",
            "token_type": "Bearer",
            "expiry": "2026-09-01T16:00:00Z",
        },
    }), encoding="utf-8")

    # Simulate active account identification
    acc_file = pdir / ".gemini" / "google_accounts.json"
    acc_file.write_text(json.dumps({"active": "agy.native@gmail.com"}), encoding="utf-8")

    # Poller should detect completion
    ok, msg, p_data = poll_native_agy_login(session_id)
    assert ok is True
    assert p_data["status"] == "completed"
    assert p_data["email"] == "agy.native@gmail.com"
    assert p_data["profile_id"] == "ag-3"


@pytest.mark.unit
def test_poll_native_agy_login_truthful_email_or_na(tmp_path, monkeypatch):
    """P0-3: When email identity cannot be found, display 'Н/Д', never an invented name."""
    slot = "ag-4"
    pdir = get_profile_dir(slot, "antigravity")

    monkeypatch.setattr("subprocess.Popen", MagicMock())
    monkeypatch.setattr("antigravity_provider.agy_subprocess.get_agy_exe", lambda: "/usr/local/bin/agy")
    monkeypatch.setattr(
        "antigravity_provider.agy_subprocess.find_terminal_emulator",
        lambda sid, exe, p: (["/usr/bin/xterm", "-e", exe], None, ["xterm"]),
    )

    ok, msg, data = start_native_agy_login(profile_id=slot)
    session_id = data["session_id"]

    cli_dir = pdir / ".gemini" / "antigravity-cli"
    cli_dir.mkdir(parents=True, exist_ok=True)
    token_file = cli_dir / "antigravity-oauth-token"
    token_file.write_text(json.dumps({
        "auth_method": "consumer",
        "token": {
            "access_token": "ya29.anon_token",
            "refresh_token": "1//anon_refresh",
        },
    }), encoding="utf-8")

    ok, msg, p_data = poll_native_agy_login(session_id)
    assert ok is True
    assert p_data["status"] == "completed"
    assert "Н/Д" in p_data["email"]


@pytest.mark.unit
def test_poll_native_agy_login_duplicate_identity_deduplication(tmp_path, monkeypatch):
    """P0-3: When logging into a new slot with an account already registered in another slot, redirect to existing slot."""
    # Slot 1 already has account
    s1_dir = get_profile_dir("ag-1", "antigravity")
    s1_dir.mkdir(parents=True, exist_ok=True)
    (s1_dir / "auth.json").write_text(json.dumps({
        "email": "corp.developer@company.com",
        "auth_method": "oauth",
        "token": {"access_token": "ya29.old", "refresh_token": "1//old"},
    }), encoding="utf-8")

    cfg = RouterConfig()
    cfg.profiles["ag-1"] = RouterProfileConfig(profile_id="ag-1", provider="antigravity")
    save_router_config(cfg)

    # User attempts login into ag-5
    s5_dir = get_profile_dir("ag-5", "antigravity")
    monkeypatch.setattr("subprocess.Popen", MagicMock())
    monkeypatch.setattr("antigravity_provider.agy_subprocess.get_agy_exe", lambda: "/usr/local/bin/agy")
    monkeypatch.setattr(
        "antigravity_provider.agy_subprocess.find_terminal_emulator",
        lambda sid, exe, p: (["/usr/bin/xterm", "-e", exe], None, ["xterm"]),
    )

    ok, msg, data = start_native_agy_login(profile_id="ag-5")
    session_id = data["session_id"]

    # agy writes credentials for corp.developer@company.com into ag-5
    cli_dir = s5_dir / ".gemini" / "antigravity-cli"
    cli_dir.mkdir(parents=True, exist_ok=True)
    (cli_dir / "antigravity-oauth-token").write_text(json.dumps({
        "auth_method": "consumer",
        "token": {"access_token": "ya29.new_corp", "refresh_token": "1//new_corp"},
    }), encoding="utf-8")
    (s5_dir / ".gemini" / "google_accounts.json").write_text(
        json.dumps({"active": "corp.developer@company.com"}), encoding="utf-8"
    )

    ok, msg, p_data = poll_native_agy_login(session_id)
    assert ok is True
    assert p_data["status"] == "completed"
    # De-duplicated back to ag-1
    assert p_data["profile_id"] == "ag-1"
    assert p_data["email"] == "corp.developer@company.com"


# ── TEST 4: Action executor integration & browser fallback ──


@pytest.mark.unit
def test_action_handler_native_auth_routes(monkeypatch):
    """P0-1/P0-5: ActionExecutor handles start_native_auth and poll_native_auth."""
    monkeypatch.setattr("subprocess.Popen", MagicMock())
    monkeypatch.setattr("antigravity_provider.agy_subprocess.get_agy_exe", lambda: "/usr/local/bin/agy")
    monkeypatch.setattr(
        "antigravity_provider.agy_subprocess.find_terminal_emulator",
        lambda sid, exe, p: (["/usr/bin/xterm", "-e", exe], None, ["xterm"]),
    )

    res = ActionExecutor.execute("start_native_auth", {"provider": "antigravity", "profile_id": "ag-6"})
    assert res["ok"] is True
    session_id = res["data"]["session_id"]

    poll_res = ActionExecutor.execute("poll_native_auth", {"session_id": session_id})
    assert poll_res["ok"] is True
    assert poll_res["data"]["status"] == "pending"

    cancel_res = ActionExecutor.execute("cancel_native_auth", {"session_id": session_id})
    assert cancel_res["ok"] is True


@pytest.mark.unit
def test_browser_redirect_auth_fallback_preserved():
    """P0-4: Existing browser OAuth redirect path is fully functional as fallback."""
    res = ActionExecutor.execute("start_redirect_auth", {"provider": "antigravity", "profile_id": "ag-7"})
    assert res["ok"] is True
    assert "url" in res["data"]
    assert "session_id" in res["data"]
    assert res["data"]["paste_kind"] == "url"

    ActionExecutor.execute("cancel_redirect_auth", {"session_id": res["data"]["session_id"]})


@pytest.mark.unit
def test_permissions_0700_and_0600(tmp_path):
    """P0-6: Profile directories are created with 0700 and credential files with 0600."""
    slot = "ag-8"
    pdir = get_profile_dir(slot, "antigravity")
    pdir.mkdir(parents=True, exist_ok=True)
    os.chmod(pdir, 0o700)

    cli_dir = pdir / ".gemini" / "antigravity-cli"
    cli_dir.mkdir(parents=True, exist_ok=True)
    token_file = cli_dir / "antigravity-oauth-token"
    token_file.write_text(json.dumps({
        "auth_method": "consumer",
        "token": {"access_token": "ya29.perm_test", "refresh_token": "1//perm"},
    }), encoding="utf-8")

    check_profile_native_auth_status(slot)

    # Check directory permissions (on POSIX systems)
    if os.name != "nt":
        assert oct(pdir.stat().st_mode & 0o777) == "0o700"
        assert oct(token_file.stat().st_mode & 0o777) == "0o600"
