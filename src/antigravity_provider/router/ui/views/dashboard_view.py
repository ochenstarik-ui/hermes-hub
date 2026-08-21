"""Approved Hermes Hub overview layout backed only by contract data."""

from __future__ import annotations

from typing import Any, Callable, Dict, Iterable, Optional

import customtkinter as ctk

from antigravity_provider.router.state_store import HubSnapshot
from antigravity_provider.router.ui.components import HubCard
from antigravity_provider.router.ui.theme import Theme


class _FlowCard(HubCard):
    def __init__(self, master: Any, **kwargs):
        kwargs.setdefault("corner_radius", Theme.RADIUS_MD)
        kwargs.setdefault("border_color", Theme.BORDER)
        kwargs.setdefault("height", 76)
        super().__init__(master, **kwargs)
        self.pack_propagate(False)
        self.title = ctk.CTkLabel(self, text="", font=Theme.font_body_bold(), text_color=Theme.TEXT_PRIMARY)
        self.title.pack(anchor="w", padx=Theme.SPACE_SM, pady=(Theme.SPACE_SM, 0))
        self.subtitle = ctk.CTkLabel(self, text="", font=Theme.font_micro(), text_color=Theme.TEXT_MUTED)
        self.subtitle.pack(anchor="w", padx=Theme.SPACE_SM, pady=2)
        self.meta = ctk.CTkLabel(self, text="", font=Theme.font_micro(), text_color=Theme.TEXT_SECONDARY)
        self.meta.pack(anchor="w", padx=Theme.SPACE_SM, pady=(0, Theme.SPACE_SM))

    def update_card(self, title: str, subtitle: str, meta: str, status: str = "unknown") -> None:
        self.title.configure(text=title)
        self.subtitle.configure(text=subtitle)
        self.meta.configure(text=meta)
        colors = {
            "healthy": Theme.STATUS_HEALTHY,
            "warning": Theme.STATUS_WARNING,
            "error": Theme.STATUS_ERROR,
            "active": Theme.BORDER_ACCENT,
        }
        self.configure(border_color=colors.get(status, Theme.BORDER))


class _KpiCard(HubCard):
    def __init__(self, master: Any, title: str, value: str, subtext: str, icon: str):
        super().__init__(master, corner_radius=Theme.RADIUS_SM)
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=Theme.SPACE_SM, pady=(Theme.SPACE_SM, 0))
        ctk.CTkLabel(header, text=icon, font=Theme.font_micro(), text_color=Theme.TEXT_ACCENT).pack(side="left")
        ctk.CTkLabel(header, text=title.upper(), font=Theme.font_micro(), text_color=Theme.TEXT_MUTED).pack(
            side="left", padx=Theme.SPACE_XS
        )
        value_row = ctk.CTkFrame(self, fg_color="transparent")
        value_row.pack(fill="x", padx=Theme.SPACE_SM, pady=(0, Theme.SPACE_SM))
        self.val_label = ctk.CTkLabel(value_row, text=value, font=Theme.font_heading(), text_color=Theme.TEXT_PRIMARY)
        self.val_label.pack(side="left")
        self.sub_label = ctk.CTkLabel(value_row, text=subtext, font=Theme.font_micro(), text_color=Theme.TEXT_MUTED)
        self.sub_label.pack(side="right")


class _StatusRow(ctk.CTkFrame):
    def __init__(self, master: Any):
        super().__init__(master, fg_color="transparent")
        self.dot = ctk.CTkLabel(self, text="●", width=14, font=Theme.font_micro())
        self.dot.pack(side="left")
        self.title = ctk.CTkLabel(self, text="", font=Theme.font_caption(), text_color=Theme.TEXT_PRIMARY)
        self.title.pack(side="left", padx=Theme.SPACE_XS)
        self.detail = ctk.CTkLabel(self, text="", font=Theme.font_micro(), text_color=Theme.TEXT_MUTED)
        self.detail.pack(side="right")

    def update_row(self, title: str, detail: str, status: str) -> None:
        self.title.configure(text=title)
        self.detail.configure(text=detail)
        color = (
            Theme.STATUS_HEALTHY
            if status == "healthy"
            else Theme.STATUS_WARNING
            if status == "warning"
            else Theme.STATUS_ERROR
            if status == "error"
            else Theme.STATUS_DISABLED
        )
        self.dot.configure(text_color=color)


class _EventRow(ctk.CTkFrame):
    def __init__(self, master: Any):
        super().__init__(master, fg_color="transparent")
        self.time = ctk.CTkLabel(self, width=58, text="", font=Theme.font_mono_sm(), text_color=Theme.TEXT_MUTED)
        self.time.pack(side="left")
        self.dot = ctk.CTkLabel(self, width=18, text="●", font=Theme.font_micro())
        self.dot.pack(side="left")
        self.message = ctk.CTkLabel(self, text="", anchor="w", font=Theme.font_caption(), text_color=Theme.TEXT_PRIMARY)
        self.message.pack(side="left", fill="x", expand=True, padx=Theme.SPACE_XS)
        self.tag = ctk.CTkLabel(
            self,
            text="",
            font=Theme.font_micro(),
            text_color=Theme.TEXT_SECONDARY,
            fg_color=Theme.SURFACE_MUTED,
            corner_radius=Theme.RADIUS_PILL,
        )
        self.tag.pack(side="right", padx=Theme.SPACE_XS)

    def update_event(self, event: Any) -> None:
        level = str(getattr(event, "level", "info"))
        color = {
            "success": Theme.STATUS_HEALTHY,
            "warning": Theme.STATUS_WARNING,
            "error": Theme.STATUS_ERROR,
        }.get(level, Theme.STATUS_INFO)
        self.time.configure(text=str(getattr(event, "timestamp", "Н/Д")))
        self.dot.configure(text_color=color)
        self.message.configure(text=str(getattr(event, "message", "Событие без описания")))
        self.tag.configure(text=f"  {getattr(event, 'category', 'system')}  ")


class DashboardView(ctk.CTkFrame):
    """Dense overview matching the approved composition without fictional metrics."""

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
        self._provider_cards: Dict[str, _FlowCard] = {}
        self._agent_cards: Dict[str, _FlowCard] = {}
        self._provider_status_rows: Dict[str, _StatusRow] = {}
        self._event_rows: list[_EventRow] = []
        self._build()

    def _build(self) -> None:
        self.scroll = ctk.CTkScrollableFrame(self, fg_color="transparent", corner_radius=0)
        self.scroll.pack(fill="both", expand=True, padx=Theme.PAGE_PAD_X, pady=Theme.PAGE_PAD_Y)

        self.snapshot_freshness = ctk.CTkLabel(
            self.scroll,
            text="Snapshot: Н/Д",
            font=Theme.font_micro(),
            text_color=Theme.TEXT_MUTED,
            anchor="w",
        )
        self.snapshot_freshness.pack(fill="x", pady=(0, Theme.SPACE_XS))

        self.metrics = ctk.CTkFrame(self.scroll, fg_color="transparent")
        self.metrics.pack(fill="x", pady=(0, Theme.SPACE_SM))
        for column in range(5):
            self.metrics.grid_columnconfigure(column, weight=1)
        self.quota_metric = _KpiCard(self.metrics, "Квоты", "Н/Д", "нет измерения", icon="◔")
        self.calls_metric = _KpiCard(self.metrics, "Вызовы", "Н/Д", "измерения", icon="◎")
        self.agents_metric = _KpiCard(self.metrics, "Агенты онлайн", "0/0", "готовые роли", icon="◇")
        self.latency_metric = _KpiCard(self.metrics, "Время отклика", "Н/Д", "P50", icon="⌁")
        self.failover_metric = _KpiCard(self.metrics, "Переключения", "Н/Д", "failover", icon="⇄")
        for index, metric in enumerate(
            (self.quota_metric, self.calls_metric, self.agents_metric, self.latency_metric, self.failover_metric)
        ):
            metric.grid(row=0, column=index, padx=Theme.SPACE_XS, sticky="nsew")

        body = ctk.CTkFrame(self.scroll, fg_color="transparent")
        body.pack(fill="x")
        body.grid_columnconfigure(0, weight=4)
        body.grid_columnconfigure(1, weight=1)

        route_card = HubCard(body)
        route_card.grid(row=0, column=0, sticky="nsew", padx=(0, Theme.SPACE_SM))
        ctk.CTkLabel(
            route_card,
            text="Маршрутизация запросов",
            font=Theme.font_heading(),
            text_color=Theme.TEXT_PRIMARY,
        ).pack(anchor="w", padx=Theme.CARD_PAD_X, pady=(Theme.CARD_PAD_Y, Theme.SPACE_SM))
        flow = ctk.CTkFrame(route_card, fg_color="transparent")
        flow.pack(fill="both", expand=True, padx=Theme.CARD_PAD_X, pady=(0, Theme.CARD_PAD_Y))
        flow.grid_columnconfigure(0, weight=3)
        flow.grid_columnconfigure(1, weight=1)
        flow.grid_columnconfigure(2, weight=3)
        flow.grid_columnconfigure(3, weight=1)
        flow.grid_columnconfigure(4, weight=3)
        self.provider_column = ctk.CTkFrame(flow, fg_color="transparent")
        self.provider_column.grid(row=0, column=0, sticky="nsew")
        ctk.CTkLabel(flow, text="→", font=Theme.font_metric(), text_color=Theme.TEXT_ACCENT).grid(row=0, column=1)
        self.orchestrator_card = _FlowCard(flow, border_color=Theme.BORDER_ACCENT)
        self.orchestrator_card.grid(row=0, column=2, sticky="ew", padx=Theme.SPACE_XS)
        ctk.CTkLabel(flow, text="→", font=Theme.font_metric(), text_color=Theme.TEXT_ACCENT).grid(row=0, column=3)
        self.agent_column = ctk.CTkFrame(flow, fg_color="transparent")
        self.agent_column.grid(row=0, column=4, sticky="nsew")
        self.context_card = _FlowCard(flow)
        self.context_card.grid(row=1, column=2, sticky="ew", padx=Theme.SPACE_XS, pady=(Theme.SPACE_SM, 0))
        self.context_card.update_card("Хранилище контекста", "Постоянная память", "Состояние: Н/Д")

        self.realtime = HubCard(body)
        self.realtime.grid(row=0, column=1, sticky="nsew")
        ctk.CTkLabel(
            self.realtime,
            text="Статус в реальном времени",
            font=Theme.font_heading(),
            text_color=Theme.TEXT_PRIMARY,
        ).pack(anchor="w", padx=Theme.CARD_PAD_X, pady=(Theme.CARD_PAD_Y, Theme.SPACE_SM))
        ctk.CTkLabel(self.realtime, text="ПРОВАЙДЕРЫ", font=Theme.font_micro(), text_color=Theme.TEXT_MUTED).pack(
            anchor="w", padx=Theme.CARD_PAD_X
        )
        self.provider_status = ctk.CTkFrame(self.realtime, fg_color="transparent")
        self.provider_status.pack(fill="x", padx=Theme.CARD_PAD_X, pady=Theme.SPACE_XS)
        ctk.CTkLabel(
            self.realtime, text="СИСТЕМНЫЕ ПОКАЗАТЕЛИ", font=Theme.font_micro(), text_color=Theme.TEXT_MUTED
        ).pack(anchor="w", padx=Theme.CARD_PAD_X, pady=(Theme.SPACE_SM, 0))
        self.host_metrics = ctk.CTkLabel(
            self.realtime,
            text="CPU       Н/Д\nПамять   Н/Д\nДиск       Н/Д\nСеть       Н/Д",
            justify="left",
            anchor="w",
            font=Theme.font_caption(),
            text_color=Theme.TEXT_SECONDARY,
        )
        self.host_metrics.pack(fill="x", padx=Theme.CARD_PAD_X, pady=Theme.SPACE_SM)
        ctk.CTkLabel(
            self.realtime,
            text="Локальные измерения • psutil",
            wraplength=210,
            justify="left",
            font=Theme.font_micro(),
            text_color=Theme.TEXT_MUTED,
        ).pack(anchor="w", padx=Theme.CARD_PAD_X, pady=(0, Theme.CARD_PAD_Y))

        self.events_card = HubCard(self.scroll)
        self.events_card.pack(fill="x", pady=(Theme.SPACE_SM, 0))
        ctk.CTkLabel(
            self.events_card,
            text="Последние события",
            font=Theme.font_heading(),
            text_color=Theme.TEXT_PRIMARY,
        ).pack(anchor="w", padx=Theme.CARD_PAD_X, pady=(Theme.CARD_PAD_Y, Theme.SPACE_XS))
        self.events_body = ctk.CTkFrame(self.events_card, fg_color="transparent")
        self.events_body.pack(fill="x", padx=Theme.CARD_PAD_X, pady=(0, Theme.CARD_PAD_Y))
        self.events_empty = ctk.CTkLabel(
            self.events_body,
            text="События: Н/Д",
            font=Theme.font_caption(),
            text_color=Theme.TEXT_MUTED,
        )
        self.events_empty.pack(anchor="w", pady=Theme.SPACE_SM)

    @staticmethod
    def _quota_text(snapshot: HubSnapshot, provider_id: str) -> str:
        profiles = snapshot.profiles_by_provider.get(provider_id, [])
        measured: list[float] = []
        for profile in profiles:
            quota = snapshot.quotas.get(profile.profile_id)
            if not quota or getattr(quota, "is_estimated", True):
                continue
            measured.extend(
                float(bucket.remaining_percent) for bucket in quota.buckets if bucket.remaining_percent is not None
            )
        if not measured:
            return "Квота: Н/Д"
        return f"Корзины: {len(measured)} измерено"

    @staticmethod
    def _sync_cards(
        container: Any,
        cache: Dict[str, _FlowCard],
        items: Iterable[tuple[str, str, str, str, str]],
    ) -> None:
        prepared = list(items)
        live = {key for key, *_rest in prepared}
        for key in list(cache):
            if key not in live:
                cache.pop(key).destroy()
        for index, (key, title, subtitle, meta, status) in enumerate(prepared):
            card = cache.get(key)
            if card is None:
                card = _FlowCard(container)
                cache[key] = card
            card.update_card(title, subtitle, meta, status)
            card.pack(fill="x", pady=Theme.SPACE_XS)

    def update_data(self, snapshot: Optional[HubSnapshot] = None) -> None:
        if not isinstance(snapshot, HubSnapshot):
            return
        self.snapshot_freshness.configure(
            text=f"{'⚠ данные устарели' if snapshot.is_stale else '● данные актуальны'} • snapshot #{snapshot.seq}",
            text_color=Theme.STATUS_WARNING if snapshot.is_stale else Theme.STATUS_HEALTHY,
        )
        readiness = snapshot.readiness
        telemetry = dict(snapshot.metrics.get("telemetry") or {})
        global_telemetry = dict(telemetry.get("global") or {})
        provider_telemetry = dict(telemetry.get("by_provider") or {})
        role_telemetry = dict(telemetry.get("by_role") or {})
        has_telemetry = bool(telemetry.get("has_data"))
        self.calls_metric.val_label.configure(text=str(global_telemetry.get("total_calls")) if has_telemetry else "Н/Д")
        self.latency_metric.val_label.configure(
            text=f"{global_telemetry['latency_p50_ms']:.0f} мс"
            if has_telemetry and global_telemetry.get("latency_p50_ms") is not None
            else "Н/Д"
        )
        self.failover_metric.val_label.configure(
            text=str(global_telemetry.get("failovers_count")) if has_telemetry else "Н/Д"
        )
        active_calls = snapshot.metrics.get("active_calls_total")
        self.calls_metric.sub_label.configure(
            text=f"активно: {active_calls}" if isinstance(active_calls, int) else "own_measurement"
        )
        self.agents_metric.val_label.configure(text=f"{readiness.roles_ready_count}/{readiness.total_roles}")
        measured_buckets = sum(
            1
            for quota in snapshot.quotas.values()
            if not getattr(quota, "is_estimated", True)
            for bucket in quota.buckets
            if bucket.remaining_percent is not None
        )
        self.quota_metric.val_label.configure(text=str(measured_buckets) if measured_buckets else "Н/Д")
        self.quota_metric.sub_label.configure(text="измеренных корзин" if measured_buckets else "нет измерения")

        providers = list(snapshot.providers)[:3]

        def provider_activity(provider_id: str, online: int, connected: int) -> str:
            measured = dict(provider_telemetry.get(provider_id) or {})
            share = measured.get("call_share")
            calls = measured.get("total_calls")
            if share is not None and calls is not None:
                return f"{share:.0%} потока • {calls} вызовов"
            return f"{online}/{connected} онлайн"

        self._sync_cards(
            self.provider_column,
            self._provider_cards,
            (
                (
                    provider.provider_id,
                    provider.provider_name,
                    provider_activity(
                        provider.provider_id,
                        provider.online_count,
                        provider.connected_count,
                    ),
                    self._quota_text(snapshot, provider.provider_id),
                    "healthy" if provider.online_count else "warning",
                )
                for provider in providers
            ),
        )
        orchestrator = next((agent for agent in snapshot.agents if agent.is_main_orchestrator), None)
        if orchestrator:
            self.orchestrator_card.update_card(
                "Главный оркестратор",
                f"{orchestrator.provider_display_name} • {orchestrator.model}",
                f"{orchestrator.account_identity or 'Аккаунт: Н/Д'} • {orchestrator.status_label_ru}",
                "active" if orchestrator.is_active else "warning",
            )
        else:
            self.orchestrator_card.update_card("Главный оркестратор", "Не назначен", "Аккаунт: Н/Д", "warning")
        agents = [agent for agent in snapshot.agents if not agent.is_main_orchestrator][:3]
        self._sync_cards(
            self.agent_column,
            self._agent_cards,
            (
                (
                    agent.role_id,
                    agent.role_name_ru,
                    f"{agent.provider_display_name} • {agent.model}",
                    (
                        f"{agent.active_quota_label or 'Квота: Н/Д'}"
                        + (
                            f" • {role_telemetry[agent.role_id]['total_calls']} вызовов"
                            if role_telemetry.get(agent.role_id, {}).get("has_data")
                            else ""
                        )
                    ),
                    "healthy" if agent.is_active else "warning",
                )
                for agent in agents
            ),
        )

        live_provider_ids = {provider.provider_id for provider in snapshot.providers}
        for provider_id in list(self._provider_status_rows):
            if provider_id not in live_provider_ids:
                self._provider_status_rows.pop(provider_id).destroy()
        for provider in snapshot.providers:
            row = self._provider_status_rows.get(provider.provider_id)
            if row is None:
                row = _StatusRow(self.provider_status)
                row.pack(fill="x", pady=Theme.SPACE_XS)
                self._provider_status_rows[provider.provider_id] = row
            measured = dict(provider_telemetry.get(provider.provider_id) or {})
            latency = measured.get("latency_p50_ms")
            row.update_row(
                provider.provider_name,
                (
                    f"{provider.online_count}/{provider.connected_count} • {latency:.0f} мс"
                    if latency is not None
                    else f"{provider.online_count}/{provider.connected_count}"
                ),
                "healthy" if provider.online_count else "warning",
            )

        host = dict(snapshot.metrics.get("host") or {})
        if host.get("has_data"):
            network_total = sum(
                value for value in (host.get("net_bytes_sent"), host.get("net_bytes_recv")) if isinstance(value, int)
            )
            network_text = f"{network_total / (1024 * 1024):.0f} МБ" if network_total else "Н/Д"
            self.host_metrics.configure(
                text=(
                    f"CPU       {host.get('cpu_percent', 'Н/Д')}%\n"
                    f"Память   {host.get('memory_percent', 'Н/Д')}%\n"
                    f"Диск       {host.get('disk_percent', 'Н/Д')}%\n"
                    f"Сеть       {network_text}"
                )
            )
        else:
            self.host_metrics.configure(text="CPU       Н/Д\nПамять   Н/Д\nДиск       Н/Д\nСеть       Н/Д")

    def update_events(self, events: Iterable[Any]) -> None:
        items = list(events)[:5]
        while len(self._event_rows) < len(items):
            row = _EventRow(self.events_body)
            row.pack(fill="x", pady=Theme.SPACE_XS)
            self._event_rows.append(row)
        for index, row in enumerate(self._event_rows):
            if index < len(items):
                row.update_event(items[index])
                row.pack(fill="x", pady=Theme.SPACE_XS)
            else:
                row.pack_forget()
        if items:
            self.events_empty.pack_forget()
        else:
            self.events_empty.pack(anchor="w", pady=Theme.SPACE_SM)
