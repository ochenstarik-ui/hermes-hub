"""Hermes Hub — Accounts View (Cockpit-grade Toolbar, Filters, and Provider Breakdown)."""
from __future__ import annotations

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
        # 1. Header
        header = HubSectionHeader(
            self,
            title="Управление аккаунтами",
            subtitle="Подключение, проверка и распределение AI-аккаунтов",
            action_text="+ Добавить аккаунт",
            action_cmd=lambda: self._trigger_action("add_account", {}),
        )
        header.pack(fill="x", padx=20, pady=(16, 8))

        # 2. Cockpit-grade Toolbar
        self.toolbar = HubToolbar(
            self,
            on_search=self._on_search,
            on_filter=self._on_filter,
            on_sort=self._on_sort,
        )
        self.toolbar.pack(fill="x", padx=20, pady=(0, 10))

        # 3. Provider Tabs with real icons
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
        profiles_by_prov = service.scan_all()

        for prov_key, scroll in self.tab_scrolls.items():
            for w in scroll.winfo_children():
                w.destroy()

            profiles = profiles_by_prov.get(prov_key, [])

            # Filter profiles
            filtered = []
            empty_slots_count = 0

            for p in profiles:
                # Count empty/unconfigured slots
                if p.is_empty_slot:
                    empty_slots_count += 1

                # Search filter
                if self._search_query:
                    q = self._search_query
                    matches = (
                        q in p.account_identity.lower()
                        or q in p.display_name.lower()
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

            # Render configured/active accounts first
            configured_profs = [p for p in filtered if not p.is_empty_slot]
            empty_profs = [p for p in filtered if p.is_empty_slot]

            grid_idx = 0
            for p in configured_profs:
                row_idx, col_idx = divmod(grid_idx, 3)
                card = self._build_account_card(scroll, p)
                card.grid(row=row_idx, column=col_idx, padx=6, pady=6, sticky="nsew")
                grid_idx += 1

            # Render free slots consolidated or individual if filtered
            if empty_profs:
                # If only a few empty or searched, show individual slots; otherwise show sleek consolidated bar
                if len(empty_profs) <= 2 or self._search_query:
                    for p in empty_profs:
                        row_idx, col_idx = divmod(grid_idx, 3)
                        card = self._build_empty_slot_card(scroll, p)
                        card.grid(row=row_idx, column=col_idx, padx=6, pady=6, sticky="nsew")
                        grid_idx += 1
                else:
                    # Sleek consolidated free slots widget
                    c_row = (grid_idx // 3) + 1
                    summary_card = HubCard(scroll, border_color=Theme.BORDER_SUBTLE, fg_color=Theme.SURFACE_MUTED)
                    summary_card.grid(row=c_row, column=0, columnspan=3, padx=6, pady=10, sticky="ew")

                    s_inner = ctk.CTkFrame(summary_card, fg_color="transparent")
                    s_inner.pack(fill="x", padx=16, pady=12)

                    ctk.CTkLabel(
                        s_inner,
                        text=f"Свободные слоты {prov_key}: {len(empty_profs)} слотов доступно для подключения",
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

        # ── Header: Provider Icon + Identity / Masked Email + Status dot ──
        top = ctk.CTkFrame(card, fg_color="transparent")
        top.pack(fill="x", padx=14, pady=(12, 2))

        p_img = AssetManager.get().get_provider_image(p.provider, size=(20, 20))
        if p_img:
            ctk.CTkLabel(top, image=p_img, text="").pack(side="left", padx=(0, 6))

        ctk.CTkLabel(top, text=p.account_identity, font=Theme.font_heading(), text_color=Theme.TEXT_PRIMARY).pack(side="left")

        if p.is_main_account:
            m_pill = ctk.CTkFrame(top, fg_color="#3D3522", corner_radius=Theme.RADIUS_SM)
            m_pill.pack(side="left", padx=(6, 0))
            ctk.CTkLabel(m_pill, text="★ MAIN", font=Theme.font_micro(), text_color=Theme.ACCENT).pack(padx=5, pady=1)

        dot_col = Theme.STATUS_HEALTHY if p.health_state == STATUS_HEALTHY else (Theme.STATUS_WARNING if "quota" in p.health_state or "auth" in p.health_state else Theme.STATUS_ERROR)
        ctk.CTkLabel(top, text="●", font=("Segoe UI", 13, "bold"), text_color=dot_col).pack(side="right")

        # Subheader: Role & Internal Slot
        sub_row = ctk.CTkFrame(card, fg_color="transparent")
        sub_row.pack(fill="x", padx=14, pady=(0, 4))
        ctk.CTkLabel(sub_row, text=f"{p.display_name} • {p.provider_display_name}", font=Theme.font_caption(), text_color=Theme.TEXT_MUTED).pack(anchor="w")

        # Per-model breakdown box (Model-Family health)
        models_box = ctk.CTkFrame(card, fg_color=Theme.SURFACE_MUTED, corner_radius=Theme.RADIUS_SM)
        models_box.pack(fill="x", padx=14, pady=4)

        if p.model_states:
            for fam_name, m_health in list(p.model_states.items())[:2]:
                mrow = ctk.CTkFrame(models_box, fg_color="transparent")
                mrow.pack(fill="x", padx=8, pady=3)
                ctk.CTkLabel(mrow, text=m_health.display_name, font=Theme.font_caption(), text_color=Theme.TEXT_PRIMARY).pack(side="left")
                m_col = Theme.STATUS_HEALTHY if m_health.status == STATUS_HEALTHY else Theme.STATUS_WARNING
                ctk.CTkLabel(mrow, text=f"● {m_health.status_label_ru}", font=Theme.font_micro(), text_color=m_col).pack(side="right")
        else:
            ctk.CTkLabel(models_box, text=f"Статус: {p.health_label_ru}", font=Theme.font_caption(), text_color=Theme.TEXT_MUTED).pack(padx=8, pady=4)

        # Assigned role tag
        role_box = ctk.CTkFrame(card, fg_color="transparent")
        role_box.pack(fill="x", padx=14, pady=2)
        role_str = p.assigned_roles[0] if p.assigned_roles else p.display_name
        ctk.CTkLabel(role_box, text=f"Роль: {role_str}", font=Theme.font_caption(), text_color=Theme.TEXT_SECONDARY).pack(anchor="w")

        # Action Buttons
        btns = ctk.CTkFrame(card, fg_color="transparent")
        btns.pack(fill="x", padx=14, pady=(6, 12))

        HubButton(btns, text="⚡ Тест", variant="secondary", width=70, height=Theme.HEIGHT_BTN_SM, command=lambda: self._trigger_action("test", p)).pack(side="left", padx=(0, 6))
        HubButton(btns, text="Назначить", variant="secondary", width=85, height=Theme.HEIGHT_BTN_SM, command=lambda: self._trigger_action("assign_role", p)).pack(side="left", padx=(0, 6))

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

    def _build_empty_slot_card(self, parent: Any, p: ProfileViewModel) -> HubCard:
        card = HubCard(parent, border_color=Theme.BORDER_SUBTLE, fg_color=Theme.SURFACE_MUTED)

        top = ctk.CTkFrame(card, fg_color="transparent")
        top.pack(fill="x", padx=14, pady=(12, 4))

        title_txt = "Холодный резерв" if p.is_cold_spare else "Свободный слот"
        ctk.CTkLabel(top, text=title_txt, font=Theme.font_heading(), text_color=Theme.TEXT_MUTED).pack(side="left")
        ctk.CTkLabel(top, text=f"({p.profile_id})", font=Theme.font_mono_sm(), text_color=Theme.TEXT_MUTED).pack(side="right")

        ctk.CTkLabel(card, text=p.provider_display_name, font=Theme.font_caption(), text_color=Theme.TEXT_SECONDARY).pack(anchor="w", padx=14, pady=(0, 4))

        desc_txt = "Не используется автоматически" if p.is_cold_spare else "Аккаунт не добавлен"
        ctk.CTkLabel(card, text=desc_txt, font=Theme.font_caption(), text_color=Theme.TEXT_MUTED).pack(anchor="w", padx=14, pady=(0, 10))

        HubButton(
            card,
            text="+ Подключить аккаунт",
            variant="accent_outline",
            height=Theme.HEIGHT_BTN_SM,
            command=lambda: self._trigger_action("oauth" if p.provider == "antigravity" else "add_account", p),
        ).pack(fill="x", padx=14, pady=(4, 12))

        return card

    def _open_account_menu(self, p: ProfileViewModel):
        popup = ctk.CTkToplevel(self.winfo_toplevel())
        popup.title(f"Аккаунт: {p.account_identity}")
        popup.geometry("320x280")
        popup.configure(fg_color=Theme.DARK)
        popup.resizable(False, False)
        popup.transient(self.winfo_toplevel())
        popup.grab_set()

        popup.update_idletasks()
        px = self.winfo_toplevel().winfo_x() + 320
        py = self.winfo_toplevel().winfo_y() + 200
        popup.geometry(f"+{px}+{py}")

        c = HubCard(popup, fg_color=Theme.DARK, border_color=Theme.BORDER_ACCENT)
        c.pack(fill="both", expand=True, padx=10, pady=10)

        ctk.CTkLabel(c, text=p.account_identity, font=Theme.font_heading(), text_color=Theme.TEXT_PRIMARY).pack(pady=(8, 2))
        ctk.CTkLabel(c, text=f"{p.provider_display_name} • {p.profile_id}", font=Theme.font_mono_sm(), text_color=Theme.TEXT_MUTED).pack(pady=(0, 10))

        def _do(action_name: str):
            popup.destroy()
            self._trigger_action(action_name, p)

        HubButton(c, text="⚡ Проверить состояние (Тест)", variant="secondary", height=30, command=lambda: _do("test")).pack(fill="x", padx=12, pady=2)
        HubButton(c, text="★ Сделать основным Hermes", variant="secondary", height=30, command=lambda: _do("set_main")).pack(fill="x", padx=12, pady=2)
        HubButton(c, text="👑 Назначить главным оркестратором", variant="secondary", height=30, command=lambda: _do("set_orchestrator")).pack(fill="x", padx=12, pady=2)
        HubButton(c, text="🗑️ Удалить credentials", variant="danger", height=30, command=lambda: _do("delete_credentials")).pack(fill="x", padx=12, pady=(4, 0))

    def _trigger_action(self, action: str, profile_vm: Any):
        if self.on_action:
            p_dict = {
                "profile_id": getattr(profile_vm, "profile_id", ""),
                "provider": getattr(profile_vm, "provider", ""),
                "display_name": getattr(profile_vm, "display_name", ""),
            } if hasattr(profile_vm, "profile_id") else profile_vm
            self.on_action(action, p_dict)
