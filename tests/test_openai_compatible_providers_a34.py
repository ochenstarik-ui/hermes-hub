"""A34 P0-2a: OpenRouter + NVIDIA OpenAI-compatible adapters.

TDD tests (RED first, then GREEN):
1. get_adapter registration for openrouter / nvidia provider keys.
2. invoke() POSTs to the configurable base_url (profile.custom_base_url,
   then auth_config["base_url"], then provider default).
3. discover_models() does GET {base_url}/models and returns the server's
   model list — no invented/hardcoded model list.
4. Bearer auth header from auth_config api_key.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from antigravity_provider.router.adapters import get_adapter
from antigravity_provider.router.router_config import RouterProfileConfig


OPENROUTER_DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
NVIDIA_DEFAULT_BASE_URL = "https://integrate.api.nvidia.com/v1"


def _mock_urlopen(payload: dict) -> MagicMock:
    mock_response = MagicMock()
    mock_response.read.return_value = json.dumps(payload).encode("utf-8")
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


def _models_response(ids: list[str]) -> dict:
    return {"data": [{"id": m, "object": "model"} for m in ids]}


# ─────────────────────────────────────────────────────────────────────────────
# 1. Registration
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.unit
def test_get_adapter_openrouter_registered():
    adapter = get_adapter("openrouter")
    assert adapter is not None
    assert type(adapter).__name__ == "OpenRouterAdapter"


@pytest.mark.unit
def test_get_adapter_nvidia_registered():
    adapter = get_adapter("nvidia")
    assert adapter is not None
    assert type(adapter).__name__ == "NvidiaAdapter"


@pytest.mark.unit
def test_get_adapter_aliases_registered():
    assert type(get_adapter("openrouter")).__name__ == "OpenRouterAdapter"
    assert type(get_adapter("nvidia")).__name__ == "NvidiaAdapter"
    assert type(get_adapter("nvidia-nim")).__name__ == "NvidiaAdapter"


# ─────────────────────────────────────────────────────────────────────────────
# 2. invoke() hits the configurable URL
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.unit
@pytest.mark.parametrize("provider", ["openrouter", "nvidia"])
def test_invoke_uses_profile_custom_base_url(provider):
    adapter = get_adapter(provider)
    profile = RouterProfileConfig(
        profile_id=f"{provider}-1",
        provider=provider,
        custom_base_url="http://127.0.0.1:9999/v1",
        preferred_models=["some-model"],
        auth_config={"api_key": "test-key"},
    )
    request = {
        "model": "some-model",
        "messages": [{"role": "user", "content": "Hello"}],
        "temperature": 0.5,
    }

    with patch("urllib.request.urlopen", return_value=_mock_urlopen(_chat_response())) as mock_urlopen:
        resp = adapter.invoke(profile, request)

    assert resp["choices"][0]["message"]["content"] == "OK"
    req_arg = mock_urlopen.call_args[0][0]
    assert req_arg.get_full_url() == "http://127.0.0.1:9999/v1/chat/completions"
    assert req_arg.get_method() == "POST"
    assert req_arg.headers.get("Authorization") == "Bearer test-key"
    payload = json.loads(req_arg.data.decode("utf-8"))
    assert payload["model"] == "some-model"
    assert payload["messages"] == [{"role": "user", "content": "Hello"}]


@pytest.mark.unit
@pytest.mark.parametrize("provider", ["openrouter", "nvidia"])
def test_invoke_uses_auth_config_base_url(provider):
    adapter = get_adapter(provider)
    profile = RouterProfileConfig(
        profile_id=f"{provider}-2",
        provider=provider,
        preferred_models=["some-model"],
        auth_config={"base_url": "http://127.0.0.1:9998/v1", "api_key": "k2"},
    )
    request = {
        "model": "some-model",
        "messages": [{"role": "user", "content": "Hi"}],
    }

    with patch("urllib.request.urlopen", return_value=_mock_urlopen(_chat_response())) as mock_urlopen:
        adapter.invoke(profile, request)

    req_arg = mock_urlopen.call_args[0][0]
    assert req_arg.get_full_url() == "http://127.0.0.1:9998/v1/chat/completions"


@pytest.mark.unit
def test_invoke_openrouter_default_base_url():
    adapter = get_adapter("openrouter")
    profile = RouterProfileConfig(
        profile_id="openrouter-1",
        provider="openrouter",
        preferred_models=["openai/gpt-4o"],
        auth_config={"api_key": "or-key"},
    )
    request = {
        "model": "openai/gpt-4o",
        "messages": [{"role": "user", "content": "Hi"}],
    }

    with patch("urllib.request.urlopen", return_value=_mock_urlopen(_chat_response())) as mock_urlopen:
        adapter.invoke(profile, request)

    req_arg = mock_urlopen.call_args[0][0]
    assert req_arg.get_full_url() == f"{OPENROUTER_DEFAULT_BASE_URL}/chat/completions"


@pytest.mark.unit
def test_invoke_nvidia_default_base_url():
    adapter = get_adapter("nvidia")
    profile = RouterProfileConfig(
        profile_id="nvidia-1",
        provider="nvidia",
        preferred_models=["meta/llama-3.1-8b-instruct"],
        auth_config={"api_key": "nv-key"},
    )
    request = {
        "model": "meta/llama-3.1-8b-instruct",
        "messages": [{"role": "user", "content": "Hi"}],
    }

    with patch("urllib.request.urlopen", return_value=_mock_urlopen(_chat_response())) as mock_urlopen:
        adapter.invoke(profile, request)

    req_arg = mock_urlopen.call_args[0][0]
    assert req_arg.get_full_url() == f"{NVIDIA_DEFAULT_BASE_URL}/chat/completions"


# ─────────────────────────────────────────────────────────────────────────────
# 3. discover_models() — GET /models, no invented list
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.unit
@pytest.mark.parametrize("provider", ["openrouter", "nvidia"])
def test_discover_models_gets_models_endpoint(provider):
    adapter = get_adapter(provider)
    profile = RouterProfileConfig(
        profile_id=f"{provider}-1",
        provider=provider,
        custom_base_url="http://127.0.0.1:9997/v1",
        auth_config={"api_key": "k"},
    )
    server_models = ["model-a", "model-b", "model-c"]

    with patch("urllib.request.urlopen", return_value=_mock_urlopen(_models_response(server_models))) as mock_urlopen:
        models = adapter.discover_models(profile)

    req_arg = mock_urlopen.call_args[0][0]
    assert req_arg.get_full_url() == "http://127.0.0.1:9997/v1/models"
    assert req_arg.get_method() == "GET"
    assert models == sorted(server_models)


@pytest.mark.unit
@pytest.mark.parametrize("provider", ["openrouter", "nvidia"])
def test_discover_models_returns_server_list_not_invented(provider):
    """The returned list must come from the server response, not a hardcoded list."""
    adapter = get_adapter(provider)
    profile = RouterProfileConfig(
        profile_id=f"{provider}-1",
        provider=provider,
        custom_base_url="http://127.0.0.1:9996/v1",
        auth_config={"api_key": "k"},
    )
    server_models = ["totally-custom-model-xyz"]

    with patch("urllib.request.urlopen", return_value=_mock_urlopen(_models_response(server_models))):
        models = adapter.discover_models(profile)

    assert models == ["totally-custom-model-xyz"]
    # No invented defaults: a model that the server did not list must not appear.
    assert "deepseek-chat" not in models
    assert "gpt-4o" not in models
    assert "llama" not in " ".join(models).lower()


@pytest.mark.unit
@pytest.mark.parametrize("provider", ["openrouter", "nvidia"])
def test_discover_models_fallback_on_error(provider):
    """On transport error, fall back to profile.preferred_models (no invented list)."""
    adapter = get_adapter(provider)
    profile = RouterProfileConfig(
        profile_id=f"{provider}-1",
        provider=provider,
        custom_base_url="http://127.0.0.1:9995/v1",
        preferred_models=["my-pref-model"],
        auth_config={"api_key": "k"},
    )

    with patch("urllib.request.urlopen", side_effect=OSError("connection refused")):
        models = adapter.discover_models(profile)

    assert models == ["my-pref-model"]


# ─────────────────────────────────────────────────────────────────────────────
# 4. health_check
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.unit
@pytest.mark.parametrize("provider", ["openrouter", "nvidia"])
def test_health_check(provider):
    adapter = get_adapter(provider)
    profile = RouterProfileConfig(
        profile_id=f"{provider}-1",
        provider=provider,
        custom_base_url="http://127.0.0.1:9994/v1",
        auth_config={"api_key": "k"},
    )

    ok_resp = MagicMock()
    ok_resp.status = 200
    ok_resp.__enter__.return_value = ok_resp
    with patch("urllib.request.urlopen", return_value=ok_resp):
        assert adapter.health_check(profile) is True

    import urllib.error
    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("refused")):
        assert adapter.health_check(profile) is False
