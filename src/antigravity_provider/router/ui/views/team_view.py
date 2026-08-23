"""Hermes Hub — Team View (Команда агентов и Dashboard с Unified Health v3)."""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional
import tkinter as tk
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
from antigravity_provider.router.auto_assigner import AutoAssigner
from antigravity_provider.router.event_bus import (
    EVENT_ACCOUNT_ADDED,
    EVENT_ACCOUNT_AUTH_CHANGED,
    EVENT_ACCOUNT_REMOVED,
    EVENT_ACCOUNT_UPDATED,
    EVENT_QUOTA_UPDATED,
    EVENT_ROUTING_UPDATED,
    EventBus,
)
from antigravity_provider.router.router_config import load_router_config
from antigravity_provider.router.ui.routing_graph import EDGE_TYPES, GraphIssue, RoutingGraphController


def persist_role_chain(role_id: str, desired_chain: List[str]) -> tuple[bool, str]:
    """Persist one ordered chain using AutoAssigner while preserving other roles."""
    config = load_router_config()
    policy = config.roles.get(role_id)
    if policy is None:
        return False, f"Роль '{role_id}' не найдена"
    if len(desired_chain) != len(set(desired_chain)):
        return False, "Профиль не может повторяться в одной цепочке"
    missing = [profile_id for profile_id in desired_chain if profile_id not in config.profiles]
    if missing:
        return False, f"Профиль '{missing[0]}' не найден"

    original = {key: list(value.preferred_chain) for key, value in config.roles.items()}
    removed = set(original[role_id]) - set(desired_chain)
    affected = {role_id}
    for profile_id in removed:
        affected.update(key for key, chain in original.items() if profile_id in chain)
        ok, message = AutoAssigner.assign_profile_to_role(profile_id, "spare", is_primary=False)
        if not ok:
            return False, message

    chains = {key: original[key] for key in affected}
    chains[role_id] = list(desired_chain)
    for target_role, chain in chains.items():
        for profile_id in reversed(chain):
            ok, message = AutoAssigner.assign_profile_to_role(profile_id, target_role, is_primary=True)
            if not ok:
                return False, message
    return True, f"Цепочка '{role_id}' сохранена"


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

        self.orch_pill = ctk.CTkFrame(self.line1, fg_color=Theme.ACCENT_DIM, corner_radius=Theme.RADIUS_SM)
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
        self._bind_settings_click(self)
        try:
            self._canvas.configure(takefocus=1)
        except (AttributeError, tk.TclError):
            pass
        self.bind("<Return>", self._open_settings, add="+")
        self.bind("<space>", self._open_settings, add="+")
        self.bind("<Enter>", self._hover_on, add="+")
        self.bind("<Leave>", self._hover_off, add="+")

    def _bind_settings_click(self, widget: Any) -> None:
        if isinstance(widget, ctk.CTkButton):
            return
        widget.configure(cursor="hand2")
        widget.bind("<Button-1>", self._open_settings, add="+")
        for child in widget.winfo_children():
            self._bind_settings_click(child)

    def _open_settings(self, _event: Any = None) -> None:
        if not self.agent_data or not self.on_action:
            return
        agent = self.agent_data
        self.on_action(
            "agent_settings",
            {
                "role_id": agent.role_id,
                "profile_id": agent.assigned_profile_id or "",
                "provider": agent.provider,
            },
        )

    def _hover_on(self, _event: Any = None) -> None:
        self.configure(fg_color=Theme.SURFACE_HOVER, border_color=Theme.BORDER_HOVER)

    def _hover_off(self, _event: Any = None) -> None:
        is_orchestrator = bool(self.agent_data and self.agent_data.is_main_orchestrator)
        self.configure(
            fg_color=Theme.SURFACE,
            border_color=Theme.BORDER_ACCENT if is_orchestrator else Theme.BORDER,
        )

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
            self.prov_lbl.configure(text="Claude", text_color=Theme.PROVIDER_CLAUDE)
        elif "grok" in prov or "xai" in prov:
            self.prov_lbl.configure(text="Grok", text_color=Theme.PROVIDER_GROK)
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
        quota_label = a.active_quota_label or "Н/Д — провайдер не отдал лимиты"
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
    """Interactive canvas over the existing router role/profile chains."""

    NODE_W = 218
    NODE_H = 104

    def __init__(
        self, master: Any, app_state: Optional[Dict[str, Any]] = None, on_action: Optional[Callable] = None, **kwargs
    ):
        super().__init__(master=master, fg_color="transparent", **kwargs)
        self.app_state = app_state or {}
        self.on_action = on_action
        self.controller = RoutingGraphController()
        self.snapshot: Optional[HubSnapshot] = None
        self._live_pipelines: Dict[str, Any] = {}
        self._quota_overrides: Dict[str, Any] = {}
        self.selected_role = "orchestrator"
        self.selected_edge = ""
        self._drag_role = ""
        self._drag_origin = (0.0, 0.0)
        self._drag_node_origin = (0.0, 0.0)
        self._drag_moved = False
        self._node_items: Dict[str, tuple[int, ...]] = {}
        self._edge_items: Dict[str, tuple[int, ...]] = {}
        self._event_bus = EventBus.get()
        self._subscribed = False
        self._build_static_layout()
        self._subscribe_runtime_events()
        self._draw_graph(rebuild=True)
        self.after(20, self._restore_viewport)

    def destroy(self):
        if self._subscribed:
            for name in self._runtime_events():
                self._event_bus.unsubscribe(name, self._on_runtime_event)
            self._subscribed = False
        super().destroy()

    @staticmethod
    def _runtime_events() -> tuple[str, ...]:
        return (
            EVENT_ROUTING_UPDATED,
            EVENT_QUOTA_UPDATED,
            EVENT_ACCOUNT_ADDED,
            EVENT_ACCOUNT_UPDATED,
            EVENT_ACCOUNT_REMOVED,
            EVENT_ACCOUNT_AUTH_CHANGED,
        )

    def _subscribe_runtime_events(self) -> None:
        if self._subscribed:
            return
        for name in self._runtime_events():
            self._event_bus.subscribe(name, self._on_runtime_event)
        self._subscribed = True

    def _build_static_layout(self) -> None:
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=Theme.PAGE_PAD_X, pady=(12, 8))
        titles = ctk.CTkFrame(header, fg_color="transparent")
        titles.pack(side="left")
        ctk.CTkLabel(titles, text="Граф маршрутизации", font=Theme.font_title_page(), text_color=Theme.TEXT_PRIMARY).pack(
            anchor="w"
        )
        self.state_label = ctk.CTkLabel(
            titles, text="Роли и реальные failover-цепочки", font=Theme.font_caption(), text_color=Theme.TEXT_MUTED
        )
        self.state_label.pack(anchor="w")
        actions = ctk.CTkFrame(header, fg_color="transparent")
        actions.pack(side="right")
        for text, command in (
            ("↶", self._undo),
            ("↷", self._redo),
            ("Авто", self._auto_layout),
            ("Вписать", self.fit_to_screen),
            ("Сохранить", self._save),
        ):
            HubButton(actions, text=text, variant="primary" if text == "Сохранить" else "secondary", command=command).pack(
                side="left", padx=3
            )

        toolbar = ctk.CTkFrame(self, fg_color=Theme.SURFACE, corner_radius=Theme.RADIUS_SM)
        toolbar.pack(fill="x", padx=Theme.PAGE_PAD_X, pady=(0, 7))
        self.search = ctk.CTkEntry(toolbar, placeholder_text="Найти роль или профиль…", width=250)
        self.search.pack(side="left", padx=8, pady=6)
        self.search.bind("<Return>", self._search)
        ctk.CTkLabel(toolbar, text="Связь", font=Theme.font_caption(), text_color=Theme.TEXT_MUTED).pack(
            side="left", padx=(8, 4)
        )
        self.edge_type = ctk.CTkOptionMenu(toolbar, values=list(EDGE_TYPES), width=112)
        self.edge_type.set("DELEGATE")
        self.edge_type.pack(side="left", pady=6)
        roles = [node.role_id for node in self.controller.graph.nodes] or ["orchestrator"]
        self.edge_target = ctk.CTkOptionMenu(toolbar, values=roles, width=135)
        self.edge_target.set(next((role for role in roles if role != self.selected_role), roles[0]))
        self.edge_target.pack(side="left", padx=(5, 0), pady=6)
        profile_ids = list(load_router_config().profiles) or ["—"]
        self.edge_profile = ctk.CTkOptionMenu(toolbar, values=["—", *profile_ids], width=140)
        self.edge_profile.set("—")
        self.edge_profile.pack(side="left", padx=(5, 0), pady=6)
        HubButton(toolbar, text="Соединить", variant="secondary", command=self._connect_selected).pack(
            side="left", padx=5
        )
        HubButton(toolbar, text="Изменить", variant="secondary", command=self._change_selected_edge).pack(
            side="left", padx=(0, 5)
        )
        self.zoom_label = ctk.CTkLabel(toolbar, text="100%", font=Theme.font_caption(), text_color=Theme.TEXT_SECONDARY)
        self.zoom_label.pack(side="right", padx=10)

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=Theme.PAGE_PAD_X, pady=(0, Theme.PAGE_PAD_Y))
        body.grid_rowconfigure(0, weight=1)
        body.grid_columnconfigure(0, weight=4)
        body.grid_columnconfigure(1, weight=1)
        canvas_frame = ctk.CTkFrame(body, fg_color=Theme.SURFACE_MUTED, border_width=1, border_color=Theme.BORDER)
        canvas_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        self.canvas = tk.Canvas(
            canvas_frame,
            bg=Theme.SURFACE_MUTED,
            highlightthickness=0,
            xscrollincrement=1,
            yscrollincrement=1,
            scrollregion=(0, 0, 1800, 1200),
        )
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.canvas.bind("<MouseWheel>", self._on_zoom)
        self.canvas.bind("<ButtonPress-2>", self._start_pan)
        self.canvas.bind("<B2-Motion>", self._pan)
        self.canvas.bind("<ButtonRelease-2>", self._end_pan)
        self.canvas.bind("<Control-z>", lambda _e: self._undo())
        self.canvas.bind("<Control-y>", lambda _e: self._redo())
        self.canvas.bind("<Delete>", self._delete_selected_edge)
        self.canvas.focus_set()

        self.minimap = tk.Canvas(canvas_frame, width=155, height=95, bg=Theme.SURFACE, highlightthickness=1)
        self.minimap.place(relx=1.0, rely=1.0, x=-12, y=-12, anchor="se")

        self.inspector = ctk.CTkFrame(body, fg_color=Theme.SURFACE, border_width=1, border_color=Theme.BORDER)
        self.inspector.grid(row=0, column=1, sticky="nsew")
        self.inspector_title = ctk.CTkLabel(
            self.inspector, text="Инспектор роли", font=Theme.font_heading(), text_color=Theme.TEXT_PRIMARY
        )
        self.inspector_title.pack(anchor="w", padx=12, pady=(12, 2))
        self.inspector_status = ctk.CTkLabel(
            self.inspector, text="", justify="left", anchor="w", font=Theme.font_caption(), text_color=Theme.TEXT_MUTED
        )
        self.inspector_status.pack(fill="x", padx=12, pady=(0, 8))
        self.chain_frame = ctk.CTkScrollableFrame(self.inspector, fg_color="transparent")
        self.chain_frame.pack(fill="both", expand=True, padx=8)
        HubButton(
            self.inspector,
            text="Открыть маршрутизацию",
            variant="primary",
            command=lambda: self._trigger_action("open_routing", {"role_id": self.selected_role}),
        ).pack(fill="x", padx=10, pady=10)

    def _world(self, x: float, y: float) -> tuple[float, float]:
        zoom = self.controller.graph.zoom
        return self.canvas.canvasx(x) / zoom, self.canvas.canvasy(y) / zoom

    def _on_press(self, event: Any) -> None:
        item = self.canvas.find_closest(self.canvas.canvasx(event.x), self.canvas.canvasy(event.y))
        tags = self.canvas.gettags(item)
        edge = next((tag[5:] for tag in tags if tag.startswith("edge:")), "")
        if edge:
            self.selected_edge = edge
            selected = next((item for item in self.controller.graph.edges if item.edge_id == edge), None)
            if selected:
                self.edge_type.set(selected.edge_type)
                self.edge_target.set(selected.target)
                self.edge_profile.set(selected.profile_id or "—")
            self._draw_graph(rebuild=True)
            return
        role = next((tag[5:] for tag in tags if tag.startswith("role:")), "")
        if role:
            self.selected_role = role
            self.selected_edge = ""
            self._drag_role = role
            self._drag_moved = False
            self._drag_origin = self._world(event.x, event.y)
            node = next((item for item in self.controller.graph.nodes if item.role_id == role), None)
            self._drag_node_origin = (node.x, node.y) if node else (0.0, 0.0)
            self._update_inspector()
            self._update_live_styles()

    def _on_drag(self, event: Any) -> None:
        if not self._drag_role:
            return
        node = next((n for n in self.controller.graph.nodes if n.role_id == self._drag_role), None)
        if not node:
            return
        x, y = self._world(event.x, event.y)
        dx, dy = x - self._drag_origin[0], y - self._drag_origin[1]
        if abs(dx) + abs(dy) > 1.5:
            self._drag_moved = True
        self._drag_origin = (x, y)
        node.x += dx
        node.y += dy
        self.controller.dirty = True
        self._draw_graph(rebuild=True)

    def _on_release(self, _event: Any) -> None:
        if self._drag_role:
            clicked_role = self._drag_role
            node = next((n for n in self.controller.graph.nodes if n.role_id == self._drag_role), None)
            if node:
                final_x, final_y = node.x, node.y
                node.x, node.y = self._drag_node_origin
                self.controller.move_node(node.role_id, final_x, final_y)
            self._drag_role = ""
            self._set_dirty_text()
            if not self._drag_moved and self.on_action:
                pipeline = self._pipeline_for(clicked_role)
                active_profile = pipeline.active_profile_id if pipeline else ""
                active_node = next(
                    (item for item in list(getattr(pipeline, "nodes", []) or []) if item.profile_id == active_profile),
                    None,
                )
                self.on_action(
                    "agent_settings",
                    {
                        "role_id": clicked_role,
                        "profile_id": active_profile,
                        "provider": getattr(active_node, "provider", ""),
                    },
                )

    def _on_zoom(self, event: Any) -> str:
        factor = 1.1 if event.delta > 0 else 0.9
        self.controller.graph.zoom = max(0.45, min(1.8, self.controller.graph.zoom * factor))
        self.controller.dirty = True
        self._draw_graph(rebuild=True)
        self._set_dirty_text()
        return "break"

    def _start_pan(self, event: Any) -> None:
        self.canvas.scan_mark(event.x, event.y)

    def _pan(self, event: Any) -> None:
        self.canvas.scan_dragto(event.x, event.y, gain=1)

    def _end_pan(self, _event: Any) -> None:
        zoom = self.controller.graph.zoom
        self.controller.graph.viewport_x = self.canvas.canvasx(0) / zoom
        self.controller.graph.viewport_y = self.canvas.canvasy(0) / zoom
        self.controller.dirty = True
        self._set_dirty_text()

    def _restore_viewport(self) -> None:
        graph = self.controller.graph
        z = graph.zoom
        self.canvas.xview_moveto(max(0.0, graph.viewport_x * z / 1800.0))
        self.canvas.yview_moveto(max(0.0, graph.viewport_y * z / 1200.0))

    def _node_coords(self, role_id: str) -> tuple[float, float, float, float]:
        node = next(item for item in self.controller.graph.nodes if item.role_id == role_id)
        z = self.controller.graph.zoom
        return node.x * z, node.y * z, (node.x + self.NODE_W) * z, (node.y + self.NODE_H) * z

    def _draw_graph(self, rebuild: bool = True) -> None:
        if rebuild:
            self.canvas.delete("all")
            self._node_items.clear()
            self._edge_items.clear()
        z = self.controller.graph.zoom
        for edge in self.controller.graph.edges:
            try:
                sx1, sy1, sx2, sy2 = self._node_coords(edge.source)
                tx1, ty1, _tx2, ty2 = self._node_coords(edge.target)
            except StopIteration:
                continue
            start = (sx2, (sy1 + sy2) / 2)
            end = (tx1, (ty1 + ty2) / 2)
            dash = () if edge.edge_type == "PRIMARY" else (7, 4) if edge.edge_type == "FALLBACK" else (2, 4)
            width = 3 if edge.edge_type == "PRIMARY" else 2
            line = self.canvas.create_line(
                *start,
                *end,
                smooth=True,
                arrow="last",
                width=width,
                dash=dash,
                fill=Theme.ACCENT if edge.edge_id == self.selected_edge else Theme.TEXT_ACCENT,
                tags=(f"edge:{edge.edge_id}", "edge"),
            )
            label = self.canvas.create_text(
                (start[0] + end[0]) / 2,
                (start[1] + end[1]) / 2 - 9,
                text=edge.edge_type,
                fill=Theme.TEXT_MUTED,
                font=("Segoe UI", max(7, int(8 * z)), "bold"),
                tags=(f"edge:{edge.edge_id}", "edge"),
            )
            self._edge_items[edge.edge_id] = (line, label)
        config = load_router_config()
        for node in self.controller.graph.nodes:
            x1, y1, x2, y2 = self._node_coords(node.role_id)
            pipeline = self._pipeline_for(node.role_id)
            active = pipeline.active_profile_id if pipeline else ""
            chain = list(config.roles.get(node.role_id).preferred_chain) if node.role_id in config.roles else []
            selected = node.role_id == self.selected_role
            rect = self.canvas.create_rectangle(
                x1,
                y1,
                x2,
                y2,
                width=2 if selected else 1,
                outline=Theme.ACCENT if selected else Theme.BORDER,
                fill=Theme.SURFACE,
                tags=(f"role:{node.role_id}", "node"),
            )
            title = self.canvas.create_text(
                x1 + 12 * z,
                y1 + 17 * z,
                anchor="w",
                text=node.label or node.role_id,
                fill=Theme.TEXT_PRIMARY,
                font=("Segoe UI", max(9, int(11 * z)), "bold"),
                tags=(f"role:{node.role_id}", "node"),
            )
            active_text = f"Активен: {active}" if active else "Активный профиль: Н/Д"
            meta = self.canvas.create_text(
                x1 + 12 * z,
                y1 + 43 * z,
                anchor="w",
                text=active_text,
                fill=Theme.STATUS_HEALTHY if active else Theme.TEXT_MUTED,
                font=("Segoe UI", max(7, int(8 * z))),
                tags=(f"role:{node.role_id}", "node"),
            )
            chain_text = " → ".join(chain[:3]) if chain else "Нет профилей"
            chain_item = self.canvas.create_text(
                x1 + 12 * z,
                y1 + 68 * z,
                anchor="w",
                width=(self.NODE_W - 24) * z,
                text=chain_text,
                fill=Theme.TEXT_SECONDARY,
                font=("Segoe UI", max(7, int(8 * z))),
                tags=(f"role:{node.role_id}", "node"),
            )
            self._node_items[node.role_id] = (rect, title, meta, chain_item)
        self.zoom_label.configure(text=f"{self.controller.graph.zoom * 100:.0f}%")
        bounds = self.canvas.bbox("all")
        if bounds:
            self.canvas.configure(scrollregion=(0, 0, max(1800, bounds[2] + 120), max(1200, bounds[3] + 120)))
        self._draw_minimap()
        self._update_inspector()

    def _draw_minimap(self) -> None:
        self.minimap.delete("all")
        if not self.controller.graph.nodes:
            return
        max_x = max(node.x for node in self.controller.graph.nodes) + self.NODE_W
        max_y = max(node.y for node in self.controller.graph.nodes) + self.NODE_H
        scale = min(145 / max(max_x, 1), 85 / max(max_y, 1))
        for node in self.controller.graph.nodes:
            self.minimap.create_rectangle(
                5 + node.x * scale,
                5 + node.y * scale,
                5 + (node.x + self.NODE_W) * scale,
                5 + (node.y + self.NODE_H) * scale,
                outline=Theme.ACCENT if node.role_id == self.selected_role else Theme.BORDER,
                fill=Theme.SURFACE_MUTED,
            )

    def _update_inspector(self) -> None:
        for child in self.chain_frame.winfo_children():
            child.destroy()
        role = self.selected_role
        pipeline = self._pipeline_for(role)
        node = next((item for item in self.controller.graph.nodes if item.role_id == role), None)
        self.inspector_title.configure(text=node.label if node else role)
        self.inspector_status.configure(
            text=(
                f"Активный: {pipeline.active_profile_id}"
                if pipeline and pipeline.active_profile_id
                else "Активный: Н/Д — профиль не назначен"
            )
        )
        config = load_router_config()
        policy = config.roles.get(role)
        chain = list(policy.preferred_chain) if policy else []
        live_nodes = {item.profile_id: item for item in pipeline.nodes} if pipeline else {}
        for index, profile_id in enumerate(chain):
            profile = config.profiles.get(profile_id)
            live = live_nodes.get(profile_id)
            card = HubCard(self.chain_frame)
            card.pack(fill="x", pady=4)
            rank = "PRIMARY" if index == 0 else f"FALLBACK {index}"
            ctk.CTkLabel(card, text=rank, font=Theme.font_micro(), text_color=Theme.TEXT_ACCENT).pack(
                anchor="w", padx=8, pady=(6, 0)
            )
            ctk.CTkLabel(
                card, text=profile_id, font=Theme.font_body_bold(), text_color=Theme.TEXT_PRIMARY
            ).pack(anchor="w", padx=8)
            provider = profile.provider if profile else "Н/Д — аккаунт не подключён"
            model = live.model if live else (
                profile.preferred_models[0]
                if profile and profile.preferred_models
                else "Н/Д — список моделей ещё не получен"
            )
            identity = live.account_identity if live and live.account_identity else "Аккаунт: Н/Д"
            quota = live.quota_status if live else "Н/Д — аккаунт не подключён"
            if profile_id in self._quota_overrides:
                raw_quota = self._quota_overrides[profile_id]
                quota = getattr(raw_quota, "status", None) or getattr(raw_quota, "quota_status", None) or quota
            if str(quota).strip().lower() in {"", "unknown", "none", "not_configured"}:
                quota = "Н/Д — провайдер не отдал лимиты"
            reason = live.failover_reason if live and live.failover_reason else "переключений ещё не было"
            ctk.CTkLabel(
                card,
                text=f"{provider} • {model}\n{identity}\nКвота: {quota}\nFailover: {reason}",
                justify="left",
                anchor="w",
                font=Theme.font_micro(),
                text_color=Theme.TEXT_SECONDARY,
            ).pack(fill="x", padx=8, pady=(2, 7))
            controls = ctk.CTkFrame(card, fg_color="transparent")
            controls.pack(fill="x", padx=6, pady=(0, 6))
            HubButton(
                controls,
                text="↑",
                variant="secondary",
                width=34,
                height=26,
                command=lambda pid=profile_id: self._move_chain_profile(pid, -1),
            ).pack(side="left", padx=2)
            HubButton(
                controls,
                text="↓",
                variant="secondary",
                width=34,
                height=26,
                command=lambda pid=profile_id: self._move_chain_profile(pid, 1),
            ).pack(side="left", padx=2)
            HubButton(
                controls,
                text="Удалить",
                variant="ghost",
                width=76,
                height=26,
                command=lambda pid=profile_id: self._remove_chain_profile(pid),
            ).pack(side="right", padx=2)
        if not chain:
            ctk.CTkLabel(
                self.chain_frame, text="Профили не назначены", font=Theme.font_caption(), text_color=Theme.STATUS_WARNING
            ).pack(anchor="w", padx=6, pady=8)

        available = [profile_id for profile_id in config.profiles if profile_id not in chain]
        add_row = ctk.CTkFrame(self.chain_frame, fg_color="transparent")
        add_row.pack(fill="x", pady=(8, 2))
        add_menu = ctk.CTkOptionMenu(
            add_row,
            values=available or ["—"],
            font=Theme.font_caption(),
            fg_color=Theme.SURFACE_MUTED,
            button_color=Theme.SECONDARY,
            button_hover_color=Theme.SURFACE_HOVER,
            text_color=Theme.TEXT_PRIMARY,
        )
        add_menu.pack(side="left", fill="x", expand=True, padx=(0, 4))
        HubButton(
            add_row,
            text="Добавить",
            variant="secondary",
            width=88,
            command=lambda: self._add_chain_profile(add_menu.get()),
            state="normal" if available else "disabled",
        ).pack(side="right")

    def _persist_selected_chain(self, chain: List[str]) -> None:
        ok, message = persist_role_chain(self.selected_role, chain)
        self.state_label.configure(text=message, text_color=Theme.STATUS_HEALTHY if ok else Theme.STATUS_ERROR)
        if ok:
            self._update_inspector()

    def _move_chain_profile(self, profile_id: str, direction: int) -> None:
        chain = list(self.controller.role_chain(self.selected_role))
        if profile_id not in chain:
            return
        source = chain.index(profile_id)
        target = source + direction
        if target < 0 or target >= len(chain):
            self.state_label.configure(text="Профиль уже на границе цепочки", text_color=Theme.STATUS_WARNING)
            return
        chain[source], chain[target] = chain[target], chain[source]
        self._persist_selected_chain(chain)

    def _remove_chain_profile(self, profile_id: str) -> None:
        chain = [item for item in self.controller.role_chain(self.selected_role) if item != profile_id]
        self._persist_selected_chain(chain)

    def _add_chain_profile(self, profile_id: str) -> None:
        if not profile_id or profile_id == "—":
            return
        chain = list(self.controller.role_chain(self.selected_role))
        if profile_id not in chain:
            chain.append(profile_id)
        self._persist_selected_chain(chain)

    def _on_runtime_event(self, name: str, data: Any) -> None:
        # EventBus may publish from a worker. Tk mutation is always marshalled.
        try:
            self.after(0, lambda: self._apply_runtime_event(name, data))
        except Exception:
            pass

    def _apply_runtime_event(self, name: str, data: Any) -> None:
        payload = data if isinstance(data, dict) else {}
        if name == EVENT_ROUTING_UPDATED and payload.get("pipeline") is not None:
            self._live_pipelines[str(payload.get("role_id", ""))] = payload["pipeline"]
        elif name == EVENT_QUOTA_UPDATED and payload.get("profile_id"):
            self._quota_overrides[str(payload["profile_id"])] = payload.get("quota_snapshot") or payload.get("snapshot")
        self._update_live_styles()

    def _pipeline_for(self, role_id: str) -> Any:
        if role_id in self._live_pipelines:
            return self._live_pipelines[role_id]
        return self.snapshot.routing.get(role_id) if self.snapshot else None

    def _update_live_styles(self) -> None:
        """Update existing canvas items; runtime events never rebuild the canvas."""
        if not self.snapshot:
            return
        for role_id, items in self._node_items.items():
            pipeline = self._pipeline_for(role_id)
            active = pipeline.active_profile_id if pipeline else ""
            self.canvas.itemconfigure(items[0], outline=Theme.ACCENT if role_id == self.selected_role else Theme.BORDER)
            self.canvas.itemconfigure(items[2], text=f"Активен: {active}" if active else "Активный профиль: Н/Д")
        self._update_inspector()

    def update_data(self, snapshot: Optional[Any] = None) -> None:
        if not isinstance(snapshot, HubSnapshot):
            return
        self.snapshot = snapshot
        self._live_pipelines = {
            role_id: pipeline
            for role_id, pipeline in self._live_pipelines.items()
            if role_id in snapshot.routing and pipeline is not snapshot.routing[role_id]
        }
        if set(snapshot.routing) != set(self._node_items):
            self._draw_graph(rebuild=True)
        else:
            self._update_live_styles()

    def _search(self, _event: Any = None) -> str:
        query = self.search.get().strip().lower()
        config = load_router_config()
        for node in self.controller.graph.nodes:
            chain = config.roles.get(node.role_id).preferred_chain if node.role_id in config.roles else []
            if query in node.role_id.lower() or query in node.label.lower() or any(query in item.lower() for item in chain):
                self.selected_role = node.role_id
                self._draw_graph(rebuild=True)
                break
        return "break"

    def focus_role(self, role_id: str) -> None:
        """Select a role when Routing delegates editing to this single editor."""
        if not any(node.role_id == role_id for node in self.controller.graph.nodes):
            self.state_label.configure(text=f"Роль {role_id} не найдена", text_color=Theme.STATUS_WARNING)
            return
        self.selected_role = role_id
        self.selected_edge = ""
        target = next((node.role_id for node in self.controller.graph.nodes if node.role_id != role_id), role_id)
        self.edge_target.set(target)
        self._draw_graph(rebuild=True)
        self.state_label.configure(text=f"Редактируется цепочка: {role_id}", text_color=Theme.TEXT_ACCENT)

    def _connect_selected(self) -> None:
        if len(self.controller.graph.nodes) < 2:
            return
        source = self.selected_role
        target = self.edge_target.get()
        profile_id = self.edge_profile.get()
        profile_id = "" if profile_id == "—" else profile_id
        ok, message = self.controller.add_edge(source, target, self.edge_type.get(), profile_id)
        self.state_label.configure(text=message, text_color=Theme.STATUS_HEALTHY if ok else Theme.STATUS_ERROR)
        self._draw_graph(rebuild=True)
        self._set_dirty_text()

    def _change_selected_edge(self) -> None:
        if not self.selected_edge:
            self.state_label.configure(text="Сначала выберите связь на графе", text_color=Theme.STATUS_WARNING)
            return
        profile_id = self.edge_profile.get()
        ok, message = self.controller.set_edge_type(
            self.selected_edge,
            self.edge_type.get(),
            "" if profile_id == "—" else profile_id,
        )
        self.state_label.configure(text=message, text_color=Theme.STATUS_HEALTHY if ok else Theme.STATUS_ERROR)
        self._draw_graph(rebuild=True)
        self._set_dirty_text()

    def _delete_selected_edge(self, _event: Any = None) -> str:
        selected = self.canvas.find_withtag("current")
        edge_id = self.selected_edge
        if selected:
            edge_id = next((tag[5:] for tag in self.canvas.gettags(selected[0]) if tag.startswith("edge:")), "")
        if edge_id:
            self.controller.delete_edge(edge_id)
            self.selected_edge = ""
            self._draw_graph(rebuild=True)
            self._set_dirty_text()
        return "break"

    def _auto_layout(self) -> None:
        self.controller.auto_layout()
        self._draw_graph(rebuild=True)
        self._set_dirty_text()

    def _undo(self) -> None:
        if self.controller.undo():
            self._draw_graph(rebuild=True)
            self._set_dirty_text()

    def _redo(self) -> None:
        if self.controller.redo():
            self._draw_graph(rebuild=True)
            self._set_dirty_text()

    def fit_to_screen(self) -> None:
        if not self.controller.graph.nodes:
            return
        self.update_idletasks()
        max_x = max(node.x for node in self.controller.graph.nodes) + self.NODE_W
        max_y = max(node.y for node in self.controller.graph.nodes) + self.NODE_H
        self.controller.graph.zoom = max(0.45, min(1.4, min(self.canvas.winfo_width() / max_x, self.canvas.winfo_height() / max_y) * 0.9))
        self.controller.dirty = True
        self._draw_graph(rebuild=True)
        self._set_dirty_text()

    def _save(self) -> None:
        zoom = self.controller.graph.zoom
        self.controller.graph.viewport_x = self.canvas.canvasx(0) / zoom
        self.controller.graph.viewport_y = self.canvas.canvasy(0) / zoom
        issues = self.controller.save()
        if issues:
            self._show_issues(issues)
            return
        self.state_label.configure(text="Сохранено • позиции и масштаб переживут перезапуск", text_color=Theme.STATUS_HEALTHY)

    def _show_issues(self, issues: List[GraphIssue]) -> None:
        bad_nodes = {issue.node_id for issue in issues if issue.node_id}
        for role_id, items in self._node_items.items():
            self.canvas.itemconfigure(items[0], outline=Theme.STATUS_ERROR if role_id in bad_nodes else Theme.BORDER)
        message = " • ".join(issue.message for issue in issues[:3])
        if len(issues) > 3:
            message += f" • ещё {len(issues) - 3}"
        self.state_label.configure(text=message, text_color=Theme.STATUS_ERROR)

    def _set_dirty_text(self) -> None:
        self.state_label.configure(
            text="● Есть несохранённые изменения" if self.controller.dirty else "Роли и реальные failover-цепочки",
            text_color=Theme.STATUS_WARNING if self.controller.dirty else Theme.TEXT_MUTED,
        )

    def _trigger_action(self, action: str, profile: Dict[str, Any]) -> None:
        if self.on_action:
            self.on_action(action, profile)
