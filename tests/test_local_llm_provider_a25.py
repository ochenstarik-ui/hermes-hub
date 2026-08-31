"""Unit and integration tests for Task A25: Local LLM Provider Integration.

Tests:
1. LocalLLMAdapter.invoke with mock HTTP server / urllib.
2. Error classification and instant failover on network / auth / rate limit errors.
3. discover_models and ModelDiscoveryService for 'local'.
4. find_free_slot("local") and config migration for local-1 / local-2.
5. Quota snapshot state "Без ограничений" (is_loading=False, status=unlimited).
6. Configurable custom_base_url and absence of hardcoded unconfigurable IP/ports.
7. ProfileAuthManager local endpoint verification and profile status.
"""
from __future__ import annotations

import io
import json
import os
import shutil
import sys
import tempfile
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from antigravity_provider.router.adapters import get_adapter
from antigravity_provider.router.adapters.base_adapter import ErrorCategory
from antigravity_provider.router.adapters.local_adapter import LocalLLMAdapter
from antigravity_provider.router.auto_assigner import AutoAssigner
from antigravity_provider.router.model_discovery_service import ModelDiscoveryService
from antigravity_provider.router.profile_manager import ProfileAuthManager
from antigravity_provider.router.quota_collector import AccountQuotaService
from antigravity_provider.router.router_config import (
    RouterConfig,
    RouterProfileConfig,
    get_default_router_config,
    load_router_config,
    save_router_config,
)


class TestLocalLLMAdapterInvoke:
    """Test LocalLLMAdapter invocation and parameters."""

    def test_adapter_registration(self):
        """Adapter must be registered for local, local-llm, llama.cpp, ollama, vllm."""
        for key in ["local", "local-llm", "llama.cpp", "ollama", "vllm"]:
            adapter = get_adapter(key)
            assert isinstance(adapter, LocalLLMAdapter)

    def test_invoke_success_without_api_key(self):
        """Invoke should perform POST to {base_url}/chat/completions without Authorization header if no key."""
        adapter = LocalLLMAdapter()
        profile = RouterProfileConfig(
            profile_id="local-1",
            provider="local",
            custom_base_url="http://127.0.0.1:8081/v1",
            preferred_models=["Qwen3.8-27B-Q4_K_M.gguf"],
        )
        request = {
            "messages": [{"role": "user", "content": "Hello"}],
            "temperature": 0.5,
        }

        mock_resp_data = {
            "id": "chatcmpl-123",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "Hi there!"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
        }

        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(mock_resp_data).encode("utf-8")
        mock_response.__enter__.return_value = mock_response

        with patch("urllib.request.urlopen", return_value=mock_response) as mock_urlopen:
            resp = adapter.invoke(profile, request)

            assert resp == mock_resp_data
            mock_urlopen.assert_called_once()
            req_arg = mock_urlopen.call_args[0][0]
            assert req_arg.get_full_url() == "http://127.0.0.1:8081/v1/chat/completions"
            assert req_arg.get_method() == "POST"
            # Verify no Authorization header sent
            assert "Authorization" not in req_arg.headers
            payload = json.loads(req_arg.data.decode("utf-8"))
            assert payload["model"] == "Qwen3.8-27B-Q4_K_M.gguf"
            assert payload["messages"] == [{"role": "user", "content": "Hello"}]
            assert payload["temperature"] == 0.5

    def test_invoke_with_api_key_and_custom_base_url(self):
        """Invoke should include Bearer token and use custom base url when provided."""
        adapter = LocalLLMAdapter()
        profile = RouterProfileConfig(
            profile_id="local-2",
            provider="local",
            custom_base_url="http://192.168.1.50:11434/v1",
            preferred_models=["llama3:8b"],
            auth_config={"api_key": "secret-token-123"},
        )
        request = {
            "model": "llama3:8b",
            "messages": [{"role": "user", "content": "Test"}],
            "tools": [{"type": "function", "function": {"name": "search"}}],
        }

        # Заглушка должна быть похожа на настоящий ответ: сервер всегда
        # возвращает хотя бы один choice с текстом. Пустой choices означает
        # отказ, и адаптер обязан его отвергнуть, а не выдать за успех.
        mock_resp_data = {
            "id": "chatcmpl-456",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "OK"},
                    "finish_reason": "stop",
                }
            ],
        }
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(mock_resp_data).encode("utf-8")
        mock_response.__enter__.return_value = mock_response

        with patch("urllib.request.urlopen", return_value=mock_response) as mock_urlopen:
            resp = adapter.invoke(profile, request)
            assert resp == mock_resp_data

            req_arg = mock_urlopen.call_args[0][0]
            assert req_arg.get_full_url() == "http://192.168.1.50:11434/v1/chat/completions"
            assert req_arg.headers.get("Authorization") == "Bearer secret-token-123"
            payload = json.loads(req_arg.data.decode("utf-8"))
            assert payload["tools"] == [{"type": "function", "function": {"name": "search"}}]


class TestLocalLLMErrorClassification:
    """Test error classification for instant failover and auth errors."""

    def test_classify_connection_refused_as_transient(self):
        adapter = LocalLLMAdapter()
        exc = urllib.error.URLError("Connection refused [WinError 10061]")
        classification = adapter.classify_error(exc)
        assert classification.category == ErrorCategory.TRANSIENT
        assert classification.retry_delay_seconds <= 5

    def test_classify_timeout_as_transient(self):
        adapter = LocalLLMAdapter()
        exc = TimeoutError("The read operation timed out")
        classification = adapter.classify_error(exc)
        assert classification.category == ErrorCategory.TRANSIENT
        assert classification.retry_delay_seconds <= 5

    def test_classify_http_502_503_as_transient(self):
        adapter = LocalLLMAdapter()
        exc = RuntimeError("Local LLM API Error (502): Bad Gateway")
        classification = adapter.classify_error(exc)
        assert classification.category == ErrorCategory.TRANSIENT

    def test_classify_http_401_403_as_auth_required(self):
        adapter = LocalLLMAdapter()
        exc = RuntimeError("Local LLM API Error (401): Unauthorized access")
        classification = adapter.classify_error(exc)
        assert classification.category == ErrorCategory.AUTH_REQUIRED

    def test_classify_http_429_as_rate_limited(self):
        adapter = LocalLLMAdapter()
        exc = RuntimeError("Local LLM API Error (429): Too Many Requests")
        classification = adapter.classify_error(exc)
        assert classification.category == ErrorCategory.RATE_LIMITED


class TestLocalLLMModelDiscovery:
    """Test discover_models and ModelDiscoveryService for local provider."""

    def test_adapter_discover_models_success(self):
        adapter = LocalLLMAdapter()
        profile = RouterProfileConfig(
            profile_id="local-1",
            provider="local",
            custom_base_url="http://127.0.0.1:8081/v1",
        )

        mock_models_resp = {
            "data": [
                {"id": "Qwen3.8-27B-Q4_K_M.gguf", "object": "model"},
                {"id": "deepseek-coder-6.7b.gguf", "object": "model"},
            ]
        }
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(mock_models_resp).encode("utf-8")
        mock_response.__enter__.return_value = mock_response

        with patch("urllib.request.urlopen", return_value=mock_response):
            models = adapter.discover_models(profile)
            assert "Qwen3.8-27B-Q4_K_M.gguf" in models
            assert "deepseek-coder-6.7b.gguf" in models

    def test_adapter_health_check(self):
        adapter = LocalLLMAdapter()
        profile = RouterProfileConfig(
            profile_id="local-1",
            provider="local",
            custom_base_url="http://127.0.0.1:8081/v1",
        )

        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.__enter__.return_value = mock_response

        with patch("urllib.request.urlopen", return_value=mock_response):
            assert adapter.health_check(profile) is True

        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("Connection refused")):
            assert adapter.health_check(profile) is False

    def test_model_discovery_service_local_probe(self):
        tmp_dir = tempfile.mkdtemp()
        try:
            cache_file = Path(tmp_dir) / "models_cache.json"
            service = ModelDiscoveryService(cache_path=cache_file)

            mock_models_resp = {
                "models": [
                    {"name": "local-qwen-27b"},
                    {"name": "local-mistral-7b"},
                ]
            }
            mock_response = MagicMock()
            mock_response.read.return_value = json.dumps(mock_models_resp).encode("utf-8")
            mock_response.__enter__.return_value = mock_response

            with patch("urllib.request.urlopen", return_value=mock_response):
                models = service.discover_models_sync("local")
                assert models is not None
                assert "local-qwen-27b" in models
                assert "local-mistral-7b" in models
                assert service.get_models("local") == sorted(["local-qwen-27b", "local-mistral-7b"])
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)


class TestLocalLLMConfigAndAutoAssigner:
    """Test default configuration, migration, and slot auto-assignment."""

    def test_default_config_clean_roles_and_local_registration(self):
        cfg = get_default_router_config()
        assert len(cfg.profiles) == 0
        assert len(cfg.roles) == 15

        slot = AutoAssigner.find_free_slot("local")
        assert slot == "local-1"

        reloaded = load_router_config()
        assert "local-1" in reloaded.profiles
        p1 = reloaded.profiles["local-1"]
        assert p1.provider == "local"
        assert "coding" in p1.capabilities

    def test_config_migration_preserves_user_profiles_without_injecting_stubs(self):
        tmp_dir = tempfile.mkdtemp()
        try:
            config_path = Path(tmp_dir) / "router_profiles.yaml"
            legacy_profiles = {
                "custom-codex": RouterProfileConfig(
                    profile_id="custom-codex",
                    provider="openai-codex",
                )
            }
            legacy_cfg = RouterConfig(
                enabled=True,
                default_role="manager",
                roles={"manager": get_default_router_config().roles["manager"]},
                profiles=legacy_profiles,
            )
            save_router_config(legacy_cfg, config_path)

            migrated = load_router_config(config_path)
            # User profile is preserved
            assert "custom-codex" in migrated.profiles
            # 15 canonical roles are migrated
            assert len(migrated.roles) == 15
            # No dummy local profiles injected
            assert "local-1" not in migrated.profiles
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def test_auto_assigner_find_free_slot_local(self):
        slot = AutoAssigner.find_free_slot("local")
        assert slot in ("local-1", "local-2")


class TestLocalLLMQuotaHonesty:
    """Test honest display of 'Без ограничений' for Local LLM quota."""

    def test_local_quota_snapshot_structure(self):
        snap = AccountQuotaService.get().fetch_account_quota("local", "local-1")
        assert snap is not None
        assert snap.is_loading is False
        assert snap.source in ("local_provider", "baseline")
        assert "Без ограничений" in (snap.unavailable_reason or "")

        assert len(snap.buckets) == 1
        bucket = snap.buckets[0]
        assert bucket.id == "local.unlimited"
        assert bucket.status == "unlimited"
        assert bucket.period == "unlimited"
        assert bucket.used_percent == 0.0
        assert bucket.remaining_percent == 100.0
        assert bucket.formatted_remaining() == "Без ограничений"


class TestProfileManagerLocalVerification:
    """Test ProfileAuthManager local endpoint verification and base_url synchronization."""

    def test_verify_local_endpoint_success(self):
        mock_data = {
            "data": [
                {"id": "qwen3.8-27b"},
                {"id": "deepseek-r1-distill"},
            ]
        }
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.read.return_value = json.dumps(mock_data).encode("utf-8")
        mock_response.__enter__.return_value = mock_response

        with patch("urllib.request.urlopen", return_value=mock_response):
            ok, dname, models, err = ProfileAuthManager.verify_local_endpoint(
                "http://127.0.0.1:8081/v1", api_key="my-key"
            )
            assert ok is True
            assert dname is not None and "127.0.0.1:8081" in dname
            assert "qwen3.8-27b" in models
            assert "deepseek-r1-distill" in models
            assert err is None

    def test_verify_local_endpoint_connection_refused(self):
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("Connection refused")):
            ok, dname, models, err = ProfileAuthManager.verify_local_endpoint("http://127.0.0.1:9999/v1")
            assert ok is False
            assert dname is None
            assert models == []
            assert err is not None
            assert "Connection refused" in err

    def test_save_profile_auth_syncs_custom_base_url(self):
        tmp_dir = tempfile.mkdtemp()
        try:
            config_path = Path(tmp_dir) / "router_profiles.yaml"
            save_router_config(get_default_router_config(), config_path)

            with patch.dict(os.environ, {"HERMES_ROUTER_CONFIG": str(config_path)}):
                auth_data = {
                    "provider": "local",
                    "profile_id": "local-1",
                    "base_url": "http://192.168.1.120:8000/v1",
                    "models": ["my-custom-model"],
                }
                ProfileAuthManager.save_profile_auth("local", "local-1", auth_data)

                # Verify custom_base_url synced in router_profiles.yaml
                reloaded = load_router_config(config_path)
                p1 = reloaded.get_profile("local-1")
                assert p1 is not None
                assert p1.custom_base_url == "http://192.168.1.120:8000/v1"
                assert p1.preferred_models == ["my-custom-model"]

                status = ProfileAuthManager.get_profile_status("local", "local-1")
                assert status["authenticated"] is True
                assert "192.168.1.120:8000" in status["account_id_masked"]
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)
