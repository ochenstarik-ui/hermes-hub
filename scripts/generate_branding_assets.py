"""Generate all brand assets for Hermes Hub:
- logo PNGs at multiple resolutions (1024, 512, 256, 128, 64, 32)
- app icons (including multi-layer HermesHub.ico with 16, 24, 32, 48, 64, 128, 256)
- splash screen assets
- installer assets
"""
import os
import sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter, ImageOps
import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCE_DIR = REPO_ROOT / "assets" / "branding" / "source"
LOGO_DIR = REPO_ROOT / "assets" / "branding" / "logo"
APP_DIR = REPO_ROOT / "assets" / "branding" / "app"
SPLASH_DIR = REPO_ROOT / "assets" / "branding" / "splash"
INSTALLER_DIR = REPO_ROOT / "assets" / "branding" / "installer"
ICONS_DIR = REPO_ROOT / "assets" / "branding" / "icons"

for d in [LOGO_DIR, APP_DIR, SPLASH_DIR, INSTALLER_DIR, ICONS_DIR]:
    d.mkdir(parents=True, exist_ok=True)

raw_logo_path = SOURCE_DIR / "Hermes Hub.png"
if not raw_logo_path.exists():
    print("Error: Source logo not found at", raw_logo_path)
    sys.exit(1)

raw_logo = Image.open(raw_logo_path).convert("RGBA")
width, height = raw_logo.size

# The logo is a circular emblem. We want to extract the circular emblem cleanly.
# Find circular emblem boundary:
# Center is (width // 2, height // 2). Radius is approximately width * 0.46
cx, cy = width / 2.0, height / 2.0
# The outer gold ring extends to about r = width * 0.47
r = min(width, height) * 0.475

# Create a circular mask with anti-aliasing (supersampled 2x)
mask_hi = Image.new("L", (width * 2, height * 2), 0)
draw_hi = ImageDraw.Draw(mask_hi)
draw_hi.ellipse(
    [(cx - r) * 2, (cy - r) * 2, (cx + r) * 2, (cy + r) * 2],
    fill=255
)
mask = mask_hi.resize((width, height), Image.Resampling.LANCZOS)

# Create clean transparent circular logo
circular_logo = raw_logo.copy()
# Crop to square bounding box of circle
bbox = (int(cx - r), int(cy - r), int(cx + r), int(cy + r))
circular_logo = circular_logo.crop(bbox)
mask_crop = mask.crop(bbox)
circular_logo.putalpha(mask_crop)

# Master square icon on transparent background
master_size = 1024
master_logo = circular_logo.resize((master_size, master_size), Image.Resampling.LANCZOS)

# Save Master Logo PNGs
master_logo.save(LOGO_DIR / "logo_master.png", "PNG")
for sz in [1024, 512, 256, 128, 64, 32]:
    resized = circular_logo.resize((sz, sz), Image.Resampling.LANCZOS)
    resized.save(LOGO_DIR / f"logo_{sz}.png", "PNG")

# App Icons (PNGs)
for sz in [1024, 512, 256, 128, 64, 48, 32, 24, 16]:
    resized = circular_logo.resize((sz, sz), Image.Resampling.LANCZOS)
    resized.save(APP_DIR / f"app_icon_{sz}.png", "PNG")

# Windows Multi-Resolution ICO
ico_sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
ico_images = [circular_logo.resize(s, Image.Resampling.LANCZOS) for s in ico_sizes]
ico_images[0].save(
    APP_DIR / "HermesHub.ico",
    format="ICO",
    sizes=ico_sizes,
    append_images=ico_images[1:]
)
# Also copy to root and launcher dir for executable embedding
ico_images[0].save(REPO_ROOT / "launcher" / "HermesHub.ico", format="ICO", sizes=ico_sizes, append_images=ico_images[1:])

# Splash Screen Background & Logo Assets
# Dark-first background #0F1510
splash_w, splash_h = 600, 360
splash_bg = Image.new("RGBA", (splash_w, splash_h), (15, 21, 16, 255))
# Subtle dark green radial gradient or corner border
draw_s = ImageDraw.Draw(splash_bg)
draw_s.rectangle([(0, 0), (splash_w - 1, splash_h - 1)], outline=(47, 74, 54, 255), width=2)
# Add gold accent line at bottom
draw_s.line([(0, splash_h - 4), (splash_w, splash_h - 4)], fill=(205, 170, 100, 255), width=3)
splash_bg.save(SPLASH_DIR / "splash_bg.png", "PNG")

splash_logo = circular_logo.resize((160, 160), Image.Resampling.LANCZOS)
splash_logo.save(SPLASH_DIR / "splash_logo.png", "PNG")

# Installer Banner & Assets
inst_w, inst_h = 500, 120
inst_banner = Image.new("RGBA", (inst_w, inst_h), (26, 42, 31, 255))
draw_ib = ImageDraw.Draw(inst_banner)
draw_ib.rectangle([(0, 0), (inst_w - 1, inst_h - 1)], outline=(47, 74, 54, 255), width=1)
draw_ib.line([(0, inst_h - 3), (inst_w, inst_h - 3)], fill=(205, 170, 100, 255), width=2)
# Paste small logo on banner
banner_logo = circular_logo.resize((80, 80), Image.Resampling.LANCZOS)
inst_banner.paste(banner_logo, (20, 20), banner_logo)
inst_banner.save(INSTALLER_DIR / "installer_banner.png", "PNG")

ico_images[0].save(INSTALLER_DIR / "installer_icon.ico", format="ICO", sizes=ico_sizes, append_images=ico_images[1:])

print("Successfully generated all branding assets!")
print("App ICO created at:", APP_DIR / "HermesHub.ico")
