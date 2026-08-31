"""Tests for Task A51 — Hub Controls Hermes.

Verifies:
1. P0-1: Account addition, multi-provider credential saving, role assignment, already-authenticated account handling, spare pool removal, preview_auto_assign, and set_default_role.
2. P0-2: Truthful assigned_roles and primary_role from preferred_chain without static fallback.
3. P0-3: Dynamic calculation of effective_answering_profile, effective_answering_model, will_bypass, and bypass_reason.
4. P0-4: Telemetry recording of routed vs bypassed calls and bypass_rate.
5. P0-5: Read-only feedback of ~/.hermes/config.yaml status in HubSnapshot.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
import pytest
import yaml

from antigravity_provider.router.action_handler import ActionExecutor
from antigravity_provider.router.auto_assigner import AutoAssigner
from antigravity_provider.router.profile_manager import ProfileAuthManager
from antigravity_provider.router.role_registry import RoleRegistry
from antigravity_provider.router.router_config import (
    RolePolicy,
    RouterConfig,
    RouterProfileConfig,
    load_router_config,
    save_router_config,
)
from antigravity_provider.router.settings_service import (
    get_hermes_config_status,
    get_hub_settings,
    save_hub_settings,
)
from antigravity_provider.router.state_store import HubStateStore
from antigravity_provider.router.telemetry_service import TelemetryService
from antigravity_provider.router.unified_health import (
    STATUS_HEALTHY,
    STATUS_QUOTA_EXHAUSTED,
    UnifiedHealthService,
)


@pytest.fixture(autouse=True)
def setup_isolated_env(tmp_path, monkeypatch):
    """Set up isolated HERMES_HOME and router configuration for tests."""
    hermes_home = tmp_path / ".hermes"
    hermes_home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))

    profiles_yaml = hermes_home / "router_profiles.yaml"
    monkeypatch.setenv("HERMES_ROUTER_CONFIG", str(profiles_yaml))

    # Initialize empty router config with canonical roles
    initial_config = RouterConfig(
        enabled=True,
        default_role="manager",
        roles=RoleRegistry.get_default_role_policies(),
        profiles={},
    )
    save_router_config(initial_config, profiles_yaml)

    # Initialize telemetry service with isolated log path
    telemetry_log = hermes_home / "telemetry.jsonl"
    TelemetryService.reset_instance()
    TelemetryService._instance = TelemetryService(log_path=telemetry_log)
    UnifiedHealthService._instance = None
    HubStateStore._instance = None

    # These tests cover persistence/routing; HTTP validation has its own A54 tests.
    from antigravity_provider.router.connection_preflight import DEFAULT_URLS
    monkeypatch.setattr("antigravity_provider.router.connection_preflight.validate_connection", lambda provider, token='', base_url='', preferred_model='': {
        "ok": True, "message": "Подключено и проверено", "data": {"models": ["fixture-model"], "base_url": base_url or DEFAULT_URLS[provider]}})
    monkeypatch.setattr("antigravity_provider.router.action_handler._rescan_after_auth", lambda *args: None)
    monkeypatch.setattr("antigravity_provider.router.account_probe_service.AccountProbeService.check_now", lambda *args, **kwargs: {"ok": True, "message": "Проверено", "data": {}})

    yield {
        "hermes_home": hermes_home,
        "profiles_yaml": profiles_yaml,
        "telemetry_log": telemetry_log,
    }


def test_p0_1_add_account_all_providers_and_assigned_to_role():
    """Verify add_account properly creates profile definition, saves auth, and adds to target_role chain."""
    # 1. Add Grok account
    res_grok = ActionExecutor.execute("add_account", {
        "provider": "grok",
        "profile_id": "grok-1",
        "api_key": "xai-test-key",
        "target_role": "coder-primary",
    })
    assert res_grok["ok"] is True

    # 2. Add OpenRouter account
    res_or = ActionExecutor.execute("add_account", {
        "provider": "openrouter",
        "profile_id": "openrouter-1",
        "api_key": "sk-or-test-key",
        "target_role": "research",
    })
    assert res_or["ok"] is True

    # 3. Add Local server account
    res_loc = ActionExecutor.execute("add_account", {
        "provider": "local",
        "profile_id": "local-1",
        "base_url": "http://127.0.0.1:8081/v1",
        "target_role": "coder-primary",
    })
    assert res_loc["ok"] is True

    cfg = load_router_config()
    assert "grok-1" in cfg.profiles
    assert "openrouter-1" in cfg.profiles
    assert "local-1" in cfg.profiles

    # Check that coder-primary role has grok-1 and local-1 in preferred_chain
    coder_primary = RoleRegistry.resolve_canonical_role("coder-primary")
    assert "grok-1" in cfg.roles[coder_primary].preferred_chain
    assert "local-1" in cfg.roles[coder_primary].preferred_chain

    # Check research role has openrouter-1 in preferred_chain
    research_role = RoleRegistry.resolve_canonical_role("research")
    assert "openrouter-1" in cfg.roles[research_role].preferred_chain


def test_p0_1_add_already_authenticated_account():
    """Verify that an account already authenticated on disk is not rejected for missing token and is assigned."""
    # Pre-populate auth data for antigravity profile
    ProfileAuthManager.save_profile_auth("antigravity", "ag-1", {
        "provider": "antigravity",
        "profile_id": "ag-1",
        "access_token": "oauth-token-123",
        "refresh_token": "refresh-token-123",
        "expires_at": 9999999999,
        "email": "user@gmail.com",
    })

    # Call add_account without token
    res = ActionExecutor.execute("add_account", {
        "provider": "antigravity",
        "profile_id": "ag-1",
        "target_role": "manager",
    })
    assert res["ok"] is True

    cfg = load_router_config()
    assert "ag-1" in cfg.profiles
    manager_role = RoleRegistry.resolve_canonical_role("manager")
    assert "ag-1" in cfg.roles[manager_role].preferred_chain


def test_p0_1_add_account_spare_unassigned():
    """Verify assigning to 'spare' or 'unassigned' removes account from active chains and preserves in profiles."""
    # First add account to coder-primary
    ActionExecutor.execute("add_account", {
        "provider": "openai-codex",
        "profile_id": "codex-1",
        "api_key": "sk-codex-key",
        "target_role": "coder-primary",
    })
    coder_role = RoleRegistry.resolve_canonical_role("coder-primary")
    cfg = load_router_config()
    assert "codex-1" in cfg.roles[coder_role].preferred_chain

    # Re-assign to spare
    res_spare = ActionExecutor.execute("add_account", {
        "provider": "openai-codex",
        "profile_id": "codex-1",
        "target_role": "spare",
    })
    assert res_spare["ok"] is True

    cfg = load_router_config()
    assert "codex-1" in cfg.profiles
    # Must not be in coder_role preferred_chain
    assert "codex-1" not in cfg.roles[coder_role].preferred_chain


def test_p0_1_preview_auto_assign_is_read_only():
    """Verify preview_auto_assign returns distribution plan without modifying router_profiles.yaml on disk."""
    # Pre-populate auth for 2 accounts
    ProfileAuthManager.save_profile_auth("openai-codex", "codex-1", {
        "provider": "openai-codex",
        "profile_id": "codex-1",
        "api_key": "key1",
    })
    ProfileAuthManager.save_profile_auth("claude", "claude-1", {
        "provider": "claude",
        "profile_id": "claude-1",
        "api_key": "key2",
    })
    AutoAssigner.ensure_profile_definition("openai-codex", "codex-1")
    AutoAssigner.ensure_profile_definition("claude", "claude-1")

    # Capture config on disk before preview
    before_yaml = load_router_config()
    coder_role = RoleRegistry.resolve_canonical_role("coder-primary")
    assert len(before_yaml.roles[coder_role].preferred_chain) == 0

    # Run preview_auto_assign
    preview_res = ActionExecutor.execute("preview_auto_assign", {})
    assert preview_res["ok"] is True
    assert preview_res["data"]["success"] is True
    assert preview_res["data"]["total_authenticated"] == 2
    assert len(preview_res["data"]["changes"]) > 0

    # Ensure disk was NOT changed
    after_yaml = load_router_config()
    assert len(after_yaml.roles[coder_role].preferred_chain) == 0

    # Now run real auto_assign_all
    apply_res = ActionExecutor.execute("auto_assign_all", {})
    assert apply_res["ok"] is True

    # Check that disk WAS changed
    final_yaml = load_router_config()
    assert len(final_yaml.roles[coder_role].preferred_chain) > 0


def test_p0_1_set_default_role():
    """Verify set_default_role updates default_role in RouterConfig and hub_settings.json."""
    res = ActionExecutor.execute("set_default_role", {"default_role": "developer-1"})
    assert res["ok"] is True
    assert res["data"]["default_role"] == "developer-1"

    cfg = load_router_config()
    assert cfg.default_role == "developer-1"

    settings = get_hub_settings()
    assert settings["default_role"] == "developer-1"


def test_p0_2_truthful_role_display_on_profiles():
    """Verify assigned_roles is formed strictly from preferred_chain without static fake roles."""
    # Add profile not in any chain
    ProfileAuthManager.save_profile_auth("grok", "grok-1", {
        "provider": "grok",
        "profile_id": "grok-1",
        "api_key": "key",
    })
    AutoAssigner.ensure_profile_definition("grok", "grok-1")

    # Add profile assigned to coder-primary (#1) and research (#2)
    ProfileAuthManager.save_profile_auth("openai-codex", "codex-1", {
        "provider": "openai-codex",
        "profile_id": "codex-1",
        "api_key": "key",
    })
    AutoAssigner.ensure_profile_definition("openai-codex", "codex-1")

    coder_role = RoleRegistry.resolve_canonical_role("coder-primary")
    research_role = RoleRegistry.resolve_canonical_role("research")

    cfg = load_router_config()
    cfg.roles[coder_role].preferred_chain = ["codex-1"]
    cfg.roles[research_role].preferred_chain = ["other-profile", "codex-1"]
    save_router_config(cfg)

    profiles_by_prov = UnifiedHealthService.get().scan_all(force=True)

    # grok-1 is unassigned
    grok_vm = next(p for p in profiles_by_prov["grok"] if p.profile_id == "grok-1")
    assert grok_vm.assigned_roles == []
    assert grok_vm.primary_role == "unassigned"

    # codex-1 is primary in coder-primary and backup #2 in research
    codex_vm = next(p for p in profiles_by_prov["openai-codex"] if p.profile_id == "codex-1")
    assert len(codex_vm.assigned_roles) == 2
    assert "Основной, #1" in codex_vm.assigned_roles[0]
    assert "Запасной, #2" in codex_vm.assigned_roles[1]
    assert codex_vm.primary_role == codex_vm.assigned_roles[0]


def test_p0_3_effective_answering_profile_and_bypass_reason():
    """Verify RolePipeline calculates effective_answering_profile and will_bypass."""
    # Setup healthy profile
    ProfileAuthManager.save_profile_auth("claude", "claude-1", {
        "provider": "claude",
        "profile_id": "claude-1",
        "api_key": "key",
    })
    AutoAssigner.ensure_profile_definition("claude", "claude-1")
    cfg = load_router_config()
    cfg.profiles["claude-1"].preferred_models = ["claude-3-5-sonnet"]

    coder_role = RoleRegistry.resolve_canonical_role("coder-primary")
    cfg.roles[coder_role].preferred_chain = ["claude-1"]

    research_role = RoleRegistry.resolve_canonical_role("research")
    cfg.roles[research_role].preferred_chain = []  # Empty chain

    save_router_config(cfg)

    pipelines = UnifiedHealthService.get().get_routing_pipelines()

    # Coder pipeline should have claude-1 as effective answering profile
    coder_pipe = pipelines[coder_role]
    assert coder_pipe.will_bypass is False
    assert coder_pipe.effective_answering_profile == "claude-1"
    assert coder_pipe.effective_answering_model == "claude-3-5-sonnet"
    assert coder_pipe.bypass_reason is None

    # Research pipeline (empty chain) should bypass with clear reason
    research_pipe = pipelines[research_role]
    assert research_pipe.will_bypass is True
    assert research_pipe.effective_answering_profile is None
    assert research_pipe.bypass_reason is not None
    assert "Цепочка пуста" in research_pipe.bypass_reason


def test_p0_4_telemetry_routed_vs_bypassed_calls():
    """Verify TelemetryService records bypass calls and computes routed vs bypass aggregates."""
    svc = TelemetryService.get()

    # 1. Record 2 successful routed calls
    svc.record_call(
        role="manager",
        profile_id="ag-1",
        provider="antigravity",
        model="gemini-2.5-pro",
        outcome="success",
        latency_seconds=0.45,
    )
    svc.record_call(
        role="developer-1",
        profile_id="codex-1",
        provider="openai-codex",
        model="gpt-4o",
        outcome="success",
        latency_seconds=0.55,
    )

    # 2. Record 1 bypass call
    svc.record_bypass(
        role="researcher",
        reason="Цепочка пуста — вызов передан штатному Hermes",
    )

    aggs = svc.get_aggregates(window_seconds=86400)
    assert aggs.total_calls == 3
    assert aggs.successful_calls == 2
    assert aggs.routed_calls_count == 2
    assert aggs.bypassed_calls_count == 1
    assert aggs.bypass_rate == round(1 / 3, 4)

    breakdown = svc.get_breakdown(window_seconds=86400)
    assert breakdown["global"]["routed_calls_count"] == 2
    assert breakdown["global"]["bypassed_calls_count"] == 1


def test_p0_5_hermes_config_status_read_only(tmp_path):
    """Verify get_hermes_config_status safely reads ~/.hermes/config.yaml without writing."""
    hermes_cfg_file = tmp_path / "config.yaml"
    hermes_cfg_data = {
        "model": {
            "default": "anthropic/claude-3-7-sonnet",
            "provider": "anthropic",
            "base_url": "https://api.anthropic.com/v1",
        }
    }
    hermes_cfg_file.write_text(yaml.dump(hermes_cfg_data), encoding="utf-8")

    st = get_hermes_config_status(hermes_cfg_file)
    assert st["exists"] is True
    assert st["model"] == "anthropic/claude-3-7-sonnet"
    assert st["provider"] == "anthropic"
    assert st["base_url"] == "https://api.anthropic.com/v1"

    # Verify missing config returns exists=False
    missing_cfg = tmp_path / "non_existent.yaml"
    st_missing = get_hermes_config_status(missing_cfg)
    assert st_missing["exists"] is False
    assert st_missing["model"] is None
