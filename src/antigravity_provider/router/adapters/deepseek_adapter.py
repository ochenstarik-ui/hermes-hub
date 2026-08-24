"""DeepSeek OpenAI-compatible provider adapter."""
from __future__ import annotations

import json
import logging
import os
import re
import urllib.error
import urllib.request
from typing import Any

from ..router_config import RouterProfileConfig
from .base_adapter import BaseProviderAdapter, ErrorCategory, ErrorClassification, extract_api_error_message

logger = logging.getLogger("hermes.router.adapter.deepseek")

DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"
DEFAULT_DEEPSEEK_MODELS = ["deepseek-chat", "deepseek-reasoner"]


class DeepSeekResponsesAdapter(BaseProviderAdapter):
    """Adapter for DeepSeek's OpenAI-compatible chat completions API."""

    def _resolve_api_key(self, profile: RouterProfileConfig) -> str | None:
        key = profile.auth_config.get("api_key") or profile.auth_config.get("token")
        if key:
            return str(key)

        suffix = profile.profile_id.upper().replace("-", "_")
        for candidate in (f"DEEPSEEK_API_KEY_{suffix}", "DEEPSEEK_API_KEY"):
            value = os.environ.get(candidate, "").strip()
            if value:
                return value
        return None

    def invoke(self, profile: RouterProfileConfig, request: dict[str, Any]) -> dict[str, Any]:
        api_key = self._resolve_api_key(profile)
        if not api_key:
            raise RuntimeError(f"No API key found for DeepSeek profile '{profile.profile_id}'")

        base_url = (
            profile.custom_base_url
            or os.environ.get("DEEPSEEK_BASE_URL", DEFAULT_DEEPSEEK_BASE_URL)
        ).rstrip("/")

        model = request.get("model", "")
        if not model or model == "default":
            model = profile.preferred_models[0] if profile.preferred_models else "deepseek-chat"

        payload: dict[str, Any] = {
            "model": model,
            "messages": request.get("messages", []),
            "temperature": request.get("temperature", 0.7),
        }
        if request.get("tools"):
            payload["tools"] = request["tools"]
        if "tool_choice" in request:
            payload["tool_choice"] = request["tool_choice"]
        if "response_format" in request:
            payload["response_format"] = request["response_format"]

        req = urllib.request.Request(
            f"{base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
                "User-Agent": "hermes-router/1.0",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                return json.loads(resp.read().decode("utf-8", errors="replace"))
        except urllib.error.HTTPError as http_err:
            raw_err = http_err.read().decode("utf-8", errors="replace")
            try:
                err_msg = extract_api_error_message(raw_err)
            except Exception:
                err_msg = raw_err
            raise RuntimeError(f"DeepSeek API Error ({http_err.code}): {err_msg}") from http_err
        except Exception as exc:
            raise RuntimeError(f"DeepSeek Transport Error: {exc}") from exc

    def health_check(self, profile: RouterProfileConfig) -> bool:
        return self._resolve_api_key(profile) is not None

    def discover_models(self, profile: RouterProfileConfig) -> list[str]:
        return list(profile.preferred_models or DEFAULT_DEEPSEEK_MODELS)

    def classify_error(
        self,
        exc: Exception,
        response_data: dict[str, Any] | None = None,
    ) -> ErrorClassification:
        err_msg = str(exc)
        err_lower = err_msg.lower()

        # Rate limits first: a 429 body routinely contains the word "limit",
        # which would otherwise be swallowed by the quota branch below.
        if "429" in err_lower or "rate limit" in err_lower or "too many requests" in err_lower:
            return ErrorClassification(
                category=ErrorCategory.RATE_LIMITED,
                message=err_msg,
                retry_delay_seconds=60,
            )

        if any(k in err_lower for k in ("quota", "insufficient balance", "insufficient_quota", "arrears")):
            reset_sec = 1800
            m_hr = re.search(r"(\d+)\s*(?:hours?|h\b)", err_lower)
            m_min = re.search(r"(\d+)\s*(?:minutes?|m\b)", err_lower)
            if m_hr:
                reset_sec = int(m_hr.group(1)) * 3600
            elif m_min:
                reset_sec = int(m_min.group(1)) * 60
            return ErrorClassification(
                category=ErrorCategory.QUOTA_EXHAUSTED,
                message=err_msg,
                reset_duration_seconds=reset_sec,
            )

        if any(k in err_lower for k in ("401", "403", "unauthorized", "invalid api key", "authentication")):
            return ErrorClassification(category=ErrorCategory.AUTH_REQUIRED, message=err_msg)

        if any(k in err_lower for k in ("timeout", "502", "503", "504", "gateway", "econnreset")):
            return ErrorClassification(
                category=ErrorCategory.TRANSIENT,
                message=err_msg,
                retry_delay_seconds=5,
            )

        return ErrorClassification(category=ErrorCategory.FATAL, message=err_msg)
