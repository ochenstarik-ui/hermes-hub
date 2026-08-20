"""Hermes Hub — Accounts View with Reusable AccountCardWidget & Zero Widget Re-creation."""
from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional
import customtkinter as ctk

from antigravity_provider.router.ui.theme import Theme
from antigravity_provider.router.ui.assets import AssetManager
from antigravity_provider.router.ui.components import (
    HubButton,
    HubCard,
    HubToolbar,
)
from antigravity_provider.router.unified_health import (
    ProfileViewModel,
    STATUS_HEALTHY,
    STATUS_QUOTA_EXHAUSTED,
    STATUS_AUTH_REQUIRED,
    STATUS_NOT_CONFIGURED,
    STATUS_COLD_SPARE,
)
from antigravity_provider.router.quota_collector import AccountQuotaService
from antigravity_provider.router.state_store import HubStateStore, HubSnapshot
from antigravity_provider.router.scheduler import HermesRefreshScheduler
from antigravity_provider.router.event_bus import (
    EventBus,
    EVENT_ACCOUNT_UPDATED,
    EVENT_QUOTA_UPDATED,
)

logger = logging.getLogger("hermes.hub.accounts_view")


class AccountCardWidget(HubCard):
    """Reusable, updateable account card widget keyed by profile_id."""

    def __init__(
        self,
        parent: Any,
        profile: ProfileViewModel,
        quota_snapshot: Optional[Any] = None,
        on_action: Optional[Callable] = None,
        on_refresh: Optional[Callable] = None,
        **kwargs,
    ):
        border_col = Theme.BORDER_ACCENT if profile.is_main_account else Theme.BORDER
        super().__init__(parent, border_color=border_col, fg_color=Theme.SURFACE, **kwargs)
        self.profile = profile
        self.on_action = on_action
        self.on_refresh = on_refresh

        self._build()
        self.update_from_model(profile, quota_snapshot)

    def _build(self):
        # 1. Top row: icon + plan badge + main badge + status dot
        self.top_row = ctk.CTkFrame(self, fg_color="transparent")
        self.top_row.pack(fill="x", padx=14, pady=(12, 2))

        self.p_icon_lbl = ctk.CTkLabel(self.top_row, text="")
        self.p_icon_lbl.pack(side="left", padx=(0, 6))

        self.plan_frame = ctk.CTkFrame(self.top_row, fg_color=Theme.SURFACE_MUTED, corner_radius=Theme.RADIUS_SM)
        self.plan_frame.pack(side="left", padx=(0, 6))
        self.plan_lbl = ctk.CTkLabel(self.plan_frame, text="", font=Theme.font_micro_bold())
        self.plan_lbl.pack(padx=6, pady=2)

        self.main_pill = ctk.CTkFrame(self.top_row, fg_color="#3D3522", corner_radius=Theme.RADIUS_SM)
        self.main_lbl = ctk.CTkLabel(self.main_pill, text="★ MAIN", font=Theme.font_micro(), text_color=Theme.ACCENT)
        self.main_lbl.pack(padx=5, pady=1)

        self.status_dot = ctk.CTkLabel(self.top_row, text="●", font=("Segoe UI", 13, "bold"))
        self.status_dot.pack(side="right")

        # 2. Identity line
        self.ident_lbl = ctk.CTkLabel(self, text="", font=Theme.font_body_bold(), text_color=Theme.TEXT_PRIMARY)
        self.ident_lbl.pack(anchor="w", padx=14, pady=(2, 2))

        # 3. Subheader: display name + provider name
        self.sub_lbl = ctk.CTkLabel(self, text="", font=Theme.font_caption(), text_color=Theme.TEXT_MUTED)
        self.sub_lbl.pack(anchor="w", padx=14, pady=(0, 4))

        # 4. Quota Buckets Container
        self.quota_box = ctk.CTkFrame(self, fg_color=Theme.SURFACE_MUTED, corner_radius=Theme.RADIUS_SM)
        self.quota_box.pack(fill="x", padx=14, pady=4)

        # 5. Freshness text
        self.fresh_lbl = ctk.CTkLabel(self, text="", font=Theme.font_micro(), text_color=Theme.TEXT_MUTED)
        self.fresh_lbl.pack(anchor="w", padx=14, pady=(2, 2))

        # 6. Action buttons
        self.btns = ctk.CTkFrame(self, fg_color="transparent")
        self.btns.pack(fill="x", padx=14, pady=(4, 12))

        self.refresh_btn = HubButton(
            self.btns,
            text="↻",
            variant="secondary",
            width=32,
            height=Theme.HEIGHT_BTN_SM,
            command=self._on_single_refresh,
        )
        self.refresh_btn.pack(side="left", padx=(0, 6))

        self.test_btn = HubButton(
            self.btns,
            text="⚡ Тест",
            variant="secondary",
            width=65,
            height=Theme.HEIGHT_BTN_SM,
            command=lambda: self._trigger("test"),
        )
        self.test_btn.pack(side="left", padx=(0, 6))

        self.assign_btn = HubButton(
            self.btns,
            text="Назначить",
            variant="secondary",
            width=80,
            height=Theme.HEIGHT_BTN_SM,
            command=lambda: self._trigger("assign_role"),
        )
        self.assign_btn.pack(side="left", padx=(0, 6))

    def _trigger(self, action: str):
        if self.on_action:
            self.on_action(action, self.profile)

    def _on_single_refresh(self):
        if self.on_refresh:
            self.on_refresh(self.profile.provider, self.profile.profile_id)

    def update_from_model(self, p: ProfileViewModel, quota_snap: Optional[Any] = None) -> None:
        """Update existing card properties in-place without destroying widgets."""
        self.profile = p

        # Border color for main
        if p.is_main_account:
            self.configure(border_color=Theme.BORDER_ACCENT)
            if not self.main_pill.winfo_ismapped():
                self.main_pill.pack(side="left", padx=(0, 6))
        else:
            self.configure(border_color=Theme.BORDER)
            if self.main_pill.winfo_ismapped():
                self.main_pill.pack_forget()

        # Provider icon
        p_img = AssetManager.get().get_provider_image(p.provider, size=(20, 20))
        if p_img:
            self.p_icon_lbl.configure(image=p_img)

        # Plan badge
        plan_color = "#3b82f6" if p.plan_code in ("PRO", "PLUS", "MAX") else ("#10b981" if p.plan_code in ("ULTRA", "SUPERGROK", "TEAM") else Theme.TEXT_MUTED)
        self.plan_lbl.configure(text=p.plan, text_color=plan_color)

        # Status dot
        dot_col = Theme.STATUS_HEALTHY if p.health_state == STATUS_HEALTHY else (
            Theme.STATUS_WARNING if "quota" in p.health_state or "auth" in p.health_state else Theme.STATUS_ERROR
        )
        self.status_dot.configure(text_color=dot_col)

        # Identity & Subheader
        self.ident_lbl.configure(text=p.account_identity)
        self.sub_lbl.configure(text=f"{p.display_name} • {p.provider_display_name}")

        # Quota Buckets
        snap = quota_snap or p.quota_snapshot or AccountQuotaService.get().get_snapshot(p.provider, p.profile_id)
        for child in self.quota_box.winfo_children():
            child.destroy()

        is_estimated = getattr(snap, "is_estimated", True) if snap else True
        if snap and getattr(snap, "buckets", None):
            for b in snap.buckets[:4]:
                brow = ctk.CTkFrame(self.quota_box, fg_color="transparent")
                brow.pack(fill="x", padx=8, pady=2)
                disp_name = f"{b.display_name} (оценка)" if is_estimated else b.display_name
                ctk.CTkLabel(brow, text=disp_name, font=Theme.font_caption(), text_color=Theme.TEXT_PRIMARY).pack(side="left")

                b_status_col = Theme.STATUS_HEALTHY if b.status == "healthy" else (Theme.STATUS_WARNING if b.status == "warning" else Theme.STATUS_ERROR)
                reset_text = f" ({b.formatted_reset()})" if b.formatted_reset() else ""
                rem_text = f"{b.formatted_remaining()}{reset_text}"
                ctk.CTkLabel(brow, text=rem_text, font=Theme.font_micro(), text_color=b_status_col).pack(side="right")
        else:
            ctk.CTkLabel(self.quota_box, text="Квота: доступна (оценка)", font=Theme.font_caption(), text_color=Theme.TEXT_MUTED).pack(padx=8, pady=4)

        # Freshness label
        fresh_lbl_text = snap.freshness_label() if (snap and hasattr(snap, "freshness_label")) else "Обновлено: недавно"
        if is_estimated:
            fresh_lbl_text += " • оценка"
        self.fresh_lbl.configure(text=fresh_lbl_text)


class AccountsView(ctk.CTkFrame):
    """Native Windows CustomTkinter view for multi-provider accounts with widget reuse."""

    def __init__(self, master: Any, app_state: Dict[str, Any], on_action: Optional[Callable] = None, **kwargs):
        super().__init__(master=master, fg_color="transparent", **kwargs)
        self.app_state = app_state
        self.on_action = on_action
        self._search_query = ""
        self._filter_status = "Все статусы"
        self._sort_by = "По умолчанию"

        self._cards: Dict[str, AccountCardWidget] = {}
        self._empty_cards: Dict[str, HubCard] = {}
        self._last_rendered_generation = 0

        self._build()
        self._subscribe_events()

    def _subscribe_events(self):
        bus = EventBus.get()
        bus.subscribe(EVENT_ACCOUNT_UPDATED, self._on_account_updated_event)
        bus.subscribe(EVENT_QUOTA_UPDATED, self._on_quota_updated_event)

    def _on_account_updated_event(self, event_name: str, payload: Any):
        if isinstance(payload, dict):
            pid = payload.get("profile_id")
            prof = payload.get("profile")
            if pid and prof and pid in self._cards:
                self.after(0, lambda: self._cards[pid].update_from_model(prof))

    def _on_quota_updated_event(self, event_name: str, payload: Any):
        if isinstance(payload, dict):
            pid = payload.get("profile_id")
            quota_snap = payload.get("quota_snapshot")
            if pid and pid in self._cards:
                p = self._cards[pid].profile
                self.after(0, lambda: self._cards[pid].update_from_model(p, quota_snap))

    def _build(self):
        # 1. Header with Refresh All and Add Account buttons
        header_row = ctk.CTkFrame(self, fg_color="transparent")
        header_row.pack(fill="x", padx=20, pady=(16, 8))

        titles_col = ctk.CTkFrame(header_row, fg_color="transparent")
        titles_col.pack(side="left", fill="both", expand=True)

        ctk.CTkLabel(
            titles_col,
            text="Управление аккаунтами",
            font=Theme.font_title(),
            text_color=Theme.TEXT_PRIMARY,
            anchor="w",
        ).pack(fill="x")

        ctk.CTkLabel(
            titles_col,
            text="Подключение, мониторинг тарифов и раздельных квот провайдеров",
            font=Theme.font_caption(),
            text_color=Theme.TEXT_SECONDARY,
            anchor="w",
        ).pack(fill="x", pady=(2, 0))

        actions_col = ctk.CTkFrame(header_row, fg_color="transparent")
        actions_col.pack(side="right")

        self.refresh_all_btn = HubButton(
            actions_col,
            text="↻ Обновить все",
            variant="secondary",
            height=Theme.HEIGHT_BTN_MD,
            command=self._refresh_all_quotas,
        )
        self.refresh_all_btn.pack(side="left", padx=(0, 8))

        HubButton(
            actions_col,
            text="+ Добавить аккаунт",
            variant="primary",
            height=Theme.HEIGHT_BTN_MD,
            command=lambda: self._trigger_action("add_account", {}),
        ).pack(side="left")

        # 2. Cockpit Toolbar
        self.toolbar = HubToolbar(
            self,
            on_search=self._on_search,
            on_filter=self._on_filter,
            on_sort=self._on_sort,
        )
        self.toolbar.pack(fill="x", padx=20, pady=(0, 10))

        # 3. Provider Tabs
        self.tabview = ctk.CTkTabview(
            self,
            fg_color=Theme.BG_WINDOW,
            segmented_button_fg_color=Theme.BG_SIDEBAR,
            segmented_button_selected_color=Theme.SECONDARY,
            segmented_button_selected_hover_color=Theme.SURFACE_HOVER,
            segmented_button_unselected_color=Theme.BG_SIDEBAR,
            segmented_button_unselected_hover_color=Theme.SURFACE_HOVER,
            text_color=Theme.TEXT_PRIMARY,
        )
        self.tabview.pack(fill="both", expand=True, padx=15, pady=(0, 10))

        provider_tabs = [
            ("antigravity", "Google Antigravity"),
            ("openai-codex", "OpenAI Codex"),
            ("opencode-go", "OpenCode Go"),
            ("claude", "Claude"),
            ("grok", "Grok"),
        ]

        self.tab_scrolls: Dict[str, ctk.CTkScrollableFrame] = {}

        for p_key, p_label in provider_tabs:
            tab = self.tabview.add(p_label)
            scroll = ctk.CTkScrollableFrame(tab, fg_color="transparent")
            scroll.pack(fill="both", expand=True, padx=4, pady=4)
            for c in range(3):
                scroll.grid_columnconfigure(c, weight=1)
            self.tab_scrolls[p_key] = scroll

        self.update_data()

    def _trigger_action(self, action: str, data: Any):
        if self.on_action:
            self.on_action(action, data)

    def _refresh_all_quotas(self):
        self.refresh_all_btn.configure(text="↻ Обновление...", state="disabled")
        def _done():
            def _ui():
                self.refresh_all_btn.configure(text="↻ Обновить все", state="normal")
                self.update_data()
            self.after(0, _ui)
        HermesRefreshScheduler.get().trigger_refresh_all(on_complete=_done)

    def _refresh_single_account(self, provider: str, profile_id: str):
        HermesRefreshScheduler.get().trigger_refresh_account(
            provider, profile_id, on_complete=lambda: self.after(0, self.update_data)
        )

    def _on_search(self, query: str):
        self._search_query = query
        self.update_data()

    def _on_filter(self, filter_val: str):
        self._filter_status = filter_val
        self.update_data()

    def _on_sort(self, sort_val: str):
        self._sort_by = sort_val
        self.update_data()

    def update_data(self, snapshot: Optional[HubSnapshot] = None):
        """Update views by reusing widgets and updating properties in place."""
        if snapshot is None:
            snapshot = HubStateStore.get().get_snapshot()

        self._last_rendered_generation = snapshot.generation
        profiles_by_prov = snapshot.profiles_by_provider

        for prov_key, scroll in self.tab_scrolls.items():
            profiles = profiles_by_prov.get(prov_key, [])

            # Filter
            filtered: List[ProfileViewModel] = []
            for p in profiles:
                if self._search_query:
                    q = self._search_query.lower()
                    matches = (
                        q in p.account_identity.lower()
                        or q in p.display_name.lower()
                        or q in p.plan.lower()
                        or any(q in m.lower() for m in p.preferred_models)
                        or any(q in r.lower() for r in p.assigned_roles)
                    )
                    if not matches:
                        continue

                if self._filter_status == "Подключённые" and p.auth_state != "AUTHENTICATED":
                    continue
                elif self._filter_status == "Требуют входа" and p.auth_state == "AUTHENTICATED":
                    continue
                elif self._filter_status == "Квота исчерпана" and "quota" not in p.health_state:
                    continue

                filtered.append(p)

            if self._sort_by == "По имени":
                filtered.sort(key=lambda x: x.display_name)
            elif self._sort_by == "По статусу":
                filtered.sort(key=lambda x: x.health_state)

            configured_profs = [p for p in filtered if not p.is_empty_slot]
            empty_profs = [p for p in filtered if p.is_empty_slot]

            # Reusable placement
            grid_idx = 0
            for p in configured_profs:
                row_idx, col_idx = divmod(grid_idx, 3)
                q_snap = snapshot.quotas.get(p.profile_id)

                if p.profile_id in self._cards:
                    card = self._cards[p.profile_id]
                    card.update_from_model(p, q_snap)
                else:
                    card = AccountCardWidget(
                        scroll,
                        profile=p,
                        quota_snapshot=q_snap,
                        on_action=self._trigger_action,
                        on_refresh=self._refresh_single_account,
                    )
                    self._cards[p.profile_id] = card

                card.grid(row=row_idx, column=col_idx, padx=6, pady=6, sticky="nsew")
                grid_idx += 1

            # Empty slots summary card
            if empty_profs:
                c_row = (grid_idx // 3) + 1
                slot_key = f"empty_{prov_key}"
                if slot_key not in self._empty_cards:
                    summary_card = HubCard(scroll, border_color=Theme.BORDER_SUBTLE, fg_color=Theme.SURFACE_MUTED)
                    s_inner = ctk.CTkFrame(summary_card, fg_color="transparent")
                    s_inner.pack(fill="x", padx=16, pady=12)

                    lbl = ctk.CTkLabel(
                        s_inner,
                        text=f"Свободные слоты: {len(empty_profs)} слотов доступно",
                        font=Theme.font_body_bold(),
                        text_color=Theme.TEXT_SECONDARY,
                    )
                    lbl.pack(side="left")

                    HubButton(
                        s_inner,
                        text="+ Подключить аккаунт",
                        variant="primary",
                        height=Theme.HEIGHT_BTN_SM,
                        command=lambda k=prov_key: self._trigger_action("add_account", {"provider": k}),
                    ).pack(side="right")

                    self._empty_cards[slot_key] = summary_card
                else:
                    summary_card = self._empty_cards[slot_key]

                summary_card.grid(row=c_row, column=0, columnspan=3, padx=6, pady=10, sticky="ew")
