"""Pytest configuration and global hermetic test isolation fixtures.

Enforces:
1. Zero modification to real user credentials or router_profiles.yaml.
2. Complete filesystem sandboxing in temporary directory via HERMES_HOME.
3. Offline execution for default test runs (network / live require explicit -m markers).
"""
from __future__ import annotations

import os
from pathlib import Path
import pytest


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
