"""Hermes Hub — Asset and Icon Manager."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, Optional, Tuple
from PIL import Image
import customtkinter as ctk


class AssetManager:
    _instance: Optional[AssetManager] = None
    _image_cache: Dict[str, ctk.CTkImage] = {}
    _pil_cache: Dict[str, Image.Image] = {}

    def __init__(self):
        self.root_dir = self._find_repo_root()
        self.branding_dir = self.root_dir / "assets" / "branding"
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
        # Check current file path up to repo root
        cur = Path(__file__).resolve()
        for p in [cur.parents[4], cur.parents[3], cur.parents[2], cur.parents[1]]:
            if (p / "assets" / "branding").exists():
                return p
        # Fallback to localappdata or standard install
        local_app = Path(os.environ.get("LOCALAPPDATA", "")) / "hermes" / "plugins" / "antigravity-provider"
        if (local_app / "assets" / "branding").exists():
            return local_app
        return Path("E:/Agent projects/hermes-hub")

    def get_ico_path(self) -> str:
        ico = self.app_dir / "HermesHub.ico"
        if ico.exists():
            return str(ico)
        alt = self.root_dir / "launcher" / "HermesHub.ico"
        if alt.exists():
            return str(alt)
        return ""

    def get_logo_image(self, size: Tuple[int, int] = (120, 120)) -> Optional[ctk.CTkImage]:
        cache_key = f"logo_{size[0]}x{size[1]}"
        if cache_key in self._image_cache:
            return self._image_cache[cache_key]

        logo_path = self.logo_dir / "logo_256.png"
        if not logo_path.exists():
            logo_path = self.logo_dir / "logo_master.png"
        if not logo_path.exists():
            logo_path = self.branding_dir / "source" / "Hermes Hub.png"

        if logo_path.exists():
            try:
                pil_img = Image.open(logo_path).convert("RGBA")
                ctk_img = ctk.CTkImage(light_image=pil_img, dark_image=pil_img, size=size)
                self._image_cache[cache_key] = ctk_img
                return ctk_img
            except Exception:
                return None
        return None

    def get_splash_logo(self, size: Tuple[int, int] = (160, 160)) -> Optional[ctk.CTkImage]:
        return self.get_logo_image(size=size)
