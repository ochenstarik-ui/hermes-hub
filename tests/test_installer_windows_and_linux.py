"""
Hermes Hub — Windows & Linux Installers and Launchers Test Suite.
Verifies requirements of Task A19.
"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
INSTALLER_DIR = REPO_ROOT / "installer"
LAUNCHER_DIR = REPO_ROOT / "launcher"


def test_windows_csharp_launchers_and_setup_compile():
    """Verify HermesHub.cs, HermesHubWeb.cs, and HermesHubSetup.cs compile without errors on Windows."""
    csc_path = r"C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
    if not os.path.isfile(csc_path):
        csc_path = r"C:\Windows\Microsoft.NET\Framework\v4.0.30319\csc.exe"

    if not os.path.isfile(csc_path):
        pytest.skip("csc.exe compiler not found in standard .NET Framework location")

    temp_out = REPO_ROOT / "artifacts" / "test_compile"
    temp_out.mkdir(parents=True, exist_ok=True)

    # 1. Compile HermesHub.cs
    hub_cs = LAUNCHER_DIR / "HermesHub.cs"
    res1 = subprocess.run([
        csc_path, "/target:winexe", f"/out:{temp_out / 'HermesHub.exe'}",
        "/r:System.Windows.Forms.dll", "/r:System.Drawing.dll", str(hub_cs)
    ], capture_output=True, text=True)
    assert res1.returncode == 0, f"HermesHub.cs compilation failed: {res1.stdout}\n{res1.stderr}"

    # 2. Compile HermesHubWeb.cs
    hub_web_cs = LAUNCHER_DIR / "HermesHubWeb.cs"
    res2 = subprocess.run([
        csc_path, "/target:winexe", f"/out:{temp_out / 'HermesHubWeb.exe'}",
        "/r:System.Windows.Forms.dll", "/r:System.Drawing.dll", str(hub_web_cs)
    ], capture_output=True, text=True)
    assert res2.returncode == 0, f"HermesHubWeb.cs compilation failed: {res2.stdout}\n{res2.stderr}"

    # 3. Compile HermesHubSetup.cs
    setup_cs = INSTALLER_DIR / "HermesHubSetup.cs"
    res3 = subprocess.run([
        csc_path, "/target:winexe", f"/out:{temp_out / 'HermesHubSetup.exe'}",
        "/r:System.Windows.Forms.dll", "/r:System.Drawing.dll", str(setup_cs)
    ], capture_output=True, text=True)
    assert res3.returncode == 0, f"HermesHubSetup.cs compilation failed: {res3.stdout}\n{res3.stderr}"


def test_windows_launcher_browser_search_and_health_check():
    """Verify HermesHubWeb.cs includes Edge/Chrome detection, --app mode, and /api/health polling."""
    web_cs = (LAUNCHER_DIR / "HermesHubWeb.cs").read_text(encoding="utf-8")

    assert "msedge.exe" in web_cs
    assert "chrome.exe" in web_cs
    assert "--app=" in web_cs
    assert "/api/health" in web_cs
    assert "IsServerHealthy" in web_cs
    assert "HermesHubWeb" in web_cs or "WebLauncher" in web_cs


def test_windows_installer_creates_both_shortcuts():
    """Verify HermesHubSetup.cs creates both Web and Desktop shortcuts."""
    setup_cs = (INSTALLER_DIR / "HermesHubSetup.cs").read_text(encoding="utf-8")

    assert "Hermes Hub (Web).lnk" in setup_cs
    assert "Hermes Hub (Desktop).lnk" in setup_cs
    assert "HermesHubWeb.exe" in setup_cs
    assert "HermesHub.exe" in setup_cs


def test_linux_installer_script_structure():
    """Verify install-linux.sh contains prerequisite checks, mirroring, manifest, and .desktop setup."""
    install_sh = (INSTALLER_DIR / "install-linux.sh").read_text(encoding="utf-8")

    assert "#!/usr/bin/env bash" in install_sh
    assert "deployment_manifest.json" in install_sh
    assert "hermes-hub-web.desktop" in install_sh
    assert "HERMES_HOME" in install_sh
    assert "antigravity-provider" in install_sh


def test_linux_launcher_script_headless_and_app_mode():
    """Verify hermes-hub-web.sh checks DISPLAY, prints SSH port forwarding on headless, and uses --app on desktop."""
    launcher_sh = (LAUNCHER_DIR / "hermes-hub-web.sh").read_text(encoding="utf-8")

    assert "#!/usr/bin/env bash" in launcher_sh
    assert "DISPLAY" in launcher_sh
    assert "WAYLAND_DISPLAY" in launcher_sh
    assert "ssh -L" in launcher_sh
    assert "127.0.0.1" in launcher_sh
    assert "--app=" in launcher_sh
    assert "/api/health" in launcher_sh
    assert "google-chrome" in launcher_sh or "chromium" in launcher_sh or "microsoft-edge" in launcher_sh


def test_linux_uninstaller_preserves_user_data():
    """Verify uninstall-linux.sh preserves user config, keys, and profiles by default."""
    uninstall_sh = (INSTALLER_DIR / "uninstall-linux.sh").read_text(encoding="utf-8")

    assert "#!/usr/bin/env bash" in uninstall_sh
    assert "PURGE_USER_DATA" in uninstall_sh
    assert "--purge-user-data" in uninstall_sh
    assert "Preserving user data and credentials" in uninstall_sh
    assert "hermes-hub-web.desktop" in uninstall_sh
