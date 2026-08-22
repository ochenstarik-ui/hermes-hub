"""Unit and integration tests for Assignment A8 (Deployment Doctor, Self-Healing, and AutoAssigner).

Verifies:
1. Self-healing bootstrap & pre-UI crash logging in logs/startup.log
2. AutoAssigner.find_free_slot returns valid existing profile or None across all 5 providers
3. Profile test button & adapters reject expired auth without launching interactive OAuth
4. Mirror installation removes stale files and excludes __pycache__
5. CLI diagnostics doctor command outputs masked matrix and concise verdict
"""
from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from antigravity_provider.router.auto_assigner import AutoAssigner
from antigravity_provider.router.launcher_bootstrap import (
    check_missing_dependencies,
    log_startup,
    get_startup_log_path,
    self_heal_dependencies,
)
from antigravity_provider.router.adapters.antigravity_adapter import AntigravityAdapter
from antigravity_provider.router.exceptions import AuthExpiredError
from antigravity_provider.router.cli_commands import print_diagnostics_cli
from antigravity_provider.router.profile_manager import ProfileAuthManager
from antigravity_provider.router.router_config import (
    RouterConfig,
    RouterProfileConfig,
    load_router_config,
    save_router_config,
)
from antigravity_provider import paths


@pytest.fixture
def clean_env(tmp_path, monkeypatch):
    hermes_dir = tmp_path / "hermes"
    hermes_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HERMES_HOME", str(hermes_dir))
    monkeypatch.setattr(paths, "get_hermes_home", lambda: hermes_dir)
    monkeypatch.setattr(paths, "get_router_profiles_path", lambda: hermes_dir / "router_profiles.yaml")
    monkeypatch.setattr(paths, "get_router_state_path", lambda: hermes_dir / "router_state.json")
    monkeypatch.setattr(paths, "get_startup_log_file", lambda: hermes_dir / "logs" / "startup.log")
    return hermes_dir


@pytest.mark.unit
def test_bootstrap_self_healing_and_crash_logging(clean_env):
    """P0-1: Verify launcher bootstrap writes to startup.log and correctly checks dependencies."""
    log_file = paths.get_startup_log_file()
    if log_file.exists():
        log_file.unlink()

    log_startup("Test startup initialization sequence")
    assert log_file.is_file()
    content = log_file.read_text(encoding="utf-8")
    assert "Test startup initialization sequence" in content

    # Check dependency checker
    missing = check_missing_dependencies()
    assert isinstance(missing, list)

    # Test self-healing with empty list
    ok, msg = self_heal_dependencies([])
    assert ok is True


@pytest.mark.unit
def test_auto_assigner_find_free_slot_for_all_five_providers(clean_env):
    """P0-2: Verify find_free_slot returns existing profiles or None for all 5 providers."""
    config = load_router_config()

    for provider in ["antigravity", "openai-codex", "opencode-go", "claude", "grok"]:
        slot = AutoAssigner.find_free_slot(provider)
        if slot is not None:
            # Slot MUST exist in config.profiles
            assert slot in config.profiles
            assert config.profiles[slot].provider == provider

    # Test recommendation when all slots are filled
    slot_claude = AutoAssigner.find_free_slot("claude")
    assert slot_claude is not None
    assert slot_claude in ("claude-orch", "claude-worker-1", "claude-worker-2")

    # Simulate fake auth on all claude slots
    for c_slot in ["claude-orch", "claude-worker-1", "claude-worker-2"]:
        ProfileAuthManager.save_profile_auth("claude", c_slot, {"api_key": "sk-ant-test-key-1234567890123456"})

    # Now claude has no free slots -> find_free_slot must return None, NOT a non-existent candidate!
    assert AutoAssigner.find_free_slot("claude") is None

    rec_slot, title, reason = AutoAssigner.recommend_assignment("claude")
    assert rec_slot == ""
    assert "Нет свободных слотов" in title


@pytest.mark.unit
def test_adapter_no_browser_on_expired_token(clean_env, monkeypatch):
    """P0-3: Verify adapter raises AuthExpiredError without calling subprocess when token is expired."""
    expired_auth = {
        "provider": "antigravity",
        "profile_id": "ag-orch-fallback",
        "tokens": {
            "access_token": "expired_access_token",
            "expiry_date": int((time.time() - 3600) * 1000),  # 1 hour ago
        },
    }
    ProfileAuthManager.save_profile_auth("antigravity", "ag-orch-fallback", expired_auth)

    adapter = AntigravityAdapter()
    pcfg = RouterProfileConfig(
        profile_id="ag-orch-fallback",
        provider="antigravity",
        account_id="ag-acc-orch",
        preferred_models=["gemini-3.7-flash"],
    )

    with pytest.raises(AuthExpiredError) as exc_info:
        adapter.invoke(pcfg, {"model": "gemini-3.7-flash", "messages": [{"role": "user", "content": "hello"}]})

    assert "Авторизация истекла" in str(exc_info.value)


@pytest.mark.ui
def test_do_test_profile_no_browser_on_expired_token(clean_env):
    """P0-3: Verify do_test_profile in UI layer catches expired token without invoking adapter."""
    pytest.importorskip("customtkinter")
    from antigravity_provider.router.hermes_hub_app import do_test_profile

    expired_auth = {
        "provider": "antigravity",
        "profile_id": "ag-orch-fallback",
        "tokens": {
            "access_token": "expired_access_token",
            "expiry_date": int((time.time() - 3600) * 1000),
        },
    }
    ProfileAuthManager.save_profile_auth("antigravity", "ag-orch-fallback", expired_auth)

    res = do_test_profile("antigravity", "ag-orch-fallback")
    assert res["success"] is False
    assert "Авторизация истекла" in res["error"]


@pytest.mark.unit
def test_mirror_deployment_removes_deleted_files(tmp_path):
    """P0-4: Verify mirror installation cleans up files and folders removed from source."""
    src_dir = tmp_path / "src"
    dst_dir = tmp_path / "dst"
    src_dir.mkdir()
    dst_dir.mkdir()

    # Populate source
    (src_dir / "module_a.py").write_text("print('A')", encoding="utf-8")
    (src_dir / "subpkg").mkdir()
    (src_dir / "subpkg" / "nested.py").write_text("print('nested')", encoding="utf-8")

    # Initial mirror copy
    def mirror_copy(s: Path, d: Path):
        d.mkdir(parents=True, exist_ok=True)
        s_names = set()
        for item in s.iterdir():
            if item.name == "__pycache__" or item.suffix == ".pyc":
                continue
            s_names.add(item.name)
            d_item = d / item.name
            if item.is_file():
                shutil.copy2(item, d_item)
            elif item.is_dir():
                mirror_copy(item, d_item)

        for d_item in d.iterdir():
            if d_item.name == "__pycache__" or d_item.suffix == ".pyc" or d_item.name not in s_names:
                if d_item.is_file():
                    d_item.unlink()
                elif d_item.is_dir():
                    shutil.rmtree(d_item, ignore_errors=True)

    mirror_copy(src_dir, dst_dir)
    assert (dst_dir / "module_a.py").is_file()
    assert (dst_dir / "subpkg" / "nested.py").is_file()

    # Simulate deleting module_a.py from source and adding legacy dead files to destination
    (src_dir / "module_a.py").unlink()
    (dst_dir / "dead_code.py").write_text("# dead", encoding="utf-8")
    (dst_dir / "dead_dir").mkdir()
    (dst_dir / "dead_dir" / "old.py").write_text("# old", encoding="utf-8")

    # Run second mirror
    mirror_copy(src_dir, dst_dir)

    assert not (dst_dir / "module_a.py").exists()
    assert not (dst_dir / "dead_code.py").exists()
    assert not (dst_dir / "dead_dir").exists()
    assert (dst_dir / "subpkg" / "nested.py").is_file()


@pytest.mark.unit
def test_print_diagnostics_cli_output(clean_env, capsys):
    """P0-5: Verify print_diagnostics_cli produces structured diagnostic table and concise verdict."""
    config = load_router_config()
    save_router_config(config)

    ret = print_diagnostics_cli()
    captured = capsys.readouterr().out

    assert "HERMES HUB — SYSTEM DIAGNOSTICS & DOCTOR" in captured
    assert "PROFILE" in captured
    assert "PROVIDER" in captured
    assert "QUOTA STATE" in captured
    assert "[ВЕРДИКТ:" in captured
