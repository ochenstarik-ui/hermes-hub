"""Hermes Hub — Native Windows Desktop Application (Refinement v2).

Features:
- Unified Health Presentation Layer
- Zero Widget-Recreation Lag (Cached Views)
- 4-Step Add Account Wizard
- Strict Separation of MAIN Account vs Orchestrator
- Non-blocking Background Workers
- Graceful Shutdown (0 zombie processes)
"""
from __future__ import annotations

import logging
import os
import sys
import threading
import time
import webbrowser
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import customtkinter as ctk

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

from antigravity_provider.router.ui.theme import Theme
from antigravity_provider.router.ui.assets import AssetManager
from antigravity_provider.router.ui.components import HubButton
from antigravity_provider.router.ui.add_account_wizard import AddAccountWizard

from antigravity_provider.router.unified_health import (
    UnifiedHealthService,
    EventLogService,
    SystemReadiness,
    STATUS_HEALTHY,
)

from antigravity_provider.router.ui.views.team_view import TeamView
from antigravity_provider.router.ui.views.accounts_view import AccountsView
from antigravity_provider.router.ui.views.providers_view import ProvidersView
from antigravity_provider.router.ui.views.routing_view import RoutingView
from antigravity_provider.router.ui.views.health_view import HealthView
from antigravity_provider.router.ui.views.logs_view import LogsView
from antigravity_provider.router.ui.views.settings_view import SettingsView
from antigravity_provider.router.ui.views.about_view import AboutView

logger = logging.getLogger("hermes.hub.gui")


# ═══════════════════════════════════════════════════════════════
#  Actions Layer (Safe & Non-blocking)
# ═══════════════════════════════════════════════════════════════

def do_set_main(provider: str, profile_id: str) -> Tuple[bool, str]:
    ok, msg = ProfileAuthManager.set_main_profile(provider, profile_id)
    if ok:
        EventLogService.get().log("account", f"Профиль {profile_id} назначен основным аккаунтом Hermes ({provider}).", level="info")
    return ok, msg


def do_set_orchestrator(profile_id: str) -> Tuple[bool, str]:
    ok, msg = AutoAssigner.set_primary_orchestrator(profile_id)
    if ok:
        EventLogService.get().log("routing", f"Профиль {profile_id} назначен главным оркестратором команды.", level="info")
    return ok, msg


def do_test_profile(provider: str, profile_id: str) -> Dict[str, Any]:
    """Strictly tests stored credentials WITHOUT triggering OAuth or opening browsers."""
    config = load_router_config()
    pcfg = config.get_profile(profile_id)
    if not pcfg:
        return {"success": False, "error": f"Профиль '{profile_id}' не найден"}

    status = ProfileAuthManager.get_profile_status(pcfg.provider, profile_id)
    if not status.get("authenticated"):
        return {"success": False, "error": "Аккаунт не авторизован. Сначала выполните вход."}

    adapter = get_adapter(pcfg.provider)
    model = pcfg.preferred_models[0] if pcfg.preferred_models else "default"
    t0 = time.time()
    try:
        resp = adapter.invoke(pcfg, {
            "model": model,
            "messages": [{"role": "user", "content": f"Respond strictly with: TEST_OK_FOR_{profile_id}"}],
            "temperature": 0.1,
        })
        el = round(time.time() - t0, 2)
        content = resp.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
        EventLogService.get().log("system", f"Тест {profile_id} ({model}) успешно пройден за {el}s.", level="success")
        return {"success": True, "model": model, "duration_sec": el, "response": content[:120]}
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


# ═══════════════════════════════════════════════════════════════
#  Main Application Window
# ═══════════════════════════════════════════════════════════════

class HermesHubApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Hermes Hub")
        self.geometry("1360x860")
        self.minsize(1080, 680)

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")
        self.configure(fg_color=Theme.BG_WINDOW)

        # Set Windows Multi-Resolution Icon
        ico_path = AssetManager.get().get_ico_path()
        if ico_path and os.path.exists(ico_path):
            try:
                self.iconbitmap(ico_path)
            except Exception:
                pass

        self._current_view = "team"
        self._views: Dict[str, ctk.CTkFrame] = {}
        self._shutting_down = False
        self._poll_timer_id = None

        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self._build_layout()
        self._show_view("team")
        self.after(50, self._refresh_data)

    def _build_layout(self):
        # ── Sidebar (Left) ──
        self.sidebar = ctk.CTkFrame(self, width=Theme.WIDTH_SIDEBAR, fg_color=Theme.BG_SIDEBAR, corner_radius=0)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)

        # Top Centered Brand Logo per mockup
        brand_container = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        brand_container.pack(fill="x", padx=16, pady=(20, 14))

        logo_img = AssetManager.get().get_logo_image(size=(72, 72))
        if logo_img:
            logo_lbl = ctk.CTkLabel(brand_container, image=logo_img, text="")
            logo_lbl.pack(anchor="center", pady=(0, 6))

        ctk.CTkLabel(brand_container, text="HERMES HUB", font=Theme.font_title_hero(), text_color=Theme.TEXT_ACCENT).pack(anchor="center")
        ctk.CTkLabel(brand_container, text="Control Center", font=Theme.font_caption(), text_color=Theme.TEXT_MUTED).pack(anchor="center")

        # Divider
        ctk.CTkFrame(self.sidebar, height=1, fg_color=Theme.BORDER).pack(fill="x", padx=14, pady=(4, 12))

        # Nav Items
        self._nav_items = [
            ("team", "Команда", "👥"),
            ("accounts", "Аккаунты", "🔍"),
            ("routing", "Маршрутизация", "🔀"),
            ("providers", "Провайдеры", "🌐"),
            ("health", "Состояние системы", "🛡️"),
            ("logs", "Журнал событий", "📜"),
            ("settings", "Настройки", "⚙️"),
            ("about", "О программе", "ℹ️"),
        ]

        self._nav_buttons: Dict[str, ctk.CTkButton] = {}
        for key, label, icon in self._nav_items:
            btn = ctk.CTkButton(
                self.sidebar,
                text=f"  {icon}  {label}",
                font=Theme.font_body(),
                height=Theme.HEIGHT_NAV_ITEM,
                fg_color="transparent",
                hover_color=Theme.SURFACE_HOVER,
                text_color=Theme.TEXT_PRIMARY,
                anchor="w",
                corner_radius=Theme.RADIUS_SM,
                command=lambda k=key: self._show_view(k),
            )
            btn.pack(fill="x", padx=12, pady=2)
            self._nav_buttons[key] = btn

        # Refresh button at bottom of sidebar
        refresh_btn = HubButton(
            self.sidebar,
            text="🔄  Обновить",
            variant="secondary",
            height=38,
            command=self._refresh_data,
        )
        refresh_btn.pack(side="bottom", fill="x", padx=14, pady=16)

        # ── Status Bar (Bottom) ──
        self.statusbar = ctk.CTkFrame(self, height=Theme.HEIGHT_STATUSBAR, fg_color=Theme.BG_STATUSBAR, corner_radius=0)
        self.statusbar.pack(side="bottom", fill="x")

        self.status_left = ctk.CTkLabel(
            self.statusbar,
            text="Аккаунты: ... | Роли: ... | Обновлено: ...",
            font=Theme.font_micro(),
            text_color=Theme.TEXT_MUTED,
        )
        self.status_left.pack(side="left", padx=16)

        self.status_right = ctk.CTkLabel(
            self.statusbar,
            text="● Hermes работает",
            font=Theme.font_micro(),
            text_color=Theme.STATUS_HEALTHY,
        )
        self.status_right.pack(side="right", padx=16)

        # ── Main Content Area ──
        self.content = ctk.CTkFrame(self, fg_color=Theme.BG_WINDOW, corner_radius=0)
        self.content.pack(side="right", fill="both", expand=True)

    def _get_or_create_view(self, view_name: str) -> ctk.CTkFrame:
        """Lazy create and cache views for zero-latency switching."""
        if view_name in self._views:
            return self._views[view_name]

        if view_name == "team":
            view = TeamView(self.content, app_state={}, on_action=self._handle_action)
        elif view_name == "accounts":
            view = AccountsView(self.content, app_state={}, on_action=self._handle_action)
        elif view_name == "providers":
            view = ProvidersView(self.content, app_state={}, on_action=self._handle_action)
        elif view_name == "routing":
            view = RoutingView(self.content)
        elif view_name == "health":
            view = HealthView(self.content, app_state={}, on_refresh=self._refresh_data)
        elif view_name == "logs":
            view = LogsView(self.content)
        elif view_name == "settings":
            view = SettingsView(self.content)
        elif view_name == "about":
            view = AboutView(self.content)
        else:
            view = TeamView(self.content, app_state={}, on_action=self._handle_action)

        self._views[view_name] = view
        return view

    def _show_view(self, view_name: str):
        """Instant view switching using pack_forget() and cached widgets."""
        self._current_view = view_name

        # Update sidebar button states
        for key, btn in self._nav_buttons.items():
            if key == view_name:
                btn.configure(
                    fg_color=Theme.SURFACE_SELECTED,
                    text_color=Theme.TEXT_ACCENT,
                    border_width=1,
                    border_color=Theme.BORDER_ACCENT,
                )
            else:
                btn.configure(
                    fg_color="transparent",
                    text_color=Theme.TEXT_PRIMARY,
                    border_width=0,
                )

        # Hide currently active views
        for v in self._views.values():
            v.pack_forget()

        # Show target view instantly
        target_view = self._get_or_create_view(view_name)
        target_view.pack(fill="both", expand=True)

    # ─────── Data Refresh (Threaded) ───────

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
                service = UnifiedHealthService.get()
                service.scan_all()
                readiness = service.get_system_readiness()
                if not self._shutting_down:
                    self.after(0, lambda: self._on_data_loaded(readiness))
            except Exception as e:
                if not self._shutting_down:
                    try:
                        self.after(0, lambda: self._on_data_error(str(e)))
                    except Exception:
                        pass

        threading.Thread(target=_load, daemon=True).start()

    def _on_data_loaded(self, readiness: SystemReadiness):
        if self._shutting_down:
            return

        self.status_left.configure(
            text=f"Аккаунты: {readiness.accounts_connected_count}/{readiness.total_accounts} | Роли: {readiness.roles_ready_count}/{readiness.total_roles} | Провайдеры: {readiness.providers_ready_count}/{readiness.total_providers} | Обновлено: {time.strftime('%H:%M:%S')}"
        )

        r_color = Theme.STATUS_HEALTHY if readiness.state == "healthy" else (Theme.STATUS_WARNING if readiness.state in ("limited", "degraded") else Theme.STATUS_ERROR)
        self.status_right.configure(text=f"● {readiness.title_ru}", text_color=r_color)

        # Update all active cached views
        for v in self._views.values():
            if hasattr(v, "update_data"):
                try:
                    v.update_data()
                except Exception:
                    pass

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
        elif action == "oauth":
            self._open_add_account_wizard()
        elif action == "add_account":
            self._open_add_account_wizard()
        elif action == "delete_credentials":
            self._run_in_thread(
                lambda: do_delete_credentials(prov, pid),
                on_success=lambda r: self._show_toast(f"✅ {r[1]}" if r[0] else f"❌ {r[1]}"),
            )
        elif action == "auto_assign_all":
            self._show_toast("⚡ Автоматическое распределение ролей...")
            self._run_in_thread(
                lambda: AutoAssigner.auto_assign_all(),
                on_success=lambda r: self._show_toast("✅ Роли успешно распределены"),
            )
        elif action == "refresh_data":
            self._refresh_data()

    def _open_add_account_wizard(self):
        wizard = AddAccountWizard(self, on_complete=self._on_wizard_complete)

    def _on_wizard_complete(self, result: Dict[str, Any]):
        self._show_toast(f"✅ Аккаунт {result.get('identity')} успешно подключён")
        self._refresh_data()

    def _show_test_result(self, result: Dict[str, Any]):
        if result.get("success"):
            msg = f"✓ Тест успешен | Модель: {result.get('model')} | Время: {result.get('duration_sec')}s"
        else:
            msg = f"✕ Ошибка теста: {result.get('error', 'Неизвестная ошибка')}"
        self._show_toast(msg)

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
                            self.after(0, lambda: on_error(str(e)))
                        else:
                            self.after(0, lambda: self._show_toast(f"❌ Ошибка: {e}"))
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
        service = UnifiedHealthService.get()
        readiness = service.get_system_readiness()
        self.status_left.configure(
            text=f"Аккаунты: {readiness.accounts_connected_count}/{readiness.total_accounts} | Роли: {readiness.roles_ready_count}/{readiness.total_roles} | Провайдеры: {readiness.providers_ready_count}/{readiness.total_providers} | Обновлено: {time.strftime('%H:%M:%S')}"
        )

    def _on_close(self):
        """Graceful shutdown without leaving orphan processes."""
        self._shutting_down = True
        try:
            self.destroy()
        except Exception:
            pass
        os._exit(0)


# ═══════════════════════════════════════════════════════════════
#  Entry Point
# ═══════════════════════════════════════════════════════════════

def launch_hub():
    app = HermesHubApp()
    app.mainloop()


if __name__ == "__main__":
    launch_hub()
