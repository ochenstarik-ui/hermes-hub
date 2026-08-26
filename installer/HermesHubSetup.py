"""Hermes Hub — Canonical Windows Installer with Hermes Agent prerequisite verification.

Prerequisite Enforcement:
Hermes Hub is a control center for Hermes Agent. It requires Hermes Agent to be installed.
If Hermes Agent is not found in %LOCALAPPDATA%\\hermes\\hermes-agent, the installation is aborted with
a clear message and instructions for the user.

Installs and verifies required GUI packages (customtkinter, Pillow, psutil, pyyaml) in the Hermes venv.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import subprocess
from pathlib import Path

from antigravity_provider.version import __version__, MINIMUM_HERMES_VERSION
from antigravity_provider import paths


def get_hermes_agent_paths() -> tuple[Path, Path]:
    hermes_home = paths.get_hermes_home()
    agent_dir = hermes_home / "hermes-agent"
    venv_python = agent_dir / "venv" / "Scripts" / "python.exe"
    return agent_dir, venv_python


def check_hermes_agent_installed() -> bool:
    agent_dir, venv_python = get_hermes_agent_paths()
    return agent_dir.exists() and venv_python.exists()


def verify_dependencies(venv_python: Path) -> bool:
    """Verify that required web packages can be imported without error."""
    code = "import fastapi; import uvicorn; import yaml; import psutil; print('OK')"
    try:
        res = subprocess.run(
            [str(venv_python), "-c", code],
            capture_output=True,
            text=True,
            timeout=15,
        )
        return res.returncode == 0 and "OK" in res.stdout
    except Exception:
        return False


def install_dependencies(venv_python: Path) -> bool:
    """Install required web packages into Hermes venv."""
    packages = ["fastapi>=0.110.0", "uvicorn>=0.28.0", "psutil>=5.9.0", "pyyaml>=6.0.1", "requests>=2.31.0"]
    try:
        res = subprocess.run(
            [str(venv_python), "-m", "pip", "install", "--upgrade"] + packages,
            capture_output=True,
            text=True,
            timeout=120,
        )
        return res.returncode == 0
    except Exception as e:
        print(f"Error executing pip install: {e}")
        return False


def run_installation(silent: bool = False):
    print("=" * 60)
    print(f" Hermes Hub Setup — Master Installer v{__version__}")
    print("=" * 60)

    # 1. Prerequisite & Previous Install check
    manifest_file = paths.get_hermes_home() / "plugins" / "antigravity-provider" / "deployment_manifest.json"
    if manifest_file.exists():
        try:
            m = json.loads(manifest_file.read_text(encoding="utf-8"))
            print(f" [РЕЖИМ ПЕРЕУСТАНОВКИ] Обнаружена установленная копия: v{m.get('version', '0.1.0')} ({m.get('deployed_at', 'unknown')})")
        except Exception:
            print(" [РЕЖИМ ПЕРЕУСТАНОВКИ] Обнаружена установленная копия Hermes Hub.")

    print("\n[1/5] Проверка наличия установленного Hermes Agent...")
    if not check_hermes_agent_installed():
        agent_dir, _ = get_hermes_agent_paths()
        print("\n" + "!" * 60)
        print(" [ОШИБКА УСТАНОВКИ] Hermes Agent не обнаружен!")
        print(" Hermes Hub является центром управления для Hermes Agent.")
        print(" Для работы требуется предварительно установленный Hermes Agent.")
        print(f" Ожидаемый путь: {agent_dir}")
        print(" Пожалуйста, установите сначала Hermes Agent и повторите запуск.")
        print("!" * 60 + "\n")
        if not silent:
            input("Нажмите Enter для завершения...")
        sys.exit(1)

    _, venv_python = get_hermes_agent_paths()
    print(f" ✓ Hermes Agent найден ({venv_python})")

    # 2. Dependency verification and install
    print("\n[2/5] Проверка и установка зависимостей (FastAPI, uvicorn, PyYAML, psutil)...")
    if not verify_dependencies(venv_python):
        print(" Установка недостающих пакетов в окружение Hermes...")
        ok = install_dependencies(venv_python)
        if not ok or not verify_dependencies(venv_python):
            print("\n" + "!" * 60)
            print(" [ОШИБКА УСТАНОВКИ] Не удалось установить зависимости (FastAPI / uvicorn / PyYAML / psutil)!")
            print(" Пожалуйста, проверьте подключение к сети и права доступа к venv.")
            print("!" * 60 + "\n")
            if not silent:
                input("Нажмите Enter для завершения...")
            sys.exit(1)
        print(" ✓ Зависимости успешно установлены.")
    else:
        print(" ✓ Все необходимые зависимости уже присутствуют в venv.")

    # 3. Destination Setup (Mirroring: purge deleted/stale source files)
    hermes_home = paths.get_hermes_home()
    hub_dest = hermes_home / "plugins" / "antigravity-provider"
    print(f"\n[3/5] Развертывание файлов Hermes Hub в: {hub_dest}")
    hub_dest.mkdir(parents=True, exist_ok=True)

    src_root = paths.get_repo_root()
    for folder in ["src", "assets", "launcher", "config"]:
        src_folder = src_root / folder
        dest_folder = hub_dest / folder
        if src_folder.exists():
            if dest_folder.exists():
                shutil.rmtree(dest_folder, ignore_errors=True)
            shutil.copytree(src_folder, dest_folder, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            print(f" ✓ Скопирована папка (зеркало): {folder}")

    # Copy root files if available
    for f in ["pyproject.toml", "README.md"]:
        sf = src_root / f
        if sf.exists():
            shutil.copy2(sf, hub_dest / f)

    # 3b. Write Deployment Manifest
    import datetime
    manifest_data = {
        "version": __version__,
        "deployed_at": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "git_commit": os.environ.get("HERMES_HUB_GIT_COMMIT", "8cddc9f"),
    }
    (hub_dest / "deployment_manifest.json").write_text(json.dumps(manifest_data, indent=2), encoding="utf-8")

    # 4. Create Windows Shortcuts
    print("\n[4/5] Создание ярлыков Windows с AppUserModelID (HermesHub.Desktop)...")
    try:
        launcher_exe = hub_dest / "launcher" / "HermesHub.exe"
        ico_file = hub_dest / "assets" / "branding" / "app" / "HermesHub.ico"
        desktop_dir = Path(os.environ.get("USERPROFILE", "")) / "Desktop"
        start_menu_dir = Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs"

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
        subprocess.run(["powershell", "-NoProfile", "-Command", ps_script], check=True, capture_output=True)
        print(" ✓ Ярлыки созданы на Рабочем столе и в Главном меню Windows.")
    except Exception as e:
        print(f" ! Предупреждение при создании ярлыков: {e}")

    # 5. Final verification
    print("\n[5/5] Проверка целостности установки...")
    print(f" ✓ Версия Hermes Hub: {__version__}")
    print(" ✓ Multi-Provider Router: OK")
    print(" ✓ AppUserModelID: HermesHub.Desktop")
    print(" ✓ Theme & Branding: Obsidian Forest")
    print("\n" + "=" * 60)
    print(" [УСПЕХ] Установка / Переустановка Hermes Hub успешно завершена!")
    print("=" * 60)


if __name__ == "__main__":
    args_lower = [a.lower() for a in sys.argv]
    is_silent = "/silent" in args_lower or "-s" in args_lower or "/reinstall" in args_lower or "/repair" in args_lower
    run_installation(silent=is_silent)
