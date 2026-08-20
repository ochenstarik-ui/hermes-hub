"""Hermes Hub — Accounts View (Multi-Provider Quota Cards, Tariffs, and Refresh)."""
from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional
import customtkinter as ctk

from antigravity_provider.router.ui.theme import Theme
from antigravity_provider.router.ui.assets import AssetManager
from antigravity_provider.router.ui.components import (
    HubButton,
    HubCard,
    HubProviderBadge,
    HubSectionHeader,
    HubStatusBadge,
    HubToolbar,
)
from antigravity_provider.router.unified_health import (
    UnifiedHealthService,
    ProfileViewModel,
    STATUS_HEALTHY,
    STATUS_QUOTA_EXHAUSTED,
    STATUS_AUTH_REQUIRED,
    STATUS_NOT_CONFIGURED,
    STATUS_COLD_SPARE,
)
from antigravity_provider.router.quota_collector import AccountQuotaService

logger = logging.getLogger("hermes.hub.accounts_view")


class AccountsView(ctk.CTkFrame):
    def __init__(self, master: Any, app_state: Dict[str, Any], on_action: Optional[Callable] = None, **kwargs):
        super().__init__(master=master, fg_color="transparent", **kwargs)
        self.app_state = app_state
        self.on_action = on_action
        self._search_query = ""
        self._filter_status = "Все статусы"
        self._sort_by = "По умолчанию"
        self._build()

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
        def _done(results):
            def _ui():
                self.refresh_all_btn.configure(text="↻ Обновить все", state="normal")
                self.update_data()
            self.after(0, _ui)
        AccountQuotaService.get().refresh_all_accounts_async(on_complete=_done)

    def _on_search(self, query: str):
        self._search_query = query
        self.update_data()

    def _on_filter(self, filter_val: str):
        self._filter_status = filter_val
        self.update_data()

    def _on_sort(self, sort_val: str):
        self._sort_by = sort_val
        self.update_data()

    def update_data(self, app_state: Optional[Dict[str, Any]] = None):
        service = UnifiedHealthService.get()
        profiles_by_prov = service.scan_all(force=True)

        for prov_key, scroll in self.tab_scrolls.items():
            for w in scroll.winfo_children():
                w.destroy()

            profiles = profiles_by_prov.get(prov_key, [])

            # Filter profiles
            filtered = []
            empty_slots_count = 0

            for p in profiles:
                if p.is_empty_slot:
                    empty_slots_count += 1

                # Search filter
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

                # Status filter
                if self._filter_status == "Подключённые" and p.auth_state != "AUTHENTICATED":
                    continue
                elif self._filter_status == "Требуют входа" and p.auth_state == "AUTHENTICATED":
                    continue
                elif self._filter_status == "Квота исчерпана" and "quota" not in p.health_state:
                    continue

                filtered.append(p)

            # Sort
            if self._sort_by == "По имени":
                filtered.sort(key=lambda x: x.display_name)
            elif self._sort_by == "По статусу":
                filtered.sort(key=lambda x: x.health_state)

            configured_profs = [p for p in filtered if not p.is_empty_slot]
            empty_profs = [p for p in filtered if p.is_empty_slot]

            grid_idx = 0
            for p in configured_profs:
                row_idx, col_idx = divmod(grid_idx, 3)
                card = self._build_account_card(scroll, p)
                card.grid(row=row_idx, column=col_idx, padx=6, pady=6, sticky="nsew")
                grid_idx += 1

            if empty_profs:
                if len(empty_profs) <= 2 or self._search_query:
                    for p in empty_profs:
                        row_idx, col_idx = divmod(grid_idx, 3)
                        card = self._build_empty_slot_card(scroll, p)
                        card.grid(row=row_idx, column=col_idx, padx=6, pady=6, sticky="nsew")
                        grid_idx += 1
                else:
                    c_row = (grid_idx // 3) + 1
                    summary_card = HubCard(scroll, border_color=Theme.BORDER_SUBTLE, fg_color=Theme.SURFACE_MUTED)
                    summary_card.grid(row=c_row, column=0, columnspan=3, padx=6, pady=10, sticky="ew")

                    s_inner = ctk.CTkFrame(summary_card, fg_color="transparent")
                    s_inner.pack(fill="x", padx=16, pady=12)

                    ctk.CTkLabel(
                        s_inner,
                        text=f"Свободные слоты {p.provider_display_name if configured_profs else prov_key}: {len(empty_profs)} слотов доступно",
                        font=Theme.font_body_bold(),
                        text_color=Theme.TEXT_SECONDARY,
                    ).pack(side="left")

                    HubButton(
                        s_inner,
                        text="+ Подключить аккаунт",
                        variant="primary",
                        height=Theme.HEIGHT_BTN_SM,
                        command=lambda k=prov_key: self._trigger_action("add_account", {"provider": k}),
                    ).pack(side="right")

    def _build_account_card(self, parent: Any, p: ProfileViewModel) -> HubCard:
        border_col = Theme.BORDER_ACCENT if p.is_main_account else Theme.BORDER
        card = HubCard(parent, border_color=border_col, fg_color=Theme.SURFACE)

        # ── Header: Provider Icon + Plan Badge + Status Dot ──
        top = ctk.CTkFrame(card, fg_color="transparent")
        top.pack(fill="x", padx=14, pady=(12, 2))

        p_img = AssetManager.get().get_provider_image(p.provider, size=(20, 20))
        if p_img:
            ctk.CTkLabel(top, image=p_img, text="").pack(side="left", padx=(0, 6))

        # Plan badge
        plan_color = "#3b82f6" if p.plan_code in ("PRO", "PLUS", "MAX") else ("#10b981" if p.plan_code in ("ULTRA", "SUPERGROK", "TEAM") else Theme.TEXT_MUTED)
        plan_frame = ctk.CTkFrame(top, fg_color=Theme.SURFACE_MUTED, corner_radius=Theme.RADIUS_SM)
        plan_frame.pack(side="left", padx=(0, 6))
        ctk.CTkLabel(plan_frame, text=p.plan, font=Theme.font_micro_bold(), text_color=plan_color).pack(padx=6, pady=2)

        if p.is_main_account:
            m_pill = ctk.CTkFrame(top, fg_color="#3D3522", corner_radius=Theme.RADIUS_SM)
            m_pill.pack(side="left", padx=(0, 6))
            ctk.CTkLabel(m_pill, text="★ MAIN", font=Theme.font_micro(), text_color=Theme.ACCENT).pack(padx=5, pady=1)

        dot_col = Theme.STATUS_HEALTHY if p.health_state == STATUS_HEALTHY else (Theme.STATUS_WARNING if "quota" in p.health_state or "auth" in p.health_state else Theme.STATUS_ERROR)
        ctk.CTkLabel(top, text="●", font=("Segoe UI", 13, "bold"), text_color=dot_col).pack(side="right")

        # Identity line (Email / Account)
        ident_row = ctk.CTkFrame(card, fg_color="transparent")
        ident_row.pack(fill="x", padx=14, pady=(2, 2))
        ctk.CTkLabel(ident_row, text=p.account_identity, font=Theme.font_body_bold(), text_color=Theme.TEXT_PRIMARY).pack(anchor="w")

        # Subheader: Role & Internal Slot
        sub_row = ctk.CTkFrame(card, fg_color="transparent")
        sub_row.pack(fill="x", padx=14, pady=(0, 4))
        ctk.CTkLabel(sub_row, text=f"{p.display_name} • {p.provider_display_name}", font=Theme.font_caption(), text_color=Theme.TEXT_MUTED).pack(anchor="w")

        # Quota Buckets Box
        quota_box = ctk.CTkFrame(card, fg_color=Theme.SURFACE_MUTED, corner_radius=Theme.RADIUS_SM)
        quota_box.pack(fill="x", padx=14, pady=4)

        snap = p.quota_snapshot or AccountQuotaService.get().get_snapshot(p.provider, p.profile_id)
        if snap and snap.buckets:
            for b in snap.buckets[:4]:
                brow = ctk.CTkFrame(quota_box, fg_color="transparent")
                brow.pack(fill="x", padx=8, pady=2)
                ctk.CTkLabel(brow, text=b.display_name, font=Theme.font_caption(), text_color=Theme.TEXT_PRIMARY).pack(side="left")

                b_status_col = Theme.STATUS_HEALTHY if b.status == "healthy" else (Theme.STATUS_WARNING if b.status == "warning" else Theme.STATUS_ERROR)
                reset_text = f" ({b.formatted_reset()})" if b.formatted_reset() else ""
                rem_text = f"{b.formatted_remaining()}{reset_text}"
                ctk.CTkLabel(brow, text=rem_text, font=Theme.font_micro(), text_color=b_status_col).pack(side="right")
        else:
            ctk.CTkLabel(quota_box, text="Квота: доступна", font=Theme.font_caption(), text_color=Theme.TEXT_MUTED).pack(padx=8, pady=4)

        # Freshness label
        fresh_row = ctk.CTkFrame(card, fg_color="transparent")
        fresh_row.pack(fill="x", padx=14, pady=(2, 2))
        fresh_lbl = snap.freshness_label() if snap else "Обновлено: недавно"
        ctk.CTkLabel(fresh_row, text=fresh_lbl, font=Theme.font_micro(), text_color=Theme.TEXT_MUTED).pack(anchor="w")

        # Action Buttons
        btns = ctk.CTkFrame(card, fg_color="transparent")
        btns.pack(fill="x", padx=14, pady=(4, 12))

        # Single-account refresh button [↻]
        refresh_single_btn = HubButton(
            btns,
            text="↻",
            variant="secondary",
            width=32,
            height=Theme.HEIGHT_BTN_SM,
            command=lambda prov=p.provider, pid=p.profile_id: self._refresh_single_account(prov, pid),
        )
        refresh_single_btn.pack(side="left", padx=(0, 6))

        HubButton(btns, text="⚡ Тест", variant="secondary", width=65, height=Theme.HEIGHT_BTN_SM, command=lambda: self._trigger_action("test", p)).pack(side="left", padx=(0, 6))
        HubButton(btns, text="Назначить", variant="secondary", width=80, height=Theme.HEIGHT_BTN_SM, command=lambda: self._trigger_action("assign_role", p)).pack(side="left", padx=(0, 6))

        ctk.CTkButton(
            btns,
            text="⋮",
            width=28,
            height=Theme.HEIGHT_BTN_SM,
            fg_color=Theme.SURFACE_MUTED,
            hover_color=Theme.SURFACE_HOVER,
            text_color=Theme.TEXT_PRIMARY,
            font=("Segoe UI", 12, "bold"),
            command=lambda: self._open_account_menu(p),
        ).pack(side="right")

        return card

    def _refresh_single_account(self, provider: str, profile_id: str):
        def _done(snap):
            self.after(0, self.update_data)
        AccountQuotaService.get().refresh_account_async(provider, profile_id, on_complete=_done)

    def _build_empty_slot_card(self, parent: Any, p: ProfileViewModel) -> HubCard:
        card = HubCard(parent, border_color=Theme.BORDER_SUBTLE, fg_color=Theme.SURFACE_MUTED)

        top = ctk.CTkFrame(card, fg_color="transparent")
        top.pack(fill="x", padx=14, pady=(12, 4))
        ctk.CTkLabel(top, text=p.display_name, font=Theme.font_heading(), text_color=Theme.TEXT_SECONDARY).pack(side="left")

        ctk.CTkLabel(card, text="Слот свободен", font=Theme.font_body(), text_color=Theme.TEXT_MUTED).pack(anchor="w", padx=14, pady=(2, 8))

        btns = ctk.CTkFrame(card, fg_color="transparent")
        btns.pack(fill="x", padx=14, pady=(4, 12))
        HubButton(
            btns,
            text="+ Подключить",
            variant="primary",
            height=Theme.HEIGHT_BTN_SM,
            command=lambda: self._trigger_action("add_account", {"profile_id": p.profile_id, "provider": p.provider}),
        ).pack(side="left")

        return card

    def _open_account_menu(self, p: ProfileViewModel):
        pass
