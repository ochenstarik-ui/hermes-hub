"""Ollama OpenAI-compatible and native API provider adapter."""
from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

from ..router_config import RouterProfileConfig
from .base_adapter import ErrorCategory, ErrorClassification, extract_api_error_message
from .local_adapter import LocalLLMAdapter

logger = logging.getLogger("hermes.router.adapter.ollama")

DEFAULT_OLLAMA_BASE_URL = "http://127.0.0.1:11434/v1"
DEFAULT_OLLAMA_MODELS = ["llama3:latest"]


class OllamaAdapter(LocalLLMAdapter):
    """Adapter for local and remote Ollama LLM servers.

    Supports both OpenAI-compatible endpoints (/v1/chat/completions, /v1/models)
    and native Ollama endpoints (/api/tags).
    """

    def _resolve_base_url(self, profile: RouterProfileConfig) -> str:
        """Resolve base_url from profile custom_base_url, auth_config, or environment."""
        url = (
            profile.custom_base_url
            or profile.auth_config.get("base_url")
            or os.environ.get("OLLAMA_BASE_URL")
            or os.environ.get("OLLAMA_HOST")
            or DEFAULT_OLLAMA_BASE_URL
        )
        url_str = str(url).strip().rstrip("/")
        if not url_str.startswith(("http://", "https://")):
            url_str = f"http://{url_str}"
        return url_str

    def _resolve_api_key(self, profile: RouterProfileConfig) -> Optional[str]:
        """Resolve optional API key from profile auth_config or environment."""
        key = profile.auth_config.get("api_key") or profile.auth_config.get("token")
        if key:
            return str(key).strip()

        suffix = profile.profile_id.upper().replace("-", "_")
        for candidate in (f"OLLAMA_API_KEY_{suffix}", "OLLAMA_API_KEY", "OLLAMA_TOKEN"):
            val = os.environ.get(candidate, "").strip()
            if val:
                return val
        return None

    def _get_native_host(self, base_url: str) -> str:
        """Strip trailing /v1 from base_url to get native Ollama host."""
        if base_url.endswith("/v1"):
            return base_url[:-3]
        return base_url

    def _get_chat_url(self, base_url: str) -> str:
        """Get standard chat completions endpoint URL."""
        if base_url.endswith("/v1"):
            return f"{base_url}/chat/completions"
        return f"{base_url}/v1/chat/completions"

    def _get_models_url(self, base_url: str) -> str:
        """Get OpenAI-compatible models endpoint URL."""
        if base_url.endswith("/v1"):
            return f"{base_url}/models"
        return f"{base_url}/v1/models"

    def invoke(self, profile: RouterProfileConfig, request: Dict[str, Any]) -> Dict[str, Any]:
        base_url = self._resolve_base_url(profile)
        api_key = self._resolve_api_key(profile)
        chat_url = self._get_chat_url(base_url)

        model = request.get("model", "")
        if not model or model == "default":
            model = profile.preferred_models[0] if profile.preferred_models else "llama3:latest"

        messages = list(request.get("messages", []))

        payload: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": request.get("temperature", 0.7),
        }
        if "tools" in request and request["tools"]:
            payload["tools"] = request["tools"]
        if "tool_choice" in request:
            payload["tool_choice"] = request["tool_choice"]
        if "response_format" in request:
            payload["response_format"] = request["response_format"]
        if "max_tokens" in request:
            payload["max_tokens"] = request["max_tokens"]
        if "stream" in request:
            payload["stream"] = request["stream"]
        if "stop" in request:
            payload["stop"] = request["stop"]

        headers: Dict[str, str] = {
            "Content-Type": "application/json",
            "User-Agent": "hermes-router/1.0",
        }
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        req = urllib.request.Request(
            chat_url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="replace"))
        except urllib.error.HTTPError as http_err:
            raw_err = http_err.read().decode("utf-8", errors="replace")
            try:
                err_msg = extract_api_error_message(raw_err)
            except Exception:
                err_msg = raw_err
            raise RuntimeError(f"Ollama API Error ({http_err.code}): {err_msg}") from http_err
        except Exception as exc:
            raise RuntimeError(f"Ollama Transport Error: {exc}") from exc

        self._reject_empty_answer(data)
        return data

    @staticmethod
    def _reject_empty_answer(data: Dict[str, Any]) -> None:
        """Reject empty completion responses."""
        choices = data.get("choices") or []
        if not choices:
            raise RuntimeError("Ollama вернул ответ без choices")

        message = choices[0].get("message") or {}
        content = (message.get("content") or "").strip()
        if content:
            return

        finish = choices[0].get("finish_reason")
        if message.get("reasoning_content"):
            raise RuntimeError(
                "Ollama израсходовал лимит токенов на рассуждения и не выдал ответ "
                f"(finish_reason={finish})."
            )
        raise RuntimeError(f"Ollama вернул пустой ответ (finish_reason={finish})")

    def discover_models(self, profile: RouterProfileConfig) -> List[str]:
        """Discover models via GET {base_url}/models or GET {host}/api/tags."""
        base_url = self._resolve_base_url(profile)
        api_key = self._resolve_api_key(profile)

        headers: Dict[str, str] = {
            "Accept": "application/json",
            "User-Agent": "hermes-router/1.0",
        }
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        # 1. Try OpenAI-compatible /models endpoint
        models_url = self._get_models_url(base_url)
        try:
            req = urllib.request.Request(models_url, headers=headers, method="GET")
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="replace"))
                items = data.get("data") or data.get("models") or []
                if isinstance(items, list) and items:
                    models = [
                        str(m.get("id") or m.get("name") if isinstance(m, dict) else m)
                        for m in items
                        if m
                    ]
                    if models:
                        return sorted(set(models))
        except Exception as exc:
            logger.debug("Ollama /models discovery failed for %s: %s", profile.profile_id, exc)

        # 2. Try native Ollama /api/tags endpoint
        native_host = self._get_native_host(base_url)
        try:
            tags_url = f"{native_host}/api/tags"
            req = urllib.request.Request(tags_url, headers=headers, method="GET")
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="replace"))
                items = data.get("models") or []
                if isinstance(items, list) and items:
                    models = [
                        str(m.get("name") or m.get("model") if isinstance(m, dict) else m)
                        for m in items
                        if m
                    ]
                    if models:
                        return sorted(set(models))
        except Exception as exc:
            logger.debug("Ollama /api/tags discovery failed for %s: %s", profile.profile_id, exc)

        return list(profile.preferred_models or DEFAULT_OLLAMA_MODELS)

    def health_check(self, profile: RouterProfileConfig) -> bool:
        """Probe /models or /api/tags endpoint. Returns True on success, False on error."""
        base_url = self._resolve_base_url(profile)
        api_key = self._resolve_api_key(profile)

        headers: Dict[str, str] = {
            "Accept": "application/json",
            "User-Agent": "hermes-router/1.0",
        }
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        # 1. Probe /models
        models_url = self._get_models_url(base_url)
        try:
            req = urllib.request.Request(models_url, headers=headers, method="GET")
            with urllib.request.urlopen(req, timeout=3) as resp:
                if resp.status in (200, 204):
                    return True
        except Exception:
            pass

        # 2. Probe /api/tags
        native_host = self._get_native_host(base_url)
        try:
            tags_url = f"{native_host}/api/tags"
            req = urllib.request.Request(tags_url, headers=headers, method="GET")
            with urllib.request.urlopen(req, timeout=3) as resp:
                if resp.status in (200, 204):
                    return True
        except Exception:
            pass

        return False

    def classify_error(
        self,
        exc: Exception,
        response_data: Optional[Dict[str, Any]] = None,
    ) -> ErrorClassification:
        """Classify execution failure into structured error category."""
        err_msg = str(exc)
        err_lower = err_msg.lower()

        if "429" in err_lower or "rate limit" in err_lower or "too many requests" in err_lower:
            return ErrorClassification(
                category=ErrorCategory.RATE_LIMITED,
                message=err_msg,
                retry_delay_seconds=30,
            )

        if any(k in err_lower for k in ("401", "403", "unauthorized", "forbidden", "invalid api key", "authentication")):
            return ErrorClassification(
                category=ErrorCategory.AUTH_REQUIRED,
                message=err_msg,
            )

        if any(k in err_lower for k in ("quota", "insufficient balance", "insufficient_quota")):
            return ErrorClassification(
                category=ErrorCategory.QUOTA_EXHAUSTED,
                message=err_msg,
                reset_duration_seconds=1800,
            )

        if any(k in err_lower for k in (
            "connection refused", "connection error", "connect", "refused",
            "timeout", "timed out", "502", "503", "504", "gateway",
            "econnrefused", "econnreset", "transport error", "urlerror",
            "winerror 10061", "nodename nor servname provided",
        )):
            return ErrorClassification(
                category=ErrorCategory.TRANSIENT,
                message=err_msg,
                retry_delay_seconds=2,
            )

        return ErrorClassification(category=ErrorCategory.TRANSIENT, message=err_msg, retry_delay_seconds=2)
