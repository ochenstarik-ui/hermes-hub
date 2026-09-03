"""Tests for Hermes Hub Installer (HermesHubSetup.exe) and pre-flight logic."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
import pytest

from antigravity_provider.version import __version__
from antigravity_provider import paths

REPO_ROOT = paths.get_repo_root()
SETUP_EXE = REPO_ROOT / "dist" / "HermesHubSetup.exe"
COMPATIBILITY_JSON = REPO_ROOT / "config" / "compatibility.json"


@pytest.mark.unit
def test_compatibility_json():
    """Verify compatibility manifest structure and fields."""
    assert COMPATIBILITY_JSON.is_file()
    data = json.loads(COMPATIBILITY_JSON.read_text(encoding="utf-8"))
    assert data["hub_version"] == __version__
    assert "0.20.4" in data["tested_versions"]
    assert "min_hermes_version" in data


@pytest.mark.installer
def test_setup_exe_exists():
    """Verify that HermesHubSetup.exe is built and present."""
    if not SETUP_EXE.is_file():
        pytest.skip("HermesHubSetup.exe not built yet")
    assert SETUP_EXE.stat().st_size > 0


@pytest.mark.installer
def test_silent_installer_execution_with_hermes(tmp_path):
    """Run HermesHubSetup.exe /silent on system where Hermes is installed (Expect 0)."""
    if not SETUP_EXE.is_file():
        pytest.skip("HermesHubSetup.exe not built yet")

    # Set up mock Hermes Agent structure in temp home pointing to the active venv
    agent_dir = tmp_path / "hermes" / "hermes-agent"
    agent_dir.mkdir(parents=True, exist_ok=True)
    real_venv = Path(sys.prefix)
    target_venv = agent_dir / "venv"
    try:
        import _winapi
        _winapi.CreateJunction(str(real_venv), str(target_venv))
    except Exception:
        try:
            os.symlink(str(real_venv), str(target_venv), target_is_directory=True)
        except Exception:
            venv_scripts = target_venv / "Scripts"
            venv_scripts.mkdir(parents=True, exist_ok=True)
            (venv_scripts / "python.exe").touch()
            (venv_scripts / "hermes.exe").touch()

    env = dict(os.environ)
    env["HERMES_HOME"] = str(tmp_path / "hermes")
    env["LOCALAPPDATA"] = str(tmp_path / "localappdata")
    env["APPDATA"] = str(tmp_path / "appdata")
    env["USERPROFILE"] = str(tmp_path / "user")
    env["HERMES_HUB_NO_REGISTRY"] = "1"

    res = subprocess.run([str(SETUP_EXE), "/silent"], env=env, capture_output=True, text=True)
    assert res.returncode == 0, f"Expected returncode 0, got {res.returncode}. Stderr: {res.stderr}. Stdout: {res.stdout}"


@pytest.mark.installer
def test_silent_installer_fails_without_hermes(tmp_path):
    """Run HermesHubSetup.exe /silent when HERMES_HOME points to empty dir."""
    if not SETUP_EXE.is_file():
        pytest.skip("HermesHubSetup.exe not built yet")

    fake_home = tmp_path / "non_existent_hermes"
    env = dict(os.environ)
    env["HERMES_HOME"] = str(fake_home)
    env["LOCALAPPDATA"] = str(tmp_path / "localappdata")
    env["APPDATA"] = str(tmp_path / "appdata")
    env["USERPROFILE"] = str(tmp_path / "user")

    res = subprocess.run([str(SETUP_EXE), "/silent"], env=env, capture_output=True, text=True)
    assert res.returncode != 0, f"Expected failure for missing Hermes, got {res.returncode}"


# ── Установка на Linux: sudo и защищённый системный Python ──
#
# Установка на сервере владельца упала так: запуск через sudo увёл всё в
# /root/.hermes, венв Hermes там не нашёлся, установщик взял /usr/bin/python3,
# а он в Ubuntu 24.04 помечен EXTERNALLY-MANAGED и отклоняет pip. Проверка
# после установки честно упала на «No module named 'fastapi'».

def _linux_installer_text() -> str:
    root = Path(__file__).resolve().parent.parent
    return (root / "installer" / "install-linux.sh").read_text(encoding="utf-8")


def test_linux_installer_refuses_sudo():
    text = _linux_installer_text()
    assert "SUDO_USER" in text, "запуск через sudo обязан распознаваться"
    assert "HERMES_ALLOW_ROOT" in text, "должен быть осознанный способ обойти отказ"
    assert "exit 3" in text


def test_linux_installer_creates_own_venv_when_system_python_is_managed():
    text = _linux_installer_text()
    assert "EXTERNALLY-MANAGED" in text, "PEP 668 должен распознаваться"
    assert "-m venv" in text, "ответ на PEP 668 — собственное окружение"
    # --break-system-packages ломает питон всей машины: имя флага не
    # преувеличивает. Упоминание в пояснении допустимо, применение — нет,
    # поэтому смотрим только на исполняемые строки.
    code_lines = [
        line for line in text.splitlines() if not line.lstrip().startswith("#")
    ]
    assert not any("--break-system-packages" in line for line in code_lines)


def test_linux_installer_fails_loudly_on_missing_deps():
    """Раньше pip падал, а установка продолжалась — до отказа на проверке."""
    text = _linux_installer_text()
    assert "exit 12" in text and "exit 13" in text
    assert "|| true" not in text.split("Installing required packages")[1][:400]


def test_linux_launcher_knows_about_installer_venv():
    root = Path(__file__).resolve().parent.parent
    launcher = (root / "launcher" / "hermes-hub-web.sh").read_text(encoding="utf-8")
    assert '$HERMES_HOME/venv/bin/python3' in launcher, (
        "иначе запуск уйдёт на системный python, где зависимостей нет"
    )
