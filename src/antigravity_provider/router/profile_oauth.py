"""Profile OAuth manager for interactive Google / Antigravity account linking.

Architecture:
- Deterministic lifecycle: session creation -> port allocation -> listener verified ready -> URL generation.
- Unified callback pipeline: both automatic localhost HTTP callback and manual pasted callback URL
  flow through handle_callback() for state validation, original PKCE verifier lookup, and token exchange.
- Thread-safe single completion guarantee preventing duplicate saves.
- Zero secret logging policy (code, verifier, tokens, secrets are excluded from logs).
"""
from __future__ import annotations

import logging
import secrets
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from antigravity_provider.oauth import (
    AUTH_URL,
    CALLBACK_HOST,
    CALLBACK_PATH,
    CLIENT_ID,
    CLIENT_SECRET,
    SCOPES,
    _expires_at,
    _pkce_pair,
    exchange_code_for_tokens,
    fetch_user_email,
)
from antigravity_provider.router.profile_manager import ProfileAuthManager, mask_email

logger = logging.getLogger("hermes.router.profile_oauth")

_ACTIVE_OAUTH_SESSIONS: Dict[str, "ProfileOAuthSession"] = {}


SUCCESS_HTML = (
    b"<!DOCTYPE html><html><head><meta charset='utf-8'><title>Hermes Hub</title>"
    b"<style>body{background:#0f172a;color:#f8fafc;font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,sans-serif;"
    b"display:flex;align-items:center;justify-content:center;height:100vh;margin:0;}"
    b".card{background:#1e293b;padding:36px 48px;border-radius:16px;border:1px solid #334155;text-align:center;"
    b"box-shadow:0 20px 35px rgba(0,0,0,0.4);max-width:440px;}"
    b"h1{color:#10b981;font-size:22px;margin:0 0 12px 0;}"
    b"p{color:#94a3b8;font-size:14px;line-height:1.5;margin:0;}</style></head>"
    b"<body><div class='card'><h1>&#10004; \xd0\x90\xd0\xb2\xd1\x82\xd0\xbe\xd1\x80\xd0\xb8\xd0\xb7\xd0\xb0\xd1\x86\xd0\xb8\xd1\x8f \xd1\x83\xd1\x81\xd0\xbf\xd0\xb5\xd1\x88\xd0\xbd\xd0\xbe \xd0\xb7\xd0\xb0\xd0\xb2\xd0\xb5\xd1\x80\xd1\x88\xd0\xb5\xd0\xbd\xd0\xb0.</h1>"
    b"<p>\xd0\x9c\xd0\xbe\xd0\xb6\xd0\xbd\xd0\xbe \xd0\xb7\xd0\xb0\xd0\xba\xd1\x80\xd1\x8b\xd1\x82\xd1\x8c \xd1\x8d\xd1\x82\xd1\x83 \xd0\xb2\xd0\xba\xd0\xbb\xd0\xb0\xd0\xb4\xd0\xba\xd1\x83 \xd0\xb8 \xd0\xb2\xd0\xb5\xd1\x80\xd0\xbd\xd1\x83\xd1\x82\xd1\x8c\xd1\x81\xd1\x8f \xd0\xb2 Hermes Hub.</p></div></body></html>"
)

ERROR_HTML = (
    b"<!DOCTYPE html><html><head><meta charset='utf-8'><title>Hermes Hub</title>"
    b"<style>body{background:#0f172a;color:#f8fafc;font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,sans-serif;"
    b"display:flex;align-items:center;justify-content:center;height:100vh;margin:0;}"
    b".card{background:#1e293b;padding:36px 48px;border-radius:16px;border:1px solid #ef4444;text-align:center;"
    b"box-shadow:0 20px 35px rgba(0,0,0,0.4);max-width:440px;}"
    b"h1{color:#ef4444;font-size:22px;margin:0 0 12px 0;}"
    b"p{color:#94a3b8;font-size:14px;line-height:1.5;margin:0;}</style></head>"
    b"<body><div class='card'><h1>\xd0\x9d\xd0\xb5 \xd1\x83\xd0\xb4\xd0\xb0\xd0\xbb\xd0\xbe\xd1\x81\xd1\x8c \xd0\xb7\xd0\xb0\xd0\xb2\xd0\xb5\xd1\x80\xd1\x88\xd0\xb8\xd1\x82\xd1\x8c \xd0\xb0\xd0\xb2\xd1\x82\xd0\xbe\xd1\x80\xd0\xb8\xd0\xb7\xd0\xb0\xd1\x86\xd0\xb8\xd1\x8e.</h1>"
    b"<p>\xd0\x92\xd0\xb5\xd1\x80\xd0\xbd\xd0\xb8\xd1\x82\xd0\xb5\xd1\x81\xd1\x8c \xd0\xb2 Hermes Hub \xd0\xb4\xd0\xbb\xd1\x8f \xd0\xbf\xd0\xbe\xd0\xbb\xd1\x83\xd1\x87\xd0\xb5\xd0\xbd\xd0\xb8\xd1\x8f \xd0\xbf\xd0\xbe\xd0\xb4\xd1\x80\xd0\xbe\xd0\xb1\xd0\xbd\xd0\xbe\xd0\xb9 \xd0\xb8\xd0\xbd\xd1\x84\xd0\xbe\xd1\x80\xd0\xbc\xd0\xb0\xd1\x86\xd0\xb8\xd0\xb8.</p></div></body></html>"
)


class _ProfileOAuthCallbackHandler(BaseHTTPRequestHandler):
    server: "_ProfileOAuthServer"

    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != CALLBACK_PATH:
            self.send_error(404)
            return

        params = urllib.parse.parse_qs(parsed.query)
        received_state = (params.get("state") or [None])[0]
        received_error = (params.get("error") or [None])[0]
        received_code = (params.get("code") or [None])[0]
        error_desc = (params.get("error_description") or [None])[0]

        effective_err = received_error or error_desc

        ok, msg = self.server.session.handle_callback(
            code=received_code,
            state=received_state,
            error=effective_err,
            source="automatic",
        )

        body = SUCCESS_HTML if ok else ERROR_HTML
        self.send_response(200 if ok else 400)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)
        self.wfile.flush()

    def log_message(self, fmt: str, *args: object) -> None:
        return


class _ProfileOAuthServer(HTTPServer):
    def __init__(self, server_address: tuple[str, int], session: "ProfileOAuthSession"):
        self.session = session
        super().__init__(server_address, _ProfileOAuthCallbackHandler)


class ProfileOAuthSession:
    """Manages a single interactive OAuth flow for linking an Antigravity profile."""

    def __init__(self, profile_id: str, port: int = 51121):
        self.session_id = secrets.token_urlsafe(16)
        self.profile_id = profile_id
        self.requested_port = port
        self.port = port
        self.state = secrets.token_urlsafe(24)
        self.verifier, self.challenge = _pkce_pair()
        self.redirect_uri = f"http://{CALLBACK_HOST}:{self.port}{CALLBACK_PATH}"

        self.server: Optional[_ProfileOAuthServer] = None
        self.server_thread: Optional[threading.Thread] = None
        self.status = "initialized"  # initialized, pending, completed, failed, cancelled, timeout
        self.error_msg: Optional[str] = None
        self.created_at = time.time()
        self.completed_profile_info: Optional[dict] = None
        self.is_listening = False

        self._completion_lock = threading.Lock()
        self._is_completed = False

    def get_auth_url(self) -> str:
        params = {
            "client_id": CLIENT_ID,
            "response_type": "code",
            "redirect_uri": self.redirect_uri,
            "scope": " ".join(SCOPES),
            "state": self.state,
            "access_type": "offline",
            "prompt": "consent",
            "code_challenge": self.challenge,
            "code_challenge_method": "S256",
        }
        return f"{AUTH_URL}?{urllib.parse.urlencode(params)}"

    def start(self) -> str:
        """Start the background HTTP listener synchronously and return the auth URL."""
        logger.info("OAUTH callback server starting for profile=%s", self.profile_id)
        try:
            self.server = _ProfileOAuthServer((CALLBACK_HOST, self.requested_port), self)
            self.port = self.requested_port
        except OSError:
            # Fallback to an available dynamic port if standard port is busy
            self.server = _ProfileOAuthServer((CALLBACK_HOST, 0), self)
            self.port = self.server.server_port
            self.redirect_uri = f"http://{CALLBACK_HOST}:{self.port}{CALLBACK_PATH}"

        self.server.timeout = 1.0
        self.is_listening = True
        self.status = "pending"
        logger.info("OAUTH callback listening host=%s port=%d", CALLBACK_HOST, self.port)

        def _serve():
            try:
                while self.status == "pending" and time.time() - self.created_at < 300:
                    if self.server:
                        try:
                            self.server.handle_request()
                        except Exception as req_err:
                            logger.warning("OAUTH handle_request warning: %s: %s", type(req_err).__name__, req_err)
                    if self._is_completed or self.status != "pending":
                        break

                if self.status == "pending" and not self._is_completed:
                    self.status = "timeout"
                    self.error_msg = "Срок действия ссылки авторизации истёк (таймаут 5 минут)"
                    logger.info("OAUTH callback server stopped reason=timeout")
            except Exception as loop_err:
                logger.error("OAUTH listener exception: %s: %s", type(loop_err).__name__, loop_err)
                if not self._is_completed:
                    self.status = "failed"
                    self.error_msg = f"Ошибка слушателя: {loop_err}"
            finally:
                self.stop_listener()

        self.server_thread = threading.Thread(target=_serve, daemon=True)
        self.server_thread.start()
        _ACTIVE_OAUTH_SESSIONS[self.session_id] = self
        return self.get_auth_url()

    def handle_callback(
        self,
        code: Optional[str],
        state: Optional[str],
        error: Optional[str] = None,
        source: str = "automatic",
    ) -> Tuple[bool, str]:
        """Unified callback handler for both automatic localhost HTTP listener and manual pasted URL.

        Thread-safe: guarantees atomic single completion and original PKCE verifier token exchange.
        """
        with self._completion_lock:
            logger.info("OAuth callback received (source=%s)", source)

            if self._is_completed:
                logger.info("OAuth session already completed for profile=%s", self.profile_id)
                return True, "Авторизация уже успешно завершена"

            if error:
                self.status = "failed"
                self.error_msg = f"Провайдер отклонил авторизацию ({error})"
                logger.warning("OAuth error from provider (source=%s, error=%s)", source, error)
                return False, self.error_msg

            if not code:
                self.status = "failed"
                self.error_msg = "Код авторизации отсутствует в callback URL"
                logger.warning("OAuth code missing in callback (source=%s)", source)
                return False, self.error_msg

            if state != self.state:
                self.status = "failed"
                self.error_msg = "Несовпадение параметра state. Callback относится к другой или устаревшей сессии."
                logger.warning("OAuth state validation failed (source=%s)", source)
                return False, self.error_msg

            logger.info("OAuth state validated (source=%s)", source)

            try:
                logger.info("OAuth code exchange started (source=%s)", source)
                tokens = exchange_code_for_tokens(
                    code,
                    redirect_uri=self.redirect_uri,
                    code_verifier=self.verifier,
                )
                logger.info("OAuth code exchange completed (source=%s)", source)

                email = fetch_user_email(tokens["access_token"])
                logger.info("OAuth account identity resolved (email_found=%s)", bool(email))

                # Format in standard gemini:antigravity shape
                auth_data = {
                    "token": {
                        "access_token": tokens["access_token"],
                        "refresh_token": tokens["refresh_token"],
                        "expiry": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(tokens["expires_at"])),
                    },
                    "email": email or "",
                    "auth_method": "oauth",
                }

                # Save strictly to the chosen profile
                saved_path = ProfileAuthManager.save_profile_auth("antigravity", self.profile_id, auth_data)
                logger.info("Saved OAuth credentials for profile=%s to %s", self.profile_id, saved_path)

                self.completed_profile_info = {
                    "email": email or "Google Account",
                    "valid": True,
                    "profile_id": self.profile_id,
                }
                self._is_completed = True
                self.status = "completed"
                logger.info("OAuth session completed successfully for profile=%s", self.profile_id)

                return True, "Авторизация успешно завершена"

            except Exception as e:
                logger.error("Error finalizing OAuth for profile=%s: %s: %s", self.profile_id, type(e).__name__, e)
                self.status = "failed"
                self.error_msg = str(e)
                return False, str(e)

    def handle_manual_callback_url(self, raw_url: str) -> Tuple[bool, str]:
        """Parse user-pasted callback URL, extract code/state/error, and process through unified handler."""
        raw_url = raw_url.strip()
        if not raw_url:
            return False, "Пожалуйста, вставьте полный URL из адресной строки браузера."

        try:
            # Handle potential protocol-less paste (e.g. 127.0.0.1:49725/oauth-callback?...)
            if not raw_url.startswith("http://") and not raw_url.startswith("https://"):
                raw_url = "http://" + raw_url

            parsed = urllib.parse.urlparse(raw_url)
            params = urllib.parse.parse_qs(parsed.query)

            code = (params.get("code") or [None])[0]
            state = (params.get("state") or [None])[0]
            error = (params.get("error") or [None])[0]
            error_desc = (params.get("error_description") or [None])[0]

            effective_err = error or error_desc

            return self.handle_callback(
                code=code,
                state=state,
                error=effective_err,
                source="manual",
            )
        except Exception as parse_err:
            logger.warning("Error parsing manual callback URL: %s", parse_err)
            return False, f"Не удалось разобрать URL: {parse_err}"

    def stop_listener(self) -> None:
        """Safely close the HTTP listener socket."""
        self.is_listening = False
        if self.server:
            try:
                self.server.server_close()
            except Exception:
                pass
            logger.info("OAUTH callback server stopped reason=%s", self.status)

    def cancel(self) -> None:
        """Explicitly cancel the session and shutdown listener."""
        with self._completion_lock:
            if not self._is_completed:
                self.status = "cancelled"
                self.error_msg = "Авторизация отменена пользователем"
        self.stop_listener()


def start_profile_oauth(profile_id: str) -> Tuple[str, str, int]:
    """Start an OAuth flow for profile_id and return (session_id, auth_url, port)."""
    session = ProfileOAuthSession(profile_id)
    url = session.start()
    return session.session_id, url, session.port


def get_oauth_session(session_id: str) -> Optional[ProfileOAuthSession]:
    """Retrieve active OAuth session by ID."""
    return _ACTIVE_OAUTH_SESSIONS.get(session_id)


def cancel_oauth_session(session_id: Optional[str]) -> None:
    """Cancel an active OAuth session by ID if present."""
    if not session_id:
        return
    session = _ACTIVE_OAUTH_SESSIONS.pop(session_id, None)
    if session:
        session.cancel()
