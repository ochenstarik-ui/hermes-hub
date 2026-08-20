"""Hermes Hub — About View (О программе)."""
from __future__ import annotations

from typing import Any, Optional
import customtkinter as ctk

from antigravity_provider.router.ui.theme import Theme
from antigravity_provider.router.ui.assets import AssetManager
from antigravity_provider.router.ui.components import (
    HubButton,
    HubCard,
    HubSectionHeader,
)

from antigravity_provider.version import __version__


class AboutView(ctk.CTkFrame):
    def __init__(self, master: Any, **kwargs):
        super().__init__(master=master, fg_color="transparent", **kwargs)
        self._build()

    def _build(self):
        header = HubSectionHeader(
            self,
            title="О программе",
            subtitle="Информация о версии, архитектуре и назначении Hermes Hub",
        )
        header.pack(fill="x", padx=20, pady=(16, 12))

        card = HubCard(self, border_color=Theme.BORDER, fg_color=Theme.SURFACE)
        card.pack(fill="both", expand=True, padx=20, pady=(0, 15))

        # Center logo
        logo_img = AssetManager.get().get_logo_image(size=(140, 140))
        if logo_img:
            logo_lbl = ctk.CTkLabel(card, image=logo_img, text="")
            logo_lbl.pack(pady=(24, 10))

        ctk.CTkLabel(
            card,
            text="HERMES HUB",
            font=Theme.font_title_hero(),
            text_color=Theme.TEXT_ACCENT,
        ).pack(pady=(0, 4))

        ctk.CTkLabel(
            card,
            text="Multi-Agent & Multi-Provider Control Hub",
            font=Theme.font_subheading(),
            text_color=Theme.TEXT_PRIMARY,
        ).pack(pady=(0, 2))

        ctk.CTkLabel(
            card,
            text=f"Версия {__version__}  •  Native Windows Application  •  Local-First",
            font=Theme.font_caption(),
            text_color=Theme.TEXT_MUTED,
        ).pack(pady=(0, 16))

        # Info Box
        info_box = ctk.CTkFrame(card, fg_color=Theme.SURFACE_MUTED, corner_radius=Theme.RADIUS_MD)
        info_box.pack(fill="x", padx=32, pady=(0, 16))

        desc_text = (
            "Hermes Hub — нативный центр управления мультиагентной системой Hermes, "
            "аккаунтами AI-провайдеров, моделями и отказоустойчивой маршрутизацией."
        )
        ctk.CTkLabel(
            info_box,
            text=desc_text,
            font=Theme.font_body(),
            text_color=Theme.TEXT_SECONDARY,
            wraplength=640,
            justify="center",
        ).pack(padx=16, pady=14)

        # Pillars
        pillars_box = ctk.CTkFrame(card, fg_color="transparent")
        pillars_box.pack(fill="x", padx=32, pady=(0, 16))
        for i in range(3):
            pillars_box.grid_columnconfigure(i, weight=1)

        p1 = ctk.CTkFrame(pillars_box, fg_color=Theme.SURFACE_MUTED, corner_radius=Theme.RADIUS_SM)
        p1.grid(row=0, column=0, padx=4, sticky="nsew")
        ctk.CTkLabel(p1, text="🛡️ Fail-Closed", font=Theme.font_subheading(), text_color=Theme.TEXT_PRIMARY).pack(pady=(8, 2))
        ctk.CTkLabel(p1, text="Защита credentials и квот", font=Theme.font_micro(), text_color=Theme.TEXT_MUTED).pack(pady=(0, 8))

        p2 = ctk.CTkFrame(pillars_box, fg_color=Theme.SURFACE_MUTED, corner_radius=Theme.RADIUS_SM)
        p2.grid(row=0, column=1, padx=4, sticky="nsew")
        ctk.CTkLabel(p2, text="🔄 Auto Failover", font=Theme.font_subheading(), text_color=Theme.TEXT_PRIMARY).pack(pady=(8, 2))
        ctk.CTkLabel(p2, text="Мгновенное переключение ролей", font=Theme.font_micro(), text_color=Theme.TEXT_MUTED).pack(pady=(0, 8))

        p3 = ctk.CTkFrame(pillars_box, fg_color=Theme.SURFACE_MUTED, corner_radius=Theme.RADIUS_SM)
        p3.grid(row=0, column=2, padx=4, sticky="nsew")
        ctk.CTkLabel(p3, text="👥 Auto Assignment", font=Theme.font_subheading(), text_color=Theme.TEXT_PRIMARY).pack(pady=(8, 2))
        ctk.CTkLabel(p3, text="Интеллектуальное распределение", font=Theme.font_micro(), text_color=Theme.TEXT_MUTED).pack(pady=(0, 8))
