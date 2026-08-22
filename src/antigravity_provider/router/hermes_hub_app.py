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
_LOCAL = Path(os.environ.get("LOCALAPPDATA", ""))
_PLUGIN_SRC = _LOCAL / "hermes" / "plugins" / "antigravity-provider" / "src"
_AGENT_DIR = _LOCAL / "hermes" / "hermes-agent"
for _p in [_PLUGIN_SRC, _AGENT_DIR, Path(__file__).resolve().parent.parent.parent]:
    _ps = str(_p)
    if _p.exists() and _ps not in sys.path:
        sys.path.insert(0, _ps)

from antigravity_provider.router.router_config import load_router_config
from antigravity_provider.router.profile_manager import ProfileAuthManager
from antigravity_provider.router.auto_assigner import AutoAssigner
from antigravity_provider.router.adapters import get_adapter
from antigravity_provider import paths
from antigravity_provider.version import __version__

from antigravity_provider.router.ui.theme import Theme
from antigravity_provider.router.ui.assets import AssetManager
from antigravity_provider.router.ui.components import HubButton, HubModal
from antigravity_provider.router.ui.add_account_wizard import AddAccountWizard

from antigravity_provider.router.unified_health import (
    UnifiedHealthService,
    EventLogService,
    SystemReadiness,
    STATUS_HEALTHY,
)

from antigravity_provider.router.ui.views.team_view import TeamView
from antigravity_provider.router.ui.views.dashboard_view import DashboardView
from antigravity_provider.router.ui.views.accounts_view import AccountsView
from antigravity_provider.router.ui.views.providers_view import ProvidersView
from antigravity_provider.router.ui.views.routing_view import RoutingView
from antigravity_provider.router.ui.views.health_view import HealthView
from antigravity_provider.router.ui.views.logs_view import LogsView
from antigravity_provider.router.ui.views.settings_view import SettingsView
from antigravity_provider.router.ui.views.about_view import AboutView
from antigravity_provider.router.ui.views.analytics_view import AnalyticsView
from antigravity_provider.router.ui.views.quotas_view import QuotasView

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


def do_set_main(provider: str, profile_id: str) -> Tuple[bool, str]:
    ok, msg = ProfileAuthManager.set_main_profile(provider, profile_id)
    if ok:
        EventLogService.get().log(
            "account", f"Профиль {profile_id} назначен основным аккаунтом Hermes ({provider}).", level="info"
        )
    return ok, msg


def do_set_orchestrator(profile_id: str) -> Tuple[bool, str]:
    ok, msg = AutoAssigner.set_primary_orchestrator(profile_id)
    if ok:
        EventLogService.get().log(
            "routing", f"Профиль {profile_id} назначен главным оркестратором команды.", level="info"
        )
    return ok, msg


def do_test_profile(provider: str, profile_id: str) -> Dict[str, Any]:
    """Check local profile readiness without inference, OAuth, or a browser."""
    config = load_router_config()
    pcfg = config.get_profile(profile_id)
    if not pcfg:
        return {"success": False, "error": f"Профиль '{profile_id}' не найден"}

    status = ProfileAuthManager.get_profile_status(pcfg.provider, profile_id)
    if not status.get("authenticated"):
        return {"success": False, "error": "Аккаунт не добавлен. Сначала выполните подключение."}

    model = pcfg.preferred_models[0] if pcfg.preferred_models else "default"
    t0 = time.time()
    try:
        auth_data = ProfileAuthManager.load_profile_auth(pcfg.provider, profile_id)
        if not auth_data:
            return {"success": False, "error": "Сохранённые данные авторизации не найдены"}
        adapter = get_adapter(pcfg.provider)
        runtime_ready = adapter.health_check(pcfg)
        el = round(time.time() - t0, 2)
        if not runtime_ready:
            return {
                "success": False,
                "duration_sec": el,
                "error": "Локальный runtime провайдера недоступен; повторная авторизация не запускалась",
            }
        EventLogService.get().log(
            "system", f"Локальная проверка профиля {profile_id} ({model}) пройдена за {el}s.", level="success"
        )
        return {
            "success": True,
            "model": model,
            "duration_sec": el,
            "response": "Авторизация сохранена; runtime провайдера доступен",
        }
    except Exception as e:
        EventLogService.get().log("system", f"Ошибка теста {profile_id} ({model}): {e}", level="error")
        return {"success": False, "model": model, "duration_sec": round(time.time() - t0, 2), "error": str(e)}


def do_delete_credentials(provider: str, profile_id: str) -> Tuple[bool, str]:
    auth_p = ProfileAuthManager.get_profile_dir(provider, profile_id) / "auth.json"
    if auth_p.is_file():
        try:
            auth_p.unlink()
            EventLogService.get().log("account", f"Учетные данные для {profile_id} удалены.", level="warning")
            return True, f"Учетные данные для '{profile_id}' удалены"
        except Exception as e:
            return False, f"Ошибка удаления: {e}"
    return True, "Учетные данные отсутствовали"


def do_save_settings(settings: Dict[str, Any]) -> Tuple[bool, str]:
    settings_file = paths.get_hermes_home() / "hub_settings.json"
    settings_file.parent.mkdir(parents=True, exist_ok=True)
    existing: Dict[str, Any] = {}
    if settings_file.exists():
        try:
            existing = json.loads(settings_file.read_text(encoding="utf-8"))
        except Exception:
            existing = {}
    existing.update(settings)
    temp_file = settings_file.with_suffix(".json.tmp")
    temp_file.write_text(json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(temp_file, settings_file)
    from antigravity_provider.router.quota_collector import AccountQuotaService

    AccountQuotaService.get().set_refresh_interval(int(settings.get("quota_refresh_interval_sec", 300)))
    return True, "Настройки сохранены"


# ═══════════════════════════════════════════════════════════════
#  Main Application Window
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
            ("providers", "Провайдеры", "providers"),
            ("quotas", "Квоты и лимиты", "quotas"),
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
        elif view_name == "quotas":
            return QuotasView(self.content)
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
            text=f"● {readiness.title_ru}",
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
                on_success=lambda r: self._show_toast(f"✅ {r[1]}" if r[0] else f"❌ {r[1]}"),
            )
        elif action == "set_orchestrator":
            self._run_in_thread(
                lambda: do_set_orchestrator(pid),
                on_success=lambda r: self._show_toast(f"✅ {r[1]}" if r[0] else f"❌ {r[1]}"),
            )
        elif action == "test":
            self._show_toast(f"⚡ Тестирование {data.get('display_name', pid)}...")
            self._run_in_thread(
                lambda: do_test_profile(prov, pid),
                on_success=self._show_test_result,
            )
        elif action == "oauth" or action == "add_account":
            self._open_add_account_wizard()
        elif action == "delete_credentials":
            self._run_in_thread(
                lambda: do_delete_credentials(prov, pid),
                on_success=lambda r: self._show_toast(f"✅ {r[1]}" if r[0] else f"❌ {r[1]}"),
            )
        elif action == "assign_role":
            self._open_assign_role_modal(pid, data.get("display_name", pid))
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
            self._show_view("team")
            team = self._views.get("team")
            if team and hasattr(team, "focus_role"):
                team.focus_role(role_id)
            self._show_toast(f"Настройка цепочки роли: {role_id}")
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

        def _save():
            chosen = role_var.get()
            ok, msg = AutoAssigner.assign_profile_to_role(
                profile_id,
                chosen,
                is_primary=primary_var.get() and chosen != "spare",
            )
            modal.destroy()
            self._show_toast(f"✅ {msg}" if ok else f"❌ {msg}")
            self._refresh_data()

        HubButton(modal.footer, text="Отмена", variant="secondary", width=100, command=modal.destroy).pack(side="left")
        HubButton(modal.footer, text="Применить роль", variant="primary", width=160, command=_save).pack(side="right")

    def _open_add_account_wizard(self):
        wizard = AddAccountWizard(self, on_complete=self._on_wizard_complete)

    def _on_wizard_complete(self, result: Dict[str, Any]):
        self._show_toast(f"✅ Аккаунт {result.get('identity')} успешно подключён")
        self._refresh_data()

    def _show_test_result(self, result: Dict[str, Any]):
        if result.get("success"):
            msg = f"✓ Профиль готов | Модель: {result.get('model')} | Время: {result.get('duration_sec')}s"
        else:
            msg = f"✕ Ошибка теста: {result.get('error', 'Неизвестная ошибка')}"
        self._show_toast(msg)

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
            text=f"● {readiness.title_ru}",
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
