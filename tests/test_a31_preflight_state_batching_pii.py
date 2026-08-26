"""Tests for Task A31: Preflight Dependency Agent, Workflow Run State, Local Concurrency & Context Window, PII Masking, and Cost Controller Honesty.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from antigravity_provider import paths
from antigravity_provider.router.action_handler import ActionExecutor
from antigravity_provider.router.adapters.local_adapter import LocalLLMAdapter
from antigravity_provider.router.preflight_service import PreflightCheckService, PreflightReport
from antigravity_provider.router.role_registry import CANONICAL_ROLES, RoleRegistry
from antigravity_provider.router.router_config import (
    RouterConfig,
    RouterProfileConfig,
    get_default_router_config,
    load_router_config,
)
from antigravity_provider.router.settings_service import (
    DEFAULT_SETTINGS,
    get_hub_settings,
    invalidate_settings_cache,
    save_hub_settings,
)
from antigravity_provider.router.telemetry_service import (
    TelemetryAggregates,
    TelemetryRecord,
    TelemetryService,
    format_token_count,
)
from antigravity_provider.router.web.server import sanitize_snapshot
from antigravity_provider.router.workflow_service import (
    AgentDefinition,
    WorkflowDefinition,
    WorkflowExecutionService,
    WorkflowService,
    get_last_run_state,
    sanitize_run_data,
)


# ============================================================================
# P0-1: Preflight Dependency Agent
# ============================================================================


def test_dependency_agent_role_registered():
    """Verify 13th role 'dependency-agent' and its canonical aliases in RoleRegistry."""
    assert len(CANONICAL_ROLES) == 13
    assert "dependency-agent" in CANONICAL_ROLES

    role_def = CANONICAL_ROLES["dependency-agent"]
    assert role_def.role_id == "dependency-agent"
    assert role_def.display_name_ru == "Проверяющий готовность"
    assert role_def.short_name_ru == "Готовность"
    assert role_def.is_implemented is True
    assert "preflight" in role_def.capabilities

    # Test alias resolution
    aliases = [
        "dependency-agent",
        "dependency_agent",
        "preflight",
        "проверяющий готовность",
        "агент зависимостей",
        "готовность",
        "dependency",
    ]
    for alias in aliases:
        canonical = RoleRegistry.resolve_role_name(alias)
        assert canonical == "dependency-agent", f"Alias '{alias}' resolved to '{canonical}'"


def test_preflight_service_cli_and_environment():
    """Verify CLI tools and environment checks."""
    service = PreflightCheckService.get()

    cli_items = service.check_cli_dependencies()
    assert len(cli_items) >= 3
    ids = {item.check_id for item in cli_items}
    assert "cli_agy" in ids
    assert "pkg_fastapi" in ids
    assert "pkg_uvicorn" in ids

    env_items = service.check_system_environment()
    assert len(env_items) >= 3
    env_ids = {item.check_id for item in env_items}
    assert "env_hermes_home" in env_ids
    assert "env_config_writable" in env_ids
    assert "env_logs_writable" in env_ids


def test_preflight_service_run_all_and_action():
    """Verify run_all_checks and action execution."""
    service = PreflightCheckService.get()
    report = service.run_all_checks()

    assert isinstance(report, PreflightReport)
    assert isinstance(report.passed_count, int)
    assert isinstance(report.failed_count, int)
    assert isinstance(report.warn_count, int)
    assert len(report.checks) > 0

    report_dict = report.to_dict()
    assert "success" in report_dict
    assert "checks" in report_dict
    assert isinstance(report_dict["checks"], list)

    # Test via ActionExecutor
    action_res = ActionExecutor.execute("run_preflight", {})
    assert "ok" in action_res
    assert "message" in action_res
    assert "data" in action_res
    assert "checks" in action_res["data"]


# ============================================================================
# P0-2: Workflow Run State Manager
# ============================================================================


def test_workflow_run_state_sanitization():
    """Verify recursive secret stripping in workflow run state."""
    raw_state = {
        "run_id": "test-run-123",
        "status": "RUNNING",
        "api_key": "sk-1234567890abcdef",
        "token": "gho_secrettoken123456",
        "nested": {
            "password": "supersecretpass",
            "auth_status": "ok",
            "message": "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0",
            "extra_url": "https://example.com/callback?access_token=secret12345&foo=bar",
        },
        "step_list": [
            {"account": "acc-1", "client_secret": "my-client-secret-123"},
            {"safe_field": "public_data"},
        ],
    }

    sanitized = sanitize_run_data(raw_state)

    assert sanitized["api_key"] == "***"
    assert sanitized["token"] == "***"
    assert sanitized["nested"]["password"] == "***"
    assert sanitized["nested"]["auth_status"] == "ok"
    assert "Bearer ***" in sanitized["nested"]["message"]
    assert "access_token=***" in sanitized["nested"]["extra_url"]
    assert sanitized["step_list"][0]["client_secret"] == "***"
    assert sanitized["step_list"][1]["safe_field"] == "public_data"


def test_workflow_run_state_interrupted_on_startup(tmp_path: Path):
    """Verify that a RUNNING state in workflow_run_state.json transitions to INTERRUPTED on reload."""
    state_file = tmp_path / "workflow_state.json"
    run_state_file = tmp_path / "workflow_run_state.json"

    # Pre-populate run state with RUNNING status
    initial_run_state = {
        "run_id": "run-crash-test",
        "status": "RUNNING",
        "started_at": "2026-08-26T00:00:00Z",
        "updated_at": "2026-08-26T00:00:00Z",
        "current_step_index": 2,
        "current_agent_id": "developer-1",
        "iteration_count": 1,
        "completed_steps": [
            {"step_index": 0, "agent_id": "manager", "status": "SUCCESS"},
            {"step_index": 1, "agent_id": "developer-1", "status": "WORKING"},
        ],
        "interruption_reason": None,
    }
    run_state_file.write_text(json.dumps(initial_run_state), encoding="utf-8")

    # Initialize WorkflowService
    service = WorkflowService(state_path=state_file, run_state_path=run_state_file)

    # Check that state transitioned to INTERRUPTED
    last_state = service.get_last_run_state()
    assert last_state is not None
    assert last_state["status"] == "INTERRUPTED"
    assert last_state["interruption_reason"] == "Прогон был прерван перезапуском сервера или сбоем процесса"
    assert len(last_state["completed_steps"]) == 2

    # Verify top-level function
    assert get_last_run_state(run_state_file)["status"] == "INTERRUPTED"


def test_workflow_execution_service_alias():
    """Verify WorkflowExecutionService is an alias of WorkflowService."""
    assert WorkflowExecutionService is WorkflowService


# ============================================================================
# P0-3: Local Concurrency & Context Window
# ============================================================================


def test_local_profile_max_concurrency_is_one():
    """Verify all local provider profiles have max_concurrency = 1."""
    config = get_default_router_config()
    for pid, pcfg in config.profiles.items():
        if pcfg.provider == "local":
            assert pcfg.max_concurrency == 1, f"Local profile {pid} has max_concurrency={pcfg.max_concurrency}"

    # Verify loaded config also enforces max_concurrency = 1 for local profiles
    loaded = load_router_config()
    for pid, pcfg in loaded.profiles.items():
        if pcfg.provider == "local":
            assert pcfg.max_concurrency == 1


def test_local_adapter_get_context_window():
    """Verify LocalLLMAdapter retrieves context window accurately without hallucinating defaults."""
    adapter = LocalLLMAdapter()

    # Profile with explicit context_window in auth_config
    prof_with_cfg = RouterProfileConfig(
        profile_id="local-test-1",
        provider="local",
        account_id="acc-1",
        auth_config={"context_window": 8192},
    )
    assert adapter.get_context_window(prof_with_cfg) == 8192

    # Profile without context length and with non-responding server
    prof_empty = RouterProfileConfig(
        profile_id="local-test-2",
        provider="local",
        account_id="acc-2",
        custom_base_url="http://127.0.0.1:9999/v1",
    )
    # Must return None instead of inventing fake numbers
    assert adapter.get_context_window(prof_empty) is None


def test_local_adapter_context_truncation_guard():
    """Verify context truncation guard protects against VRAM overflow when context_window is known."""
    adapter = LocalLLMAdapter()

    prof = RouterProfileConfig(
        profile_id="local-small-ctx",
        provider="local",
        account_id="acc-1",
        auth_config={"context_window": 500},
        custom_base_url="http://127.0.0.1:12345/v1",
    )

    # Huge prompt exceeding 500 tokens
    long_middle_content = "important historical dialogue step " * 100
    messages = [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Initial prompt 1"},
        {"role": "assistant", "content": long_middle_content},
        {"role": "user", "content": "Initial prompt 2"},
        {"role": "assistant", "content": long_middle_content},
        {"role": "user", "content": "Latest user task to execute."},
    ]

    mock_resp = {
        "choices": [{"message": {"role": "assistant", "content": "Truncated prompt executed successfully."}}],
        "usage": {"prompt_tokens": 200, "completion_tokens": 10},
    }

    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_cm = MagicMock()
        mock_cm.read.return_value = json.dumps(mock_resp).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_cm

        res = adapter.invoke(prof, {"messages": messages, "max_tokens": 100})
        assert res["choices"][0]["message"]["content"] == "Truncated prompt executed successfully."

        # Verify sent payload messages were truncated
        args, kwargs = mock_urlopen.call_args
        sent_req = args[0]
        sent_body = json.loads(sent_req.data.decode("utf-8"))
        sent_messages = sent_body["messages"]

        assert sent_messages[0]["role"] == "system"
        assert sent_messages[-1]["content"] == "Latest user task to execute."
        # Total count of messages should be pruned
        assert len(sent_messages) < len(messages)


# ============================================================================
# P0-4: PII Email Masking
# ============================================================================


def test_settings_email_masking_mode():
    """Verify email_masking_mode in default settings and persistence."""
    assert DEFAULT_SETTINGS["email_masking_mode"] == "none"

    settings = get_hub_settings()
    assert settings.get("email_masking_mode") in ("none", "partial", "full")


def test_sanitize_snapshot_email_masking_modes():
    """Verify email masking behavior across 'none', 'partial', and 'full' modes."""
    snapshot_data = {
        "user_email": "vasya.pupkin@example.com",
        "account_id": "google-user-1",
        "api_key": "sk-secret123456789",
        "nested": {
            "developer": "developer.one@domain.org",
            "reviewer": "r@test.com",
        },
    }

    # 1. Mode: none (emails unchanged, secrets masked)
    san_none = sanitize_snapshot(snapshot_data, email_masking_mode="none")
    assert san_none["user_email"] == "vasya.pupkin@example.com"
    assert san_none["nested"]["developer"] == "developer.one@domain.org"
    assert san_none["nested"]["reviewer"] == "r@test.com"
    assert "api_key" not in san_none

    # 2. Mode: partial (preserves first and last char of local part + domain for differentiation)
    san_partial = sanitize_snapshot(snapshot_data, email_masking_mode="partial")
    assert san_partial["user_email"] == "v***n@example.com"
    assert san_partial["nested"]["developer"] == "d***e@domain.org"
    assert san_partial["nested"]["reviewer"] == "r***@test.com"
    assert "api_key" not in san_partial

    # 3. Mode: full (***@***.***)
    san_full = sanitize_snapshot(snapshot_data, email_masking_mode="full")
    assert san_full["user_email"] == "***@***.***"
    assert san_full["nested"]["developer"] == "***@***.***"
    assert san_full["nested"]["reviewer"] == "***@***.***"
    assert "api_key" not in san_full


# ============================================================================
# P0-5: Cost Controller Token Honesty
# ============================================================================


def test_telemetry_measured_vs_estimated_tokens(tmp_path: Path):
    """Verify telemetry distinguishes measured exact tokens from estimated tokens with ~."""
    log_file = tmp_path / "telemetry_test.jsonl"
    service = TelemetryService(log_path=log_file)

    # 1. Record measured call
    rec1 = service.record_call(
        role="developer-1",
        profile_id="ag-w1",
        provider="antigravity",
        model="claude-3-7-sonnet",
        outcome="success",
        latency_seconds=1.25,
        prompt_tokens_measured=500,
        completion_tokens_measured=150,
        is_estimated=False,
    )
    assert rec1.prompt_tokens_measured == 500
    assert rec1.prompt_tokens_estimated is None
    assert rec1.is_estimated is False
    assert rec1.total_tokens == 650

    # 2. Record estimated call
    rec2 = service.record_call(
        role="tester",
        profile_id="local-1",
        provider="local",
        model="Qwen3.8-27B-Q4_K_M.gguf",
        outcome="success",
        latency_seconds=0.85,
        prompt_tokens_estimated=300,
        completion_tokens_estimated=50,
        is_estimated=True,
    )
    assert rec2.prompt_tokens_measured is None
    assert rec2.prompt_tokens_estimated == 300
    assert rec2.is_estimated is True
    assert rec2.total_tokens == 350

    # 3. Aggregates for measured only
    agg_measured = service.get_aggregates(profile_id="ag-w1")
    assert agg_measured.total_tokens_measured == 650
    assert agg_measured.tokens_display == "650"
    assert agg_measured.has_estimated_tokens is False

    # 4. Aggregates for estimated only
    agg_est = service.get_aggregates(profile_id="local-1")
    assert agg_est.total_tokens_estimated == 350
    assert agg_est.tokens_display == "~350"
    assert agg_est.has_estimated_tokens is True


def test_format_token_count():
    """Verify format_token_count formatting helper."""
    assert format_token_count(1250, None) == "1250"
    assert format_token_count(None, 1250) == "~1250"
    assert format_token_count(1000, 250) == "1000"
    assert format_token_count(None, None) is None
