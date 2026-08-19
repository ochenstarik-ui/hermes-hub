"""Tests for Hermes Hub Installer (HermesHubSetup.exe) and pre-flight logic."""
import subprocess
from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SETUP_EXE = REPO_ROOT / "dist" / "HermesHubSetup.exe"
COMPATIBILITY_JSON = REPO_ROOT / "config" / "compatibility.json"


def test_setup_exe_exists():
    """Verify that HermesHubSetup.exe is built and present."""
    assert SETUP_EXE.is_file(), f"HermesHubSetup.exe not found at {SETUP_EXE}"
    assert SETUP_EXE.stat().st_size > 0


def test_compatibility_json():
    """Verify compatibility manifest structure and fields."""
    import json
    assert COMPATIBILITY_JSON.is_file()
    data = json.loads(COMPATIBILITY_JSON.read_text(encoding="utf-8"))
    assert data["hub_version"] == "0.1.0"
    assert "0.20.4" in data["tested_versions"]
    assert "min_hermes_version" in data


def test_silent_installer_execution_with_hermes():
    """Run HermesHubSetup.exe /silent on live system where Hermes is installed (Expect 0)."""
    if not SETUP_EXE.is_file():
        pytest.skip("HermesHubSetup.exe not built")

    res = subprocess.run([str(SETUP_EXE), "/silent"], capture_output=True, text=True)
    assert res.returncode == 0, f"Expected returncode 0, got {res.returncode}. Stderr: {res.stderr}"


def test_silent_installer_fails_without_hermes(tmp_path, monkeypatch):
    """Run HermesHubSetup.exe /silent when HERMES_HOME points to empty dir (Expect code 10)."""
    if not SETUP_EXE.is_file():
        pytest.skip("HermesHubSetup.exe not built")

    fake_home = tmp_path / "non_existent_hermes"
    env = dict(subprocess.os.environ)
    env["HERMES_HOME"] = str(fake_home)
    env["LOCALAPPDATA"] = str(tmp_path)

    res = subprocess.run([str(SETUP_EXE), "/silent"], env=env, capture_output=True, text=True)
    assert res.returncode == 10, f"Expected returncode 10 for missing Hermes, got {res.returncode}"
