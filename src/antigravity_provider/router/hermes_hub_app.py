"""Hermes Hub — Native Windows Desktop Application (Stabilization & UX v3).

Features:
- Windows AppUserModelID (HermesHub.Desktop) for proper Taskbar Pinning & Identity
- High-Performance Sub-100ms Tab Switching (Persistent View Cache, Zero I/O on switch)
- Instrumentation: tab_switch_ms Logging & Benchmark Verification
- Debounced Resize & Movement Handling
- Unified Health Presentation (Strict Priority Resolver, No Stale Quota on Unadded Accounts)
- Real Provider Icon Marks (Google Antigravity, OpenAI Codex, OpenCode Go)
- Non-blocking Background Workers & Graceful Shutdown Coordinator
"""

from __future__ import annotations

import ctypes
import json
import logging
import os
import sys
import threading
import time
import webbrowser
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import customtkinter as ctk

# ── Set Windows AppUserModelID before UI initialization ──
if sys.platform == "win32":
    try:
        APP_ID = "HermesHub.Desktop"
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except Exception:
        pass

# ── Ensure plugin and repo paths are on sys.path ──
_SRC_DIR = Path(__file__).resolve().parent.parent.parent
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from antigravity_provider import paths
_hermes_home = paths.get_hermes_home()
_PLUGIN_SRC = _hermes_home / "plugins" / "antigravity-provider" / "src"
_AGENT_DIR = _hermes_home / "hermes-agent"
for _p in [_PLUGIN_SRC, _AGENT_DIR]:
    _ps = str(_p)
    if _p.exists() and _ps not in sys.path:
        sys.path.insert(0, _ps)

from antigravity_provider.router.router_config import load_router_config, save_router_config
from antigravity_provider.router.profile_manager import ProfileAuthManager
from antigravity_provider.router.auto_assigner import AutoAssigner
from antigravity_provider.router.adapters import get_adapter
# Единственная реализация действий живёт в action_handler: её используют
# и десктоп, и веб-API. Второй копии в проекте быть не должно.
from antigravity_provider.router.action_handler import (
    do_delete_credentials,
    do_save_settings,
    do_set_main,
    do_set_orchestrator,
    do_test_profile,
)
from antigravity_provider import paths
from antigravity_provider.version import __version__

from antigravity_provider.router.ui.theme import Theme
from antigravity_provider.router.ui.assets import AssetManager
from antigravity_provider.router.ui.components import AccountCardWidget, HubButton, HubModal
from antigravity_provider.router.ui.add_account_wizard import AddAccountWizard

from antigravity_provider.router.unified_health import (
    UnifiedHealthService,
    EventLogService,
    SystemReadiness,
    STATUS_HEALTHY,
)
from antigravity_provider.router.state_store import HubStateStore

from antigravity_provider.router.ui.views.team_view import TeamView, persist_role_chain
from antigravity_provider.router.ui.views.dashboard_view import DashboardView
from antigravity_provider.router.ui.views.accounts_view import AccountsView
from antigravity_provider.router.ui.views.providers_view import ProvidersView
from antigravity_provider.router.ui.views.routing_view import RoutingView
from antigravity_provider.router.ui.views.health_view import HealthView
from antigravity_provider.router.ui.views.logs_view import LogsView
from antigravity_provider.router.ui.views.settings_view import SettingsView
from antigravity_provider.router.ui.views.about_view import AboutView
from antigravity_provider.router.ui.views.analytics_view import AnalyticsView
from antigravity_provider.router.ui.model_catalog import get_cached_models, refresh_models_async

logger = logging.getLogger("hermes.hub.gui")

def _load_saved_theme() -> str:
    settings_file = paths.get_hermes_home() / "hub_settings.json"
    try:
        settings = json.loads(settings_file.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return "dark"
    return str(settings.get("theme", "dark"))


# ═══════════════════════════════════════════════════════════════
#  Actions Layer (Safe & Non-blocking)
# ═══════════════════════════════════════════════════════════════


class HermesHubApp(ctk.CTk):
    def __init__(self):
        self._theme_name = Theme.apply_scheme(_load_saved_theme())
        ctk.set_appearance_mode("dark" if self._theme_name == "dark" else "light")
        super().__init__()
        self.title("Hermes Hub")
        self.geometry("1380x880")
        self.minsize(1100, 700)

        ctk.set_default_color_theme("blue")
        self.configure(fg_color=Theme.BG_WINDOW)

        # Set Windows Multi-Resolution Icon
        ico_path = AssetManager.get().get_ico_path()
        if ico_path and os.path.exists(ico_path):
            try:
                self.iconbitmap(ico_path)
            except Exception:
                pass

        self._current_view = "overview"
        self._views: Dict[str, ctk.CTkFrame] = {}
        self._view_generations: Dict[str, int] = {}
        self._shutting_down = False
        self._resize_timer_id = None

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.bind("<Configure>", self._on_window_configure)

        self._build_layout()
        self._show_view("overview")

        try:
            from antigravity_provider.router.scheduler import HermesRefreshScheduler

            HermesRefreshScheduler.get().start()
        except Exception:
            pass

        try:
            from antigravity_provider.router.quota_collector import AccountQuotaService

            AccountQuotaService.get().start_background_scheduler()
        except Exception:
            pass

        self.after(50, self._refresh_data)
        self.after(800, self._refresh_quotas_on_startup)

    def _refresh_quotas_on_startup(self) -> None:
        """Populate measured quota cards immediately instead of after the 5-minute scheduler tick."""
        if self._shutting_down:
            return
        try:
            from antigravity_provider.router.scheduler import HermesRefreshScheduler

            HermesRefreshScheduler.get().trigger_refresh_all(on_complete=lambda: self.after(0, self._refresh_data))
        except Exception as exc:
            logger.warning("Initial quota refresh could not start: %s", exc)

    def _build_layout(self):
        # ── Sidebar (Left) ──
        self.sidebar = ctk.CTkFrame(self, width=Theme.WIDTH_SIDEBAR, fg_color=Theme.BG_SIDEBAR, corner_radius=0)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)

        # Top Centered Brand Logo
        brand_container = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        brand_container.pack(fill="x", padx=Theme.SPACE_MD, pady=(Theme.SPACE_LG, Theme.SPACE_SM))

        logo_img = AssetManager.get().get_logo_image(size=(78, 78))
        if logo_img:
            logo_lbl = ctk.CTkLabel(brand_container, image=logo_img, text="")
            logo_lbl.pack(anchor="center", pady=(0, 6))

        ctk.CTkLabel(
            brand_container,
            text="HERMES HUB",
            font=(Theme.FONT_FAMILY_TITLE, 17, "bold"),
            text_color=Theme.TEXT_ACCENT,
        ).pack(anchor="center")
        ctk.CTkFrame(self.sidebar, height=1, fg_color=Theme.BORDER_ACCENT).pack(
            fill="x", padx=Theme.SPACE_MD, pady=(Theme.SPACE_XS, Theme.SPACE_SM)
        )

        # Nav Items with clean Fluent glyphs
        self._nav_items = [
            ("overview", "Обзор", "overview"),
            ("team", "Команда", "team"),
            ("accounts", "Аккаунты", "accounts"),
            ("routing", "Маршрутизация", "routing"),
            ("providers", "Модели и провайдеры", "providers"),
            ("analytics", "Аналитика", "analytics"),
            ("health", "Состояние", "health"),
            ("logs", "Журнал событий", "logs"),
            ("settings", "Настройки", "settings"),
            ("about", "О программе", "about"),
        ]

        self.nav_frame = ctk.CTkScrollableFrame(
            self.sidebar,
            fg_color="transparent",
            corner_radius=0,
            scrollbar_fg_color=Theme.BG_SIDEBAR,
            scrollbar_button_color=Theme.BG_SIDEBAR,
            scrollbar_button_hover_color=Theme.BORDER_HOVER,
        )
        self.nav_frame.pack(fill="both", expand=True)
        self._nav_buttons: Dict[str, ctk.CTkButton] = {}
        for key, label, icon in self._nav_items:
            icon_image = AssetManager.get().get_nav_icon(icon, size=19)
            btn = ctk.CTkButton(
                self.nav_frame,
                text=label,
                image=icon_image,
                compound="left",
                font=Theme.font_body(),
                height=Theme.HEIGHT_NAV_ITEM,
                fg_color="transparent",
                hover_color=Theme.SIDEBAR_HOVER,
                text_color=Theme.SIDEBAR_TEXT,
                anchor="w",
                corner_radius=Theme.RADIUS_SM,
                command=lambda k=key: self._show_view(k),
            )
            btn.pack(fill="x", padx=Theme.SPACE_SM, pady=1)
            self._nav_buttons[key] = btn

        self.sidebar_version = ctk.CTkLabel(
            self.sidebar,
            text=f"Hermes Hub v{__version__}",
            font=Theme.font_micro(),
            text_color=Theme.SIDEBAR_MUTED,
        )
        self.sidebar_version.pack(side="bottom", pady=(0, Theme.SPACE_SM))
        user_card = ctk.CTkFrame(
            self.sidebar,
            fg_color=Theme.SIDEBAR_SELECTED,
            border_width=1,
            border_color=Theme.BORDER,
            corner_radius=Theme.RADIUS_MD,
        )
        user_card.pack(side="bottom", fill="x", padx=Theme.SPACE_SM, pady=Theme.SPACE_SM)
        ctk.CTkLabel(
            user_card,
            text="AD",
            width=30,
            height=30,
            corner_radius=15,
            fg_color=Theme.ACCENT,
            text_color=Theme.TEXT_ON_ACCENT,
            font=Theme.font_badge_bold(),
        ).pack(side="left", padx=Theme.SPACE_SM, pady=Theme.SPACE_SM)
        ctk.CTkLabel(
            user_card,
            text="Administrator\nОсновная команда",
            justify="left",
            font=Theme.font_micro(),
            text_color=Theme.SIDEBAR_TEXT,
        ).pack(side="left")

        # ── Global top bar ──
        self.statusbar = ctk.CTkFrame(self, height=Theme.HEIGHT_HEADER, fg_color=Theme.BG_HEADER, corner_radius=0)
        self.statusbar.pack(side="top", fill="x")
        self.statusbar.pack_propagate(False)

        self.status_left = ctk.CTkLabel(
            self.statusbar,
            text="● Состояние загружается",
            font=Theme.font_caption(),
            text_color=Theme.STATUS_HEALTHY,
        )
        self.status_left.pack(side="left", padx=Theme.SPACE_LG)
        self.status_left.configure(cursor="hand2")
        self.status_left.bind("<Button-1>", lambda _event: self._show_view("health"), add="+")

        self.global_search = ctk.CTkEntry(
            self.statusbar,
            placeholder_text="Поиск по агентам, аккаунтам, задачам…     Ctrl + K",
            width=360,
            height=Theme.HEIGHT_INPUT,
            fg_color=Theme.SURFACE,
            border_color=Theme.BORDER,
            text_color=Theme.TEXT_PRIMARY,
        )
        self.global_search.pack(side="left", padx=Theme.SPACE_MD)
        self.global_search.bind("<Return>", self._run_global_search)
        self.bind_all("<Control-k>", self._focus_global_search)

        for icon_name, command in (
            ("settings", lambda: self._show_view("settings")),
            ("about", lambda: self._show_view("about")),
            ("logs", lambda: self._show_view("logs")),
        ):
            HubButton(
                self.statusbar,
                text="",
                image=AssetManager.get().get_nav_icon(icon_name, size=18),
                variant="ghost",
                width=Theme.HEIGHT_BTN_MD,
                command=command,
            ).pack(side="right", padx=Theme.SPACE_XS)
        self.add_account_button = HubButton(
            self.statusbar,
            text="+  Добавить аккаунт",
            variant="primary",
            command=lambda: self._handle_action("add_account", {}),
        )
        self.add_account_button.pack(side="right", padx=(Theme.SPACE_XS, Theme.SPACE_MD))

        self.status_right = ctk.CTkLabel(
            self.statusbar,
            text="Snapshot: Н/Д",
            font=Theme.font_micro(),
            text_color=Theme.TEXT_MUTED,
        )

        # ── Main Content Area ──
        self.content = ctk.CTkFrame(self, fg_color=Theme.BG_WINDOW, corner_radius=0)
        self.content.pack(side="right", fill="both", expand=True)

        # Pre-instantiate all views so switching is 100% instant (0-15 ms)
        for key, _, _ in self._nav_items:
            self._views[key] = self._create_view(key)

    def _focus_global_search(self, _event=None) -> str:
        self.global_search.focus_set()
        return "break"

    def _run_global_search(self, _event=None) -> str:
        query = self.global_search.get().strip()
        self._show_view("accounts")
        accounts = self._views.get("accounts")
        if accounts and hasattr(accounts, "search"):
            accounts.search.delete(0, "end")
            accounts.search.insert(0, query)
            accounts._set_search(query)
        return "break"

    def _create_view(self, view_name: str) -> ctk.CTkFrame:
        """Create view widget instance."""
        if view_name == "overview":
            return DashboardView(
                self.content,
                app_state={},
                on_navigate=self._show_view,
                on_action=self._handle_action,
            )
        elif view_name == "team":
            return TeamView(self.content, app_state={}, on_action=self._handle_action)
        elif view_name == "accounts":
            return AccountsView(self.content, app_state={}, on_action=self._handle_action)
        elif view_name == "providers":
            return ProvidersView(self.content, app_state={}, on_action=self._handle_action)
        elif view_name == "routing":
            return RoutingView(self.content, on_action=self._handle_action)
        elif view_name == "analytics":
            return AnalyticsView(self.content)
        elif view_name == "health":
            return HealthView(self.content, app_state={}, on_refresh=self._refresh_data)
        elif view_name == "logs":
            return LogsView(self.content)
        elif view_name == "settings":
            return SettingsView(self.content, on_action=self._handle_action, theme_name=self._theme_name)
        elif view_name == "about":
            return AboutView(self.content)
        else:
            return TeamView(self.content, app_state={}, on_action=self._handle_action)

    def _show_view(self, view_name: str):
        """Instant view switching using pack_forget() and cached widgets with lazy generation update."""
        t0 = time.time()
        prev_view = self._current_view
        self._current_view = view_name

        # Update sidebar button states
        for key, btn in self._nav_buttons.items():
            if key == view_name:
                btn.configure(
                    fg_color=Theme.SIDEBAR_SELECTED,
                    text_color=Theme.TEXT_ACCENT,
                    border_width=1,
                    border_color=Theme.BORDER_ACCENT,
                )
            else:
                btn.configure(
                    fg_color="transparent",
                    text_color=Theme.SIDEBAR_TEXT,
                    border_width=0,
                )

        # Hide currently active views
        for v in self._views.values():
            v.pack_forget()

        # Show target view instantly
        target_view = self._views.get(view_name)
        if target_view:
            target_view.pack(fill="both", expand=True)

            # Lazy update if view state is behind current snapshot generation
            from antigravity_provider.router.state_store import HubStateStore

            snap = HubStateStore.get().get_snapshot()
            if self._view_generations.get(view_name, 0) < snap.generation:
                if hasattr(target_view, "update_data"):
                    try:
                        target_view.update_data(snap)
                    except Exception as ex:
                        logger.warning("Error in lazy view update for %s: %s", view_name, ex)
                self._view_generations[view_name] = snap.generation
            self._update_auxiliary_data(target_view)

        # Instrument tab switch latency
        el_ms = round((time.time() - t0) * 1000, 2)
        if el_ms > 100:
            logger.warning(f"[TAB SWITCH SLOW] {prev_view} -> {view_name}: {el_ms} ms")
        else:
            logger.debug(f"[TAB SWITCH] {prev_view} -> {view_name}: {el_ms} ms")

    def _on_window_configure(self, event):
        """Debounce window resize to maintain 60fps smoothness."""
        if event.widget != self:
            return
        if self._resize_timer_id:
            try:
                self.after_cancel(self._resize_timer_id)
            except Exception:
                pass
        self._resize_timer_id = self.after(100, self._handle_debounced_resize)

    def _handle_debounced_resize(self):
        self._resize_timer_id = None

    # ─────── Data Refresh (Threaded via Scheduler & HubStateStore) ───────

    def _refresh_data(self):
        if self._shutting_down:
            return
        try:
            self.status_left.configure(text="Обновление состояния...")
        except Exception:
            pass

        def _load():
            if self._shutting_down:
                return
            try:
                from antigravity_provider.router.state_store import HubStateStore

                snap = HubStateStore.get().refresh(force_scan=True)
                if not self._shutting_down:
                    self.after(0, lambda: self._on_data_loaded(snap))
            except Exception as e:
                if not self._shutting_down:
                    try:
                        self.after(0, lambda err=str(e): self._on_data_error(err))
                    except Exception:
                        pass

        threading.Thread(target=_load, daemon=True).start()

    def _on_data_loaded(self, snapshot_or_readiness: Any):
        if self._shutting_down:
            return

        from antigravity_provider.router.state_store import HubSnapshot, HubStateStore

        if isinstance(snapshot_or_readiness, HubSnapshot):
            snap = snapshot_or_readiness
            readiness = snap.readiness
        else:
            snap = HubStateStore.get().get_snapshot()
            readiness = snapshot_or_readiness

        freshness = "⚠ Данные устарели" if snap.is_stale else f"Snapshot #{snap.seq}"
        self.status_left.configure(
            text=f"● {readiness.title_ru}{' · Подробнее' if readiness.state != 'healthy' else ''}",
            text_color=Theme.STATUS_HEALTHY
            if readiness.state == "healthy"
            else Theme.STATUS_WARNING
            if readiness.state in ("limited", "degraded")
            else Theme.STATUS_ERROR,
        )

        self.status_right.configure(
            text=f"{freshness} • {readiness.accounts_connected_count} аккаунтов • {readiness.roles_ready_count} ролей",
            text_color=Theme.STATUS_WARNING if snap.is_stale else Theme.TEXT_MUTED,
        )

        # Update ONLY the currently visible view (others are updated lazily on tab switch)
        curr_view = self._views.get(self._current_view)
        if curr_view and hasattr(curr_view, "update_data"):
            try:
                curr_view.update_data(snap)
            except Exception as ex:
                logger.warning("Error updating current view %s: %s", self._current_view, ex)
            self._view_generations[self._current_view] = snap.generation
            self._update_auxiliary_data(curr_view)

    @staticmethod
    def _update_auxiliary_data(view: Any) -> None:
        if hasattr(view, "update_events"):
            try:
                view.update_events(EventLogService.get().get_events(limit=20))
            except Exception as ex:
                logger.warning("Error updating event presentation: %s", ex)

    def _on_data_error(self, error: str):
        if self._shutting_down:
            return
        self.status_left.configure(text=f"Ошибка: {error}")

    # ─────── Action Handler ───────

    def _handle_action(self, action: str, data: Dict[str, Any]):
        pid = data.get("profile_id", "")
        prov = data.get("provider", "")

        if action == "set_main":
            self._run_in_thread(
                lambda: do_set_main(prov, pid),
                on_success=lambda r: self._show_account_action_result(pid, r[1], r[0]),
            )
        elif action == "set_orchestrator":
            self._run_in_thread(
                lambda: do_set_orchestrator(pid),
                on_success=lambda r: self._show_account_action_result(pid, r[1], r[0]),
            )
        elif action == "test":
            self._show_account_action_result(pid, f"Тестирование {data.get('display_name', pid)}…", None)
            self._run_in_thread(
                lambda: do_test_profile(prov, pid),
                on_success=lambda result: self._show_test_result(result, pid),
            )
        elif action == "oauth" or action == "add_account":
            self._open_add_account_wizard()
        elif action == "delete_credentials":
            self._run_in_thread(
                lambda: do_delete_credentials(prov, pid),
                on_success=lambda r: self._show_account_action_result(pid, r[1], r[0]),
            )
        elif action == "assign_role":
            self._open_assign_role_modal(pid, data.get("display_name", pid))
        elif action == "account_details":
            self._open_account_details_modal(pid)
        elif action == "agent_settings":
            self._open_agent_settings_modal(
                data.get("role_id", ""),
                pid,
            )
        elif action == "auto_assign_all":
            self._show_toast("⚡ Автоматическое распределение ролей...")
            self._run_in_thread(
                lambda: AutoAssigner.auto_assign_all(),
                on_success=lambda r: self._show_toast("✅ Роли успешно распределены"),
            )
        elif action == "refresh_data":
            self._refresh_data()
        elif action == "refresh_all":
            from antigravity_provider.router.scheduler import HermesRefreshScheduler

            HermesRefreshScheduler.get().trigger_refresh_all(on_complete=lambda: self.after(0, self._refresh_data))
        elif action == "refresh_account":
            from antigravity_provider.router.scheduler import HermesRefreshScheduler

            HermesRefreshScheduler.get().trigger_refresh_account(
                prov,
                pid,
                on_complete=lambda: self.after(0, self._refresh_data),
            )
        elif action == "edit_route":
            role_id = data.get("role_id", "")
            self._open_route_editor_modal(role_id)
        elif action == "open_routing":
            self._show_view("routing")
            routing = self._views.get("routing")
            if routing and hasattr(routing, "focus_role"):
                routing.focus_role(data.get("role_id", ""))
        elif action == "save_settings":

            def _settings_saved(result: Tuple[bool, str]) -> None:
                requested_theme = str(data.get("theme", self._theme_name))
                if requested_theme != self._theme_name:
                    self._apply_theme(requested_theme)
                self._show_toast(f"✅ {result[1]}")

            self._run_in_thread(
                lambda: do_save_settings(data),
                on_success=_settings_saved,
            )
        elif action == "check_updates":
            from antigravity_provider.updater import UpdateManager

            self._run_in_thread(
                lambda: UpdateManager().check_for_updates(),
                on_success=lambda result: self._show_toast(
                    f"Доступна версия {result.manifest.version}"
                    if result.update_available and result.manifest
                    else (f"Ошибка: {result.error}" if result.error else "Установлена актуальная версия")
                ),
            )

    def _open_assign_role_modal(self, profile_id: str, display_name: str):
        modal = HubModal(self, title=f"Назначение роли: {display_name}", width=500, height=420)

        ctk.CTkLabel(
            modal.body,
            text=f"Выберите роль в команде Hermes для профиля «{display_name}» ({profile_id}):",
            font=Theme.font_body(),
            text_color=Theme.TEXT_SECONDARY,
            wraplength=440,
            justify="left",
        ).pack(anchor="w", pady=(0, 12))

        config = load_router_config()
        current_role = next(
            (role_id for role_id, policy in config.roles.items() if profile_id in policy.preferred_chain),
            "orchestrator",
        )
        role_var = ctk.StringVar(value=current_role)
        roles = [
            ("orchestrator", "👑 Главный оркестратор"),
            ("coder-primary", "💻 Основной кодер"),
            ("coder-secondary", "💻 Резервный кодер"),
            ("reviewer", "🔍 Ревьюер (Code Review)"),
            ("research", "🌐 Исследователь (Search / Docs)"),
            ("fast", "⚡ Быстрый агент"),
            ("spare", "🛡️ Резерв (Spare)"),
        ]

        for val, lbl in roles:
            ctk.CTkRadioButton(
                modal.body,
                text=lbl,
                variable=role_var,
                value=val,
                font=Theme.font_body(),
                text_color=Theme.TEXT_PRIMARY,
                fg_color=Theme.ACCENT,
                hover_color=Theme.ACCENT_HOVER,
            ).pack(anchor="w", padx=8, pady=3)

        primary_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            modal.body,
            text="Сделать основным в выбранной цепочке",
            variable=primary_var,
            font=Theme.font_body(),
            text_color=Theme.TEXT_PRIMARY,
            fg_color=Theme.ACCENT,
            hover_color=Theme.ACCENT_HOVER,
        ).pack(anchor="w", padx=8, pady=(12, 3))

        result_label = ctk.CTkLabel(
            modal.body,
            text="",
            font=Theme.font_body_bold(),
            text_color=Theme.TEXT_SECONDARY,
            wraplength=440,
            justify="left",
            anchor="w",
        )
        result_label.pack(fill="x", padx=8, pady=(8, 0))
        modal.result_label = result_label

        def _save():
            chosen = role_var.get()
            ok, msg = AutoAssigner.assign_profile_to_role(
                profile_id,
                chosen,
                is_primary=primary_var.get() and chosen != "spare",
            )
            result_label.configure(
                text=f"{'✓' if ok else '✕'} {msg}",
                text_color=Theme.STATUS_HEALTHY if ok else Theme.STATUS_ERROR,
            )
            self._show_account_action_result(profile_id, msg, ok)
            if ok:
                save_button.configure(text="Готово", command=modal.destroy)
                self._refresh_data()

        HubButton(modal.footer, text="Отмена", variant="secondary", width=100, command=modal.destroy).pack(side="left")
        save_button = HubButton(
            modal.footer, text="Применить роль", variant="primary", width=160, command=_save
        )
        save_button.pack(side="right")
        modal.save_button = save_button
        return modal

    def _open_account_details_modal(self, profile_id: str):
        """Open account details from a click anywhere on its compact row."""
        snapshot = HubStateStore.get().get_snapshot()
        profile = snapshot.all_profiles.get(profile_id)
        if profile is None:
            self._show_toast(f"❌ Профиль '{profile_id}' не найден")
            return None
        modal = HubModal(self, title=AccountCardWidget.resolve_identity(profile), width=680, height=520)
        summary = ctk.CTkFrame(modal.body, fg_color=Theme.SURFACE_MUTED, corner_radius=Theme.RADIUS_MD)
        summary.pack(fill="x", pady=(0, Theme.SPACE_MD))
        roles = ", ".join(profile.assigned_roles or []) or "роль не назначена"
        ctk.CTkLabel(
            summary,
            text=f"{profile.provider_display_name} • {profile.display_name}",
            font=Theme.font_heading(),
            text_color=Theme.TEXT_PRIMARY,
        ).pack(anchor="w", padx=12, pady=(10, 2))
        ctk.CTkLabel(
            summary,
            text=f"Роли: {roles}   •   Авторизация: {profile.auth_label_ru}   •   {profile.health_label_ru}",
            font=Theme.font_caption(),
            text_color=Theme.TEXT_SECONDARY,
        ).pack(anchor="w", padx=12, pady=(0, 10))

        config = load_router_config()
        profile_config = config.profiles.get(profile_id)
        catalog = get_cached_models(profile.provider)
        configured_model = (
            profile_config.preferred_models[0] if profile_config and profile_config.preferred_models else ""
        )
        model_values = list(catalog.models)
        if configured_model and configured_model not in model_values:
            model_values.insert(0, configured_model)
        model_var = ctk.StringVar(
            value=configured_model or (model_values[0] if model_values else "Список моделей ещё не получен")
        )
        model_row = ctk.CTkFrame(modal.body, fg_color="transparent")
        model_row.pack(fill="x", pady=(0, Theme.SPACE_SM))
        model_menu = ctk.CTkOptionMenu(
            model_row,
            values=model_values or ["Список моделей ещё не получен"],
            variable=model_var,
            fg_color=Theme.SURFACE_MUTED,
            button_color=Theme.ACCENT,
            button_hover_color=Theme.ACCENT_HOVER,
            text_color=Theme.TEXT_PRIMARY,
        )
        model_menu.pack(side="left", fill="x", expand=True)
        model_note = catalog.unavailable_reason if not catalog.models else (
            f"⚠ «{configured_model}» отсутствует в обнаруженном списке"
            if configured_model and configured_model not in catalog.models
            else f"{len(catalog.models)} моделей из кэша"
        )
        ctk.CTkLabel(
            modal.body,
            text=model_note,
            font=Theme.font_micro(),
            text_color=Theme.STATUS_WARNING if not catalog.models or configured_model not in catalog.models else Theme.TEXT_MUTED,
        ).pack(anchor="w", pady=(0, Theme.SPACE_SM))

        def _save_profile_model() -> None:
            selected = model_var.get()
            if selected == "Список моделей ещё не получен" or not profile_config:
                self._show_toast("❌ Сначала получите список моделей")
                return
            updated = load_router_config()
            target = updated.profiles[profile_id]
            target.preferred_models = [selected] + [item for item in target.preferred_models if item != selected]
            updated.profiles[profile_id] = target
            if save_router_config(updated):
                self._show_toast(f"✅ Модель профиля сохранена: {selected}")
                self._refresh_data()
            else:
                self._show_toast("❌ Не удалось сохранить модель профиля")

        HubButton(
            model_row,
            text="Сохранить модель",
            variant="secondary",
            width=140,
            command=_save_profile_model,
        ).pack(side="right", padx=(Theme.SPACE_SM, 0))
        HubButton(
            model_row,
            text="Обновить список",
            variant="ghost",
            width=120,
            command=lambda: refresh_models_async(
                profile.provider,
                lambda _result: self.after(
                    0,
                    lambda: (modal.destroy(), self._open_account_details_modal(profile_id)),
                ),
            ),
        ).pack(side="right", padx=(Theme.SPACE_SM, 0))

        ctk.CTkLabel(
            modal.body, text="Квоты и периоды", font=Theme.font_body_bold(), text_color=Theme.TEXT_PRIMARY
        ).pack(anchor="w")
        quota_box = ctk.CTkFrame(modal.body, fg_color="transparent")
        quota_box.pack(fill="both", expand=True, pady=(4, 8))
        quota = snapshot.quotas.get(profile_id)
        buckets = list(getattr(quota, "buckets", None) or [])
        if not buckets:
            reason = getattr(quota, "unavailable_reason", None) or "Провайдер не отдал данные о лимитах"
            ctk.CTkLabel(
                quota_box, text=f"Н/Д — {reason}", font=Theme.font_caption(), text_color=Theme.TEXT_MUTED
            ).pack(anchor="w", pady=8)
        for bucket in buckets:
            row = ctk.CTkFrame(quota_box, fg_color=Theme.SURFACE_MUTED, corner_radius=Theme.RADIUS_SM)
            row.pack(fill="x", pady=2)
            ctk.CTkLabel(
                row, text=bucket.display_name, font=Theme.font_caption(), text_color=Theme.TEXT_PRIMARY
            ).pack(side="left", padx=10, pady=7)
            detail = bucket.formatted_remaining()
            if detail == "Н/Д":
                detail = getattr(bucket, "unavailable_reason", None) or getattr(quota, "unavailable_reason", None) or detail
            reset = bucket.formatted_reset() or "время сброса не предоставлено"
            ctk.CTkLabel(
                row,
                text=f"{detail}  •  {reset}",
                font=Theme.font_caption(),
                text_color=Theme.TEXT_SECONDARY,
            ).pack(side="right", padx=10, pady=7)

        HubButton(
            modal.footer,
            text="Проверить",
            variant="secondary",
            command=lambda: (modal.destroy(), self._handle_action("test", profile.__dict__)),
        ).pack(side="left", padx=(0, 5))
        HubButton(
            modal.footer,
            text="Назначить роль",
            variant="secondary",
            command=lambda: (modal.destroy(), self._open_assign_role_modal(profile_id, profile.display_name)),
        ).pack(side="left")
        HubButton(modal.footer, text="Закрыть", variant="primary", command=modal.destroy).pack(side="right")
        return modal

    def _open_route_editor_modal(self, role_id: str):
        """Direct, visible editor for one ordered failover chain."""
        config = load_router_config()
        policy = config.roles.get(role_id)
        if policy is None:
            self._show_toast(f"❌ Роль '{role_id}' не найдена")
            return None
        modal = HubModal(self, title=f"Цепочка маршрутизации: {role_id}", width=620, height=520)
        ctk.CTkLabel(
            modal.body,
            text="Первый профиль — основной. Ниже идут резервы в порядке переключения.",
            font=Theme.font_body(),
            text_color=Theme.TEXT_SECONDARY,
        ).pack(anchor="w", pady=(0, 10))
        chain = list(policy.preferred_chain)
        rows = ctk.CTkFrame(modal.body, fg_color="transparent")
        rows.pack(fill="both", expand=True)
        result = ctk.CTkLabel(modal.body, text="", font=Theme.font_caption(), text_color=Theme.TEXT_SECONDARY)
        result.pack(fill="x", pady=(6, 0))

        def _render() -> None:
            for child in rows.winfo_children():
                child.destroy()
            for index, pid in enumerate(chain):
                pcfg = load_router_config().profiles.get(pid)
                row = ctk.CTkFrame(rows, fg_color=Theme.SURFACE_MUTED, corner_radius=Theme.RADIUS_SM)
                row.pack(fill="x", pady=3)
                ctk.CTkLabel(
                    row,
                    text=f"{index + 1}.  {pid}",
                    font=Theme.font_body_bold(),
                    text_color=Theme.TEXT_PRIMARY,
                ).pack(side="left", padx=10, pady=8)
                ctk.CTkLabel(
                    row,
                    text=(pcfg.provider if pcfg else "профиль не найден"),
                    font=Theme.font_caption(),
                    text_color=Theme.TEXT_MUTED,
                ).pack(side="left", padx=6)

                def _move(delta: int, current: int = index) -> None:
                    target = current + delta
                    if 0 <= target < len(chain):
                        chain[current], chain[target] = chain[target], chain[current]
                        _render()

                def _remove(current: int = index) -> None:
                    chain.pop(current)
                    _render()

                HubButton(row, text="Удалить", variant="ghost", width=70, command=_remove).pack(
                    side="right", padx=(2, 8), pady=5
                )
                HubButton(row, text="↓", variant="secondary", width=34, command=lambda i=index: _move(1, i)).pack(
                    side="right", padx=2, pady=5
                )
                HubButton(row, text="↑", variant="secondary", width=34, command=lambda i=index: _move(-1, i)).pack(
                    side="right", padx=2, pady=5
                )

        add_row = ctk.CTkFrame(modal.body, fg_color="transparent")
        add_row.pack(fill="x", pady=(8, 0))
        # Keep every profile in the selector so a just-removed item can be
        # re-added immediately without closing and reopening the editor.
        available = list(config.profiles)
        add_var = ctk.StringVar(value=available[0] if available else "Нет доступных профилей")
        add_menu = ctk.CTkOptionMenu(
            add_row,
            values=available or ["Нет доступных профилей"],
            variable=add_var,
            fg_color=Theme.SURFACE_MUTED,
            button_color=Theme.ACCENT,
            text_color=Theme.TEXT_PRIMARY,
        )
        add_menu.pack(side="left", fill="x", expand=True)

        def _add() -> None:
            pid = add_var.get()
            if pid in config.profiles and pid not in chain:
                chain.append(pid)
                _render()

        HubButton(add_row, text="+ Добавить в цепочку", variant="secondary", command=_add).pack(side="right", padx=(8, 0))

        def _save_chain() -> None:
            ok, message = persist_role_chain(role_id, chain)
            result.configure(
                text=f"{'✓' if ok else '✕'} {message}",
                text_color=Theme.STATUS_HEALTHY if ok else Theme.STATUS_ERROR,
            )
            if ok:
                save_button.configure(text="Готово", command=modal.destroy)
                self._refresh_data()

        _render()
        HubButton(modal.footer, text="Отмена", variant="secondary", command=modal.destroy).pack(side="left")
        save_button = HubButton(modal.footer, text="Сохранить цепочку", variant="primary", command=_save_chain)
        save_button.pack(side="right")
        return modal

    def _open_agent_settings_modal(self, role_id: str, profile_id: str):
        """Open practical role settings from a click anywhere on an agent card."""
        from antigravity_provider.router.quota_collector import AccountQuotaService

        config = load_router_config()
        role = config.roles.get(role_id)
        live_snapshot = HubStateStore.get().get_snapshot()
        pipeline = live_snapshot.get_role_pipeline(role_id)
        role_labels = {
            "orchestrator": "Главный оркестратор",
            "coder-primary": "Кодер 1",
            "coder-secondary": "Кодер 2",
            "reviewer": "Ревьюер",
            "research": "Исследователь",
            "fast": "Быстрый агент",
        }
        modal = HubModal(self, title=f"Настройки агента: {role_labels.get(role_id, role_id)}", width=620, height=720)
        ctk.CTkLabel(
            modal.body,
            text="Аккаунт, модель и реальные лимиты агента",
            font=Theme.font_heading(),
            text_color=Theme.TEXT_PRIMARY,
        ).pack(anchor="w", pady=(0, 12))

        chain_card = ctk.CTkFrame(modal.body, fg_color=Theme.SURFACE_MUTED, corner_radius=Theme.RADIUS_MD)
        chain_card.pack(fill="x", pady=(0, 10))
        chain = list(role.preferred_chain) if role else []
        chain_text = "  →  ".join(
            f"{'● ' if pipeline and node_id == pipeline.active_profile_id else ''}{node_id}" for node_id in chain
        ) or "Профили не назначены"
        active_node = next(
            (node for node in list(getattr(pipeline, "nodes", []) or []) if node.profile_id == pipeline.active_profile_id),
            None,
        )
        failover_reason = getattr(active_node, "failover_reason", None) or "переключений ещё не было"
        ctk.CTkLabel(
            chain_card,
            text=f"Цепочка: {chain_text}",
            font=Theme.font_caption(),
            text_color=Theme.TEXT_PRIMARY,
            anchor="w",
        ).pack(fill="x", padx=10, pady=(8, 2))
        ctk.CTkLabel(
            chain_card,
            text=f"Последнее переключение: {failover_reason}",
            font=Theme.font_micro(),
            text_color=Theme.TEXT_MUTED,
            anchor="w",
        ).pack(fill="x", padx=10, pady=(0, 8))

        choices: dict[str, str] = {}
        for pid, pcfg in config.profiles.items():
            status = ProfileAuthManager.get_profile_status(pcfg.provider, pid)
            if not status.get("authenticated"):
                continue
            identity = AccountQuotaService.get().get_identity(pcfg.provider, pid).primary_identifier()
            label = f"{pid}  •  {identity}"
            choices[label] = pid
        if not choices:
            ctk.CTkLabel(
                modal.body,
                text="Нет подключённых аккаунтов. Сначала добавьте аккаунт.",
                text_color=Theme.STATUS_WARNING,
            ).pack(anchor="w")
            HubButton(modal.footer, text="Закрыть", variant="secondary", command=modal.destroy).pack(side="right")
            return modal

        selected_label = next((label for label, pid in choices.items() if pid == profile_id), next(iter(choices)))
        account_var = ctk.StringVar(value=selected_label)
        model_var = ctk.StringVar(value="")

        ctk.CTkLabel(modal.body, text="Аккаунт", font=Theme.font_caption(), text_color=Theme.TEXT_SECONDARY).pack(
            anchor="w"
        )
        account_menu = ctk.CTkOptionMenu(
            modal.body,
            values=list(choices),
            variable=account_var,
            fg_color=Theme.SURFACE_MUTED,
            button_color=Theme.ACCENT,
            button_hover_color=Theme.ACCENT_HOVER,
            text_color=Theme.TEXT_PRIMARY,
        )
        account_menu.pack(fill="x", pady=(3, 10))

        ctk.CTkLabel(modal.body, text="Модель агента", font=Theme.font_caption(), text_color=Theme.TEXT_SECONDARY).pack(
            anchor="w"
        )
        model_menu = ctk.CTkOptionMenu(
            modal.body,
            values=["default"],
            variable=model_var,
            fg_color=Theme.SURFACE_MUTED,
            button_color=Theme.ACCENT,
            button_hover_color=Theme.ACCENT_HOVER,
            text_color=Theme.TEXT_PRIMARY,
        )
        model_menu.pack(fill="x", pady=(3, 10))
        model_status = ctk.CTkLabel(
            modal.body,
            text="",
            font=Theme.font_caption(),
            text_color=Theme.TEXT_MUTED,
            anchor="w",
            justify="left",
        )
        model_status.pack(fill="x", pady=(0, 5))

        def _apply_cached_models() -> None:
            current_pid = choices[account_var.get()]
            current_cfg = load_router_config().profiles[current_pid]
            catalog = get_cached_models(current_cfg.provider)
            configured = (
                role.default_model
                if role and role.default_model
                else current_cfg.preferred_models[0]
                if current_cfg.preferred_models
                else ""
            )
            values = list(catalog.models)
            if configured and configured not in values:
                values.insert(0, configured)
            model_menu.configure(values=values or ["Список моделей ещё не получен"])
            model_var.set(configured or (values[0] if values else "Список моделей ещё не получен"))
            if not catalog.models:
                model_status.configure(text=catalog.unavailable_reason, text_color=Theme.STATUS_WARNING)
            elif configured and configured not in catalog.models:
                model_status.configure(
                    text=f"⚠ Настроенная модель «{configured}» отсутствует в обнаруженном списке. Она не изменена.",
                    text_color=Theme.STATUS_WARNING,
                )
            else:
                freshness = f" • получено {catalog.fetched_at}" if catalog.fetched_at else ""
                stale = " • кэш устарел" if catalog.is_stale else ""
                model_status.configure(
                    text=f"{len(catalog.models)} моделей из кэша{freshness}{stale}",
                    text_color=Theme.TEXT_MUTED if not catalog.is_stale else Theme.STATUS_WARNING,
                )

        def _refresh_models() -> None:
            current_pid = choices[account_var.get()]
            provider = load_router_config().profiles[current_pid].provider
            model_status.configure(text="Обновление моделей запущено в фоне…", text_color=Theme.TEXT_SECONDARY)
            started = refresh_models_async(provider, lambda _result: self.after(0, _apply_cached_models))
            if not started:
                model_status.configure(
                    text="Фоновое обновление пока недоступно; показан последний кэш.",
                    text_color=Theme.STATUS_WARNING,
                )

        HubButton(
            modal.body,
            text="Обновить список моделей",
            variant="secondary",
            height=30,
            command=_refresh_models,
        ).pack(anchor="w", pady=(0, 8))

        quota_card = ctk.CTkFrame(modal.body, fg_color=Theme.SURFACE_MUTED, corner_radius=Theme.RADIUS_MD)
        quota_card.pack(fill="both", expand=True, pady=(2, 10))
        quota_title = ctk.CTkLabel(
            quota_card, text="Реальные лимиты", font=Theme.font_body_bold(), text_color=Theme.TEXT_PRIMARY
        )
        quota_title.pack(anchor="w", padx=12, pady=(10, 5))
        quota_rows = ctk.CTkFrame(quota_card, fg_color="transparent")
        quota_rows.pack(fill="both", expand=True, padx=12, pady=(0, 8))

        def _refresh_account_panel(_choice: Optional[str] = None) -> None:
            current_pid = choices[account_var.get()]
            current_cfg = load_router_config().profiles[current_pid]
            _apply_cached_models()
            for child in quota_rows.winfo_children():
                child.destroy()
            snapshot = AccountQuotaService.get().get_snapshot(current_cfg.provider, current_pid)
            buckets = list(snapshot.buckets) if snapshot else []
            quota_title.configure(text=f"Реальные лимиты • {current_cfg.provider}")
            if not buckets:
                ctk.CTkLabel(
                    quota_rows, text="Лимиты пока не получены", text_color=Theme.TEXT_MUTED, font=Theme.font_caption()
                ).pack(anchor="w", pady=5)
            for bucket in buckets[:6]:
                row = ctk.CTkFrame(quota_rows, fg_color="transparent")
                row.pack(fill="x", pady=3)
                ctk.CTkLabel(
                    row, text=bucket.display_name, font=Theme.font_caption(), text_color=Theme.TEXT_PRIMARY
                ).pack(side="left")
                reset = bucket.formatted_reset() or "Сброс: Н/Д"
                ctk.CTkLabel(
                    row,
                    text=f"{bucket.formatted_remaining()}  •  {reset}",
                    font=Theme.font_caption(),
                    text_color=Theme.STATUS_HEALTHY if bucket.status == "healthy" else Theme.STATUS_WARNING,
                ).pack(side="right")

        account_menu.configure(command=_refresh_account_panel)
        _refresh_account_panel()
        result = ctk.CTkLabel(modal.body, text="", font=Theme.font_caption(), text_color=Theme.TEXT_SECONDARY)
        result.pack(fill="x")

        def _save_agent() -> None:
            current_pid = choices[account_var.get()]
            current_model = model_var.get()
            if current_model == "Список моделей ещё не получен":
                result.configure(text="✕ Сначала получите список моделей", text_color=Theme.STATUS_ERROR)
                return
            updated = load_router_config()
            profile = updated.profiles[current_pid]
            profile.preferred_models = [current_model] + [m for m in profile.preferred_models if m != current_model]
            updated.profiles[current_pid] = profile
            if role_id in updated.roles:
                updated.roles[role_id].default_model = current_model
            if not save_router_config(updated):
                result.configure(text="✕ Не удалось сохранить модель", text_color=Theme.STATUS_ERROR)
                return
            ok, message = AutoAssigner.assign_profile_to_role(current_pid, role_id, is_primary=True)
            result.configure(
                text=f"{'✓' if ok else '✕'} {message}",
                text_color=Theme.STATUS_HEALTHY if ok else Theme.STATUS_ERROR,
            )
            if ok:
                save_button.configure(text="Готово", command=modal.destroy)
                self._refresh_data()

        HubButton(modal.footer, text="Отмена", variant="secondary", command=modal.destroy).pack(side="left")
        save_button = HubButton(modal.footer, text="Сохранить настройки", variant="primary", command=_save_agent)
        save_button.pack(side="right")
        return modal

    def _open_add_account_wizard(self):
        wizard = AddAccountWizard(self, on_complete=self._on_wizard_complete)

    def _on_wizard_complete(self, result: Dict[str, Any]):
        self._show_toast(f"✅ Аккаунт {result.get('identity')} успешно подключён")
        self._refresh_data()

    def _show_account_action_result(self, profile_id: str, message: str, success: Optional[bool]) -> None:
        view = self._views.get("accounts")
        if view and hasattr(view, "show_action_result"):
            view.show_action_result(profile_id, message, success)
        prefix = "✅" if success is True else "❌" if success is False else "⚡"
        self._show_toast(f"{prefix} {message}")

    def _show_test_result(self, result: Dict[str, Any], profile_id: str = ""):
        if result.get("success"):
            msg = f"Профиль готов • модель: {result.get('model')} • время: {result.get('duration_sec')} с"
        else:
            msg = f"Ошибка теста: {result.get('error', 'Неизвестная ошибка')}"
        self._show_account_action_result(profile_id, msg, bool(result.get("success")))

    def _apply_theme(self, scheme: str) -> None:
        """Apply all palette tokens by rebuilding presentation widgets in place."""
        current_view = self._current_view
        self._theme_name = Theme.apply_scheme(scheme)
        ctk.set_appearance_mode("dark" if self._theme_name == "dark" else "light")
        for child in list(self.winfo_children()):
            child.destroy()
        self._views.clear()
        self._view_generations.clear()
        self.configure(fg_color=Theme.BG_WINDOW)
        self._build_layout()
        self._show_view(current_view)
        from antigravity_provider.router.state_store import HubStateStore

        self._on_data_loaded(HubStateStore.get().get_snapshot())

    def _run_in_thread(self, func, on_success=None, on_error=None):
        def _worker():
            if self._shutting_down:
                return
            try:
                result = func()
                if not self._shutting_down:
                    if on_success:
                        self.after(0, lambda: on_success(result))
                    self.after(300, self._refresh_data)
            except Exception as e:
                if not self._shutting_down:
                    try:
                        if on_error:
                            self.after(0, lambda err=str(e): on_error(err))
                        else:
                            self.after(0, lambda err=str(e): self._show_toast(f"❌ Ошибка: {err}"))
                    except Exception:
                        pass

        threading.Thread(target=_worker, daemon=True).start()

    def _show_toast(self, message: str):
        if self._shutting_down:
            return
        self.status_left.configure(text=message)
        self.after(6000, self._restore_status)

    def _restore_status(self):
        if self._shutting_down:
            return
        from antigravity_provider.router.state_store import HubStateStore

        readiness = HubStateStore.get().get_snapshot().readiness
        self.status_left.configure(
            text=f"● {readiness.title_ru}{' · Подробнее' if readiness.state != 'healthy' else ''}",
            text_color=Theme.STATUS_HEALTHY
            if readiness.state == "healthy"
            else Theme.STATUS_WARNING
            if readiness.state in ("limited", "degraded")
            else Theme.STATUS_ERROR,
        )

    def _on_close(self):
        """Graceful shutdown coordinator without leaving orphan processes."""
        self._shutting_down = True
        try:
            from antigravity_provider.router.scheduler import HermesRefreshScheduler

            HermesRefreshScheduler.get().stop()
        except Exception:
            pass
        try:
            from antigravity_provider.router.quota_collector import AccountQuotaService

            AccountQuotaService.get().stop_background_scheduler()
        except Exception:
            pass
        try:
            if self._resize_timer_id:
                self.after_cancel(self._resize_timer_id)
        except Exception:
            pass
        try:
            global _APP_MUTEX_HANDLE
            if _APP_MUTEX_HANDLE and sys.platform == "win32":
                ctypes.windll.kernel32.CloseHandle(_APP_MUTEX_HANDLE)
                _APP_MUTEX_HANDLE = None
        except Exception:
            pass
        try:
            self.destroy()
        except Exception:
            pass
        os._exit(0)


_APP_MUTEX_HANDLE = None


def check_single_instance() -> bool:
    """Ensure only one Hermes Hub instance runs. If already running, activate existing window and return False."""
    global _APP_MUTEX_HANDLE
    if sys.platform != "win32":
        return True
    try:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        mutex_name = "Global\\HermesHubSingleInstanceMutex"
        mutex = kernel32.CreateMutexW(None, True, mutex_name)
        last_err = kernel32.GetLastError()

        # ERROR_ALREADY_EXISTS = 183
        if last_err == 183:
            hwnd = user32.FindWindowW(None, "Hermes Hub")
            if hwnd:
                user32.ShowWindow(hwnd, 9)  # SW_RESTORE
                user32.SetForegroundWindow(hwnd)
            if mutex:
                kernel32.CloseHandle(mutex)
            return False

        _APP_MUTEX_HANDLE = mutex
        return True
    except Exception:
        return True


def launch_hub():
    from antigravity_provider import paths
    from antigravity_provider.version import __version__

    # Startup logging
    log_file = paths.get_startup_log_file()
    try:
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Starting Hermes Hub v{__version__} (PID {os.getpid()})\n")
    except Exception:
        pass

    if not check_single_instance():
        try:
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(
                    f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Another instance is already running. Focused existing window and exiting.\n"
                )
        except Exception:
            pass
        sys.exit(0)

    try:
        app = HermesHubApp()
        app.mainloop()
    except Exception as exc:
        try:
            import traceback

            tb = traceback.format_exc()
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] FATAL CRASH:\n{tb}\n")
            if sys.platform == "win32":
                ctypes.windll.user32.MessageBoxW(
                    0,
                    f"Произошла критическая ошибка при запуске Hermes Hub:\n\n{exc}\n\nПодробности записаны в: {log_file}",
                    "Hermes Hub — Ошибка запуска",
                    0x10,  # MB_ICONERROR
                )
        except Exception:
            pass
        sys.exit(1)


if __name__ == "__main__":
    launch_hub()
