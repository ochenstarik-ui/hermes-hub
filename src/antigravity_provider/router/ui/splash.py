"""Hermes Hub — Native Brand Splash Screen."""

from __future__ import annotations

import tkinter as tk
from typing import Optional
import customtkinter as ctk

from antigravity_provider.router.ui.theme import Theme
from antigravity_provider.router.ui.assets import AssetManager


class SplashScreen(ctk.CTkToplevel):
    """Brand-compliant Splash Screen shown during initialization."""

    def __init__(self, parent: ctk.CTk, width: int = 500, height: int = 300):
        super().__init__(parent)
        self.overrideredirect(True)
        self.configure(fg_color=Theme.BG_WINDOW)

        # Center on screen
        self.update_idletasks()
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        x = (sw - width) // 2
        y = (sh - height) // 2
        self.geometry(f"{width}x{height}+{x}+{y}")

        # Container
        container = ctk.CTkFrame(
            self,
            corner_radius=Theme.RADIUS_LG,
            border_width=2,
            border_color=Theme.BORDER_ACCENT,
            fg_color=Theme.BG_WINDOW,
        )
        container.pack(fill="both", expand=True, padx=2, pady=2)

        # Logo
        logo_img = AssetManager.get().get_splash_logo(size=(100, 100))
        if logo_img:
            ctk.CTkLabel(container, image=logo_img, text="").pack(pady=(28, 8))

        ctk.CTkLabel(
            container,
            text="HERMES HUB",
            font=Theme.font_title_hero(),
            text_color=Theme.TEXT_ACCENT,
        ).pack(pady=(0, 2))

        ctk.CTkLabel(
            container,
            text="Multi-Agent & Multi-Provider Control Hub",
            font=Theme.font_body(),
            text_color=Theme.TEXT_PRIMARY,
        ).pack(pady=(0, 16))

        # Progress indicator bar
        self.progress = ctk.CTkProgressBar(
            container,
            width=300,
            height=4,
            corner_radius=2,
            fg_color=Theme.SURFACE,
            progress_color=Theme.ACCENT,
            mode="indeterminate",
        )
        self.progress.pack(pady=(0, 20))
        self.progress.start()

        self.update()

    def close(self):
        try:
            self.progress.stop()
            self.destroy()
        except Exception:
            pass
