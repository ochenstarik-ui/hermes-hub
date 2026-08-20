"""Hermes Hub — Accounts View (Компактная responsive сетка аккаунтов и слотов)."""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional
import customtkinter as ctk

from antigravity_provider.router.ui.theme import Theme
from antigravity_provider.router.ui.components import (
    HubButton,
    HubCard,
    HubProviderBadge,
    HubSectionHeader,
    HubStatusBadge,
)
from antigravity_provider.router.unified_health import (
    UnifiedHealthService,
    ProfileViewModel,
    STATUS_HEALTHY,
    STATUS_QUOTA_EXHAUSTED,
    STATUS_AUTH_REQUIRED,
    STATUS_COLD_SPARE,
)


class AccountsView(ctk.CTkFrame):
    def __init__(self, master: Any, app_state: Dict[str, Any], on_action: Optional[Callable] = None, **kwargs):
        super().__init__(master=master, fg_color="transparent", **kwargs)
        self.app_state = app_state
        self.on_action = on_action
        self._build()

    def _build(self):
        header = HubSectionHeader(
            self,
            title="Управление аккаунтами",
            subtitle="Подключение, тестирование и распределение учетных записей провайдеров",
            action_text="+ Добавить аккаунт",
            action_cmd=lambda: self._trigger_action("add_account", {}),
        )
        header.pack(fill="x", padx=20, pady=(16, 12))

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

    def update_data(self, app_state: Optional[Dict[str, Any]] = None):
        service = UnifiedHealthService.get()
        profiles_by_prov = service.scan_all()

        for prov_key, scroll in self.tab_scrolls.items():
            for w in scroll.winfo_children():
                w.destroy()

            profiles = profiles_by_prov.get(prov_key, [])
            for idx, p in enumerate(profiles):
                row_idx, col_idx = divmod(idx, 3)
                if p.is_empty_slot or p.is_cold_spare:
                    card = self._build_empty_slot_card(scroll, p)
                else:
                    card = self._build_account_card(scroll, p)
                card.grid(row=row_idx, column=col_idx, padx=6, pady=6, sticky="nsew")

    def _build_account_card(self, parent: Any, p: ProfileViewModel) -> HubCard:
        border_col = Theme.BORDER_ACCENT if p.is_main_account else Theme.BORDER
        card = HubCard(parent, border_color=border_col, fg_color=Theme.SURFACE)

        # Top line: Identity / Email + MAIN badge + Status dot
        top = ctk.CTkFrame(card, fg_color="transparent")
        top.pack(fill="x", padx=12, pady=(10, 2))

        ctk.CTkLabel(top, text=p.account_identity, font=Theme.font_body_bold(), text_color=Theme.TEXT_PRIMARY).pack(side="left")

        if p.is_main_account:
            m_pill = ctk.CTkFrame(top, fg_color="#3D3522", corner_radius=Theme.RADIUS_SM)
            m_pill.pack(side="left", padx=(6, 0))
            ctk.CTkLabel(m_pill, text="★ MAIN", font=Theme.font_micro(), text_color=Theme.ACCENT).pack(padx=4, pady=1)

        dot_col = Theme.STATUS_HEALTHY if p.health_state == STATUS_HEALTHY else (Theme.STATUS_WARNING if "quota" in p.health_state or "auth" in p.health_state else Theme.STATUS_ERROR)
        ctk.CTkLabel(top, text="●", font=("Segoe UI", 12, "bold"), text_color=dot_col).pack(side="right")

        # Provider & Slot info
        prov_row = ctk.CTkFrame(card, fg_color="transparent")
        prov_row.pack(fill="x", padx=12, pady=(0, 4))
        ctk.CTkLabel(prov_row, text=f"{p.provider_display_name} • {p.profile_id}", font=Theme.font_micro(), text_color=Theme.TEXT_MUTED).pack(anchor="w")

        # Per-model breakdown box (Model-Family health)
        models_box = ctk.CTkFrame(card, fg_color=Theme.SURFACE_MUTED, corner_radius=Theme.RADIUS_SM)
        models_box.pack(fill="x", padx=12, pady=4)

        if p.model_states:
            for fam_name, m_health in list(p.model_states.items())[:2]:
                mrow = ctk.CTkFrame(models_box, fg_color="transparent")
                mrow.pack(fill="x", padx=8, pady=2)
                ctk.CTkLabel(mrow, text=m_health.display_name, font=Theme.font_micro(), text_color=Theme.TEXT_SECONDARY).pack(side="left")
                m_col = Theme.STATUS_HEALTHY if m_health.status == STATUS_HEALTHY else Theme.STATUS_WARNING
                ctk.CTkLabel(mrow, text=f"● {m_health.status_label_ru}", font=Theme.font_micro(), text_color=m_col).pack(side="right")
        else:
            ctk.CTkLabel(models_box, text=f"Статус: {p.health_label_ru}", font=Theme.font_micro(), text_color=Theme.TEXT_MUTED).pack(padx=8, pady=4)

        # Assigned role info
        role_box = ctk.CTkFrame(card, fg_color="transparent")
        role_box.pack(fill="x", padx=12, pady=2)
        role_str = p.assigned_roles[0] if p.assigned_roles else p.display_name
        ctk.CTkLabel(role_box, text=f"Назначение: {role_str}", font=Theme.font_caption(), text_color=Theme.TEXT_SECONDARY).pack(anchor="w")

        # Action Buttons
        btns = ctk.CTkFrame(card, fg_color="transparent")
        btns.pack(fill="x", padx=12, pady=(6, 10))

        HubButton(btns, text="⚡ Тест", variant="secondary", width=65, height=Theme.HEIGHT_BTN_SM, command=lambda: self._trigger_action("test", p)).pack(side="left", padx=(0, 4))
        HubButton(btns, text="Назначить", variant="secondary", width=80, height=Theme.HEIGHT_BTN_SM, command=lambda: self._trigger_action("assign_role", p)).pack(side="left", padx=(0, 4))

        ctk.CTkButton(
            btns,
            text="⋮",
            width=26,
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
        top.pack(fill="x", padx=12, pady=(12, 4))

        title_txt = "Холодный резерв" if p.is_cold_spare else "Свободный слот"
        ctk.CTkLabel(top, text=title_txt, font=Theme.font_heading(), text_color=Theme.TEXT_MUTED).pack(side="left")
        ctk.CTkLabel(top, text=f"({p.profile_id})", font=Theme.font_mono_sm(), text_color=Theme.TEXT_MUTED).pack(side="right")

        ctk.CTkLabel(card, text=p.provider_display_name, font=Theme.font_caption(), text_color=Theme.TEXT_SECONDARY).pack(anchor="w", padx=12, pady=(0, 4))

        desc_txt = "Не используется автоматически" if p.is_cold_spare else "Аккаунт не подключён"
        ctk.CTkLabel(card, text=desc_txt, font=Theme.font_micro(), text_color=Theme.TEXT_MUTED).pack(anchor="w", padx=12, pady=(0, 10))

        HubButton(
            card,
            text="+ Подключить аккаунт",
            variant="accent_outline",
            height=Theme.HEIGHT_BTN_SM,
            command=lambda: self._trigger_action("oauth" if p.provider == "antigravity" else "add_account", p),
        ).pack(fill="x", padx=12, pady=(4, 12))

        return card

    def _open_account_menu(self, p: ProfileViewModel):
        popup = ctk.CTkToplevel(self.winfo_toplevel())
        popup.title(f"Аккаунт: {p.account_identity}")
        popup.geometry("300x260")
        popup.configure(fg_color=Theme.DARK)
        popup.resizable(False, False)
        popup.transient(self.winfo_toplevel())
        popup.grab_set()

        popup.update_idletasks()
        px = self.winfo_toplevel().winfo_x() + 320
        py = self.winfo_toplevel().winfo_y() + 200
        popup.geometry(f"+{px}+{py}")

        c = HubCard(popup, fg_color=Theme.DARK, border_color=Theme.BORDER_ACCENT)
        c.pack(fill="both", expand=True, padx=8, pady=8)

        ctk.CTkLabel(c, text=p.account_identity, font=Theme.font_heading(), text_color=Theme.TEXT_PRIMARY).pack(pady=(8, 2))
        ctk.CTkLabel(c, text=f"{p.provider_display_name} • {p.profile_id}", font=Theme.font_mono_sm(), text_color=Theme.TEXT_MUTED).pack(pady=(0, 8))

        def _do(action_name: str):
            popup.destroy()
            self._trigger_action(action_name, p)

        HubButton(c, text="⚡ Проверить состояние", variant="secondary", height=28, command=lambda: _do("test")).pack(fill="x", padx=12, pady=2)
        HubButton(c, text="★ Сделать основным Hermes", variant="secondary", height=28, command=lambda: _do("set_main")).pack(fill="x", padx=12, pady=2)
        HubButton(c, text="👑 Назначить главным оркестратором", variant="secondary", height=28, command=lambda: _do("set_orchestrator")).pack(fill="x", padx=12, pady=2)
        HubButton(c, text="🗑️ Удалить credentials", variant="danger", height=28, command=lambda: _do("delete_credentials")).pack(fill="x", padx=12, pady=(4, 0))

    def _trigger_action(self, action: str, profile_vm: Any):
        if self.on_action:
            p_dict = {
                "profile_id": getattr(profile_vm, "profile_id", ""),
                "provider": getattr(profile_vm, "provider", ""),
                "display_name": getattr(profile_vm, "display_name", ""),
            } if hasattr(profile_vm, "profile_id") else profile_vm
            self.on_action(action, p_dict)
