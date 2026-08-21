import tkinter as tk
from typing import Any, Callable, Dict, List, Optional, Tuple

try:
    import customtkinter as ctk
except ImportError:
    import unittest.mock as _mock

    ctk = _mock.MagicMock()

from antigravity_provider.router.ui.theme import Theme
from antigravity_provider.router.ui.assets import AssetManager


class HubButton(ctk.CTkButton):
    """Design-system compliant button supporting primary, secondary, ghost, danger and accent_outline variants."""

    def __init__(
        self,
        master: Any,
        text: str,
        variant: str = "primary",  # primary | secondary | ghost | danger | accent_outline
        command: Optional[Callable] = None,
        width: int = 120,
        height: int = Theme.HEIGHT_BTN_MD,
        font: Optional[Tuple[str, int, str]] = None,
        image: Optional[ctk.CTkImage] = None,
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
            fg_color = Theme.DANGER_SURFACE
            hover_color = Theme.DANGER_SURFACE_HOVER
            text_color = Theme.DANGER_TEXT
            border_width = 1
            border_color = Theme.DANGER_BORDER
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
            "image": image,
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


def enable_clipboard_shortcuts(entry_widget: Any) -> None:
    """Enable robust clipboard (Ctrl+V, Ctrl+C, Ctrl+X, Ctrl+A, Shift+Insert) across English and Cyrillic layouts."""
    inner = getattr(entry_widget, "_entry", entry_widget)

    def _paste_handler(event=None):
        try:
            text = entry_widget.clipboard_get()
            if text is not None:
                try:
                    inner.delete("sel.first", "sel.last")
                except Exception:
                    pass
                inner.insert("insert", text)
            return "break"
        except Exception:
            return "break"

    def _select_all_handler(event=None):
        try:
            inner.select_range(0, "end")
            inner.icursor("end")
            return "break"
        except Exception:
            return "break"

    def _copy_handler(event=None):
        try:
            if inner.select_present():
                sel = inner.selection_get()
                entry_widget.clipboard_clear()
                entry_widget.clipboard_append(sel)
            return "break"
        except Exception:
            pass

    def _cut_handler(event=None):
        try:
            if inner.select_present():
                sel = inner.selection_get()
                entry_widget.clipboard_clear()
                entry_widget.clipboard_append(sel)
                inner.delete("sel.first", "sel.last")
            return "break"
        except Exception:
            pass

    # Standard Latin shortcuts
    for p in (
        "<Control-v>",
        "<Control-V>",
        "<Control-KeyPress-v>",
        "<Control-KeyPress-V>",
        "<Shift-Insert>",
        "<Shift-KeyPress-Insert>",
    ):
        try:
            inner.bind(p, _paste_handler, add=False)
        except Exception:
            pass
    for a in ("<Control-a>", "<Control-A>", "<Control-KeyPress-a>", "<Control-KeyPress-A>"):
        try:
            inner.bind(a, _select_all_handler, add=False)
        except Exception:
            pass
    for c in ("<Control-c>", "<Control-C>", "<Control-KeyPress-c>", "<Control-KeyPress-C>"):
        try:
            inner.bind(c, _copy_handler, add=False)
        except Exception:
            pass
    for x in ("<Control-x>", "<Control-X>", "<Control-KeyPress-x>", "<Control-KeyPress-X>"):
        try:
            inner.bind(x, _cut_handler, add=False)
        except Exception:
            pass

    # Windows Cyrillic / Russian keyboard layouts
    for p in ("<Control-KeyPress-1084>", "<Control-KeyPress-1052>", "<Control-cyrillic_em>", "<Control-Cyrillic_EM>"):
        try:
            inner.bind(p, _paste_handler, add=False)
        except Exception:
            pass
    for a in ("<Control-KeyPress-1092>", "<Control-KeyPress-1060>", "<Control-cyrillic_ef>", "<Control-Cyrillic_EF>"):
        try:
            inner.bind(a, _select_all_handler, add=False)
        except Exception:
            pass
    for c in ("<Control-KeyPress-1089>", "<Control-KeyPress-1057>", "<Control-cyrillic_es>", "<Control-Cyrillic_ES>"):
        try:
            inner.bind(c, _copy_handler, add=False)
        except Exception:
            pass
    for x in ("<Control-KeyPress-1095>", "<Control-KeyPress-1063>", "<Control-cyrillic_che>", "<Control-Cyrillic_CHE>"):
        try:
            inner.bind(x, _cut_handler, add=False)
        except Exception:
            pass


class HubEntry(ctk.CTkEntry):
    """Design-system compliant Entry with automatic clipboard & keyboard layout support."""

    def __init__(self, master: Any, **kwargs):
        super().__init__(master=master, **kwargs)
        enable_clipboard_shortcuts(self)


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
            font=Theme.font_title_page(),
            text_color=Theme.TEXT_PRIMARY,
        ).pack(anchor="w")

        if subtitle:
            ctk.CTkLabel(
                left,
                text=subtitle,
                font=Theme.font_caption(),
                text_color=Theme.TEXT_MUTED,
            ).pack(anchor="w", pady=(Theme.SPACE_XS, 0))

        if action_text and action_cmd:
            HubButton(
                self,
                text=action_text,
                variant="primary",
                command=action_cmd,
                height=Theme.HEIGHT_BTN_MD,
            ).pack(side="right", padx=(Theme.SPACE_MD, 0))


class HubStatusBadge(ctk.CTkFrame):
    """Status pill with dot and localized label for all normalized health states."""

    STATUS_MAP = {
        "healthy": (Theme.STATUS_HEALTHY, "Работает"),
        "quota_low": (Theme.STATUS_WARNING, "Квота заканчивается"),
        "quota_exhausted": (Theme.STATUS_ERROR, "Квота исчерпана"),
        "cooldown": (Theme.STATUS_WARNING, "Ожидание сброса"),
        "rate_limited": (Theme.STATUS_WARNING, "Лимит запросов"),
        "not_configured": (Theme.TEXT_MUTED, "Аккаунт не добавлен"),
        "auth_required": (Theme.STATUS_AUTH_REQUIRED, "Требуется вход"),
        "auth_expired": (Theme.STATUS_AUTH_REQUIRED, "Требуется повторная авторизация"),
        "disabled": (Theme.STATUS_DISABLED, "Отключён"),
        "cold_spare": (Theme.TEXT_MUTED, "Холодный резерв"),
        "unhealthy": (Theme.STATUS_ERROR, "Ошибка"),
        "not_tested": (Theme.TEXT_MUTED, "Не проверен"),
    }

    def __init__(self, master: Any, status_key: str, **kwargs):
        super().__init__(master=master, fg_color=Theme.SURFACE_MUTED, corner_radius=Theme.RADIUS_PILL, **kwargs)

        inner = ctk.CTkFrame(self, fg_color="transparent")
        inner.pack(padx=Theme.SPACE_MD, pady=Theme.SPACE_XS)

        self.dot = ctk.CTkLabel(
            inner,
            text="●",
            font=Theme.font_badge_bold(),
        )
        self.dot.pack(side="left", padx=(0, Theme.SPACE_XS))

        self.label = ctk.CTkLabel(
            inner,
            font=Theme.font_caption(),
            text_color=Theme.TEXT_SECONDARY,
        )
        self.label.pack(side="left")
        self.set_status(status_key)

    def set_status(self, status_key: str, label: Optional[str] = None) -> None:
        clean_key = (status_key or "unknown").lower().replace("-", "_")
        color, default_label = self.STATUS_MAP.get(clean_key, (Theme.TEXT_MUTED, status_key or "Н/Д"))
        self.dot.configure(text_color=color)
        self.label.configure(text=label or default_label)


class HubProviderBadge(ctk.CTkFrame):
    """Badge indicating the AI provider with real provider mark."""

    def __init__(self, master: Any, provider: str, size: Tuple[int, int] = (18, 18), **kwargs):
        super().__init__(master=master, fg_color="transparent", **kwargs)

        prov = provider.lower()
        if "antigravity" in prov:
            color = Theme.PROVIDER_ANTIGRAVITY
            name = "Google Antigravity"
        elif "codex" in prov or "openai" in prov:
            color = Theme.PROVIDER_CODEX
            name = "OpenAI Codex"
        elif "opencode" in prov:
            color = Theme.PROVIDER_OPENCODE
            name = "OpenCode Go"
        else:
            color = Theme.TEXT_MUTED
            name = provider

        badge = ctk.CTkFrame(self, fg_color=Theme.SURFACE_MUTED, corner_radius=Theme.RADIUS_SM)
        badge.pack(side="left")

        img = AssetManager.get().get_provider_image(prov, size=size)
        if img:
            ctk.CTkLabel(badge, image=img, text="").pack(
                side="left", padx=(Theme.SPACE_SM, Theme.SPACE_XS), pady=Theme.SPACE_XS
            )

        ctk.CTkLabel(
            badge,
            text=name,
            font=Theme.font_caption(),
            text_color=color,
        ).pack(side="left", padx=(0 if img else Theme.SPACE_SM, Theme.SPACE_SM), pady=Theme.SPACE_XS)


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

        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", padx=Theme.CARD_PAD_X, pady=(Theme.CARD_PAD_Y, Theme.SPACE_XS))

        ctk.CTkLabel(
            top,
            text=icon,
            font=Theme.font_icon(),
            text_color=Theme.ACCENT if accent else Theme.TEXT_MUTED,
        ).pack(side="left", padx=(0, Theme.SPACE_SM))

        ctk.CTkLabel(
            top,
            text=title.upper(),
            font=Theme.font_micro(),
            text_color=Theme.TEXT_MUTED,
        ).pack(side="left")

        val_color = Theme.ACCENT if accent else Theme.TEXT_PRIMARY
        self.val_label = ctk.CTkLabel(
            self,
            text=value,
            font=Theme.font_metric(),
            text_color=val_color,
        )
        self.val_label.pack(anchor="w", padx=Theme.CARD_PAD_X, pady=(Theme.SPACE_XS, Theme.SPACE_XS))

        self.sub_label = ctk.CTkLabel(
            self,
            text=subtext,
            font=Theme.font_caption(),
            text_color=Theme.TEXT_SECONDARY,
        )
        self.sub_label.pack(anchor="w", padx=Theme.CARD_PAD_X, pady=(0, Theme.CARD_PAD_Y))


class HubToolbar(ctk.CTkFrame):
    """Cockpit-grade toolbar with Search, Category Filter, and Sorting."""

    def __init__(
        self,
        master: Any,
        on_search: Optional[Callable[[str], None]] = None,
        on_filter: Optional[Callable[[str], None]] = None,
        on_sort: Optional[Callable[[str], None]] = None,
        **kwargs,
    ):
        super().__init__(master=master, fg_color="transparent", **kwargs)
        self.on_search = on_search
        self.on_filter = on_filter
        self.on_sort = on_sort

        # Search Entry
        self.search_entry = ctk.CTkEntry(
            self,
            placeholder_text="🔍 Поиск аккаунта или модели...",
            font=Theme.font_body(),
            height=Theme.HEIGHT_BTN_MD,
            width=260,
            fg_color=Theme.SURFACE,
            border_color=Theme.BORDER,
            text_color=Theme.TEXT_PRIMARY,
        )
        self.search_entry.pack(side="left", padx=(0, Theme.INLINE_GAP))
        self.search_entry.bind("<KeyRelease>", self._handle_search)

        # Filter Option Menu
        self.filter_menu = ctk.CTkOptionMenu(
            self,
            values=["Все статусы", "Подключённые", "Требуют входа", "Квота исчерпана"],
            font=Theme.font_caption(),
            height=Theme.HEIGHT_BTN_MD,
            width=160,
            fg_color=Theme.SURFACE,
            button_color=Theme.SECONDARY,
            text_color=Theme.TEXT_PRIMARY,
            command=self._handle_filter,
        )
        self.filter_menu.pack(side="left", padx=(0, Theme.INLINE_GAP))

        # Sort Option Menu
        self.sort_menu = ctk.CTkOptionMenu(
            self,
            values=["По умолчанию", "По имени", "По статусу", "По провайдеру"],
            font=Theme.font_caption(),
            height=Theme.HEIGHT_BTN_MD,
            width=150,
            fg_color=Theme.SURFACE,
            button_color=Theme.SECONDARY,
            text_color=Theme.TEXT_PRIMARY,
            command=self._handle_sort,
        )
        self.sort_menu.pack(side="left")

    def _handle_search(self, event=None):
        if self.on_search:
            self.on_search(self.search_entry.get().strip().lower())

    def _handle_filter(self, choice: str):
        if self.on_filter:
            self.on_filter(choice)

    def _handle_sort(self, choice: str):
        if self.on_sort:
            self.on_sort(choice)


class HubModal(ctk.CTkToplevel):
    """Reusable modal dialog on dark backdrop."""

    def __init__(self, parent: Any, title: str, width: int = 580, height: int = 500):
        super().__init__(parent)
        self.title(title)
        self.geometry(f"{width}x{height}")
        self.configure(fg_color=Theme.BG_WINDOW)
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

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
        self.container.pack(fill="both", expand=True, padx=Theme.SPACE_LG, pady=Theme.SPACE_LG)

        self.hdr = ctk.CTkFrame(self.container, fg_color="transparent")
        self.hdr.pack(fill="x", padx=Theme.CARD_PAD_X, pady=(Theme.CARD_PAD_Y, Theme.SPACE_SM))

        self.title_lbl = ctk.CTkLabel(
            self.hdr,
            text=title,
            font=Theme.font_title_section(),
            text_color=Theme.TEXT_PRIMARY,
        )
        self.title_lbl.pack(side="left")

        self.body = ctk.CTkFrame(self.container, fg_color="transparent")
        self.body.pack(fill="both", expand=True, padx=Theme.CARD_PAD_X, pady=Theme.SPACE_SM)

        self.footer = ctk.CTkFrame(self.container, fg_color="transparent")
        self.footer.pack(fill="x", padx=Theme.CARD_PAD_X, pady=(Theme.SPACE_SM, Theme.CARD_PAD_Y))


# Public design-system names. Existing Hub-prefixed imports remain compatible.
SectionHeader = HubSectionHeader
StatusBadge = HubStatusBadge
ProviderBadge = HubProviderBadge


def _semantic_color(status: str) -> str:
    """Return an operational colour without using brand gold as health."""
    key = (status or "unknown").lower().replace("-", "_")
    if key in {"healthy", "active", "authenticated", "online", "ready"}:
        return Theme.COLOR_POSITIVE
    if key in {"warning", "quota_low", "cooldown", "reserve", "rate_limited"}:
        return Theme.COLOR_CAUTION
    if key in {"error", "unhealthy", "quota_exhausted", "offline", "auth_expired"}:
        return Theme.COLOR_NEGATIVE
    return Theme.COLOR_NEUTRAL


def ellipsize_text(text: str, max_chars: int = 34) -> str:
    """Truncate long identities while retaining the full value for a tooltip."""
    value = str(text or "")
    if len(value) <= max_chars:
        return value
    return f"{value[: max(1, max_chars - 1)]}…"


class Tooltip:
    """Lightweight tooltip implemented with Tk only; no extra dependency."""

    def __init__(self, widget: Any, text: str):
        self.widget = widget
        self.text = text
        self._window: Optional[tk.Toplevel] = None
        widget.bind("<Enter>", self._show, add="+")
        widget.bind("<Leave>", self._hide, add="+")

    def _show(self, _event=None) -> None:
        if not self.text or self._window is not None:
            return
        self._window = tk.Toplevel(self.widget)
        self._window.wm_overrideredirect(True)
        self._window.wm_geometry(f"+{self.widget.winfo_rootx() + Theme.SPACE_MD}+{self.widget.winfo_rooty() + 28}")
        label = tk.Label(
            self._window,
            text=self.text,
            background=Theme.BG_HEADER,
            foreground=Theme.TEXT_PRIMARY,
            relief="solid",
            borderwidth=1,
            font=Theme.font_caption(),
        )
        label.pack(padx=Theme.SPACE_SM, pady=Theme.SPACE_XS)

    def _hide(self, _event=None) -> None:
        if self._window is not None:
            self._window.destroy()
            self._window = None


class EllipsizedLabel(ctk.CTkLabel):
    """Label that shortens long account identities and exposes the full value."""

    def __init__(self, master: Any, text: str, max_chars: int = 34, **kwargs):
        self.full_text = str(text or "")
        self.max_chars = max_chars
        super().__init__(master, text=ellipsize_text(self.full_text, max_chars), **kwargs)
        self.tooltip = Tooltip(self, self.full_text) if len(self.full_text) > max_chars else None

    def set_text(self, text: str) -> None:
        self.full_text = str(text or "")
        self.configure(text=ellipsize_text(self.full_text, self.max_chars))
        if self.tooltip:
            self.tooltip.text = self.full_text
        elif len(self.full_text) > self.max_chars:
            self.tooltip = Tooltip(self, self.full_text)


class _TextBadge(ctk.CTkFrame):
    """Small neutral badge used for plans and metadata, not health."""

    def __init__(self, master: Any, text: str, text_color: str = Theme.TEXT_SECONDARY, **kwargs):
        super().__init__(
            master=master,
            height=Theme.HEIGHT_BADGE,
            fg_color=Theme.SURFACE_MUTED,
            border_width=1,
            border_color=Theme.BORDER_SUBTLE,
            corner_radius=Theme.RADIUS_PILL,
            **kwargs,
        )
        self.label = ctk.CTkLabel(self, text=text, font=Theme.font_micro(), text_color=text_color)
        self.label.pack(padx=Theme.SPACE_SM, pady=Theme.SPACE_XS)

    def set_text(self, text: str) -> None:
        self.label.configure(text=text)


class PlanBadge(_TextBadge):
    """Provider plan badge. Unknown/empty plans should not instantiate it."""


class QuotaBar(ctk.CTkFrame):
    """Compact quota bar with honest unknown state and semantic thresholds."""

    def __init__(
        self,
        master: Any,
        value: Optional[float] = None,
        label: str = "Квота",
        detail: str = "Н/Д",
        **kwargs,
    ):
        super().__init__(master=master, fg_color="transparent", **kwargs)
        self.header = ctk.CTkFrame(self, fg_color="transparent")
        self.header.pack(fill="x")
        self.label = ctk.CTkLabel(self.header, text=label, font=Theme.font_caption(), text_color=Theme.TEXT_SECONDARY)
        self.label.pack(side="left")
        self.detail = ctk.CTkLabel(self.header, text=detail, font=Theme.font_micro(), text_color=Theme.TEXT_MUTED)
        self.detail.pack(side="right")
        self.progress = ctk.CTkProgressBar(
            self,
            height=Theme.SPACE_SM,
            corner_radius=Theme.RADIUS_PILL,
            fg_color=Theme.BG_SIDEBAR,
            progress_color=Theme.COLOR_NEUTRAL,
        )
        self.progress.pack(fill="x", pady=(Theme.SPACE_XS, 0))
        self.set_value(value, detail)

    def set_value(self, value: Optional[float], detail: Optional[str] = None) -> None:
        if value is None:
            self.progress.set(0)
            self.progress.configure(progress_color=Theme.COLOR_NEUTRAL)
            self.detail.configure(text=detail or "Н/Д", text_color=Theme.TEXT_MUTED)
            return
        normalized = max(0.0, min(1.0, float(value)))
        color = (
            Theme.COLOR_NEGATIVE
            if normalized <= 0.05
            else (Theme.COLOR_CAUTION if normalized <= 0.20 else Theme.COLOR_POSITIVE)
        )
        self.progress.set(normalized)
        self.progress.configure(progress_color=color)
        self.detail.configure(text=detail or f"{normalized:.0%}", text_color=color)


class QuotaBucketWidget(HubCard):
    """Reusable quota bucket updated in place by a stable bucket key."""

    def __init__(
        self,
        master: Any,
        bucket_key: str,
        label: str,
        remaining_ratio: Optional[float] = None,
        reset_text: str = "",
        is_estimated: bool = False,
        **kwargs,
    ):
        super().__init__(master, corner_radius=Theme.RADIUS_SM, border_color=Theme.BORDER_SUBTLE, **kwargs)
        self.bucket_key = bucket_key
        self.title = ctk.CTkLabel(self, text="", font=Theme.font_body_bold(), text_color=Theme.TEXT_PRIMARY)
        self.title.pack(anchor="w", padx=Theme.CARD_PAD_X, pady=(Theme.SPACE_SM, Theme.SPACE_XS))
        self.bar = QuotaBar(self, label="Остаток")
        self.bar.pack(fill="x", padx=Theme.CARD_PAD_X)
        self.reset = ctk.CTkLabel(self, text="", font=Theme.font_micro(), text_color=Theme.TEXT_MUTED)
        self.reset.pack(anchor="w", padx=Theme.CARD_PAD_X, pady=(Theme.SPACE_XS, Theme.SPACE_SM))
        self.update_bucket(label, remaining_ratio, reset_text, is_estimated)

    def update_bucket(
        self,
        label: str,
        remaining_ratio: Optional[float],
        reset_text: str = "",
        is_estimated: bool = False,
        detail: Optional[str] = None,
    ) -> None:
        suffix = " • оценка" if is_estimated else ""
        self.title.configure(text=f"{label}{suffix}")
        self.bar.set_value(remaining_ratio, detail or ("Н/Д" if remaining_ratio is None else None))
        self.reset.configure(text=reset_text or "Сброс: Н/Д")


class SearchField(HubEntry):
    """Normalized searchable text field with clipboard support."""

    def __init__(self, master: Any, placeholder_text: str = "Поиск…", width: int = 260, **kwargs):
        super().__init__(
            master,
            placeholder_text=placeholder_text,
            width=width,
            height=Theme.HEIGHT_INPUT,
            font=Theme.font_body(),
            fg_color=Theme.SURFACE,
            border_color=Theme.BORDER,
            text_color=Theme.TEXT_PRIMARY,
            **kwargs,
        )


class FilterButton(ctk.CTkOptionMenu):
    """Compact filter selector with a consistent visual treatment."""

    def __init__(self, master: Any, values: List[str], command: Optional[Callable] = None, **kwargs):
        super().__init__(
            master,
            values=values,
            command=command,
            height=Theme.HEIGHT_INPUT,
            font=Theme.font_caption(),
            fg_color=Theme.SURFACE,
            button_color=Theme.SECONDARY,
            button_hover_color=Theme.SURFACE_HOVER,
            text_color=Theme.TEXT_PRIMARY,
            **kwargs,
        )


class ActionButton(HubButton):
    """Semantic alias used for text actions in views."""


class IconButton(HubButton):
    """Square icon action using the existing lightweight asset infrastructure."""

    def __init__(self, master: Any, text: str, size: int = Theme.HEIGHT_BTN_SM, **kwargs):
        super().__init__(master, text=text, width=size, height=size, variant="ghost", **kwargs)


class EmptyState(HubCard):
    """Honest empty/unknown state with an optional recovery action."""

    def __init__(
        self,
        master: Any,
        title: str,
        message: str,
        action_text: Optional[str] = None,
        action_cmd: Optional[Callable] = None,
        **kwargs,
    ):
        super().__init__(master, border_color=Theme.BORDER_SUBTLE, fg_color=Theme.SURFACE_MUTED, **kwargs)
        ctk.CTkLabel(self, text=title, font=Theme.font_heading(), text_color=Theme.TEXT_PRIMARY).pack(
            pady=(Theme.SPACE_LG, Theme.SPACE_XS)
        )
        ctk.CTkLabel(self, text=message, font=Theme.font_caption(), text_color=Theme.TEXT_MUTED).pack(
            padx=Theme.SPACE_LG, pady=(0, Theme.SPACE_MD)
        )
        if action_text and action_cmd:
            ActionButton(self, text=action_text, variant="secondary", command=action_cmd).pack(pady=(0, Theme.SPACE_LG))


class RouteTargetWidget(HubCard):
    """One node in a primary → reserve failover chain."""

    def __init__(self, master: Any, rank: str, title: str, subtitle: str, status: str = "unknown", **kwargs):
        super().__init__(master, corner_radius=Theme.RADIUS_SM, **kwargs)
        self.rank = ctk.CTkLabel(self, text=rank, font=Theme.font_micro(), text_color=Theme.TEXT_MUTED)
        self.rank.pack(anchor="w", padx=Theme.CARD_PAD_X, pady=(Theme.SPACE_SM, 0))
        self.title = ctk.CTkLabel(self, text=title, font=Theme.font_body_bold(), text_color=Theme.TEXT_PRIMARY)
        self.title.pack(anchor="w", padx=Theme.CARD_PAD_X, pady=(Theme.SPACE_XS, 0))
        self.subtitle = ctk.CTkLabel(self, text=subtitle, font=Theme.font_micro(), text_color=Theme.TEXT_MUTED)
        self.subtitle.pack(anchor="w", padx=Theme.CARD_PAD_X, pady=(0, Theme.SPACE_SM))
        self.update_target(rank, title, subtitle, status)

    def update_target(self, rank: str, title: str, subtitle: str, status: str = "unknown") -> None:
        self.rank.configure(text=rank)
        self.title.configure(text=title)
        self.subtitle.configure(text=subtitle)
        self.set_status(status)

    def set_status(self, status: str) -> None:
        self.configure(border_color=_semantic_color(status))


class AccountCardWidget(HubCard):
    """Keyed account card whose quota buckets are updated without rebuilding the card."""

    def __init__(
        self,
        master: Any,
        profile_id: str,
        identity: str,
        provider: str,
        status: str = "unknown",
        compact: bool = False,
        on_action: Optional[Callable[[str, Any], None]] = None,
        **kwargs,
    ):
        super().__init__(master, **kwargs)
        self.profile_id = profile_id
        self.profile_model: Any = None
        self.on_action = on_action
        self.compact = compact
        self._quota_widgets: Dict[str, QuotaBucketWidget] = {}
        self.widgets_created = 0
        self.widgets_destroyed = 0

        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", padx=Theme.CARD_PAD_X, pady=(Theme.CARD_PAD_Y, Theme.SPACE_XS))
        self.provider = ctk.CTkLabel(top, text=provider, font=Theme.font_micro(), text_color=Theme.TEXT_MUTED)
        self.provider.pack(side="left")
        self.toggle = IconButton(top, text="▾", command=self.toggle_compact)
        self.toggle.pack(side="right")

        self.identity = EllipsizedLabel(self, text=identity, font=Theme.font_body_bold(), text_color=Theme.TEXT_PRIMARY)
        self.identity.pack(anchor="w", padx=Theme.CARD_PAD_X)
        self.meta = ctk.CTkLabel(self, text="", font=Theme.font_micro(), text_color=Theme.TEXT_MUTED)
        self.meta.pack(anchor="w", padx=Theme.CARD_PAD_X, pady=(Theme.SPACE_XS, 0))
        self.status = StatusBadge(self, status)
        self.status.pack(anchor="w", padx=Theme.CARD_PAD_X, pady=Theme.SPACE_SM)

        self.details = ctk.CTkFrame(self, fg_color="transparent")
        self.details.pack(fill="x")
        self.quota_box = ctk.CTkFrame(self.details, fg_color="transparent")
        self.quota_box.pack(fill="x", padx=Theme.CARD_PAD_X)
        self.empty_quota = ctk.CTkLabel(
            self.quota_box, text="Квота: Н/Д", font=Theme.font_caption(), text_color=Theme.TEXT_MUTED
        )
        self.actions = ctk.CTkFrame(self.details, fg_color="transparent")
        self.actions.pack(fill="x", padx=Theme.CARD_PAD_X, pady=(Theme.SPACE_SM, Theme.CARD_PAD_Y))
        ActionButton(
            self.actions,
            text="Обновить",
            variant="secondary",
            width=86,
            command=lambda: self._trigger("refresh_account"),
        ).pack(side="left")
        ActionButton(
            self.actions,
            text="Удалить",
            variant="ghost",
            width=72,
            command=lambda: self._trigger("delete_credentials"),
        ).pack(side="right")
        self.set_compact(compact)

    @staticmethod
    def resolve_identity(profile: Any) -> str:
        """Contract order: email → normalized account identity → display name → profile id."""
        for value in (
            getattr(profile, "email", None),
            getattr(profile, "account_identity", None),
            getattr(profile, "display_name", None),
            getattr(profile, "profile_id", None),
        ):
            if value and str(value).strip() and str(value).strip() not in {"—", "Н/Д"}:
                return str(value).strip()
        return "Аккаунт: Н/Д"

    def _trigger(self, action: str) -> None:
        if self.on_action and self.profile_model is not None:
            self.on_action(action, self.profile_model)

    def toggle_compact(self) -> None:
        self.set_compact(not self.compact)

    def set_compact(self, compact: bool) -> None:
        self.compact = compact
        self.toggle.configure(text="▸" if compact else "▾")
        if compact:
            self.details.pack_forget()
        else:
            self.details.pack(fill="x")

    def update_account(self, profile: Any, quota_snapshot: Optional[Any] = None) -> None:
        self.profile_model = profile
        self.profile_id = profile.profile_id
        self.identity.set_text(self.resolve_identity(profile))
        self.provider.configure(text=profile.provider_display_name or profile.provider)
        roles = ", ".join(getattr(profile, "assigned_roles", []) or []) or "Роль: Н/Д"
        self.meta.configure(text=f"{profile.display_name} • {roles}")
        self.status.set_status(profile.health_state, getattr(profile, "health_label_ru", None))
        self.configure(border_color=Theme.BORDER_ACCENT if profile.is_main_account else Theme.BORDER)

        snapshot = quota_snapshot or getattr(profile, "quota_snapshot", None)
        buckets = list(getattr(snapshot, "buckets", None) or [])
        estimated = bool(getattr(snapshot, "is_estimated", True)) if snapshot else True
        seen: set[str] = set()
        for bucket in buckets:
            key = str(getattr(bucket, "id", "") or getattr(bucket, "display_name", "bucket"))
            seen.add(key)
            remaining = getattr(bucket, "remaining_percent", None)
            ratio = float(remaining) / 100.0 if remaining is not None else None
            if ratio is None:
                remaining_abs = getattr(bucket, "remaining_absolute", None)
                limit_abs = getattr(bucket, "limit_absolute", None)
                if remaining_abs is not None and limit_abs:
                    ratio = float(remaining_abs) / float(limit_abs)
            detail = bucket.formatted_remaining() if hasattr(bucket, "formatted_remaining") else "Н/Д"
            reset = bucket.formatted_reset() if hasattr(bucket, "formatted_reset") else None
            if key not in self._quota_widgets:
                widget = QuotaBucketWidget(self.quota_box, key, bucket.display_name)
                widget.pack(fill="x", pady=(0, Theme.SPACE_SM))
                self._quota_widgets[key] = widget
                self.widgets_created += 1
            self._quota_widgets[key].update_bucket(
                bucket.display_name,
                ratio,
                reset or "Сброс: Н/Д",
                estimated,
                detail,
            )

        for key in list(self._quota_widgets):
            if key not in seen:
                self._quota_widgets.pop(key).destroy()
                self.widgets_destroyed += 1
        if buckets:
            self.empty_quota.pack_forget()
        else:
            self.empty_quota.pack(anchor="w", pady=Theme.SPACE_SM)


class AgentCardWidget(HubCard):
    """Model-agnostic agent-card shell shared by team views."""

    def __init__(self, master: Any, name: str, role: str, detail: str = "Н/Д", **kwargs):
        super().__init__(master, **kwargs)
        ctk.CTkLabel(self, text=role, font=Theme.font_micro(), text_color=Theme.TEXT_MUTED).pack(
            anchor="w", padx=Theme.CARD_PAD_X, pady=(Theme.CARD_PAD_Y, Theme.SPACE_XS)
        )
        ctk.CTkLabel(self, text=name, font=Theme.font_body_bold(), text_color=Theme.TEXT_PRIMARY).pack(
            anchor="w", padx=Theme.CARD_PAD_X
        )
        ctk.CTkLabel(self, text=detail, font=Theme.font_caption(), text_color=Theme.TEXT_SECONDARY).pack(
            anchor="w", padx=Theme.CARD_PAD_X, pady=(Theme.SPACE_XS, Theme.CARD_PAD_Y)
        )


class ConfirmDialog(HubModal):
    """Reusable destructive/non-destructive confirmation dialog."""

    def __init__(
        self,
        parent: Any,
        title: str,
        message: str,
        on_confirm: Callable[[], None],
        destructive: bool = False,
    ):
        super().__init__(parent, title=title, width=440, height=240)
        ctk.CTkLabel(
            self.body,
            text=message,
            wraplength=380,
            justify="left",
            font=Theme.font_body(),
            text_color=Theme.TEXT_SECONDARY,
        ).pack(fill="x")
        ActionButton(self.footer, text="Отмена", variant="ghost", command=self.destroy).pack(side="right")

        def _confirm() -> None:
            self.destroy()
            on_confirm()

        ActionButton(
            self.footer,
            text="Подтвердить",
            variant="danger" if destructive else "primary",
            command=_confirm,
        ).pack(side="right", padx=(0, Theme.SPACE_SM))


class Toast(HubCard):
    """Non-blocking in-window notification with an optional auto-dismiss timer."""

    def __init__(self, master: Any, message: str, status: str = "unknown", duration_ms: int = 4000, **kwargs):
        super().__init__(master, border_color=_semantic_color(status), fg_color=Theme.BG_HEADER, **kwargs)
        ctk.CTkLabel(self, text=message, font=Theme.font_caption(), text_color=Theme.TEXT_PRIMARY).pack(
            padx=Theme.CARD_PAD_X, pady=Theme.CARD_PAD_Y
        )
        if duration_ms > 0:
            self.after(duration_ms, self.destroy)
