"""Acceptance coverage for UI state contract v1.1 fields."""

from __future__ import annotations

from dataclasses import replace
import time

import pytest

pytest.importorskip("customtkinter")

import customtkinter as ctk

from antigravity_provider.router.account_identity import QuotaBucket, QuotaSnapshot
from antigravity_provider.router.state_store import HubSnapshot
from antigravity_provider.router.ui.components import AccountCardWidget, QuotaBucketWidget
from antigravity_provider.router.ui.theme import Theme
from antigravity_provider.router.ui.views.dashboard_view import DashboardView
from antigravity_provider.router.ui.views.routing_view import RoutingRoleWidget
from antigravity_provider.router.ui.views.team_view import AgentCardWidget
from antigravity_provider.router.unified_health import (
    AgentViewModel,
    PipelineNode,
    ProfileViewModel,
    ProviderSummary,
    RolePipeline,
    SystemReadiness,
)


@pytest.fixture(scope="module")
def ui_root(tk_root):
    root = ctk.CTkToplevel(tk_root)
    root.withdraw()
    yield root
    root.destroy()


def _profile(plan_code: str = "PRO", plan_source: str = "provider_api") -> ProfileViewModel:
    return ProfileViewModel(
        profile_id="account-1",
        display_name="Primary",
        account_identity="user@example.test",
        provider="antigravity",
        provider_display_name="Google Antigravity",
        assigned_roles=["coder-primary"],
        primary_role="coder-primary",
        is_main_account=True,
        is_main_orchestrator=False,
        auth_state="AUTHENTICATED",
        health_state="healthy",
        health_label_ru="Работает",
        model_states={},
        cooldown_remaining_sec=0,
        last_checked_at="12:00:00",
        enabled=True,
        is_cold_spare=False,
        is_empty_slot=False,
        plan_code=plan_code,
        plan_source=plan_source,
    )


def _readiness() -> SystemReadiness:
    return SystemReadiness(
        state="healthy",
        title_ru="Система готова",
        summary_ru="Все роли доступны",
        roles_ready_count=1,
        total_roles=1,
        accounts_connected_count=1,
        total_accounts=1,
        providers_ready_count=1,
        total_providers=1,
    )


@pytest.mark.ui
def test_plan_badge_distinguishes_trusted_inferred_and_unknown(ui_root) -> None:
    card = AccountCardWidget(ui_root, "account-1", "user@example.test", "Antigravity")
    try:
        card.pack()
        card.update_account(_profile("PRO", "provider_api"))
        ui_root.update_idletasks()
        assert card.plan_badge.label.cget("text") == "Тариф PRO"
        assert card.plan_badge.winfo_manager() == "pack"

        card.update_account(_profile("PRO", "inferred"))
        ui_root.update_idletasks()
        assert card.plan_badge.label.cget("text") == "Тариф PRO • выведено"
        assert card.plan_badge.label.cget("text_color") == Theme.TEXT_MUTED

        card.update_account(_profile("UNKNOWN", "unknown"))
        ui_root.update_idletasks()
        assert card.plan_badge.winfo_manager() == ""
    finally:
        card.destroy()


@pytest.mark.ui
def test_live_quota_overrides_stale_exhausted_card_status(ui_root) -> None:
    card = AccountCardWidget(ui_root, "account-1", "user@example.test", "Antigravity")
    profile = replace(_profile(), health_state="quota_exhausted", health_label_ru="Квота исчерпана")
    snapshot = QuotaSnapshot(
        account_id="account-1",
        provider="antigravity",
        source="provider_api",
        buckets=[
            QuotaBucket(id="claude", display_name="Claude", remaining_percent=100.0),
            QuotaBucket(id="gemini", display_name="Gemini", remaining_percent=100.0),
        ],
    )
    try:
        card.pack()
        card.update_account(profile, snapshot)
        ui_root.update_idletasks()
        assert card.status.label.cget("text") == "Работает"
        assert card.status.dot.cget("text_color") == Theme.STATUS_HEALTHY
    finally:
        card.destroy()


@pytest.mark.ui
def test_quota_missing_is_not_rendered_as_zero_and_reason_is_visible(ui_root) -> None:
    widget = QuotaBucketWidget(ui_root, "bucket", "Claude 5h")
    try:
        widget.pack()
        widget.update_bucket("Claude 5h", None, unavailable_reason="Провайдер не вернул лимит")
        ui_root.update_idletasks()
        assert widget.bar.detail.cget("text") == "Н/Д"
        assert widget.bar.progress.cget("progress_color") == Theme.COLOR_NEUTRAL
        assert "Провайдер не вернул лимит" in widget.unavailable_reason.cget("text")

        widget.update_bucket("Claude 5h", 0.0)
        ui_root.update_idletasks()
        assert widget.bar.detail.cget("text") == "0%"
        assert widget.bar.progress.cget("progress_color") == Theme.COLOR_NEGATIVE
        assert widget.unavailable_reason.winfo_manager() == ""
    finally:
        widget.destroy()


@pytest.mark.ui
def test_agent_quota_and_failover_reason_are_bound_to_their_models(ui_root) -> None:
    agent = AgentViewModel(
        role_id="coder-primary",
        role_name_ru="Кодер 1",
        role_description_ru="Основной кодер",
        assigned_profile_id="account-2",
        assigned_display_name="Reserve",
        provider="codex",
        provider_display_name="OpenAI Codex",
        model="gpt-5",
        account_identity="reserve@example.test",
        routing_position="Fallback 1",
        status="healthy",
        status_label_ru="Работает",
        is_active=True,
        is_main_orchestrator=False,
        session_id="session-42",
        active_quota_status="warning",
        active_quota_label="Осталось 12%",
    )
    team_card = AgentCardWidget(ui_root)
    pipeline = RolePipeline(
        role_id="coder-primary",
        role_name_ru="Кодер 1",
        default_model="gpt-5",
        max_failover=2,
        session_affinity=True,
        active_profile_id="account-2",
        nodes=[
            PipelineNode(
                profile_id="account-1",
                display_name="Primary",
                provider="Google Antigravity",
                model="gemini-2.5-pro",
                status="quota_exhausted",
                status_label_ru="Исчерпан",
                is_active=False,
                account_identity="primary@example.test",
                quota_status="exhausted",
                failover_reason="Исчерпана квота (429)",
            ),
            PipelineNode(
                profile_id="account-2",
                display_name="Reserve",
                provider="OpenAI Codex",
                model="gpt-5",
                status="healthy",
                status_label_ru="Работает",
                is_active=True,
                account_identity="reserve@example.test",
                quota_status="warning",
            ),
        ],
    )
    route = RoutingRoleWidget(ui_root, pipeline)
    try:
        team_card.pack()
        route.pack()
        team_card.update_agent(agent)
        route.update_from_pipeline(pipeline)
        ui_root.update_idletasks()
        assert "Осталось 12%" in team_card.quota_lbl.cget("text")
        assert "session-42" in team_card.quota_lbl.cget("text")
        assert "Исчерпана квота (429)" in route._nodes["account-1"].failover.cget("text")
        assert route._nodes["account-2"].failover.cget("text") == ""
        assert "Квота: исчерпана" == route._nodes["account-1"].quota.cget("text")
    finally:
        route.destroy()
        team_card.destroy()


def test_dashboard_agent_quota_measurement_drives_progress_percent() -> None:
    agent = AgentViewModel(
        role_id="coder-primary",
        role_name_ru="Кодер 1",
        role_description_ru="Основной кодер",
        assigned_profile_id="ag-w1",
        assigned_display_name="Primary",
        provider="antigravity",
        provider_display_name="Google Antigravity",
        model="gemini-3.1-pro",
        account_identity="user@example.test",
        routing_position="Primary",
        status="healthy",
        status_label_ru="Работает",
        is_active=True,
        is_main_orchestrator=False,
        active_quota_status="healthy",
        active_quota_label="Осталось 73%",
    )
    snapshot = HubSnapshot(
        generation=1,
        seq=1,
        timestamp=time.time(),
        profiles_by_provider={},
        all_profiles={},
        readiness=_readiness(),
        agents=[agent],
        providers=[],
        routing={},
        quotas={
            "ag-w1": QuotaSnapshot(
                account_id="ag-w1",
                provider="antigravity",
                source="provider_api",
                buckets=[
                    QuotaBucket(
                        id="antigravity.gemini.7d",
                        display_name="Gemini • неделя",
                        model_family="gemini",
                        remaining_percent=73.0,
                    )
                ],
            )
        },
    )

    label, percent = DashboardView._agent_quota_measurement(snapshot, agent)

    assert label == "Осталось 73%"
    assert percent == 73.0


@pytest.mark.ui
def test_stale_snapshot_is_visibly_marked_with_sequence(ui_root) -> None:
    snapshot = HubSnapshot(
        generation=7,
        seq=11,
        timestamp=time.time() - 301,
        profiles_by_provider={},
        all_profiles={},
        readiness=_readiness(),
        agents=[],
        providers=[],
        routing={},
        quotas={},
        is_stale=True,
    )
    view = DashboardView(ui_root)
    try:
        view.pack()
        view.update_data(snapshot)
        ui_root.update_idletasks()
        label = view.snapshot_freshness.cget("text")
        assert "#11" in label
        assert "устарели" in label
        assert view.snapshot_freshness.cget("text_color") == Theme.STATUS_WARNING
    finally:
        view.destroy()


@pytest.mark.ui
def test_dashboard_makes_all_connected_accounts_visible_in_provider_summary(ui_root) -> None:
    profiles = [
        replace(
            _profile(),
            profile_id=f"ag-{index}",
            account_identity=f"user{index}@example.test",
            email=f"user{index}@example.test",
        )
        for index in range(6)
    ]
    readiness = replace(_readiness(), accounts_connected_count=6, total_accounts=6)
    provider = ProviderSummary(
        provider_id="antigravity",
        provider_name="Google Antigravity",
        total_slots=10,
        connected_count=6,
        online_count=6,
        auth_required_count=0,
        quota_exhausted_count=0,
        cold_spare_count=0,
        discovered_models=["gemini-3.7-flash"],
        last_refresh_at="12:00:00",
    )
    snapshot = HubSnapshot(
        generation=1,
        seq=1,
        timestamp=time.time(),
        profiles_by_provider={"antigravity": profiles},
        all_profiles={profile.profile_id: profile for profile in profiles},
        readiness=readiness,
        agents=[],
        providers=[provider],
        routing={},
        quotas={},
    )
    view = DashboardView(ui_root)
    try:
        view.pack()
        view.update_data(snapshot)
        ui_root.update_idletasks()
        assert view.agents_metric.val_label.cget("text") == "6"
        assert "6 аккаунт" in view._provider_cards["antigravity"].subtitle.cget("text")
        assert not hasattr(view, "realtime")
        assert view.route_diagram.provider_slots[0].winfo_manager() == "place"
    finally:
        view.destroy()


@pytest.mark.unit
def test_snapshot_unavailable_reason_can_flow_to_account_bucket() -> None:
    snapshot = QuotaSnapshot(
        account_id="account-1",
        provider="antigravity",
        buckets=[QuotaBucket(id="b", display_name="Gemini 5h")],
        unavailable_reason="Авторизация недоступна",
    )
    assert snapshot.buckets[0].remaining_percent is None
    assert snapshot.unavailable_reason == "Авторизация недоступна"


@pytest.mark.ui
def test_dashboard_renders_all_five_providers_in_order(ui_root) -> None:
    provider_ids = ["antigravity", "openai-codex", "opencode-go", "claude", "grok"]
    providers = [
        ProviderSummary(
            provider_id=pid,
            provider_name=pid.upper(),
            total_slots=2,
            connected_count=1,
            online_count=1,
            auth_required_count=0,
            quota_exhausted_count=0,
            cold_spare_count=0,
            discovered_models=["model-1"],
            last_refresh_at="12:00:00",
        )
        for pid in provider_ids
    ]
    snapshot = HubSnapshot(
        generation=1,
        seq=1,
        timestamp=time.time(),
        profiles_by_provider={},
        all_profiles={},
        readiness=_readiness(),
        agents=[],
        providers=providers,
        routing={},
        quotas={},
    )
    view = DashboardView(ui_root)
    try:
        view.pack()
        view.update_data(snapshot)
        ui_root.update_idletasks()
        assert len(view._provider_cards) == 5
        assert set(view._provider_cards.keys()) == set(provider_ids)
        for slot in view.route_diagram.provider_slots[:5]:
            assert slot.winfo_manager() == "place"
    finally:
        view.destroy()
