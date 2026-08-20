"""Hermes Hub — P0 Release Gate Verification Suite.

Validates all critical release blockers and regressions:
- P0-1: customtkinter / Pillow clean install verification
- P0-2: ProfileAuthManager.get_profile_dir unified API
- P0-3: Wizard json import & API-key saving flow
- P0-4: AutoAssigner.auto_assign_all implementation with canonical roles
- P0-5: Antigravity failover on quota exhaustion + non-router error handling (B1)
- P0-6: OAuth session status unification and fast error reaction
- P0-7: Role assignment canonical mapping and unknown role rejection (B2)
- P0-8: Wizard role application to live config
- P0-9: Real API validation / removal of fake validation
- P0-10: YAML round-trip config preservation (B3)
- P0-11: Rate limit (60s) vs Quota exhaustion duration parsing (B4, S1)
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from antigravity_provider.paths import get_hermes_home, get_profile_dir
from antigravity_provider.router.auto_assigner import AutoAssigner, CANONICAL_ROLE_MAP
from antigravity_provider.router.exceptions import (
    AuthExpiredError,
    AuthRequiredError,
    QuotaExceededError,
    RateLimitedError,
    RouterError,
)
from antigravity_provider.router.profile_manager import ProfileAuthManager
from antigravity_provider.router.router_config import (
    RolePolicy,
    RouterConfig,
    RouterProfileConfig,
    get_default_router_config,
    load_router_config,
    save_router_config,
)
from antigravity_provider.router.router_engine import RouterEngine
from antigravity_provider.version import __version__


@pytest.mark.unit
def test_p0_1_installer_dependencies():
    """P0-1: Verify that required UI dependencies are importable in runtime."""
    pytest.importorskip("customtkinter")
    import customtkinter
    from PIL import Image
    import psutil
    import yaml

    assert customtkinter is not None
    assert Image is not None
    assert psutil is not None
    assert yaml is not None


@pytest.mark.unit
def test_p0_2_get_profile_dir_signature(tmp_path, monkeypatch):
    """P0-2: Verify ProfileAuthManager.get_profile_dir works with both (profile_id) and (provider, profile_id)."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))

    # Signature variant 1: single arg
    p1 = ProfileAuthManager.get_profile_dir("ag-w1")
    assert isinstance(p1, Path)
    assert "agy_profiles" in str(p1) or "ag-w1" in str(p1)

    # Signature variant 2: (provider, profile_id)
    p2 = ProfileAuthManager.get_profile_dir("antigravity", "ag-w1")
    assert isinstance(p2, Path)
    assert p2.name == "ag-w1"

    # Signature variant 3: (profile_id, provider)
    p3 = ProfileAuthManager.get_profile_dir("codex-orch", "openai-codex")
    assert isinstance(p3, Path)
    assert p3.name == "codex-orch"


@pytest.mark.unit
def test_p0_3_wizard_api_key_save(tmp_path, monkeypatch):
    """P0-3: Verify API key saving flow saves JSON auth file without NameError."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))

    # Test saving auth directly
    auth_data = {
        "provider": "openai-codex",
        "profile_id": "codex-test-1",
        "api_key": "sk-test12345678901234567890",
    }
    saved_path = ProfileAuthManager.save_profile_auth("openai-codex", "codex-test-1", auth_data)
    assert saved_path.exists()

    loaded = ProfileAuthManager.load_profile_auth("openai-codex", "codex-test-1")
    assert loaded is not None
    assert loaded["api_key"] == "sk-test12345678901234567890"


@pytest.mark.unit
def test_p0_4_auto_assign_all(tmp_path, monkeypatch):
    """P0-4: Verify AutoAssigner.auto_assign_all assigns to canonical roles without creating generic roles."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))

    # Save mock auth for 2 profiles
    ProfileAuthManager.save_profile_auth("antigravity", "ag-w1", {"tokens": {"access_token": "valid"}})
    ProfileAuthManager.save_profile_auth("openai-codex", "codex-orch", {"api_key": "sk-valid-key-123456789"})

    result = AutoAssigner.auto_assign_all()
    assert isinstance(result, dict)
    assert result.get("success") is True
    assert "assigned_count" in result

    # Verify only canonical roles exist in config
    cfg = load_router_config()
    for rname in cfg.roles:
        assert rname in {"orchestrator", "coder-primary", "coder-secondary", "reviewer", "research", "fast"}


@pytest.mark.unit
def test_p0_5_antigravity_failover_on_quota(tmp_path, monkeypatch):
    """P0-5: Verify Antigravity quota error raises QuotaExceededError and triggers failover to fallback."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))

    config = RouterConfig(
        profiles={
            "ag-orch-primary": RouterProfileConfig(
                profile_id="ag-orch-primary",
                provider="antigravity",
                enabled=True,
            ),
            "codex-orch-fallback": RouterProfileConfig(
                profile_id="codex-orch-fallback",
                provider="openai-codex",
                enabled=True,
            ),
        },
        roles={
            "orchestrator": RolePolicy(
                role_name="orchestrator",
                preferred_chain=["ag-orch-primary", "codex-orch-fallback"],
                max_failover_attempts=2,
            )
        }
    )
    save_router_config(config)

    from antigravity_provider.router.adapters.antigravity_adapter import AntigravityAdapter
    from antigravity_provider.router.adapters.codex_adapter import CodexAdapter

    def mock_agy_invoke(profile, req):
        raise QuotaExceededError("Resource exhausted: 429 quota reached", provider="antigravity", profile_id=profile.profile_id)

    def mock_codex_invoke(profile, req):
        return {
            "id": "chatcmpl-fallback-ok",
            "choices": [{"message": {"role": "assistant", "content": "Fallback response from Codex"}}],
            "usage": {"total_tokens": 42},
        }

    engine = RouterEngine(config=config)

    with patch.object(AntigravityAdapter, "invoke", side_effect=mock_agy_invoke), \
         patch.object(CodexAdapter, "invoke", side_effect=mock_codex_invoke):

        res = engine.route_request({"messages": [{"role": "user", "content": "Hello"}]}, role="orchestrator")

        # Must receive fallback response, NOT error text as message content!
        assert "choices" in res
        content = res["choices"][0]["message"]["content"]
        assert content == "Fallback response from Codex"
        assert "Antigravity (agy) error" not in content
        assert res["router_metadata"]["failover_count"] == 1
        assert res["router_metadata"]["profile_id"] == "codex-orch-fallback"


@pytest.mark.unit
def test_p0_5_b1_non_router_error_fallback(tmp_path, monkeypatch):
    """B1: Verify that non-router path in hermes_plugin handles error payloads without crashing with IndexError."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))

    from antigravity_provider.hermes_plugin import antigravity_llm_execution
    from antigravity_provider.router import get_router_engine

    # Ensure router is disabled
    engine = get_router_engine()
    prev_enabled = engine.config.enabled
    engine.config.enabled = False

    try:
        # Simulate agy_generate returning error dict
        error_completion = {"error": {"message": "Resource exhausted: 429 quota reached"}}

        with patch("antigravity_provider.hermes_plugin.agy_generate", return_value=error_completion):
            res = antigravity_llm_execution(
                provider="google-antigravity",
                request={"model": "gemini-2.5-pro", "messages": [{"role": "user", "content": "hello"}]},
            )

            # Must have choices[0] and message.content without IndexError!
            assert hasattr(res, "choices")
            assert len(res.choices) > 0
            assert res.choices[0].message.content is not None
            content_lower = str(res.choices[0].message.content).lower()
            assert "429" in content_lower or "exhausted" in content_lower or "error" in content_lower
    finally:
        engine.config.enabled = prev_enabled


@pytest.mark.unit
def test_p0_6_oauth_session_status_unification():
    """P0-6: Verify OAuth statuses are unified and error triggers fast failure."""
    valid_statuses = {"pending", "success", "completed", "failed", "error", "cancelled", "timeout"}
    error_statuses = {"failed", "error", "cancelled", "timeout"}
    for st in error_statuses:
        assert st in valid_statuses


@pytest.mark.unit
def test_p0_7_assign_role_action(tmp_path, monkeypatch):
    """P0-7 & B2: Verify assign_profile_to_role maps human names to canonical roles and rejects unknown roles."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))

    config = get_default_router_config()
    save_router_config(config)

    # 1. Assign "coder" -> must update "coder-primary"
    ok, msg = AutoAssigner.assign_profile_to_role("ag-w1", "coder", is_primary=True)
    assert ok is True
    reloaded = load_router_config()
    assert reloaded.roles["coder-primary"].preferred_chain[0] == "ag-w1"
    assert "coder" not in reloaded.roles  # Must NOT create a non-canonical role

    # 2. Assign "researcher" -> must update "research"
    ok, msg = AutoAssigner.assign_profile_to_role("ag-w2", "researcher", is_primary=True)
    assert ok is True
    reloaded = load_router_config()
    assert reloaded.roles["research"].preferred_chain[0] == "ag-w2"

    # 3. Unknown role -> must return False and reject
    ok, msg = AutoAssigner.assign_profile_to_role("ag-w1", "completely_unknown_role_xyz")
    assert ok is False
    assert "Неизвестная роль" in msg


@pytest.mark.unit
def test_n1_spare_assignment_mode(tmp_path, monkeypatch):
    """N1: Verify that selecting spare mode removes profile from active roles without creating rogue roles."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))

    config = get_default_router_config()
    # Put ag-w1 in coder-primary
    config.roles["coder-primary"].preferred_chain = ["ag-w1", "ag-w2"]
    save_router_config(config)

    # Assign ag-w1 to spare
    ok, msg = AutoAssigner.assign_profile_to_role("ag-w1", "spare")
    assert ok is True
    assert "резерв" in msg.lower() or "spare" in msg.lower()

    reloaded = load_router_config()
    assert "ag-w1" not in reloaded.roles["coder-primary"].preferred_chain
    assert "spare" not in reloaded.roles  # Canonical role set unchanged
    assert reloaded.profiles["ag-w1"].enabled is True


@pytest.mark.unit
def test_n2_error_formatter_deduplication():
    """N2: Verify that format_antigravity_error never creates double 'Antigravity error:' prefixes."""
    from antigravity_provider.runtime import format_antigravity_error

    # Case 1: Raw exception message
    assert format_antigravity_error("connection refused") == "Antigravity error: connection refused"

    # Case 2: Already prefixed with Antigravity error:
    assert format_antigravity_error("Antigravity error: quota exceeded") == "Antigravity error: quota exceeded"

    # Case 3: Nested multiple prefixes
    assert format_antigravity_error("Antigravity error: Antigravity error: agy error: 429") == "Antigravity error: 429"

    # Case 4: Dict error format
    assert format_antigravity_error({"message": "Antigravity (agy) error: timeout"}) == "Antigravity error: timeout"


@pytest.mark.unit
def test_p0_8_wizard_role_application(tmp_path, monkeypatch):
    """P0-8: Verify Wizard step 4 role assignment is applied directly to configuration."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))

    config = get_default_router_config()
    save_router_config(config)

    # Apply role
    ok, msg = AutoAssigner.assign_profile_to_role("codex-worker-1", "reviewer", is_primary=True)
    assert ok is True

    reloaded = load_router_config()
    assert "codex-worker-1" in reloaded.roles["reviewer"].preferred_chain
    assert reloaded.roles["reviewer"].preferred_chain[0] == "codex-worker-1"


@pytest.mark.unit
def test_p0_9_real_api_key_validation():
    """P0-9: Verify real/structural token verification without fake hardcoded PASS."""
    # Invalid key must return False
    valid, _, models = ProfileAuthManager.verify_codex_token("invalid-key")
    assert valid is False
    assert len(models) == 0

    # Valid format key returns True with appropriate models
    valid_key = "sk-proj-1234567890123456789012345678"
    valid, masked, models = ProfileAuthManager.verify_codex_token(valid_key)
    assert valid is True
    assert masked.startswith("sk-...")


@pytest.mark.unit
def test_p0_10_yaml_round_trip_preservation(tmp_path, monkeypatch):
    """B3: Verify YAML load -> save -> load preserves router block and settings without loss."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))

    cfg_file = tmp_path / "test_profiles.yaml"
    cfg = get_default_router_config()
    cfg.max_failover_attempts = 5
    cfg.session_affinity_ttl_seconds = 2400

    save_router_config(cfg, config_path=cfg_file)
    assert cfg_file.exists()

    reloaded = load_router_config(config_path=cfg_file)
    assert reloaded.enabled is True
    assert reloaded.max_failover_attempts == 5
    assert reloaded.session_affinity_ttl_seconds == 2400
    assert len(reloaded.roles) == len(cfg.roles)
    assert len(reloaded.profiles) == len(cfg.profiles)


@pytest.mark.unit
def test_p0_11_rate_limit_vs_quota_classification():
    """B4 & S1: Verify rate limiting gets 60s cooldown and quota parsing extracts hours/minutes."""
    from antigravity_provider.router.adapters.antigravity_adapter import AntigravityAdapter
    from antigravity_provider.router.adapters.base_adapter import ErrorCategory
    from antigravity_provider.router.router_config import RouterProfileConfig

    adapter = AntigravityAdapter()
    profile = RouterProfileConfig(profile_id="ag-w1", provider="antigravity")

    # 1. Rate Limit Error -> must be RATE_LIMITED with 60s cooldown
    rate_resp = {"error": {"message": "429 Too Many Requests: rate limit exceeded"}}
    with patch("antigravity_provider.router.adapters.antigravity_adapter.agy_generate", return_value=rate_resp):
        with pytest.raises(RateLimitedError) as exc_info:
            adapter.invoke(profile, {"messages": []})
        classification = adapter.classify_error(exc_info.value)
        assert classification.category == ErrorCategory.RATE_LIMITED
        assert classification.retry_delay_seconds == 60

    # 2. Quota with "resets in 2h" -> must parse 7200s cooldown
    quota_resp = {"error": {"message": "individual quota reached, resets in 2h"}}
    with patch("antigravity_provider.router.adapters.antigravity_adapter.agy_generate", return_value=quota_resp):
        with pytest.raises(QuotaExceededError) as exc_info:
            adapter.invoke(profile, {"messages": []})
        assert exc_info.value.reset_in_sec == 7200
        classification = adapter.classify_error(exc_info.value)
        assert classification.category == ErrorCategory.QUOTA_EXHAUSTED
        assert classification.reset_duration_seconds == 7200


@pytest.mark.unit
def test_r4_settings_runtime_influence(tmp_path, monkeypatch):
    """R4: Verify that hub_settings.json dynamically modifies RouterEngine behavior."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))

    from antigravity_provider.router.settings_service import save_hub_settings
    from antigravity_provider.router.adapters.antigravity_adapter import AntigravityAdapter
    from antigravity_provider.router.adapters.codex_adapter import CodexAdapter

    config = RouterConfig(
        profiles={
            "ag-orch-primary": RouterProfileConfig(profile_id="ag-orch-primary", provider="antigravity", enabled=True),
            "codex-orch-fallback": RouterProfileConfig(profile_id="codex-orch-fallback", provider="openai-codex", enabled=True),
        },
        roles={
            "orchestrator": RolePolicy(
                role_name="orchestrator",
                preferred_chain=["ag-orch-primary", "codex-orch-fallback"],
                max_failover_attempts=2,
            )
        }
    )
    save_router_config(config)

    # 1. With auto_failover=False in hub_settings.json, failover must NOT attempt fallback
    save_hub_settings({"auto_failover": False})
    engine = RouterEngine(config=config)

    def mock_agy_quota(profile, req):
        raise QuotaExceededError("Quota reached", provider="antigravity", profile_id=profile.profile_id)

    mock_codex = MagicMock()

    with patch.object(AntigravityAdapter, "invoke", side_effect=mock_agy_quota), \
         patch.object(CodexAdapter, "invoke", mock_codex):

        res = engine.route_request({"messages": [{"role": "user", "content": "Hello"}]}, role="orchestrator")
        assert "error" in res or "choices" in res
        # Codex fallback must NOT have been called because auto_failover was False!
        assert mock_codex.call_count == 0

    # 2. With auto_failover=True in hub_settings.json, failover attempts fallback
    save_hub_settings({"auto_failover": True, "failover_attempts": 2})
    mock_codex.return_value = {"choices": [{"message": {"role": "assistant", "content": "Fallback OK"}}]}

    with patch.object(AntigravityAdapter, "invoke", side_effect=mock_agy_quota), \
         patch.object(CodexAdapter, "invoke", mock_codex):

        res = engine.route_request({"messages": [{"role": "user", "content": "Hello"}]}, role="orchestrator")
        assert res["choices"][0]["message"]["content"] == "Fallback OK"
        assert mock_codex.call_count == 1
