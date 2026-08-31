"""Hermes Hub — Central Hub Settings Service.

Provides unified reading, saving, and querying of runtime settings from hub_settings.json.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

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
    "quota_threshold_percent": 10.0,
    "quota_threshold_action": "notify",
    "email_masking_mode": "none",
    "default_role": "manager",
}



_SETTINGS_CACHE: Dict[str, Any] | None = None
_SETTINGS_CACHE_MTIME: float = -1.0
_SETTINGS_CACHE_PATH: str = ""


def invalidate_settings_cache() -> None:
    """Clear in-memory settings cache."""
    global _SETTINGS_CACHE, _SETTINGS_CACHE_MTIME, _SETTINGS_CACHE_PATH
    _SETTINGS_CACHE = None
    _SETTINGS_CACHE_MTIME = -1.0
    _SETTINGS_CACHE_PATH = ""


def get_settings_file() -> Path:
    """Return the absolute path to hub_settings.json in HERMES_HOME."""
    return get_hermes_home() / "hub_settings.json"


def get_hub_settings() -> Dict[str, Any]:
    """Load settings from hub_settings.json merged with standard defaults, cached by mtime."""
    global _SETTINGS_CACHE, _SETTINGS_CACHE_MTIME, _SETTINGS_CACHE_PATH
    sfile = get_settings_file()
    sfile_str = str(sfile)

    current_mtime = -1.0
    if sfile.exists():
        try:
            current_mtime = sfile.stat().st_mtime
        except Exception:
            current_mtime = -1.0

    if (
        _SETTINGS_CACHE is not None
        and _SETTINGS_CACHE_PATH == sfile_str
        and _SETTINGS_CACHE_MTIME == current_mtime
    ):
        return dict(_SETTINGS_CACHE)

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

    try:
        merged["quota_threshold_percent"] = float(merged.get("quota_threshold_percent", 10.0))
    except (ValueError, TypeError):
        merged["quota_threshold_percent"] = 10.0

    action = str(merged.get("quota_threshold_action", "notify")).strip().lower()
    if action not in ("notify", "switch"):
        action = "notify"
    merged["quota_threshold_action"] = action

    email_mode = str(merged.get("email_masking_mode", "none")).strip().lower()
    if email_mode not in ("none", "partial", "full"):
        email_mode = "none"
    merged["email_masking_mode"] = email_mode

    default_role = str(merged.get("default_role", "manager")).strip().lower()
    merged["default_role"] = default_role or "manager"

    _SETTINGS_CACHE = dict(merged)
    _SETTINGS_CACHE_MTIME = current_mtime
    _SETTINGS_CACHE_PATH = sfile_str

    return dict(merged)


def save_hub_settings(settings: Dict[str, Any]) -> bool:
    """Persist settings dictionary into hub_settings.json."""
    try:
        sfile = get_settings_file()
        sfile.parent.mkdir(parents=True, exist_ok=True)
        current = get_hub_settings()
        current.update(settings)
        sfile.write_text(json.dumps(current, indent=2, ensure_ascii=False), encoding="utf-8")
        invalidate_settings_cache()
        return True
    except Exception:
        return False


def get_hermes_config_status(config_path: Optional[Path] = None) -> Dict[str, Any]:
    """Read Hermes configuration (~/.hermes/config.yaml) in read-only mode to provide status feedback."""
    import yaml
    if config_path is None:
        config_path = get_hermes_home() / "config.yaml"

    if not config_path.exists():
        return {
            "exists": False,
            "model": None,
            "provider": None,
            "base_url": None,
            "path": str(config_path),
            "message": "Конфигурационный файл ~/.hermes/config.yaml не найден",
        }

    try:
        raw_text = config_path.read_text(encoding="utf-8")
        data = yaml.safe_load(raw_text)
        if not isinstance(data, dict):
            return {
                "exists": True,
                "model": None,
                "provider": None,
                "base_url": None,
                "path": str(config_path),
                "message": "Конфигурационный файл пуст или некорректен",
            }

        model_cfg = data.get("model", {})
        if not isinstance(model_cfg, dict):
            model_cfg = {}

        default_model = model_cfg.get("default") or data.get("default_model") or data.get("model")
        provider = model_cfg.get("provider") or data.get("provider")
        base_url = model_cfg.get("base_url") or data.get("base_url")

        return {
            "exists": True,
            "model": default_model,
            "provider": provider,
            "base_url": base_url,
            "path": str(config_path),
        }
    except Exception as e:
        return {
            "exists": True,
            "model": None,
            "provider": None,
            "base_url": None,
            "path": str(config_path),
            "error": str(e),
        }

