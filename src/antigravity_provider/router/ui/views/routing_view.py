"""Keyed failover-chain view driven exclusively by RolePipeline objects."""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional
import tkinter as tk

import customtkinter as ctk

from antigravity_provider.router.state_store import HubSnapshot
from antigravity_provider.router.ui.components import ActionButton, HubCard, RouteTargetWidget, SectionHeader
from antigravity_provider.router.ui.theme import Theme
from antigravity_provider.router.unified_health import RolePipeline


class RoutingRoleWidget(HubCard):
    def __init__(self, master: Any, pipeline: RolePipeline, on_action: Optional[Callable] = None, **kwargs):
        super().__init__(master, **kwargs)
        self.pipeline = pipeline
        self.on_action = on_action
        self._nodes: Dict[str, RouteTargetWidget] = {}
        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", padx=Theme.CARD_PAD_X, pady=(Theme.CARD_PAD_Y, Theme.SPACE_SM))
        self.title = ctk.CTkLabel(top, text="", font=Theme.font_heading(), text_color=Theme.TEXT_PRIMARY)
        self.title.pack(side="left")
        self.meta = ctk.CTkLabel(top, text="", font=Theme.font_caption(), text_color=Theme.TEXT_MUTED)
        self.meta.pack(side="left", padx=Theme.SPACE_SM)
        ActionButton(
            top,
            text="Изменить цепочку →",
            variant="secondary",
            width=90,
            command=lambda: self.on_action and self.on_action("edit_route", {"role_id": self.pipeline.role_id}),
        ).pack(side="right")
        self.chain = ctk.CTkFrame(self, fg_color=Theme.SURFACE_MUTED, corner_radius=Theme.RADIUS_SM)
        self.chain.pack(fill="x", padx=Theme.CARD_PAD_X)
        self.footer = ctk.CTkLabel(self, text="", font=Theme.font_caption(), text_color=Theme.TEXT_SECONDARY)
        self.footer.pack(anchor="w", padx=Theme.CARD_PAD_X, pady=(Theme.SPACE_SM, Theme.CARD_PAD_Y))
        self.update_from_pipeline(pipeline)

    def update_from_pipeline(self, pipeline: RolePipeline) -> None:
        self.pipeline = pipeline
        self.title.configure(text=pipeline.role_name_ru)
        affinity = "session affinity" if pipeline.session_affinity else "без affinity"
        self.meta.configure(text=f"{pipeline.default_model} • {affinity}")
        live = {node.profile_id for node in pipeline.nodes}
        for profile_id in list(self._nodes):
            if profile_id not in live:
                self._nodes.pop(profile_id).destroy()
        for index, node in enumerate(pipeline.nodes):
            rank = "Основной" if index == 0 else f"Резерв {index}"
            identity = f" • {node.account_identity}" if node.account_identity else ""
            subtitle = f"{node.provider} • {node.model}{identity}"
            widget = self._nodes.get(node.profile_id)
            if widget is None:
                widget = RouteTargetWidget(self.chain, rank, node.display_name, subtitle)
                self._nodes[node.profile_id] = widget
            widget.update_target(
                rank,
                node.display_name,
                subtitle,
                "active" if node.is_active else node.status,
                node.quota_status,
                node.failover_reason,
            )
            widget.grid(row=0, column=index, padx=Theme.SPACE_XS, pady=Theme.SPACE_SM, sticky="nsew")
            self.chain.grid_columnconfigure(index, weight=1)
        active = next((node for node in pipeline.nodes if node.is_active), None)
        reasons = [node.failover_reason for node in pipeline.nodes if node.failover_reason]
        self.footer.configure(
            text=(
                f"Активен: {active.display_name} • причина: {'; '.join(reasons) if reasons else 'переключений ещё не было'}"
                if active
                else "Активный узел: Н/Д — аккаунт не подключён либо все профили недоступны"
            )
        )


class RoutingView(ctk.CTkFrame):
    def __init__(
        self, master: Any, routing_data: Optional[Dict[str, Any]] = None, on_action: Optional[Callable] = None, **kwargs
    ):
        super().__init__(master=master, fg_color="transparent", **kwargs)
        self.on_action = on_action
        self._role_widgets: Dict[str, RoutingRoleWidget] = {}
        SectionHeader(
            self,
            title="Маршрутизация",
            subtitle="Основной → резерв 1 → резерв 2 → резерв 3; без выдуманных причин failover",
        ).pack(fill="x", padx=Theme.PAGE_PAD_X, pady=(Theme.PAGE_PAD_Y, Theme.SPACE_SM))
        self.scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.scroll.pack(fill="both", expand=True, padx=Theme.PAGE_PAD_X, pady=(0, Theme.PAGE_PAD_Y))

    def focus_role(self, role_id: str) -> None:
        """Focus the existing route editor/card selected in the graph inspector."""
        widget = self._role_widgets.get(role_id)
        if not widget:
            return
        for current in self._role_widgets.values():
            current.configure(border_color=Theme.BORDER)
        widget.configure(border_color=Theme.BORDER_ACCENT)
        try:
            self.scroll._parent_canvas.yview_moveto(max(0.0, widget.winfo_y() / max(1, self.scroll.winfo_height())))
        except (AttributeError, tk.TclError):
            pass

    def update_data(self, snapshot: Optional[HubSnapshot] = None) -> None:
        if not isinstance(snapshot, HubSnapshot):
            return
        live_roles = set(snapshot.routing)
        for role_id in list(self._role_widgets):
            if role_id not in live_roles:
                self._role_widgets.pop(role_id).destroy()
        for role_id, pipeline in snapshot.routing.items():
            widget = self._role_widgets.get(role_id)
            if widget is None:
                widget = RoutingRoleWidget(self.scroll, pipeline, self.on_action)
                widget.pack(fill="x", pady=Theme.SPACE_XS)
                self._role_widgets[role_id] = widget
            widget.update_from_pipeline(pipeline)
