"""Hermes Hub — Routing View with Reusable Pipeline & Node Widgets."""
from __future__ import annotations

from typing import Any, Dict, List, Optional
import customtkinter as ctk

from antigravity_provider.router.ui.theme import Theme
from antigravity_provider.router.ui.assets import AssetManager
from antigravity_provider.router.ui.components import (
    HubCard,
    HubSectionHeader,
)
from antigravity_provider.router.unified_health import (
    RolePipeline,
    PipelineNode,
    STATUS_HEALTHY,
)
from antigravity_provider.router.state_store import HubStateStore, HubSnapshot
from antigravity_provider.router.event_bus import (
    EventBus,
    EVENT_ROUTING_UPDATED,
)


class RoutingRoleWidget(HubCard):
    """Reusable visual pipeline widget for a specific role."""

    def __init__(self, parent: Any, pipeline: RolePipeline, **kwargs):
        super().__init__(parent, border_color=Theme.BORDER, fg_color=Theme.SURFACE, **kwargs)
        self.pipeline = pipeline
        self._build()
        self.update_from_pipeline(pipeline)

    def _build(self):
        # 1. Top row
        self.top_row = ctk.CTkFrame(self, fg_color="transparent")
        self.top_row.pack(fill="x", padx=16, pady=(14, 4))

        self.title_lbl = ctk.CTkLabel(self.top_row, text="", font=Theme.font_heading(), text_color=Theme.TEXT_ACCENT)
        self.title_lbl.pack(side="left")

        self.role_id_lbl = ctk.CTkLabel(self.top_row, text="", font=Theme.font_mono_sm(), text_color=Theme.TEXT_MUTED)
        self.role_id_lbl.pack(side="left", padx=(8, 0))

        self.meta_top_lbl = ctk.CTkLabel(self.top_row, text="", font=Theme.font_caption(), text_color=Theme.TEXT_SECONDARY)
        self.meta_top_lbl.pack(side="right")

        # 2. Visualizer Box
        self.pipeline_box = ctk.CTkFrame(self, fg_color=Theme.SURFACE_MUTED, corner_radius=Theme.RADIUS_SM)
        self.pipeline_box.pack(fill="x", padx=16, pady=6)

        self.p_inner = ctk.CTkFrame(self.pipeline_box, fg_color="transparent")
        self.p_inner.pack(fill="x", padx=12, pady=10)

        # 3. Bottom status row
        self.bottom_row = ctk.CTkFrame(self, fg_color="transparent")
        self.bottom_row.pack(fill="x", padx=16, pady=(4, 12))

        self.act_route_lbl = ctk.CTkLabel(self.bottom_row, text="", font=Theme.font_caption())
        self.act_route_lbl.pack(side="left")

        self.failover_lbl = ctk.CTkLabel(self.bottom_row, text="", font=Theme.font_micro(), text_color=Theme.TEXT_MUTED)
        self.failover_lbl.pack(side="right")

    def update_from_pipeline(self, pipe: RolePipeline) -> None:
        self.pipeline = pipe

        self.title_lbl.configure(text=pipe.role_name_ru)
        self.role_id_lbl.configure(text=f"({pipe.role_id})")

        affinity_str = "Session Affinity ON" if pipe.session_affinity else "Affinity OFF"
        self.meta_top_lbl.configure(text=f"Модель: {pipe.default_model}  •  {affinity_str}")

        # Update nodes inside p_inner
        for w in self.p_inner.winfo_children():
            w.destroy()

        for idx, node in enumerate(pipe.nodes):
            if idx > 0:
                ctk.CTkLabel(self.p_inner, text=" ➔ ", font=("Segoe UI", 15, "bold"), text_color=Theme.TEXT_MUTED).pack(side="left", padx=4)

            node_border = Theme.BORDER_ACCENT if node.is_active else Theme.BORDER
            node_fg = Theme.DARK if node.is_active else Theme.SURFACE

            node_card = HubCard(self.p_inner, border_color=node_border, fg_color=node_fg, corner_radius=Theme.RADIUS_SM)
            node_card.pack(side="left", padx=2)

            n_top = ctk.CTkFrame(node_card, fg_color="transparent")
            n_top.pack(fill="x", padx=10, pady=(6, 2))

            p_img = AssetManager.get().get_provider_image(node.provider, size=(16, 16))
            if p_img:
                ctk.CTkLabel(n_top, image=p_img, text="").pack(side="left", padx=(0, 4))

            dot_col = Theme.STATUS_HEALTHY if node.status == STATUS_HEALTHY else Theme.STATUS_WARNING
            ctk.CTkLabel(n_top, text="●", font=("Segoe UI", 11, "bold"), text_color=dot_col).pack(side="left", padx=(0, 4))
            ctk.CTkLabel(n_top, text=node.display_name, font=Theme.font_body_bold(), text_color=Theme.TEXT_PRIMARY).pack(side="left")

            rank_txt = "Primary" if idx == 0 else f"Fallback {idx}"
            ctk.CTkLabel(node_card, text=f"{rank_txt} • {node.model}", font=Theme.font_micro(), text_color=Theme.TEXT_MUTED).pack(padx=10, pady=(0, 6), anchor="w")

        # Bottom Route Notice
        act_str = f"Текущий активный маршрут: [{pipe.active_profile_id}]" if pipe.active_profile_id else "Все маршруты исчерпаны!"
        act_col = Theme.TEXT_SECONDARY if pipe.active_profile_id else Theme.STATUS_ERROR
        self.act_route_lbl.configure(text=act_str, text_color=act_col)
        self.failover_lbl.configure(text=f"Максимум попыток failover: {pipe.max_failover}")


class RoutingView(ctk.CTkFrame):
    def __init__(self, master: Any, routing_data: Optional[Dict[str, Any]] = None, **kwargs):
        super().__init__(master=master, fg_color="transparent", **kwargs)
        self.routing_data = routing_data or {}
        self._role_widgets: Dict[str, RoutingRoleWidget] = {}
        self._last_rendered_generation = 0

        self._build()
        self._subscribe_events()

    def _subscribe_events(self):
        EventBus.get().subscribe(EVENT_ROUTING_UPDATED, self._on_routing_event)

    def _on_routing_event(self, event_name: str, payload: Any):
        self.after(0, self.update_data)

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

    def update_data(self, snapshot: Optional[HubSnapshot] = None):
        """Update routing view using cached snapshot and reusable role widgets."""
        if not isinstance(snapshot, HubSnapshot):
            # A non-snapshot (e.g. a legacy app_state dict) must fall back
            # to the store rather than crash the view.
            snapshot = HubStateStore.get().get_snapshot()

        self._last_rendered_generation = snapshot.generation
        pipelines = snapshot.routing

        for rname, pipe in pipelines.items():
            if rname in self._role_widgets:
                self._role_widgets[rname].update_from_pipeline(pipe)
            else:
                widget = RoutingRoleWidget(self.scroll, pipe)
                widget.pack(fill="x", pady=6)
                self._role_widgets[rname] = widget
