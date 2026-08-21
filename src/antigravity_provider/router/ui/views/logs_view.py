"""Keyed event timeline populated by the application action layer."""

from __future__ import annotations

from typing import Any, Iterable, Optional

import customtkinter as ctk

from antigravity_provider.router.state_store import HubSnapshot
from antigravity_provider.router.ui.components import FilterButton, HubCard, SearchField, SectionHeader
from antigravity_provider.router.ui.theme import Theme


class _LogRow(HubCard):
    def __init__(self, master: Any):
        super().__init__(master, corner_radius=Theme.RADIUS_SM, border_color=Theme.BORDER_SUBTLE)
        self.time = ctk.CTkLabel(self, text="", width=70, font=Theme.font_mono_sm(), text_color=Theme.TEXT_MUTED)
        self.time.pack(side="left", padx=(Theme.CARD_PAD_X, 0), pady=Theme.SPACE_SM)
        self.dot = ctk.CTkLabel(self, text="●", width=18, font=Theme.font_micro())
        self.dot.pack(side="left")
        self.message = ctk.CTkLabel(self, text="", anchor="w", font=Theme.font_caption(), text_color=Theme.TEXT_PRIMARY)
        self.message.pack(side="left", fill="x", expand=True, padx=Theme.SPACE_SM)
        self.category = ctk.CTkLabel(
            self,
            text="",
            font=Theme.font_micro(),
            text_color=Theme.TEXT_SECONDARY,
            fg_color=Theme.SURFACE_MUTED,
            corner_radius=Theme.RADIUS_PILL,
        )
        self.category.pack(side="right", padx=Theme.CARD_PAD_X)

    def update_event(self, event: Any) -> None:
        level = str(getattr(event, "level", "info"))
        color = {
            "success": Theme.STATUS_HEALTHY,
            "warning": Theme.STATUS_WARNING,
            "error": Theme.STATUS_ERROR,
        }.get(level, Theme.STATUS_INFO)
        self.time.configure(text=str(getattr(event, "timestamp", "Н/Д")))
        self.dot.configure(text_color=color)
        self.message.configure(text=str(getattr(event, "message", "Н/Д")))
        self.category.configure(text=f"  {getattr(event, 'category', 'system')}  ")


class LogsView(ctk.CTkFrame):
    def __init__(self, master: Any, **kwargs):
        super().__init__(master=master, fg_color="transparent", **kwargs)
        self._events: list[Any] = []
        self._rows: list[_LogRow] = []
        self._query = ""
        self._level = "Все уровни"
        SectionHeader(
            self,
            title="Журнал событий",
            subtitle="Реальные события Hermes Hub с уровнями и категориями",
        ).pack(fill="x", padx=Theme.PAGE_PAD_X, pady=(Theme.PAGE_PAD_Y, Theme.SPACE_SM))
        toolbar = ctk.CTkFrame(self, fg_color="transparent")
        toolbar.pack(fill="x", padx=Theme.PAGE_PAD_X, pady=(0, Theme.SPACE_SM))
        self.search = SearchField(toolbar, placeholder_text="Поиск по журналу…", width=320)
        self.search.pack(side="left", padx=(0, Theme.SPACE_SM))
        self.search.bind("<KeyRelease>", lambda _event: self._set_query(self.search.get()))
        self.level = FilterButton(
            toolbar,
            values=["Все уровни", "Информация", "Успех", "Предупреждение", "Ошибка"],
            command=self._set_level,
            width=170,
        )
        self.level.pack(side="left")
        self.scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.scroll.pack(fill="both", expand=True, padx=Theme.PAGE_PAD_X, pady=(0, Theme.PAGE_PAD_Y))
        self.empty = ctk.CTkLabel(
            self.scroll,
            text="События: Н/Д",
            font=Theme.font_caption(),
            text_color=Theme.TEXT_MUTED,
        )

    def _set_query(self, value: str) -> None:
        self._query = value.strip().lower()
        self._render()

    def _set_level(self, value: str) -> None:
        self._level = value
        self._render()

    def _filtered(self) -> list[Any]:
        levels = {
            "Информация": "info",
            "Успех": "success",
            "Предупреждение": "warning",
            "Ошибка": "error",
        }
        expected = levels.get(self._level)
        result = []
        for event in self._events:
            if expected and str(getattr(event, "level", "info")) != expected:
                continue
            haystack = f"{getattr(event, 'category', '')} {getattr(event, 'message', '')}".lower()
            if self._query and self._query not in haystack:
                continue
            result.append(event)
        return result

    def _render(self) -> None:
        events = self._filtered()
        while len(self._rows) < len(events):
            row = _LogRow(self.scroll)
            self._rows.append(row)
        for index, row in enumerate(self._rows):
            if index < len(events):
                row.update_event(events[index])
                row.pack(fill="x", pady=Theme.SPACE_XS)
            else:
                row.pack_forget()
        if events:
            self.empty.pack_forget()
        else:
            self.empty.pack(anchor="w", pady=Theme.SPACE_XL)

    def update_events(self, events: Iterable[Any]) -> None:
        self._events = list(events)
        self._render()

    def update_data(self, snapshot: Optional[HubSnapshot] = None) -> None:
        if not isinstance(snapshot, HubSnapshot):
            return
