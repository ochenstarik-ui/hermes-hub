"""Tests for Hermes Hub Dashboard Data (Assignment A6 & A7).

Verifies:
- HubSnapshot includes structured telemetry breakdown (global, by_provider, by_role)
- Provider call_share calculation (e.g. 45% / 35% / 20%) and None on empty window
- Real host system metrics via psutil with CPU warm-up and live network throughput (Mbps)
- Active calls tracking from RouterEngine.leases reflected in snapshot and ProfileViewModel
"""
from __future__ import annotations

import collections
import time
from unittest.mock import MagicMock, patch
import pytest

from antigravity_provider.router.telemetry_service import TelemetryService
from antigravity_provider.router.host_metrics import HostMetricsService
from antigravity_provider.router.session_affinity import LeaseManager
from antigravity_provider.router.router_engine import get_router_engine
from antigravity_provider.router.state_store import HubStateStore
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

    HostMetricsService.reset_state()

    with patch.object(TelemetryService, "get", return_value=ts), \
         patch.object(LeaseManager, "get", return_value=lm):
        yield ts, lm

    HubStateStore._instance = old_store
    re_mod._ROUTER_ENGINE = old_engine
    HostMetricsService.reset_state()


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
            role="manager",
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
            role="developer-1",
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
            role="tester",
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
    assert breakdown["by_role"]["manager"]["total_calls"] == 45
    assert breakdown["by_role"]["developer-1"]["total_calls"] == 35
    assert breakdown["by_role"]["tester"]["total_calls"] == 20


@pytest.mark.unit
def test_host_metrics_service_psutil():
    """P1-3 & P0-2: Verify HostMetricsService measures system host resources with CPU warm-up."""
    HostMetricsService.reset_state()
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
def test_host_metrics_cpu_warmup_avoids_cold_zero():
    """P0-2: Verify initial CPU collection uses interval warm-up to avoid cold start 0.0%."""
    HostMetricsService.reset_state()

    # Mock psutil to verify that interval=0.05 is passed on cold start
    with patch("psutil.cpu_percent", return_value=14.5) as mock_cpu:
        snap = HostMetricsService.collect()
        mock_cpu.assert_called_once_with(interval=0.05)
        assert snap.cpu_percent == 14.5

    # Second call should use interval=None
    with patch("psutil.cpu_percent", return_value=22.0) as mock_cpu_2:
        snap2 = HostMetricsService.collect()
        mock_cpu_2.assert_called_once_with(interval=None)
        assert snap2.cpu_percent == 22.0


@pytest.mark.unit
def test_host_metrics_network_live_speed():
    """P1-4: Verify live network throughput calculation (Mbps) between samples."""
    HostMetricsService.reset_state()
    NetCounters = collections.namedtuple("NetCounters", ["bytes_sent", "bytes_recv"])

    # First sample: 10,000,000 sent, 20,000,000 recv
    with patch("psutil.net_io_counters", return_value=NetCounters(10_000_000, 20_000_000)):
        snap1 = HostMetricsService.collect()
        assert snap1.net_bytes_sent == 10_000_000
        assert snap1.net_bytes_recv == 20_000_000
        assert snap1.net_speed_mbps is None  # Initial baseline

    time.sleep(0.1)

    # Second sample: +1,250,000 bytes sent (10 Mbits) and +1,250,000 bytes recv (10 Mbits)
    # Total 20 Mbits in ~0.1s -> ~200 Mbps
    with patch("psutil.net_io_counters", return_value=NetCounters(11_250_000, 21_250_000)):
        snap2 = HostMetricsService.collect()
        assert snap2.net_bytes_sent == 11_250_000
        assert snap2.net_bytes_recv == 21_250_000
        assert snap2.net_speed_mbps is not None
        assert snap2.net_speed_mbps > 0.0


@pytest.mark.unit
def test_active_calls_and_hub_snapshot_integration(clean_services, tmp_path, monkeypatch):
    """P0-1: Verify HubSnapshot exposes active leases acquired via router engine path."""
    ts, _ = clean_services

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
            "manager": RolePolicy(
                role_name="manager",
                preferred_chain=["ag-w1"],
            )
        }
    )
    save_router_config(config)

    # Acquire lease directly on the router engine's lease manager
    engine = get_router_engine()
    assert engine.leases.acquire("ag-w1", max_concurrency=2) is True
    assert engine.leases.total_active_count() == 1
    assert engine.leases.active_count("ag-w1") == 1

    # Record 1 call
    ts.record_call(
        role="manager",
        profile_id="ag-w1",
        provider="antigravity",
        model="gemini-2.5-pro",
        outcome="success",
        latency_seconds=0.22,
        prompt_tokens=150,
        completion_tokens=50,
    )

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

    # Verify active calls in snapshot matches engine leases
    assert "active_calls_total" in snapshot.metrics
    assert snapshot.metrics["active_calls_total"] == 1
    assert snapshot.metrics["active_calls_by_profile"].get("ag-w1") == 1

    # Check ProfileViewModel active_leases
    prof = snapshot.get_profile("ag-w1")
    if prof:
        assert prof.active_leases == 1

    # Check HealthTracker ProfileHealthRecord.active_leases
    prec = engine.health.get_or_create("ag-w1")
    assert prec.active_leases == 1

    # Release lease and verify count drops to 0
    engine.leases.release("ag-w1")
    assert engine.leases.total_active_count() == 0
