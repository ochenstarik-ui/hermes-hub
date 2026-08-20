"""Anthropic Claude OAuth PKCE session manager for Hermes Hub.

Handles official Claude / Claude Code OAuth 2.0 PKCE flow:
- Authorizes at https://claude.ai/oauth/authorize
- Token exchange at https://platform.claude.com/v1/oauth/token (with console.anthropic.com fallback)
- Extracts user email/identity from user:profile and JWT claims
- Stores credentials into dedicated ~/.hermes/claude_profiles/<profile_id>/auth.json
- Supports manual authorization code / token insertion fallback
- Thread-safe single completion lock and zero-secret logging.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, Optional, Tuple

from antigravity_provider.router.profile_manager import ProfileAuthManager

logger = logging.getLogger("hermes.router.claude_oauth")

CLAUDE_OAUTH_CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
CLAUDE_OAUTH_TOKEN_URLS = [
    "https://platform.claude.com/v1/oauth/token",
    "https://console.anthropic.com/v1/oauth/token",
]
CLAUDE_OAUTH_REDIRECT_URI = "https://console.anthropic.com/oauth/code/callback"
CLAUDE_OAUTH_SCOPES = "org:create_api_key user:profile user:inference"
CLAUDE_OAUTH_TOKEN_USER_AGENT = "axios/1.7.9"

_ACTIVE_CLAUDE_SESSIONS: Dict[str, "ClaudeOAuthSession"] = {}


def _generate_pkce() -> Tuple[str, str]:
    """Generate PKCE code_verifier and code_challenge (S256)."""
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b"=").decode()
    return verifier, challenge


class ClaudeOAuthSession:
    """Manages an interactive OAuth PKCE session for linking a Claude (Anthropic) account."""

    def __init__(self, profile_id: str):
        self.session_id = secrets.token_urlsafe(16)
        self.profile_id = profile_id
        self.verifier, self.challenge = _generate_pkce()
        self.oauth_state = secrets.token_urlsafe(32)

        params = {
            "code": "true",
            "client_id": CLAUDE_OAUTH_CLIENT_ID,
            "response_type": "code",
            "redirect_uri": CLAUDE_OAUTH_REDIRECT_URI,
            "scope": CLAUDE_OAUTH_SCOPES,
            "code_challenge": self.challenge,
            "code_challenge_method": "S256",
            "state": self.oauth_state,
        }
        self.auth_url = f"https://claude.ai/oauth/authorize?{urllib.parse.urlencode(params)}"
        self.status = "pending"
        self.error_msg: Optional[str] = None
        self.created_at = time.time()
        self.completed_profile_info: Optional[dict] = None

        self._completion_lock = threading.RLock()
        self._is_completed = False
        _ACTIVE_CLAUDE_SESSIONS[self.session_id] = self

    def start(self) -> str:
        logger.info("Claude OAuth session started for profile=%s", self.profile_id)
        return self.auth_url

    def handle_auth_code(self, raw_code: str) -> Tuple[bool, str]:
        """Exchange authorization code (or 'code#state') for access token and refresh token."""
        raw_code = raw_code.strip()
        if not raw_code:
            return False, "Пожалуйста, введите код авторизации."

        with self._completion_lock:
            if self._is_completed:
                return True, "Авторизация уже успешно завершена"

            splits = raw_code.split("#")
            code = splits[0].strip()
            received_state = splits[1].strip() if len(splits) > 1 else ""

            # Check direct JSON token paste fallback
            if code.startswith("{") and code.endswith("}"):
                try:
                    d = json.loads(code)
                    acc = d.get("access_token") or d.get("apiKey")
                    ref = d.get("refresh_token") or ""
                    if acc:
                        return self._finalize_with_tokens(acc, ref), "Авторизация успешно завершена"
                except Exception:
                    pass

            exchange_data = json.dumps({
                "grant_type": "authorization_code",
                "client_id": CLAUDE_OAUTH_CLIENT_ID,
                "code": code,
                "state": received_state or self.oauth_state,
                "redirect_uri": CLAUDE_OAUTH_REDIRECT_URI,
                "code_verifier": self.verifier,
            }).encode()

            result = None
            last_error = None
            for endpoint in CLAUDE_OAUTH_TOKEN_URLS:
                req = urllib.request.Request(
                    endpoint,
                    data=exchange_data,
                    headers={
                        "Content-Type": "application/json",
                        "User-Agent": CLAUDE_OAUTH_TOKEN_USER_AGENT,
                    },
                    method="POST",
                )
                try:
                    with urllib.request.urlopen(req, timeout=15) as resp:
                        result = json.loads(resp.read().decode())
                    break
                except Exception as exc:
                    last_error = exc
                    logger.debug("Claude token exchange failed at %s: %s", endpoint, exc)
                    continue

            if result is None:
                # If network exchange failed, allow token fallback
                if len(code) > 20:
                    return self._finalize_with_tokens(code), "Авторизация успешно завершена"
                err_msg = f"Ошибка обмена кода Claude: {last_error}"
                self.status = "failed"
                self.error_msg = err_msg
                return False, err_msg

            access_token = result.get("access_token", "")
            refresh_token = result.get("refresh_token", "")
            if not access_token:
                return False, "Ответ Anthropic не содержит access_token."

            return self._finalize_with_tokens(access_token, refresh_token), "Авторизация успешно завершена"

    def _finalize_with_tokens(self, access_token: str, refresh_token: str = "") -> bool:
        email, sub = ProfileAuthManager.extract_jwt_identity(access_token)
        auth_data = {
            "provider": "claude",
            "profile_id": self.profile_id,
            "auth_mode": "oauth",
            "plan_type": "MAX",
            "token": {
                "access_token": access_token,
                "refresh_token": refresh_token,
            },
            "email": email or "",
            "created_at": time.time(),
        }

        saved_path = ProfileAuthManager.save_profile_auth("claude", self.profile_id, auth_data)
        logger.info("Saved Claude OAuth credentials for %s to %s", self.profile_id, saved_path)

        self.completed_profile_info = {
            "email": email or "Claude Account",
            "valid": True,
            "profile_id": self.profile_id,
        }
        self._is_completed = True
        self.status = "completed"
        return True

    def cancel(self) -> None:
        with self._completion_lock:
            if not self._is_completed:
                self.status = "cancelled"
                self.error_msg = "Авторизация отменена пользователем"


def start_claude_oauth(profile_id: str) -> Tuple[str, str]:
    """Start Claude OAuth flow and return (session_id, auth_url)."""
    session = ClaudeOAuthSession(profile_id)
    url = session.start()
    return session.session_id, url


def get_claude_oauth_session(session_id: str) -> Optional[ClaudeOAuthSession]:
    return _ACTIVE_CLAUDE_SESSIONS.get(session_id)


def cancel_claude_oauth_session(session_id: Optional[str]) -> None:
    if not session_id:
        return
    session = _ACTIVE_CLAUDE_SESSIONS.pop(session_id, None)
    if session:
        session.cancel()
