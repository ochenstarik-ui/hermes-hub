"""Hermes Hub — Asset and Icon Manager with Provider Icon Caching."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

try:
    from PIL import Image, ImageDraw
except ImportError:
    Image = None
    ImageDraw = None

try:
    import customtkinter as ctk
except ImportError:
    import unittest.mock as _mock

    ctk = _mock.MagicMock()


class AssetManager:
    _instance: Optional[AssetManager] = None
    _image_cache: Dict[str, ctk.CTkImage] = {}
    _pil_cache: Dict[str, Any] = {}

    def __init__(self):
        self.root_dir = self._find_repo_root()
        self.branding_dir = self.root_dir / "assets" / "branding"
        self.providers_dir = self.root_dir / "assets" / "providers"
        self.logo_dir = self.branding_dir / "logo"
        self.app_dir = self.branding_dir / "app"
        self.splash_dir = self.branding_dir / "splash"
        self.icons_dir = self.branding_dir / "icons"

    @classmethod
    def get(cls) -> AssetManager:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _find_repo_root(self) -> Path:
        from antigravity_provider.paths import get_repo_root
        return get_repo_root()

    def get_ico_path(self) -> str:
        ico = self.app_dir / "HermesHub.ico"
        if ico.exists():
            return str(ico)
        alt = self.root_dir / "launcher" / "HermesHub.ico"
        if alt.exists():
            return str(alt)
        return ""

    @classmethod
    def clear_cache(cls):
        cls._image_cache.clear()
        cls._pil_cache.clear()

    def get_logo_image(self, size: Tuple[int, int] = (120, 120)) -> Optional[ctk.CTkImage]:
        logo_path = self.logo_dir / "logo_approved.png"
        if not logo_path.exists():
            logo_path = self.logo_dir / "logo_256.png"
        if not logo_path.exists():
            logo_path = self.logo_dir / "logo_master.png"
        if not logo_path.exists():
            logo_path = self.branding_dir / "source" / "Hermes Hub.png"

        if logo_path.exists():
            try:
                pil_img = Image.open(logo_path).convert("RGBA")
                from antigravity_provider.router.ui.theme import Theme

                transparent = pil_img.copy()
                pixels = []
                tint_gold = Theme.current_scheme in {"dark", "hybrid"}
                dark_fill = tuple(int(Theme.BG_SIDEBAR[index : index + 2], 16) for index in (1, 3, 5))
                pixel_data = (
                    transparent.get_flattened_data()
                    if hasattr(transparent, "get_flattened_data")
                    else transparent.getdata()
                )
                for red, green, blue, alpha in pixel_data:
                    if red > 232 and green > 230 and blue > 224:
                        pixels.append((red, green, blue, 0))
                    elif tint_gold and max(red, green, blue) < 105:
                        pixels.append((*dark_fill, alpha))
                    else:
                        pixels.append((red, green, blue, alpha))
                transparent.putdata(pixels)
                return ctk.CTkImage(light_image=transparent, dark_image=transparent, size=size)
            except Exception:
                return None
        return None

    def get_provider_image(self, provider: str, size: Tuple[int, int] = (20, 20)) -> Optional[ctk.CTkImage]:
        """Fetch cached CTkImage for AI providers (antigravity, openai, opencode)."""
        prov_clean = provider.lower()
        if "antigravity" in prov_clean:
            key_name = "antigravity"
        elif "codex" in prov_clean or "openai" in prov_clean:
            key_name = "openai"
        elif "opencode" in prov_clean:
            key_name = "opencode"
        else:
            key_name = "antigravity"

        cache_key = f"prov_{key_name}_{size[0]}x{size[1]}"
        if cache_key in self._image_cache:
            return self._image_cache[cache_key]

        prov_folder = self.providers_dir / key_name
        # Find best size matching
        target_file = prov_folder / f"{key_name}_{size[0]}.png"
        if not target_file.exists():
            target_file = prov_folder / f"{key_name}_32.png"
        if not target_file.exists():
            target_file = prov_folder / f"{key_name}_master.png"

        if target_file.exists():
            try:
                pil_img = Image.open(target_file).convert("RGBA")
                return ctk.CTkImage(light_image=pil_img, dark_image=pil_img, size=size)
            except Exception:
                return None
        return None

    def get_nav_icon(self, name: str, size: int = 20) -> Optional[ctk.CTkImage]:
        """Return a consistent gold outline icon for the sidebar."""
        if Image is None or ImageDraw is None:
            return None
        from antigravity_provider.router.ui.theme import Theme

        cache_key = f"nav_{Theme.current_scheme}_{name}_{size}"
        if cache_key in self._image_cache:
            return self._image_cache[cache_key]
        scale = 4
        canvas_size = size * scale
        image = Image.new("RGBA", (canvas_size, canvas_size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        color = Theme.TEXT_ACCENT
        width = 2 * scale

        def points(values):
            return tuple(tuple(int(coord * scale) for coord in point) for point in values)

        def line(values, **kwargs):
            draw.line(points(values), fill=color, width=width, joint="curve", **kwargs)

        def ellipse(box):
            draw.ellipse(tuple(int(value * scale) for value in box), outline=color, width=width)

        def rectangle(box, radius=0):
            scaled = tuple(int(value * scale) for value in box)
            if radius:
                draw.rounded_rectangle(scaled, radius=radius * scale, outline=color, width=width)
            else:
                draw.rectangle(scaled, outline=color, width=width)

        if name == "overview":
            line(((3, 10), (10, 4), (17, 10)))
            line(((5, 9), (5, 17), (15, 17), (15, 9)))
            line(((8, 17), (8, 12), (12, 12), (12, 17)))
        elif name == "team":
            ellipse((3, 4, 9, 10))
            ellipse((11, 5, 16, 10))
            draw.arc((1 * scale, 9 * scale, 12 * scale, 19 * scale), 190, 350, fill=color, width=width)
            draw.arc((8 * scale, 10 * scale, 19 * scale, 19 * scale), 190, 350, fill=color, width=width)
        elif name == "accounts":
            draw.ellipse((3 * scale, 3 * scale, 17 * scale, 8 * scale), outline=color, width=width)
            line(((3, 5.5), (3, 15), (5, 17), (15, 17), (17, 15), (17, 5.5)))
            draw.arc((3 * scale, 8 * scale, 17 * scale, 13 * scale), 0, 180, fill=color, width=width)
        elif name == "routing":
            ellipse((2, 8, 6, 12))
            ellipse((8, 2, 12, 6))
            ellipse((14, 8, 18, 12))
            ellipse((8, 14, 12, 18))
            line(((6, 10), (14, 10)))
            line(((10, 6), (10, 14)))
        elif name == "orchestrator":
            ellipse((6, 6, 14, 14))
            for box in ((2, 2, 5, 5), (15, 2, 18, 5), (2, 15, 5, 18), (15, 15, 18, 18)):
                ellipse(box)
            line(((5, 5), (7, 7)))
            line(((15, 5), (13, 7)))
            line(((5, 15), (7, 13)))
            line(((15, 15), (13, 13)))
        elif name == "providers":
            draw.arc((2 * scale, 7 * scale, 18 * scale, 17 * scale), 175, 365, fill=color, width=width)
            draw.arc((5 * scale, 2 * scale, 14 * scale, 13 * scale), 190, 350, fill=color, width=width)
            line(((4, 16), (16, 16)))
        elif name == "quotas":
            line(((10, 2), (17, 5), (16, 13), (10, 18), (4, 13), (3, 5), (10, 2)))
            line(((7, 10), (9, 12), (13, 7)))
        elif name == "analytics":
            rectangle((3, 11, 6, 17))
            rectangle((8.5, 7, 11.5, 17))
            rectangle((14, 3, 17, 17))
            line(((2, 18), (18, 18)))
        elif name == "health":
            line(((2, 11), (6, 11), (8, 5), (11, 16), (13, 9), (18, 9)))
        elif name == "logs":
            rectangle((4, 2, 16, 18), radius=1)
            line(((7, 7), (13, 7)))
            line(((7, 11), (13, 11)))
            line(((7, 15), (11, 15)))
        elif name == "incidents":
            line(((10, 2), (18, 17), (2, 17), (10, 2)))
            line(((10, 7), (10, 12)))
            ellipse((9.3, 14, 10.7, 15.4))
        elif name == "settings":
            ellipse((7, 7, 13, 13))
            for angle in range(0, 360, 45):
                import math

                start = (10 + 5 * math.cos(math.radians(angle)), 10 + 5 * math.sin(math.radians(angle)))
                end = (10 + 8 * math.cos(math.radians(angle)), 10 + 8 * math.sin(math.radians(angle)))
                line((start, end))
        else:
            ellipse((3, 3, 17, 17))
            line(((10, 8), (10, 15)))
            ellipse((9.3, 5, 10.7, 6.4))

        image = image.resize((size, size), Image.Resampling.LANCZOS)
        result = ctk.CTkImage(light_image=image, dark_image=image, size=(size, size))
        self._image_cache[cache_key] = result
        return result
