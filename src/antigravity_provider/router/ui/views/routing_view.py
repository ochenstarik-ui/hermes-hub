"""Hermes Hub — Routing View (Визуализация цепочек маршрутизации и отказоустойчивости)."""
from __future__ import annotations

from typing import Any, Dict, List, Optional
import customtkinter as ctk

from antigravity_provider.router.ui.theme import Theme
from antigravity_provider.router.ui.components import (
    HubButton,
    HubCard,
    HubSectionHeader,
    HubStatusBadge,
)
from antigravity_provider.router.unified_health import (
    UnifiedHealthService,
    RolePipeline,
    STATUS_HEALTHY,
)


class RoutingView(ctk.CTkFrame):
    def __init__(self, master: Any, routing_data: Optional[Dict[str, Any]] = None, **kwargs):
        super().__init__(master=master, fg_color="transparent", **kwargs)
        self.routing_data = routing_data or {}
        self._build()

    def _build(self):
        header = HubSectionHeader(
            self,
            title="Маршрутизация и Цепочки Failover",
            subtitle="Политики выбора провайдеров для ролей агентов, приоритеты и сессионная привязка",
        )
        header.pack(fill="x", padx=20, pady=(16, 12))

        self.scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.scroll.pack(fill="both", expand=True, padx=15, pady=(0, 10))

        self.update_data()

    def update_data(self, routing_data: Optional[Dict[str, Any]] = None):
        for w in self.scroll.winfo_children():
            w.destroy()

        pipelines = UnifiedHealthService.get().get_routing_pipelines()

        for rname, pipe in pipelines.items():
            card = HubCard(self.scroll, border_color=Theme.BORDER, fg_color=Theme.SURFACE)
            card.pack(fill="x", pady=6)

            # Top Row
            top = ctk.CTkFrame(card, fg_color="transparent")
            top.pack(fill="x", padx=16, pady=(12, 4))

            ctk.CTkLabel(top, text=pipe.role_name_ru, font=Theme.font_heading(), text_color=Theme.TEXT_ACCENT).pack(side="left")
            ctk.CTkLabel(top, text=f"({pipe.role_id})", font=Theme.font_mono_sm(), text_color=Theme.TEXT_MUTED).pack(side="left", padx=(6, 0))

            affinity_str = "Session Affinity ON" if pipe.session_affinity else "Affinity OFF"
            ctk.CTkLabel(top, text=f"Модель: {pipe.default_model}  •  {affinity_str}", font=Theme.font_caption(), text_color=Theme.TEXT_SECONDARY).pack(side="right")

            # Pipeline Visualizer Row
            pipeline_box = ctk.CTkFrame(card, fg_color=Theme.SURFACE_MUTED, corner_radius=Theme.RADIUS_SM)
            pipeline_box.pack(fill="x", padx=16, pady=4)

            p_inner = ctk.CTkFrame(pipeline_box, fg_color="transparent")
            p_inner.pack(fill="x", padx=10, pady=8)

            for idx, node in enumerate(pipe.nodes):
                if idx > 0:
                    ctk.CTkLabel(p_inner, text=" ➔ ", font=("Segoe UI", 13, "bold"), text_color=Theme.TEXT_MUTED).pack(side="left", padx=2)

                node_border = Theme.BORDER_ACCENT if node.is_active else Theme.BORDER
                node_fg = Theme.DARK if node.is_active else Theme.SURFACE

                node_card = HubCard(p_inner, border_color=node_border, fg_color=node_fg, corner_radius=Theme.RADIUS_SM)
                node_card.pack(side="left", padx=2)

                n_top = ctk.CTkFrame(node_card, fg_color="transparent")
                n_top.pack(fill="x", padx=8, pady=(4, 2))

                dot_col = Theme.STATUS_HEALTHY if node.status == STATUS_HEALTHY else Theme.STATUS_WARNING
                ctk.CTkLabel(n_top, text="●", font=("Segoe UI", 10, "bold"), text_color=dot_col).pack(side="left", padx=(0, 4))
                ctk.CTkLabel(n_top, text=node.display_name, font=Theme.font_body_bold(), text_color=Theme.TEXT_PRIMARY).pack(side="left")

                rank_txt = "Primary" if idx == 0 else f"Fallback {idx}"
                ctk.CTkLabel(node_card, text=f"{rank_txt} • {node.provider}", font=Theme.font_micro(), text_color=Theme.TEXT_MUTED).pack(padx=8, pady=(0, 4), anchor="w")

            # Active Route Notice
            meta_row = ctk.CTkFrame(card, fg_color="transparent")
            meta_row.pack(fill="x", padx=16, pady=(4, 10))

            act_str = f"Текущий активный маршрут: [{pipe.active_profile_id}]" if pipe.active_profile_id else "Все маршруты исчерпаны!"
            act_col = Theme.TEXT_SECONDARY if pipe.active_profile_id else Theme.STATUS_ERROR
            ctk.CTkLabel(meta_row, text=act_str, font=Theme.font_caption(), text_color=act_col).pack(side="left")
            ctk.CTkLabel(meta_row, text=f"Максимум попыток failover: {pipe.max_failover}", font=Theme.font_micro(), text_color=Theme.TEXT_MUTED).pack(side="right")
