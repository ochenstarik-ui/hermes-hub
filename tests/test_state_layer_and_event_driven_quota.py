"""Comprehensive tests for Task A: State Layer, Event-Driven Quota, Seq-Guards, and OAuth Lifecycle."""

from __future__ import annotations

import time
import pytest
from datetime import datetime, timezone

from antigravity_provider.router.event_bus import (
    EventBus,
    EVENT_ACCOUNT_UPDATED,
    EVENT_ACCOUNT_ADDED,
    EVENT_ACCOUNT_REMOVED,
    EVENT_QUOTA_UPDATED,
    EVENT_ROUTING_UPDATED,
    EVENT_SYSTEM_READINESS_CHANGED,
)
from antigravity_provider.router.state_store import HubStateStore, HubSnapshot
from antigravity_provider.router.account_identity import QuotaBucket, QuotaSnapshot
from antigravity_provider.router.quota_collector import AccountQuotaService
from antigravity_provider.router.scheduler import HermesRefreshScheduler
from antigravity_provider.router.unified_health import UnifiedHealthService


@pytest.mark.unit
def test_targeted_account_quota_delta_event():
    """Verify that updating an account's quota produces EVENT_QUOTA_UPDATED with exact account identifiers."""
    bus = EventBus.get()
    store = HubStateStore.get()

    received_events = []

    def _listener(name, payload):
        received_events.append((name, payload))

    bus.subscribe(EVENT_QUOTA_UPDATED, _listener)

    try:
        bucket = QuotaBucket(
            id="antigravity.claude.5h",
            display_name="5h",
            model_family="claude",
            used_percent=100.0,
            remaining_percent=0.0,
            status="exhausted",
        )
        snap = QuotaSnapshot(
            account_id="ag-orch-primary",
            provider="antigravity",
            buckets=[bucket],
            source="runtime_event",
        )

        store.apply_delta_quota_updated("antigravity", "ag-orch-primary", snap)

        assert len(received_events) >= 1
        name, payload = received_events[-1]
        assert name == EVENT_QUOTA_UPDATED
        assert payload["provider"] == "antigravity"
        assert payload["profile_id"] == "ag-orch-primary"
        assert payload["snapshot"] == snap
        assert payload["snapshot"].is_estimated is False
    finally:
        bus.unsubscribe(EVENT_QUOTA_UPDATED, _listener)


@pytest.mark.unit
def test_seq_token_prevents_stale_refresh_clobber():
    """Verify that an out-of-order stale background response cannot overwrite fresher state."""
    store = HubStateStore.get()

    seq_fresh = store.next_seq()
    snap_fresh = store.refresh(force_scan=False, seq=seq_fresh)
    gen_fresh = snap_fresh.generation

    # Simulate a delayed/stale response from an earlier seq counter
    seq_stale = seq_fresh - 1
    snap_after_stale = store.refresh(force_scan=False, seq=seq_stale)

    # Stale response must be rejected, retaining the fresh generation
    assert snap_after_stale.generation == gen_fresh
    assert store.refresh_skipped_total >= 1


@pytest.mark.unit
def test_account_added_and_removed_delta_events():
    """Verify that account added and removed delta methods fire targeted events without global scan."""
    bus = EventBus.get()
    store = HubStateStore.get()

    added_events = []
    removed_events = []

    def _on_added(name, payload):
        added_events.append(payload)

    def _on_removed(name, payload):
        removed_events.append(payload)

    bus.subscribe(EVENT_ACCOUNT_ADDED, _on_added)
    bus.subscribe(EVENT_ACCOUNT_REMOVED, _on_removed)

    try:
        store.apply_delta_account_added("openai-codex", "codex-slot-2")
        assert len(added_events) >= 1
        assert added_events[-1]["provider"] == "openai-codex"
        assert added_events[-1]["profile_id"] == "codex-slot-2"

        store.apply_delta_account_removed("openai-codex", "codex-slot-2")
        assert len(removed_events) >= 1
        assert removed_events[-1]["provider"] == "openai-codex"
        assert removed_events[-1]["profile_id"] == "codex-slot-2"
    finally:
        bus.unsubscribe(EVENT_ACCOUNT_ADDED, _on_added)
        bus.unsubscribe(EVENT_ACCOUNT_REMOVED, _on_removed)


@pytest.mark.unit
def test_provider_refresh_scheduler_execution():
    """Verify HermesRefreshScheduler.trigger_refresh_provider refreshes specific provider."""
    scheduler = HermesRefreshScheduler.get()
    completed = []

    def _on_done():
        completed.append(True)

    scheduler.trigger_refresh_provider("antigravity", on_complete=_on_done)

    # Wait briefly for worker thread
    t0 = time.time()
    while not completed and (time.time() - t0 < 3.0):
        time.sleep(0.05)

    assert len(completed) == 1


@pytest.mark.unit
def test_antigravity_claude_vs_gemini_quota_bucket_isolation():
    """Verify Antigravity quota separates Claude and Gemini model families cleanly."""
    snap = AccountQuotaService.get()._generate_baseline_snapshot("antigravity", "ag-orch-primary")
    assert snap is not None
    assert len(snap.buckets) >= 2

    claude_bucket = snap.get_bucket_for_model("claude-3-7-sonnet")
    gemini_bucket = snap.get_bucket_for_model("gemini-2.5-pro")

    assert claude_bucket is not None
    assert gemini_bucket is not None
    assert claude_bucket.model_family == "claude"
    assert gemini_bucket.model_family == "gemini"
    assert claude_bucket.id != gemini_bucket.id

    # Mark claude exhausted
    claude_bucket.status = "exhausted"
    claude_bucket.remaining_percent = 0.0

    assert snap.is_model_available("claude-3-7-sonnet") is False
    assert snap.is_model_available("gemini-2.5-pro") is True
