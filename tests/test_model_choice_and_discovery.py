"""
Hermes Hub — Model Choice & Discovery Persistence Tests.
Verifies P0-1 and P0-2 requirements of Task A18.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
import pytest

from antigravity_provider.router.action_handler import ActionExecutor, do_set_model
from antigravity_provider.router.model_discovery_service import ModelDiscoveryService
from antigravity_provider.router.router_config import load_router_config, save_router_config


@pytest.fixture
def temp_models_cache(tmp_path, monkeypatch):
    """Provide isolated models_cache.json."""
    cache_file = tmp_path / "models_cache.json"
    cache_file.write_text(
        json.dumps({
            "antigravity": {
                "models": [
                    "gemini-3.7-flash-high",
                    "gemini-3.5-flash-high",
                    "gemini-3.1-pro-high",
                    "claude-sonnet-4-6",
                ],
                "discovered_at": time.time(),
            },
            "opencode-go": {
                "models": ["deepseek-r1", "deepseek-v4-pro", "qwen3.8-max"],
                "discovered_at": time.time(),
            },
        }, ensure_ascii=False),
        encoding="utf-8"
    )
    svc = ModelDiscoveryService(cache_path=cache_file)
    monkeypatch.setattr(ModelDiscoveryService, "get", classmethod(lambda cls: svc))
    return svc, cache_file


def test_set_model_success_and_config_persistence(temp_models_cache):
    """Verify setting valid discovered model succeeds and persists in router_config."""
    svc, _ = temp_models_cache
    config = load_router_config()
    profile_id = "ag-w1"
    assert profile_id in config.profiles

    # Pick valid discovered model
    target_model = "gemini-3.1-pro-high"
    res = ActionExecutor.execute("set_model", {
        "profile_id": profile_id,
        "model": target_model,
        "role_id": "developer-1",
    })

    assert res["ok"] is True
    assert "успешно" in res["message"]

    # Verify persistence on disk
    reloaded = load_router_config()
    assert reloaded.profiles[profile_id].preferred_models[0] == target_model
    assert reloaded.roles["developer-1"].default_model == target_model


def test_set_model_rejects_nonexistent_model(temp_models_cache):
    """Verify nonexistent model is strictly rejected without modifying configuration."""
    svc, _ = temp_models_cache
    config = load_router_config()
    profile_id = "ag-w1"
    orig_models = list(config.profiles[profile_id].preferred_models)

    # Attempt to set invalid/hallucinated model
    res = ActionExecutor.execute("set_model", {
        "profile_id": profile_id,
        "model": "gemini-nonexistent-model-99",
    })

    assert res["ok"] is False
    assert "отсутствует в списке" in res["message"] or "не поддерживается" in res["message"]

    # Verify config was not corrupted
    reloaded = load_router_config()
    assert reloaded.profiles[profile_id].preferred_models == orig_models


def test_models_cache_disk_persistence_and_reload(tmp_path):
    """Verify models cache survives service recreation and disk reload."""
    cache_file = tmp_path / "models_cache.json"
    cache_file.write_text(
        json.dumps({
            "claude": {
                "models": ["claude-3-7-sonnet", "claude-sonnet-4-6"],
                "discovered_at": time.time(),
            }
        }, ensure_ascii=False),
        encoding="utf-8"
    )

    svc1 = ModelDiscoveryService(cache_path=cache_file)
    assert svc1.get_models("claude") == ["claude-3-7-sonnet", "claude-sonnet-4-6"]

    # Simulate new process/service instance
    svc2 = ModelDiscoveryService(cache_path=cache_file)
    assert svc2.get_models("claude") == ["claude-3-7-sonnet", "claude-sonnet-4-6"]


def test_models_discovery_timeout_retains_existing_cache(tmp_path, monkeypatch):
    """Verify that timeout/probe failure does not erase previously cached models."""
    cache_file = tmp_path / "models_cache.json"
    cache_file.write_text(
        json.dumps({
            "grok": {
                "models": ["grok-2-latest", "grok-beta"],
                "discovered_at": time.time(),
            }
        }, ensure_ascii=False),
        encoding="utf-8"
    )

    svc = ModelDiscoveryService(cache_path=cache_file)

    # Mock _probe_provider to simulate a hang/timeout
    def mock_hang_probe(provider):
        time.sleep(2.0)
        return ["invented-model"]

    monkeypatch.setattr(svc, "_probe_provider", mock_hang_probe)

    # Synchronous probe with 0.1s timeout
    result = svc.discover_models_sync("grok", timeout=0.1)

    # Result should retain existing cached models
    assert result == ["grok-2-latest", "grok-beta"]
    assert svc.get_models("grok") == ["grok-2-latest", "grok-beta"]
