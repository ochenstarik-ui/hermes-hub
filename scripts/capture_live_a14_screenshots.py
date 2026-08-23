"""Comprehensive live screenshot capture for Task A14 criteria."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
import sys
import time
from pathlib import Path
from PIL import Image

import customtkinter as ctk

from antigravity_provider.router.hermes_hub_app import HermesHubApp
from antigravity_provider.router.ui.theme import Theme
from antigravity_provider.router.ui.add_account_wizard import AddAccountWizard
from antigravity_provider.router.router_config import load_router_config


def hwnd_to_image(hwnd: int) -> Image.Image | None:
    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32

    rect = wintypes.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(rect))
    w = rect.right - rect.left
    h = rect.bottom - rect.top
    if w <= 0 or h <= 0:
        return None

    hdc = user32.GetDC(hwnd)
    cdc = gdi32.CreateCompatibleDC(hdc)
    hbmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
    oldbmp = gdi32.SelectObject(cdc, hbmp)

    user32.PrintWindow(hwnd, cdc, 2)

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [
            ("biSize", wintypes.DWORD),
            ("biWidth", wintypes.LONG),
            ("biHeight", wintypes.LONG),
            ("biPlanes", wintypes.WORD),
            ("biBitCount", wintypes.WORD),
            ("biCompression", wintypes.DWORD),
            ("biSizeImage", wintypes.DWORD),
            ("biXPelsPerMeter", wintypes.LONG),
            ("biYPelsPerMeter", wintypes.LONG),
            ("biClrUsed", wintypes.DWORD),
            ("biClrImportant", wintypes.DWORD),
        ]

    class BITMAPINFO(ctypes.Structure):
        _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]

    bmi = BITMAPINFO()
    bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bmi.bmiHeader.biWidth = w
    bmi.bmiHeader.biHeight = -h
    bmi.bmiHeader.biPlanes = 1
    bmi.bmiHeader.biBitCount = 32
    bmi.bmiHeader.biCompression = 0

    buffer = ctypes.create_string_buffer(w * h * 4)
    gdi32.GetDIBits(cdc, hbmp, 0, h, buffer, ctypes.byref(bmi), 0)

    gdi32.SelectObject(cdc, oldbmp)
    gdi32.DeleteObject(hbmp)
    gdi32.DeleteDC(cdc)
    user32.ReleaseDC(hwnd, hdc)

    img = Image.frombuffer("RGBA", (w, h), buffer, "raw", "BGRA", 0, 1)
    return img.convert("RGB")


def capture_all_a14(output_dir: Path):
    output_dir.mkdir(parents=True, exist_ok=True)
    os.environ["HERMES_HUB_DEV_MODE"] = "1"

    app = HermesHubApp()
    app.geometry("1366x800+30+30")
    app.deiconify()
    app.lift()
    app.attributes("-topmost", True)

    for _ in range(15):
        app.update()
        time.sleep(0.04)

    captured = []

    def snap(name: str, target_widget=None):
        app.update_idletasks()
        app.update()
        time.sleep(0.15)
        widget = target_widget or app
        hwnd = widget.winfo_id()
        img = hwnd_to_image(hwnd)
        if img:
            target_path = output_dir / f"{name}.png"
            img.save(target_path)
            captured.append(target_path)
            print(f"Captured: {target_path} ({img.size[0]}x{img.size[1]})")
        else:
            print(f"Could not capture {name}")

    try:
        app._apply_theme("dark")

        # 1. Accounts view: 16 accounts with compact cards and visible quotas
        app._show_view("accounts")
        snap("01_accounts_compact_view")

        # 2. Overview view after section cleanup
        app._show_view("overview")
        snap("02_overview_after_cleanup")

        # 3. Grok wizard - Step 1: Provider selection
        wizard = AddAccountWizard(app, on_complete=lambda res: None)
        wizard.geometry("760x640+200+100")
        wizard.deiconify()
        wizard.lift()
        snap("03_grok_wizard_step1_provider", wizard)

        # 4. Grok wizard - Step 2: Auth Flow
        wizard.provider_var.set("grok")
        wizard._proceed_to_step_2()
        snap("04_grok_wizard_step2_auth", wizard)

        # 5. Grok wizard - Step 3: Validation & Step 4: Role Assignment
        wizard.discovered_identity = "user@xai.com"
        wizard.discovered_plan = "Grok Pro"
        wizard.discovered_models = ["grok-3", "grok-3-mini", "grok-2"]
        wizard.is_verified = True
        wizard._show_step_3_validation()
        snap("05_grok_wizard_step3_validation", wizard)

        wizard._show_step_4_assignment()
        snap("06_grok_wizard_step4_role_assignment", wizard)

        wizard.destroy()

        # 6. Role config modal with chain and quotas
        role_modal = app._open_route_editor_modal("coder-primary")
        if role_modal:
            role_modal.geometry("680x540+220+120")
            role_modal.deiconify()
            role_modal.lift()
            snap("07_role_modal_with_chain_and_quotas", role_modal)
            role_modal.destroy()

        # 7. Account details modal
        config = load_router_config()
        pids = list(config.profiles.keys())
        if pids:
            acc_modal = app._open_account_details_modal(pids[0])
            if acc_modal:
                acc_modal.geometry("680x540+220+120")
                acc_modal.deiconify()
                acc_modal.lift()
                snap("08_account_details_modal", acc_modal)
                acc_modal.destroy()

    finally:
        app.attributes("-topmost", False)
        app._shutting_down = True
        app.destroy()

    return captured


if __name__ == "__main__":
    dest = Path("artifacts/a14-screenshots")
    res = capture_all_a14(dest)
    print(f"Total screenshots captured: {len(res)}")
