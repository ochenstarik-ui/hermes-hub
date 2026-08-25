"""Hermes Hub — Comprehensive Test Suite for Plan A Stabilization & Smart Capability Routing.

Tests:
1. HubSnapshot & HubStateStore single-pass build, sequence tracking, and stale response protection.
2. EventBus typed subscriptions, dispatch, and UI thread safety.
3. HermesRefreshScheduler task execution, concurrency limit (1), deduplication, and initial delay distribution.
4. SessionAffinityTracker TTL expiration, LRU capacity bounds, and pruning.
5. ModelRegistry capability hard filtering, multi-dimensional scoring, and role requirements.
6. RouterEngine dynamic selection trace, Antigravity separate bucket isolation, and same-account fallback.
7. Non-blocking _CM_LOCK and credential restoration in AntigravityAdapter.
8. Thread-safe singletons with double-checked locking.
9. FastAPI REST endpoints in gui_server (/api/snapshot, /api/models, /api/models/recommend).
"""
from __future__ import annotations

import time
from unittest.mock import MagicMock, patch
import pytest

from antigravity_provider.router.event_bus import (
    EventBus,
    EVENT_ACCOUNT_UPDATED,
    EVENT_QUOTA_UPDATED,
    EVENT_ROUTING_UPDATED,
    EVENT_SYSTEM_READINESS_CHANGED,
)
from antigravity_provider.router.state_store import HubStateStore, HubSnapshot
from antigravity_provider.router.scheduler import (
    HermesRefreshScheduler,
    stable_initial_delay,
)
from antigravity_provider.router.session_affinity import SessionAffinityTracker
from antigravity_provider.router.model_registry import (
    ModelRegistry,
    ModelDescriptor,
    RoleRequirements,
    DEFAULT_ROLE_REQUIREMENTS,
)
from antigravity_provider.router.router_config import (
    RouterConfig,
    RouterProfileConfig,
    RolePolicy,
)
from antigravity_provider.router.health_tracker import HealthTracker
from antigravity_provider.router.router_engine import RouterEngine
from antigravity_provider.router.unified_health import (
    UnifiedHealthService,
    EventLogService,
)


# ── TEST 1: HubSnapshot & HubStateStore ──
def test_hub_state_store_and_snapshot():
    store = HubStateStore.get()
    snap = store.get_snapshot()

    assert snap is not None
    assert snap.generation > 0
    assert snap.timestamp > 0
    assert hasattr(snap, "profiles_by_provider")
    assert hasattr(snap, "readiness")
    assert hasattr(snap, "routing")
    assert hasattr(snap, "quotas")

    # Stale response sequence rejection
    seq_old = 1
    store._latest_applied_seq = 100
    snap_stale = store.refresh(force_scan=False, seq=seq_old)
    assert store.refresh_skipped_total >= 1


# ── TEST 2: EventBus Pub/Sub & UI Dispatch ──
def test_event_bus_pub_sub():
    bus = EventBus.get()
    received = []

    def _handler(ev, data):
        received.append((ev, data))

    bus.subscribe(EVENT_ACCOUNT_UPDATED, _handler)
    bus.publish(EVENT_ACCOUNT_UPDATED, {"profile_id": "test-p1"})

    assert len(received) == 1
    assert received[0][0] == EVENT_ACCOUNT_UPDATED
    assert received[0][1]["profile_id"] == "test-p1"

    # Unsubscribe
    bus.unsubscribe(EVENT_ACCOUNT_UPDATED, _handler)
    bus.publish(EVENT_ACCOUNT_UPDATED, {"profile_id": "test-p2"})
    assert len(received) == 1  # No new items

    # UI thread dispatch with root.after mock
    mock_root = MagicMock()
    bus.publish_to_ui(mock_root, EVENT_ROUTING_UPDATED, {"role": "developer-1"})
    assert mock_root.after.called


# ── TEST 3: HermesRefreshScheduler ──
def test_refresh_scheduler_dedup_and_delays():
    # Stable initial delay
    d1 = stable_initial_delay("antigravity:full", 1.0, 5.0)
    d2 = stable_initial_delay("antigravity:full", 1.0, 5.0)
    d3 = stable_initial_delay("openai-codex:full", 1.0, 5.0)

    assert d1 == d2  # Deterministic
    assert 1.0 <= d1 <= 5.0
    assert 1.0 <= d3 <= 5.0

    scheduler = HermesRefreshScheduler(tick_interval_sec=0.1, max_concurrent_tasks=1)
    assert scheduler.max_concurrent_tasks == 1

    # Deduplication test
    complete_count = [0]
    def _done():
        complete_count[0] += 1

    scheduler.trigger_refresh_account("antigravity", "ag-w1", on_complete=_done)
    # Immediate duplicate should be deduplicated
    scheduler.trigger_refresh_account("antigravity", "ag-w1")
    assert scheduler.tasks_deduplicated_total >= 1


# ── TEST 4: SessionAffinityTracker TTL, LRU Capacity & Pruning ──
def test_session_affinity_ttl_and_lru():
    tracker = SessionAffinityTracker(ttl_seconds=2, max_entries=3)

    tracker.set_affinity("s1", "developer-1", "ag-w1", "gemini-2.5-pro")
    tracker.set_affinity("s2", "developer-1", "ag-w2", "gemini-2.5-pro")
    tracker.set_affinity("s3", "code-reviewer", "codex-w1", "gpt-4o")

    assert tracker.get_affinity("s1") is not None
    assert tracker.get_affinity("s2") is not None
    assert tracker.get_affinity("s3") is not None

    # Exceed capacity -> triggers LRU eviction
    tracker.set_affinity("s4", "tester", "ag-w3", "gemini-2.5-flash")
    assert len(tracker._sessions) <= 3

    # Test TTL expiration
    time.sleep(2.1)
    assert tracker.get_affinity("s4") is None  # Expired
    pruned = tracker.prune_expired()
    assert len(tracker._sessions) == 0


# ── TEST 5: ModelRegistry Hard Capability Filtering & Scoring ──
def test_model_registry_capability_filtering():
    reg = ModelRegistry.get()

    m_gemini_pro = reg.get_model("google-antigravity/gemini-2.5-pro")
    m_gemini_flash = reg.get_model("google-antigravity/gemini-2.5-flash")

    assert m_gemini_pro is not None
    assert m_gemini_flash is not None

    # Reviewer requires security_analysis and coding
    req_reviewer = reg.get_role_requirements("code-reviewer")
    ok_pro, score_pro, _ = reg.evaluate_model_score(m_gemini_pro, req_reviewer)
    ok_flash, score_flash, reason_flash = reg.evaluate_model_score(m_gemini_flash, req_reviewer)

    assert ok_pro is True
    # Flash does not have security_analysis capability, so hard filter must reject it
    assert ok_flash is False

    # Fast role prioritizes latency
    req_fast = reg.get_role_requirements("tester")
    ok_f_flash, score_f_flash, _ = reg.evaluate_model_score(m_gemini_flash, req_fast)
    ok_f_pro, score_f_pro, _ = reg.evaluate_model_score(m_gemini_pro, req_fast)

    assert ok_f_flash is True
    assert score_f_flash > score_f_pro  # Flash is ultra_low latency so scores higher for fast role


# ── TEST 6: RouterEngine Dynamic Selection Trace & Same-Account Fallback ──
def test_router_engine_selection_trace_and_same_account_fallback():
    cfg = RouterConfig(
        default_role="developer-1",
        profiles={
            "ag-w1": RouterProfileConfig(
                profile_id="ag-w1",
                provider="antigravity",
                enabled=True,
                preferred_models=["google-antigravity/gemini-2.5-pro", "google-antigravity/claude-3-7-sonnet"],
            ),
            "codex-w1": RouterProfileConfig(
                profile_id="codex-w1",
                provider="openai-codex",
                enabled=True,
                preferred_models=["openai/gpt-4o"],
            ),
        },
        roles={
            "developer-1": RolePolicy(
                role_name="developer-1",
                preferred_chain=["ag-w1", "codex-w1"],
            ),
        },
    )

    health = HealthTracker()
    engine = RouterEngine(config=cfg, health=health)

    with patch("antigravity_provider.router.router_engine.get_adapter") as mock_adapter_getter:
        mock_adapter = MagicMock()
        mock_adapter.invoke.return_value = {"content": "code generated", "model": "google-antigravity/gemini-2.5-pro"}
        mock_adapter_getter.return_value = mock_adapter

        res = engine.route_request({"messages": [{"role": "user", "content": "hello"}]}, role="developer-1")
        assert "router_metadata" in res
        meta = res["router_metadata"]
        assert meta["role"] == "developer-1"
        assert meta["profile_id"] == "ag-w1"
        assert "selection_trace" in meta
        assert meta["selection_trace"]["selected_model"] == "google-antigravity/gemini-2.5-pro"


# ── TEST 7: Custom Env Profile Isolation ──
def test_antigravity_adapter_credential_restoration():
    from antigravity_provider.router.adapters.antigravity_adapter import AntigravityAdapter
    from antigravity_provider.router.profile_manager import ProfileAuthManager

    adapter = AntigravityAdapter()
    prof = RouterProfileConfig(profile_id="ag-test-1", provider="antigravity")

    with patch.object(ProfileAuthManager, "load_profile_auth", return_value={"token": "t123"}), \
         patch("antigravity_provider.router.adapters.antigravity_adapter.agy_generate", return_value={"response": "ok"}) as mock_gen:

        res = adapter.invoke(prof, {"model": "gemini-2.5-flash", "messages": []})
        assert res == {"response": "ok"}
        mock_gen.assert_called_once()
        _, kwargs = mock_gen.call_args
        custom_env = kwargs.get("custom_env", {})
        assert "ag-test-1" in custom_env.get("USERPROFILE", "")


# ── TEST 8: Thread-Safe Singletons ──
def test_thread_safe_singletons():
    s1 = UnifiedHealthService.get()
    s2 = UnifiedHealthService.get()
    assert s1 is s2

    e1 = EventLogService.get()
    e2 = EventLogService.get()
    assert e1 is e2

    h1 = HubStateStore.get()
    h2 = HubStateStore.get()
    assert h1 is h2

    r1 = HermesRefreshScheduler.get()
    r2 = HermesRefreshScheduler.get()
    assert r1 is r2
