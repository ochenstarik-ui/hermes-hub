"""Accounts and quota view driven exclusively by a supplied HubSnapshot."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Callable, Dict, Iterable, Optional

import customtkinter as ctk

from antigravity_provider.router.state_store import HubSnapshot
from antigravity_provider.router.ui.components import (
    AccountCardWidget,
    ActionButton,
    EmptyState,
    FilterButton,
    SearchField,
    SectionHeader,
)
from antigravity_provider.router.ui.theme import Theme


PROVIDER_LABELS = {
    "antigravity": "Google Antigravity",
    "openai-codex": "OpenAI Codex",
    "opencode-go": "OpenCode Go",
    "claude": "Claude",
    "grok": "Grok",
}


class ProviderGroup(ctk.CTkFrame):
    """Collapsible provider section that retains its account cards while hidden."""

    def __init__(self, master: Any, provider: str):
        super().__init__(master, fg_color="transparent")
        self.provider = provider
        self.collapsed = False
        self.header = ctk.CTkFrame(self, fg_color=Theme.BG_HEADER, corner_radius=Theme.RADIUS_SM)
        self.header.pack(fill="x", pady=(Theme.SPACE_SM, Theme.SPACE_XS))
        self.toggle = ActionButton(
            self.header,
            text="▾",
            variant="ghost",
            width=34,
            command=self.toggle_collapsed,
        )
        self.toggle.pack(side="left", padx=(Theme.SPACE_SM, 0))
        self.title = ctk.CTkLabel(
            self.header,
            text=PROVIDER_LABELS.get(provider, provider),
            font=Theme.font_heading(),
            text_color=Theme.TEXT_PRIMARY,
        )
        self.title.pack(side="left", padx=Theme.SPACE_SM, pady=Theme.SPACE_SM)
        self.count = ctk.CTkLabel(self.header, text="0", font=Theme.font_caption(), text_color=Theme.TEXT_MUTED)
        self.count.pack(side="right", padx=Theme.SPACE_MD)
        self.body = ctk.CTkFrame(self, fg_color="transparent")
        self.body.pack(fill="x")
        for column in range(Theme.ACCOUNT_CARD_COLUMNS):
            self.body.grid_columnconfigure(column, weight=1)

    def toggle_collapsed(self) -> None:
        self.collapsed = not self.collapsed
        self.toggle.configure(text="▸" if self.collapsed else "▾")
        if self.collapsed:
            self.body.pack_forget()
        else:
            self.body.pack(fill="x")


class AccountsView(ctk.CTkFrame):
    """Keyed accounts view; one account delta never reconstructs another card."""

    def __init__(
        self, master: Any, app_state: Optional[Dict[str, Any]] = None, on_action: Optional[Callable] = None, **kwargs
    ):
        super().__init__(master=master, fg_color="transparent", **kwargs)
        self.on_action = on_action
        self._snapshot: Optional[HubSnapshot] = None
        self._cards: Dict[str, AccountCardWidget] = {}
        self._groups: Dict[str, ProviderGroup] = {}
        self._search = ""
        self._provider_filter = "Все провайдеры"
        self._health_filter = "Все состояния"
        self._role_filter = "Все роли"
        self.cards_created = 0
        self.cards_destroyed = 0
        self._build()

    def _build(self) -> None:
        header = SectionHeader(
            self,
            title="Аккаунты и квоты",
            subtitle="Реальные идентичности, независимые лимитные корзины и резервные роли",
            action_text="+ Добавить аккаунт",
            action_cmd=lambda: self._emit("add_account", {}),
        )
        header.pack(fill="x", padx=Theme.PAGE_PAD_X, pady=(Theme.PAGE_PAD_Y, Theme.SPACE_SM))

        toolbar = ctk.CTkFrame(self, fg_color="transparent")
        toolbar.pack(fill="x", padx=Theme.PAGE_PAD_X, pady=(0, Theme.SPACE_SM))
        self.search = SearchField(toolbar, placeholder_text="Поиск по аккаунту, модели или роли…", width=300)
        self.search.pack(side="left", padx=(0, Theme.SPACE_SM))
        self.search.bind("<KeyRelease>", lambda _event: self._set_search(self.search.get()))
        self.provider_filter = FilterButton(
            toolbar,
            values=["Все провайдеры", *PROVIDER_LABELS.values()],
            command=self._set_provider_filter,
            width=170,
        )
        self.provider_filter.pack(side="left", padx=(0, Theme.SPACE_SM))
        self.health_filter = FilterButton(
            toolbar,
            values=["Все состояния", "Работают", "Требуют входа", "Проблемные"],
            command=self._set_health_filter,
            width=150,
        )
        self.health_filter.pack(side="left", padx=(0, Theme.SPACE_SM))
        self.role_filter = FilterButton(
            toolbar,
            values=["Все роли", "orchestrator", "coder", "reviewer", "researcher", "tester", "general", "spare"],
            command=self._set_role_filter,
            width=135,
        )
        self.role_filter.pack(side="left")
        ActionButton(
            toolbar,
            text="Обновить все",
            variant="secondary",
            command=lambda: self._emit("refresh_all", {}),
        ).pack(side="right")

        self.scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.scroll.pack(fill="both", expand=True, padx=Theme.PAGE_PAD_X, pady=(0, Theme.PAGE_PAD_Y))
        self.empty = EmptyState(
            self.scroll,
            title="Нет подходящих аккаунтов",
            message="Измените фильтры или подключите новый аккаунт.",
            action_text="Подключить аккаунт",
            action_cmd=lambda: self._emit("add_account", {}),
        )

    def _emit(self, action: str, profile: Any) -> None:
        if not self.on_action:
            return
        if isinstance(profile, dict):
            payload = profile
        else:
            payload = {
                "profile_id": profile.profile_id,
                "provider": profile.provider,
                "display_name": profile.display_name,
            }
        self.on_action(action, payload)

    def _set_search(self, value: str) -> None:
        self._search = value.strip().lower()
        self._render_visibility()

    def _set_provider_filter(self, value: str) -> None:
        self._provider_filter = value
        self._render_visibility()

    def _set_health_filter(self, value: str) -> None:
        self._health_filter = value
        self._render_visibility()

    def _set_role_filter(self, value: str) -> None:
        self._role_filter = value
        self._render_visibility()

    def _matches(self, profile: Any) -> bool:
        if self._provider_filter != "Все провайдеры":
            if PROVIDER_LABELS.get(profile.provider, profile.provider) != self._provider_filter:
                return False
        if self._health_filter == "Работают" and profile.health_state != "healthy":
            return False
        if self._health_filter == "Требуют входа" and profile.auth_state not in {"AUTH_REQUIRED", "AUTH_EXPIRED"}:
            return False
        if self._health_filter == "Проблемные" and profile.health_state in {"healthy", "not_configured", "cold_spare"}:
            return False
        roles = list(getattr(profile, "assigned_roles", []) or [])
        if self._role_filter != "Все роли" and not any(self._role_filter.lower() in role.lower() for role in roles):
            return False
        haystack = " ".join(
            [
                AccountCardWidget.resolve_identity(profile),
                profile.display_name,
                profile.provider_display_name,
                *roles,
                *(getattr(profile, "preferred_models", []) or []),
            ]
        ).lower()
        return not self._search or self._search in haystack

    def _profiles(self) -> Iterable[Any]:
        if not self._snapshot:
            return []
        return (profile for profile in self._snapshot.all_profiles.values() if not profile.is_empty_slot)

    def update_data(self, snapshot: Optional[HubSnapshot] = None) -> None:
        if not isinstance(snapshot, HubSnapshot):
            return
        self._snapshot = snapshot
        live_ids = {profile.profile_id for profile in self._profiles()}
        collapse_new_collection = len(self._cards) <= 1 and len(live_ids) > 1
        for profile_id in list(self._cards):
            if profile_id not in live_ids:
                self._cards.pop(profile_id).destroy()
                self.cards_destroyed += 1

        for profile in self._profiles():
            group = self._groups.get(profile.provider)
            if group is None:
                group = ProviderGroup(self.scroll, profile.provider)
                self._groups[profile.provider] = group
            card = self._cards.get(profile.profile_id)
            if card is None:
                card = AccountCardWidget(
                    group.body,
                    profile.profile_id,
                    AccountCardWidget.resolve_identity(profile),
                    profile.provider_display_name,
                    compact=len(live_ids) > 1,
                    on_action=self._emit,
                )
                self._cards[profile.profile_id] = card
                self.cards_created += 1
            card.update_account(profile, snapshot.quotas.get(profile.profile_id))
        if collapse_new_collection:
            for card in self._cards.values():
                card.set_compact(True)
        self._render_visibility()

    def _render_visibility(self) -> None:
        if not self._snapshot:
            self.empty.pack(fill="x", pady=Theme.SPACE_XL)
            return
        grouped: Dict[str, list[Any]] = defaultdict(list)
        for profile in self._profiles():
            if self._matches(profile):
                grouped[profile.provider].append(profile)
        visible_total = 0
        for provider, group in self._groups.items():
            profiles = grouped.get(provider, [])
            if not profiles:
                group.pack_forget()
                continue
            group.pack(fill="x")
            group.count.configure(text=f"{len(profiles)} аккаунт(а)")
            for card in self._cards.values():
                if card.profile_model and card.profile_model.provider == provider:
                    card.grid_remove()
            for index, profile in enumerate(profiles):
                self._cards[profile.profile_id].grid(
                    row=index // Theme.ACCOUNT_CARD_COLUMNS,
                    column=index % Theme.ACCOUNT_CARD_COLUMNS,
                    padx=Theme.SPACE_XS,
                    pady=Theme.SPACE_XS,
                    sticky="nsew",
                )
            visible_total += len(profiles)
        if visible_total:
            self.empty.pack_forget()
        else:
            self.empty.pack(fill="x", pady=Theme.SPACE_XL)

    def render_stats(self) -> Dict[str, int]:
        return {
            "cards_created": self.cards_created,
            "cards_destroyed": self.cards_destroyed,
            "quota_widgets_created": sum(card.widgets_created for card in self._cards.values()),
            "quota_widgets_destroyed": sum(card.widgets_destroyed for card in self._cards.values()),
        }

    def show_action_result(self, profile_id: str, message: str, success: Optional[bool]) -> bool:
        """Keep account action feedback next to the originating controls."""
        card = self._cards.get(profile_id)
        if card is None:
            return False
        card.set_action_feedback(message, success)
        return True
