"""Truthful multi-bucket quota overview driven by HubSnapshot."""

from __future__ import annotations

from typing import Any, Dict, Optional

import customtkinter as ctk

from antigravity_provider.router.state_store import HubSnapshot
from antigravity_provider.router.ui.components import EmptyState, HubCard, QuotaBar, SectionHeader
from antigravity_provider.router.ui.theme import Theme


class _QuotaRow(HubCard):
    def __init__(self, master: Any):
        super().__init__(master, corner_radius=Theme.RADIUS_SM)
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=Theme.CARD_PAD_X, pady=(Theme.CARD_PAD_Y, Theme.SPACE_XS))
        self.title = ctk.CTkLabel(header, text="", font=Theme.font_body_bold(), text_color=Theme.TEXT_PRIMARY)
        self.title.pack(side="left")
        self.source = ctk.CTkLabel(header, text="", font=Theme.font_micro(), text_color=Theme.TEXT_MUTED)
        self.source.pack(side="right")
        self.identity = ctk.CTkLabel(self, text="", font=Theme.font_caption(), text_color=Theme.TEXT_SECONDARY)
        self.identity.pack(anchor="w", padx=Theme.CARD_PAD_X)
        self.bar = QuotaBar(self, label="Остаток")
        self.bar.pack(fill="x", padx=Theme.CARD_PAD_X, pady=Theme.SPACE_SM)
        self.reset = ctk.CTkLabel(self, text="", font=Theme.font_micro(), text_color=Theme.TEXT_MUTED)
        self.reset.pack(anchor="w", padx=Theme.CARD_PAD_X, pady=(0, Theme.CARD_PAD_Y))

    def update_bucket(self, profile: Any, quota: Any, bucket: Any) -> None:
        remaining = getattr(bucket, "remaining_percent", None)
        ratio = float(remaining) / 100.0 if remaining is not None else None
        detail = bucket.formatted_remaining() if hasattr(bucket, "formatted_remaining") else "Н/Д"
        reset = bucket.formatted_reset() if hasattr(bucket, "formatted_reset") else None
        estimated = bool(getattr(quota, "is_estimated", True))
        self.title.configure(text=f"{bucket.display_name} • {profile.provider_display_name}")
        self.identity.configure(text=profile.account_identity or profile.display_name)
        self.source.configure(text="оценка" if estimated else str(getattr(quota, "source", "измерено")))
        self.bar.set_value(ratio, detail)
        reason = getattr(quota, "unavailable_reason", None)
        self.reset.configure(text=reason or reset or "Сброс: Н/Д")


class QuotasView(ctk.CTkFrame):
    def __init__(self, master: Any, **kwargs):
        super().__init__(master=master, fg_color="transparent", **kwargs)
        self._rows: Dict[str, _QuotaRow] = {}
        SectionHeader(
            self,
            title="Квоты и лимиты",
            subtitle="Независимые корзины провайдеров; отсутствие измерения не считается нулём",
        ).pack(fill="x", padx=Theme.PAGE_PAD_X, pady=(Theme.PAGE_PAD_Y, Theme.SPACE_SM))
        self.scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.scroll.pack(fill="both", expand=True, padx=Theme.PAGE_PAD_X, pady=(0, Theme.PAGE_PAD_Y))
        self.empty = EmptyState(
            self.scroll,
            title="Квоты: Н/Д",
            message="Провайдеры ещё не опубликовали ни одной квотной корзины.",
        )

    def update_data(self, snapshot: Optional[HubSnapshot] = None) -> None:
        if not isinstance(snapshot, HubSnapshot):
            return
        incoming: list[tuple[str, Any, Any, Any]] = []
        for profile in snapshot.all_profiles.values():
            quota = snapshot.quotas.get(profile.profile_id)
            for bucket in list(getattr(quota, "buckets", None) or []):
                incoming.append((f"{profile.profile_id}:{bucket.id}", profile, quota, bucket))
        live = {key for key, *_rest in incoming}
        for key in list(self._rows):
            if key not in live:
                self._rows.pop(key).destroy()
        for key, profile, quota, bucket in incoming:
            row = self._rows.get(key)
            if row is None:
                row = _QuotaRow(self.scroll)
                row.pack(fill="x", pady=Theme.SPACE_XS)
                self._rows[key] = row
            row.update_bucket(profile, quota, bucket)
        if incoming:
            self.empty.pack_forget()
        else:
            self.empty.pack(fill="x", pady=Theme.SPACE_XL)
