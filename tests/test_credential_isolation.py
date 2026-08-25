"""Tests for subprocess credential isolation and provider selection explanation."""
from __future__ import annotations

import ast
import os
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock, patch
import pytest

from antigravity_provider.agy_subprocess import (
    build_safe_subprocess_env,
    SAFE_SYSTEM_ENV_VARS,
    BLOCKED_SECRET_PATTERNS,
)
from antigravity_provider.router.adapters.antigravity_adapter import AntigravityAdapter
from antigravity_provider.router.router_config import (
    RolePolicy,
    RouterConfig,
    RouterProfileConfig,
    get_default_router_config,
)
from antigravity_provider.router.router_engine import RouterEngine
from antigravity_provider import paths


@pytest.mark.unit
def test_build_safe_subprocess_env_strips_all_provider_secrets():
    """Verify that build_safe_subprocess_env strictly filters out provider secrets and tokens."""
    dirty_env = {
        # System variables that must be preserved
        "PATH": "C:\\Windows\\system32;C:\\Python312",
        "SYSTEMROOT": "C:\\Windows",
        "LOCALAPPDATA": "C:\\Users\\test\\AppData\\Local",
        "TEMP": "C:\\Users\\test\\AppData\\Local\\Temp",
        "USERPROFILE": "C:\\Users\\test",
        # Foreign provider keys and secrets that MUST be stripped
        "OPENAI_API_KEY": "sk-proj-secret123456789",
        "CODEX_TOKEN_MAIN": "codex-jwt-token-xyz",
        "CODEX_API_KEY": "sk-codex-key",
        "ANTHROPIC_API_KEY": "sk-ant-secret98765",
        "DEEPSEEK_API_KEY": "sk-deepseek-secret",
        "OPENCODE_GO_API_KEY": "opencode-key-456",
        "XAI_API_KEY": "xai-secret-key",
        "GROK_API_KEY": "grok-secret-key",
        "HERMES_API_SECRET": "hermes-super-secret",
        "MY_AUTH_TOKEN": "bearer-token-val",
        "GEMINI_API_KEY": "ai-studio-gemini-key",
        "GOOGLE_API_KEY": "google-api-key-val",
    }

    clean = build_safe_subprocess_env(
        base_env=dirty_env,
        overrides={"USERPROFILE": "C:\\HermesProfiles\\ag-w1", "HOME": "C:\\HermesProfiles\\ag-w1"},
    )

    # Allowed system vars preserved
    assert clean["PATH"] == "C:\\Windows\\system32;C:\\Python312"
    assert clean["SYSTEMROOT"] == "C:\\Windows"
    assert clean["LOCALAPPDATA"] == "C:\\Users\\test\\AppData\\Local"
    assert clean["USERPROFILE"] == "C:\\HermesProfiles\\ag-w1"
    assert clean["HOME"] == "C:\\HermesProfiles\\ag-w1"

    # All secret keys strictly absent
    for secret_key in [
        "OPENAI_API_KEY", "CODEX_TOKEN_MAIN", "CODEX_API_KEY",
        "ANTHROPIC_API_KEY", "DEEPSEEK_API_KEY", "OPENCODE_GO_API_KEY",
        "XAI_API_KEY", "GROK_API_KEY", "HERMES_API_SECRET",
        "MY_AUTH_TOKEN", "GEMINI_API_KEY", "GOOGLE_API_KEY",
    ]:
        assert secret_key not in clean, f"Secret key '{secret_key}' leaked into clean subprocess environment!"


@pytest.mark.unit
def test_antigravity_adapter_subprocess_env_isolation(tmp_path, monkeypatch):
    """Verify that AntigravityAdapter passes a sanitized custom_env to agy subprocess."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-leaked-key")
    monkeypatch.setenv("CODEX_TOKEN_1", "codex-token-leaked")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-leaked")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-deepseek-leaked")
    monkeypatch.setenv("OPENCODE_GO_API_KEY", "sk-opencode-leaked")

    profile = RouterProfileConfig(
        profile_id="ag-w1",
        provider="antigravity",
        preferred_models=["gemini-2.5-pro"],
        enabled=True,
    )

    captured_env: Dict[str, str] = {}

    import subprocess
    orig_run = subprocess.run

    def mock_subprocess_run(*args, **kwargs):
        nonlocal captured_env
        if "env" in kwargs and kwargs["env"]:
            captured_env = dict(kwargs["env"])
        # Mock successful agy JSON output
        mock_res = MagicMock()
        mock_res.stdout = '{"choices": [{"message": {"role": "assistant", "content": "Subprocess response OK"}}]}'
        mock_res.returncode = 0
        return mock_res

    adapter = AntigravityAdapter()
    with patch("subprocess.run", side_effect=mock_subprocess_run):
        res = adapter.invoke(profile, {"messages": [{"role": "user", "content": "hi"}]})

    assert captured_env, "subprocess.run was not invoked with an explicit env dictionary"

    # Verify no foreign secrets leaked into the child process
    for secret in ["OPENAI_API_KEY", "CODEX_TOKEN_1", "ANTHROPIC_API_KEY", "DEEPSEEK_API_KEY", "OPENCODE_GO_API_KEY"]:
        assert secret not in captured_env, f"Subprocess environment leaked '{secret}'!"

    # Verify isolated profile directory is applied
    assert "USERPROFILE" in captured_env
    assert "ag_profiles" in captured_env["USERPROFILE"] or "ag-w1" in captured_env["USERPROFILE"]


@pytest.mark.unit
def test_no_unfiltered_environ_copy_in_src():
    """Static AST audit asserting that src/ does not pass raw dict(os.environ) or os.environ.copy() to subprocesses."""
    src_dir = paths.get_repo_root() / "src"
    violations = []

    for py_file in src_dir.rglob("*.py"):
        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        except Exception:
            continue

        for node in ast.walk(tree):
            # Check for dict(os.environ) without build_safe_subprocess_env
            if isinstance(node, ast.Call):
                # Call to dict(os.environ)
                if isinstance(node.func, ast.Name) and node.func.id == "dict":
                    if node.args and isinstance(node.args[0], ast.Attribute):
                        arg = node.args[0]
                        if isinstance(arg.value, ast.Name) and arg.value.id == "os" and arg.attr == "environ":
                            # Check if this file is agy_subprocess where build_safe_subprocess_env uses base_env or os.environ
                            if py_file.name != "agy_subprocess.py":
                                violations.append(f"{py_file.name}:{node.lineno} calls dict(os.environ) directly")

                # Call to os.environ.copy()
                elif isinstance(node.func, ast.Attribute) and node.func.attr == "copy":
                    if isinstance(node.func.value, ast.Attribute):
                        val = node.func.value
                        if isinstance(val.value, ast.Name) and val.value.id == "os" and val.attr == "environ":
                            violations.append(f"{py_file.name}:{node.lineno} calls os.environ.copy() directly")

    assert not violations, f"Found unshielded os.environ copies in src/: {violations}"


@pytest.mark.unit
def test_provider_selection_explanation_and_candidate_matrix(tmp_path, monkeypatch):
    """Verify that RouterEngine captures complete evaluation matrix explaining skipped, rejected, and selected candidates."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))

    config = RouterConfig(
        profiles={
            "ag-disabled": RouterProfileConfig(profile_id="ag-disabled", provider="antigravity", enabled=False),
            "ag-unauth": RouterProfileConfig(profile_id="ag-unauth", provider="antigravity", enabled=True),
            "ag-healthy": RouterProfileConfig(profile_id="ag-healthy", provider="antigravity", enabled=True, preferred_models=["gemini-2.5-pro"]),
        },
        roles={
            "manager": RolePolicy(
                role_name="manager",
                preferred_chain=["ag-disabled", "ag-unauth", "ag-healthy"],
                max_failover_attempts=3,
            )
        }
    )

    from antigravity_provider.router.adapters.antigravity_adapter import AntigravityAdapter
    from antigravity_provider.router.exceptions import AuthExpiredError

    def mock_invoke(profile, req):
        if profile.profile_id == "ag-unauth":
            raise AuthExpiredError("Authentication expired: 401 Unauthorized", provider="antigravity", profile_id="ag-unauth")
        return {
            "id": "chatcmpl-ok",
            "choices": [{"message": {"role": "assistant", "content": "Selected candidate response"}}],
            "usage": {"total_tokens": 10},
        }

    engine = RouterEngine(config=config)

    with patch.object(AntigravityAdapter, "invoke", side_effect=mock_invoke):

        res = engine.route_request({"messages": [{"role": "user", "content": "explain"}]}, role="manager")

        assert "router_metadata" in res
        meta = res["router_metadata"]
        assert meta["profile_id"] == "ag-healthy"

        trace = meta.get("selection_trace")
        assert trace is not None
        assert "evaluation_matrix" in trace

        matrix = trace["evaluation_matrix"]
        assert len(matrix) == 3

        # Check candidate 1: ag-disabled
        assert matrix[0]["profile_id"] == "ag-disabled"
        assert matrix[0]["status"] == "skipped"
        assert "disabled" in matrix[0]["reason"].lower()

        # Check candidate 2: ag-unauth (failed during execution due to auth expired)
        assert matrix[1]["profile_id"] == "ag-unauth"
        assert matrix[1]["status"] == "failed"
        assert "auth" in matrix[1]["reason"].lower() or "401" in matrix[1]["reason"]

        # Check candidate 3: ag-healthy (selected after failover)
        assert matrix[2]["profile_id"] == "ag-healthy"
        assert matrix[2]["status"] == "selected"
        assert matrix[2]["provider"] == "antigravity"


@pytest.mark.unit
def test_failover_exhaustion_includes_selection_trace(tmp_path, monkeypatch):
    """Verify that when all candidates fail, the error response carries selection_trace with failure reasons."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))

    config = RouterConfig(
        profiles={
            "ag-w1": RouterProfileConfig(profile_id="ag-w1", provider="antigravity", enabled=True, preferred_models=["gemini-2.5-pro"]),
        },
        roles={
            "manager": RolePolicy(
                role_name="manager",
                preferred_chain=["ag-w1"],
                max_failover_attempts=1,
            )
        }
    )

    from antigravity_provider.router.adapters.antigravity_adapter import AntigravityAdapter
    from antigravity_provider.router.profile_manager import ProfileAuthManager

    def mock_invoke_fail(profile, req):
        raise RuntimeError("Quota 429: resource exhausted")

    engine = RouterEngine(config=config)

    with patch.object(ProfileAuthManager, "get_profile_status", return_value={"authenticated": True, "auth_state": "AUTHENTICATED"}), \
         patch.object(AntigravityAdapter, "invoke", side_effect=mock_invoke_fail):

        res = engine.route_request({"messages": [{"role": "user", "content": "hello"}]}, role="manager")

        assert res.get("router_error") is True
        assert "selection_trace" in res
        trace = res["selection_trace"]
        assert trace["selected_profile_id"] is None
        assert len(trace["evaluation_matrix"]) == 1
        assert trace["evaluation_matrix"][0]["status"] == "failed"
        assert "429" in trace["evaluation_matrix"][0]["reason"] or "quota" in trace["evaluation_matrix"][0]["reason"].lower()
