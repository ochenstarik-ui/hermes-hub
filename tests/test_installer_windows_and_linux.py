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
        # Установщик несёт содержимое вшитым ресурсом и распаковывает его через
        # ZipFile — сборка требует System.IO.Compression.FileSystem.
        "/r:System.Windows.Forms.dll", "/r:System.Drawing.dll",
        "/r:System.IO.Compression.FileSystem.dll", str(setup_cs)
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


def test_windows_installer_creates_standard_shortcut_and_cleans_legacy():
    """Verify HermesHubSetup.cs creates standard Hermes Hub.lnk shortcut and cleans up legacy shortcuts."""
    setup_cs = (INSTALLER_DIR / "HermesHubSetup.cs").read_text(encoding="utf-8")

    assert "Hermes Hub.lnk" in setup_cs
    assert "Hermes Hub (Web).lnk" in setup_cs
    assert "Hermes Hub (Desktop).lnk" in setup_cs
    assert "HermesHubWeb.exe" in setup_cs


def test_linux_installer_script_structure():
    """Verify install-linux.sh contains prerequisite checks, mirroring, manifest, and .desktop setup."""
    install_sh = (INSTALLER_DIR / "install-linux.sh").read_text(encoding="utf-8")

    assert "#!/usr/bin/env bash" in install_sh
    assert "deployment_manifest.json" in install_sh
    assert "hermes-hub-web.desktop" in install_sh
    assert "HERMES_HOME" in install_sh
    assert "antigravity-provider" in install_sh

    # Значок .desktop-записи должен быть растровым (PNG/SVG), не .ico.
    #
    # Измерено на настоящем GTK-рабочем столе: GdkPixbuf.Pixbuf.new_from_file
    # на .ico падает с "Compressed icons are not supported", а .desktop-файл
    # с нерендерящейся иконкой меню приложений и файловый менеджер просто
    # показывают пустым — без ошибки, молча. HermesHub.ico в тех же ассетах
    # существует и раньше подставлялся сюда, поэтому мало проверить, что путь
    # не пуст — нужно, чтобы это не был именно .ico.
    icon_line = next(line for line in install_sh.splitlines() if line.startswith("ICON_PATH="))
    assert ".ico" not in icon_line, f"иконка .desktop-записи — .ico, GTK его не рендерит: {icon_line!r}"


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


def test_linux_uninstaller_stops_running_hub():
    """A61/A62: uninstall-linux.sh must stop the hub before deleting its files.

    Раньше удаление не трогало работающий процесс: rm -rf уходил под живым
    сервером, а с --purge-user-data ещё и сносил каталоги, на которые у
    процесса были открыты файловые дескрипторы. Хаб продолжал отвечать по
    старому порту после «успешного» удаления. Измерено живым прогоном:
    сервер, запущенный в песочнице, оставался в списке процессов после
    uninstall-linux.sh до этой правки.
    """
    uninstall_sh = (INSTALLER_DIR / "uninstall-linux.sh").read_text(encoding="utf-8")
    assert "lib_stop_running_hub.sh" in uninstall_sh
    assert "stop_running_hub" in uninstall_sh


def test_linux_stop_launcher_exists_and_reuses_shared_logic():
    """A61/A62: должен существовать способ остановить хаб не из терминала руками.

    На Windows это «Exit» из системного трея HermesHubWeb.exe. На Linux до
    этого не было ничего — ни кнопки в интерфейсе (её нет ни на одной
    платформе), ни трея, ни пункта меню: сервер, оставленный в фоне после
    закрытия окна браузера, можно было остановить только pkill'ом из
    терминала. launcher/hermes-hub-stop.sh — недостающий эквивалент,
    устанавливается install-linux.sh как второй пункт меню приложений.
    """
    stop_sh = (LAUNCHER_DIR / "hermes-hub-stop.sh").read_text(encoding="utf-8")
    assert "#!/usr/bin/env bash" in stop_sh
    assert "stop_running_hub" in stop_sh

    lib_sh = (INSTALLER_DIR / "lib_stop_running_hub.sh").read_text(encoding="utf-8")
    assert "stop_running_hub()" in lib_sh
    # Общий источник, а не третья копия той же функции: install и uninstall
    # обязаны ссылаться на тот же файл, а не хранить свою версию.
    install_sh = (INSTALLER_DIR / "install-linux.sh").read_text(encoding="utf-8")
    uninstall_sh = (INSTALLER_DIR / "uninstall-linux.sh").read_text(encoding="utf-8")
    for script_name, script_text in (("install-linux.sh", install_sh), ("uninstall-linux.sh", uninstall_sh)):
        assert "lib_stop_running_hub.sh" in script_text, f"{script_name} не источает общую функцию"
        assert script_text.count("stop_running_hub() {") == 0, (
            f"{script_name} держит собственную копию функции вместо общего источника"
        )

    assert "hermes-hub-stop" in install_sh, "install-linux.sh не разворачивает лаунчер остановки"
    assert "hermes-hub-stop.desktop" in install_sh, "у лаунчера остановки нет пункта меню"
    assert "hermes-hub-stop" in uninstall_sh, "uninstall-linux.sh не убирает лаунчер остановки"
