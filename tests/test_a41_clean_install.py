"""Unit and integration tests for Task A41: Clean First Install & Routing Reset.

Verifies:
1. Clean default configuration (0 profiles, 13 canonical roles with empty preferred_chain).
2. RoleRegistry CANONICAL_ROLES clean default chains.
3. Migration idempotence & preservation of user profiles without injecting stubs.
4. Action reset_router_config creates backup and resets routing without touching credentials.
5. Clean numbered slot generation upon adding accounts (codex-1, ag-1, claude-1, etc.).
6. Full compatibility with verify_multi_provider_router script.
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
from pathlib import Path
from unittest.mock import patch
import pytest

from antigravity_provider.paths import get_hermes_home, get_profile_dir
from antigravity_provider.router.action_handler import ActionExecutor, do_reset_router_config
from antigravity_provider.router.auto_assigner import AutoAssigner
from antigravity_provider.router.profile_manager import ProfileAuthManager
from antigravity_provider.router.role_registry import CANONICAL_ROLES, RoleRegistry
from antigravity_provider.router.router_config import (
    RolePolicy,
    RouterConfig,
    RouterProfileConfig,
    get_default_router_config,
    load_router_config,
    save_router_config,
)
from antigravity_provider.router.settings_service import get_hub_settings, save_hub_settings


@pytest.fixture
def clean_a41_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Set up an isolated hermes home directory for testing."""
    hermes_home = tmp_path / "hermes_home"
    hermes_home.mkdir(parents=True, exist_ok=True)
    config_file = hermes_home / "router_profiles.yaml"
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    monkeypatch.setenv("HERMES_ROUTER_CONFIG", str(config_file))
    return hermes_home, config_file


@pytest.mark.unit
def test_p0_1_clean_default_configuration():
    """P0-1 & P0-3: Clean configuration on first install has 0 profiles and 14 canonical roles with empty chains."""
    # 1. Check CANONICAL_ROLES registry
    assert len(CANONICAL_ROLES) == 15
    for role_id, role_def in CANONICAL_ROLES.items():
        assert role_def.default_preferred_chain == [], f"Role {role_id} has non-empty default chain"

    # 2. Check get_default_router_config()
    default_cfg = get_default_router_config()
    assert len(default_cfg.profiles) == 0, f"Expected 0 profiles, got {len(default_cfg.profiles)}"
    assert len(default_cfg.roles) == 15, f"Expected 15 roles, got {len(default_cfg.roles)}"
    assert default_cfg.default_role == "manager"

    for rname, rpol in default_cfg.roles.items():
        assert rpol.preferred_chain == [], f"Expected empty preferred_chain for role {rname}"


@pytest.mark.unit
def test_p0_1_dynamic_clean_slot_numbering(clean_a41_env):
    """P0-1: Accounts added dynamically receive clean numbered slots (ag-1, codex-1, claude-1, etc.)."""
    hermes_home, config_file = clean_a41_env

    # 1. Antigravity slots
    ag_slot_1 = AutoAssigner.find_free_slot("antigravity")
    assert ag_slot_1 == "ag-1"
    ProfileAuthManager.save_profile_auth("antigravity", ag_slot_1, {"tokens": {"access_token": "token1"}})

    ag_slot_2 = AutoAssigner.find_free_slot("antigravity")
    assert ag_slot_2 == "ag-2"

    # 2. Codex slots
    codex_slot_1 = AutoAssigner.find_free_slot("openai-codex")
    assert codex_slot_1 == "codex-1"
    ProfileAuthManager.save_profile_auth("openai-codex", codex_slot_1, {"api_key": "sk-1"})

    codex_slot_2 = AutoAssigner.find_free_slot("openai-codex")
    assert codex_slot_2 == "codex-2"

    # 3. Claude slots
    claude_slot_1 = AutoAssigner.find_free_slot("claude")
    assert claude_slot_1 == "claude-1"

    # 4. Grok slots
    grok_slot_1 = AutoAssigner.find_free_slot("grok")
    assert grok_slot_1 == "grok-1"

    # 5. OpenCode slots
    opengo_slot_1 = AutoAssigner.find_free_slot("opencode-go")
    assert opengo_slot_1 == "opengo-1"

    # 6. Local slots
    local_slot_1 = AutoAssigner.find_free_slot("local")
    assert local_slot_1 == "local-1"

    # 7. OpenRouter, NVIDIA, Ollama slots
    assert AutoAssigner.find_free_slot("openrouter") == "openrouter-1"
    assert AutoAssigner.find_free_slot("nvidia") == "nvidia-1"
    assert AutoAssigner.find_free_slot("ollama") == "ollama-1"


@pytest.mark.unit
def test_p0_3_migration_preserves_user_config_and_adds_missing_roles_cleanly(clean_a41_env):
    """P0-3: Migration preserves existing user profiles and chains without injecting fake profile stubs."""
    hermes_home, config_file = clean_a41_env

    # User configured 2 specific profiles and legacy role names
    user_profiles = {
        "user-primary-ag": RouterProfileConfig(
            profile_id="user-primary-ag",
            provider="antigravity",
            account_id="user-acc-1",
            preferred_models=["gemini-2.5-pro"],
        ),
        "user-primary-codex": RouterProfileConfig(
            profile_id="user-primary-codex",
            provider="openai-codex",
            account_id="user-acc-2",
            preferred_models=["o3-mini"],
        ),
    }

    user_roles = {
        "orchestrator": RolePolicy(role_name="orchestrator", preferred_chain=["user-primary-codex"]),
        "coder-primary": RolePolicy(role_name="coder-primary", preferred_chain=["user-primary-ag"]),
    }

    user_cfg = RouterConfig(
        enabled=True,
        default_role="manager",
        roles=user_roles,
        profiles=user_profiles,
    )
    save_router_config(user_cfg, config_file)

    # Trigger load and migration
    migrated_cfg = load_router_config(config_file)

    # 1. User profiles are preserved verbatim
    assert len(migrated_cfg.profiles) == 2
    assert "user-primary-ag" in migrated_cfg.profiles
    assert "user-primary-codex" in migrated_cfg.profiles
    assert migrated_cfg.profiles["user-primary-ag"].preferred_models == ["gemini-2.5-pro"]

    # 2. Legacy roles migrated to canonical names preserving chains
    assert "manager" in migrated_cfg.roles
    assert migrated_cfg.roles["manager"].preferred_chain == ["user-primary-codex"]

    assert "developer-1" in migrated_cfg.roles
    assert migrated_cfg.roles["developer-1"].preferred_chain == ["user-primary-ag"]

    # 3. All canonical roles exist
    assert len(migrated_cfg.roles) == 15

    # 4. Missing roles added with clean empty chains
    for rname, rpol in migrated_cfg.roles.items():
        if rname not in ("manager", "developer-1"):
            assert rpol.preferred_chain == [], f"Missing role {rname} should have empty chain"


@pytest.mark.unit
def test_p0_2_p0_4_reset_router_config_and_preserve_credentials(clean_a41_env):
    """P0-2 & P0-4: Reset action backs up router_profiles.yaml, resets to clean state, and strictly preserves credentials."""
    hermes_home, config_file = clean_a41_env

    # 1. Seed user configuration
    initial_profiles = {
        "ag-1": RouterProfileConfig(profile_id="ag-1", provider="antigravity"),
        "codex-1": RouterProfileConfig(profile_id="codex-1", provider="openai-codex"),
    }
    initial_roles = {
        "manager": RolePolicy(role_name="manager", preferred_chain=["codex-1"]),
        "developer-1": RolePolicy(role_name="developer-1", preferred_chain=["ag-1"]),
    }
    save_router_config(RouterConfig(profiles=initial_profiles, roles=initial_roles), config_file)

    # 2. Seed credentials across different providers and hub_settings.json
    ag_auth = ProfileAuthManager.save_profile_auth("antigravity", "ag-1", {"tokens": {"access_token": "secret_ag_token"}})
    codex_auth = ProfileAuthManager.save_profile_auth("openai-codex", "codex-1", {"api_key": "sk-secret-codex-key"})
    claude_auth = ProfileAuthManager.save_profile_auth("claude", "claude-1", {"api_key": "sk-ant-secret-claude-key"})
    grok_auth = ProfileAuthManager.save_profile_auth("grok", "grok-1", {"api_key": "xai-secret-grok-key"})
    opengo_auth = ProfileAuthManager.save_profile_auth("opencode-go", "opengo-1", {"api_key": "opengo-secret-key"})

    # Seed hub settings
    save_hub_settings({"email_masking_mode": "full", "quota_threshold_percent": 15.0})

    # Verify credentials exist on disk before reset
    assert ag_auth.is_file()
    assert codex_auth.is_file()
    assert claude_auth.is_file()
    assert grok_auth.is_file()
    assert opengo_auth.is_file()

    # 3. Execute Reset Action via ActionExecutor
    res = ActionExecutor.execute("reset_router_config", {})
    assert res["ok"] is True
    assert "сброшена" in res["message"].lower()

    # 4. Verify backup was created
    backups = list(hermes_home.glob("router_profiles.yaml.bak_*"))
    assert len(backups) >= 1, "Backup file was not created during reset"
    backup_content = backups[0].read_text(encoding="utf-8")
    assert "codex-1" in backup_content

    # 5. Verify router_profiles.yaml is now in clean state (0 profiles, 15 canonical roles with empty chains)
    reloaded_cfg = load_router_config(config_file)
    assert len(reloaded_cfg.profiles) == 0
    assert len(reloaded_cfg.roles) == 15
    for rname, rpol in reloaded_cfg.roles.items():
        assert rpol.preferred_chain == []

    # 6. Verify ALL credentials remain 100% intact and untouched
    assert ag_auth.is_file()
    assert codex_auth.is_file()
    assert claude_auth.is_file()
    assert grok_auth.is_file()
    assert opengo_auth.is_file()

    loaded_ag = ProfileAuthManager.load_profile_auth("antigravity", "ag-1")
    assert loaded_ag["tokens"]["access_token"] == "secret_ag_token"

    loaded_codex = ProfileAuthManager.load_profile_auth("openai-codex", "codex-1")
    assert loaded_codex["api_key"] == "sk-secret-codex-key"

    # Verify hub settings untouched
    settings = get_hub_settings()
    assert settings.get("email_masking_mode") == "full"
    assert settings.get("quota_threshold_percent") == 15.0


@pytest.mark.unit
def test_p0_5_verification_script_runs_clean_and_filled(clean_a41_env):
    """P0-5: verify_multi_provider_router.py passes on both clean default and filled user configs."""
    hermes_home, config_file = clean_a41_env

    # 1. Run on clean default config (file does not exist yet)
    import subprocess
    import sys
    env = os.environ.copy()
    env["HERMES_ROUTER_CONFIG"] = str(config_file)
    env["HERMES_HOME"] = str(hermes_home)

    script_path = Path(__file__).resolve().parent.parent / "scripts" / "verify_multi_provider_router.py"
    proc = subprocess.run([sys.executable, str(script_path)], env=env, capture_output=True, text=True)
    assert proc.returncode == 0, f"Verification failed on clean config: {proc.stderr}\n{proc.stdout}"
    assert "10/10 CHECKS PASSED" in proc.stdout

    # 2. Run on populated user config
    AutoAssigner.find_free_slot("openai-codex")
    AutoAssigner.find_free_slot("antigravity")
    AutoAssigner.assign_profile_to_role("codex-1", "manager", is_primary=True)
    AutoAssigner.assign_profile_to_role("ag-1", "manager", is_primary=False)

    proc_filled = subprocess.run([sys.executable, str(script_path)], env=env, capture_output=True, text=True)
    assert proc_filled.returncode == 0, f"Verification failed on filled config: {proc_filled.stderr}\n{proc_filled.stdout}"
    assert "10/10 CHECKS PASSED" in proc_filled.stdout
