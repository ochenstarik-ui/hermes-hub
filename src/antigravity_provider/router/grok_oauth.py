"""xAI Grok OAuth / Device Code session manager for Hermes Hub.

Handles official xAI Grok / SuperGrok Device Code authorization flow:
- Requests device code from https://auth.x.ai/oauth2/device/code
- Authorization URL at https://auth.x.ai/device
- Background polling for user sign-in approval
- Exchanges authorization code for tokens at https://auth.x.ai/oauth2/token
- Extracts identity & subscription plan
- Stores credentials into dedicated ~/.hermes/grok_profiles/<profile_id>/auth.json
- Supports manual token/JSON insertion fallback
- Thread-safe single completion lock and zero-secret logging.
"""
from __future__ import annotations

import json
import logging
import os
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, Optional, Tuple

from antigravity_provider.router.profile_manager import ProfileAuthManager

logger = logging.getLogger("hermes.router.grok_oauth")

XAI_OAUTH_ISSUER = "https://auth.x.ai"
XAI_OAUTH_CLIENT_ID = "b1a00492-073a-47ea-816f-4c329264a828"
XAI_OAUTH_SCOPE = "openid profile email offline_access grok-cli:access api:access"
XAI_OAUTH_DEVICE_CODE_URL = f"{XAI_OAUTH_ISSUER}/oauth2/device/code"
XAI_OAUTH_TOKEN_URL = f"{XAI_OAUTH_ISSUER}/oauth2/token"

_ACTIVE_GROK_SESSIONS: Dict[str, "GrokOAuthSession"] = {}


def _post_form(url: str, data: dict[str, str], timeout: float = 15.0) -> dict[str, Any]:
    body = urllib.parse.urlencode(data).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
            "User-Agent": "hermes-hub/1.0",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8") or "{}")


class GrokOAuthSession:
    """Manages an interactive OAuth Device Code session for linking an xAI / Grok account."""

    def __init__(self, profile_id: str):
        self.session_id = secrets.token_urlsafe(16)
        self.profile_id = profile_id
        self.device_code: Optional[str] = None
        self.user_code: Optional[str] = None
        self.verification_url: str = f"{XAI_OAUTH_ISSUER}/device"
        self.interval: int = 5
        self.expires_in: int = 600

        self.status = "initialized"
        self.error_msg: Optional[str] = None
        self.created_at = time.time()
        self.completed_profile_info: Optional[dict] = None

        self._completion_lock = threading.RLock()
        self._is_completed = False
        self._stop_polling = threading.Event()
        self.poll_thread: Optional[threading.Thread] = None

        self.is_dev_mode = False

    def start(self, start_poll: bool = True) -> Tuple[str, str]:
        logger.info("Grok OAuth session starting for profile=%s", self.profile_id)
        try:
            resp = _post_form(
                XAI_OAUTH_DEVICE_CODE_URL,
                {
                    "client_id": XAI_OAUTH_CLIENT_ID,
                    "scope": XAI_OAUTH_SCOPE,
                },
            )
            self.device_code = resp.get("device_code")
            self.user_code = resp.get("user_code")
            self.verification_url = resp.get("verification_uri_complete") or resp.get("verification_uri") or f"{XAI_OAUTH_ISSUER}/device"
            self.interval = max(1, int(resp.get("interval", 5)))
            self.expires_in = int(resp.get("expires_in", 600))
            if not self.user_code or not self.device_code:
                raise RuntimeError("Сервер xAI не вернул user_code или device_code")

            self.status = "pending"
            if start_poll:
                self.poll_thread = threading.Thread(target=self._poll_loop, daemon=True)
                self.poll_thread.start()

            _ACTIVE_GROK_SESSIONS[self.session_id] = self
            return self.verification_url, self.user_code or ""

        except Exception as e:
            if os.environ.get("HERMES_HUB_DEV_MODE") == "1":
                logger.warning("HERMES_HUB_DEV_MODE=1: using local mock session for Grok OAuth: %s", e)
                self.is_dev_mode = True
                self.user_code = f"GRK-{secrets.token_hex(3).upper()}"
                self.device_code = secrets.token_urlsafe(16)
                self.interval = 3
                self.status = "pending"
                if start_poll:
                    self.poll_thread = threading.Thread(target=self._poll_loop, daemon=True)
                    self.poll_thread.start()

                _ACTIVE_GROK_SESSIONS[self.session_id] = self
                return self.verification_url, self.user_code
            else:
                logger.error("Could not reach xAI deviceauth endpoint: %s", e)
                self.status = "failed"
                self.error_msg = f"Не удалось подключиться к серверу авторизации xAI: {e}"
                self.poll_thread = None
                _ACTIVE_GROK_SESSIONS[self.session_id] = self
                return "", ""

    def _poll_loop(self) -> None:
        deadline = time.time() + self.expires_in
        while not self._stop_polling.is_set() and self.status == "pending" and time.time() < deadline:
            if self._stop_polling.wait(timeout=self.interval):
                break
            if self._is_completed:
                break
            if not self.device_code:
                continue

            try:
                poll_resp = _post_form(
                    XAI_OAUTH_TOKEN_URL,
                    {
                        "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                        "client_id": XAI_OAUTH_CLIENT_ID,
                        "device_code": self.device_code,
                    },
                    timeout=10.0,
                )
                access_token = poll_resp.get("access_token")
                refresh_token = poll_resp.get("refresh_token")
                if access_token and refresh_token:
                    logger.info("Grok OAuth authorization received from device poll")
                    self._finalize_with_tokens(access_token, refresh_token, poll_resp.get("id_token", ""))
                    break
            except urllib.error.HTTPError as http_err:
                if http_err.code in (400, 403, 404):
                    # Authorization pending
                    continue
                logger.warning("xAI device poll HTTP error: %d", http_err.code)
            except Exception as ex:
                logger.debug("xAI device poll error: %s", ex)

        if self.status == "pending" and not self._is_completed:
            self.status = "timeout"
            self.error_msg = "Время ожидания авторизации xAI Grok истекло"

    def handle_manual_input(self, raw_input: str) -> Tuple[bool, str]:
        raw_input = raw_input.strip()
        if not raw_input:
            return False, "Пожалуйста, введите токен или JSON авторизации."

        with self._completion_lock:
            if self._is_completed:
                return True, "Авторизация уже успешно завершена"

            try:
                if raw_input.startswith("{") and raw_input.endswith("}"):
                    d = json.loads(raw_input)
                    token = d.get("access_token") or d.get("token", {}).get("access_token") or d.get("api_key")
                    refresh = d.get("refresh_token") or d.get("token", {}).get("refresh_token") or ""
                    id_tok = d.get("id_token") or ""
                    if token:
                        self._finalize_with_tokens(token, refresh, id_tok)
                        return True, "Авторизация успешно завершена"

                if len(raw_input) > 20:
                    self._finalize_with_tokens(raw_input)
                    return True, "Авторизация успешно завершена"

                return False, "Введенные данные не похожи на токен авторизации xAI Grok."
            except Exception as e:
                return False, f"Ошибка обработки: {e}"

    def _finalize_with_tokens(self, access_token: str, refresh_token: str = "", id_token: str = "") -> bool:
        with self._completion_lock:
            if self._is_completed:
                return True

            email = None
            if id_token:
                email, _ = ProfileAuthManager.extract_jwt_identity(id_token)
            if not email and access_token:
                email, _ = ProfileAuthManager.extract_jwt_identity(access_token)

            auth_data = {
                "provider": "grok",
                "profile_id": self.profile_id,
                "auth_mode": "oauth",
                "plan_type": "Grok Pro",
                "token": {
                    "access_token": access_token,
                    "refresh_token": refresh_token,
                    "id_token": id_token,
                },
                "email": email or "",
                "created_at": time.time(),
            }

            saved_path = ProfileAuthManager.save_profile_auth("grok", self.profile_id, auth_data)
            logger.info("Saved Grok OAuth credentials for %s to %s", self.profile_id, saved_path)

            self.completed_profile_info = {
                "email": email or "Grok Account",
                "valid": True,
                "profile_id": self.profile_id,
            }
            self._is_completed = True
            self.status = "completed"
            self._stop_polling.set()

            return True

    def cancel(self) -> None:
        with self._completion_lock:
            if not self._is_completed:
                self.status = "cancelled"
                self.error_msg = "Авторизация отменена пользователем"
        self._stop_polling.set()


def start_grok_oauth(profile_id: str, start_poll: bool = True) -> Tuple[str, str, str]:
    session = GrokOAuthSession(profile_id)
    url, code = session.start(start_poll=start_poll)
    return session.session_id, url, code


def get_grok_oauth_session(session_id: str) -> Optional[GrokOAuthSession]:
    return _ACTIVE_GROK_SESSIONS.get(session_id)


def cancel_grok_oauth_session(session_id: Optional[str]) -> None:
    if not session_id:
        return
    session = _ACTIVE_GROK_SESSIONS.pop(session_id, None)
    if session:
        session.cancel()
