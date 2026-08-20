"""Hermes Hub — Central Hub Settings Service.

Provides unified reading, saving, and querying of runtime settings from hub_settings.json.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from antigravity_provider.paths import get_hermes_home

DEFAULT_SETTINGS: Dict[str, Any] = {
    "session_affinity": True,
    "auto_failover": True,
    "failover_attempts": 3,
    "auto_return_primary": True,
    "auto_monitoring": True,
    "auto_update": True,
    "release_channel": "stable",
    "model_timeout_seconds": 60,
    "monitoring_interval_seconds": 30,
}


def get_settings_file() -> Path:
    """Return the absolute path to hub_settings.json in HERMES_HOME."""
    return get_hermes_home() / "hub_settings.json"


def get_hub_settings() -> Dict[str, Any]:
    """Load settings from hub_settings.json merged with standard defaults."""
    sfile = get_settings_file()
    merged = dict(DEFAULT_SETTINGS)
    if sfile.exists():
        try:
            data = json.loads(sfile.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                merged.update(data)
        except Exception:
            pass

    # Normalize numeric types
    try:
        merged["failover_attempts"] = int(merged.get("failover_attempts", 3))
    except (ValueError, TypeError):
        merged["failover_attempts"] = 3

    try:
        merged["model_timeout_seconds"] = int(merged.get("model_timeout_seconds", 60))
    except (ValueError, TypeError):
        merged["model_timeout_seconds"] = 60

    try:
        merged["monitoring_interval_seconds"] = int(merged.get("monitoring_interval_seconds", 30))
    except (ValueError, TypeError):
        merged["monitoring_interval_seconds"] = 30

    return merged


def save_hub_settings(settings: Dict[str, Any]) -> None:
    """Persist settings dictionary into hub_settings.json."""
    sfile = get_settings_file()
    sfile.parent.mkdir(parents=True, exist_ok=True)
    sfile.write_text(json.dumps(settings, indent=2, ensure_ascii=False), encoding="utf-8")
