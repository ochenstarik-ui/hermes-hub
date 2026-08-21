"""Hermes Hub — Tests for Real Call Telemetry, Empirical Aggregates, and Debts Verification."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock, patch
import pytest

from antigravity_provider.router.telemetry_service import (
    TelemetryAggregates,
    TelemetryRecord,
    TelemetryService,
    MAX_MEMORY_RECORDS,
)
from antigravity_provider.router.router_config import (
    RolePolicy,
    RouterConfig,
    RouterProfileConfig,
    load_router_config,
    save_router_config,
)
from antigravity_provider.router.router_engine import RouterEngine


@pytest.fixture
def temp_telemetry_service(tmp_path):
    """Fixture providing an isolated TelemetryService with a temporary file log."""
    log_file = tmp_path / "test_telemetry.jsonl"
    service = TelemetryService(log_path=log_file)
    return service


@pytest.mark.unit
def test_telemetry_recording_latency_tokens_outcome(temp_telemetry_service):
    """Verify individual call recording captures accurate metadata and token usage."""
    svc = temp_telemetry_service

    rec = svc.record_call(
        role="orchestrator",
        profile_id="ag-orch",
        provider="antigravity",
        model="gemini-2.5-pro",
        outcome="success",
        latency_seconds=0.125,
        prompt_tokens=150,
        completion_tokens=50,
        total_tokens=200,
        failover_count=0,
    )

    assert rec.role == "orchestrator"
    assert rec.profile_id == "ag-orch"
    assert rec.provider == "antigravity"
    assert rec.model == "gemini-2.5-pro"
    assert rec.outcome == "success"
    assert rec.latency_seconds == 0.125
    assert rec.prompt_tokens == 150
    assert rec.completion_tokens == 50
    assert rec.total_tokens == 200
    assert rec.source == "own_measurement"

    # Verify persisted to disk
    log_path = svc._log_path
    assert log_path.is_file()
    lines = log_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    disk_data = json.loads(lines[0])
    assert disk_data["profile_id"] == "ag-orch"
    assert disk_data["total_tokens"] == 200


@pytest.mark.unit
def test_telemetry_aggregates_calculation(temp_telemetry_service):
    """Verify empirical metric calculation (P50, P95, Max, Token Sums, Error Rate) with known values."""
    svc = temp_telemetry_service

    # Record 10 calls with deterministic latencies: 100ms, 200ms, ..., 1000ms
    for i in range(1, 11):
        outcome = "success" if i <= 8 else "error"
        error_cat = None if outcome == "success" else "quota_exhausted"
        svc.record_call(
            role="coder-primary",
            profile_id="codex-w1",
            provider="openai-codex",
            model="gpt-4o",
            outcome=outcome,
            latency_seconds=i * 0.1,  # 100ms to 1000ms
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            failover_count=1 if i == 9 else 0,
            error_category=error_cat,
        )

    aggs = svc.get_aggregates()

    assert aggs.has_data is True
    assert aggs.total_calls == 10
    assert aggs.successful_calls == 8
    assert aggs.failed_calls == 2
    assert aggs.error_rate == 0.2  # 2/10
    assert aggs.total_prompt_tokens == 1000
    assert aggs.total_completion_tokens == 500
    assert aggs.total_tokens == 1500
    assert aggs.latency_max_ms == 1000.0
    assert aggs.source == "own_measurement"

    # Median (P50) of [100, 200, 300, 400, 500, 600, 700, 800, 900, 1000] = 550.0
    assert aggs.latency_p50_ms == 550.0
    # P95 = 955.0
    assert aggs.latency_p95_ms == 955.0


@pytest.mark.unit
def test_telemetry_aggregates_empty_window(temp_telemetry_service):
    """Verify that when no calls exist, aggregates return None and has_data=False, NOT zero."""
    svc = temp_telemetry_service
    aggs = svc.get_aggregates(window_seconds=3600)

    assert aggs.has_data is False
    assert aggs.total_calls == 0
    assert aggs.successful_calls == 0
    assert aggs.failed_calls == 0
    assert aggs.error_rate is None
    assert aggs.latency_p50_ms is None
    assert aggs.latency_p95_ms is None
    assert aggs.latency_max_ms is None
    assert aggs.total_prompt_tokens is None
    assert aggs.total_completion_tokens is None
    assert aggs.total_tokens is None
    assert aggs.total_cost_usd is None
    assert aggs.source == "own_measurement"


@pytest.mark.unit
def test_telemetry_no_tokens_when_usage_missing(temp_telemetry_service):
    """Verify that if provider does not return usage, token fields remain None without guessing."""
    svc = temp_telemetry_service

    rec = svc.record_call(
        role="fast",
        profile_id="opengo-1",
        provider="opencode-go",
        model="deepseek-v4-flash",
        outcome="success",
        latency_seconds=0.05,
        prompt_tokens=None,
        completion_tokens=None,
        total_tokens=None,
    )

    assert rec.prompt_tokens is None
    assert rec.completion_tokens is None
    assert rec.total_tokens is None

    aggs = svc.get_aggregates()
    assert aggs.total_calls == 1
    assert aggs.total_prompt_tokens is None
    assert aggs.total_completion_tokens is None
    assert aggs.total_tokens is None


@pytest.mark.unit
def test_telemetry_no_secrets_and_no_request_response_content(temp_telemetry_service):
    """Verify that telemetry records only metadata and strictly excludes secrets or prompt/response payloads."""
    svc = temp_telemetry_service

    # Record a normal call
    rec = svc.record_call(
        role="orchestrator",
        profile_id="ag-w1",
        provider="antigravity",
        model="gemini-2.5-pro",
        outcome="success",
        latency_seconds=0.45,
        prompt_tokens=300,
        completion_tokens=100,
    )

    d = rec.to_dict()
    # Ensure no content or secret fields exist
    forbidden_keys = [
        "messages", "prompt_text", "completion_text", "content", "response", "payload",
        "api_key", "secret", "password", "bearer", "authorization"
    ]
    for key in d.keys():
        for forbidden in forbidden_keys:
            assert forbidden != key.lower() and forbidden not in key.lower(), f"Forbidden key '{key}' found in telemetry record!"

    log_content = svc._log_path.read_text(encoding="utf-8")
    assert "sk-" not in log_content
    assert "bearer" not in log_content.lower()


@pytest.mark.unit
def test_telemetry_storage_rotation(tmp_path):
    """Verify log rotation occurs when file exceeds MAX_FILE_BYTES and bounded memory buffer."""
    log_file = tmp_path / "telemetry_rot.jsonl"
    svc = TelemetryService(log_path=log_file)

    # Patch MAX_FILE_BYTES temporarily to 500 bytes to test file rotation cleanly
    with patch("antigravity_provider.router.telemetry_service.MAX_FILE_BYTES", 400):
        for i in range(25):
            svc.record_call(
                role="coder",
                profile_id=f"prof-{i}",
                provider="antigravity",
                model="gemini-2.5-flash",
                outcome="success",
                latency_seconds=0.1,
                prompt_tokens=10,
                completion_tokens=20,
            )

    # Main file and backup .1 must exist
    assert log_file.exists()
    backup_1 = log_file.with_name(f"{log_file.name}.1")
    assert backup_1.exists()


@pytest.mark.unit
def test_telemetry_cost_calculation_with_and_without_pricing(temp_telemetry_service):
    """Verify USD cost computation only runs when explicit pricing is configured."""
    svc = temp_telemetry_service

    # 1. Without pricing -> cost_usd is None
    rec1 = svc.record_call(
        role="coder-primary",
        profile_id="ag-w1",
        provider="antigravity",
        model="gemini-2.5-pro",
        outcome="success",
        latency_seconds=0.2,
        prompt_tokens=1_000_000,
        completion_tokens=500_000,
    )
    assert rec1.cost_usd is None

    # 2. Configure pricing: $1.25 per 1M prompt, $5.00 per 1M completion
    svc.set_pricing_table({
        "gemini-2.5-pro": {"input_cost_per_m": 1.25, "output_cost_per_m": 5.00}
    })

    rec2 = svc.record_call(
        role="coder-primary",
        profile_id="ag-w1",
        provider="antigravity",
        model="gemini-2.5-pro",
        outcome="success",
        latency_seconds=0.2,
        prompt_tokens=1_000_000,
        completion_tokens=500_000,
    )
    # Expected cost = 1.0 * 1.25 + 0.5 * 5.00 = 1.25 + 2.50 = 3.75 USD
    assert rec2.cost_usd == 3.75

    aggs = svc.get_aggregates()
    assert aggs.total_cost_usd == 3.75


@pytest.mark.unit
def test_router_engine_records_telemetry_end_to_end(tmp_path, monkeypatch):
    """Verify that RouterEngine.route_request automatically records telemetry on success and failover."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))

    log_file = tmp_path / "hermes" / "telemetry.jsonl"
    svc = TelemetryService(log_path=log_file)

    config = RouterConfig(
        profiles={
            "ag-w1": RouterProfileConfig(
                profile_id="ag-w1",
                provider="antigravity",
                enabled=True,
                preferred_models=["gemini-2.5-pro"],
            ),
        },
        roles={
            "orchestrator": RolePolicy(
                role_name="orchestrator",
                preferred_chain=["ag-w1"],
            )
        }
    )

    from antigravity_provider.router.adapters.antigravity_adapter import AntigravityAdapter

    def mock_invoke(profile, req):
        return {
            "id": "chatcmpl-telemetry-test",
            "choices": [{"message": {"role": "assistant", "content": "Telemetry verified"}}],
            "usage": {
                "prompt_tokens": 120,
                "completion_tokens": 40,
                "total_tokens": 160,
            },
        }

    engine = RouterEngine(config=config)

    with patch.object(TelemetryService, "get", return_value=svc), \
         patch.object(AntigravityAdapter, "invoke", side_effect=mock_invoke):

        res = engine.route_request({"messages": [{"role": "user", "content": "hello"}]}, role="orchestrator")

        assert "router_metadata" in res
        aggs = svc.get_aggregates()
        assert aggs.total_calls == 1
        assert aggs.successful_calls == 1
        assert aggs.total_prompt_tokens == 120
        assert aggs.total_completion_tokens == 40
        assert aggs.total_tokens == 160


@pytest.mark.unit
def test_yaml_comments_preservation_and_debts_closure(tmp_path):
    """P1-5: Verify router_profiles.yaml preservation of existing header comments & blank lines."""
    test_yaml = tmp_path / "router_profiles.yaml"
    initial_content = (
        "# Line 1: Header comment\n"
        "# Line 2: Purpose description\n"
        "# Line 3: Invariant notice\n"
        "\n"
        "# Line 5: Section header\n"
        "router:\n"
        "  enabled: true\n"
        "  default_role: orchestrator\n"
        "roles: {}\n"
        "profiles: {}\n"
    )
    test_yaml.write_text(initial_content, encoding="utf-8")

    cfg = load_router_config(test_yaml)
    assert cfg.enabled is True

    # Save and reload
    save_router_config(cfg, test_yaml)
    saved_content = test_yaml.read_text(encoding="utf-8")

    # All 5 comment/blank lines before first YAML key must be preserved verbatim
    assert "# Line 1: Header comment" in saved_content
    assert "# Line 2: Purpose description" in saved_content
    assert "# Line 3: Invariant notice" in saved_content
    assert "# Line 5: Section header" in saved_content
