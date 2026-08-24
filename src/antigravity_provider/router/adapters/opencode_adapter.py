"""OpenCode Go provider adapter for multi-provider router."""
from __future__ import annotations

import json
import logging
import os
import re
import urllib.request
import urllib.error
from typing import Any, Dict, List, Optional

from ..router_config import RouterProfileConfig
from .base_adapter import BaseProviderAdapter, ErrorCategory, ErrorClassification, extract_api_error_message

logger = logging.getLogger(__name__)

DEFAULT_OPENCODE_GO_BASE_URL = "https://opencode.ai/zen/go/v1"
DEFAULT_OPENCODE_MODELS = [
    "kimi-k2.7-code",
    "deepseek-v4-pro",
    "deepseek-v4-flash",
    "qwen3.8-max",
    "qwen3.7-max",
    "qwen3.7-plus",
    "grok-4.5",
    "glm-5.3",
    "mimo-v2.5-pro",
    "minimax-m3",
]


class OpenCodeGoAdapter(BaseProviderAdapter):
    """Adapter for OpenCode Go with support for multi-account key pools and reasoning knobs."""

    def _resolve_api_key(self, profile: RouterProfileConfig) -> Optional[str]:
        # 1. Profile explicit auth_config
        if "api_key" in profile.auth_config and profile.auth_config["api_key"]:
            return profile.auth_config["api_key"]

        # 2. Профиль в хранилище учётных данных.
        # Мастер подключения сохраняет ключ именно сюда, а адаптер его не читал:
        # смотрел только YAML-конфиг и переменные окружения. Из-за этого любой
        # аккаунт OpenCode, подключённый через интерфейс, не работал никогда —
        # маршрутизация падала с «No API key found», хотя ключ лежал на диске.
        # Остальные адаптеры (grok, claude, codex) читают профиль; этот — нет.
        try:
            from ..profile_manager import ProfileAuthManager

            creds = ProfileAuthManager.load_profile_auth("opencode-go", profile.profile_id)
            if creds:
                for key in ("api_key", "access_token", "token"):
                    value = creds.get(key)
                    if isinstance(value, dict):
                        value = value.get("api_key") or value.get("access_token")
                    if isinstance(value, str) and value.strip():
                        return value.strip()
        except Exception:
            pass

        # 3. Account-specific environment variable (e.g. OPENCODE_GO_KEY_OPENGO_1, OPENCODE_GO_KEY_1)
        suffix = profile.profile_id.upper().replace("-", "_")
        for candidate in (
            f"OPENCODE_GO_KEY_{suffix}",
            f"OPENCODE_KEY_{suffix}",
            f"OPENCODE_GO_API_KEY_{suffix}",
        ):
            if candidate in os.environ and os.environ[candidate].strip():
                return os.environ[candidate].strip()

        # Account ID mapped env
        acc_suffix = profile.account_id.upper().replace("-", "_")
        for candidate in (
            f"OPENCODE_GO_KEY_{acc_suffix}",
            f"OPENCODE_KEY_{acc_suffix}",
        ):
            if candidate in os.environ and os.environ[candidate].strip():
                return os.environ[candidate].strip()

        # 4. Global OpenCode Go keys
        for global_env in ("OPENCODE_GO_API_KEY", "OPENCODE_ZEN_API_KEY", "OPENCODE_API_KEY"):
            if global_env in os.environ and os.environ[global_env].strip():
                return os.environ[global_env].strip()

        return None

    def _build_model_kwargs(self, model: str, request: Dict[str, Any]) -> tuple[dict, dict]:
        """Format reasoning_effort and extra_body thinking based on OpenCode model policies."""
        extra_body: dict[str, Any] = {}
        top_level: dict[str, Any] = {}

        effort = request.get("reasoning_effort")

        if "kimi" in model.lower():
            if effort in ("low", "medium", "high"):
                top_level["reasoning_effort"] = effort
            elif effort in ("xhigh", "max", "ultra"):
                top_level["reasoning_effort"] = "high"
            else:
                extra_body["thinking"] = {"type": "enabled"}
        elif "deepseek" in model.lower():
            if effort in ("xhigh", "max", "ultra"):
                top_level["reasoning_effort"] = "max"
            elif effort in ("low", "medium", "high"):
                top_level["reasoning_effort"] = effort
            else:
                extra_body["thinking"] = {"type": "enabled"}
        elif "glm" in model.lower():
            if effort:
                top_level["reasoning_effort"] = "max" if effort in ("xhigh", "max") else "high"

        return extra_body, top_level

    def invoke(self, profile: RouterProfileConfig, request: Dict[str, Any]) -> Dict[str, Any]:
        api_key = self._resolve_api_key(profile)
        if not api_key:
            raise RuntimeError(f"No API key found for OpenCode Go profile '{profile.profile_id}'")

        base_url = (profile.custom_base_url or os.environ.get("OPENCODE_GO_BASE_URL", DEFAULT_OPENCODE_GO_BASE_URL)).rstrip("/")
        url = f"{base_url}/chat/completions"

        # Model selection
        model = request.get("model", "")
        if not model or model == "default" or "antigravity" in model:
            model = profile.preferred_models[0] if profile.preferred_models else "kimi-k2.7-code"

        extra_body, top_level = self._build_model_kwargs(model, request)

        payload: dict[str, Any] = {
            "model": model,
            "messages": request.get("messages", []),
            "temperature": request.get("temperature", 0.6),
        }
        if "tools" in request and request["tools"]:
            payload["tools"] = request["tools"]
        if "tool_choice" in request:
            payload["tool_choice"] = request["tool_choice"]
        if extra_body:
            payload["extra_body"] = extra_body
        payload.update(top_level)

        body_bytes = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=body_bytes,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
                "User-Agent": "hermes-router/1.0",
                "X-OpenCode-Source": "hermes-agent",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                resp_bytes = resp.read()
                return json.loads(resp_bytes.decode("utf-8", errors="replace"))
        except urllib.error.HTTPError as http_err:
            raw_err = http_err.read().decode("utf-8", errors="replace")
            try:
                err_json = json.loads(raw_err)
            except Exception:
                err_json = {"error": {"message": raw_err}}
            err_msg = extract_api_error_message(raw_err)
            raise RuntimeError(f"OpenCode Go Error ({http_err.code}): {err_msg}") from http_err
        except Exception as e:
            raise RuntimeError(f"OpenCode Go Transport Error: {e}") from e

    def health_check(self, profile: RouterProfileConfig) -> bool:
        return self._resolve_api_key(profile) is not None

    def discover_models(self, profile: RouterProfileConfig) -> List[str]:
        return list(profile.preferred_models or DEFAULT_OPENCODE_MODELS)

    def classify_error(self, exc: Exception, response_data: Optional[Dict[str, Any]] = None) -> ErrorClassification:
        err_msg = str(exc)
        err_lower = err_msg.lower()

        # Quota / balance
        if any(k in err_lower for k in ("quota", "insufficient_quota", "insufficient balance", "balance", "arrears")):
            return ErrorClassification(
                category=ErrorCategory.QUOTA_EXHAUSTED,
                message=err_msg,
                reset_duration_seconds=1800,
            )

        # Rate limited (429)
        if "429" in err_lower or "rate limit" in err_lower or "too many requests" in err_lower:
            return ErrorClassification(
                category=ErrorCategory.RATE_LIMITED,
                message=err_msg,
                retry_delay_seconds=60,
            )

        # Auth errors (401, 403)
        if any(k in err_lower for k in ("401", "403", "unauthorized", "invalid api key", "invalid_token")):
            return ErrorClassification(
                category=ErrorCategory.AUTH_REQUIRED,
                message=err_msg,
            )

        # Transient
        if any(k in err_lower for k in ("timeout", "502", "503", "504", "gateway", "econnreset")):
            return ErrorClassification(
                category=ErrorCategory.TRANSIENT,
                message=err_msg,
                retry_delay_seconds=5,
            )

        return ErrorClassification(
            category=ErrorCategory.FATAL,
            message=err_msg,
        )
