"""Anthropic Claude provider adapter for multi-provider router."""
from __future__ import annotations

import json
import logging
import os
import re
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

from ..router_config import RouterProfileConfig
from .base_adapter import BaseProviderAdapter, ErrorCategory, ErrorClassification

logger = logging.getLogger(__name__)

DEFAULT_CLAUDE_MODELS = [
    "claude-3-7-sonnet",
    "claude-3-5-sonnet",
    "claude-3-5-haiku",
    "claude-3-opus",
]


class ClaudeAdapter(BaseProviderAdapter):
    """Adapter for Anthropic Claude Messages API with multi-account isolation."""

    def __init__(self) -> None:
        self._auth_tokens: dict[str, str] = {}

    def _resolve_token(self, profile: RouterProfileConfig) -> Optional[str]:
        # 1. Profile auth_config token
        if "access_token" in profile.auth_config and profile.auth_config["access_token"]:
            return profile.auth_config["access_token"]
        if "api_key" in profile.auth_config and profile.auth_config["api_key"]:
            return profile.auth_config["api_key"]

        # 2. Check profile-specific storage (Multi-account isolation)
        try:
            from ..profile_manager import ProfileAuthManager
            creds = ProfileAuthManager.load_profile_auth("claude", profile.profile_id)
            if creds:
                if isinstance(creds.get("token"), dict) and creds["token"].get("access_token"):
                    return creds["token"]["access_token"]
                if isinstance(creds.get("tokens"), dict) and creds["tokens"].get("access_token"):
                    return creds["tokens"]["access_token"]
                if creds.get("access_token"):
                    return creds["access_token"]
                if creds.get("api_key"):
                    return creds["api_key"]
        except Exception:
            pass

        # 3. Environment variables
        env_var_name = f"CLAUDE_TOKEN_{profile.profile_id.upper().replace('-', '_')}"
        if env_var_name in os.environ and os.environ[env_var_name].strip():
            return os.environ[env_var_name].strip()

        for fallback_env in ("ANTHROPIC_API_KEY", "CLAUDE_API_KEY"):
            if fallback_env in os.environ and os.environ[fallback_env].strip():
                return os.environ[fallback_env].strip()

        return None

    def invoke(self, profile: RouterProfileConfig, request: Dict[str, Any]) -> Dict[str, Any]:
        token = self._resolve_token(profile)
        if not token:
            raise RuntimeError(f"No authentication token found for Claude profile '{profile.profile_id}'")

        base_url = profile.custom_base_url or os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com/v1").rstrip("/")
        url = f"{base_url}/messages"

        model = request.get("model", "")
        if not model or model == "default" or "antigravity" in model:
            model = profile.preferred_models[0] if profile.preferred_models else "claude-3-7-sonnet"

        payload = {
            "model": model,
            "messages": request.get("messages", []),
            "max_tokens": request.get("max_tokens", 4096),
            "temperature": request.get("temperature", 0.7),
        }
        if "system" in request and request["system"]:
            payload["system"] = request["system"]
        if "tools" in request and request["tools"]:
            payload["tools"] = request["tools"]

        headers = {
            "Content-Type": "application/json",
            "anthropic-version": "2023-06-01",
            "User-Agent": "hermes-router/1.0",
        }
        # OAuth vs API Key headers
        if token.startswith("sk-ant-"):
            headers["x-api-key"] = token
        else:
            headers["Authorization"] = f"Bearer {token}"
            headers["anthropic-beta"] = "oauth-2025-04-20"

        body_bytes = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=body_bytes, headers=headers, method="POST")

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
            raise RuntimeError(f"Claude API Error ({http_err.code}): {err_msg}") from http_err
        except Exception as e:
            raise RuntimeError(f"Claude Transport Error: {e}") from e

    def health_check(self, profile: RouterProfileConfig) -> bool:
        token = self._resolve_token(profile)
        return token is not None

    def discover_models(self, profile: RouterProfileConfig) -> List[str]:
        return list(profile.preferred_models or DEFAULT_CLAUDE_MODELS)

    def classify_error(self, exc: Exception, response_data: Optional[Dict[str, Any]] = None) -> ErrorClassification:
        err_msg = str(exc)
        err_lower = err_msg.lower()

        if any(k in err_lower for k in ("quota", "overloaded", "usage_limit", "credit", "rate_limit")):
            reset_sec = 1800
            m_sec = re.search(r"(\d+)\s*(?:seconds?|s\b)", err_lower)
            if m_sec:
                reset_sec = int(m_sec.group(1))
            return ErrorClassification(
                category=ErrorCategory.QUOTA_EXHAUSTED,
                message=err_msg,
                reset_duration_seconds=reset_sec,
                model_family="claude",
            )

        if "401" in err_lower or "403" in err_lower or "authentication" in err_lower or "invalid_api_key" in err_lower:
            return ErrorClassification(
                category=ErrorCategory.AUTH_REQUIRED,
                message=err_msg,
                model_family="claude",
            )

        return ErrorClassification(
            category=ErrorCategory.TRANSIENT,
            message=err_msg,
            model_family="claude",
        )
