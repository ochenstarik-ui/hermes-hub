"""Hermes Hub — Logs View (Журнал событий и аудит маршрутизации)."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Optional
import customtkinter as ctk

from antigravity_provider.router.ui.theme import Theme
from antigravity_provider.router.ui.components import (
    HubButton,
    HubCard,
    HubSectionHeader,
)
from antigravity_provider.router.unified_health import EventLogService


class LogsView(ctk.CTkFrame):
    def __init__(self, master: Any, **kwargs):
        super().__init__(master=master, fg_color="transparent", **kwargs)
        self.filter_category: Optional[str] = None
        self._build()

    def _build(self):
        header = HubSectionHeader(
            self,
            title="Журнал Событий и Аудит",
            subtitle="История подключений, переключений маршрутизатора, исчерпания квот и failover",
            action_text="🔄 Обновить",
            action_cmd=self._refresh_events,
        )
        header.pack(fill="x", padx=20, pady=(16, 12))

        # Filter Buttons Row
        filters_row = ctk.CTkFrame(self, fg_color="transparent")
        filters_row.pack(fill="x", padx=20, pady=(0, 8))

        cats = [
            (None, "Все события"),
            ("account", "Аккаунты"),
            ("quota", "Квоты"),
            ("routing", "Маршрутизация"),
            ("system", "Система"),
        ]

        self.filter_btns: Dict[Optional[str], ctk.CTkButton] = {}
        for c_id, c_lbl in cats:
            btn = ctk.CTkButton(
                filters_row,
                text=c_lbl,
                width=110,
                height=28,
                fg_color=Theme.SURFACE if c_id is None else "transparent",
                hover_color=Theme.SURFACE_HOVER,
                text_color=Theme.TEXT_ACCENT if c_id is None else Theme.TEXT_SECONDARY,
                font=Theme.font_micro(),
                corner_radius=Theme.RADIUS_SM,
                command=lambda cid=c_id: self._set_filter(cid),
            )
            btn.pack(side="left", padx=(0, 6))
            self.filter_btns[c_id] = btn

        # Events Scroll Area
        self.scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.scroll.pack(fill="both", expand=True, padx=15, pady=(0, 10))

        self._refresh_events()

    def _set_filter(self, cat: Optional[str]):
        self.filter_category = cat
        for cid, btn in self.filter_btns.items():
            if cid == cat:
                btn.configure(fg_color=Theme.SURFACE, text_color=Theme.TEXT_ACCENT)
            else:
                btn.configure(fg_color="transparent", text_color=Theme.TEXT_SECONDARY)
        self._refresh_events()

    def _refresh_events(self):
        for w in self.scroll.winfo_children():
            w.destroy()

        events = EventLogService.get().get_events(limit=50, category=self.filter_category)

        if not events:
            ctk.CTkLabel(self.scroll, text="Нет записанных событий", font=Theme.font_body(), text_color=Theme.TEXT_MUTED).pack(pady=40)
            return

        for ev in events:
            card = HubCard(self.scroll, border_color=Theme.BORDER_SUBTLE, fg_color=Theme.SURFACE)
            card.pack(fill="x", pady=3)

            top = ctk.CTkFrame(card, fg_color="transparent")
            top.pack(fill="x", padx=12, pady=(8, 2))

            dot_col = Theme.STATUS_HEALTHY if ev.level == "success" else (Theme.STATUS_WARNING if ev.level == "warning" else (Theme.STATUS_ERROR if ev.level == "error" else Theme.TEXT_MUTED))
            ctk.CTkLabel(top, text=f"● [{ev.category.upper()}]", font=Theme.font_micro(), text_color=dot_col).pack(side="left")
            ctk.CTkLabel(top, text=ev.timestamp, font=Theme.font_mono_sm(), text_color=Theme.TEXT_MUTED).pack(side="right")

            ctk.CTkLabel(card, text=ev.message, font=Theme.font_body(), text_color=Theme.TEXT_PRIMARY, wraplength=760, justify="left").pack(anchor="w", padx=12, pady=(0, 8))

            if ev.details:
                d_box = ctk.CTkFrame(card, fg_color=Theme.SURFACE_MUTED, corner_radius=Theme.RADIUS_SM)
                d_box.pack(fill="x", padx=12, pady=(0, 8))
                ctk.CTkLabel(d_box, text=ev.details, font=Theme.font_mono_sm(), text_color=Theme.TEXT_MUTED, justify="left").pack(padx=8, pady=4, anchor="w")
