"""Keyed system-health view using only the supplied snapshot."""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional

import customtkinter as ctk

from antigravity_provider.router.state_store import HubSnapshot
from antigravity_provider.router.ui.components import HubCard, SectionHeader, StatusBadge
from antigravity_provider.router.ui.theme import Theme


class HealthProfileRow(HubCard):
    def __init__(self, master: Any):
        super().__init__(master, corner_radius=Theme.RADIUS_SM, border_color=Theme.BORDER_SUBTLE)
        self.identity = ctk.CTkLabel(self, text="", font=Theme.font_body_bold(), text_color=Theme.TEXT_PRIMARY)
        self.identity.grid(row=0, column=0, padx=Theme.CARD_PAD_X, pady=Theme.SPACE_SM, sticky="w")
        self.models = ctk.CTkLabel(self, text="", font=Theme.font_caption(), text_color=Theme.TEXT_MUTED)
        self.models.grid(row=0, column=1, padx=Theme.CARD_PAD_X, pady=Theme.SPACE_SM, sticky="w")
        self.status = StatusBadge(self, "not_tested")
        self.status.grid(row=0, column=2, padx=Theme.CARD_PAD_X, pady=Theme.SPACE_SM, sticky="e")
        self.grid_columnconfigure(0, weight=2)
        self.grid_columnconfigure(1, weight=3)
        self.grid_columnconfigure(2, weight=1)

    def update_profile(self, profile: Any) -> None:
        identity = profile.email or profile.account_identity or profile.profile_id
        self.identity.configure(text=f"{identity}\n{profile.profile_id}")
        families = (
            ", ".join(f"{family}: {state.status_label_ru}" for family, state in profile.model_states.items())
            or "Семейства моделей: Н/Д"
        )
        self.models.configure(text=families)
        self.status.set_status(profile.health_state, profile.health_label_ru)


class HealthView(ctk.CTkFrame):
    def __init__(
        self, master: Any, app_state: Optional[Dict[str, Any]] = None, on_refresh: Optional[Callable] = None, **kwargs
    ):
        super().__init__(master=master, fg_color="transparent", **kwargs)
        self._rows: Dict[str, HealthProfileRow] = {}
        SectionHeader(
            self,
            title="Состояние системы",
            subtitle="Авторизация, локальное здоровье и наблюдаемые состояния моделей",
            action_text="Обновить аудит",
            action_cmd=on_refresh,
        ).pack(fill="x", padx=Theme.PAGE_PAD_X, pady=(Theme.PAGE_PAD_Y, Theme.SPACE_SM))
        self.scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.scroll.pack(fill="both", expand=True, padx=Theme.PAGE_PAD_X, pady=(0, Theme.PAGE_PAD_Y))
        self.banner = HubCard(self.scroll, border_color=Theme.BORDER_ACCENT, fg_color=Theme.DARK)
        self.banner.pack(fill="x", pady=(0, Theme.SECTION_GAP))
        self.title = ctk.CTkLabel(
            self.banner, text="Ожидание snapshot", font=Theme.font_heading(), text_color=Theme.TEXT_ACCENT
        )
        self.title.pack(anchor="w", padx=Theme.CARD_PAD_X, pady=(Theme.CARD_PAD_Y, Theme.SPACE_XS))
        self.summary = ctk.CTkLabel(self.banner, text="", font=Theme.font_body(), text_color=Theme.TEXT_SECONDARY)
        self.summary.pack(anchor="w", padx=Theme.CARD_PAD_X, pady=(0, Theme.CARD_PAD_Y))
        self.rows = ctk.CTkFrame(self.scroll, fg_color="transparent")
        self.rows.pack(fill="x")

    def update_data(self, snapshot: Optional[HubSnapshot] = None) -> None:
        if not isinstance(snapshot, HubSnapshot):
            return
        readiness = snapshot.readiness
        self.title.configure(text=readiness.title_ru)
        warnings = " • ".join(readiness.warnings) if readiness.warnings else "Предупреждений нет"
        self.summary.configure(
            text=(
                f"{readiness.summary_ru}\n"
                f"Аккаунты {readiness.accounts_connected_count}/{readiness.total_accounts} • "
                f"Роли {readiness.roles_ready_count}/{readiness.total_roles} • {warnings}"
            )
        )
        live = set(snapshot.all_profiles)
        for profile_id in list(self._rows):
            if profile_id not in live:
                self._rows.pop(profile_id).destroy()
        ordered = sorted(snapshot.all_profiles.values(), key=lambda profile: (profile.provider, profile.display_name))
        for index, profile in enumerate(ordered):
            row = self._rows.get(profile.profile_id)
            if row is None:
                row = HealthProfileRow(self.rows)
                self._rows[profile.profile_id] = row
            row.update_profile(profile)
            row.grid(row=index, column=0, sticky="ew", pady=Theme.SPACE_XS)
        self.rows.grid_columnconfigure(0, weight=1)
