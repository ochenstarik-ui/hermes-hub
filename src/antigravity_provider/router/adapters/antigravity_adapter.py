"""Antigravity provider adapter with isolated per-profile agy environments."""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from ...agy_subprocess import (
    _find_agy_exe,
    agy_generate,
    discover_models,
)
from ..exceptions import (
    AuthExpiredError,
    AuthRequiredError,
    InvalidRequestError,
    ProviderUnavailableError,
    QuotaExceededError,
    RateLimitedError,
    RouterError,
)
from ..profile_manager import ProfileAuthManager, _CM_LOCK, get_profile_dir
from ..router_config import RouterProfileConfig
from .base_adapter import BaseProviderAdapter, ErrorCategory, ErrorClassification


def get_profile_env_dir(profile_id: str) -> Path:
    """Return isolated environment path for an agy profile."""
    return get_profile_dir(profile_id, "antigravity")


class AntigravityAdapter(BaseProviderAdapter):
    """Adapter for Google Antigravity using local agy CLI subprocess with isolated environments."""

    def invoke(self, profile: RouterProfileConfig, request: Dict[str, Any]) -> Dict[str, Any]:
        profile_dir = get_profile_env_dir(profile.profile_id)
        custom_env = dict(os.environ)
        # Isolate USERPROFILE and HOME so agy processes do not collide on locks or cache
        custom_env["USERPROFILE"] = str(profile_dir)
        custom_env["HOME"] = str(profile_dir)
        custom_env["HOMEPATH"] = str(profile_dir)

        # If profile specifies a preferred model and request has generic or no model
        req = dict(request)
        model = req.get("model", "")
        if (not model or model == "default" or "antigravity" not in model.lower()) and profile.preferred_models:
            req["model"] = profile.preferred_models[0]

        # Load profile-specific auth and swap into Windows Credential Manager if present
        profile_auth = ProfileAuthManager.load_profile_auth("antigravity", profile.profile_id)

        with _CM_LOCK:
            if profile_auth:
                ProfileAuthManager.write_windows_credential("gemini:antigravity", profile_auth)
            res = agy_generate(req, custom_env=custom_env)

        if isinstance(res, dict) and "error" in res:
            err_dict = res.get("error")
            err_msg = err_dict.get("message", "Antigravity provider error") if isinstance(err_dict, dict) else str(err_dict)
            err_lower = err_msg.lower()

            # 1. Auth errors
            if any(k in err_lower for k in ("auth", "401", "403", "expired", "token", "unauthorized", "login", "keychain")):
                raise AuthExpiredError(err_msg, provider="antigravity", profile_id=profile.profile_id)

            # 2. Rate limiting (Check BEFORE general quota so "429: rate limit exceeded" gets 60s cooldown)
            if any(k in err_lower for k in ("rate", "too many requests", "rate_limit")):
                raise RateLimitedError(err_msg, provider="antigravity", profile_id=profile.profile_id)

            # 3. Quota Exhaustion (Parse reset duration e.g. "resets in 2h")
            if any(k in err_lower for k in ("quota", "resource_exhausted", "429", "limit", "exhausted")):
                reset_sec = 1800
                m_hr = re.search(r"(\d+)\s*(?:hours?|h\b)", err_lower)
                m_min = re.search(r"(\d+)\s*(?:minutes?|m\b)", err_lower)
                m_sec = re.search(r"(\d+)\s*(?:seconds?|s\b)", err_lower)
                if m_hr:
                    reset_sec = int(m_hr.group(1)) * 3600
                elif m_min:
                    reset_sec = int(m_min.group(1)) * 60
                elif m_sec:
                    reset_sec = int(m_sec.group(1))

                raise QuotaExceededError(err_msg, provider="antigravity", profile_id=profile.profile_id, reset_in_sec=reset_sec)

            raise ProviderUnavailableError(err_msg, provider="antigravity", profile_id=profile.profile_id)

        return res

    def health_check(self, profile: RouterProfileConfig) -> bool:
        try:
            exe = _find_agy_exe()
            return bool(exe and Path(exe).is_file())
        except Exception:
            return False

    def discover_models(self, profile: RouterProfileConfig) -> List[str]:
        try:
            discovered = discover_models()
            if isinstance(discovered, dict) and discovered:
                return list(set(discovered.values()))
        except Exception:
            pass
        return list(profile.preferred_models or ["gemini-2.5-pro", "gemini-2.5-flash", "gemini-2.5-flash-thinking"])

    def classify_error(self, exc: Exception, response_data: Optional[Dict[str, Any]] = None) -> ErrorClassification:
        if isinstance(exc, QuotaExceededError):
            return ErrorClassification(
                category=ErrorCategory.QUOTA_EXHAUSTED,
                message=exc.message,
                reset_duration_seconds=exc.reset_in_sec or 1800,
            )
        if isinstance(exc, RateLimitedError):
            return ErrorClassification(
                category=ErrorCategory.RATE_LIMITED,
                message=exc.message,
                retry_delay_seconds=60,
            )
        if isinstance(exc, (AuthRequiredError, AuthExpiredError)):
            return ErrorClassification(
                category=ErrorCategory.AUTH_REQUIRED,
                message=exc.message,
            )
        if isinstance(exc, InvalidRequestError):
            return ErrorClassification(
                category=ErrorCategory.INVALID_REQUEST,
                message=exc.message,
            )

        err_msg = str(exc)
        if response_data and isinstance(response_data, dict):
            if "error" in response_data:
                err_msg = str(response_data["error"])

        err_lower = err_msg.lower()

        # Check for quota exhaustion
        if any(k in err_lower for k in ("individual quota reached", "resource_exhausted", "quota exhausted", "quota limit")):
            reset_sec = 1800
            m_sec = re.search(r"(\d+)\s*(?:seconds?|s\b)", err_lower)
            m_min = re.search(r"(\d+)\s*(?:minutes?|m\b)", err_lower)
            m_hr = re.search(r"(\d+)\s*(?:hours?|h\b)", err_lower)
            if m_hr:
                reset_sec = int(m_hr.group(1)) * 3600
            elif m_min:
                reset_sec = int(m_min.group(1)) * 60
            elif m_sec:
                reset_sec = int(m_sec.group(1))

            return ErrorClassification(
                category=ErrorCategory.QUOTA_EXHAUSTED,
                message=err_msg,
                reset_duration_seconds=reset_sec,
            )

        # Check for rate limits / 429
        if "429" in err_lower or "rate limit" in err_lower or "too many requests" in err_lower:
            return ErrorClassification(
                category=ErrorCategory.RATE_LIMITED,
                message=err_msg,
                retry_delay_seconds=60,
            )

        # Check for auth errors
        if any(k in err_lower for k in ("401", "403", "auth", "unauthorized", "forbidden", "token expired", "login required")):
            return ErrorClassification(
                category=ErrorCategory.AUTH_REQUIRED,
                message=err_msg,
            )

        return ErrorClassification(
            category=ErrorCategory.UNKNOWN,
            message=err_msg,
        )
