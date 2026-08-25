"""End-to-end verification for Grok and Claude connection, assignment, and testing."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
import pytest

from antigravity_provider.router.auto_assigner import AutoAssigner
from antigravity_provider.router import action_handler
from antigravity_provider.router.router_config import RouterConfig, RouterProfileConfig, RolePolicy
from antigravity_provider.router.ui.add_account_wizard import ensure_profile_in_routing
from antigravity_provider.router.hermes_hub_app import do_test_profile


@pytest.mark.unit
def test_grok_and_claude_free_slots_discovery():
    """Verify free slots for grok and claude can be found from default slots."""
    config = RouterConfig(
        profiles={
            "grok-worker-1": RouterProfileConfig(profile_id="grok-worker-1", provider="grok", enabled=True),
            "claude-orch": RouterProfileConfig(profile_id="claude-orch", provider="claude", enabled=True),
        }
    )
    with patch("antigravity_provider.router.auto_assigner.load_router_config", return_value=config):
        grok_slot = AutoAssigner.find_free_slot("grok")
        assert grok_slot == "grok-worker-1"

        claude_slot = AutoAssigner.find_free_slot("claude")
        assert claude_slot == "claude-orch"


@pytest.mark.unit
def test_grok_wizard_definition_and_routing_flow():
    """Verify Grok profile definition and routing pipeline addition."""
    config = RouterConfig(
        profiles={},
        roles={"developer-1": RolePolicy(role_name="developer-1", preferred_chain=[])},
    )
    with patch("antigravity_provider.router.auto_assigner.load_router_config", return_value=config), \
         patch("antigravity_provider.router.auto_assigner.save_router_config", return_value=True), \
         patch("antigravity_provider.router.ui.add_account_wizard.load_router_config", return_value=config):
        
        ok_def, msg_def = AutoAssigner.ensure_profile_definition("grok", "grok-worker-1")
        assert ok_def, f"Definition failed: {msg_def}"
        assert "grok-worker-1" in config.profiles
        assert config.profiles["grok-worker-1"].provider == "grok"

        ok_route, msg_route = ensure_profile_in_routing("grok-worker-1")
        assert ok_route, f"Routing failed: {msg_route}"
        assert "grok-worker-1" in config.roles["developer-1"].preferred_chain


@pytest.mark.unit
def test_claude_wizard_definition_and_routing_flow():
    """Verify Claude profile definition and routing pipeline addition."""
    config = RouterConfig(
        profiles={},
        roles={"manager": RolePolicy(role_name="manager", preferred_chain=[])},
    )
    with patch("antigravity_provider.router.auto_assigner.load_router_config", return_value=config), \
         patch("antigravity_provider.router.auto_assigner.save_router_config", return_value=True), \
         patch("antigravity_provider.router.ui.add_account_wizard.load_router_config", return_value=config):
        
        ok_def, msg_def = AutoAssigner.ensure_profile_definition("claude", "claude-orch")
        assert ok_def, f"Definition failed: {msg_def}"
        assert "claude-orch" in config.profiles
        assert config.profiles["claude-orch"].provider == "claude"

        ok_route, msg_route = ensure_profile_in_routing("claude-orch")
        assert ok_route, f"Routing failed: {msg_route}"
        assert "claude-orch" in config.roles["manager"].preferred_chain


@pytest.mark.unit
def test_do_test_profile_for_grok_and_claude():
    """Verify profile local test helper handles grok and claude profiles."""
    config = RouterConfig(
        profiles={
            "grok-worker-1": RouterProfileConfig(profile_id="grok-worker-1", provider="grok", preferred_models=["grok-beta"]),
            "claude-orch": RouterProfileConfig(profile_id="claude-orch", provider="claude", preferred_models=["claude-3-5-sonnet"]),
        }
    )
    
    mock_adapter = MagicMock()
    mock_adapter.health_check.return_value = True

    with patch("antigravity_provider.router.action_handler.load_router_config", return_value=config), \
         patch("antigravity_provider.router.profile_manager.ProfileAuthManager.get_profile_status", return_value={"authenticated": True, "is_expired": False}), \
         patch("antigravity_provider.router.profile_manager.ProfileAuthManager.load_profile_auth", return_value={"api_key": "test"}), \
         patch("antigravity_provider.router.action_handler.get_adapter", return_value=mock_adapter):
        
        res_grok = do_test_profile("grok", "grok-worker-1")
        assert res_grok["success"] is True
        assert res_grok["model"] == "grok-beta"

        res_claude = do_test_profile("claude", "claude-orch")
        assert res_claude["success"] is True
        assert res_claude["model"] == "claude-3-5-sonnet"
