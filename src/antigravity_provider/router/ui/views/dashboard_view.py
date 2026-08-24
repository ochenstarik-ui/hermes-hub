"""Approved Hermes Hub overview, visually aligned with the B5 reference."""

from __future__ import annotations

import tkinter as tk
from typing import Any, Callable, Dict, Iterable, Optional

import customtkinter as ctk

from antigravity_provider.router.state_store import HubSnapshot
from antigravity_provider.router.ui.assets import AssetManager
from antigravity_provider.router.ui.components import HubButton, HubCard
from antigravity_provider.router.ui.theme import Theme


class _Sparkline(ctk.CTkFrame):
    """Tiny chart built only from values observed during this UI session."""

    def __init__(self, master: Any, width: int = 58, height: int = 18):
        super().__init__(master, width=width, height=height, fg_color="transparent")
        self.pack_propagate(False)
        self._width, self._height = width, height
        self._values: list[float] = []
        self.canvas = tk.Canvas(self, width=width, height=height, bg=Theme.SURFACE, highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True)

    def update_value(self, value: Optional[float]) -> None:
        if value is not None:
            self._values.append(float(value))
            self._values = self._values[-18:]
        self.canvas.delete("all")
        if not self._values:
            self.canvas.create_line(3, self._height - 4, self._width - 3, self._height - 4, fill=Theme.BORDER_SUBTLE)
            return
        values = self._values if len(self._values) > 1 else [self._values[0], self._values[0]]
        low, high = min(values), max(values)
        span = max(high - low, max(abs(high), 1.0) * 0.08)
        points: list[float] = []
        for index, current in enumerate(values):
            points.extend(
                (
                    3 + index * (self._width - 6) / max(len(values) - 1, 1),
                    self._height - 3 - ((current - low) / span) * (self._height - 7),
                )
            )
        self.canvas.create_line(*points, fill=Theme.STATUS_HEALTHY, width=1.4, smooth=True)


class _KpiCard(HubCard):
    def __init__(self, master: Any, title: str, value: str, subtext: str):
        super().__init__(master, corner_radius=Theme.RADIUS_SM, height=62)
        self.grid_propagate(False)
        self.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(self, text=title, font=Theme.font_micro(), text_color=Theme.TEXT_SECONDARY).grid(
            row=0, column=0, columnspan=3, sticky="w", padx=10, pady=(7, 0)
        )
        self.val_label = ctk.CTkLabel(self, text=value, font=Theme.font_heading(), text_color=Theme.TEXT_PRIMARY)
        self.val_label.grid(row=1, column=0, sticky="w", padx=10, pady=(0, 6))
        self.sub_label = ctk.CTkLabel(self, text=subtext, font=Theme.font_micro(), text_color=Theme.TEXT_MUTED)
        self.sub_label.grid(row=1, column=1, sticky="e", padx=(2, 5), pady=(0, 6))
        self.spark = _Sparkline(self, width=48, height=16)
        self.spark.grid(row=1, column=2, sticky="e", padx=(0, 7), pady=(0, 5))

    def set_metric(self, value: str, subtext: str, numeric: Optional[float] = None) -> None:
        self.val_label.configure(text=value)
        self.sub_label.configure(text=subtext)
        self.spark.update_value(numeric)


class _EndpointCard(HubCard):
    """Compact provider/agent card with brand icon and a real quota bar."""

    def __init__(self, master: Any):
        super().__init__(master, corner_radius=Theme.RADIUS_MD, height=76)
        self.pack_propagate(False)
        self.icon = ctk.CTkLabel(self, text="◇", width=38, font=Theme.font_heading(), text_color=Theme.TEXT_ACCENT)
        self.icon.pack(side="left", padx=(8, 5))
        text = ctk.CTkFrame(self, fg_color="transparent")
        text.pack(side="left", fill="both", expand=True, pady=3)
        self.title = ctk.CTkLabel(text, text="", font=Theme.font_body_bold(), text_color=Theme.TEXT_PRIMARY)
        self.title.pack(anchor="w")
        self.subtitle = ctk.CTkLabel(text, text="", font=Theme.font_micro(), text_color=Theme.TEXT_MUTED)
        self.subtitle.pack(anchor="w", pady=(0, 1))
        self.status = ctk.CTkLabel(text, text="", font=Theme.font_micro(), text_color=Theme.STATUS_HEALTHY)
        self.status.pack(anchor="w")
        quota = ctk.CTkFrame(self, fg_color="transparent", width=92)
        quota.pack(side="right", fill="y", padx=(3, 8), pady=8)
        quota.pack_propagate(False)
        self.quota_label = ctk.CTkLabel(quota, text="—", font=Theme.font_micro(), text_color=Theme.TEXT_SECONDARY)
        self.quota_label.pack(anchor="e")
        self.progress = ctk.CTkProgressBar(
            quota, height=4, corner_radius=2, progress_color=Theme.STATUS_HEALTHY, fg_color=Theme.SURFACE_MUTED
        )
        self.progress.pack(fill="x", pady=(5, 0))
        self.progress.set(0)
        self._click_action: Optional[Callable[[], None]] = None
        self._status = "unknown"
        self._bind_click_tree(self)
        try:
            self._canvas.configure(takefocus=1)
        except (AttributeError, tk.TclError):
            pass
        self.bind("<Return>", self._activate, add="+")
        self.bind("<space>", self._activate, add="+")
        self.bind("<Enter>", self._hover_on, add="+")
        self.bind("<Leave>", self._hover_off, add="+")

    def _bind_click_tree(self, widget: Any) -> None:
        widget.configure(cursor="hand2")
        widget.bind("<Button-1>", self._activate, add="+")
        for child in widget.winfo_children():
            self._bind_click_tree(child)

    def set_click_action(self, action: Optional[Callable[[], None]]) -> None:
        self._click_action = action
        self.configure(cursor="hand2" if action else "arrow")

    def _activate(self, _event: Any = None) -> None:
        if self._click_action:
            self._click_action()

    def _hover_on(self, _event: Any = None) -> None:
        if self._click_action:
            self.configure(fg_color=Theme.SURFACE_HOVER, border_color=Theme.BORDER_HOVER)

    def _hover_off(self, _event: Any = None) -> None:
        self.configure(
            fg_color=Theme.SURFACE,
            border_color=Theme.BORDER_ACCENT if self._status == "healthy" else Theme.BORDER,
        )

    def update_card(
        self,
        provider_key: str,
        title: str,
        subtitle: str,
        status_text: str,
        quota_text: str,
        quota_percent: Optional[float],
        status: str,
    ) -> None:
        self._status = status
        image = AssetManager.get().get_provider_image(provider_key, size=(30, 30))
        self.icon.configure(image=image, text="" if image else "◇")
        self.icon.image = image
        self.title.configure(text=title)
        self.subtitle.configure(text=subtitle)
        self.status.configure(text=f"●  {status_text}")
        self.quota_label.configure(text=quota_text)
        color = {
            "healthy": Theme.STATUS_HEALTHY,
            "warning": Theme.STATUS_WARNING,
            "error": Theme.STATUS_ERROR,
        }.get(status, Theme.STATUS_DISABLED)
        self.status.configure(text_color=color)
        self.configure(border_color=Theme.BORDER_ACCENT if status == "healthy" else Theme.BORDER)
        self.progress.configure(progress_color=color)
        self.progress.set(max(0.0, min(1.0, quota_percent / 100.0)) if quota_percent is not None else 0)


class _OrchestratorNode(ctk.CTkFrame):
    def __init__(self, master: Any):
        super().__init__(master, width=174, height=150, fg_color="transparent")
        self.pack_propagate(False)
        self.circle = ctk.CTkFrame(
            self,
            width=96,
            height=96,
            corner_radius=48,
            fg_color=Theme.BG_SIDEBAR if Theme.current_scheme != "light" else Theme.SURFACE,
            border_width=2,
            border_color=Theme.BORDER_ACCENT,
        )
        self.circle.pack(pady=(0, 3))
        self.circle.pack_propagate(False)
        logo = AssetManager.get().get_logo_image(size=(76, 76))
        self.logo = ctk.CTkLabel(
            self.circle, image=logo, text="H" if logo is None else "", text_color=Theme.TEXT_ACCENT
        )
        self.logo.image = logo
        self.logo.place(relx=0.5, rely=0.5, anchor="center")
        ctk.CTkLabel(
            self, text="Главный оркестратор", font=Theme.font_body_bold(), text_color=Theme.TEXT_PRIMARY
        ).pack()
        self.subtitle = ctk.CTkLabel(self, text="Не назначен", font=Theme.font_micro(), text_color=Theme.TEXT_MUTED)
        self.subtitle.pack()
        self.status = ctk.CTkLabel(self, text="●  Н/Д", font=Theme.font_micro(), text_color=Theme.STATUS_WARNING)
        self.status.pack()

    def update_node(self, subtitle: str, status_text: str, active: bool) -> None:
        self.subtitle.configure(text=subtitle)
        self.status.configure(
            text=f"●  {status_text}", text_color=Theme.STATUS_HEALTHY if active else Theme.STATUS_WARNING
        )


class _RouteDiagram(ctk.CTkFrame):
    """Responsive diagram with smooth connections behind native widgets."""

    def __init__(self, master: Any):
        super().__init__(master, height=440, fg_color="transparent")
        self.pack_propagate(False)
        self.canvas = tk.Canvas(self, bg=Theme.SURFACE, highlightthickness=0, bd=0)
        self.canvas.place(relx=0, rely=0, relwidth=1, relheight=1)
        self.provider_slots: list[Any] = []
        self.agent_slots: list[Any] = []
        self.orchestrator = _OrchestratorNode(self)
        self.orchestrator.place(relx=0.51, rely=0.46, anchor="center")
        self.context = HubCard(self, corner_radius=Theme.RADIUS_MD, height=46)
        self.context.place(relx=0.51, rely=0.91, relwidth=0.25, anchor="center")
        ctk.CTkLabel(
            self.context, text="▤  Хранилище контекста", font=Theme.font_caption(), text_color=Theme.TEXT_PRIMARY
        ).pack(pady=(6, 0))
        self.context_status = ctk.CTkLabel(
            self.context,
            text="●  Нет телеметрии хранилища",
            font=Theme.font_micro(),
            text_color=Theme.TEXT_MUTED,
        )
        self.context_status.pack()
        self._left_labels: list[str] = []
        self._right_labels: list[str] = []
        self._redraw_timer_id: Any = None
        self.bind("<Configure>", self._schedule_redraw)

    def _schedule_redraw(self, event: Any = None) -> None:
        """Свести поток <Configure> к одной перерисовке.

        При перетаскивании окна Tk шлёт <Configure> непрерывно, и раньше каждое
        событие вызывало полную перерисовку канвы: удаление и построение всех
        связей, подписей и узлов. Очередь не успевала разгребаться, и окно
        продолжало ползти ещё несколько секунд после того, как мышь отпущена.

        Перерисовываем один раз, когда поток событий утих.
        """
        if self._redraw_timer_id is not None:
            try:
                self.after_cancel(self._redraw_timer_id)
            except Exception:
                pass
        self._redraw_timer_id = self.after(80, self._redraw_now)

    def _redraw_now(self) -> None:
        self._redraw_timer_id = None
        try:
            self._redraw()
        except Exception:
            pass

    def sync_slots(self, provider_count: int, agent_count: int) -> None:
        """Grow/shrink endpoint slots to match the snapshot without hard caps."""
        while len(self.provider_slots) < provider_count:
            self.provider_slots.append(ctk.CTkFrame(self, height=76, fg_color="transparent"))
        while len(self.agent_slots) < agent_count:
            self.agent_slots.append(ctk.CTkFrame(self, height=68, fg_color="transparent"))
        for index, slot in enumerate(self.provider_slots):
            if index >= provider_count:
                slot.place_forget()
                continue
            y = 0.02 + index * (0.78 / max(provider_count - 1, 1))
            slot.place(relx=0.012, rely=y, relwidth=0.30)
        for index, slot in enumerate(self.agent_slots):
            if index >= agent_count:
                slot.place_forget()
                continue
            y = 0.01 + index * (0.80 / max(agent_count - 1, 1))
            slot.place(relx=0.71, rely=y, relwidth=0.278)
        self._redraw()

    def set_labels(self, left: list[str], right: list[str]) -> None:
        self._left_labels = list(left)
        self._right_labels = list(right)
        self._redraw()

    def _redraw(self, _event: Any = None) -> None:
        width, height = max(self.winfo_width(), 600), max(self.winfo_height(), 300)
        self.canvas.delete("route")
        center_x, center_y = width * 0.51, height * 0.40
        left_x, right_x = width * 0.312, width * 0.71
        left_count = len(self._left_labels)
        left_ys = [
            height * (0.02 + index * (0.78 / max(left_count - 1, 1))) + 38 for index in range(left_count)
        ]
        for index, y_pos in enumerate(left_ys):
            self.canvas.create_line(
                left_x,
                y_pos,
                left_x + 44,
                y_pos,
                center_x - 78,
                center_y,
                center_x - 48,
                center_y,
                fill=Theme.BORDER_ACCENT,
                width=1.35,
                smooth=True,
                arrow=tk.LAST,
                tags="route",
            )
            self.canvas.create_text(
                left_x + 50,
                y_pos - 8,
                text=self._left_labels[index],
                fill=Theme.TEXT_SECONDARY,
                font=(Theme.FONT_FAMILY_UI, 8),
                anchor="w",
                tags="route",
            )
        right_count = len(self._right_labels)
        right_ys = [
            height * (0.01 + index * (0.80 / max(right_count - 1, 1))) + 34 for index in range(right_count)
        ]
        for index, y_pos in enumerate(right_ys):
            self.canvas.create_line(
                center_x + 48,
                center_y,
                right_x - 34,
                y_pos,
                right_x,
                y_pos,
                fill=Theme.BORDER_ACCENT,
                width=1.35,
                smooth=True,
                arrow=tk.LAST,
                tags="route",
            )
            self.canvas.create_text(
                right_x - 39,
                y_pos - 8,
                text=self._right_labels[index],
                fill=Theme.TEXT_SECONDARY,
                font=(Theme.FONT_FAMILY_UI, 8),
                anchor="e",
                tags="route",
            )
        self.canvas.create_line(
            center_x,
            center_y + 48,
            center_x,
            height * 0.83,
            fill=Theme.BORDER_ACCENT,
            width=1.2,
            dash=(3, 3),
            arrow=tk.LAST,
            tags="route",
        )


class _StatusRow(ctk.CTkFrame):
    def __init__(self, master: Any):
        super().__init__(master, fg_color="transparent", height=24)
        self.pack_propagate(False)
        self.dot = ctk.CTkLabel(self, text="●", width=12, font=Theme.font_micro())
        self.dot.pack(side="left")
        self.title = ctk.CTkLabel(self, text="", font=Theme.font_micro(), text_color=Theme.TEXT_PRIMARY)
        self.title.pack(side="left", padx=4)
        self.detail = ctk.CTkLabel(self, text="", font=Theme.font_micro(), text_color=Theme.TEXT_SECONDARY)
        self.detail.pack(side="right")

    def update_row(self, title: str, detail: str, status: str) -> None:
        self.title.configure(text=title)
        self.detail.configure(text=detail)
        self.dot.configure(
            text_color={
                "healthy": Theme.STATUS_HEALTHY,
                "warning": Theme.STATUS_WARNING,
                "error": Theme.STATUS_ERROR,
            }.get(status, Theme.STATUS_DISABLED)
        )


class _SystemRow(ctk.CTkFrame):
    def __init__(self, master: Any, title: str):
        super().__init__(master, fg_color="transparent", height=25)
        self.pack_propagate(False)
        ctk.CTkLabel(
            self, text=title, width=47, anchor="w", font=Theme.font_micro(), text_color=Theme.TEXT_SECONDARY
        ).pack(side="left")
        self.value = ctk.CTkLabel(
            self, text="Н/Д", width=48, anchor="e", font=Theme.font_micro(), text_color=Theme.TEXT_PRIMARY
        )
        self.value.pack(side="left")
        self.spark = _Sparkline(self, width=54, height=16)
        self.spark.pack(side="right")

    def update_metric(self, text: str, numeric: Optional[float]) -> None:
        self.value.configure(text=text)
        self.spark.update_value(numeric)


class _EventRow(ctk.CTkFrame):
    def __init__(self, master: Any):
        super().__init__(master, fg_color="transparent", height=23)
        self.pack_propagate(False)
        self.time = ctk.CTkLabel(self, width=58, text="", font=Theme.font_micro(), text_color=Theme.TEXT_MUTED)
        self.time.pack(side="left")
        self.dot = ctk.CTkLabel(self, width=18, text="●", font=Theme.font_micro())
        self.dot.pack(side="left")
        self.category = ctk.CTkLabel(
            self, width=112, text="", anchor="w", font=Theme.font_micro(), text_color=Theme.TEXT_PRIMARY
        )
        self.category.pack(side="left", padx=(0, 6))
        self.message = ctk.CTkLabel(self, text="", anchor="w", font=Theme.font_micro(), text_color=Theme.TEXT_SECONDARY)
        self.message.pack(side="left", fill="x", expand=True)
        self.tag = ctk.CTkLabel(
            self,
            text="",
            width=82,
            font=Theme.font_micro(),
            text_color=Theme.TEXT_SECONDARY,
            fg_color=Theme.SURFACE_MUTED,
            corner_radius=Theme.RADIUS_PILL,
        )
        self.tag.pack(side="right")

    def update_event(self, event: Any) -> None:
        level = str(getattr(event, "level", "info"))
        color = {
            "success": Theme.STATUS_HEALTHY,
            "warning": Theme.STATUS_WARNING,
            "error": Theme.STATUS_ERROR,
        }.get(level, Theme.STATUS_INFO)
        category = str(getattr(event, "category", "system"))
        self.time.configure(text=str(getattr(event, "timestamp", "Н/Д")))
        self.dot.configure(text_color=color)
        self.category.configure(text=category.replace("_", " ").title())
        self.message.configure(text=str(getattr(event, "message", "Событие без описания")))
        self.tag.configure(text=category)


class DashboardView(ctk.CTkFrame):
    """Dense overview following the approved dashboard composition."""

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
        self._provider_cards: Dict[str, _EndpointCard] = {}
        self._agent_cards: Dict[str, _EndpointCard] = {}
        self._event_rows: list[_EventRow] = []
        self._build()

    def _build(self) -> None:
        self.scroll = ctk.CTkScrollableFrame(self, fg_color="transparent", corner_radius=0)
        self.scroll.pack(fill="both", expand=True, padx=Theme.PAGE_PAD_X, pady=(8, 10))
        self.snapshot_freshness = ctk.CTkLabel(
            self.scroll,
            text="●  Система загружается",
            font=Theme.font_micro(),
            text_color=Theme.STATUS_HEALTHY,
            anchor="w",
        )
        # Kept as a presentation-state probe for tests/accessibility; the same
        # status is rendered once in the global header, as in the approved mockup.

        self.empty_state = HubCard(self.scroll, border_color=Theme.BORDER_ACCENT, fg_color=Theme.ACCENT_DIM)
        empty_copy = ctk.CTkFrame(self.empty_state, fg_color="transparent")
        empty_copy.pack(side="left", fill="x", expand=True, padx=14, pady=10)
        ctk.CTkLabel(
            empty_copy,
            text="Подключите первый аккаунт",
            font=Theme.font_heading(),
            text_color=Theme.TEXT_PRIMARY,
        ).pack(anchor="w")
        ctk.CTkLabel(
            empty_copy,
            text="Hermes назначит профиль роли и покажет реальную квоту, модель и цепочку отказоустойчивости.",
            font=Theme.font_caption(),
            text_color=Theme.TEXT_SECONDARY,
        ).pack(anchor="w", pady=(2, 0))
        HubButton(
            self.empty_state,
            text="Добавить аккаунт",
            variant="primary",
            command=lambda: self.on_action("add_account", {}) if self.on_action else None,
        ).pack(side="right", padx=12, pady=10)

        self.metrics = ctk.CTkFrame(self.scroll, fg_color="transparent")
        self.metrics.pack(fill="x", pady=(0, 8))
        for column in range(6):
            self.metrics.grid_columnconfigure(column, weight=1, uniform="kpi")
        self.quota_metric = _KpiCard(self.metrics, "Квота сегодня", "Н/Д", "нет измерения")
        self.calls_metric = _KpiCard(self.metrics, "Вызовы", "Н/Д", "активно: 0")
        self.agents_metric = _KpiCard(self.metrics, "Подключено аккаунтов", "0", "авторизованы")
        self.latency_metric = _KpiCard(self.metrics, "Время отклика", "Н/Д", "P50")
        self.failover_metric = _KpiCard(self.metrics, "Переключения", "Н/Д", "failover")
        self.host_metric = _KpiCard(self.metrics, "Нагрузка CPU", "Н/Д", "нет измерения хоста")
        for index, metric in enumerate(
            (
                self.quota_metric,
                self.calls_metric,
                self.agents_metric,
                self.latency_metric,
                self.failover_metric,
                self.host_metric,
            )
        ):
            metric.grid(row=0, column=index, padx=(0 if index == 0 else 3, 0 if index == 5 else 3), sticky="nsew")

        body = ctk.CTkFrame(self.scroll, fg_color="transparent")
        body.pack(fill="x")
        body.grid_columnconfigure(0, weight=1)
        route_card = HubCard(body, height=480)
        route_card.grid(row=0, column=0, sticky="nsew")
        route_card.grid_propagate(False)
        ctk.CTkLabel(
            route_card, text="Маршрутизация запросов", font=Theme.font_body_bold(), text_color=Theme.TEXT_PRIMARY
        ).pack(anchor="w", padx=10, pady=(8, 0))
        self.route_diagram = _RouteDiagram(route_card)
        self.route_diagram.pack(fill="both", expand=True, padx=6, pady=(2, 6))

        self.events_card = HubCard(self.scroll)
        self.events_card.pack(fill="x", pady=(8, 0))
        events_header = ctk.CTkFrame(self.events_card, fg_color="transparent")
        events_header.pack(fill="x", padx=10, pady=(7, 3))
        ctk.CTkLabel(
            events_header, text="Последние события", font=Theme.font_body_bold(), text_color=Theme.TEXT_PRIMARY
        ).pack(side="left")
        ctk.CTkButton(
            events_header,
            text="Все события  →",
            width=82,
            height=22,
            fg_color="transparent",
            hover_color=Theme.SURFACE_HOVER,
            text_color=Theme.TEXT_ACCENT,
            font=Theme.font_micro(),
            command=lambda: self.on_navigate("logs") if self.on_navigate else None,
        ).pack(side="right")
        self.events_body = ctk.CTkFrame(self.events_card, fg_color="transparent")
        self.events_body.pack(fill="x", padx=10, pady=(0, 7))
        self.events_empty = ctk.CTkLabel(
            self.events_body, text="События: Н/Д", font=Theme.font_micro(), text_color=Theme.TEXT_MUTED
        )
        self.events_empty.pack(anchor="w", pady=5)

    @staticmethod
    def _quota_measurement(snapshot: HubSnapshot, provider_id: Optional[str] = None) -> tuple[str, Optional[float]]:
        profiles = snapshot.profiles_by_provider.get(provider_id, []) if provider_id else snapshot.all_profiles.values()
        for profile in profiles:
            quota = snapshot.quotas.get(profile.profile_id)
            if not quota or getattr(quota, "is_estimated", True):
                continue
            for bucket in quota.buckets:
                if bucket.remaining_percent is not None:
                    return f"{bucket.remaining_percent:.0f}%", float(bucket.remaining_percent)
        return "Нет данных API", None

    @staticmethod
    def _agent_quota_measurement(snapshot: HubSnapshot, agent: Any) -> tuple[str, Optional[float]]:
        quota = snapshot.quotas.get(agent.assigned_profile_id)
        if quota and not getattr(quota, "is_estimated", True):
            bucket = quota.get_bucket_for_model(agent.model)
            if bucket and bucket.remaining_percent is not None:
                remaining = float(bucket.remaining_percent)
                return bucket.formatted_remaining(), remaining
        reason = getattr(quota, "unavailable_reason", None) if quota else None
        return reason or agent.active_quota_label or "Нет телеметрии: роль ещё не вызывалась", None

    @staticmethod
    def _sync_endpoint_cards(
        slots: list[Any],
        cache: Dict[str, _EndpointCard],
        items: Iterable[tuple[str, str, str, str, str, str, Optional[float], str]],
    ) -> None:
        prepared = list(items)[: len(slots)]
        live = {key for key, *_rest in prepared}
        for key in list(cache):
            if key not in live:
                cache.pop(key).destroy()
        for index, item in enumerate(prepared):
            key, provider_key, title, subtitle, status_text, quota_text, quota_percent, status = item
            card = cache.get(key)
            if card is None:
                card = _EndpointCard(slots[index])
                card.pack(fill="both", expand=True)
                cache[key] = card
            card.update_card(provider_key, title, subtitle, status_text, quota_text, quota_percent, status)

    def update_data(self, snapshot: Optional[HubSnapshot] = None) -> None:
        if not isinstance(snapshot, HubSnapshot):
            return
        self.snapshot_freshness.configure(
            text=(
                f"⚠  Данные устарели • snapshot #{snapshot.seq}"
                if snapshot.is_stale
                else f"●  Система работает штатно • snapshot #{snapshot.seq}"
            ),
            text_color=Theme.STATUS_WARNING if snapshot.is_stale else Theme.STATUS_HEALTHY,
        )
        readiness = snapshot.readiness
        if readiness.accounts_connected_count == 0:
            self.empty_state.pack(fill="x", pady=(0, 8), before=self.metrics)
        else:
            self.empty_state.pack_forget()
        telemetry = dict(snapshot.metrics.get("telemetry") or {})
        global_telemetry = dict(telemetry.get("global") or {})
        provider_telemetry = dict(telemetry.get("by_provider") or {})
        role_telemetry = dict(telemetry.get("by_role") or {})
        has_telemetry = bool(telemetry.get("has_data"))
        total_calls = global_telemetry.get("total_calls") if has_telemetry else None
        latency = global_telemetry.get("latency_p50_ms") if has_telemetry else None
        failovers = global_telemetry.get("failovers_count") if has_telemetry else None
        active_calls = snapshot.metrics.get("active_calls_total")
        host = dict(snapshot.metrics.get("host") or {})
        cpu = host.get("cpu_percent") if host.get("has_data") else None
        quota_text, quota_percent = self._quota_measurement(snapshot)
        self.quota_metric.set_metric(
            quota_text, "реальная корзина" if quota_percent is not None else "нет измерения", quota_percent
        )
        self.calls_metric.set_metric(
            str(total_calls) if total_calls is not None else "Н/Д",
            f"активно: {active_calls}"
            if isinstance(active_calls, int)
            else "нет телеметрии: запросы ещё не выполнялись",
            float(total_calls) if total_calls is not None else None,
        )
        self.agents_metric.set_metric(
            str(readiness.accounts_connected_count),
            f"роли готовы: {readiness.roles_ready_count}/{readiness.total_roles}",
            float(readiness.accounts_connected_count),
        )
        self.latency_metric.set_metric(
            f"{latency:.0f} мс" if latency is not None else "Н/Д",
            "P50" if latency is not None else "нет телеметрии: запросы ещё не выполнялись",
            float(latency) if latency is not None else None,
        )
        self.failover_metric.set_metric(
            str(failovers) if failovers is not None else "Н/Д",
            "failover" if failovers is not None else "нет телеметрии переключений",
            float(failovers) if failovers is not None else None,
        )
        self.host_metric.set_metric(
            f"{cpu:.0f}%" if cpu is not None else "Н/Д",
            "host_measurement" if cpu is not None else "psutil не вернул измерение",
            float(cpu) if cpu is not None else None,
        )

        providers = list(snapshot.providers)
        agents = [agent for agent in snapshot.agents if not agent.is_main_orchestrator]
        self.route_diagram.sync_slots(len(providers), len(agents))
        self._sync_endpoint_cards(
            self.route_diagram.provider_slots,
            self._provider_cards,
            (
                (
                    provider.provider_id,
                    provider.provider_id,
                    provider.provider_name,
                    (
                        f"{provider.connected_count} аккаунт(а) • "
                        + next(
                            (
                                profile.preferred_models[0]
                                for profile in snapshot.profiles_by_provider.get(provider.provider_id, [])
                                if profile.preferred_models
                            ),
                            "модели не обнаружены",
                        )
                    ),
                    "Онлайн" if provider.online_count else "Недоступен",
                    *self._quota_measurement(snapshot, provider.provider_id),
                    "healthy" if provider.online_count else "warning",
                )
                for provider in providers
            ),
        )
        orchestrator = next((agent for agent in snapshot.agents if agent.is_main_orchestrator), None)
        if orchestrator:
            self.route_diagram.orchestrator.update_node(
                f"{orchestrator.provider_display_name} • {orchestrator.model}",
                "Онлайн" if orchestrator.is_active else orchestrator.status_label_ru,
                orchestrator.is_active,
            )
        else:
            self.route_diagram.orchestrator.update_node("Аккаунт не подключён", "Роль не настроена", False)

        agent_items = []
        for agent in agents:
            agent_quota_text, agent_quota_percent = self._agent_quota_measurement(snapshot, agent)
            agent_items.append(
                (
                    agent.role_id,
                    agent.provider,
                    agent.role_name_ru,
                    f"{agent.provider_display_name} • {agent.model}",
                    "Здорово" if agent.is_active else agent.status_label_ru,
                    agent_quota_text,
                    agent_quota_percent,
                    "healthy" if agent.is_active else "warning",
                )
            )
        self._sync_endpoint_cards(
            self.route_diagram.agent_slots,
            self._agent_cards,
            agent_items,
        )
        for agent in agents:
            card = self._agent_cards.get(agent.role_id)
            if card is not None:
                card.set_click_action(
                    lambda current=agent: self.on_action(
                        "agent_settings",
                        {
                            "role_id": current.role_id,
                            "profile_id": current.assigned_profile_id,
                            "provider": current.provider,
                        },
                    )
                    if self.on_action
                    else None
                )
        left_labels: list[str] = []
        for provider in providers:
            share = dict(provider_telemetry.get(provider.provider_id) or {}).get("call_share")
            left_labels.append(f"{share:.0%}" if share is not None else "нет телеметрии")
        right_labels: list[str] = []
        for agent in agents:
            measured = dict(role_telemetry.get(agent.role_id) or {})
            calls = measured.get("total_calls") if measured.get("has_data") else None
            right_labels.append(f"{calls} выз." if calls is not None else "нет вызовов")
        self.route_diagram.set_labels(left_labels, right_labels)

    def update_events(self, events: Iterable[Any]) -> None:
        items = list(events)[:5]
        while len(self._event_rows) < len(items):
            row = _EventRow(self.events_body)
            row.pack(fill="x", pady=1)
            self._event_rows.append(row)
        for index, row in enumerate(self._event_rows):
            if index < len(items):
                row.update_event(items[index])
                row.pack(fill="x", pady=1)
            else:
                row.pack_forget()
        if items:
            self.events_empty.pack_forget()
        else:
            self.events_empty.pack(anchor="w", pady=5)
