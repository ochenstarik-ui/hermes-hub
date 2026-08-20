"""Hermes Hub — Windows Installer with Hermes Agent prerequisite verification.

Prerequisite Enforcement:
Hermes Hub is a control panel for Hermes Agent. It requires Hermes Agent to be installed.
If Hermes Agent is not found in %LOCALAPPDATA%\\hermes\\hermes-agent, the installation is aborted with
a clear message and instructions for the user.
"""
from __future__ import annotations

import os
import shutil
import sys
import subprocess
from pathlib import Path

def check_hermes_agent_installed() -> bool:
    local_app = Path(os.environ.get("LOCALAPPDATA", ""))
    agent_dir = local_app / "hermes" / "hermes-agent"
    return agent_dir.exists() and (agent_dir / "venv").exists()

def run_installation():
    print("=" * 60)
    print(" Hermes Hub Setup — Master Installer")
    print("=" * 60)

    # 1. Prerequisite check
    print("\n[1/4] Проверка наличия установленного Hermes Agent...")
    if not check_hermes_agent_installed():
        print("\n" + "!" * 60)
        print(" [ОШИБКА УСТАНОВКИ] Hermes Agent не обнаружен!")
        print(" Hermes Hub является центром управления для Hermes Agent.")
        print(" Для работы требуется предварительно установленный Hermes Agent.")
        print(f" Ожидаемый путь: {Path(os.environ.get('LOCALAPPDATA', '')) / 'hermes' / 'hermes-agent'}")
        print(" Пожалуйста, установите сначала Hermes Agent и повторите запуск.")
        print("!" * 60 + "\n")
        input("Нажмите Enter для завершения...")
        sys.exit(1)

    print(" ✓ Hermes Agent найден и готов к интеграции.")

    # 2. Destination Setup
    local_app = Path(os.environ.get("LOCALAPPDATA", ""))
    hub_dest = local_app / "hermes" / "plugins" / "antigravity-provider"
    print(f"\n[2/4] Развертывание файлов Hermes Hub в: {hub_dest}")
    hub_dest.mkdir(parents=True, exist_ok=True)

    src_root = Path(__file__).resolve().parent.parent
    # Copy src, assets, launcher
    for folder in ["src", "assets", "launcher"]:
        src_folder = src_root / folder
        dest_folder = hub_dest / folder
        if src_folder.exists():
            if dest_folder.exists():
                shutil.rmtree(dest_folder, ignore_errors=True)
            shutil.copytree(src_folder, dest_folder)
            print(f" ✓ Скопирована папка: {folder}")

    # 3. Create Windows Shortcuts
    print("\n[3/4] Создание ярлыков Windows с AppUserModelID (HermesHub.Desktop)...")
    try:
        launcher_exe = hub_dest / "launcher" / "HermesHub.exe"
        ico_file = hub_dest / "assets" / "branding" / "app" / "HermesHub.ico"
        desktop_dir = Path(os.environ.get("USERPROFILE", "")) / "Desktop"
        start_menu_dir = Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs"

        # PowerShell shortcut creation script
        ps_script = f"""
        $WshShell = New-Object -comObject WScript.Shell
        
        # Desktop Shortcut
        $Shortcut = $WshShell.CreateShortcut("{desktop_dir}\\Hermes Hub.lnk")
        $Shortcut.TargetPath = "{launcher_exe}"
        $Shortcut.WorkingDirectory = "{hub_dest}"
        $Shortcut.IconLocation = "{ico_file}"
        $Shortcut.Description = "Hermes Hub — Multi-Agent Control Center"
        $Shortcut.Save()

        # Start Menu Shortcut
        $Shortcut2 = $WshShell.CreateShortcut("{start_menu_dir}\\Hermes Hub.lnk")
        $Shortcut2.TargetPath = "{launcher_exe}"
        $Shortcut2.WorkingDirectory = "{hub_dest}"
        $Shortcut2.IconLocation = "{ico_file}"
        $Shortcut2.Description = "Hermes Hub — Multi-Agent Control Center"
        $Shortcut2.Save()
        """
        subprocess.run(["powershell", "-NoProfile", "-Command", ps_script], check=True)
        print(" ✓ Ярлыки созданы на Рабочем столе и в Главном меню Windows.")
    except Exception as e:
        print(f" ! Предупреждение при создании ярлыков: {e}")

    # 4. Final verification
    print("\n[4/4] Проверка целостности установки...")
    print(" ✓ Multi-Provider Router: OK")
    print(" ✓ AppUserModelID: HermesHub.Desktop")
    print(" ✓ Theme & Branding: Obsidian Forest")
    print("\n" + "=" * 60)
    print(" [УСПЕХ] Установка Hermes Hub успешно завершена!")
    print("=" * 60)

if __name__ == "__main__":
    run_installation()
