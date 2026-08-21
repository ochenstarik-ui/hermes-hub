"""Hermes Hub — Team View (Команда агентов и Dashboard с Unified Health v3)."""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional
import customtkinter as ctk

from antigravity_provider.router.ui.theme import Theme
from antigravity_provider.router.ui.assets import AssetManager
from antigravity_provider.router.ui.components import (
    HubButton,
    HubCard,
    HubMetricCard,
    HubSectionHeader,
    HubStatusBadge,
)
from antigravity_provider.router.unified_health import (
    AgentViewModel,
    STATUS_HEALTHY,
    STATUS_QUOTA_LOW,
    STATUS_QUOTA_EXHAUSTED,
    STATUS_AUTH_REQUIRED,
    STATUS_NOT_CONFIGURED,
    STATUS_AUTH_EXPIRED,
)
from antigravity_provider.router.state_store import HubSnapshot


class AgentCardWidget(HubCard):
    """Reusable agent card that updates in-place without rebuilding widgets."""

    def __init__(self, master: Any, on_action: Optional[Callable] = None, **kwargs):
        super().__init__(master=master, border_color=Theme.BORDER, fg_color=Theme.SURFACE, **kwargs)
        self.on_action = on_action
        self.agent_data: Optional[AgentViewModel] = None

        # ── Line 1: Role Title + Badges + Status Dot ──
        self.line1 = ctk.CTkFrame(self, fg_color="transparent")
        self.line1.pack(fill="x", padx=14, pady=(12, 2))

        self.role_lbl = ctk.CTkLabel(self.line1, text="—", font=Theme.font_heading(), text_color=Theme.TEXT_PRIMARY)
        self.role_lbl.pack(side="left")

        self.orch_pill = ctk.CTkFrame(self.line1, fg_color="#3D3522", corner_radius=Theme.RADIUS_SM)
        self.orch_pill_lbl = ctk.CTkLabel(
            self.orch_pill, text="👑 ЛИДЕР РОУТЕРА", font=Theme.font_micro(), text_color=Theme.ACCENT
        )
        self.orch_pill_lbl.pack(padx=5, pady=1)

        self.status_dot = ctk.CTkLabel(
            self.line1, text="●", font=("Segoe UI", 13, "bold"), text_color=Theme.STATUS_HEALTHY
        )
        self.status_dot.pack(side="right")

        # ── Line 2: Internal ID + Model ──
        self.line2 = ctk.CTkFrame(self, fg_color="transparent")
        self.line2.pack(fill="x", padx=14, pady=(0, 4))
        self.id_model_lbl = ctk.CTkLabel(self.line2, text="—", font=Theme.font_caption(), text_color=Theme.TEXT_MUTED)
        self.id_model_lbl.pack(anchor="w")

        # ── Line 3: Provider with Real Logo ──
        self.line3 = ctk.CTkFrame(self, fg_color="transparent")
        self.line3.pack(fill="x", padx=14, pady=(2, 2))

        self.prov_icon = ctk.CTkLabel(self.line3, text="")
        self.prov_icon.pack(side="left", padx=(0, 6))

        self.prov_lbl = ctk.CTkLabel(self.line3, text="—", font=Theme.font_caption(), text_color=Theme.TEXT_SECONDARY)
        self.prov_lbl.pack(side="left")

        # ── Line 4: Identity / Account ──
        self.line4 = ctk.CTkFrame(self, fg_color="transparent")
        self.line4.pack(fill="x", padx=14, pady=(2, 4))
        self.identity_lbl = ctk.CTkLabel(
            self.line4, text="—", font=Theme.font_mono_sm(), text_color=Theme.TEXT_SECONDARY
        )
        self.identity_lbl.pack(anchor="w")

        self.quota_lbl = ctk.CTkLabel(
            self.line4, text="Квота: Н/Д", font=Theme.font_micro(), text_color=Theme.TEXT_MUTED
        )
        self.quota_lbl.pack(anchor="w", pady=(Theme.SPACE_XS, 0))

        # ── Line 5: Role Tag Pills ──
        self.line5 = ctk.CTkFrame(self, fg_color="transparent")
        self.line5.pack(fill="x", padx=14, pady=(4, 6))

        self.pill1 = ctk.CTkFrame(self.line5, fg_color=Theme.SURFACE_MUTED, corner_radius=Theme.RADIUS_SM)
        self.pill1.pack(side="left", padx=(0, 6))
        self.pill1_lbl = ctk.CTkLabel(self.pill1, text="—", font=Theme.font_micro(), text_color=Theme.TEXT_SECONDARY)
        self.pill1_lbl.pack(padx=6, pady=2)

        self.pill2 = ctk.CTkFrame(self.line5, fg_color=Theme.SURFACE_MUTED, corner_radius=Theme.RADIUS_SM)
        self.pill2.pack(side="left", padx=(0, 6))
        self.pill2_lbl = ctk.CTkLabel(self.pill2, text="Primary", font=Theme.font_micro(), text_color=Theme.TEXT_MUTED)
        self.pill2_lbl.pack(padx=6, pady=2)

        # ── Line 6: Status & Menu Action ──
        self.line6 = ctk.CTkFrame(self, fg_color="transparent")
        self.line6.pack(fill="x", padx=14, pady=(4, 12))

        self.status_str_lbl = ctk.CTkLabel(
            self.line6, text="● Работает", font=Theme.font_caption(), text_color=Theme.STATUS_HEALTHY
        )
        self.status_str_lbl.pack(side="left")

        self.menu_btn = ctk.CTkButton(
            self.line6,
            text="⋮",
            width=28,
            height=24,
            fg_color="transparent",
            hover_color=Theme.SURFACE_HOVER,
            text_color=Theme.TEXT_SECONDARY,
            font=("Segoe UI", 12, "bold"),
            command=self._open_menu,
        )
        self.menu_btn.pack(side="right")

    def update_agent(self, a: AgentViewModel):
        self.agent_data = a
        is_orch = a.is_main_orchestrator
        self.configure(border_color=Theme.BORDER_ACCENT if is_orch else Theme.BORDER)

        self.role_lbl.configure(text=a.role_name_ru)

        if is_orch:
            self.orch_pill.pack(side="left", padx=(8, 0))
        else:
            self.orch_pill.pack_forget()

        # Dot color
        dot_color = (
            Theme.STATUS_HEALTHY
            if a.status == STATUS_HEALTHY
            else (
                Theme.STATUS_WARNING
                if "quota" in a.status or "auth" in a.status or "not_configured" in a.status
                else Theme.STATUS_ERROR
            )
        )
        self.status_dot.configure(text_color=dot_color)

        # ID + Model
        self.id_model_lbl.configure(text=f"{a.assigned_profile_id} • {a.model}")

        # Provider Icon + Label
        p_img = AssetManager.get().get_provider_image(a.provider, size=(18, 18))
        if p_img:
            self.prov_icon.configure(image=p_img)
            self.prov_icon.pack(side="left", padx=(0, 6))
        else:
            self.prov_icon.pack_forget()

        prov = a.provider.lower()
        if "antigravity" in prov:
            self.prov_lbl.configure(text="Google Antigravity", text_color=Theme.PROVIDER_ANTIGRAVITY)
        elif "codex" in prov:
            self.prov_lbl.configure(text="OpenAI Codex", text_color=Theme.PROVIDER_CODEX)
        elif "opencode" in prov:
            self.prov_lbl.configure(text="OpenCode Go", text_color=Theme.PROVIDER_OPENCODE)
        elif "claude" in prov or "anthropic" in prov:
            self.prov_lbl.configure(text="Claude", text_color="#d97706")
        elif "grok" in prov or "xai" in prov:
            self.prov_lbl.configure(text="Grok", text_color="#3b82f6")
        else:
            self.prov_lbl.configure(text=a.provider_display_name, text_color=Theme.TEXT_MUTED)

        self.identity_lbl.configure(text=a.account_identity or "Аккаунт: Н/Д")
        quota_color = (
            Theme.STATUS_HEALTHY
            if a.active_quota_status == "healthy"
            else (
                Theme.STATUS_WARNING
                if a.active_quota_status == "warning"
                else Theme.STATUS_ERROR
                if a.active_quota_status == "exhausted"
                else Theme.TEXT_MUTED
            )
        )
        quota_label = a.active_quota_label or "Н/Д"
        session = f" • сессия {a.session_id}" if a.session_id else ""
        self.quota_lbl.configure(text=f"Квота: {quota_label}{session}", text_color=quota_color)

        # Pills
        self.pill1_lbl.configure(text=a.role_id)
        self.pill2_lbl.configure(text=a.routing_position)

        # Status text
        cd_str = f" ({a.cooldown_remaining_sec}s)" if a.cooldown_remaining_sec > 0 else ""
        self.status_str_lbl.configure(text=f"● {a.status_label_ru.upper()}{cd_str}", text_color=dot_color)

    def _open_menu(self):
        if not self.agent_data:
            return
        a = self.agent_data
        pid = a.assigned_profile_id or ""

        popup = ctk.CTkToplevel(self.winfo_toplevel())
        popup.title(f"Действия: {a.role_name_ru}")
        popup.geometry("320x260")
        popup.configure(fg_color=Theme.DARK)
        popup.resizable(False, False)
        popup.transient(self.winfo_toplevel())
        popup.grab_set()

        popup.update_idletasks()
        px = self.winfo_toplevel().winfo_x() + 300
        py = self.winfo_toplevel().winfo_y() + 200
        popup.geometry(f"+{px}+{py}")

        c = HubCard(popup, fg_color=Theme.DARK, border_color=Theme.BORDER_ACCENT)
        c.pack(fill="both", expand=True, padx=10, pady=10)

        ctk.CTkLabel(c, text=a.role_name_ru, font=Theme.font_heading(), text_color=Theme.TEXT_PRIMARY).pack(pady=(8, 2))
        ctk.CTkLabel(
            c, text=f"Аккаунт: {a.account_identity} ({pid})", font=Theme.font_mono_sm(), text_color=Theme.TEXT_MUTED
        ).pack(pady=(0, 10))

        def _do(action_name: str):
            popup.destroy()
            if self.on_action:
                self.on_action(
                    action_name, {"profile_id": pid, "provider": a.provider, "display_name": a.assigned_display_name}
                )

        HubButton(c, text="⚡ Проверить (Тест)", variant="secondary", height=30, command=lambda: _do("test")).pack(
            fill="x", padx=12, pady=2
        )
        HubButton(
            c,
            text="👑 Назначить главным оркестратором",
            variant="secondary",
            height=30,
            command=lambda: _do("set_orchestrator"),
        ).pack(fill="x", padx=12, pady=2)
        HubButton(
            c,
            text="★ Сделать основным аккаунтом Hermes",
            variant="secondary",
            height=30,
            command=lambda: _do("set_main"),
        ).pack(fill="x", padx=12, pady=2)
        HubButton(
            c, text="🔄 Перераспределить роли", variant="ghost", height=28, command=lambda: _do("auto_assign_all")
        ).pack(fill="x", padx=12, pady=(2, 0))


class TeamView(ctk.CTkFrame):
    def __init__(
        self, master: Any, app_state: Optional[Dict[str, Any]] = None, on_action: Optional[Callable] = None, **kwargs
    ):
        super().__init__(master=master, fg_color="transparent", **kwargs)
        self.app_state = app_state or {}
        self.on_action = on_action
        self._card_widgets: Dict[str, AgentCardWidget] = {}
        self._build_static_layout()
        self.update_data()

    def _build_static_layout(self):
        # ── 1. Top Section Header ──
        header_frame = ctk.CTkFrame(self, fg_color="transparent")
        header_frame.pack(fill="x", padx=20, pady=(16, 12))

        left_titles = ctk.CTkFrame(header_frame, fg_color="transparent")
        left_titles.pack(side="left")

        ctk.CTkLabel(
            left_titles,
            text="Команда агентов",
            font=Theme.font_title_page(),
            text_color=Theme.TEXT_PRIMARY,
        ).pack(anchor="w")

        ctk.CTkLabel(
            left_titles,
            text="Управляйте командой Hermes и их ролями",
            font=Theme.font_caption(),
            text_color=Theme.TEXT_MUTED,
        ).pack(anchor="w", pady=(2, 0))

        right_actions = ctk.CTkFrame(header_frame, fg_color="transparent")
        right_actions.pack(side="right")

        HubButton(
            right_actions,
            text="+ Добавить агент",
            variant="primary",
            height=Theme.HEIGHT_BTN_MD,
            command=lambda: self._trigger_action("add_account", {}),
        ).pack(side="left", padx=(0, 8))

        ctk.CTkButton(
            right_actions,
            text="⋮",
            width=38,
            height=Theme.HEIGHT_BTN_MD,
            fg_color=Theme.SURFACE,
            hover_color=Theme.SURFACE_HOVER,
            text_color=Theme.TEXT_PRIMARY,
            font=("Segoe UI", 14, "bold"),
            corner_radius=Theme.RADIUS_SM,
            command=lambda: self._trigger_action("auto_assign_all", {}),
        ).pack(side="left")

        # ── Scrollable Body ──
        self.scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.scroll.pack(fill="both", expand=True, padx=15, pady=(0, 8))

        # ── 2. Top 4 Metric Cards (Real Readiness) ──
        metrics_grid = ctk.CTkFrame(self.scroll, fg_color="transparent")
        metrics_grid.pack(fill="x", pady=(0, 16))
        for i in range(4):
            metrics_grid.grid_columnconfigure(i, weight=1)

        self.m1 = HubMetricCard(
            metrics_grid, title="АГЕНТЫ", value="0/6", subtext="готовы к работе", icon="👥", accent=True
        )
        self.m1.grid(row=0, column=0, padx=6, sticky="nsew")

        self.m2 = HubMetricCard(metrics_grid, title="АККАУНТЫ", value="0/16", subtext="подключено", icon="💼")
        self.m2.grid(row=0, column=1, padx=6, sticky="nsew")

        self.m3 = HubMetricCard(metrics_grid, title="ПРОВАЙДЕРЫ", value="3/3", subtext="доступно", icon="⚛")
        self.m3.grid(row=0, column=2, padx=6, sticky="nsew")

        self.m4 = HubMetricCard(
            metrics_grid, title="СОСТОЯНИЕ", value="Healthy", subtext="Все системы работают", icon="🛡️"
        )
        self.m4.grid(row=0, column=3, padx=6, sticky="nsew")

        # ── 3. Hierarchy: orchestrator → role agents ──
        ctk.CTkLabel(
            self.scroll,
            text="ОРКЕСТРАТОР",
            font=Theme.font_micro(),
            text_color=Theme.TEXT_MUTED,
        ).pack(anchor="w", padx=Theme.SPACE_XS)
        self.orchestrator_grid = ctk.CTkFrame(self.scroll, fg_color="transparent")
        self.orchestrator_grid.pack(fill="x", pady=(Theme.SPACE_XS, Theme.SECTION_GAP))
        self.orchestrator_grid.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            self.scroll,
            text="РОЛИ И АГЕНТЫ",
            font=Theme.font_micro(),
            text_color=Theme.TEXT_MUTED,
        ).pack(anchor="w", padx=Theme.SPACE_XS)
        self.cards_grid = ctk.CTkFrame(self.scroll, fg_color="transparent")
        self.cards_grid.pack(fill="both", expand=True)
        for col_idx in range(3):
            self.cards_grid.grid_columnconfigure(col_idx, weight=1)

    def update_data(self, snapshot: Optional[Any] = None):
        if not isinstance(snapshot, HubSnapshot):
            return

        readiness = snapshot.readiness
        agents = snapshot.agents

        # Update metric cards
        self.m1.val_label.configure(text=f"{readiness.roles_ready_count}/{readiness.total_roles}")
        self.m1.sub_label.configure(text="ролей готовы")

        self.m2.val_label.configure(text=f"{readiness.accounts_connected_count}/{readiness.total_accounts}")
        self.m2.sub_label.configure(text="подключено")

        self.m3.val_label.configure(text=f"{readiness.providers_ready_count}/{readiness.total_providers}")
        self.m3.sub_label.configure(text="доступно")

        self.m4.val_label.configure(text=readiness.title_ru)
        self.m4.sub_label.configure(text=readiness.summary_ru)

        live_roles = {agent.role_id for agent in agents}
        for role_id in list(self._card_widgets):
            if role_id not in live_roles:
                self._card_widgets.pop(role_id).destroy()

        orchestrators = [agent for agent in agents if agent.is_main_orchestrator]
        role_agents = [agent for agent in agents if not agent.is_main_orchestrator]
        for index, agent in enumerate(orchestrators):
            card = self._card_widgets.get(agent.role_id)
            if card is None:
                card = AgentCardWidget(self.orchestrator_grid, on_action=self.on_action)
                self._card_widgets[agent.role_id] = card
            card.update_agent(agent)
            card.grid(row=index, column=0, padx=Theme.SPACE_XS, pady=Theme.SPACE_XS, sticky="nsew")

        for index, agent in enumerate(role_agents):
            card = self._card_widgets.get(agent.role_id)
            if card is None:
                card = AgentCardWidget(self.cards_grid, on_action=self.on_action)
                self._card_widgets[agent.role_id] = card
            card.update_agent(agent)
            card.grid(row=index // 3, column=index % 3, padx=6, pady=6, sticky="nsew")

    def _trigger_action(self, action: str, profile: Dict[str, Any]):
        if self.on_action:
            self.on_action(action, profile)
