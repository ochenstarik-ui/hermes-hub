"""Hermes Hub — Self-Healing Launcher Bootstrap and Crash Handler.

Responsibilities:
1. Dependency Verification & Self-Healing:
   Checks for required packages (customtkinter, pillow, psutil, pyyaml, requests).
   If any package is missing, attempts non-blocking silent auto-installation into the active Python environment.
2. Pre-UI Crash Logging:
   Ensures all startup lifecycle stages and any early unhandled exceptions are written to
   logs/startup.log with full traceback before GUI initialization.
3. Native User Feedback:
   If a fatal crash occurs before a window can be displayed, shows a native Windows error dialog
   pointing to the exact log file location instead of silent process termination.
"""
from __future__ import annotations

import ctypes
import datetime
import os
import subprocess
import sys
import traceback
from pathlib import Path
from typing import Dict, List, Tuple


def get_startup_log_path() -> Path:
    """Resolve startup.log path safely using paths.py."""
    _SRC_DIR = Path(__file__).resolve().parent.parent.parent
    if str(_SRC_DIR) not in sys.path:
        sys.path.insert(0, str(_SRC_DIR))
    from antigravity_provider import paths
    return paths.get_startup_log_file()


def log_startup(msg: str) -> None:
    """Append a timestamped log entry to startup.log."""
    try:
        p = get_startup_log_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(p, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {msg}\n")
    except Exception:
        pass


def show_native_error(title: str, message: str) -> None:
    """Display a native Windows error modal (or fallback to stderr on POSIX)."""
    if sys.platform == "win32":
        try:
            MB_ICONERROR = 0x10
            MB_OK = 0x0
            ctypes.windll.user32.MessageBoxW(0, message, title, MB_ICONERROR | MB_OK)
            return
        except Exception:
            pass
    print(f"[{title}] {message}", file=sys.stderr)


REQUIRED_PACKAGES: Dict[str, str] = {
    "fastapi": "fastapi>=0.110.0",
    "uvicorn": "uvicorn>=0.28.0",
    "psutil": "psutil>=5.9.0",
    "yaml": "pyyaml>=6.0.1",
}


def check_missing_dependencies() -> List[str]:
    """Check which required Web / system packages are currently unimportable."""
    missing = []
    for mod_name, pkg_spec in REQUIRED_PACKAGES.items():
        try:
            __import__(mod_name)
        except ImportError:
            missing.append(pkg_spec)
    return missing


def self_heal_dependencies(missing_packages: List[str]) -> Tuple[bool, str]:
    """Attempt pip install for missing packages in the current Python executable environment."""
    if not missing_packages:
        return True, "All dependencies present"

    log_startup(f"Missing dependencies detected: {missing_packages}. Starting self-healing...")
    try:
        cmd = [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--no-warn-script-location",
        ] + missing_packages

        res = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=90,
        )
        if res.returncode == 0:
            log_startup("Self-healing successful. Re-verifying package imports...")
            still_missing = check_missing_dependencies()
            if not still_missing:
                log_startup("All packages verified after self-healing.")
                return True, "Self-healing completed successfully"
            else:
                err = f"Packages still missing after install: {still_missing}"
                log_startup(err)
                return False, err
        else:
            err = f"pip install exited with code {res.returncode}: {res.stderr.strip()}"
            log_startup(err)
            return False, err
    except Exception as exc:
        err = f"Self-healing exception: {type(exc).__name__}: {exc}"
        log_startup(err)
        return False, err


def bootstrap_and_launch() -> None:
    """Bootstrap entry point: log startup, verify dependencies, and launch Hermes Hub Web."""
    log_startup("=== Hermes Hub Launcher Bootstrap initiated ===")
    log_startup(f"Python: {sys.executable} (version {sys.version.split()[0]})")
    log_startup(f"Working Directory: {os.getcwd()}")

    # 1. Dependency verification & self-healing
    missing = check_missing_dependencies()
    if missing:
        log_startup(f"Pre-flight dependency check: missing {missing}")
        ok, detail = self_heal_dependencies(missing)
        if not ok:
            log_path = get_startup_log_path()
            show_native_error(
                "Hermes Hub — Ошибка компонентов",
                "Не удалось автоматически установить необходимые компоненты веб-интерфейса (fastapi / uvicorn / psutil / pyyaml).\n\n"
                f"Детали ошибки: {detail}\n\n"
                f"Лог запуска: {log_path}\n\n"
                "Вы можете установить их вручную командой:\n"
                f"{sys.executable} -m pip install fastapi uvicorn psutil pyyaml",
            )
            sys.exit(1)

    # 2. Launch Web GUI with full exception capture
    try:
        log_startup("Importing web.server module...")
        from antigravity_provider.router.web.server import run_web_server

        log_startup("Executing run_web_server()...")
        run_web_server(open_browser=True)
        log_startup("Hermes Hub Web closed normally.")
    except Exception as exc:
        tb = traceback.format_exc()
        log_startup(f"FATAL EXCEPTION during launch:\n{tb}")
        log_path = get_startup_log_path()
        show_native_error(
            "Hermes Hub — Критическая ошибка при запуске",
            f"Произошла ошибка при запуске интерфейса Hermes Hub:\n\n{exc}\n\n"
            f"Полный текст ошибки записан в лог:\n{log_path}",
        )
        sys.exit(1)


if __name__ == "__main__":
    bootstrap_and_launch()
