"""Presentation-only settings screen; persistence is delegated to the app action layer."""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional

import customtkinter as ctk

from antigravity_provider.router.ui.components import ActionButton, HubCard, SectionHeader
from antigravity_provider.router.ui.theme import Theme
from antigravity_provider.version import CHANNEL, __version__


class SettingsView(ctk.CTkFrame):
    def __init__(
        self,
        master: Any,
        on_action: Optional[Callable] = None,
        theme_name: str = "dark",
        **kwargs,
    ):
        super().__init__(master=master, fg_color="transparent", **kwargs)
        self.on_action = on_action
        SectionHeader(
            self,
            title="Настройки",
            subtitle="Маршрутизация, мониторинг и обновления",
            action_text="Сохранить",
            action_cmd=self._save,
        ).pack(fill="x", padx=Theme.PAGE_PAD_X, pady=(Theme.PAGE_PAD_Y, Theme.SPACE_SM))
        scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=Theme.PAGE_PAD_X, pady=(0, Theme.PAGE_PAD_Y))
        appearance = self._section(scroll, "Оформление")
        theme_row = ctk.CTkFrame(appearance, fg_color="transparent")
        theme_row.pack(fill="x", padx=Theme.CARD_PAD_X, pady=Theme.SPACE_SM)
        ctk.CTkLabel(
            theme_row,
            text="Цветовая схема",
            font=Theme.font_body(),
            text_color=Theme.TEXT_PRIMARY,
        ).pack(side="left")
        self.theme = ctk.CTkOptionMenu(
            theme_row,
            values=list(Theme.SCHEME_LABELS.values()),
            fg_color=Theme.SURFACE_MUTED,
            button_color=Theme.SECONDARY,
            text_color=Theme.TEXT_PRIMARY,
        )
        self.theme.set(Theme.SCHEME_LABELS.get(theme_name, Theme.SCHEME_LABELS["dark"]))
        self.theme.pack(side="right")
        routing = self._section(scroll, "Маршрутизация и отказоустойчивость")
        self.affinity = self._switch(routing, "Сессионная привязка", True)
        self.failover = self._switch(routing, "Автоматический failover", True)
        self.same_account = self._switch(routing, "Сначала менять модель на том же аккаунте", True)
        refresh = self._section(scroll, "Мониторинг")
        row = ctk.CTkFrame(refresh, fg_color="transparent")
        row.pack(fill="x", padx=Theme.CARD_PAD_X, pady=Theme.SPACE_SM)
        ctk.CTkLabel(row, text="Интервал обновления квот", font=Theme.font_body(), text_color=Theme.TEXT_PRIMARY).pack(
            side="left"
        )
        self.interval = ctk.CTkOptionMenu(
            row,
            values=["Выкл", "1 мин", "5 мин", "10 мин", "30 мин"],
            fg_color=Theme.SURFACE_MUTED,
            button_color=Theme.SECONDARY,
        )
        self.interval.set("5 мин")
        self.interval.pack(side="right")
        updates = self._section(scroll, "Обновления")
        self.update_status = ctk.CTkLabel(
            updates,
            text=f"Версия {__version__} • канал {CHANNEL} • состояние обновления: Н/Д",
            font=Theme.font_body(),
            text_color=Theme.TEXT_SECONDARY,
        )
        self.update_status.pack(anchor="w", padx=Theme.CARD_PAD_X, pady=Theme.SPACE_SM)
        ActionButton(
            updates,
            text="Проверить обновления",
            variant="secondary",
            command=lambda: self.on_action and self.on_action("check_updates", {}),
        ).pack(anchor="w", padx=Theme.CARD_PAD_X, pady=(0, Theme.CARD_PAD_Y))

    @staticmethod
    def _section(master: Any, title: str) -> HubCard:
        card = HubCard(master)
        card.pack(fill="x", pady=Theme.SPACE_XS)
        ctk.CTkLabel(card, text=title, font=Theme.font_heading(), text_color=Theme.TEXT_PRIMARY).pack(
            anchor="w", padx=Theme.CARD_PAD_X, pady=(Theme.CARD_PAD_Y, Theme.SPACE_SM)
        )
        return card

    @staticmethod
    def _switch(master: Any, label: str, selected: bool) -> ctk.CTkSwitch:
        row = ctk.CTkFrame(master, fg_color="transparent")
        row.pack(fill="x", padx=Theme.CARD_PAD_X, pady=Theme.SPACE_XS)
        ctk.CTkLabel(row, text=label, font=Theme.font_body(), text_color=Theme.TEXT_PRIMARY).pack(side="left")
        switch = ctk.CTkSwitch(row, text="", progress_color=Theme.ACCENT)
        switch.pack(side="right")
        if selected:
            switch.select()
        return switch

    def _save(self) -> None:
        if not self.on_action:
            return
        intervals = {"Выкл": 0, "1 мин": 60, "5 мин": 300, "10 мин": 600, "30 мин": 1800}
        theme_key = next(
            (key for key, label in Theme.SCHEME_LABELS.items() if label == self.theme.get()),
            "dark",
        )
        self.on_action(
            "save_settings",
            {
                "session_affinity": bool(self.affinity.get()),
                "auto_failover": bool(self.failover.get()),
                "prefer_same_account_model_fallback": bool(self.same_account.get()),
                "quota_refresh_interval_label": self.interval.get(),
                "quota_refresh_interval_sec": intervals.get(self.interval.get(), 300),
                "theme": theme_key,
            },
        )
