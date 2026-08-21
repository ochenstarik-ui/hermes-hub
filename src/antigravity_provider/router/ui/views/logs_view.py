"""Event-log screen with honest handling of the current snapshot contract gap."""

from __future__ import annotations

from typing import Any, Optional

import customtkinter as ctk

from antigravity_provider.router.state_store import HubSnapshot
from antigravity_provider.router.ui.components import EmptyState, SectionHeader
from antigravity_provider.router.ui.theme import Theme


class LogsView(ctk.CTkFrame):
    def __init__(self, master: Any, **kwargs):
        super().__init__(master=master, fg_color="transparent", **kwargs)
        SectionHeader(
            self,
            title="Журнал событий",
            subtitle="Только события, переданные через единый snapshot-контракт",
        ).pack(fill="x", padx=Theme.PAGE_PAD_X, pady=(Theme.PAGE_PAD_Y, Theme.SPACE_SM))
        self.empty = EmptyState(
            self,
            title="Журнал: Н/Д",
            message=(
                "HubSnapshot пока не содержит события журнала. Экран не читает файлы и backend "
                "напрямую и не показывает выдуманную историю."
            ),
        )
        self.empty.pack(fill="x", padx=Theme.PAGE_PAD_X, pady=Theme.SPACE_XL)

    def update_data(self, snapshot: Optional[HubSnapshot] = None) -> None:
        if not isinstance(snapshot, HubSnapshot):
            return
