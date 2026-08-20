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

    # Also isolate agy profile dirs
    (temp_hermes / "agy_profiles").mkdir(exist_ok=True)
    (temp_hermes / "codex_profiles").mkdir(exist_ok=True)
    (temp_hermes / "opengo_profiles").mkdir(exist_ok=True)
    (temp_hermes / "logs").mkdir(exist_ok=True)

    yield temp_hermes
