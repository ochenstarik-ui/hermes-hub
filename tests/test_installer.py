"""Tests for Hermes Hub Installer (HermesHubSetup.exe) and pre-flight logic."""
from __future__ import annotations

import json
import os
import subprocess
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

    # Set up mock Hermes Agent structure in temp home
    agent_dir = tmp_path / "hermes" / "hermes-agent"
    venv_scripts = agent_dir / "venv" / "Scripts"
    venv_scripts.mkdir(parents=True, exist_ok=True)
    (venv_scripts / "python.exe").touch()
    (venv_scripts / "hermes.exe").touch()

    env = dict(os.environ)
    env["HERMES_HOME"] = str(tmp_path / "hermes")
    env["LOCALAPPDATA"] = str(tmp_path)

    res = subprocess.run([str(SETUP_EXE), "/silent"], env=env, capture_output=True, text=True)
    assert res.returncode == 0, f"Expected returncode 0, got {res.returncode}. Stderr: {res.stderr}"


@pytest.mark.installer
def test_silent_installer_fails_without_hermes(tmp_path):
    """Run HermesHubSetup.exe /silent when HERMES_HOME points to empty dir."""
    if not SETUP_EXE.is_file():
        pytest.skip("HermesHubSetup.exe not built yet")

    fake_home = tmp_path / "non_existent_hermes"
    env = dict(os.environ)
    env["HERMES_HOME"] = str(fake_home)
    env["LOCALAPPDATA"] = str(tmp_path)

    res = subprocess.run([str(SETUP_EXE), "/silent"], env=env, capture_output=True, text=True)
    assert res.returncode != 0, f"Expected failure for missing Hermes, got {res.returncode}"
