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

    # ── Operational / Status Colors ──
    STATUS_HEALTHY = "#2E7D32"      # Vibrant Forest Green
    STATUS_WARNING = "#D97706"      # Amber Gold
    STATUS_ERROR = "#DC2626"        # Ruby Crimson
    STATUS_INFO = "#2563EB"         # Azure
    STATUS_AUTH_REQUIRED = "#D97706"
    STATUS_DISABLED = "#5A6B5D"
    STATUS_FAILOVER = "#3B82F6"
    STATUS_MAIN = "#CDAA64"         # Gold Badge
    STATUS_ORCHESTRATOR = "#E5C158" # Imperial Gold

    # ── Provider Specific Accent Colors ──
    PROVIDER_ANTIGRAVITY = "#4285F4" # Google Blue
    PROVIDER_CODEX = "#10A37F"       # OpenAI Emerald
    PROVIDER_OPENCODE = "#F97316"    # OpenCode Orange

    # ── Spacing Scale (px) ──
    SPACE_XS = 4
    SPACE_SM = 8
    SPACE_MD = 12
    SPACE_LG = 16
    SPACE_XL = 24
    SPACE_2XL = 32

    # ── Corner Radius Scale (px) ──
    RADIUS_SM = 6
    RADIUS_MD = 10
    RADIUS_LG = 14
    RADIUS_PILL = 999

    # ── Control Heights & Dimensions ──
    HEIGHT_BTN_SM = 30
    HEIGHT_BTN_MD = 38
    HEIGHT_BTN_LG = 44
    HEIGHT_NAV_ITEM = 42
    HEIGHT_HEADER = 60
    HEIGHT_STATUSBAR = 30
    WIDTH_SIDEBAR = 240

    # ── Fonts ──
    FONT_FAMILY_TITLE = "Cinzel"
    FONT_FAMILY_UI = "Segoe UI"
    FONT_FAMILY_MONO = "Consolas"

    @classmethod
    def font_title_hero(cls):
        return (cls.FONT_FAMILY_TITLE, 24, "bold")

    @classmethod
    def font_title_page(cls):
        return (cls.FONT_FAMILY_UI, 24, "bold")

    @classmethod
    def font_title_section(cls):
        return (cls.FONT_FAMILY_UI, 19, "bold")

    @classmethod
    def font_heading(cls):
        return (cls.FONT_FAMILY_UI, 16, "bold")

    @classmethod
    def font_subheading(cls):
        return (cls.FONT_FAMILY_UI, 15, "bold")

    @classmethod
    def font_body(cls):
        return (cls.FONT_FAMILY_UI, 14)

    @classmethod
    def font_body_bold(cls):
        return (cls.FONT_FAMILY_UI, 14, "bold")

    @classmethod
    def font_caption(cls):
        return (cls.FONT_FAMILY_UI, 12)

    @classmethod
    def font_micro(cls):
        return (cls.FONT_FAMILY_UI, 11)

    @classmethod
    def font_mono(cls):
        return (cls.FONT_FAMILY_MONO, 13)

    @classmethod
    def font_mono_sm(cls):
        return (cls.FONT_FAMILY_MONO, 12)
