"""Unit and integration tests for Task A39: Request options for local profiles.

Tests:
1. RouterProfileConfig schema, YAML serialization, and persistence across save/load.
2. LocalLLMAdapter payload merging with nested structures (e.g. chat_template_kwargs).
3. Precedence of explicit request parameters over request_options and warning logging.
4. Provider isolation: ensure non-local adapters never leak request_options.
5. Error parsing and classification for invalid/unknown parameters.
6. Action handler save_request_options execution.
7. Web UI contract in app.js for request options editor, live preview, and validation.
8. Clean codebase: absence of hardcoded parameter keys in adapter/router logic.
"""
from __future__ import annotations

import json
import logging
import pathlib
import tempfile
from unittest.mock import MagicMock, patch
import pytest

from antigravity_provider.router.adapters import get_adapter
from antigravity_provider.router.adapters.base_adapter import ErrorCategory
from antigravity_provider.router.adapters.local_adapter import LocalLLMAdapter
from antigravity_provider.router.router_config import (
    RouterConfig,
    RouterProfileConfig,
    load_router_config,
    save_router_config,
)
from antigravity_provider.router.action_handler import ActionExecutor, do_save_request_options
from antigravity_provider.router.unified_health import UnifiedHealthService


class TestProfileConfigAndPersistence:
    """Test RouterProfileConfig schema and YAML persistence."""

    def test_profile_config_defaults(self):
        pcfg = RouterProfileConfig(
            profile_id="local-test",
            provider="local",
        )
        assert pcfg.request_options == {}

    def test_profile_config_custom_options_and_nested_dict(self):
        options = {
            "chat_template_kwargs": {"enable_thinking": False},
            "seed": 42,
            "top_k": 40,
        }
        pcfg = RouterProfileConfig(
            profile_id="local-test",
            provider="local",
            request_options=options,
        )
        assert pcfg.request_options == options
        assert pcfg.request_options["chat_template_kwargs"]["enable_thinking"] is False

    def test_yaml_roundtrip_preserves_nested_request_options(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_path = pathlib.Path(tmpdir) / "router_profiles.yaml"
            cfg = RouterConfig(
                profiles={
                    "local-1": RouterProfileConfig(
                        profile_id="local-1",
                        provider="local",
                        preferred_models=["Qwen3.8-27B-Q4_K_M.gguf"],
                        request_options={
                            "chat_template_kwargs": {"enable_thinking": False},
                            "seed": 1234,
                            "custom_flag": True,
                        },
                    ),
                    "ag-w1": RouterProfileConfig(
                        profile_id="ag-w1",
                        provider="antigravity",
                        request_options={},
                    ),
                }
            )

            assert save_router_config(cfg, cfg_path)
            assert cfg_path.is_file()

            loaded = load_router_config(cfg_path)
            loaded_p = loaded.get_profile("local-1")
            assert loaded_p is not None
            assert loaded_p.request_options == {
                "chat_template_kwargs": {"enable_thinking": False},
                "seed": 1234,
                "custom_flag": True,
            }
            assert loaded_p.request_options["chat_template_kwargs"]["enable_thinking"] is False

            ag_p = loaded.get_profile("ag-w1")
            assert ag_p is not None
            assert ag_p.request_options == {}

    def test_unified_health_profile_view_model_includes_request_options(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_path = pathlib.Path(tmpdir) / "router_profiles.yaml"
            cfg = RouterConfig(
                profiles={
                    "local-1": RouterProfileConfig(
                        profile_id="local-1",
                        provider="local",
                        request_options={"chat_template_kwargs": {"enable_thinking": False}},
                    )
                }
            )
            save_router_config(cfg, cfg_path)

            with patch.dict("os.environ", {"HERMES_ROUTER_CONFIG": str(cfg_path)}):
                uh = UnifiedHealthService.get()
                profs = uh.scan_all(force=True)
                local_list = profs.get("local", [])
                matching = [p for p in local_list if p.profile_id == "local-1"]
                assert len(matching) == 1
                assert matching[0].request_options == {"chat_template_kwargs": {"enable_thinking": False}}


class TestLocalLLMAdapterRequestOptions:
    """Test LocalLLMAdapter.invoke merging of request_options and precedence handling."""

    def test_invoke_merges_nested_request_options_into_payload(self):
        adapter = LocalLLMAdapter()
        profile = RouterProfileConfig(
            profile_id="local-1",
            provider="local",
            custom_base_url="http://127.0.0.1:8081/v1",
            preferred_models=["Qwen3.8-27B-Q4_K_M.gguf"],
            request_options={
                "chat_template_kwargs": {"enable_thinking": False},
                "presence_penalty": 0.5,
            },
        )
        request = {
            "messages": [{"role": "user", "content": "Hello world"}],
            "max_tokens": 500,
        }

        mock_resp_data = {
            "id": "chatcmpl-1",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "Hello!"}, "finish_reason": "stop"}],
        }
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(mock_resp_data).encode("utf-8")
        mock_response.__enter__.return_value = mock_response

        with patch("urllib.request.urlopen", return_value=mock_response) as mock_urlopen:
            resp = adapter.invoke(profile, request)
            assert resp == mock_resp_data

            req_arg = mock_urlopen.call_args[0][0]
            payload = json.loads(req_arg.data.decode("utf-8"))

            assert payload["chat_template_kwargs"] == {"enable_thinking": False}
            assert payload["presence_penalty"] == 0.5
            assert payload["max_tokens"] == 500
            assert payload["messages"] == [{"role": "user", "content": "Hello world"}]
            assert payload["model"] == "Qwen3.8-27B-Q4_K_M.gguf"

    def test_explicit_request_parameters_override_request_options_and_log_warning(self, caplog):
        adapter = LocalLLMAdapter()
        profile = RouterProfileConfig(
            profile_id="local-1",
            provider="local",
            request_options={
                "max_tokens": 4096,
                "temperature": 0.1,
                "presence_penalty": 0.2,
            },
        )
        request = {
            "messages": [{"role": "user", "content": "test"}],
            "max_tokens": 1500,  # Explicit request parameter wins
            "temperature": 0.8,   # Explicit request parameter wins
        }

        mock_resp_data = {
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "OK"}, "finish_reason": "stop"}],
        }
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(mock_resp_data).encode("utf-8")
        mock_response.__enter__.return_value = mock_response

        with caplog.at_level(logging.WARNING):
            with patch("urllib.request.urlopen", return_value=mock_response) as mock_urlopen:
                adapter.invoke(profile, request)

                req_arg = mock_urlopen.call_args[0][0]
                payload = json.loads(req_arg.data.decode("utf-8"))

                assert payload["max_tokens"] == 1500
                assert payload["temperature"] == 0.8
                assert payload["presence_penalty"] == 0.2

        # Verify warnings logged for conflicts
        warnings = [record.message for record in caplog.records if record.levelno >= logging.WARNING]
        assert any("max_tokens" in w for w in warnings)
        assert any("temperature" in w for w in warnings)

    def test_temperature_from_request_options_used_when_request_omits_temperature(self):
        adapter = LocalLLMAdapter()
        profile = RouterProfileConfig(
            profile_id="local-1",
            provider="local",
            request_options={"temperature": 0.2},
        )
        request = {
            "messages": [{"role": "user", "content": "test"}],
        }

        mock_resp_data = {
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "OK"}, "finish_reason": "stop"}],
        }
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(mock_resp_data).encode("utf-8")
        mock_response.__enter__.return_value = mock_response

        with patch("urllib.request.urlopen", return_value=mock_response) as mock_urlopen:
            adapter.invoke(profile, request)
            req_arg = mock_urlopen.call_args[0][0]
            payload = json.loads(req_arg.data.decode("utf-8"))
            assert payload["temperature"] == 0.2


class TestProviderIsolation:
    """Verify other provider adapters never leak request_options."""

    @pytest.mark.parametrize(
        "provider_name",
        ["antigravity", "openai-codex", "claude", "grok", "opencode-go"],
    )
    def test_non_local_adapters_do_not_inject_arbitrary_request_options(self, provider_name):
        adapter = get_adapter(provider_name)
        assert not isinstance(adapter, LocalLLMAdapter)

        import inspect
        src = inspect.getsource(adapter.invoke)
        assert "request_options" not in src, f"{provider_name} adapter must not reference request_options"


class TestErrorHandlingAndClassification:
    """Test error parsing and error classification for local provider."""

    def test_unknown_parameter_http_400_raises_runtime_error_with_extracted_message(self):
        adapter = LocalLLMAdapter()
        profile = RouterProfileConfig(
            profile_id="local-1",
            provider="local",
            request_options={"invalid_param": 123},
        )
        request = {"messages": [{"role": "user", "content": "hi"}]}

        import io
        import urllib.error
        error_body = json.dumps({"error": {"message": "unknown parameter 'invalid_param'", "type": "invalid_request_error"}}).encode("utf-8")
        http_err = urllib.error.HTTPError("http://127.0.0.1:8081/v1/chat/completions", 400, "Bad Request", {}, io.BytesIO(error_body))

        with patch("urllib.request.urlopen", side_effect=http_err):
            with pytest.raises(RuntimeError) as exc_info:
                adapter.invoke(profile, request)

            err_str = str(exc_info.value)
            assert "Local LLM API Error (400)" in err_str
            assert "unknown parameter 'invalid_param'" in err_str

    def test_classify_error_for_invalid_request(self):
        adapter = LocalLLMAdapter()
        exc = RuntimeError("Local LLM API Error (400): unknown parameter 'foo'")
        classification = adapter.classify_error(exc)
        assert classification.category == ErrorCategory.INVALID_REQUEST
        assert "unknown parameter" in classification.message


class TestActionHandlerAndWebUI:
    """Test action execution and web client contracts for request_options."""

    def test_do_save_request_options(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_path = pathlib.Path(tmpdir) / "router_profiles.yaml"
            cfg = RouterConfig(
                profiles={
                    "local-1": RouterProfileConfig(
                        profile_id="local-1",
                        provider="local",
                        preferred_models=["default"],
                    )
                }
            )
            save_router_config(cfg, cfg_path)

            with patch.dict("os.environ", {"HERMES_ROUTER_CONFIG": str(cfg_path)}):
                ok, msg = do_save_request_options("local-1", {"chat_template_kwargs": {"enable_thinking": False}})
                assert ok is True
                assert "успешно сохранены" in msg

                # Verify persistence
                loaded = load_router_config(cfg_path)
                assert loaded.get_profile("local-1").request_options == {
                    "chat_template_kwargs": {"enable_thinking": False}
                }

    def test_action_executor_save_request_options(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_path = pathlib.Path(tmpdir) / "router_profiles.yaml"
            cfg = RouterConfig(
                profiles={
                    "local-1": RouterProfileConfig(
                        profile_id="local-1",
                        provider="local",
                    )
                }
            )
            save_router_config(cfg, cfg_path)

            with patch.dict("os.environ", {"HERMES_ROUTER_CONFIG": str(cfg_path)}):
                res = ActionExecutor.execute(
                    "save_request_options",
                    {
                        "profile_id": "local-1",
                        "request_options": {"chat_template_kwargs": {"enable_thinking": False}},
                    },
                )
                assert res.get("ok") is True

    def test_action_executor_invalid_json_fails_gracefully(self):
        ok, msg = do_save_request_options("local-1", "{invalid json...")
        assert ok is False
        assert "Некорректный JSON" in msg

    def test_app_js_contains_request_options_modal_and_validation(self):
        app_js = pathlib.Path("src/antigravity_provider/router/web/static/app.js").read_text(encoding="utf-8")
        assert "modal-request-options-input" in app_js
        assert "updateRequestOptionsPreview" in app_js
        assert "handleSaveRequestOptions" in app_js
        assert "modal-payload-preview-content" in app_js
        assert "save_request_options" in app_js
        assert "openAccountDetailsModal" in app_js


class TestNoHardcodedConstants:
    """Verify neither enable_thinking nor reasoning_effort is hardcoded in local adapter or router config logic."""

    def test_no_hardcoded_keys_in_local_adapter_and_router_config(self):
        src_files = [
            pathlib.Path("src/antigravity_provider/router/adapters/local_adapter.py"),
            pathlib.Path("src/antigravity_provider/router/router_config.py"),
            pathlib.Path("src/antigravity_provider/router/action_handler.py"),
        ]
        for py_file in src_files:
            text = py_file.read_text(encoding="utf-8")
            lines = text.splitlines()
            for idx, line in enumerate(lines, 1):
                clean = line.strip()
                if clean.startswith("#"):
                    continue
                assert "enable_thinking" not in clean, f"Hardcoded enable_thinking found in {py_file.name}:{idx}: {line}"
                assert "reasoning_effort" not in clean, f"Hardcoded reasoning_effort found in {py_file.name}:{idx}: {line}"
