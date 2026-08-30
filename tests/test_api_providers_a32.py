"""A32 Provider Adapters & Limits Export Test Suite.

Verifies:
1. Ollama adapter (local and remote endpoints, API key, discover_models via /models and /api/tags,
   health_check, unlimited quota).
2. Claude adapter (health_check real probe, discover_models real probe with fallback).
3. OpenRouter adapter (HTTP-Referer, X-OpenRouter-Title headers, context_length and display_name discovery).
4. NVIDIA adapter (invoke, health_check, discover_models).
5. Quota & Limits export (/api/quotas/export endpoint and export_quotas action in JSON and CSV).
6. Multi-profile credential and token isolation.
"""
from __future__ import annotations

import csv
import io
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from antigravity_provider.router.adapters import get_adapter
from antigravity_provider.router.adapters.claude_adapter import DEFAULT_CLAUDE_MODELS, ClaudeAdapter
from antigravity_provider.router.adapters.ollama_adapter import DEFAULT_OLLAMA_BASE_URL, OllamaAdapter
from antigravity_provider.router.adapters.openrouter_adapter import OpenRouterAdapter
from antigravity_provider.router.adapters.nvidia_adapter import NvidiaAdapter
from antigravity_provider.router.router_config import RouterConfig, RouterProfileConfig
from antigravity_provider.router.quota_collector import AccountQuotaService
from antigravity_provider.router.action_handler import ActionExecutor, generate_quotas_export
from antigravity_provider.router.profile_manager import ProfileAuthManager
from antigravity_provider.router.web.server import app


def _mock_urlopen(payload: dict, status: int = 200) -> MagicMock:
    mock_response = MagicMock()
    mock_response.read.return_value = json.dumps(payload).encode("utf-8")
    mock_response.status = status
    mock_response.__enter__.return_value = mock_response
    return mock_response


def _chat_response(content: str = "OK") -> dict:
    return {
        "id": "chatcmpl-test",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
    }


# ─────────────────────────────────────────────────────────────────────────────
# 1. Ollama Adapter Tests
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.unit
def test_ollama_adapter_registered():
    adapter = get_adapter("ollama")
    assert adapter is not None
    assert isinstance(adapter, OllamaAdapter)


@pytest.mark.unit
def test_ollama_invoke_default_base_url():
    adapter = OllamaAdapter()
    profile = RouterProfileConfig(
        profile_id="ollama-1",
        provider="ollama",
        preferred_models=["llama3:latest"],
        auth_config={},
    )
    request = {
        "model": "llama3:latest",
        "messages": [{"role": "user", "content": "ping"}],
    }

    with patch("urllib.request.urlopen", return_value=_mock_urlopen(_chat_response("pong"))) as mock_urlopen:
        resp = adapter.invoke(profile, request)

    assert resp["choices"][0]["message"]["content"] == "pong"
    req_arg = mock_urlopen.call_args[0][0]
    assert req_arg.get_full_url() == f"{DEFAULT_OLLAMA_BASE_URL}/chat/completions"
    assert req_arg.get_method() == "POST"
    assert "Authorization" not in req_arg.headers


@pytest.mark.unit
def test_ollama_invoke_remote_custom_url_and_api_key():
    adapter = OllamaAdapter()
    profile = RouterProfileConfig(
        profile_id="ollama-remote-1",
        provider="ollama",
        custom_base_url="https://remote-ollama.example.com:11434/v1",
        preferred_models=["mistral:latest"],
        auth_config={"api_key": "secret-bearer-token"},
    )
    request = {
        "model": "mistral:latest",
        "messages": [{"role": "user", "content": "hi"}],
    }

    with patch("urllib.request.urlopen", return_value=_mock_urlopen(_chat_response("hello"))) as mock_urlopen:
        resp = adapter.invoke(profile, request)

    assert resp["choices"][0]["message"]["content"] == "hello"
    req_arg = mock_urlopen.call_args[0][0]
    assert req_arg.get_full_url() == "https://remote-ollama.example.com:11434/v1/chat/completions"
    assert req_arg.headers.get("Authorization") == "Bearer secret-bearer-token"


@pytest.mark.unit
def test_ollama_discover_models_v1_models_endpoint():
    adapter = OllamaAdapter()
    profile = RouterProfileConfig(
        profile_id="ollama-1",
        provider="ollama",
        auth_config={},
    )
    models_payload = {"data": [{"id": "qwen2.5-coder:7b"}, {"id": "llama3.1:8b"}]}

    with patch("urllib.request.urlopen", return_value=_mock_urlopen(models_payload)) as mock_urlopen:
        models = adapter.discover_models(profile)

    assert models == ["llama3.1:8b", "qwen2.5-coder:7b"]
    req_arg = mock_urlopen.call_args[0][0]
    assert req_arg.get_full_url() == "http://127.0.0.1:11434/v1/models"


@pytest.mark.unit
def test_ollama_discover_models_fallback_to_native_api_tags():
    adapter = OllamaAdapter()
    profile = RouterProfileConfig(
        profile_id="ollama-1",
        provider="ollama",
        auth_config={},
    )
    native_tags_payload = {
        "models": [
            {"name": "deepseek-r1:14b", "model": "deepseek-r1:14b"},
            {"name": "phi4:latest", "model": "phi4:latest"},
        ]
    }

    def _side_effect(req, timeout=5):
        if req.get_full_url().endswith("/v1/models"):
            raise OSError("404 Not Found")
        if req.get_full_url().endswith("/api/tags"):
            return _mock_urlopen(native_tags_payload)
        raise OSError("Unknown url")

    with patch("urllib.request.urlopen", side_effect=_side_effect):
        models = adapter.discover_models(profile)

    assert models == ["deepseek-r1:14b", "phi4:latest"]


@pytest.mark.unit
def test_ollama_health_check():
    adapter = OllamaAdapter()
    profile = RouterProfileConfig(
        profile_id="ollama-1",
        provider="ollama",
        auth_config={},
    )

    with patch("urllib.request.urlopen", return_value=_mock_urlopen({"data": []}, status=200)):
        assert adapter.health_check(profile) is True

    with patch("urllib.request.urlopen", side_effect=OSError("connection refused")):
        assert adapter.health_check(profile) is False


@pytest.mark.unit
def test_ollama_quota_unlimited():
    service = AccountQuotaService.get()
    snap = service.get_snapshot("ollama", "ollama-1")
    assert snap is not None
    assert snap.buckets[0].status == "unlimited"
    assert snap.buckets[0].remaining_percent == 100.0
    assert "Без ограничений" in snap.buckets[0].formatted_remaining()


# ─────────────────────────────────────────────────────────────────────────────
# 2. Claude Adapter Tests (Real Probes & Fallback)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.unit
def test_claude_health_check_real_probe():
    adapter = ClaudeAdapter()
    profile = RouterProfileConfig(
        profile_id="claude-1",
        provider="claude",
        auth_config={"api_key": "sk-ant-testkey"},
    )

    with patch("urllib.request.urlopen", return_value=_mock_urlopen({"data": []}, status=200)) as mock_urlopen:
        ok = adapter.health_check(profile)

    assert ok is True
    req_arg = mock_urlopen.call_args[0][0]
    assert req_arg.get_full_url() == "https://api.anthropic.com/v1/models"
    assert req_arg.headers.get("X-api-key") == "sk-ant-testkey"
    assert req_arg.headers.get("Anthropic-version") == "2023-06-01"


@pytest.mark.unit
def test_claude_discover_models_api_probe_and_fallback():
    adapter = ClaudeAdapter()
    profile = RouterProfileConfig(
        profile_id="claude-1",
        provider="claude",
        auth_config={"access_token": "oauth-token-123"},
    )
    models_payload = {
        "data": [
            {"id": "claude-3-7-sonnet-20250219", "display_name": "Claude 3.7 Sonnet"},
            {"id": "claude-3-5-haiku-20241022", "display_name": "Claude 3.5 Haiku"},
        ]
    }

    with patch("urllib.request.urlopen", return_value=_mock_urlopen(models_payload)) as mock_urlopen:
        models = adapter.discover_models(profile)

    assert models == ["claude-3-5-haiku-20241022", "claude-3-7-sonnet-20250219"]
    req_arg = mock_urlopen.call_args[0][0]
    assert req_arg.headers.get("Authorization") == "Bearer oauth-token-123"
    assert req_arg.headers.get("Anthropic-beta") == "oauth-2025-04-20"

    # Fallback test on error
    with patch("urllib.request.urlopen", side_effect=OSError("API offline")):
        fallback_models = adapter.discover_models(profile)
    assert fallback_models == DEFAULT_CLAUDE_MODELS


# ─────────────────────────────────────────────────────────────────────────────
# 3. OpenRouter Adapter Tests (Referer, Title, Context Length, Display Name)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.unit
def test_openrouter_headers_and_metadata_discovery():
    adapter = OpenRouterAdapter()
    profile = RouterProfileConfig(
        profile_id="openrouter-1",
        provider="openrouter",
        auth_config={"api_key": "sk-or-v1-key"},
    )
    models_payload = {
        "data": [
            {
                "id": "openai/gpt-4o",
                "name": "OpenAI: GPT-4o",
                "context_length": 128000,
            },
            {
                "id": "anthropic/claude-3.5-sonnet",
                "name": "Anthropic: Claude 3.5 Sonnet",
                "context_length": 200000,
            },
        ]
    }

    with patch("urllib.request.urlopen", return_value=_mock_urlopen(models_payload)) as mock_urlopen:
        models = adapter.discover_models(profile)

    assert "openai/gpt-4o" in models
    assert "anthropic/claude-3.5-sonnet" in models

    req_arg = mock_urlopen.call_args[0][0]
    assert req_arg.headers.get("Http-referer") == "https://github.com/ochenstarik-ui/hermes-hub"
    assert req_arg.headers.get("X-openrouter-title") == "Hermes Hub"

    # Check extracted metadata & context window
    gpt4o_meta = adapter.get_model_metadata("openai/gpt-4o")
    assert gpt4o_meta is not None
    assert gpt4o_meta["display_name"] == "OpenAI: GPT-4o"
    assert gpt4o_meta["context_length"] == 128000
    assert adapter.get_context_window(profile, "openai/gpt-4o") == 128000


# ─────────────────────────────────────────────────────────────────────────────
# 4. NVIDIA Adapter Tests
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.unit
def test_nvidia_adapter_invoke_and_health():
    adapter = get_adapter("nvidia")
    assert isinstance(adapter, NvidiaAdapter)

    profile = RouterProfileConfig(
        profile_id="nvidia-1",
        provider="nvidia",
        auth_config={"api_key": "nvapi-test"},
    )

    with patch("urllib.request.urlopen", return_value=_mock_urlopen(_chat_response("NV_OK"))):
        resp = adapter.invoke(profile, {"model": "meta/llama-3.1-8b-instruct", "messages": [{"role": "user", "content": "hi"}]})
    assert resp["choices"][0]["message"]["content"] == "NV_OK"

    with patch("urllib.request.urlopen", return_value=_mock_urlopen({}, status=200)):
        assert adapter.health_check(profile) is True


# ─────────────────────────────────────────────────────────────────────────────
# 5. Quota & Limits Export Tests
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.unit
def test_generate_quotas_export_json_and_csv():
    json_export = generate_quotas_export(format="json")
    assert isinstance(json_export, dict)
    assert "exported_at" in json_export
    assert "total_profiles" in json_export
    assert "profiles" in json_export
    assert "rows" in json_export
    assert len(json_export["profiles"]) > 0

    csv_export = generate_quotas_export(format="csv")
    assert isinstance(csv_export, str)
    reader = csv.reader(io.StringIO(csv_export))
    header = next(reader)
    assert "provider" in header
    assert "profile_id" in header
    assert "remaining_percent" in header
    assert "status" in header


@pytest.mark.unit
def test_action_handler_export_quotas():
    res_json = ActionExecutor.execute("export_quotas", {"format": "json"})
    assert res_json["ok"] is True
    assert res_json["data"]["format"] == "json"
    assert "report" in res_json["data"]

    res_csv = ActionExecutor.execute("export_quotas", {"format": "csv"})
    assert res_csv["ok"] is True
    assert res_csv["data"]["format"] == "csv"
    assert "content" in res_csv["data"]


@pytest.mark.unit
def test_api_quotas_export_endpoint():
    client = TestClient(app)

    # JSON export
    resp_json = client.get("/api/quotas/export?format=json")
    assert resp_json.status_code == 200
    data = resp_json.json()
    assert "exported_at" in data
    assert "profiles" in data

    # CSV export
    resp_csv = client.get("/api/quotas/export?format=csv")
    assert resp_csv.status_code == 200
    assert "text/csv" in resp_csv.headers["content-type"]
    assert "hermes_quotas_export.csv" in resp_csv.headers["content-disposition"]
    assert "provider,profile_id" in resp_csv.text


# ─────────────────────────────────────────────────────────────────────────────
# 6. Multi-Profile Key Isolation Tests
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.unit
def test_profile_credential_isolation(tmp_path):
    with patch("antigravity_provider.paths.get_hermes_home", return_value=tmp_path):
        ProfileAuthManager.save_profile_auth("ollama", "ollama-1", {"api_key": "key-ollama-1", "base_url": "http://127.0.0.1:11434/v1"})
        ProfileAuthManager.save_profile_auth("ollama", "ollama-2", {"api_key": "key-ollama-2", "base_url": "http://192.168.1.50:11434/v1"})
        ProfileAuthManager.save_profile_auth("openrouter", "openrouter-1", {"api_key": "key-or-1"})
        ProfileAuthManager.save_profile_auth("openrouter", "openrouter-2", {"api_key": "key-or-2"})

        p1 = ProfileAuthManager.load_profile_auth("ollama", "ollama-1")
        p2 = ProfileAuthManager.load_profile_auth("ollama", "ollama-2")
        or1 = ProfileAuthManager.load_profile_auth("openrouter", "openrouter-1")
        or2 = ProfileAuthManager.load_profile_auth("openrouter", "openrouter-2")

        assert p1["api_key"] == "key-ollama-1"
        assert p2["api_key"] == "key-ollama-2"
        assert p1["base_url"] != p2["base_url"]

        assert or1["api_key"] == "key-or-1"
        assert or2["api_key"] == "key-or-2"
        assert or1["api_key"] != or2["api_key"]
