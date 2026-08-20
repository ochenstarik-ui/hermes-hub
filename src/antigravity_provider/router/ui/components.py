"""Hermes Hub — Reusable Design System Component Library (v2)."""
from __future__ import annotations

import tkinter as tk
from typing import Any, Callable, Dict, List, Optional, Tuple
import customtkinter as ctk

from antigravity_provider.router.ui.theme import Theme


class HubButton(ctk.CTkButton):
    """Design-system compliant button supporting primary, secondary, ghost and danger variants."""

    def __init__(
        self,
        master: Any,
        text: str,
        variant: str = "primary",  # primary | secondary | ghost | danger | accent_outline
        command: Optional[Callable] = None,
        width: int = 120,
        height: int = Theme.HEIGHT_BTN_MD,
        font: Optional[Tuple[str, int, str]] = None,
        **kwargs,
    ):
        if font is None:
            font = Theme.font_subheading() if variant in ("primary", "danger") else Theme.font_body()

        fg_color = Theme.ACCENT
        hover_color = Theme.ACCENT_HOVER
        text_color = Theme.TEXT_ON_ACCENT
        border_width = 0
        border_color = None

        if variant == "primary":
            fg_color = Theme.ACCENT
            hover_color = Theme.ACCENT_HOVER
            text_color = Theme.TEXT_ON_ACCENT
        elif variant == "secondary":
            fg_color = Theme.SURFACE
            hover_color = Theme.SURFACE_HOVER
            text_color = Theme.TEXT_PRIMARY
            border_width = 1
            border_color = Theme.BORDER
        elif variant == "ghost":
            fg_color = "transparent"
            hover_color = Theme.SURFACE_HOVER
            text_color = Theme.TEXT_PRIMARY
        elif variant == "danger":
            fg_color = "#5A1E1E"
            hover_color = "#7A2828"
            text_color = "#FFD6D6"
            border_width = 1
            border_color = "#8A3333"
        elif variant == "accent_outline":
            fg_color = "transparent"
            hover_color = Theme.ACCENT_DIM
            text_color = Theme.ACCENT
            border_width = 1
            border_color = Theme.ACCENT

        btn_kwargs = {
            "master": master,
            "text": text,
            "command": command,
            "width": width,
            "height": height,
            "corner_radius": Theme.RADIUS_SM,
            "fg_color": fg_color,
            "hover_color": hover_color,
            "text_color": text_color,
            "border_width": border_width,
            "font": font,
        }
        if border_color is not None:
            btn_kwargs["border_color"] = border_color
        btn_kwargs.update(kwargs)

        super().__init__(**btn_kwargs)


class HubCard(ctk.CTkFrame):
    """Card container with standardized surface color, subtle border and corner radius."""

    def __init__(
        self,
        master: Any,
        corner_radius: int = Theme.RADIUS_MD,
        border_width: int = 1,
        border_color: str = Theme.BORDER,
        fg_color: str = Theme.SURFACE,
        **kwargs,
    ):
        super().__init__(
            master=master,
            corner_radius=corner_radius,
            border_width=border_width,
            border_color=border_color,
            fg_color=fg_color,
            **kwargs,
        )


class HubSectionHeader(ctk.CTkFrame):
    """Section title with optional subtitle and right-aligned action button."""

    def __init__(
        self,
        master: Any,
        title: str,
        subtitle: Optional[str] = None,
        action_text: Optional[str] = None,
        action_cmd: Optional[Callable] = None,
        **kwargs,
    ):
        super().__init__(master=master, fg_color="transparent", **kwargs)

        left = ctk.CTkFrame(self, fg_color="transparent")
        left.pack(side="left", fill="both", expand=True)

        ctk.CTkLabel(
            left,
            text=title,
            font=Theme.font_title_section(),
            text_color=Theme.TEXT_PRIMARY,
        ).pack(anchor="w")

        if subtitle:
            ctk.CTkLabel(
                left,
                text=subtitle,
                font=Theme.font_caption(),
                text_color=Theme.TEXT_MUTED,
            ).pack(anchor="w", pady=(2, 0))

        if action_text and action_cmd:
            HubButton(
                self,
                text=action_text,
                variant="primary",
                command=action_cmd,
                height=Theme.HEIGHT_BTN_MD,
            ).pack(side="right", padx=(10, 0))


class HubStatusBadge(ctk.CTkFrame):
    """Status pill with dot and localized label for all normalized health states."""

    STATUS_MAP = {
        "healthy": (Theme.STATUS_HEALTHY, "Работает"),
        "quota_low": (Theme.STATUS_WARNING, "Квота заканчивается"),
        "quota_exhausted": (Theme.STATUS_ERROR, "Квота исчерпана"),
        "cooldown": (Theme.STATUS_WARNING, "Ожидание сброса"),
        "rate_limited": (Theme.STATUS_WARNING, "Лимит запросов"),
        "auth_required": (Theme.STATUS_AUTH_REQUIRED, "Требуется вход"),
        "auth_expired": (Theme.STATUS_AUTH_REQUIRED, "Авторизация истекла"),
        "disabled": (Theme.STATUS_DISABLED, "Отключён"),
        "cold_spare": (Theme.TEXT_MUTED, "Холодный резерв"),
        "unhealthy": (Theme.STATUS_ERROR, "Ошибка"),
        "not_tested": (Theme.TEXT_MUTED, "Не проверен"),
    }

    def __init__(self, master: Any, status_key: str, **kwargs):
        super().__init__(master=master, fg_color=Theme.SURFACE_MUTED, corner_radius=Theme.RADIUS_PILL, **kwargs)

        clean_key = status_key.lower().replace("-", "_")
        color, label = self.STATUS_MAP.get(clean_key, (Theme.TEXT_MUTED, status_key))

        inner = ctk.CTkFrame(self, fg_color="transparent")
        inner.pack(padx=8, pady=3)

        ctk.CTkLabel(
            inner,
            text="●",
            font=("Segoe UI", 12, "bold"),
            text_color=color,
        ).pack(side="left", padx=(0, 4))

        ctk.CTkLabel(
            inner,
            text=label,
            font=Theme.font_micro(),
            text_color=Theme.TEXT_SECONDARY,
        ).pack(side="left")


class HubProviderBadge(ctk.CTkFrame):
    """Badge indicating the AI provider with distinct color."""

    def __init__(self, master: Any, provider: str, **kwargs):
        super().__init__(master=master, fg_color="transparent", **kwargs)

        prov = provider.lower()
        if "antigravity" in prov:
            color = Theme.PROVIDER_ANTIGRAVITY
            name = "Google Antigravity"
            icon = "G"
        elif "codex" in prov:
            color = Theme.PROVIDER_CODEX
            name = "OpenAI Codex"
            icon = "◈"
        elif "opencode" in prov:
            color = Theme.PROVIDER_OPENCODE
            name = "OpenCode Go"
            icon = "◈"
        else:
            color = Theme.TEXT_MUTED
            name = provider
            icon = "◈"

        badge = ctk.CTkFrame(self, fg_color=Theme.SURFACE_MUTED, corner_radius=Theme.RADIUS_SM)
        badge.pack(side="left")

        ctk.CTkLabel(
            badge,
            text=f"{icon} {name}",
            font=Theme.font_micro(),
            text_color=color,
        ).pack(padx=6, pady=2)


class HubMetricCard(HubCard):
    """Dashboard metric card with icon, large number and label."""

    def __init__(
        self,
        master: Any,
        title: str,
        value: str,
        subtext: str,
        icon: str = "◈",
        accent: bool = False,
        **kwargs,
    ):
        border_color = Theme.BORDER_ACCENT if accent else Theme.BORDER
        super().__init__(master=master, border_color=border_color, **kwargs)

        # Header: icon + title
        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", padx=16, pady=(12, 4))

        ctk.CTkLabel(
            top,
            text=icon,
            font=("Segoe UI", 14),
            text_color=Theme.ACCENT if accent else Theme.TEXT_MUTED,
        ).pack(side="left", padx=(0, 6))

        ctk.CTkLabel(
            top,
            text=title.upper(),
            font=Theme.font_micro(),
            text_color=Theme.TEXT_MUTED,
        ).pack(side="left")

        # Value
        val_color = Theme.ACCENT if accent else Theme.TEXT_PRIMARY
        self.val_label = ctk.CTkLabel(
            self,
            text=value,
            font=("Segoe UI", 26, "bold"),
            text_color=val_color,
        )
        self.val_label.pack(anchor="w", padx=16, pady=(2, 2))

        # Subtext
        self.sub_label = ctk.CTkLabel(
            self,
            text=subtext,
            font=Theme.font_caption(),
            text_color=Theme.TEXT_SECONDARY,
        )
        self.sub_label.pack(anchor="w", padx=16, pady=(0, 12))


class HubModal(ctk.CTkToplevel):
    """Reusable modal dialog on dark backdrop."""

    def __init__(self, parent: Any, title: str, width: int = 560, height: int = 480):
        super().__init__(parent)
        self.title(title)
        self.geometry(f"{width}x{height}")
        self.configure(fg_color=Theme.BG_WINDOW)
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        # Center on parent
        self.update_idletasks()
        px = parent.winfo_x() + (parent.winfo_width() - width) // 2
        py = parent.winfo_y() + (parent.winfo_height() - height) // 2
        self.geometry(f"+{px}+{py}")

        self.container = HubCard(
            self,
            corner_radius=Theme.RADIUS_LG,
            border_color=Theme.BORDER_ACCENT,
            fg_color=Theme.DARK,
        )
        self.container.pack(fill="both", expand=True, padx=16, pady=16)

        # Header
        self.hdr = ctk.CTkFrame(self.container, fg_color="transparent")
        self.hdr.pack(fill="x", padx=16, pady=(16, 8))

        self.title_lbl = ctk.CTkLabel(
            self.hdr,
            text=title,
            font=Theme.font_heading(),
            text_color=Theme.TEXT_PRIMARY,
        )
        self.title_lbl.pack(side="left")

        # Body area
        self.body = ctk.CTkFrame(self.container, fg_color="transparent")
        self.body.pack(fill="both", expand=True, padx=16, pady=8)

        # Footer
        self.footer = ctk.CTkFrame(self.container, fg_color="transparent")
        self.footer.pack(fill="x", padx=16, pady=(8, 16))
