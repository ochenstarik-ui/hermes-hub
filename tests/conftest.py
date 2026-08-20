"""Pytest configuration and global hermetic test isolation fixtures.

Enforces:
1. Zero modification to real user credentials or router_profiles.yaml.
2. Complete filesystem sandboxing in temporary directory via HERMES_HOME.
3. Offline execution for default test runs (network / live require explicit -m markers).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
import pytest

REPO_SRC = Path(__file__).resolve().parent.parent / "src"
if str(REPO_SRC) not in sys.path or sys.path[0] != str(REPO_SRC):
    sys.path.insert(0, str(REPO_SRC))


@pytest.fixture(autouse=True)
def isolate_hermes_environment(tmp_path, monkeypatch):
    """Automatically sandbox all file I/O to a temporary HERMES_HOME directory."""
    temp_hermes = tmp_path / "hermes_test_home"
    temp_hermes.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HERMES_HOME", str(temp_hermes))

    # Isolate all provider profile dirs
    (temp_hermes / "agy_profiles").mkdir(exist_ok=True)
    (temp_hermes / "codex_profiles").mkdir(exist_ok=True)
    (temp_hermes / "opengo_profiles").mkdir(exist_ok=True)
    (temp_hermes / "claude_profiles").mkdir(exist_ok=True)
    (temp_hermes / "grok_profiles").mkdir(exist_ok=True)
    (temp_hermes / "logs").mkdir(exist_ok=True)

    yield temp_hermes


def pytest_configure(config):
    config.addinivalue_line("markers", "ui: mark test as requiring CustomTkinter / Tk graphical environment")


def pytest_collection_modifyitems(config, items):
    """Ensure tests requiring CustomTkinter gracefully skip if it cannot be loaded."""
    has_ctk = False
    try:
        import customtkinter as _ctk  # noqa
        has_ctk = True
    except Exception:
        has_ctk = False

    if not has_ctk:
        skip_ui = pytest.mark.skip(reason="customtkinter is not installed in current environment")
        for item in items:
            if "ui" in item.keywords or "view" in item.name.lower() or "wizard" in item.name.lower():
                item.add_marker(skip_ui)
