"""Hermes Hub — Health View (Диагностический Dashboard состояния системы с иконками)."""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional
import customtkinter as ctk

from antigravity_provider.router.ui.theme import Theme
from antigravity_provider.router.ui.assets import AssetManager
from antigravity_provider.router.ui.components import (
    HubButton,
    HubCard,
    HubSectionHeader,
    HubStatusBadge,
)
from antigravity_provider.router.unified_health import (
    UnifiedHealthService,
    ProfileViewModel,
    STATUS_HEALTHY,
    STATUS_NOT_CONFIGURED,
)


class HealthView(ctk.CTkFrame):
    def __init__(self, master: Any, app_state: Dict[str, Any], on_refresh: Optional[Callable] = None, **kwargs):
        super().__init__(master=master, fg_color="transparent", **kwargs)
        self.app_state = app_state
        self.on_refresh = on_refresh
        self._build()

    def _build(self):
        header = HubSectionHeader(
            self,
            title="Диагностика и Состояние Системы",
            subtitle="Детальный аудит доступности аккаунтов, авторизации, семейств моделей и квот",
            action_text="🔄 Обновить аудит",
            action_cmd=self.on_refresh,
        )
        header.pack(fill="x", padx=20, pady=(16, 12))

        self.scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.scroll.pack(fill="both", expand=True, padx=15, pady=(0, 10))

        self.update_data()

    def update_data(self, snapshot: Optional[Any] = None):
        for w in self.scroll.winfo_children():
            w.destroy()

        from antigravity_provider.router.state_store import HubStateStore
        if snapshot is None:
            snapshot = HubStateStore.get().get_snapshot()

        readiness = snapshot.readiness
        profiles_by_prov = snapshot.profiles_by_provider

        # Top Diagnostic Banner
        banner = HubCard(self.scroll, border_color=Theme.BORDER_ACCENT, fg_color=Theme.DARK)
        banner.pack(fill="x", pady=(0, 12))

        b_top = ctk.CTkFrame(banner, fg_color="transparent")
        b_top.pack(fill="x", padx=16, pady=(14, 4))

        ctk.CTkLabel(b_top, text=f"СОСТОЯНИЕ СИСТЕМЫ: {readiness.title_ru.upper()}", font=Theme.font_heading(), text_color=Theme.TEXT_ACCENT).pack(side="left")
        ctk.CTkLabel(b_top, text=f"Аккаунты: {readiness.accounts_connected_count}/{readiness.total_accounts}  •  Роли: {readiness.roles_ready_count}/{readiness.total_roles}", font=Theme.font_caption(), text_color=Theme.TEXT_SECONDARY).pack(side="right")

        ctk.CTkLabel(banner, text=readiness.summary_ru, font=Theme.font_body(), text_color=Theme.TEXT_PRIMARY).pack(anchor="w", padx=16, pady=(0, 10))

        if readiness.warnings:
            w_box = ctk.CTkFrame(banner, fg_color="#3B2610", corner_radius=Theme.RADIUS_SM)
            w_box.pack(fill="x", padx=16, pady=(0, 12))
            for w_txt in readiness.warnings:
                ctk.CTkLabel(w_box, text=f"⚠️ {w_txt}", font=Theme.font_caption(), text_color=Theme.STATUS_WARNING).pack(anchor="w", padx=10, pady=2)

        # Provider Breakdown Tables
        for prov_id, prov_label in [
            ("antigravity", "Google Antigravity"),
            ("openai-codex", "OpenAI Codex"),
            ("opencode-go", "OpenCode Go"),
        ]:
            profs = profiles_by_prov.get(prov_id, [])

            p_card = HubCard(self.scroll, border_color=Theme.BORDER, fg_color=Theme.SURFACE)
            p_card.pack(fill="x", pady=8)

            # Provider Header with icon
            p_hdr = ctk.CTkFrame(p_card, fg_color="transparent")
            p_hdr.pack(fill="x", padx=16, pady=(12, 6))

            p_img = AssetManager.get().get_provider_image(prov_id, size=(20, 20))
            if p_img:
                ctk.CTkLabel(p_hdr, image=p_img, text="").pack(side="left", padx=(0, 6))

            ctk.CTkLabel(p_hdr, text=prov_label, font=Theme.font_heading(), text_color=Theme.TEXT_PRIMARY).pack(side="left")

            # Table Header Row
            th_row = ctk.CTkFrame(p_card, fg_color=Theme.BG_SIDEBAR, corner_radius=Theme.RADIUS_SM)
            th_row.pack(fill="x", padx=14, pady=2)
            th_row.grid_columnconfigure(0, weight=2)
            th_row.grid_columnconfigure(1, weight=2)
            th_row.grid_columnconfigure(2, weight=3)
            th_row.grid_columnconfigure(3, weight=2)
            th_row.grid_columnconfigure(4, weight=1)

            ctk.CTkLabel(th_row, text="СЛОТ / АККАУНТ", font=Theme.font_caption(), text_color=Theme.TEXT_MUTED).grid(row=0, column=0, padx=8, pady=6, sticky="w")
            ctk.CTkLabel(th_row, text="АВТОРИЗАЦИЯ", font=Theme.font_caption(), text_color=Theme.TEXT_MUTED).grid(row=0, column=1, padx=8, pady=6, sticky="w")
            ctk.CTkLabel(th_row, text="СЕМЕЙСТВА МОДЕЛЕЙ", font=Theme.font_caption(), text_color=Theme.TEXT_MUTED).grid(row=0, column=2, padx=8, pady=6, sticky="w")
            ctk.CTkLabel(th_row, text="СТАТУС ЗДОРОВЬЯ", font=Theme.font_caption(), text_color=Theme.TEXT_MUTED).grid(row=0, column=3, padx=8, pady=6, sticky="w")
            ctk.CTkLabel(th_row, text="ПРОВЕРКА", font=Theme.font_caption(), text_color=Theme.TEXT_MUTED).grid(row=0, column=4, padx=8, pady=6, sticky="w")

            # Table Rows
            for p in profs:
                tr = ctk.CTkFrame(p_card, fg_color=Theme.SURFACE_MUTED, corner_radius=Theme.RADIUS_SM)
                tr.pack(fill="x", padx=14, pady=2)
                tr.grid_columnconfigure(0, weight=2)
                tr.grid_columnconfigure(1, weight=2)
                tr.grid_columnconfigure(2, weight=3)
                tr.grid_columnconfigure(3, weight=2)
                tr.grid_columnconfigure(4, weight=1)

                # Col 0: Account / Slot
                ctk.CTkLabel(tr, text=f"{p.display_name}\n({p.profile_id})", font=Theme.font_body(), text_color=Theme.TEXT_PRIMARY, justify="left").grid(row=0, column=0, padx=8, pady=8, sticky="w")

                # Col 1: Auth
                auth_txt = "✓ Подключён" if p.auth_state == "AUTHENTICATED" else ("⚠️ Требуется вход" if p.auth_state == "AUTH_EXPIRED" else "— Не добавлен")
                auth_col = Theme.STATUS_HEALTHY if p.auth_state == "AUTHENTICATED" else Theme.TEXT_MUTED
                ctk.CTkLabel(tr, text=f"{auth_txt}\n{p.account_identity}", font=Theme.font_caption(), text_color=auth_col, justify="left").grid(row=0, column=1, padx=8, pady=8, sticky="w")

                # Col 2: Model Families
                fams_txt = "\n".join(f"• {k}: {v.status_label_ru}" for k, v in list(p.model_states.items())[:2]) or "default"
                ctk.CTkLabel(tr, text=fams_txt, font=Theme.font_mono_sm(), text_color=Theme.TEXT_SECONDARY, justify="left").grid(row=0, column=2, padx=8, pady=8, sticky="w")

                # Col 3: Status
                st_col = Theme.STATUS_HEALTHY if p.health_state == STATUS_HEALTHY else (Theme.STATUS_WARNING if "quota" in p.health_state or "auth" in p.health_state else (Theme.TEXT_MUTED if p.health_state == STATUS_NOT_CONFIGURED else Theme.STATUS_ERROR))
                ctk.CTkLabel(tr, text=f"● {p.health_label_ru}", font=Theme.font_caption(), text_color=st_col).grid(row=0, column=3, padx=8, pady=8, sticky="w")

                # Col 4: Last check
                ctk.CTkLabel(tr, text=p.last_checked_at or "—", font=Theme.font_caption(), text_color=Theme.TEXT_MUTED).grid(row=0, column=4, padx=8, pady=8, sticky="w")
