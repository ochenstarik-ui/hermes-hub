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
    """Skip tests explicitly marked as needing the Tk graphical stack.

    Selection is by the ``ui`` marker only. It used to also match any test whose
    *name* contained "ui", "view" or "wizard", which silently skipped static
    checks that never touch the toolkit — and hid real failures for weeks.
    Modules that import the GUI stack guard themselves with
    ``pytest.importorskip("customtkinter")`` at module scope; that guard is
    enforced by tests/test_import_invariants.py.
    """
    try:
        import customtkinter  # noqa: F401
    except Exception:
        skip_ui = pytest.mark.skip(reason="customtkinter is not installed in current environment")
        for item in items:
            if "ui" in item.keywords:
                item.add_marker(skip_ui)

@pytest.fixture(scope="session")
def tk_root():
    """Shared Tkinter root for all UI tests to avoid Tcl resource exhaustion."""
    try:
        import customtkinter as ctk
        root = ctk.CTk()
        root.withdraw()
        yield root
        root.destroy()
    except Exception as e:
        pytest.skip(f"Tkinter could not be initialized: {e}")
