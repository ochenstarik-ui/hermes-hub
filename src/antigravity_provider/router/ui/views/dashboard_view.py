"""Snapshot-driven overview of readiness, routes and actionable account warnings."""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional

import customtkinter as ctk

from antigravity_provider.router.state_store import HubSnapshot
from antigravity_provider.router.ui.components import ActionButton, EmptyState, HubCard, HubMetricCard, SectionHeader
from antigravity_provider.router.ui.theme import Theme


class _SummaryRow(HubCard):
    def __init__(self, master: Any, title: str = "", detail: str = ""):
        super().__init__(master, corner_radius=Theme.RADIUS_SM, border_color=Theme.BORDER_SUBTLE)
        self.title = ctk.CTkLabel(self, text=title, font=Theme.font_body_bold(), text_color=Theme.TEXT_PRIMARY)
        self.title.pack(side="left", padx=Theme.CARD_PAD_X, pady=Theme.SPACE_SM)
        self.detail = ctk.CTkLabel(self, text=detail, font=Theme.font_caption(), text_color=Theme.TEXT_MUTED)
        self.detail.pack(side="right", padx=Theme.CARD_PAD_X, pady=Theme.SPACE_SM)

    def update_row(self, title: str, detail: str, status: str = "unknown") -> None:
        self.title.configure(text=title)
        self.detail.configure(text=detail)
        color = (
            Theme.COLOR_POSITIVE
            if status == "healthy"
            else (Theme.COLOR_CAUTION if status in {"warning", "quota_low", "auth_expired"} else Theme.COLOR_NEUTRAL)
        )
        self.configure(border_color=color)


class DashboardView(ctk.CTkFrame):
    def __init__(
        self,
        master: Any,
        app_state: Optional[Dict[str, Any]] = None,
        on_navigate: Optional[Callable] = None,
        on_action: Optional[Callable] = None,
        **kwargs,
    ):
        super().__init__(master=master, fg_color="transparent", **kwargs)
        self.on_navigate = on_navigate
        self.on_action = on_action
        self._provider_rows: Dict[str, _SummaryRow] = {}
        self._route_rows: Dict[str, _SummaryRow] = {}
        self._alert_rows: Dict[str, _SummaryRow] = {}
        self._build()

    def _build(self) -> None:
        SectionHeader(
            self,
            title="Обзор Hermes Hub",
            subtitle="Кто работает сейчас, через какой маршрут и где требуется внимание",
            action_text="Обновить",
            action_cmd=lambda: self.on_action and self.on_action("refresh_data", {}),
        ).pack(fill="x", padx=Theme.PAGE_PAD_X, pady=(Theme.PAGE_PAD_Y, Theme.SPACE_SM))
        self.scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.scroll.pack(fill="both", expand=True, padx=Theme.PAGE_PAD_X, pady=(0, Theme.PAGE_PAD_Y))

        self.snapshot_freshness = ctk.CTkLabel(
            self.scroll,
            text="Snapshot: Н/Д",
            font=Theme.font_caption(),
            text_color=Theme.TEXT_MUTED,
            anchor="w",
        )
        self.snapshot_freshness.pack(fill="x", pady=(0, Theme.SPACE_SM))

        metrics = ctk.CTkFrame(self.scroll, fg_color="transparent")
        metrics.pack(fill="x", pady=(0, Theme.SECTION_GAP))
        for column in range(4):
            metrics.grid_columnconfigure(column, weight=1)
        self.system_metric = HubMetricCard(metrics, "Состояние", "Н/Д", "Ожидание snapshot", icon="◈", accent=True)
        self.provider_metric = HubMetricCard(metrics, "Провайдеры", "0/0", "доступно", icon="◉")
        self.account_metric = HubMetricCard(metrics, "Аккаунты", "0/0", "подключено", icon="◎")
        self.role_metric = HubMetricCard(metrics, "Роли", "0/0", "готово", icon="◇")
        for index, metric in enumerate(
            (self.system_metric, self.provider_metric, self.account_metric, self.role_metric)
        ):
            metric.grid(row=0, column=index, padx=Theme.SPACE_XS, sticky="nsew")

        columns = ctk.CTkFrame(self.scroll, fg_color="transparent")
        columns.pack(fill="x")
        columns.grid_columnconfigure((0, 1), weight=1)
        self.providers_card = self._section(columns, "Провайдеры", 0, 0)
        self.routes_card = self._section(columns, "Активные маршруты", 0, 1)
        self.alerts_card = self._section(columns, "Требует внимания", 1, 0, columnspan=2)
        self.events_gap = EmptyState(
            self.scroll,
            title="Последние события: Н/Д",
            message="Журнал событий не входит в HubSnapshot; выдуманные события не отображаются.",
        )
        self.events_gap.pack(fill="x", pady=(Theme.SECTION_GAP, 0))

    def _section(self, master: Any, title: str, row: int, column: int, columnspan: int = 1) -> ctk.CTkFrame:
        card = HubCard(master)
        card.grid(
            row=row, column=column, columnspan=columnspan, padx=Theme.SPACE_XS, pady=Theme.SPACE_XS, sticky="nsew"
        )
        ctk.CTkLabel(card, text=title, font=Theme.font_heading(), text_color=Theme.TEXT_PRIMARY).pack(
            anchor="w", padx=Theme.CARD_PAD_X, pady=(Theme.CARD_PAD_Y, Theme.SPACE_SM)
        )
        body = ctk.CTkFrame(card, fg_color="transparent")
        body.pack(fill="x", padx=Theme.CARD_PAD_X, pady=(0, Theme.CARD_PAD_Y))
        return body

    @staticmethod
    def _sync_rows(container: Any, cache: Dict[str, _SummaryRow], rows: Dict[str, tuple[str, str, str]]) -> None:
        for key in list(cache):
            if key not in rows:
                cache.pop(key).destroy()
        for key, (title, detail, status) in rows.items():
            if key not in cache:
                cache[key] = _SummaryRow(container)
                cache[key].pack(fill="x", pady=Theme.SPACE_XS)
            cache[key].update_row(title, detail, status)

    def update_data(self, snapshot: Optional[HubSnapshot] = None) -> None:
        if not isinstance(snapshot, HubSnapshot):
            return
        if snapshot.is_stale:
            self.snapshot_freshness.configure(
                text=f"⚠ Snapshot #{snapshot.seq}: данные устарели",
                text_color=Theme.STATUS_WARNING,
            )
        else:
            self.snapshot_freshness.configure(
                text=f"Snapshot #{snapshot.seq}: актуальные данные",
                text_color=Theme.TEXT_MUTED,
            )
        readiness = snapshot.readiness
        self.system_metric.val_label.configure(text=readiness.title_ru)
        self.system_metric.sub_label.configure(text=readiness.summary_ru)
        self.provider_metric.val_label.configure(text=f"{readiness.providers_ready_count}/{readiness.total_providers}")
        self.account_metric.val_label.configure(text=f"{readiness.accounts_connected_count}/{readiness.total_accounts}")
        self.role_metric.val_label.configure(text=f"{readiness.roles_ready_count}/{readiness.total_roles}")

        provider_rows = {
            provider.provider_id: (
                provider.provider_name,
                f"{provider.online_count}/{provider.connected_count} онлайн • {provider.auth_required_count} требуют входа",
                "healthy" if provider.online_count else "warning",
            )
            for provider in snapshot.providers
        }
        self._sync_rows(self.providers_card, self._provider_rows, provider_rows)

        route_rows = {}
        for role_id, pipeline in snapshot.routing.items():
            active = next((node for node in pipeline.nodes if node.is_active), None)
            detail = f"{active.provider} • {active.model}" if active else "Активный узел: Н/Д"
            route_rows[role_id] = (pipeline.role_name_ru, detail, "healthy" if active else "warning")
        self._sync_rows(self.routes_card, self._route_rows, route_rows)

        alerts: Dict[str, tuple[str, str, str]] = {}
        for profile in snapshot.all_profiles.values():
            if profile.auth_state == "AUTH_EXPIRED":
                alerts[f"auth:{profile.profile_id}"] = (
                    profile.account_identity or profile.profile_id,
                    "Авторизация истекла",
                    "auth_expired",
                )
            quota = snapshot.quotas.get(profile.profile_id)
            if quota and not getattr(quota, "is_estimated", True):
                low = [
                    bucket
                    for bucket in quota.buckets
                    if bucket.remaining_percent is not None and bucket.remaining_percent <= 20
                ]
                if low:
                    alerts[f"quota:{profile.profile_id}"] = (
                        profile.account_identity or profile.profile_id,
                        ", ".join(f"{bucket.display_name}: {bucket.remaining_percent:.0f}%" for bucket in low),
                        "quota_low",
                    )
        for index, warning in enumerate(readiness.warnings):
            alerts[f"warning:{index}"] = ("Системное предупреждение", warning, "warning")
        if not alerts:
            alerts["none"] = ("Критичных предупреждений нет", "По данным текущего snapshot", "healthy")
        self._sync_rows(self.alerts_card, self._alert_rows, alerts)

    def _navigate(self, target: str) -> None:
        if self.on_navigate:
            self.on_navigate(target)
