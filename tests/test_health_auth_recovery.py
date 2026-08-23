"""Tests for health tracker and router profile self-recovery from AUTH_REQUIRED state."""
from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from antigravity_provider.router.adapters.antigravity_adapter import AntigravityAdapter
from antigravity_provider.router.health_tracker import (
    AUTH_REQUIRED,
    HEALTHY,
    HealthTracker,
)
from antigravity_provider.router.profile_manager import ProfileAuthManager
from antigravity_provider.router.router_config import (
    RolePolicy,
    RouterConfig,
    RouterProfileConfig,
)
from antigravity_provider.router.router_engine import RouterEngine


@pytest.fixture
def isolated_env(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    state_file = tmp_path / "router_state.json"
    ht = HealthTracker(state_file=state_file)
    return tmp_path, ht


def test_auth_required_skipped_in_routing(isolated_env):
    tmp_path, ht = isolated_env

    # Configure 2 profiles for role 'orchestrator'
    cfg = RouterConfig(
        profiles={
            "ag-orch-1": RouterProfileConfig(
                profile_id="ag-orch-1",
                provider="antigravity",
                enabled=True,
            ),
            "ag-orch-2": RouterProfileConfig(
                profile_id="ag-orch-2",
                provider="antigravity",
                enabled=True,
            ),
        },
        roles={
            "orchestrator": RolePolicy(
                role_name="orchestrator",
                preferred_chain=["ag-orch-1", "ag-orch-2"],
            ),
        },
        default_role="orchestrator",
    )

    engine = RouterEngine(config=cfg, health=ht)

    def _mock_invoke(*args, **kwargs):
        return {"id": "res-1", "choices": [{"message": {"role": "assistant", "content": "hello"}}]}

    # Initial state: ag-orch-1 is healthy and selected
    with patch.object(AntigravityAdapter, "invoke", side_effect=_mock_invoke):
        res = engine.route_request({"prompt": "hi"}, role="orchestrator")
        assert res.get("router_metadata", {}).get("profile_id") == "ag-orch-1"

    # Mark ag-orch-1 as AUTH_REQUIRED
    ht.mark_auth_required("ag-orch-1", reason="401 Unauthorized token expired")
    assert not ht.is_healthy("ag-orch-1")

    # Routing should skip ag-orch-1 and route to ag-orch-2
    with patch.object(AntigravityAdapter, "invoke", side_effect=_mock_invoke):
        res = engine.route_request({"prompt": "hi"}, role="orchestrator")
        assert res.get("router_metadata", {}).get("profile_id") == "ag-orch-2"


def test_save_profile_auth_auto_recovery(isolated_env):
    tmp_path, ht = isolated_env

    cfg = RouterConfig(
        profiles={
            "ag-orch-1": RouterProfileConfig(
                profile_id="ag-orch-1",
                provider="antigravity",
                enabled=True,
            ),
            "ag-orch-2": RouterProfileConfig(
                profile_id="ag-orch-2",
                provider="antigravity",
                enabled=True,
            ),
        },
        roles={
            "orchestrator": RolePolicy(
                role_name="orchestrator",
                preferred_chain=["ag-orch-1", "ag-orch-2"],
            ),
        },
        default_role="orchestrator",
    )
    engine = RouterEngine(config=cfg, health=ht)

    def _mock_invoke(*args, **kwargs):
        return {"id": "res-1", "choices": [{"message": {"role": "assistant", "content": "hello"}}]}

    # Mark ag-orch-1 as AUTH_REQUIRED
    ht.mark_auth_required("ag-orch-1", reason="Auth token rejected")
    rec = ht.get_or_create("ag-orch-1")
    assert rec.overall_state == AUTH_REQUIRED
    assert rec.last_error == "Auth token rejected"
    assert not ht.is_healthy("ag-orch-1")

    # Saving credentials via ProfileAuthManager publishes event and auto-recovers health
    ProfileAuthManager.save_profile_auth(
        "antigravity",
        "ag-orch-1",
        {"token": {"access_token": "valid_tok_123", "refresh_token": "ref_123"}},
    )

    # State is automatically restored to HEALTHY without manual clear_cooldown
    rec = ht.get_or_create("ag-orch-1")
    assert rec.overall_state == HEALTHY
    assert rec.last_error is None
    assert ht.is_healthy("ag-orch-1")

    # Router now routes back to primary profile ag-orch-1
    with patch.object(AntigravityAdapter, "invoke", side_effect=_mock_invoke):
        res = engine.route_request({"prompt": "hi"}, role="orchestrator")
        assert res.get("router_metadata", {}).get("profile_id") == "ag-orch-1"


def test_auth_file_mtime_recovery_in_is_healthy(isolated_env):
    tmp_path, ht = isolated_env

    # Setup profile directory and initial auth file
    pdir = tmp_path / "agy_profiles" / "ag-test-1"
    pdir.mkdir(parents=True, exist_ok=True)
    auth_file = pdir / "auth.json"
    auth_file.write_text(json.dumps({"token": "old"}), encoding="utf-8")
    time.sleep(0.05)

    # Mark AUTH_REQUIRED at a timestamp
    ht.mark_auth_required("ag-test-1", reason="OAuth error")
    rec = ht.get_or_create("ag-test-1")
    assert rec.overall_state == AUTH_REQUIRED
    assert not ht.is_healthy("ag-test-1")

    # Now update auth.json with newer mtime
    time.sleep(0.05)
    auth_file.write_text(json.dumps({"token": {"access_token": "new_refreshed_token"}}), encoding="utf-8")

    # Calling is_healthy should detect the newer valid auth file and auto-recover
    assert ht.is_healthy("ag-test-1")
    rec = ht.get_or_create("ag-test-1")
    assert rec.overall_state == HEALTHY
    assert rec.last_error is None


def test_clear_cooldown_full_reset(isolated_env):
    tmp_path, ht = isolated_env

    ht.mark_auth_required("ag-1", reason="Invalid grant")
    rec = ht.get_or_create("ag-1")
    assert rec.overall_state == AUTH_REQUIRED
    assert rec.last_error == "Invalid grant"

    # clear_cooldown should completely reset overall_state and last_error
    ht.clear_cooldown("ag-1")
    rec = ht.get_or_create("ag-1")
    assert rec.overall_state == HEALTHY
    assert rec.last_error is None
    for frec in rec.families.values():
        assert frec.state == HEALTHY
        assert frec.last_error is None
        assert frec.reason is None
