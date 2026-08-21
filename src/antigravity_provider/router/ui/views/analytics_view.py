"""Empirical router telemetry and local host measurements."""

from __future__ import annotations

from typing import Any, Optional

import customtkinter as ctk

from antigravity_provider.router.state_store import HubSnapshot
from antigravity_provider.router.ui.components import HubMetricCard, SectionHeader
from antigravity_provider.router.ui.theme import Theme


class AnalyticsView(ctk.CTkFrame):
    def __init__(self, master: Any, **kwargs):
        super().__init__(master=master, fg_color="transparent", **kwargs)
        SectionHeader(
            self,
            title="Аналитика",
            subtitle="Только собственные измерения Hermes Router",
        ).pack(fill="x", padx=Theme.PAGE_PAD_X, pady=(Theme.PAGE_PAD_Y, Theme.SPACE_SM))
        grid = ctk.CTkFrame(self, fg_color="transparent")
        grid.pack(fill="x", padx=Theme.PAGE_PAD_X)
        for column in range(3):
            grid.grid_columnconfigure(column, weight=1)
        definitions = (
            ("calls", "Вызовы", "◎"),
            ("latency", "P50 задержка", "⌁"),
            ("errors", "Доля ошибок", "△"),
            ("tokens", "Токены", "◇"),
            ("failovers", "Переключения", "⇄"),
            ("cost", "Стоимость", "$"),
        )
        self.cards = {}
        for index, (key, title, icon) in enumerate(definitions):
            card = HubMetricCard(grid, title, "Н/Д", "нет измерений", icon=icon)
            card.grid(row=index // 3, column=index % 3, padx=Theme.SPACE_XS, pady=Theme.SPACE_XS, sticky="nsew")
            self.cards[key] = card
        self.note = ctk.CTkLabel(
            self,
            text="Вызовы измерены Hermes Router; аппаратные показатели — локально через psutil. Внешний SLA не заявляется.",
            font=Theme.font_caption(),
            text_color=Theme.TEXT_MUTED,
        )
        self.note.pack(anchor="w", padx=Theme.PAGE_PAD_X, pady=Theme.SPACE_LG)

    def update_data(self, snapshot: Optional[HubSnapshot] = None) -> None:
        if not isinstance(snapshot, HubSnapshot):
            return
        telemetry = dict(snapshot.metrics.get("telemetry") or {})
        global_telemetry = dict(telemetry.get("global") or {})
        if not telemetry.get("has_data"):
            for card in self.cards.values():
                card.val_label.configure(text="Н/Д")
                card.sub_label.configure(text="нет измерений")
            return
        values = {
            "calls": str(global_telemetry.get("total_calls", "Н/Д")),
            "latency": f"{global_telemetry['latency_p50_ms']:.0f} мс"
            if global_telemetry.get("latency_p50_ms") is not None
            else "Н/Д",
            "errors": f"{global_telemetry['error_rate']:.1%}"
            if global_telemetry.get("error_rate") is not None
            else "Н/Д",
            "tokens": str(global_telemetry.get("total_tokens"))
            if global_telemetry.get("total_tokens") is not None
            else "Н/Д",
            "failovers": str(global_telemetry.get("failovers_count", 0)),
            "cost": f"${global_telemetry['total_cost_usd']:.4f}"
            if global_telemetry.get("total_cost_usd") is not None
            else "Н/Д",
        }
        for key, value in values.items():
            self.cards[key].val_label.configure(text=value)
            self.cards[key].sub_label.configure(text="own_measurement")
