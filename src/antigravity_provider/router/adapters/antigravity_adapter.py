"""Antigravity provider adapter with isolated per-profile agy environments."""
from __future__ import annotations

import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from ...agy_subprocess import (
    _find_agy_exe,
    agy_generate,
    build_safe_subprocess_env,
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


import threading

_AGY_INVOCATION_LOCK = threading.RLock()


def get_profile_env_dir(profile_id: str) -> Path:
    """Return isolated environment path for an agy profile."""
    return get_profile_dir(profile_id, "antigravity")


class AntigravityAdapter(BaseProviderAdapter):
    """Adapter for Google Antigravity using local agy CLI subprocess with isolated environments."""

    def invoke(self, profile: RouterProfileConfig, request: Dict[str, Any]) -> Dict[str, Any]:
        profile_dir = get_profile_env_dir(profile.profile_id)
        # Isolate USERPROFILE and HOME while strictly stripping non-Antigravity provider secrets
        custom_env = build_safe_subprocess_env(
            overrides={
                "USERPROFILE": str(profile_dir),
                "HOME": str(profile_dir),
                "HOMEPATH": str(profile_dir),
            }
        )

        # If profile specifies a preferred model and request has generic or no model
        req = dict(request)
        model = req.get("model", "")
        if (not model or model == "default" or "antigravity" not in model.lower()) and profile.preferred_models:
            req["model"] = profile.preferred_models[0]

        # Load profile-specific auth and swap into Windows Credential Manager if present
        profile_auth = ProfileAuthManager.load_profile_auth("antigravity", profile.profile_id)

        if profile_auth:
            # Pre-flight check: verify token expiry before calling subprocess to prevent interactive browser login
            tokens = profile_auth.get("token") or profile_auth.get("tokens", {})
            refresh_tok = tokens.get("refresh_token") if isinstance(tokens, dict) else profile_auth.get("refresh_token")
            expiry = tokens.get("expiry_date") if isinstance(tokens, dict) else profile_auth.get("expiry_date")
            if not expiry and isinstance(tokens, dict):
                expiry = tokens.get("expires_at")
            if expiry:
                if float(expiry) > 1e11:
                    expiry = float(expiry) / 1000.0
                if time.time() > float(expiry) and not refresh_tok:
                    raise AuthExpiredError(
                        "Авторизация истекла, требуется повторный вход.",
                        provider="antigravity",
                        profile_id=profile.profile_id,
                    )

            with _AGY_INVOCATION_LOCK:
                res = agy_generate(req, custom_env=custom_env, profile_id=profile.profile_id)
        else:
            res = agy_generate(req, custom_env=custom_env, profile_id=profile.profile_id)

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
        return list(profile.preferred_models or [])

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

        # ErrorCategory.UNKNOWN не существует — обращение к нему роняло сам
        # классификатор, то есть отказ происходил ровно там, где обрабатывался
        # другой отказ, и маршрутизация обрывалась вместо перехода к резерву.
        # FATAL выбран по образцу codex и opencode: неразобранная ошибка не
        # должна вызывать повторов на том же профиле.
        return ErrorClassification(
            category=ErrorCategory.FATAL,
            message=err_msg,
        )
