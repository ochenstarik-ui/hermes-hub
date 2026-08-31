"""Comprehensive test suite for Hermes Multi-Provider Account Router."""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

# Ensure plugin package is in sys.path
repo_root = Path(__file__).resolve().parent.parent
plugin_src = repo_root / "plugins" / "antigravity-provider" / "src"
if str(plugin_src) not in sys.path:
    sys.path.insert(0, str(plugin_src))

from antigravity_provider.router.router_config import (
    RolePolicy,
    RouterConfig,
    RouterProfileConfig,
    get_default_router_config,
    load_router_config,
)
from antigravity_provider.router.health_tracker import (
    AUTH_REQUIRED,
    DISABLED,
    HEALTHY,
    IN_USE,
    QUOTA_EXHAUSTED,
    RATE_LIMITED,
    HealthTracker,
    extract_model_family,
)
from antigravity_provider.router.session_affinity import LeaseManager, SessionAffinityTracker
from antigravity_provider.router.router_engine import RouterEngine, get_router_engine
from antigravity_provider.router.adapters.base_adapter import ErrorCategory, ErrorClassification
from antigravity_provider.router.adapters.antigravity_adapter import AntigravityAdapter, get_profile_env_dir
from antigravity_provider.router.adapters.codex_adapter import CodexAdapter
from antigravity_provider.router.adapters.opencode_adapter import OpenCodeGoAdapter
from antigravity_provider.router.cli_commands import (
    clear_cooldown_cli,
    print_router_status,
    print_routing_policy,
    simulate_quota_cli,
)


class TestRouterConfig:
    """Test configuration schema, clean default config, and role definitions."""

    def test_default_config_is_clean(self):
        config = get_default_router_config()
        assert len(config.profiles) == 0
        assert len(config.roles) == 14
        assert config.default_role == "manager"
        assert config.enabled is True

    def test_role_policies_chains(self):
        config = get_default_router_config()
        assert "manager" in config.roles
        assert "developer-1" in config.roles
        assert "developer-2" in config.roles
        assert "code-reviewer" in config.roles
        assert "researcher" in config.roles
        assert "tester" in config.roles
        assert "tech-writer" in config.roles
        assert "analyst" in config.roles
        assert "guardian" in config.roles
        assert "cost-controller" in config.roles
        assert "integration-expert" in config.roles
        assert "security-expert" in config.roles
        assert "dependency-agent" in config.roles

        for rname, rpol in config.roles.items():
            assert rpol.preferred_chain == [], f"Expected empty chain for {rname} on clean install"


class TestHealthTracker:
    """Test health state tracking, model families, and simulation."""

    def test_model_family_extraction(self):
        assert extract_model_family("gemini-3.7-flash") == "gemini"
        assert extract_model_family("claude-sonnet-4-6") == "claude"
        assert extract_model_family("gpt-4o") == "gpt"
        assert extract_model_family("deepseek-v4-pro") == "deepseek"
        assert extract_model_family("kimi-k2.7-code") == "kimi"
        assert extract_model_family("qwen3.8-max") == "qwen"
        assert extract_model_family("grok-4.5") == "grok"
        assert extract_model_family("glm-5.3") == "glm"

    def test_quota_exhaustion_and_expiry(self, tmp_path):
        state_file = tmp_path / "test_state.json"
        tracker = HealthTracker(state_file=state_file)

        # Initially healthy
        assert tracker.is_healthy("ag-w1", "gemini-3.7-flash") is True

        # Mark quota exhausted with 2 second duration
        tracker.mark_quota_exhausted("ag-w1", "gemini-3.7-flash", duration=2, reason="Quota reached")
        assert tracker.is_healthy("ag-w1", "gemini-3.7-flash") is False

        # Wait for expiration
        time.sleep(2.1)
        assert tracker.is_healthy("ag-w1", "gemini-3.7-flash") is True

    def test_simulated_quota_and_clear(self, tmp_path):
        state_file = tmp_path / "test_state.json"
        tracker = HealthTracker(state_file=state_file)

        tracker.simulate_quota("codex-orch", duration=600)
        assert tracker.is_healthy("codex-orch") is False
        rec = tracker.get_or_create("codex-orch")
        assert rec.simulated is True

        # Clear cooldown
        tracker.clear_cooldown("codex-orch")
        assert tracker.is_healthy("codex-orch") is True
        assert tracker.get_or_create("codex-orch").simulated is False


class TestSessionAffinityAndLeases:
    """Test session affinity retention and concurrency leases."""

    def test_session_affinity_lifecycle(self):
        affinity = SessionAffinityTracker()
        assert affinity.get_affinity("sess-1") is None

        affinity.set_affinity("sess-1", "manager", "codex-orch", "gpt-4o")
        rec = affinity.get_affinity("sess-1")
        assert rec is not None
        assert rec.profile_id == "codex-orch"
        assert rec.role == "manager"

        # Update on failover
        affinity.set_affinity("sess-1", "manager", "ag-orch-fallback", "gemini-3.7-flash")
        rec2 = affinity.get_affinity("sess-1")
        assert rec2.profile_id == "ag-orch-fallback"

    def test_lease_concurrency(self):
        leases = LeaseManager()
        assert leases.acquire("ag-w1", max_concurrency=1) is True
        # Exceeds concurrency 1
        assert leases.acquire("ag-w1", max_concurrency=1) is False
        assert leases.active_count("ag-w1") == 1

        leases.release("ag-w1")
        assert leases.active_count("ag-w1") == 0
        assert leases.acquire("ag-w1", max_concurrency=1) is True


class TestRouterEngineFailover:
    """Test multi-provider role-aware failover execution loop."""

    @staticmethod
    def _get_test_config() -> RouterConfig:
        return RouterConfig(
            enabled=True,
            default_role="manager",
            roles={
                "manager": RolePolicy(
                    role_name="manager",
                    preferred_chain=["codex-orch", "ag-orch-fallback", "opengo-3"],
                    max_failover_attempts=3,
                    session_affinity_enabled=True,
                )
            },
            profiles={
                "codex-orch": RouterProfileConfig(profile_id="codex-orch", provider="openai-codex"),
                "ag-orch-fallback": RouterProfileConfig(profile_id="ag-orch-fallback", provider="antigravity"),
                "opengo-3": RouterProfileConfig(profile_id="opengo-3", provider="opencode-go"),
            },
        )

    def test_orchestrator_failover_chain(self, tmp_path):
        state_file = tmp_path / "test_router_state.json"
        engine = RouterEngine(
            config=self._get_test_config(),
            health=HealthTracker(state_file=state_file),
            affinity=SessionAffinityTracker(),
        )

        # Mock adapter responses
        mock_codex_response = {"id": "codex-1", "choices": [{"message": {"role": "assistant", "content": "from-codex"}}]}
        mock_ag_response = {"id": "ag-1", "choices": [{"message": {"role": "assistant", "content": "from-antigravity"}}]}
        mock_opengo_response = {"id": "opengo-1", "choices": [{"message": {"role": "assistant", "content": "from-opencode"}}]}

        # 1. Normal state: codex-orch succeeds
        with patch.object(CodexAdapter, "invoke", return_value=mock_codex_response):
            resp = engine.route_request({"messages": [{"role": "user", "content": "hello"}]}, role="manager", session_id="sess-orch-1")
            assert resp["choices"][0]["message"]["content"] == "from-codex"
            assert resp["router_metadata"]["profile_id"] == "codex-orch"

        # 2. Simulate quota on codex-orch: should auto-failover to ag-orch-fallback
        engine.health.simulate_quota("codex-orch", duration=600)
        with patch.object(AntigravityAdapter, "invoke", return_value=mock_ag_response):
            resp2 = engine.route_request({"messages": [{"role": "user", "content": "hello again"}]}, role="manager", session_id="sess-orch-2")
            assert resp2["choices"][0]["message"]["content"] == "from-antigravity"
            assert resp2["router_metadata"]["profile_id"] == "ag-orch-fallback"
            assert resp2["router_metadata"]["failover_count"] == 0  # picked directly because codex-orch was marked unhealthy

        # 3. Simulate quota on both codex-orch and ag-orch-fallback: should failover to opengo-3
        engine.health.simulate_quota("ag-orch-fallback", duration=600)
        with patch.object(OpenCodeGoAdapter, "invoke", return_value=mock_opengo_response):
            resp3 = engine.route_request({"messages": [{"role": "user", "content": "hello third"}]}, role="manager", session_id="sess-orch-3")
            assert resp3["choices"][0]["message"]["content"] == "from-opencode"
            assert resp3["router_metadata"]["profile_id"] == "opengo-3"

        # Clear cooldowns
        engine.health.clear_cooldown()
        assert engine.health.is_healthy("codex-orch") is True
        assert engine.health.is_healthy("ag-orch-fallback") is True

    def test_session_affinity_retention_after_failover(self, tmp_path):
        state_file = tmp_path / "test_affinity_state.json"
        engine = RouterEngine(
            config=self._get_test_config(),
            health=HealthTracker(state_file=state_file),
            affinity=SessionAffinityTracker(),
        )

        mock_codex = {"id": "c1", "choices": [{"message": {"role": "assistant", "content": "c1"}}]}
        mock_ag = {"id": "a1", "choices": [{"message": {"role": "assistant", "content": "a1"}}]}

        # Turn 1: codex-orch fails with quota exhaustion -> failover to ag-orch-fallback
        with patch.object(CodexAdapter, "invoke", side_effect=RuntimeError("Quota limit reached")):
            with patch.object(AntigravityAdapter, "invoke", return_value=mock_ag):
                resp = engine.route_request({"messages": [{"role": "user", "content": "turn 1"}]}, role="manager", session_id="session-user-123")
                assert resp["choices"][0]["message"]["content"] == "a1"
                assert resp["router_metadata"]["profile_id"] == "ag-orch-fallback"

        # Turn 2: same session continues directly on ag-orch-fallback
        with patch.object(AntigravityAdapter, "invoke", return_value=mock_ag):
            resp2 = engine.route_request({"messages": [{"role": "user", "content": "turn 2"}]}, role="manager", session_id="session-user-123")
            assert resp2["choices"][0]["message"]["content"] == "a1"
            assert resp2["router_metadata"]["profile_id"] == "ag-orch-fallback"


class TestAntigravityIsolation:
    """Test environment isolation for Antigravity profiles."""

    def test_profile_env_dir_creation(self):
        pdir = get_profile_env_dir("ag-w1")
        assert pdir.exists()
        assert "ag-w1" in str(pdir)


class TestRouterCLI:
    """Test CLI commands: status, policy, simulate, clear-cooldown."""

    def test_print_router_status(self, capsys):
        rc = print_router_status()
        assert rc == 0
        out = capsys.readouterr().out
        assert "HERMES MULTI-PROVIDER ACCOUNT ROUTER" in out
        assert "manager" in out or "developer-1" in out or "ag-w1" in out

    def test_print_routing_policy(self, capsys):
        rc = print_routing_policy()
        assert rc == 0
        out = capsys.readouterr().out
        assert "manager" in out
        assert "developer-1" in out
        assert "code-reviewer" in out

    def test_simulate_quota_cli(self, capsys):
        rc = simulate_quota_cli("codex-orch", duration=300)
        assert rc == 0
        out = capsys.readouterr().out
        assert "Simulated quota exhaustion activated" in out

        rc_clear = clear_cooldown_cli("codex-orch")
        assert rc_clear == 0
        out_clear = capsys.readouterr().out
        assert "cleared for profile 'codex-orch'" in out_clear
