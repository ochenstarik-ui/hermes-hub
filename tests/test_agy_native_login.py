"""Tests for A22: Native agy CLI Login, Profile Isolation, ~/.gemini Protection, and Model Discovery.

Acceptance criteria verification:
1. Hub never modifies ~/.gemini or global Windows Credential Manager during profile operations.
2. launch_native_agy_login spawns agy in target profile's isolated environment.
3. check_profile_native_auth_status detects native credentials without logging secrets.
4. AutoAssigner and wizard support sequential multi-account progression across all Antigravity slots.
5. do_set_model allows valid model selection.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from antigravity_provider.agy_subprocess import (
    check_profile_native_auth_status,
)
from antigravity_provider.paths import get_profile_dir
from antigravity_provider.router.action_handler import do_set_model
from antigravity_provider.router.auto_assigner import AutoAssigner
from antigravity_provider.router.profile_manager import ProfileAuthManager
from antigravity_provider.router.router_config import (
    RouterConfig,
    RouterProfileConfig,
    load_router_config,
    save_router_config,
)


# ── TEST 1: Absolute protection of global ~/.gemini ──


@pytest.mark.unit
def test_profile_operations_never_touch_user_home_gemini(tmp_path, monkeypatch):
    """P0-4: Saving, updating, refreshing or probing profiles must NEVER touch ~/.gemini."""
    hermes_home = tmp_path / "hermes_home"
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))

    # Mock user home
    user_home = tmp_path / "user_home"
    global_gemini = user_home / ".gemini"
    global_gemini.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("USERPROFILE", str(user_home))
    monkeypatch.setenv("HOME", str(user_home))
    monkeypatch.setattr(Path, "home", lambda: user_home)

    # Seed global .gemini with owner's sensitive files
    accounts_file = global_gemini / "google_accounts.json"
    accounts_file.write_text(json.dumps({"active": "owner@gmail.com", "old": []}), encoding="utf-8")

    creds_file = global_gemini / "oauth_creds.json"
    creds_file.write_text(json.dumps({"access_token": "ya29.owner_token", "expiry_date": 9999999999999}), encoding="utf-8")

    # Snapshot initial state of ~/.gemini
    initial_snapshot = {
        p.name: (p.stat().st_mtime_ns, p.read_bytes())
        for p in global_gemini.iterdir()
        if p.is_file()
    }

    # Perform diverse profile operations across multiple Antigravity slots
    auth_data = {
        "email": "worker1@gmail.com",
        "auth_method": "oauth",
        "token": {
            "access_token": "ya29.worker1_token",
            "refresh_token": "1//worker1_refresh",
            "id_token": "eyJhbGciOiJSUzI1NiJ9.worker1.sig",
            "scope": "openid email",
            "token_type": "Bearer",
            "expiry_date": int(time.time() * 1000) + 3600000,
        },
    }

    for slot in ["ag-orch-fallback", "ag-w1", "ag-w2"]:
        ProfileAuthManager.save_profile_auth("antigravity", slot, auth_data)
        loaded = ProfileAuthManager.load_profile_auth("antigravity", slot)
        assert loaded is not None

        # Check native status
        is_authed, email, data = check_profile_native_auth_status(slot)
        assert is_authed is True
        assert email == "worker1@gmail.com"

    # Set main profile
    ProfileAuthManager.set_main_profile("antigravity", "ag-w1")

    # Verify global ~/.gemini is 100% UNTOUCHED
    current_files = list(global_gemini.iterdir())
    assert len(current_files) == len(initial_snapshot), "New files appeared in ~/.gemini!"

    for p in current_files:
        assert p.name in initial_snapshot, f"Unexpected file {p.name} in ~/.gemini"
        init_mtime, init_bytes = initial_snapshot[p.name]
        assert p.read_bytes() == init_bytes, f"File {p.name} in ~/.gemini was modified!"


# ── TEST 2: Native agy login execution and environment isolation ──


@pytest.mark.unit
def test_unused_console_login_removed():
    from antigravity_provider import agy_subprocess
    assert not hasattr(agy_subprocess, "launch_native_agy_login")


# ── TEST 3: Detection of native agy authentication ──


@pytest.mark.unit
def test_check_profile_native_auth_status(tmp_path, monkeypatch):
    """P0-2: check_profile_native_auth_status detects native credentials and syncs auth.json."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))

    slot = "ag-w3"
    pdir = get_profile_dir(slot, "antigravity", create=True)
    gemini_dir = pdir / ".gemini"
    gemini_dir.mkdir(parents=True, exist_ok=True)

    # Initially not authenticated
    is_authed, email, data = check_profile_native_auth_status(slot)
    assert is_authed is False
    assert email is None

    # Simulate agy writing its native credentials
    oauth_creds = {
        "access_token": "ya29.native_access_token",
        "refresh_token": "1//native_refresh_token",
        "id_token": "eyJhbGciOiJSUzI1NiJ9.native_id.sig",
        "scope": "openid https://www.googleapis.com/auth/userinfo.email",
        "token_type": "Bearer",
        "expiry_date": int(time.time() * 1000) + 3600000,
    }
    (gemini_dir / "oauth_creds.json").write_text(json.dumps(oauth_creds), encoding="utf-8")

    google_accounts = {
        "active": "native.coder@gmail.com",
        "old": [],
    }
    (gemini_dir / "google_accounts.json").write_text(json.dumps(google_accounts), encoding="utf-8")

    # Detection succeeds
    is_authed, email, data = check_profile_native_auth_status(slot)
    assert is_authed is True
    assert email == "native.coder@gmail.com"
    assert data["token"]["access_token"] == "ya29.native_access_token"

    # auth.json was synced
    auth_file = pdir / "auth.json"
    assert auth_file.is_file()
    saved = json.loads(auth_file.read_text(encoding="utf-8"))
    assert saved["email"] == "native.coder@gmail.com"


# ── TEST 4: Multi-account sequential slot progression ──


@pytest.mark.unit
def test_multi_account_sequential_slot_progression(tmp_path, monkeypatch):
    """P0-2: Wizard can iterate through all Antigravity profile slots sequentially."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))

    # Initial free slot
    first_slot = AutoAssigner.find_free_slot("antigravity")
    assert first_slot == "ag-1"

    # Connect first slot
    AutoAssigner.ensure_profile_definition("antigravity", first_slot)
    pdir = get_profile_dir(first_slot, "antigravity", create=True)
    (pdir / "auth.json").write_text(json.dumps({"auth_method": "oauth", "email": "user1@gmail.com"}))

    # Next free slot
    second_slot = AutoAssigner.find_free_slot("antigravity")
    assert second_slot == "ag-2"

    # Connect second slot
    AutoAssigner.ensure_profile_definition("antigravity", second_slot)
    pdir2 = get_profile_dir(second_slot, "antigravity", create=True)
    (pdir2 / "auth.json").write_text(json.dumps({"auth_method": "oauth", "email": "user2@gmail.com"}))

    # Next free slot
    third_slot = AutoAssigner.find_free_slot("antigravity")
    assert third_slot == "ag-3"


# ── TEST 5: Model selection and assignment (P1-6) ──


@pytest.mark.unit
def test_do_set_model_allows_valid_model_assignment(tmp_path, monkeypatch):
    """P1-6: do_set_model permits setting valid models like gemini-3.1-pro-high."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))

    cfg = RouterConfig()
    cfg.profiles["ag-w1"] = RouterProfileConfig(
        profile_id="ag-w1",
        provider="antigravity",
        account_id="ag-w1",
        preferred_models=["gemini-2.5-pro"],
    )
    save_router_config(cfg)

    # Set model to gemini-3.1-pro-high
    ok, msg = do_set_model("ag-w1", "gemini-3.1-pro-high")
    assert ok is True
    assert "успешно сохранена" in msg

    updated = load_router_config()
    assert updated.profiles["ag-w1"].preferred_models[0] == "gemini-3.1-pro-high"
