"""Script to process and generate multi-resolution provider icons for Hermes Hub."""
from pathlib import Path
from PIL import Image, ImageOps

USER_ASSETS = Path(r"C:\Users\trush\.gemini\antigravity\brain\18159cee-1b4f-42dd-9d89-a0f3ac4c0506\.user_uploaded")
REPO_ROOT = Path(r"E:\Agent projects\hermes-hub")
PROV_SRC = REPO_ROOT / "assets" / "providers" / "source"
PROV_OUT = REPO_ROOT / "assets" / "providers"

PROV_SRC.mkdir(parents=True, exist_ok=True)
PROV_OUT.mkdir(parents=True, exist_ok=True)

# 1. Map uploaded assets
raw_sources = {
    "opencode": USER_ASSETS / "media_1787197959433.jpg",
    "openai": USER_ASSETS / "media_1787197959439.png",
    "antigravity": USER_ASSETS / "media_1787197959591.png",
}

SIZES = [16, 20, 24, 32, 48, 64, 128]

for prov_key, src_path in raw_sources.items():
    if not src_path.exists():
        print(f"Warning: source asset not found: {src_path}")
        continue

    # Save to source
    ext = ".png" if src_path.suffix.lower() == ".png" else ".jpg"
    target_src = PROV_SRC / f"{prov_key}{ext}"
    target_src.write_bytes(src_path.read_bytes())

    # Process image
    img = Image.open(src_path).convert("RGBA")

    # If JPG or black background with white logo, make sure it's clean
    prov_dir = PROV_OUT / prov_key
    prov_dir.mkdir(parents=True, exist_ok=True)

    # Save master
    img.save(prov_dir / f"{prov_key}_master.png", "PNG")

    # Generate each size with LANCZOS
    for sz in SIZES:
        resized = img.resize((sz, sz), Image.Resampling.LANCZOS)
        resized.save(prov_dir / f"{prov_key}_{sz}.png", "PNG")
        print(f"Generated: {prov_dir / f'{prov_key}_{sz}.png'}")

print("\n[SUCCESS] Provider assets generated successfully.")
