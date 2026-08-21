"""Tests for Hermes Hub Dashboard Data (Assignment A6).

Verifies:
- HubSnapshot includes structured telemetry breakdown (global, by_provider, by_role)
- Provider call_share calculation (e.g. 45% / 35% / 20%) and None on empty window
- Real host system metrics via psutil with 'host_measurement' provenance
- Active calls tracking from LeaseManager reflected in snapshot and ProfileViewModel
"""
from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from antigravity_provider.router.telemetry_service import TelemetryService
from antigravity_provider.router.host_metrics import HostMetricsService, HostMetricsSnapshot
from antigravity_provider.router.session_affinity import LeaseManager
from antigravity_provider.router.state_store import HubStateStore, HubSnapshot
from antigravity_provider.router.router_config import (
    RolePolicy,
    RouterConfig,
    RouterProfileConfig,
    save_router_config,
)


@pytest.fixture
def clean_services(tmp_path, monkeypatch):
    hermes_dir = tmp_path / "hermes"
    hermes_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HERMES_HOME", str(hermes_dir))
    monkeypatch.setattr("antigravity_provider.paths.get_router_profiles_path", lambda: hermes_dir / "router_profiles.yaml")
    monkeypatch.setattr("antigravity_provider.paths.get_router_state_path", lambda: hermes_dir / "router_state.json")

    log_file = hermes_dir / "telemetry.jsonl"
    ts = TelemetryService(log_path=log_file)
    lm = LeaseManager()

    # Reset singletons
    old_store = HubStateStore._instance
    HubStateStore._instance = None
    import antigravity_provider.router.router_engine as re_mod
    old_engine = re_mod._ROUTER_ENGINE
    re_mod._ROUTER_ENGINE = None

    with patch.object(TelemetryService, "get", return_value=ts), \
         patch.object(LeaseManager, "get", return_value=lm):
        yield ts, lm

    HubStateStore._instance = old_store
    re_mod._ROUTER_ENGINE = old_engine


@pytest.mark.unit
def test_provider_call_share_calculation(clean_services):
    """P0-2: Verify call_share correctly calculates 45% / 35% / 20% distribution and None on empty."""
    ts, _ = clean_services

    # 1. Empty window -> call_share is None
    aggs_empty = ts.get_aggregates(provider="antigravity")
    assert aggs_empty.call_share is None
    assert aggs_empty.has_data is False

    # 2. Record 45 antigravity calls, 35 codex calls, 20 opencode calls (Total 100)
    for _ in range(45):
        ts.record_call(
            role="orchestrator",
            profile_id="ag-orch",
            provider="antigravity",
            model="gemini-2.5-pro",
            outcome="success",
            latency_seconds=0.15,
            prompt_tokens=100,
            completion_tokens=50,
        )

    for _ in range(35):
        ts.record_call(
            role="coder-primary",
            profile_id="codex-w1",
            provider="openai-codex",
            model="gpt-4o",
            outcome="success",
            latency_seconds=0.25,
            prompt_tokens=200,
            completion_tokens=80,
        )

    for _ in range(20):
        ts.record_call(
            role="fast",
            profile_id="opengo-1",
            provider="opencode-go",
            model="deepseek-v4-flash",
            outcome="success",
            latency_seconds=0.08,
            prompt_tokens=50,
            completion_tokens=30,
        )

    # Verify per-provider call_share
    aggs_ag = ts.get_aggregates(provider="antigravity")
    assert aggs_ag.total_calls == 45
    assert aggs_ag.call_share == 0.45

    aggs_codex = ts.get_aggregates(provider="openai-codex")
    assert aggs_codex.total_calls == 35
    assert aggs_codex.call_share == 0.35

    aggs_opengo = ts.get_aggregates(provider="opencode-go")
    assert aggs_opengo.total_calls == 20
    assert aggs_opengo.call_share == 0.20

    # Test breakdown structure
    breakdown = ts.get_breakdown()
    assert breakdown["global"]["total_calls"] == 100
    assert breakdown["by_provider"]["antigravity"]["call_share"] == 0.45
    assert breakdown["by_provider"]["openai-codex"]["call_share"] == 0.35
    assert breakdown["by_provider"]["opencode-go"]["call_share"] == 0.20
    assert breakdown["by_role"]["orchestrator"]["total_calls"] == 45
    assert breakdown["by_role"]["coder-primary"]["total_calls"] == 35
    assert breakdown["by_role"]["fast"]["total_calls"] == 20


@pytest.mark.unit
def test_host_metrics_service_psutil():
    """P1-3: Verify HostMetricsService measures system host resources with 'host_measurement' provenance."""
    snap = HostMetricsService.collect()

    assert snap.source == "host_measurement"
    if snap.has_data:
        assert snap.cpu_percent is not None
        assert 0.0 <= snap.cpu_percent <= 100.0
        assert snap.memory_percent is not None
        assert 0.0 <= snap.memory_percent <= 100.0
        assert snap.disk_percent is not None
        assert 0.0 <= snap.disk_percent <= 100.0
        assert snap.memory_used_mb is not None
        assert snap.memory_total_mb is not None

    # Test failure fallback when psutil errors
    with patch("psutil.cpu_percent", side_effect=RuntimeError("psutil error")):
        fail_snap = HostMetricsService.collect()
        assert fail_snap.has_data is False
        assert fail_snap.cpu_percent is None
        assert fail_snap.memory_percent is None
        assert fail_snap.source == "host_measurement"


@pytest.mark.unit
def test_active_calls_and_hub_snapshot_integration(clean_services, tmp_path, monkeypatch):
    """P0-1 & P1-4: Verify HubSnapshot exposes telemetry breakdown, host metrics, and active leases."""
    ts, lm = clean_services

    # Record 1 call
    ts.record_call(
        role="orchestrator",
        profile_id="ag-w1",
        provider="antigravity",
        model="gemini-2.5-pro",
        outcome="success",
        latency_seconds=0.22,
        prompt_tokens=150,
        completion_tokens=50,
    )

    # Acquire an active lease on ag-w1
    assert lm.acquire("ag-w1", max_concurrency=2) is True
    assert lm.total_active_count() == 1
    assert lm.active_count("ag-w1") == 1

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
    save_router_config(config)

    store = HubStateStore.get()
    snapshot = store.refresh(force_scan=True)

    assert "telemetry" in snapshot.metrics
    t_data = snapshot.metrics["telemetry"]
    assert "global" in t_data
    assert "by_provider" in t_data
    assert "by_role" in t_data
    assert t_data["global"]["total_calls"] == 1
    assert t_data["global"]["latency_p50_ms"] == 220.0

    assert "host" in snapshot.metrics
    assert snapshot.metrics["host"]["source"] == "host_measurement"

    assert "active_calls_total" in snapshot.metrics
    assert snapshot.metrics["active_calls_total"] == 1
    assert snapshot.metrics["active_calls_by_profile"].get("ag-w1") == 1

    # Check ProfileViewModel active_leases
    prof = snapshot.get_profile("ag-w1")
    if prof:
        assert prof.active_leases == 1

    # Release lease and verify count drops to 0
    lm.release("ag-w1")
    assert lm.total_active_count() == 0
