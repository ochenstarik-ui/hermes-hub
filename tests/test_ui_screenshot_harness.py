"""Manual screenshot harness for every tab in all approved color schemes."""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

pytest.importorskip("customtkinter")
pytest.importorskip("PIL")

from PIL import ImageGrab

from antigravity_provider.router.hermes_hub_app import HermesHubApp


def capture_all(output_dir: Path) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    app = HermesHubApp()
    app.geometry("1366x768+20+20")
    app.deiconify()
    app.lift()
    app.attributes("-topmost", True)
    for _index in range(20):
        app.update()
        time.sleep(0.04)

    captured = []
    try:
        for scheme in ("dark", "hybrid", "light"):
            app._apply_theme(scheme)
            for view_name, _label, _icon in app._nav_items:
                app._show_view(view_name)
                app.update_idletasks()
                app.update()
                time.sleep(0.08)
                left = app.winfo_rootx()
                top = app.winfo_rooty()
                target = output_dir / f"{view_name}-{scheme}.png"
                ImageGrab.grab(bbox=(left, top, left + app.winfo_width(), top + app.winfo_height())).save(target)
                captured.append(target)
    finally:
        app.attributes("-topmost", False)
        app._shutting_down = True
        app.destroy()
    return captured


if __name__ == "__main__":
    destination = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("artifacts/mockup-redesign")
    for screenshot in capture_all(destination):
        print(screenshot)
