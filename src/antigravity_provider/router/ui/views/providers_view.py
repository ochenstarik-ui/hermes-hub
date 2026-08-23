"""Provider summaries updated by stable provider id."""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional

import customtkinter as ctk

from antigravity_provider.router.state_store import HubSnapshot
from antigravity_provider.router.ui.components import HubCard, SectionHeader
from antigravity_provider.router.ui.theme import Theme


class ProviderCard(HubCard):
    def __init__(self, master: Any):
        super().__init__(master)
        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", padx=Theme.CARD_PAD_X, pady=(Theme.CARD_PAD_Y, Theme.SPACE_SM))
        self.title = ctk.CTkLabel(top, text="", font=Theme.font_heading(), text_color=Theme.TEXT_PRIMARY)
        self.title.pack(side="left")
        self.updated = ctk.CTkLabel(top, text="", font=Theme.font_micro(), text_color=Theme.TEXT_MUTED)
        self.updated.pack(side="right")
        self.stats = ctk.CTkLabel(self, text="", font=Theme.font_body(), text_color=Theme.TEXT_SECONDARY)
        self.stats.pack(anchor="w", padx=Theme.CARD_PAD_X)
        self.models = ctk.CTkLabel(
            self,
            text="",
            font=Theme.font_mono_sm(),
            text_color=Theme.TEXT_PRIMARY,
            wraplength=900,
            justify="left",
        )
        self.models.pack(anchor="w", padx=Theme.CARD_PAD_X, pady=(Theme.SPACE_SM, Theme.CARD_PAD_Y))

    def update_provider(self, summary: Any) -> None:
        self.title.configure(text=summary.provider_name)
        self.updated.configure(text=f"Обновлено: {summary.last_refresh_at or 'Н/Д — обнаружение ещё не запускалось'}")
        self.stats.configure(
            text=(
                f"Онлайн {summary.online_count}/{summary.connected_count} • "
                f"требуют входа {summary.auth_required_count} • "
                f"квота исчерпана {summary.quota_exhausted_count} • "
                f"холодный резерв {summary.cold_spare_count}"
            )
        )
        self.models.configure(
            text="Модели: "
            + (
                " • ".join(summary.discovered_models)
                if summary.discovered_models
                else "Н/Д — список моделей ещё не получен"
            )
        )


class ProvidersView(ctk.CTkFrame):
    def __init__(
        self, master: Any, app_state: Optional[Dict[str, Any]] = None, on_action: Optional[Callable] = None, **kwargs
    ):
        super().__init__(master=master, fg_color="transparent", **kwargs)
        self.on_action = on_action
        self._cards: Dict[str, ProviderCard] = {}
        SectionHeader(
            self,
            title="Провайдеры и модели",
            subtitle="Локальная доступность адаптеров и реально обнаруженные модели",
            action_text="Обновить",
            action_cmd=lambda: self.on_action and self.on_action("refresh_data", {}),
        ).pack(fill="x", padx=Theme.PAGE_PAD_X, pady=(Theme.PAGE_PAD_Y, Theme.SPACE_SM))
        self.scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.scroll.pack(fill="both", expand=True, padx=Theme.PAGE_PAD_X, pady=(0, Theme.PAGE_PAD_Y))

    def update_data(self, snapshot: Optional[HubSnapshot] = None) -> None:
        if not isinstance(snapshot, HubSnapshot):
            return
        live = {summary.provider_id for summary in snapshot.providers}
        for provider_id in list(self._cards):
            if provider_id not in live:
                self._cards.pop(provider_id).destroy()
        for summary in snapshot.providers:
            card = self._cards.get(summary.provider_id)
            if card is None:
                card = ProviderCard(self.scroll)
                card.pack(fill="x", pady=Theme.SPACE_XS)
                self._cards[summary.provider_id] = card
            card.update_provider(summary)
