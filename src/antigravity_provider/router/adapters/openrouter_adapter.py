"""OpenRouter OpenAI-compatible provider adapter."""
from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

from ..router_config import RouterProfileConfig
from .base_adapter import BaseProviderAdapter, ErrorCategory, ErrorClassification, extract_api_error_message

logger = logging.getLogger("hermes.router.adapter.openrouter")

DEFAULT_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


class OpenRouterAdapter(BaseProviderAdapter):
    """Adapter for OpenRouter's OpenAI-compatible chat completions API."""

    _models_metadata: Dict[str, Dict[str, Any]] = {}
    _context_window_cache: Dict[str, int] = {}

    def _resolve_base_url(self, profile: RouterProfileConfig) -> str:
        """Resolve base_url from profile custom_base_url, auth_config, or default."""
        url = (
            profile.custom_base_url
            or profile.auth_config.get("base_url")
            or os.environ.get("OPENROUTER_BASE_URL")
            or DEFAULT_OPENROUTER_BASE_URL
        )
        url_str = str(url).strip().rstrip("/")
        if not url_str.startswith(("http://", "https://")):
            url_str = f"https://{url_str}"
        return url_str

    def _resolve_api_key(self, profile: RouterProfileConfig) -> Optional[str]:
        """Resolve API key from profile auth_config or environment."""
        key = profile.auth_config.get("api_key") or profile.auth_config.get("token")
        if key:
            return str(key).strip()

        # Ключ, введённый в мастере, сохраняется через ProfileAuthManager, а не в
        # auth_config из router_profiles.yaml. Адаптер читал только второе место и
        # уходил без заголовка Authorization: провайдер отвечал 401 «Header of type
        # authorization was missing», хотя список моделей тем же ключом получался.
        try:
            from antigravity_provider.router.profile_manager import ProfileAuthManager

            stored = ProfileAuthManager.load_profile_auth(profile.provider, profile.profile_id) or {}
            key = stored.get("api_key") or stored.get("token")
            if key:
                return str(key).strip()
        except Exception:
            pass

        suffix = profile.profile_id.upper().replace("-", "_")
        for candidate in (f"OPENROUTER_API_KEY_{suffix}", "OPENROUTER_API_KEY"):
            val = os.environ.get(candidate, "").strip()
            if val:
                return val
        return None

    def _build_headers(self, api_key: Optional[str] = None) -> Dict[str, str]:
        """Build standard headers with OpenRouter attribution headers."""
        referer = (
            os.environ.get("OPENROUTER_HTTP_REFERER")
            or os.environ.get("HERMES_REFERER")
            or "https://github.com/ochenstarik-ui/hermes-hub"
        )
        title = (
            os.environ.get("OPENROUTER_APP_TITLE")
            or os.environ.get("OPENROUTER_TITLE")
            or "Hermes Hub"
        )
        headers: Dict[str, str] = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "hermes-router/1.0",
            "HTTP-Referer": referer,
            "X-OpenRouter-Title": title,
        }
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        return headers

    def get_context_window(
        self,
        profile: RouterProfileConfig,
        model: Optional[str] = None,
    ) -> Optional[int]:
        """Fetch actual context_window / max_context_length from profile or discovery cache."""
        cache_key = f"{profile.profile_id}:{model or 'default'}"
        if cache_key in self._context_window_cache:
            return self._context_window_cache[cache_key]
        if model and model in self._context_window_cache:
            return self._context_window_cache[model]
        return None

    def get_model_metadata(self, model_id: str) -> Optional[Dict[str, Any]]:
        """Return cached metadata for model ID if available."""
        return self._models_metadata.get(model_id)

    def invoke(self, profile: RouterProfileConfig, request: Dict[str, Any]) -> Dict[str, Any]:
        base_url = self._resolve_base_url(profile)
        api_key = self._resolve_api_key(profile)

        model = request.get("model", "")
        if not model or model == "default":
            model = profile.preferred_models[0] if profile.preferred_models else "default"

        payload: Dict[str, Any] = {
            "model": model,
            "messages": list(request.get("messages", [])),
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

        headers = self._build_headers(api_key)

        req = urllib.request.Request(
            f"{base_url}/chat/completions",
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
            raise RuntimeError(f"OpenRouter API Error ({http_err.code}): {err_msg}") from http_err
        except Exception as exc:
            raise RuntimeError(f"OpenRouter Transport Error: {exc}") from exc

        self._reject_empty_answer(data)
        return data

    @staticmethod
    def _reject_empty_answer(data: Dict[str, Any]) -> None:
        """Пустой ответ — это отказ, а не успех."""
        choices = data.get("choices") or []
        if not choices:
            raise RuntimeError("OpenRouter вернул ответ без choices")

        message = choices[0].get("message") or {}
        content = (message.get("content") or "").strip()
        if content:
            return

        finish = choices[0].get("finish_reason")
        raise RuntimeError(f"OpenRouter вернул пустой ответ (finish_reason={finish})")

    def discover_models(self, profile: RouterProfileConfig) -> List[str]:
        """Request GET {base_url}/models and return the server's model list.

        Extracts context_length and display_name metadata when provided by the API.
        No invented/hardcoded model list: on error, fall back to profile.preferred_models.
        """
        base_url = self._resolve_base_url(profile)
        api_key = self._resolve_api_key(profile)
        headers = self._build_headers(api_key)

        req = urllib.request.Request(
            f"{base_url}/models",
            headers=headers,
            method="GET",
        )

        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="replace"))
                items = data.get("data") or data.get("models") or []
                if isinstance(items, list) and items:
                    models = []
                    for m in items:
                        if isinstance(m, dict):
                            m_id = str(m.get("id") or m.get("name") or "")
                            if not m_id:
                                continue
                            display_name = str(m.get("name") or m.get("display_name") or m_id)
                            ctx_len = m.get("context_length") or m.get("context_window") or m.get("max_context_length")
                            meta: Dict[str, Any] = {
                                "id": m_id,
                                "display_name": display_name,
                            }
                            if ctx_len is not None:
                                try:
                                    val = int(ctx_len)
                                    meta["context_length"] = val
                                    self._context_window_cache[f"{profile.profile_id}:{m_id}"] = val
                                    self._context_window_cache[m_id] = val
                                except (ValueError, TypeError):
                                    pass
                            self._models_metadata[m_id] = meta
                            models.append(m_id)
                        elif isinstance(m, str) and m:
                            models.append(m)
                    if models:
                        return sorted(set(models))
        except Exception as exc:
            logger.debug("Failed to discover models for openrouter profile %s: %s", profile.profile_id, exc)

        return list(profile.preferred_models or [])

    def health_check(self, profile: RouterProfileConfig) -> bool:
        """Fast GET {base_url}/models probe. Returns True on success, False on error."""
        base_url = self._resolve_base_url(profile)
        api_key = self._resolve_api_key(profile)
        headers = self._build_headers(api_key)

        req = urllib.request.Request(
            f"{base_url}/models",
            headers=headers,
            method="GET",
        )

        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status in (200, 204)
        except Exception:
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
