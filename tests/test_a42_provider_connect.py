"""Tests for A42: Real provider connection, model discovery, quota and health fixes."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from antigravity_provider.router.action_handler import ActionExecutor
from antigravity_provider.router.adapters import get_adapter
from antigravity_provider.router.adapters.base_adapter import ErrorCategory
from antigravity_provider.router.adapters.codex_adapter import CodexAdapter
from antigravity_provider.router.auto_assigner import AutoAssigner
from antigravity_provider.router.health_tracker import (
    HEALTHY,
    QUOTA_EXHAUSTED,
    RATE_LIMITED,
    COOLDOWN,
    HealthTracker,
)
from antigravity_provider.router.model_discovery_service import ModelDiscoveryService
from antigravity_provider.router.profile_manager import ProfileAuthManager
from antigravity_provider.router.router_config import (
    RouterConfig,
    RouterProfileConfig,
    load_router_config,
    save_router_config,
)
from antigravity_provider.router.unified_health import (
    STATUS_COOLDOWN,
    STATUS_HEALTHY,
    STATUS_QUOTA_EXHAUSTED,
    STATUS_RATE_LIMITED,
    STATUS_UNHEALTHY,
    UnifiedHealthService,
)


@pytest.fixture(autouse=True)
def setup_test_environment(tmp_path, monkeypatch):
    """Isolate Hermes home and configuration for all tests."""
    hermes_home = tmp_path / ".hermes"
    hermes_home.mkdir(parents=True, exist_ok=True)
    profiles_dir = hermes_home / "profiles"
    profiles_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))

    # Initialize empty config
    cfg = RouterConfig()
    save_router_config(cfg)

    yield hermes_home


# ═════════════════════════════════════════════════════════════════════════════
# P0-1: Real connection of OpenRouter, NVIDIA, Ollama, Claude, Local
# ═════════════════════════════════════════════════════════════════════════════

@pytest.mark.unit
def test_p0_1_auto_assigner_provider_slots_and_capabilities():
    """Verify openrouter, nvidia, nvidia-nim are present in provider_slots and capabilities_map."""
    slot_or = AutoAssigner.find_free_slot("openrouter")
    assert slot_or in ("openrouter-1", "openrouter-2")

    slot_nv = AutoAssigner.find_free_slot("nvidia")
    assert slot_nv in ("nvidia-1", "nvidia-2")

    slot_nim = AutoAssigner.find_free_slot("nvidia-nim")
    # nvidia и nvidia-nim — псевдонимы одного провайдера с одним адаптером,
    # поэтому слоты у них общие: разводить параллельные наборы профилей
    # для одного провайдера означало бы вернуть мышление слотами (A41).
    assert slot_nim in ("nvidia-1", "nvidia-2", "nvidia-nim-1", "nvidia-nim-2")

    # Capabilities definition
    ok, _ = AutoAssigner.ensure_profile_definition("openrouter", "openrouter-1")
    assert ok is True
    cfg = load_router_config()
    pcfg = cfg.get_profile("openrouter-1")
    assert pcfg is not None
    assert "coding" in pcfg.capabilities

    ok2, _ = AutoAssigner.ensure_profile_definition("nvidia", "nvidia-1")
    assert ok2 is True
    cfg2 = load_router_config()
    pcfg2 = cfg2.get_profile("nvidia-1")
    assert pcfg2 is not None
    assert "reasoning" in pcfg2.capabilities


@pytest.mark.unit
def test_p0_1_add_account_openrouter_default_base_url():
    """Verify add_account for openrouter substitutes default base_url and saves auth."""
    res = ActionExecutor.execute(
        "add_account",
        {
            "provider": "openrouter",
            "token": "sk-or-v1-test-key-12345",
            "base_url": "",  # Empty base url
            "target_role": "developer-1",
        },
    )
    assert res["ok"] is True
    assert "успешно подключен" in res["message"]

    # Verify profile created and auth saved
    auth = ProfileAuthManager.load_profile_auth("openrouter", "openrouter-1")
    assert auth is not None
    assert auth["api_key"] == "sk-or-v1-test-key-12345"
    assert auth["base_url"] == "https://openrouter.ai/api/v1"

    status = ProfileAuthManager.get_profile_status("openrouter", "openrouter-1")
    assert status["authenticated"] is True
    assert "sk-or-" in status["account_id_masked"]


@pytest.mark.unit
def test_p0_1_add_account_nvidia_default_base_url():
    """Verify add_account for nvidia substitutes default base_url and saves auth."""
    res = ActionExecutor.execute(
        "add_account",
        {
            "provider": "nvidia",
            "token": "nvapi-test-key-abcde",
            "base_url": "",
            "target_role": "developer-1",
        },
    )
    assert res["ok"] is True
    assert "успешно подключен" in res["message"]

    auth = ProfileAuthManager.load_profile_auth("nvidia", "nvidia-1")
    assert auth is not None
    assert auth["api_key"] == "nvapi-test-key-abcde"
    assert auth["base_url"] == "https://integrate.api.nvidia.com/v1"

    status = ProfileAuthManager.get_profile_status("nvidia", "nvidia-1")
    assert status["authenticated"] is True


@pytest.mark.unit
def test_p0_1_add_account_ollama_default_base_url():
    """Verify add_account for ollama substitutes default base_url http://127.0.0.1:11434."""
    res = ActionExecutor.execute(
        "add_account",
        {
            "provider": "ollama",
            "base_url": "",  # left empty
            "target_role": "developer-1",
        },
    )
    assert res["ok"] is True
    auth = ProfileAuthManager.load_profile_auth("ollama", "ollama-1")
    assert auth is not None
    assert auth["base_url"] == "http://127.0.0.1:11434"


@pytest.mark.unit
def test_p0_1_add_account_local_default_base_url():
    """Verify add_account for local substitutes default base_url http://127.0.0.1:8081/v1."""
    res = ActionExecutor.execute(
        "add_account",
        {
            "provider": "local",
            "base_url": "",
            "target_role": "developer-1",
        },
    )
    assert res["ok"] is True
    auth = ProfileAuthManager.load_profile_auth("local", "local-1")
    assert auth is not None
    assert auth["base_url"] == "http://127.0.0.1:8081/v1"


@pytest.mark.unit
def test_p0_1_add_account_claude_and_opencode():
    """Verify add_account for claude and opencode-go with API keys."""
    res_claude = ActionExecutor.execute(
        "add_account",
        {
            "provider": "claude",
            "token": "sk-ant-api03-test-1234567890",
            "target_role": "developer-1",
        },
    )
    assert res_claude["ok"] is True

    res_opencode = ActionExecutor.execute(
        "add_account",
        {
            "provider": "opencode-go",
            "token": "opencode-test-key-12345",
            "target_role": "developer-1",
        },
    )
    assert res_opencode["ok"] is True


@pytest.mark.unit
def test_p0_1_add_account_honest_rejections():
    """Verify add_account returns honest errors and NEVER fake {'ok': True, 'message': 'Навигация'}."""
    # Missing API key for openrouter
    res_or = ActionExecutor.execute("add_account", {"provider": "openrouter", "token": ""})
    assert res_or["ok"] is False
    assert "API-ключ" in res_or["message"]

    # Missing API key for nvidia
    res_nv = ActionExecutor.execute("add_account", {"provider": "nvidia", "token": ""})
    assert res_nv["ok"] is False
    assert "API-ключ" in res_nv["message"]

    # Missing API key for claude
    res_cl = ActionExecutor.execute("add_account", {"provider": "claude", "token": ""})
    assert res_cl["ok"] is False
    assert "API-ключ" in res_cl["message"]

    # Unsupported provider
    res_unsupp = ActionExecutor.execute("add_account", {"provider": "unknown_provider_xyz"})
    assert res_unsupp["ok"] is False
    assert "не поддерживается" in res_unsupp["message"]
    assert res_unsupp.get("message") != "Навигация"


# ═════════════════════════════════════════════════════════════════════════════
# P0-2: Model Discovery for OpenRouter, NVIDIA, Ollama + Error Preservation
# ═════════════════════════════════════════════════════════════════════════════

@pytest.mark.unit
def test_p0_2_openrouter_discovery_headers(tmp_path):
    """Verify OpenRouter model discovery queries {base_url}/models with required headers."""
    cache_file = tmp_path / "models_cache.json"
    service = ModelDiscoveryService(cache_path=cache_file)

    # Save auth for openrouter profile
    auth_data = {
        "provider": "openrouter",
        "profile_id": "openrouter-1",
        "base_url": "https://openrouter.ai/api/v1",
        "api_key": "sk-or-test-key",
    }
    ProfileAuthManager.save_profile_auth("openrouter", "openrouter-1", auth_data)
    AutoAssigner.ensure_profile_definition("openrouter", "openrouter-1")

    captured_request = []

    def _mock_urlopen(req, timeout=15):
        captured_request.append(req)
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "data": [
                {"id": "anthropic/claude-3.7-sonnet"},
                {"id": "openai/gpt-4o"},
                {"id": "deepseek/deepseek-r1"},
            ]
        }).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp
        return mock_resp

    with patch("urllib.request.urlopen", side_effect=_mock_urlopen):
        models = service.discover_models_sync("openrouter", timeout=5.0)

    assert models is not None
    assert "anthropic/claude-3.7-sonnet" in models
    assert "openai/gpt-4o" in models

    assert len(captured_request) == 1
    req = captured_request[0]
    assert req.full_url == "https://openrouter.ai/api/v1/models"
    assert req.headers.get("Authorization") == "Bearer sk-or-test-key"
    assert "Http-referer" in req.headers or "HTTP-Referer" in req.headers
    assert "X-openrouter-title" in req.headers or "X-OpenRouter-Title" in req.headers


@pytest.mark.unit
def test_p0_2_nvidia_discovery(tmp_path):
    """Verify NVIDIA model discovery queries {base_url}/models with Bearer token."""
    cache_file = tmp_path / "models_cache.json"
    service = ModelDiscoveryService(cache_path=cache_file)

    auth_data = {
        "provider": "nvidia",
        "profile_id": "nvidia-1",
        "base_url": "https://integrate.api.nvidia.com/v1",
        "api_key": "nvapi-test-key",
    }
    ProfileAuthManager.save_profile_auth("nvidia", "nvidia-1", auth_data)
    AutoAssigner.ensure_profile_definition("nvidia", "nvidia-1")

    captured_request = []

    def _mock_urlopen(req, timeout=15):
        captured_request.append(req)
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "data": [
                {"id": "meta/llama-3.1-405b-instruct"},
                {"id": "nvidia/nemotron-4-340b-instruct"},
            ]
        }).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp
        return mock_resp

    with patch("urllib.request.urlopen", side_effect=_mock_urlopen):
        models = service.discover_models_sync("nvidia", timeout=5.0)

    assert models is not None
    assert "meta/llama-3.1-405b-instruct" in models
    assert captured_request[0].headers.get("Authorization") == "Bearer nvapi-test-key"


@pytest.mark.unit
def test_p0_2_ollama_native_tags_discovery(tmp_path):
    """Verify Ollama discovery queries native endpoint /api/tags."""
    cache_file = tmp_path / "models_cache.json"
    service = ModelDiscoveryService(cache_path=cache_file)

    auth_data = {
        "provider": "ollama",
        "profile_id": "ollama-1",
        "base_url": "http://127.0.0.1:11434",
    }
    ProfileAuthManager.save_profile_auth("ollama", "ollama-1", auth_data)
    AutoAssigner.ensure_profile_definition("ollama", "ollama-1")

    def _mock_urlopen(req, timeout=5):
        if "/api/tags" in req.full_url:
            mock_resp = MagicMock()
            mock_resp.read.return_value = json.dumps({
                "models": [
                    {"name": "llama3.3:latest"},
                    {"name": "qwen2.5-coder:32b"},
                ]
            }).encode("utf-8")
            mock_resp.__enter__.return_value = mock_resp
            return mock_resp
        raise urllib.error.HTTPError(req.full_url, 404, "Not Found", {}, None)

    with patch("urllib.request.urlopen", side_effect=_mock_urlopen):
        models = service.discover_models_sync("ollama", timeout=5.0)

    assert models is not None
    assert "llama3.3:latest" in models
    assert "qwen2.5-coder:32b" in models


@pytest.mark.unit
def test_p0_2_discovery_error_preservation(tmp_path):
    """Verify exact HTTP / connection error is preserved in cache for UI display."""
    cache_file = tmp_path / "models_cache.json"
    service = ModelDiscoveryService(cache_path=cache_file)

    auth_data = {
        "provider": "openrouter",
        "profile_id": "openrouter-1",
        "base_url": "https://openrouter.ai/api/v1",
        "api_key": "sk-or-invalid-key",
    }
    ProfileAuthManager.save_profile_auth("openrouter", "openrouter-1", auth_data)
    AutoAssigner.ensure_profile_definition("openrouter", "openrouter-1")

    err_body = json.dumps({"error": {"message": "Invalid API key provided"}}).encode("utf-8")
    http_error = urllib.error.HTTPError(
        url="https://openrouter.ai/api/v1/models",
        code=401,
        msg="Unauthorized",
        hdrs={},
        fp=MagicMock(read=MagicMock(return_value=err_body)),
    )

    with patch("urllib.request.urlopen", side_effect=http_error):
        res = service.discover_models_sync("openrouter", timeout=5.0)

    assert res is None
    error_msg = service.get_error("openrouter")
    assert error_msg is not None
    assert "401" in error_msg
    assert "Invalid API key" in error_msg

    meta = service.get_models_with_metadata("openrouter")
    assert meta["error"] == error_msg


# ═════════════════════════════════════════════════════════════════════════════
# P0-3: Health & Quota Status Fixes
# ═════════════════════════════════════════════════════════════════════════════

@pytest.mark.unit
def test_p0_3_cooldown_vs_quota_exhausted_separation(tmp_path):
    """Verify temporary error cooldown (frec.reset_at > now) is STATUS_COOLDOWN, not QUOTA_EXHAUSTED."""
    cfg = RouterConfig()
    cfg.profiles["codex-orch"] = RouterProfileConfig(
        profile_id="codex-orch",
        provider="openai-codex",
        account_id="codex-orch",
        preferred_models=["gpt-4o"],
        enabled=True,
    )
    save_router_config(cfg)

    ProfileAuthManager.save_profile_auth("openai-codex", "codex-orch", {"api_key": "sk-test", "provider": "openai-codex"})

    from antigravity_provider.router.router_engine import get_router_engine
    from antigravity_provider.router.health_tracker import FamilyHealthRecord
    engine = get_router_engine()
    now = time.time()
    rec = engine.health.get_or_create("codex-orch")
    rec.overall_state = HEALTHY
    rec.last_error = "Server 500 Error"
    rec.families["gpt"] = FamilyHealthRecord(
        family="gpt",
        state=COOLDOWN,
        reset_at=now + 120,
        reason="500 Server Error Backoff",
    )

    service = UnifiedHealthService.get()
    profiles = service.scan_all(force=True)
    codex_vm = next((p for p in profiles["openai-codex"] if p.profile_id == "codex-orch"), None)

    assert codex_vm is not None
    # Must be COOLDOWN, NOT QUOTA_EXHAUSTED
    assert codex_vm.health_state == STATUS_COOLDOWN
    assert "Откат" in codex_vm.health_label_ru
    assert "Квота исчерпана" not in codex_vm.health_label_ru


@pytest.mark.unit
def test_p0_3_rate_limited_checked_before_cooldown(tmp_path):
    """Verify RATE_LIMITED is prioritized before error cooldowns."""
    cfg = RouterConfig()
    cfg.profiles["codex-orch"] = RouterProfileConfig(
        profile_id="codex-orch",
        provider="openai-codex",
        account_id="codex-orch",
        preferred_models=["gpt-4o"],
        enabled=True,
    )
    save_router_config(cfg)
    ProfileAuthManager.save_profile_auth("openai-codex", "codex-orch", {"api_key": "sk-test", "provider": "openai-codex"})

    from antigravity_provider.router.router_engine import get_router_engine
    from antigravity_provider.router.health_tracker import FamilyHealthRecord
    engine = get_router_engine()
    now = time.time()
    rec = engine.health.get_or_create("codex-orch")
    rec.overall_state = RATE_LIMITED
    rec.last_error = "429 Too Many Requests"
    rec.families["gpt"] = FamilyHealthRecord(
        family="gpt",
        state=RATE_LIMITED,
        reset_at=now + 60,
        reason="Rate Limit 429",
    )

    service = UnifiedHealthService.get()
    profiles = service.scan_all(force=True)
    codex_vm = next((p for p in profiles["openai-codex"] if p.profile_id == "codex-orch"), None)

    assert codex_vm is not None
    assert codex_vm.health_state == STATUS_RATE_LIMITED
    assert "Лимит запросов" in codex_vm.health_label_ru


@pytest.mark.unit
def test_p0_3_health_tracker_no_overall_quota_on_missing_model():
    """Verify HealthTracker.mark_quota_exhausted does NOT set overall_state = QUOTA_EXHAUSTED on missing/default model."""
    ht = HealthTracker()
    rec = ht.get_or_create("codex-orch")
    rec.overall_state = HEALTHY

    # Call with model_name=None
    ht.mark_quota_exhausted("codex-orch", model_name=None, duration=600, reason="Test")
    assert rec.overall_state == HEALTHY

    # Call with model_name="default"
    ht.mark_quota_exhausted("codex-orch", model_name="default", duration=600, reason="Test")
    assert rec.overall_state == HEALTHY


@pytest.mark.unit
def test_p0_3_codex_adapter_classify_error():
    """Verify CodexAdapter.classify_error correctly distinguishes rate limit, auth, transient, and quota."""
    adapter = CodexAdapter()

    # Rate limited
    c1 = adapter.classify_error(Exception("HTTP 429: Too Many Requests"))
    assert c1.category == ErrorCategory.RATE_LIMITED

    c2 = adapter.classify_error(Exception("Rate limit reached for requests per min (RPM)"))
    assert c2.category == ErrorCategory.RATE_LIMITED

    # Auth
    c3 = adapter.classify_error(Exception("HTTP 401: Invalid API key"))
    assert c3.category == ErrorCategory.AUTH_REQUIRED

    # Real Quota
    c4 = adapter.classify_error(Exception("You exceeded your current quota, please check your plan and billing details."))
    assert c4.category == ErrorCategory.QUOTA_EXHAUSTED

    c5 = adapter.classify_error(Exception("insufficient_quota"))
    assert c5.category == ErrorCategory.QUOTA_EXHAUSTED

    # Transient
    c6 = adapter.classify_error(Exception("HTTP 502: Bad Gateway"))
    assert c6.category == ErrorCategory.TRANSIENT

    c7 = adapter.classify_error(Exception("Connection reset by peer"))
    assert c7.category == ErrorCategory.TRANSIENT
