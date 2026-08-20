"""Hermes Hub — Settings View (Интерактивные параметры и настройки)."""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any, Dict, Optional
import customtkinter as ctk

from antigravity_provider.router.ui.theme import Theme
from antigravity_provider.router.ui.components import (
    HubButton,
    HubCard,
    HubSectionHeader,
)


class SettingsView(ctk.CTkFrame):
    def __init__(self, master: Any, **kwargs):
        super().__init__(master=master, fg_color="transparent", **kwargs)
        self.settings_file = Path(os.environ.get("LOCALAPPDATA", "")) / "hermes" / "hub_settings.json"
        self._load_settings()
        self._build()

    def _load_settings(self):
        self.settings = {
            "session_affinity": True,
            "failover_attempts": "3",
            "model_timeout_sec": "120",
            "auto_assignment": True,
            "auto_failover": True,
            "auto_return_primary": True,
            "auto_monitoring": True,
            "monitoring_interval_min": "5",
        }
        if self.settings_file.exists():
            try:
                data = json.loads(self.settings_file.read_text(encoding="utf-8"))
                self.settings.update(data)
            except Exception:
                pass

    def _save_settings(self):
        try:
            self.settings_file.parent.mkdir(parents=True, exist_ok=True)
            self.settings_file.write_text(json.dumps(self.settings, indent=2), encoding="utf-8")
        except Exception:
            pass

    def _build(self):
        header = HubSectionHeader(
            self,
            title="Настройки Hermes Hub",
            subtitle="Конфигурация параметров маршрутизации, восстановления и мониторинга",
            action_text="💾 Сохранить",
            action_cmd=self._save_settings,
        )
        header.pack(fill="x", padx=20, pady=(16, 12))

        scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=15, pady=(0, 10))

        # ── 1. Routing & Failover ──
        c1 = HubCard(scroll, border_color=Theme.BORDER, fg_color=Theme.SURFACE)
        c1.pack(fill="x", pady=6)
        ctk.CTkLabel(c1, text="Маршрутизация и Отказоустойчивость", font=Theme.font_heading(), text_color=Theme.TEXT_PRIMARY).pack(anchor="w", padx=16, pady=(12, 6))

        # Session Affinity switch
        r1 = ctk.CTkFrame(c1, fg_color="transparent")
        r1.pack(fill="x", padx=16, pady=4)
        ctk.CTkLabel(r1, text="Сессионная привязка (Session Affinity)", font=Theme.font_body(), text_color=Theme.TEXT_PRIMARY).pack(side="left")
        aff_sw = ctk.CTkSwitch(r1, text="", fg_color=Theme.SURFACE_MUTED, progress_color=Theme.ACCENT)
        aff_sw.pack(side="right")
        if self.settings.get("session_affinity"):
            aff_sw.select()

        # Auto Failover switch
        r2 = ctk.CTkFrame(c1, fg_color="transparent")
        r2.pack(fill="x", padx=16, pady=4)
        ctk.CTkLabel(r2, text="Автоматический Failover при исчерпании квот", font=Theme.font_body(), text_color=Theme.TEXT_PRIMARY).pack(side="left")
        fo_sw = ctk.CTkSwitch(r2, text="", fg_color=Theme.SURFACE_MUTED, progress_color=Theme.ACCENT)
        fo_sw.pack(side="right")
        if self.settings.get("auto_failover"):
            fo_sw.select()

        # Failover Attempts
        r3 = ctk.CTkFrame(c1, fg_color="transparent")
        r3.pack(fill="x", padx=16, pady=(4, 12))
        ctk.CTkLabel(r3, text="Лимит попыток failover на запрос", font=Theme.font_body(), text_color=Theme.TEXT_PRIMARY).pack(side="left")
        fo_menu = ctk.CTkOptionMenu(
            r3,
            values=["1", "2", "3", "4", "5"],
            width=80,
            height=28,
            fg_color=Theme.SURFACE_MUTED,
            button_color=Theme.ACCENT,
            text_color=Theme.TEXT_PRIMARY,
        )
        fo_menu.set(str(self.settings.get("failover_attempts", "3")))
        fo_menu.pack(side="right")

        # ── 2. Recovery & Quota Management ──
        c2 = HubCard(scroll, border_color=Theme.BORDER, fg_color=Theme.SURFACE)
        c2.pack(fill="x", pady=6)
        ctk.CTkLabel(c2, text="Восстановление и Квоты", font=Theme.font_heading(), text_color=Theme.TEXT_PRIMARY).pack(anchor="w", padx=16, pady=(12, 6))

        r4 = ctk.CTkFrame(c2, fg_color="transparent")
        r4.pack(fill="x", padx=16, pady=4)
        ctk.CTkLabel(r4, text="Возвращаться на основной аккаунт после сброса квоты", font=Theme.font_body(), text_color=Theme.TEXT_PRIMARY).pack(side="left")
        ret_sw = ctk.CTkSwitch(r4, text="", fg_color=Theme.SURFACE_MUTED, progress_color=Theme.ACCENT)
        ret_sw.pack(side="right")
        if self.settings.get("auto_return_primary"):
            ret_sw.select()

        r5 = ctk.CTkFrame(c2, fg_color="transparent")
        r5.pack(fill="x", padx=16, pady=(4, 12))
        ctk.CTkLabel(r5, text="Автоматический фоновый мониторинг здоровья", font=Theme.font_body(), text_color=Theme.TEXT_PRIMARY).pack(side="left")
        mon_sw = ctk.CTkSwitch(r5, text="", fg_color=Theme.SURFACE_MUTED, progress_color=Theme.ACCENT)
        mon_sw.pack(side="right")
        if self.settings.get("auto_monitoring"):
            mon_sw.select()

        # ── 3. Advanced / Дополнительно (Collapsible) ──
        c3 = HubCard(scroll, border_color=Theme.BORDER, fg_color=Theme.DARK)
        c3.pack(fill="x", pady=6)

        ctk.CTkLabel(c3, text="Дополнительно (Инструменты и Пути)", font=Theme.font_heading(), text_color=Theme.TEXT_ACCENT).pack(anchor="w", padx=16, pady=(12, 6))

        hermes_home = Path(os.environ.get("LOCALAPPDATA", "")) / "hermes"

        btns_row = ctk.CTkFrame(c3, fg_color="transparent")
        btns_row.pack(fill="x", padx=16, pady=6)

        HubButton(btns_row, text="📁 Открыть папку данных", variant="secondary", width=180, command=lambda: self._open_folder(hermes_home)).pack(side="left", padx=(0, 8))
        HubButton(btns_row, text="📜 Открыть журнал логов", variant="secondary", width=180, command=lambda: self._open_folder(hermes_home / "logs")).pack(side="left")

        paths_info = [
            ("Профили роутера:", str(hermes_home / "router_profiles.yaml")),
            ("Учетные данные:", str(hermes_home / "auth.json")),
            ("Файл логов:", str(hermes_home / "logs" / "hermes-hub.log")),
        ]
        for label, pstr in paths_info:
            p_row = ctk.CTkFrame(c3, fg_color=Theme.SURFACE_MUTED, corner_radius=Theme.RADIUS_SM)
            p_row.pack(fill="x", padx=16, pady=2)
            ctk.CTkLabel(p_row, text=label, font=Theme.font_caption(), text_color=Theme.TEXT_SECONDARY).pack(side="left", padx=8, pady=4)
            ctk.CTkLabel(p_row, text=pstr, font=Theme.font_mono_sm(), text_color=Theme.TEXT_MUTED).pack(side="right", padx=8)

        ctk.CTkLabel(c3, text="", font=Theme.font_micro()).pack(pady=4)

    def _open_folder(self, path: Path):
        try:
            if path.exists():
                os.startfile(str(path))
            elif path.parent.exists():
                os.startfile(str(path.parent))
        except Exception:
            pass
