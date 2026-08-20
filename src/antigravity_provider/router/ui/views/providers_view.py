"""Hermes Hub — Providers View (Реальные метрики провайдеров и моделей)."""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional
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
    ProviderSummary,
)


class ProvidersView(ctk.CTkFrame):
    def __init__(self, master: Any, app_state: Dict[str, Any], on_action: Optional[Callable] = None, **kwargs):
        super().__init__(master=master, fg_color="transparent", **kwargs)
        self.app_state = app_state
        self.on_action = on_action
        self._build()

    def _build(self):
        header = HubSectionHeader(
            self,
            title="Провайдеры ИИ и Модели",
            subtitle="Сводка доступности адаптеров, квот и обнаруженных языковых моделей",
            action_text="🔄 Обновить модели",
            action_cmd=self._refresh_models,
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

        summaries = snapshot.providers

        for s in summaries:
            col = Theme.PROVIDER_ANTIGRAVITY if "antigravity" in s.provider_id else (Theme.PROVIDER_CODEX if "codex" in s.provider_id else Theme.PROVIDER_OPENCODE)

            card = HubCard(self.scroll, border_color=Theme.BORDER, fg_color=Theme.SURFACE)
            card.pack(fill="x", pady=8)

            # Top Header
            top = ctk.CTkFrame(card, fg_color="transparent")
            top.pack(fill="x", padx=16, pady=(14, 4))

            ctk.CTkLabel(top, text=s.provider_name, font=Theme.font_heading(), text_color=col).pack(side="left")
            ctk.CTkLabel(top, text=f"Обновлено: {s.last_refresh_at}", font=Theme.font_micro(), text_color=Theme.TEXT_MUTED).pack(side="right")

            # Metrics Row (4 mini cards)
            metrics_row = ctk.CTkFrame(card, fg_color="transparent")
            metrics_row.pack(fill="x", padx=16, pady=6)
            for i in range(4):
                metrics_row.grid_columnconfigure(i, weight=1)

            p1 = ctk.CTkFrame(metrics_row, fg_color=Theme.SURFACE_MUTED, corner_radius=Theme.RADIUS_SM)
            p1.grid(row=0, column=0, padx=4, sticky="nsew")
            ctk.CTkLabel(p1, text="ПОДКЛЮЧЕНО", font=Theme.font_micro(), text_color=Theme.TEXT_MUTED).pack(pady=(6, 1))
            ctk.CTkLabel(p1, text=f"{s.connected_count} / {s.total_slots}", font=Theme.font_body_bold(), text_color=Theme.TEXT_PRIMARY).pack(pady=(0, 6))

            p2 = ctk.CTkFrame(metrics_row, fg_color=Theme.SURFACE_MUTED, corner_radius=Theme.RADIUS_SM)
            p2.grid(row=0, column=1, padx=4, sticky="nsew")
            ctk.CTkLabel(p2, text="В СТРОЮ", font=Theme.font_micro(), text_color=Theme.TEXT_MUTED).pack(pady=(6, 1))
            ctk.CTkLabel(p2, text=str(s.online_count), font=Theme.font_body_bold(), text_color=Theme.STATUS_HEALTHY).pack(pady=(0, 6))

            p3 = ctk.CTkFrame(metrics_row, fg_color=Theme.SURFACE_MUTED, corner_radius=Theme.RADIUS_SM)
            p3.grid(row=0, column=2, padx=4, sticky="nsew")
            ctk.CTkLabel(p3, text="ТРЕБУЮТ ВХОДА", font=Theme.font_micro(), text_color=Theme.TEXT_MUTED).pack(pady=(6, 1))
            ctk.CTkLabel(p3, text=str(s.auth_required_count), font=Theme.font_body_bold(), text_color=Theme.STATUS_WARNING if s.auth_required_count > 0 else Theme.TEXT_MUTED).pack(pady=(0, 6))

            p4 = ctk.CTkFrame(metrics_row, fg_color=Theme.SURFACE_MUTED, corner_radius=Theme.RADIUS_SM)
            p4.grid(row=0, column=3, padx=4, sticky="nsew")
            ctk.CTkLabel(p4, text="ХОЛОДНЫЙ РЕЗЕРВ", font=Theme.font_micro(), text_color=Theme.TEXT_MUTED).pack(pady=(6, 1))
            ctk.CTkLabel(p4, text=str(s.cold_spare_count), font=Theme.font_body_bold(), text_color=Theme.TEXT_MUTED).pack(pady=(0, 6))

            # Discovered Models list
            m_box = ctk.CTkFrame(card, fg_color=Theme.SURFACE_MUTED, corner_radius=Theme.RADIUS_SM)
            m_box.pack(fill="x", padx=16, pady=(4, 12))

            ctk.CTkLabel(m_box, text="Доступные проверенные модели:", font=Theme.font_micro(), text_color=Theme.TEXT_MUTED).pack(anchor="w", padx=10, pady=(6, 2))
            models_str = " • ".join(s.discovered_models) if s.discovered_models else "Модели не обнаружены"
            ctk.CTkLabel(m_box, text=models_str, font=Theme.font_mono_sm(), text_color=Theme.TEXT_PRIMARY, wraplength=700, justify="left").pack(anchor="w", padx=10, pady=(0, 8))

    def _refresh_models(self):
        if self.on_action:
            self.on_action("refresh_data", {})
