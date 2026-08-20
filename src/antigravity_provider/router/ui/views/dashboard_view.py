"""Hermes Hub — Dashboard View (Главный экран)."""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional
import customtkinter as ctk

from antigravity_provider.router.ui.theme import Theme
from antigravity_provider.router.ui.components import (
    HubButton,
    HubCard,
    HubMetricCard,
    HubProviderBadge,
    HubSectionHeader,
    HubStatusBadge,
)


class DashboardView(ctk.CTkFrame):
    def __init__(self, master: Any, app_state: Dict[str, Any], on_navigate: Optional[Callable] = None, on_action: Optional[Callable] = None, **kwargs):
        super().__init__(master=master, fg_color="transparent", **kwargs)
        self.app_state = app_state
        self.on_navigate = on_navigate
        self.on_action = on_action
        self._build()

    def _build(self):
        # ── Header ──
        header = HubSectionHeader(
            self,
            title="Главная панель управления",
            subtitle="Multi-Agent & Multi-Provider Control Hub",
            action_text="+ Добавить аккаунт",
            action_cmd=lambda: self._trigger_action("add_account"),
        )
        header.pack(fill="x", padx=20, pady=(20, 16))

        scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=15, pady=(0, 10))

        data = self.app_state
        stats = data.get("stats", {})
        total_profiles = stats.get("total_profiles", 0)
        auth_profiles = stats.get("authenticated_profiles", 0)
        providers_data = data.get("providers", {})

        ag_list = providers_data.get("antigravity", [])
        codex_list = providers_data.get("openai-codex", [])
        opencode_list = providers_data.get("opencode-go", [])

        ag_online = sum(1 for p in ag_list if p.get("authenticated"))
        codex_online = sum(1 for p in codex_list if p.get("authenticated"))
        opencode_online = sum(1 for p in opencode_list if p.get("authenticated"))

        overall_state = "Healthy" if auth_profiles > 0 else "Degraded"

        # ── 1. Top Metrics (4 cards) ──
        metrics_grid = ctk.CTkFrame(scroll, fg_color="transparent")
        metrics_grid.pack(fill="x", pady=(0, 16))
        for i in range(4):
            metrics_grid.grid_columnconfigure(i, weight=1)

        m1 = HubMetricCard(metrics_grid, title="Агенты", value=str(total_profiles), subtext=f"{auth_profiles} активны в ролях", icon="👥", accent=True)
        m1.grid(row=0, column=0, padx=6, sticky="nsew")

        m2 = HubMetricCard(metrics_grid, title="Аккаунты", value=f"{auth_profiles}/{total_profiles}", subtext="Авторизовано", icon="🔑")
        m2.grid(row=0, column=1, padx=6, sticky="nsew")

        m3 = HubMetricCard(metrics_grid, title="Провайдеры", value="3", subtext="Antigravity, Codex, OpenCode", icon="🌐")
        m3.grid(row=0, column=2, padx=6, sticky="nsew")

        m4 = HubMetricCard(metrics_grid, title="Состояние", value=overall_state, subtext="Fail-closed router active", icon="🛡️")
        m4.grid(row=0, column=3, padx=6, sticky="nsew")

        # ── 2. Middle Row: Providers Status & Active Roles ──
        mid_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        mid_frame.pack(fill="x", pady=(0, 16))
        mid_frame.grid_columnconfigure(0, weight=1)
        mid_frame.grid_columnconfigure(1, weight=1)

        # 2A: Provider Status Breakdown
        prov_card = HubCard(mid_frame)
        prov_card.grid(row=0, column=0, padx=(0, 8), sticky="nsew")

        ctk.CTkLabel(prov_card, text="Состояние провайдеров", font=Theme.font_heading(), text_color=Theme.TEXT_PRIMARY).pack(anchor="w", padx=16, pady=(14, 10))

        prov_rows = [
            ("Google Antigravity", f"{ag_online} / {len(ag_list)} онлайн", Theme.PROVIDER_ANTIGRAVITY),
            ("OpenAI Codex", f"{codex_online} / {len(codex_list)} онлайн", Theme.PROVIDER_CODEX),
            ("OpenCode Go", f"{opencode_online} / {len(opencode_list)} онлайн", Theme.PROVIDER_OPENCODE),
        ]
        for name, status_txt, col in prov_rows:
            row = ctk.CTkFrame(prov_card, fg_color=Theme.SURFACE_MUTED, corner_radius=Theme.RADIUS_SM)
            row.pack(fill="x", padx=16, pady=4)
            ctk.CTkLabel(row, text=f"◈ {name}", font=Theme.font_body_bold(), text_color=col).pack(side="left", padx=10, pady=8)
            ctk.CTkLabel(row, text=status_txt, font=Theme.font_body(), text_color=Theme.TEXT_SECONDARY).pack(side="right", padx=10)

        # 2B: Core Leadership & Orchestrator
        lead_card = HubCard(mid_frame)
        lead_card.grid(row=0, column=1, padx=(8, 0), sticky="nsew")

        ctk.CTkLabel(lead_card, text="Ключевые назначения", font=Theme.font_heading(), text_color=Theme.TEXT_PRIMARY).pack(anchor="w", padx=16, pady=(14, 10))

        # Find main profile and orchestrator
        main_ag_id = data.get("main_profiles", {}).get("antigravity", "—")
        main_codex_id = data.get("main_profiles", {}).get("openai-codex", "—")

        key_items = [
            ("👑 Главный оркестратор", f"OpenAI Codex ({main_codex_id})", Theme.STATUS_ORCHESTRATOR),
            ("⭐ Основной Antigravity", f"Google Antigravity ({main_ag_id})", Theme.STATUS_MAIN),
            ("🔄 Резервный оркестратор", "Google Antigravity (ag-orch-fallback)", Theme.STATUS_FAILOVER),
        ]
        for title_str, val_str, clr in key_items:
            row = ctk.CTkFrame(lead_card, fg_color=Theme.SURFACE_MUTED, corner_radius=Theme.RADIUS_SM)
            row.pack(fill="x", padx=16, pady=4)
            ctk.CTkLabel(row, text=title_str, font=Theme.font_body_bold(), text_color=clr).pack(side="left", padx=10, pady=8)
            ctk.CTkLabel(row, text=val_str, font=Theme.font_caption(), text_color=Theme.TEXT_SECONDARY).pack(side="right", padx=10)

        # ── 3. Quick Actions Banner ──
        banner = HubCard(scroll, fg_color=Theme.DARK, border_color=Theme.BORDER_ACCENT)
        banner.pack(fill="x", pady=(0, 10))

        b_inner = ctk.CTkFrame(banner, fg_color="transparent")
        b_inner.pack(fill="x", padx=16, pady=14)

        b_text = ctk.CTkFrame(b_inner, fg_color="transparent")
        b_text.pack(side="left")
        ctk.CTkLabel(b_text, text="Управление маршрутизацией и отказоустойчивостью", font=Theme.font_heading(), text_color=Theme.TEXT_ACCENT).pack(anchor="w")
        ctk.CTkLabel(b_text, text="Автоматический failover при исчерпании квот и поддержка session affinity активны.", font=Theme.font_caption(), text_color=Theme.TEXT_SECONDARY).pack(anchor="w")

        b_btns = ctk.CTkFrame(b_inner, fg_color="transparent")
        b_btns.pack(side="right")
        HubButton(b_btns, text="Команда агентов", variant="secondary", command=lambda: self._navigate("team")).pack(side="left", padx=4)
        HubButton(b_btns, text="Маршрутизация", variant="secondary", command=lambda: self._navigate("routing")).pack(side="left", padx=4)

    def _navigate(self, target: str):
        if self.on_navigate:
            self.on_navigate(target)

    def _trigger_action(self, action: str):
        if self.on_action:
            self.on_action(action, {})
