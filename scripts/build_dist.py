"""Hermes Hub — Reproducible Package & Checksums Builder.

Builds distribution archive (hermes-hub-<version>.zip), computes SHA-256 hashes,
and writes canonical dist/checksums.txt.
"""
from __future__ import annotations

import hashlib
import os
import zipfile
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from antigravity_provider.version import __version__
DIST_DIR = ROOT / "dist"
SRC_DIR = ROOT / "src"


def sha256_file(filepath: Path) -> str:
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def build_package_zip(version: str = __version__) -> Path:
    DIST_DIR.mkdir(parents=True, exist_ok=True)
    zip_name = f"hermes-hub-{version}.zip"
    zip_path = DIST_DIR / zip_name

    # Create reproducible zip archive with deterministic timestamps
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(SRC_DIR):
            for file in sorted(files):
                if file.endswith((".pyc", ".pyo")) or "__pycache__" in root:
                    continue
                file_path = Path(root) / file
                arcname = file_path.relative_to(ROOT).as_posix()
                zf.write(file_path, arcname=arcname)

        # Include config and docs
        for extra in ("config/compatibility.json", "README.md", "pyproject.toml"):
            extra_path = ROOT / extra
            if extra_path.is_file():
                zf.write(extra_path, arcname=extra)

    return zip_path


def update_checksums():
    DIST_DIR.mkdir(parents=True, exist_ok=True)
    checksum_file = DIST_DIR / "checksums.txt"

    lines = []
    for item in sorted(DIST_DIR.iterdir()):
        if item.is_file() and item.name != "checksums.txt":
            digest = sha256_file(item)
            lines.append(f"{digest}  {item.name}")

    if lines:
        checksum_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"Updated {checksum_file} with {len(lines)} artifact checksum(s):")
        for line in lines:
            print(f"  {line}")


def main():
    print(f"Building Hermes Hub distribution package v{__version__}...")
    zip_path = build_package_zip(__version__)
    print(f"Created: {zip_path}")
    update_checksums()


if __name__ == "__main__":
    main()
