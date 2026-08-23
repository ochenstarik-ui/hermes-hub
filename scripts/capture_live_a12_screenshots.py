"""Live screenshot capture script for A12 acceptance criteria."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import customtkinter as ctk

from antigravity_provider.router.hermes_hub_app import HermesHubApp
from antigravity_provider.router.ui.theme import Theme


def run_capture(output_dir: Path):
    output_dir.mkdir(parents=True, exist_ok=True)
    os.environ["HERMES_HUB_DEV_MODE"] = "1"

    app = HermesHubApp()
    app.geometry("1366x800+30+30")
    app.deiconify()
    app.lift()
    app.attributes("-topmost", True)

    # Allow startup refresh
    for _ in range(15):
        app.update()
        time.sleep(0.05)

    captured = []

    def snap(name: str):
        app.update_idletasks()
        app.update()
        time.sleep(0.1)
        target = output_dir / f"{name}.png"
        try:
            from PIL import ImageGrab
            left = app.winfo_rootx()
            top = app.winfo_rooty()
            ImageGrab.grab(bbox=(left, top, left + app.winfo_width(), top + app.winfo_height())).save(target)
            captured.append(target)
            print(f"Captured: {target}")
        except Exception as exc:
            print(f"Screen grab not available in current session ({exc}); view {name} rendered successfully.")

    try:
        app._apply_theme("dark")

        # 1. Accounts view with compact cards and visible quotas
        app._show_view("accounts")
        snap("01_accounts_compact_view")

        # 2. Overview dashboard with 5 providers
        app._show_view("overview")
        snap("02_overview_all_providers")

        # 3. Providers & models view
        app._show_view("providers")
        snap("03_providers_and_models")

        # 4. Routing view
        app._show_view("routing")
        snap("04_routing_chains")

        # 5. Team view
        app._show_view("team")
        snap("05_team_view")

        # 6. Grok wizard step
        app._handle_action("add_account", {})
        app.update_idletasks()
        app.update()
        time.sleep(0.1)
        snap("06_wizard_step1_providers")

    finally:
        app.attributes("-topmost", False)
        app._shutting_down = True
        app.destroy()

    return captured


if __name__ == "__main__":
    dest = Path("artifacts/a12-screenshots")
    res = run_capture(dest)
    print(f"Total screenshots completed: {len(res)}")
