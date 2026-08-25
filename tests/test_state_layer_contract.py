"""Task A regressions for sequence ordering and point updates."""
from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock

import pytest

from antigravity_provider.router.event_bus import (
    EventBus,
    EVENT_ACCOUNT_ADDED,
    EVENT_ACCOUNT_REMOVED,
    EVENT_QUOTA_UPDATED,
)
from antigravity_provider.router.profile_manager import ProfileAuthManager
from antigravity_provider.router.scheduler import HermesRefreshScheduler
from antigravity_provider.router.state_store import HubSnapshot, HubStateStore
from antigravity_provider.router.model_registry import ModelRegistry
from antigravity_provider.router.unified_health import ProfileViewModel, SystemReadiness


def _readiness() -> SystemReadiness:
    return SystemReadiness(
        state="limited",
        title_ru="Тест",
        summary_ru="",
        roles_ready_count=0,
        total_roles=0,
        accounts_connected_count=0,
        total_accounts=0,
        providers_ready_count=0,
        total_providers=0,
    )


def _profile(profile_id: str) -> ProfileViewModel:
    return ProfileViewModel(
        profile_id=profile_id,
        display_name=profile_id,
        account_identity=f"{profile_id}@example.test",
        provider="antigravity",
        provider_display_name="Antigravity",
        assigned_roles=[],
        primary_role=None,
        is_main_account=False,
        is_main_orchestrator=False,
        auth_state="AUTHENTICATED",
        health_state="healthy",
        health_label_ru="Работает",
        model_states={},
        cooldown_remaining_sec=0,
        last_checked_at=None,
        enabled=True,
        is_cold_spare=False,
        is_empty_slot=False,
    )


@pytest.mark.unit
def test_late_refresh_result_cannot_overwrite_newer_seq(monkeypatch: pytest.MonkeyPatch) -> None:
    slow_started = threading.Event()
    release_slow = threading.Event()

    class FakeHealth:
        def scan_all(self, force: bool = False):
            if threading.current_thread().name == "slow-refresh":
                slow_started.set()
                assert release_slow.wait(2)
            return {}

        def get_system_readiness(self):
            return _readiness()

        def get_agent_view_models(self):
            return []

        def get_provider_summaries(self):
            return []

        def get_routing_pipelines(self):
            return {}

    monkeypatch.setattr(
        "antigravity_provider.router.state_store.UnifiedHealthService.get",
        lambda: FakeHealth(),
    )

    store = HubStateStore()
    slow = threading.Thread(target=lambda: store.refresh(seq=1), name="slow-refresh")
    slow.start()
    assert slow_started.wait(1)
    fast_snapshot = store.refresh(seq=2)
    release_slow.set()
    slow.join(timeout=2)

    assert fast_snapshot.seq == 2
    assert store.get_snapshot().seq == 2
    assert store.get_snapshot().generation == 1
    assert store.refresh_skipped_total == 1


@pytest.mark.unit
def test_quota_delta_updates_only_target_profile_and_emits_key() -> None:
    profile_a = _profile("account-a")
    profile_b = _profile("account-b")
    store = HubStateStore()
    store._current_snapshot = HubSnapshot(
        generation=1,
        seq=1,
        timestamp=time.time(),
        profiles_by_provider={"antigravity": [profile_a, profile_b]},
        all_profiles={"account-a": profile_a, "account-b": profile_b},
        readiness=_readiness(),
        agents=[],
        providers=[],
        routing={},
        quotas={},
    )
    received = []
    bus = EventBus.get()
    bus.subscribe(EVENT_QUOTA_UPDATED, lambda _name, payload: received.append(payload))
    try:
        quota = object()
        store.apply_delta_quota_updated("antigravity", "account-a", quota)
    finally:
        bus._listeners.clear()

    snapshot = store.get_snapshot()
    assert snapshot.all_profiles["account-b"] is profile_b
    assert snapshot.all_profiles["account-a"] is not profile_a
    assert snapshot.quotas["account-a"] is quota
    assert received[-1]["profile_id"] == "account-a"
    assert received[-1]["seq"] == snapshot.seq


@pytest.mark.unit
def test_single_scheduler_refresh_waits_for_quota_before_delta(monkeypatch: pytest.MonkeyPatch) -> None:
    order: list[str] = []
    quota_service = MagicMock()
    quota_service.fetch_account_quota.side_effect = lambda *_args, **_kwargs: order.append("fetch") or "quota"
    store = MagicMock()
    store.apply_delta_quota_updated.side_effect = lambda *_args: order.append("quota_delta")
    store.apply_delta_account_updated.side_effect = lambda *_args: order.append("account_delta")
    monkeypatch.setattr(
        "antigravity_provider.router.scheduler.AccountQuotaService.get",
        lambda: quota_service,
    )
    monkeypatch.setattr("antigravity_provider.router.scheduler.HubStateStore.get", lambda: store)

    done = threading.Event()
    scheduler = HermesRefreshScheduler()
    scheduler.trigger_refresh_account("antigravity", "account-a", on_complete=done.set)
    assert done.wait(2)
    assert order == ["fetch", "quota_delta", "account_delta"]


@pytest.mark.unit
def test_model_score_rejects_exhausted_pool_and_prefers_more_quota() -> None:
    registry = ModelRegistry.get()
    descriptor = registry.get_model("gemini-2.5-pro")
    requirements = registry.get_role_requirements("researcher")
    assert descriptor is not None

    ok_empty, _, reason = registry.evaluate_model_score(
        descriptor,
        requirements,
        quota_remaining_percent=0,
    )
    ok_low, score_low, _ = registry.evaluate_model_score(
        descriptor,
        requirements,
        quota_remaining_percent=10,
    )
    ok_high, score_high, _ = registry.evaluate_model_score(
        descriptor,
        requirements,
        quota_remaining_percent=90,
    )

    assert not ok_empty and reason == "Quota bucket exhausted"
    assert ok_low and ok_high
    assert score_high > score_low


@pytest.mark.unit
def test_auth_storage_emits_secret_free_targeted_lifecycle_events(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))
    bus = EventBus.get()
    bus._listeners.clear()
    received: list[tuple[str, dict]] = []
    bus.subscribe("*", lambda name, payload: received.append((name, payload)))

    ProfileAuthManager.save_profile_auth(
        "antigravity",
        "account-a",
        {"access_token": "must-not-leak", "email": "person@example.test"},
    )
    assert received[-1] == (
        EVENT_ACCOUNT_ADDED,
        {"provider": "antigravity", "profile_id": "account-a"},
    )
    assert "must-not-leak" not in repr(received)

    assert ProfileAuthManager.delete_profile_auth("antigravity", "account-a")
    assert received[-1] == (
        EVENT_ACCOUNT_REMOVED,
        {"provider": "antigravity", "profile_id": "account-a"},
    )
    bus._listeners.clear()
