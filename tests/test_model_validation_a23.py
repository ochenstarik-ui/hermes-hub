"""Tests for model validation, suffix matching, and model discovery refresh."""
from __future__ import annotations

import json
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from antigravity_provider.router.action_handler import ActionExecutor, do_set_model
from antigravity_provider.router.model_discovery_service import ModelDiscoveryService
from antigravity_provider.router.router_config import (
    RolePolicy,
    RouterConfig,
    RouterProfileConfig,
    save_router_config,
)


@pytest.fixture
def isolated_hub(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))

    # Reset ModelDiscoveryService singleton
    ModelDiscoveryService._instance = None

    # Setup a router configuration
    cfg = RouterConfig(
        profiles={
            "ag-orch-1": RouterProfileConfig(
                profile_id="ag-orch-1",
                provider="antigravity",
                enabled=True,
                preferred_models=["google-antigravity/gemini-2.5-pro"],
            ),
            "codex-1": RouterProfileConfig(
                profile_id="codex-1",
                provider="openai-codex",
                enabled=True,
                preferred_models=["gpt-4o"],
            ),
        },
        roles={
            "manager": RolePolicy(
                role_name="manager",
                preferred_chain=["ag-orch-1"],
            ),
        },
        default_role="manager",
    )
    save_router_config(cfg)
    return tmp_path


def test_nonexistent_model_rejected_with_populated_cache(isolated_hub):
    """Тест 1: Несуществующая модель отклоняется при наполненном кэше."""
    service = ModelDiscoveryService.get()
    with service._cache_lock:
        service._cache["antigravity"] = {
            "models": ["gemini-2.5-pro", "gemini-2.5-flash", "gemini-3.7-flash-high"],
            "discovered_at": 1000.0,
        }

    ok, msg = do_set_model("ag-orch-1", "completely-fake-model-xyz")
    assert ok is False
    assert "отсутствует в списке обнаруженных моделей провайдера 'antigravity'" in msg


def test_unknown_model_rejected_with_empty_cache(isolated_hub):
    """Тест 2: При пустом кэше неизвестная модель отклоняется с внятной ошибкой."""
    service = ModelDiscoveryService.get()
    with service._cache_lock:
        service._cache.clear()

    with patch.object(service, "discover_models_sync", return_value=None):
        ok, msg = do_set_model("ag-orch-1", "unknown-unregistered-model")
        assert ok is False
        assert msg == "Кэш моделей для провайдера 'antigravity' пуст, а модель 'unknown-unregistered-model' не найдена в списке известных моделей."


def test_base_name_without_effort_suffix_accepted(isolated_hub):
    """Тест 3: Базовое имя без суффикса усилия (например gemini-3.7-flash) принимается, если в кэше есть gemini-3.7-flash-high."""
    service = ModelDiscoveryService.get()
    with service._cache_lock:
        service._cache["antigravity"] = {
            "models": ["gemini-3.7-flash-high", "gemini-3.7-flash-medium"],
            "discovered_at": 1000.0,
        }

    ok, msg = do_set_model("ag-orch-1", "gemini-3.7-flash")
    assert ok is True
    assert "успешно сохранена" in msg


def test_canonical_model_accepted_even_with_empty_cache(isolated_hub):
    """Каноническая модель из ModelRegistry принимается даже при пустом кэше discovery."""
    service = ModelDiscoveryService.get()
    with service._cache_lock:
        service._cache.clear()

    with patch.object(service, "discover_models_sync", return_value=None):
        ok, msg = do_set_model("ag-orch-1", "gemini-2.5-pro")
        assert ok is True
        assert "успешно сохранена" in msg


def test_action_executor_refresh_models(isolated_hub):
    """ActionExecutor.execute handles 'refresh_models' action."""
    service = ModelDiscoveryService.get()
    with patch.object(service, "discover_models_sync", return_value=["test-model-1"]):
        res = ActionExecutor.execute("refresh_models", {"provider": "antigravity"})
        assert res.get("ok") is True
        assert res.get("data") == ["test-model-1"]

    with patch.object(service, "refresh_all_async") as mock_refresh_all:
        res = ActionExecutor.execute("refresh_models", {})
        assert res.get("ok") is True
        mock_refresh_all.assert_called_once()


def test_model_discovery_cache_retained_on_timeout_and_error(isolated_hub):
    """Cache is not overwritten or cleared when model discovery probe times out or raises error."""
    service = ModelDiscoveryService.get()
    with service._cache_lock:
        service._cache["antigravity"] = {
            "models": ["existing-gemini-model"],
            "discovered_at": 1000.0,
        }

    # Simulate error in _probe_provider
    with patch.object(service, "_probe_provider", side_effect=RuntimeError("Network failure")):
        res = service.discover_models_sync("antigravity", timeout=1.0)
        assert res == ["existing-gemini-model"]
        assert service.get_models("antigravity") == ["existing-gemini-model"]



