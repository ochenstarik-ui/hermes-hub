"""Hermes Hub — Centralized Design Tokens and Theme Definition (v3).

Source of Truth: Brand Guidelines & Brandbook
Primary Palette:
  PRIMARY:   #0F1510 (Obsidian Forest)
  DARK:      #1A2A1F (Deep Pine)
  SECONDARY: #2F4A36 (Moss Slate)
  LIGHT:     #F7F1E3 (Warm Ivory)
  ACCENT:    #CDAA64 (Ancient Gold)
"""

from __future__ import annotations


class Theme:
    # ── Core Brand Palette ──
    PRIMARY = "#0F1510"
    DARK = "#1A2A1F"
    SECONDARY = "#2F4A36"
    LIGHT = "#F7F1E3"
    ACCENT = "#CDAA64"

    # ── Surfaces & Backgrounds ──
    BG_WINDOW = "#0F1510"
    BG_SIDEBAR = "#142018"
    BG_HEADER = "#16241B"
    BG_STATUSBAR = "#121C15"
    BG_MODAL_BACKDROP = "#080B08"

    SURFACE = "#1D3123"
    SURFACE_HOVER = "#274230"
    SURFACE_ACTIVE = "#31543D"
    SURFACE_SELECTED = "#284432"
    SURFACE_MUTED = "#16251A"

    # ── Borders ──
    BORDER = "#2F4A36"
    BORDER_SUBTLE = "#1F3526"
    BORDER_ACCENT = "#CDAA64"
    BORDER_HOVER = "#40644B"

    # ── Typography Colors ──
    TEXT_PRIMARY = "#F7F1E3"
    TEXT_SECONDARY = "#C5BEAF"
    TEXT_MUTED = "#8A9C8E"
    TEXT_ON_ACCENT = "#0F1510"
    TEXT_ACCENT = "#CDAA64"
    TEXT_DISABLED = "#546457"

    # ── Accent States ──
    ACCENT_HOVER = "#DCBE7D"
    ACCENT_PRESSED = "#BA954E"
    ACCENT_DIM = "#3D3522"
    ACCENT_GLOW = "#CDAA64"

    DANGER_SURFACE = "#5A1E1E"
    DANGER_SURFACE_HOVER = "#7A2828"
    DANGER_BORDER = "#8A3333"
    DANGER_TEXT = "#FFD6D6"

    # ── Operational / Status Colors ──
    STATUS_HEALTHY = "#2E7D32"  # Vibrant Forest Green
    STATUS_WARNING = "#D97706"  # Amber Gold
    STATUS_ERROR = "#DC2626"  # Ruby Crimson
    STATUS_INFO = "#2563EB"  # Azure
    STATUS_AUTH_REQUIRED = "#D97706"
    STATUS_DISABLED = "#5A6B5D"
    STATUS_FAILOVER = "#3B82F6"
    STATUS_MAIN = "#CDAA64"  # Gold Badge
    STATUS_ORCHESTRATOR = "#E5C158"  # Imperial Gold

    # Semantic roles. Brand gold is intentionally not a health colour.
    COLOR_POSITIVE = STATUS_HEALTHY
    COLOR_CAUTION = STATUS_WARNING
    COLOR_NEGATIVE = STATUS_ERROR
    COLOR_NEUTRAL = STATUS_DISABLED
    COLOR_BRAND = ACCENT

    # ── Provider Specific Accent Colors ──
    PROVIDER_ANTIGRAVITY = "#4285F4"  # Google Blue
    PROVIDER_CODEX = "#10A37F"  # OpenAI Emerald
    PROVIDER_OPENCODE = "#F97316"  # OpenCode Orange
    PROVIDER_CLAUDE = "#D97706"
    PROVIDER_GROK = "#3B82F6"
    PROVIDER_GENERIC = "#8B5CF6"

    SCHEMES = ("dark", "hybrid", "light")
    SCHEME_LABELS = {
        "dark": "Тёмная",
        "hybrid": "Средняя (гибрид)",
        "light": "Светлая (бежевая)",
    }
    PALETTES = {
        "dark": {
            "PRIMARY": "#071A17",
            "DARK": "#0B211D",
            "SECONDARY": "#244B3C",
            "LIGHT": "#F4EAD4",
            "ACCENT": "#C89A2B",
            "BG_WINDOW": "#061916",
            "BG_SIDEBAR": "#08221E",
            "BG_HEADER": "#071B18",
            "BG_STATUSBAR": "#061512",
            "BG_MODAL_BACKDROP": "#020B09",
            "SURFACE": "#0B2520",
            "SURFACE_HOVER": "#12342C",
            "SURFACE_ACTIVE": "#194535",
            "SURFACE_SELECTED": "#173B2E",
            "SURFACE_MUTED": "#091E1A",
            "BORDER": "#36513B",
            "BORDER_SUBTLE": "#203A2D",
            "BORDER_ACCENT": "#B78525",
            "BORDER_HOVER": "#537456",
            "TEXT_PRIMARY": "#F8F0DC",
            "TEXT_SECONDARY": "#D1C7AE",
            "TEXT_MUTED": "#8FA395",
            "TEXT_ON_ACCENT": "#102018",
            "TEXT_ACCENT": "#E0B84E",
            "TEXT_DISABLED": "#617367",
            "ACCENT_HOVER": "#E0B84E",
            "ACCENT_PRESSED": "#A9781E",
            "ACCENT_DIM": "#3D3218",
            "ACCENT_GLOW": "#D9AA37",
            "DANGER_SURFACE": "#4A2020",
            "DANGER_SURFACE_HOVER": "#692A2A",
            "DANGER_BORDER": "#8A3B36",
            "DANGER_TEXT": "#FFD8D2",
            "STATUS_HEALTHY": "#72C943",
            "STATUS_WARNING": "#E1A62B",
            "STATUS_ERROR": "#E45C4F",
            "STATUS_INFO": "#4C8DD8",
            "STATUS_AUTH_REQUIRED": "#E1A62B",
            "STATUS_DISABLED": "#708078",
            "STATUS_FAILOVER": "#4C8DD8",
            "STATUS_MAIN": "#C89A2B",
            "STATUS_ORCHESTRATOR": "#E0B84E",
            "PROVIDER_ANTIGRAVITY": "#74A9FF",
            "PROVIDER_CODEX": "#46BE8A",
            "PROVIDER_OPENCODE": "#F39A50",
            "PROVIDER_CLAUDE": "#DF9C63",
            "PROVIDER_GROK": "#6DA6F2",
            "PROVIDER_GENERIC": "#A99DD8",
            "SIDEBAR_TEXT": "#F8F0DC",
            "SIDEBAR_MUTED": "#8FA395",
            "SIDEBAR_HOVER": "#12342C",
            "SIDEBAR_SELECTED": "#173B2E",
        },
        "hybrid": {
            "PRIMARY": "#F7F2E8",
            "DARK": "#0A2721",
            "SECONDARY": "#DCE6D7",
            "LIGHT": "#FCF8F0",
            "ACCENT": "#B98118",
            "BG_WINDOW": "#F5F0E7",
            "BG_SIDEBAR": "#08251F",
            "BG_HEADER": "#FBF8F1",
            "BG_STATUSBAR": "#EFE8DB",
            "BG_MODAL_BACKDROP": "#E8E0D3",
            "SURFACE": "#FBF8F1",
            "SURFACE_HOVER": "#EEE8DA",
            "SURFACE_ACTIVE": "#E1EAD9",
            "SURFACE_SELECTED": "#E4EBD8",
            "SURFACE_MUTED": "#F1EBE0",
            "BORDER": "#D8CCB8",
            "BORDER_SUBTLE": "#E7DDCE",
            "BORDER_ACCENT": "#BD8B2F",
            "BORDER_HOVER": "#AFA188",
            "TEXT_PRIMARY": "#17241D",
            "TEXT_SECONDARY": "#4C584F",
            "TEXT_MUTED": "#7B817B",
            "TEXT_ON_ACCENT": "#FFFFFF",
            "TEXT_ACCENT": "#9B6C13",
            "TEXT_DISABLED": "#A9AAA4",
            "ACCENT_HOVER": "#CF9C39",
            "ACCENT_PRESSED": "#936514",
            "ACCENT_DIM": "#F0E4C8",
            "ACCENT_GLOW": "#C59432",
            "DANGER_SURFACE": "#F8E2DE",
            "DANGER_SURFACE_HOVER": "#F1CBC5",
            "DANGER_BORDER": "#C86155",
            "DANGER_TEXT": "#812E28",
            "STATUS_HEALTHY": "#397B35",
            "STATUS_WARNING": "#BE7B13",
            "STATUS_ERROR": "#C6473D",
            "STATUS_INFO": "#326DAD",
            "STATUS_AUTH_REQUIRED": "#BE7B13",
            "STATUS_DISABLED": "#969B94",
            "STATUS_FAILOVER": "#326DAD",
            "STATUS_MAIN": "#B98118",
            "STATUS_ORCHESTRATOR": "#A87817",
            "PROVIDER_ANTIGRAVITY": "#326DAD",
            "PROVIDER_CODEX": "#247A50",
            "PROVIDER_OPENCODE": "#B96324",
            "PROVIDER_CLAUDE": "#A55C2C",
            "PROVIDER_GROK": "#326DAD",
            "PROVIDER_GENERIC": "#7365A5",
            "SIDEBAR_TEXT": "#F8F0DC",
            "SIDEBAR_MUTED": "#98A89D",
            "SIDEBAR_HOVER": "#12342C",
            "SIDEBAR_SELECTED": "#173B2E",
        },
        "light": {
            "PRIMARY": "#FFF9EE",
            "DARK": "#FFF8EC",
            "SECONDARY": "#E9DFC9",
            "LIGHT": "#FFFDF8",
            "ACCENT": "#A96F12",
            "BG_WINDOW": "#FFF9EF",
            "BG_SIDEBAR": "#FBF0DE",
            "BG_HEADER": "#FFFDF8",
            "BG_STATUSBAR": "#F7EDDE",
            "BG_MODAL_BACKDROP": "#EDE2D2",
            "SURFACE": "#FFFDF8",
            "SURFACE_HOVER": "#F4E9D9",
            "SURFACE_ACTIVE": "#DFE8D7",
            "SURFACE_SELECTED": "#E7EEDC",
            "SURFACE_MUTED": "#F8F0E5",
            "BORDER": "#DDCFB9",
            "BORDER_SUBTLE": "#EDE2D2",
            "BORDER_ACCENT": "#B57A1C",
            "BORDER_HOVER": "#B8A78D",
            "TEXT_PRIMARY": "#1E281F",
            "TEXT_SECONDARY": "#505A51",
            "TEXT_MUTED": "#7E837C",
            "TEXT_ON_ACCENT": "#FFFFFF",
            "TEXT_ACCENT": "#90600F",
            "TEXT_DISABLED": "#ADAEA7",
            "ACCENT_HOVER": "#C58B2D",
            "ACCENT_PRESSED": "#835609",
            "ACCENT_DIM": "#F2E3C4",
            "ACCENT_GLOW": "#BA8428",
            "DANGER_SURFACE": "#F9E5E0",
            "DANGER_SURFACE_HOVER": "#F3D0C9",
            "DANGER_BORDER": "#C85A4E",
            "DANGER_TEXT": "#812E28",
            "STATUS_HEALTHY": "#367B36",
            "STATUS_WARNING": "#B97612",
            "STATUS_ERROR": "#C6473D",
            "STATUS_INFO": "#326DAD",
            "STATUS_AUTH_REQUIRED": "#B97612",
            "STATUS_DISABLED": "#999D96",
            "STATUS_FAILOVER": "#326DAD",
            "STATUS_MAIN": "#A96F12",
            "STATUS_ORCHESTRATOR": "#9D6810",
            "PROVIDER_ANTIGRAVITY": "#326DAD",
            "PROVIDER_CODEX": "#247A50",
            "PROVIDER_OPENCODE": "#B96324",
            "PROVIDER_CLAUDE": "#A55C2C",
            "PROVIDER_GROK": "#326DAD",
            "PROVIDER_GENERIC": "#7365A5",
            "SIDEBAR_TEXT": "#283129",
            "SIDEBAR_MUTED": "#767D76",
            "SIDEBAR_HOVER": "#F0E3D0",
            "SIDEBAR_SELECTED": "#E6EEDB",
        },
    }
    current_scheme = "dark"

    @classmethod
    def apply_scheme(cls, scheme: str) -> str:
        """Activate a complete palette and return its normalized key."""
        normalized = scheme if scheme in cls.PALETTES else "dark"
        for token, value in cls.PALETTES[normalized].items():
            setattr(cls, token, value)
        cls.current_scheme = normalized
        cls.COLOR_POSITIVE = cls.STATUS_HEALTHY
        cls.COLOR_CAUTION = cls.STATUS_WARNING
        cls.COLOR_NEGATIVE = cls.STATUS_ERROR
        cls.COLOR_NEUTRAL = cls.STATUS_DISABLED
        cls.COLOR_BRAND = cls.ACCENT
        return normalized

    # ── Spacing Scale (px) ──
    SPACE_XS = 4
    SPACE_SM = 8
    SPACE_MD = 12
    SPACE_LG = 16
    SPACE_XL = 24
    SPACE_2XL = 32

    # Layout aliases used by views and reusable components.
    PAGE_PAD_X = SPACE_LG
    PAGE_PAD_Y = SPACE_MD
    SECTION_GAP = SPACE_MD
    CARD_PAD_X = SPACE_MD
    CARD_PAD_Y = SPACE_MD
    INLINE_GAP = SPACE_SM

    # ── Corner Radius Scale (px) ──
    RADIUS_SM = 6
    RADIUS_MD = 10
    RADIUS_LG = 14
    RADIUS_PILL = 999

    # ── Control Heights & Dimensions ──
    HEIGHT_BTN_SM = 30
    HEIGHT_BTN_MD = 38
    HEIGHT_BTN_LG = 44
    HEIGHT_NAV_ITEM = 34
    HEIGHT_HEADER = 56
    HEIGHT_STATUSBAR = 30
    WIDTH_SIDEBAR = 190
    HEIGHT_INPUT = 36
    HEIGHT_BADGE = 24
    ACCOUNT_CARD_MIN_HEIGHT = 188
    ACCOUNT_CARD_COLUMNS = 3

    # ── Fonts ──
    FONT_FAMILY_TITLE = "Cinzel"
    FONT_FAMILY_UI = "Segoe UI"
    FONT_FAMILY_MONO = "Consolas"

    @classmethod
    def font_title_hero(cls):
        return (cls.FONT_FAMILY_TITLE, 24, "bold")

    @classmethod
    def font_title_page(cls):
        return (cls.FONT_FAMILY_UI, 20, "bold")

    @classmethod
    def font_title(cls):
        """Compatibility alias for the normalized page title."""
        return cls.font_title_page()

    @classmethod
    def font_title_section(cls):
        return (cls.FONT_FAMILY_UI, 17, "bold")

    @classmethod
    def font_heading(cls):
        return (cls.FONT_FAMILY_UI, 15, "bold")

    @classmethod
    def font_subheading(cls):
        return (cls.FONT_FAMILY_UI, 14, "bold")

    @classmethod
    def font_body(cls):
        return (cls.FONT_FAMILY_UI, 13)

    @classmethod
    def font_body_bold(cls):
        return (cls.FONT_FAMILY_UI, 13, "bold")

    @classmethod
    def font_caption(cls):
        return (cls.FONT_FAMILY_UI, 11)

    @classmethod
    def font_micro(cls):
        return (cls.FONT_FAMILY_UI, 10)

    @classmethod
    def font_mono(cls):
        return (cls.FONT_FAMILY_MONO, 13)

    @classmethod
    def font_mono_sm(cls):
        return (cls.FONT_FAMILY_MONO, 12)

    @classmethod
    def font_micro_bold(cls):
        return (cls.FONT_FAMILY_UI, 10, "bold")

    @classmethod
    def font_badge_bold(cls):
        return (cls.FONT_FAMILY_UI, 10, "bold")

    @classmethod
    def font_icon(cls):
        return (cls.FONT_FAMILY_UI, 15)

    @classmethod
    def font_metric(cls):
        return (cls.FONT_FAMILY_UI, 24, "bold")


Theme.apply_scheme("dark")
