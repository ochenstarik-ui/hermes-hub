"""Comprehensive tests for A26: Unlimited Provider Accounts, Overview Role Assignment,
Smart Auto-Distribution, and Configurable Quota Thresholds.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict

import pytest

from antigravity_provider.router.action_handler import ActionExecutor, do_save_settings
from antigravity_provider.router.auto_assigner import AutoAssigner
from antigravity_provider.router.health_tracker import (
    HEALTHY,
    QUOTA_EXHAUSTED,
    HealthTracker,
)
from antigravity_provider.router.profile_manager import ProfileAuthManager
from antigravity_provider.router.quota_collector import AccountQuotaService, QuotaBucket, QuotaSnapshot
from antigravity_provider.router.router_config import (
    RolePolicy,
    RouterConfig,
    RouterProfileConfig,
    load_router_config,
    save_router_config,
)
from antigravity_provider.router.settings_service import (
    get_hub_settings,
    invalidate_settings_cache,
    save_hub_settings,
)
from antigravity_provider.router.state_store import HubStateStore
from antigravity_provider.router.unified_health import EventLogService, UnifiedHealthService


@pytest.fixture(autouse=True)
def setup_test_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Set up isolated HERMES_HOME and clean caches for each test."""
    hermes_home = tmp_path / "hermes"
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    monkeypatch.setenv("HERMES_ROUTER_CONFIG", str(hermes_home / "router_profiles.yaml"))
    invalidate_settings_cache()

    # Reset singletons state where needed
    AccountQuotaService.get()._snapshots.clear()
    EventLogService.get()._events.clear()

    return hermes_home


@pytest.mark.unit
def test_unlimited_provider_slots_p0_1(tmp_path: Path):
    """P0-1: Connecting 4th and 5th account of a provider removes slot ceiling and dynamically registers profiles."""
    # Pre-authenticate 3 codex slots: codex-1, codex-2, codex-3
    ProfileAuthManager.save_profile_auth("openai-codex", "codex-1", {"api_key": "sk-1"})
    ProfileAuthManager.save_profile_auth("openai-codex", "codex-2", {"api_key": "sk-2"})
    ProfileAuthManager.save_profile_auth("openai-codex", "codex-3", {"api_key": "sk-3"})

    # 4th slot should be generated dynamically (e.g. codex-4)
    slot_4 = AutoAssigner.find_free_slot("openai-codex")
    assert slot_4 == "codex-4"

    # Profile should now be ensured in router config
    cfg = load_router_config()
    assert "codex-4" in cfg.profiles
    assert cfg.profiles["codex-4"].provider == "openai-codex"

    # Save auth for 4th slot, then 5th slot should be codex-5
    ProfileAuthManager.save_profile_auth("openai-codex", "codex-4", {"api_key": "sk-4"})
    slot_5 = AutoAssigner.find_free_slot("openai-codex")
    assert slot_5 == "codex-5"

    # Test OpenCode provider dynamic slots: opengo-1, 2, 3 authenticated -> opengo-4
    ProfileAuthManager.save_profile_auth("opencode-go", "opengo-1", {"api_key": "op-1"})
    ProfileAuthManager.save_profile_auth("opencode-go", "opengo-2", {"api_key": "op-2"})
    ProfileAuthManager.save_profile_auth("opencode-go", "opengo-3", {"api_key": "op-3"})

    slot_op_4 = AutoAssigner.find_free_slot("opencode-go")
    assert slot_op_4 == "opengo-4"

    cfg = load_router_config()
    assert "opengo-4" in cfg.profiles


@pytest.mark.unit
def test_single_account_assigned_to_all_six_roles_p0_3():
    """P0-3: A single account can be assigned as primary across all 6 canonical roles without error."""
    ProfileAuthManager.save_profile_auth("antigravity", "ag-w1", {"tokens": {"access_token": "token-1"}})

    from antigravity_provider.router.role_registry import RoleRegistry
    canonical_roles = list(RoleRegistry.get_role_ids())

    for rname in canonical_roles:
        ok, msg = AutoAssigner.assign_profile_to_role("ag-w1", rname, is_primary=True)
        assert ok is True, f"Failed assigning to role {rname}: {msg}"

    cfg = load_router_config()
    for rname in canonical_roles:
        assert rname in cfg.roles
        assert cfg.roles[rname].preferred_chain[0] == "ag-w1"

    # Verify action executor handles assign_role cleanly
    res = ActionExecutor.execute("assign_role", {"role_id": "manager", "profile_id": "ag-w1", "is_primary": True})
    assert res.get("ok") is True


@pytest.mark.unit
def test_auto_assign_all_single_account_p0_4():
    """P0-4 (Scenario A): Exactly 1 connected account is assigned as primary to all 6 roles."""
    ProfileAuthManager.save_profile_auth("antigravity", "ag-w1", {"tokens": {"access_token": "token-1"}})

    result = AutoAssigner.auto_assign_all()
    assert result["success"] is True
    assert result["total_authenticated"] == 1

    cfg = load_router_config()
    from antigravity_provider.router.role_registry import RoleRegistry
    canonical_roles = list(RoleRegistry.get_role_ids())
    for rname in canonical_roles:
        if RoleRegistry.is_role_implemented(rname):
            assert cfg.roles[rname].preferred_chain == ["ag-w1"]


@pytest.mark.unit
def test_auto_assign_all_two_accounts_same_provider_p0_4():
    """P0-4 (Scenario B): 2 accounts of the same provider are rotated across 6 roles for quota balance."""
    ProfileAuthManager.save_profile_auth("antigravity", "ag-w1", {"tokens": {"access_token": "token-1"}})
    ProfileAuthManager.save_profile_auth("antigravity", "ag-w2", {"tokens": {"access_token": "token-2"}})

    result = AutoAssigner.auto_assign_all()
    assert result["success"] is True
    assert result["total_authenticated"] == 2

    cfg = load_router_config()
    # Primary accounts should alternate between ag-w1 and ag-w2
    primaries = [cfg.roles[r].preferred_chain[0] for r in ["manager", "developer-1", "developer-2", "code-reviewer", "researcher", "tester"]]
    assert "ag-w1" in primaries
    assert "ag-w2" in primaries
    # Fallback chains should contain the alternate account
    for r in ["manager", "developer-1", "developer-2", "code-reviewer", "researcher", "tester"]:
        chain = cfg.roles[r].preferred_chain
        assert len(chain) == 2
        assert set(chain) == {"ag-w1", "ag-w2"}


@pytest.mark.unit
def test_auto_assign_all_multi_provider_preferences_p0_4():
    """P0-4 (Scenario C): Multiple providers are distributed according to canonical role preferences."""
    ProfileAuthManager.save_profile_auth("openai-codex", "codex-orch", {"api_key": "sk-codex"})
    ProfileAuthManager.save_profile_auth("antigravity", "ag-w1", {"tokens": {"access_token": "token-ag"}})
    ProfileAuthManager.save_profile_auth("opencode-go", "opengo-1", {"api_key": "sk-opencode"})

    result = AutoAssigner.auto_assign_all()
    assert result["success"] is True
    assert result["total_authenticated"] == 3

    cfg = load_router_config()
    # Orchestrator prefers codex
    assert cfg.roles["manager"].preferred_chain[0] == "codex-orch"
    # Research / fast prefers opencode
    assert cfg.roles["researcher"].preferred_chain[0] == "opengo-1"
    assert cfg.roles["tester"].preferred_chain[0] == "opengo-1"


@pytest.mark.unit
def test_quota_threshold_notify_action_p0_5(tmp_path: Path):
    """P0-5: When remaining <= threshold and action is 'notify', warnings are logged and profile remains healthy."""
    save_hub_settings({
        "quota_threshold_percent": 10.0,
        "quota_threshold_action": "notify",
    })

    health_file = tmp_path / "hermes" / "router_state.json"
    tracker = HealthTracker(state_file=health_file)

    # Measured quota is 8% (below 10% threshold)
    tracker.reconcile_measured_quota("codex-orch", {"gpt": 8.0})

    # Action is notify: profile should NOT be quota-exhausted
    assert tracker.is_healthy("codex-orch", model_name="gpt-4o") is True

    # Event log should contain warning
    events = EventLogService.get().get_events(limit=10)
    warning_events = [e for e in events if e.level == "warning" and "порог" in e.message.lower()]
    assert len(warning_events) >= 1


@pytest.mark.unit
def test_quota_threshold_switch_action_and_auto_recovery_p0_5(tmp_path: Path):
    """P0-5: When remaining <= threshold and action is 'switch', transitions to QUOTA_EXHAUSTED, and recovers automatically when quota restores."""
    save_hub_settings({
        "quota_threshold_percent": 10.0,
        "quota_threshold_action": "switch",
    })

    health_file = tmp_path / "hermes" / "router_state.json"
    tracker = HealthTracker(state_file=health_file)

    # 1. Low quota (5% <= 10%) -> switch to exhausted
    tracker.reconcile_measured_quota("codex-orch", {"gpt": 5.0})
    assert tracker.is_healthy("codex-orch", model_name="gpt-4o") is False
    rec = tracker.get_or_create("codex-orch")
    assert rec.overall_state == QUOTA_EXHAUSTED or rec.families.get("gpt", {}).state == QUOTA_EXHAUSTED

    # 2. Quota recovers (80% > 10%) -> automatic recovery without restart
    tracker.reconcile_measured_quota("codex-orch", {"gpt": 80.0})
    assert tracker.is_healthy("codex-orch", model_name="gpt-4o") is True
    rec = tracker.get_or_create("codex-orch")
    assert rec.overall_state == HEALTHY
    assert rec.families.get("gpt", {}).state == HEALTHY


@pytest.mark.unit
def test_quota_threshold_zero_fake_p0_5(tmp_path: Path):
    """P0-5: If quota is unknown (None / N/A), threshold does NOT trigger."""
    save_hub_settings({
        "quota_threshold_percent": 10.0,
        "quota_threshold_action": "switch",
    })

    health_file = tmp_path / "hermes" / "router_state.json"
    tracker = HealthTracker(state_file=health_file)

    # Reconcile empty/None measurements
    tracker.reconcile_measured_quota("codex-orch", {})
    assert tracker.is_healthy("codex-orch", model_name="gpt-4o") is True


@pytest.mark.unit
def test_instant_settings_and_state_cache_update_p0_5():
    """P0-5: Saving settings updates cache and state store instantly without restart."""
    res, msg = do_save_settings({
        "quota_threshold_percent": 15.0,
        "quota_threshold_action": "switch",
        "monitoring_interval_seconds": 45,
    })
    assert res is True

    settings = get_hub_settings()
    assert settings["quota_threshold_percent"] == 15.0
    assert settings["quota_threshold_action"] == "switch"
    assert settings["monitoring_interval_seconds"] == 45

    # Check router config sync
    cfg = load_router_config()
    assert cfg.quota_threshold_percent == 15.0
    assert cfg.quota_threshold_action == "switch"


@pytest.mark.unit
def test_web_static_contracts_and_empty_state_p0_2_p0_3_p0_5():
    """Verify web client contract in app.js, style.css and index.html."""
    app_js_path = Path("src/antigravity_provider/router/web/static/app.js")
    style_css_path = Path("src/antigravity_provider/router/web/static/style.css")
    index_html_path = Path("src/antigravity_provider/router/web/static/index.html")

    assert app_js_path.exists()
    assert style_css_path.exists()
    assert index_html_path.exists()

    app_js = app_js_path.read_text(encoding="utf-8")
    style_css = style_css_path.read_text(encoding="utf-8")
    index_html = index_html_path.read_text(encoding="utf-8")

    # P0-2: Accounts empty state and connected-only filter
    assert "accounts-empty-state" in app_js
    assert "accounts-empty-state" in style_css
    assert "Нет подключённых аккаунтов" in app_js

    # P0-3: Overview diagram account selector
    assert "diagram-account-select" in app_js
    assert "diagram-account-select" in style_css
    assert "handleNodeAccountChange" in app_js

    # P0-5: Quota threshold settings
    assert "setting-quota-threshold-percent" in index_html
    assert "setting-quota-threshold-action" in index_html
    assert "quota_threshold_percent" in app_js
    assert "quota_threshold_action" in app_js
