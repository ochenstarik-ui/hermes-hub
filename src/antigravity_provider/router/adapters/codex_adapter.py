"""OpenAI Codex provider adapter for multi-provider router."""
from __future__ import annotations

import json
import logging
import os
import re
import urllib.request
import urllib.error
from typing import Any, Dict, List, Optional

from ..router_config import RouterProfileConfig
from .base_adapter import BaseProviderAdapter, ErrorCategory, ErrorClassification

logger = logging.getLogger(__name__)

DEFAULT_CODEX_MODELS = ["gpt-4o", "o3-mini", "gpt-4o-mini", "codex"]


class CodexAdapter(BaseProviderAdapter):
    """Adapter for OpenAI Codex / Responses API with multi-account isolation."""

    def __init__(self) -> None:
        self._auth_tokens: dict[str, str] = {}

    def _resolve_token(self, profile: RouterProfileConfig) -> Optional[str]:
        # 1. Profile auth_config token
        if "access_token" in profile.auth_config:
            return profile.auth_config["access_token"]
        if "api_key" in profile.auth_config:
            return profile.auth_config["api_key"]

        # 2. Check environment variable mapped to this account
        env_var_name = f"CODEX_TOKEN_{profile.profile_id.upper().replace('-', '_')}"
        if env_var_name in os.environ and os.environ[env_var_name].strip():
            return os.environ[env_var_name].strip()

        # 3. Check general CODEX / OPENAI keys
        for fallback_env in ("CODEX_API_KEY", "OPENAI_API_KEY"):
            if fallback_env in os.environ and os.environ[fallback_env].strip():
                return os.environ[fallback_env].strip()

        # 4. Check Hermes auth.json store
        try:
            from hermes_cli.auth import resolve_codex_runtime_credentials
            creds = resolve_codex_runtime_credentials()
            if creds and creds.get("api_key"):
                return creds["api_key"]
        except Exception:
            pass

        return None

    def invoke(self, profile: RouterProfileConfig, request: Dict[str, Any]) -> Dict[str, Any]:
        token = self._resolve_token(profile)
        if not token:
            raise RuntimeError(f"No authentication token found for Codex profile '{profile.profile_id}'")

        base_url = profile.custom_base_url or os.environ.get("CODEX_BASE_URL", "https://api.openai.com/v1").rstrip("/")
        url = f"{base_url}/chat/completions"

        # Model selection
        model = request.get("model", "")
        if not model or model == "default" or "antigravity" in model:
            model = profile.preferred_models[0] if profile.preferred_models else "gpt-4o"

        payload = {
            "model": model,
            "messages": request.get("messages", []),
            "temperature": request.get("temperature", 0.7),
        }
        if "tools" in request and request["tools"]:
            payload["tools"] = request["tools"]
        if "tool_choice" in request:
            payload["tool_choice"] = request["tool_choice"]

        body_bytes = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=body_bytes,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {token}",
                "User-Agent": "hermes-router/1.0",
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
            err_msg = err_json.get("error", {}).get("message", raw_err)
            raise RuntimeError(f"Codex API Error ({http_err.code}): {err_msg}") from http_err
        except Exception as e:
            raise RuntimeError(f"Codex Transport Error: {e}") from e

    def health_check(self, profile: RouterProfileConfig) -> bool:
        token = self._resolve_token(profile)
        return token is not None

    def discover_models(self, profile: RouterProfileConfig) -> List[str]:
        return list(profile.preferred_models or DEFAULT_CODEX_MODELS)

    def classify_error(self, exc: Exception, response_data: Optional[Dict[str, Any]] = None) -> ErrorClassification:
        err_msg = str(exc)
        err_lower = err_msg.lower()

        # Quota / usage limit
        if any(k in err_lower for k in ("quota", "insufficient_quota", "usage_limit", "exceeded your current quota")):
            reset_sec = 1800
            m_sec = re.search(r"(\d+)\s*(?:seconds?|s\b)", err_lower)
            if m_sec:
                reset_sec = int(m_sec.group(1))
            return ErrorClassification(
                category=ErrorCategory.QUOTA_EXHAUSTED,
                message=err_msg,
                reset_duration_seconds=reset_sec,
            )

        # Rate limited (429)
        if "429" in err_lower or "rate limit" in err_lower or "tokens per min" in err_lower:
            return ErrorClassification(
                category=ErrorCategory.RATE_LIMITED,
                message=err_msg,
                retry_delay_seconds=60,
            )

        # Auth errors
        if any(k in err_lower for k in ("401", "unauthorized", "invalid_api_key", "token_invalidated", "token_revoked")):
            return ErrorClassification(
                category=ErrorCategory.AUTH_REQUIRED,
                message=err_msg,
            )

        # Transient
        if any(k in err_lower for k in ("timeout", "502", "503", "504", "connection reset")):
            return ErrorClassification(
                category=ErrorCategory.TRANSIENT,
                message=err_msg,
                retry_delay_seconds=5,
            )

        return ErrorClassification(
            category=ErrorCategory.FATAL,
            message=err_msg,
        )
