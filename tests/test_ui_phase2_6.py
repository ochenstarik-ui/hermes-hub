"""Acceptance coverage for the phase 2–6 snapshot-driven UI."""

from __future__ import annotations

import time
from dataclasses import replace
from pathlib import Path

import pytest

pytest.importorskip("customtkinter")

import customtkinter as ctk

from antigravity_provider.router.account_identity import QuotaBucket, QuotaSnapshot
from antigravity_provider.router.state_store import HubSnapshot
from antigravity_provider.router.ui.components import AccountCardWidget
from antigravity_provider.router.ui.views.accounts_view import AccountsView
from antigravity_provider.router.ui.views.dashboard_view import DashboardView
from antigravity_provider.router.ui.views.routing_view import RoutingView
from antigravity_provider.router.ui.views.team_view import TeamView
from antigravity_provider.router.unified_health import ProfileViewModel, SystemReadiness


@pytest.fixture(scope="module")
def ui_root():
    root = ctk.CTk()
    root.withdraw()
    yield root
    root.destroy()


def _profile(index: int) -> ProfileViewModel:
    return ProfileViewModel(
        profile_id=f"account-{index}",
        display_name=f"Worker {index}",
        account_identity=f"user-{index}@example.test",
        provider="antigravity",
        provider_display_name="Google Antigravity",
        assigned_roles=["coder" if index else "orchestrator"],
        primary_role="coder" if index else "orchestrator",
        is_main_account=index == 0,
        is_main_orchestrator=index == 0,
        auth_state="AUTHENTICATED",
        health_state="healthy",
        health_label_ru="Работает",
        model_states={},
        cooldown_remaining_sec=0,
        last_checked_at="12:00:00",
        enabled=True,
        is_cold_spare=False,
        is_empty_slot=False,
        email=f"mail-{index}@example.test",
        plan="PRO",
        plan_code="PRO",
        preferred_models=["gemini-2.5-pro"],
    )


def _quota(profile_id: str, remaining: float | None = None) -> QuotaSnapshot:
    return QuotaSnapshot(
        account_id=profile_id,
        provider="antigravity",
        buckets=[
            QuotaBucket(
                id="antigravity.gemini.5h",
                display_name="Gemini 5h",
                model_family="gemini",
                remaining_percent=remaining,
                period="5h",
            )
        ],
        source="baseline",
    )


def _snapshot(count: int = 50, changed_remaining: float | None = None) -> HubSnapshot:
    profiles = [_profile(index) for index in range(count)]
    quotas = {
        profile.profile_id: _quota(
            profile.profile_id,
            changed_remaining if profile.profile_id == "account-0" else None,
        )
        for profile in profiles
    }
    return HubSnapshot(
        generation=1 if changed_remaining is None else 2,
        seq=1 if changed_remaining is None else 2,
        timestamp=time.time(),
        profiles_by_provider={"antigravity": profiles},
        all_profiles={profile.profile_id: profile for profile in profiles},
        readiness=SystemReadiness(
            state="healthy",
            title_ru="Система готова",
            summary_ru="Все назначенные роли доступны",
            roles_ready_count=6,
            total_roles=6,
            accounts_connected_count=count,
            total_accounts=count,
            providers_ready_count=1,
            total_providers=1,
        ),
        agents=[],
        providers=[],
        routing={},
        quotas=quotas,
    )


@pytest.mark.unit
def test_identity_priority_and_plan_badge_suppression() -> None:
    profile = _profile(1)
    assert AccountCardWidget.resolve_identity(profile) == profile.email
    assert "PlanBadge" not in Path("src/antigravity_provider/router/ui/views/accounts_view.py").read_text(
        encoding="utf-8"
    )


@pytest.mark.ui
def test_fifty_accounts_update_one_quota_without_rebuilding_other_cards(ui_root) -> None:
    view = AccountsView(ui_root)
    try:
        view.pack(fill="both", expand=True)
        view.update_data(_snapshot())
        ui_root.update_idletasks()
        before = view.render_stats()
        card_ids = {key: id(card) for key, card in view._cards.items()}
        assert all(card.compact for card in view._cards.values())

        view.update_data(_snapshot(changed_remaining=42.0))
        ui_root.update_idletasks()
        after = view.render_stats()

        assert len(view._cards) == 50
        assert before["cards_created"] == after["cards_created"] == 50
        assert before["cards_destroyed"] == after["cards_destroyed"] == 0
        assert before["quota_widgets_created"] == after["quota_widgets_created"] == 50
        assert before["quota_widgets_destroyed"] == after["quota_widgets_destroyed"] == 0
        assert {key: id(card) for key, card in view._cards.items()} == card_ids
        bucket = view._cards["account-0"]._quota_widgets["antigravity.gemini.5h"]
        assert "оценка" in bucket.title.cget("text")
    finally:
        view.destroy()


@pytest.mark.ui
def test_removing_account_destroys_only_its_card_and_views_accept_snapshot(ui_root) -> None:
    children = []
    try:
        view = AccountsView(ui_root)
        children.append(view)
        first = _snapshot(3)
        view.update_data(first)
        retained = id(view._cards["account-1"])
        profiles = first.profiles_by_provider["antigravity"][1:]
        second = replace(
            first,
            generation=2,
            all_profiles={profile.profile_id: profile for profile in profiles},
            profiles_by_provider={"antigravity": profiles},
            quotas={key: value for key, value in first.quotas.items() if key != "account-0"},
        )
        view.update_data(second)
        assert "account-0" not in view._cards
        assert id(view._cards["account-1"]) == retained
        assert view.render_stats()["cards_destroyed"] == 1

        for child in (DashboardView(ui_root), TeamView(ui_root), RoutingView(ui_root)):
            children.append(child)
            child.update_data(second)
        ui_root.update_idletasks()
    finally:
        for child in children:
            child.destroy()


@pytest.mark.unit
def test_data_views_do_not_call_backend_services() -> None:
    view_dir = Path("src/antigravity_provider/router/ui/views")
    forbidden = ("HubStateStore", "scan_all(", "AccountQuotaService", "HermesRefreshScheduler", "EventLogService")
    for name in (
        "accounts_view.py",
        "dashboard_view.py",
        "team_view.py",
        "routing_view.py",
        "providers_view.py",
        "health_view.py",
        "logs_view.py",
    ):
        source = (view_dir / name).read_text(encoding="utf-8")
        assert not any(token in source for token in forbidden), f"{name} accesses backend directly"
