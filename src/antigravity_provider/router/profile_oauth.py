"""Profile OAuth manager for interactive Google / Antigravity account linking.

Features:
- Immediate listener startup with verified socket binding.
- Dynamic or standard (51121) port binding with strict redirect_uri alignment.
- Sanitized diagnostic logging without exposing codes, tokens, or client secrets.
- Deterministic session lifecycle, state validation, and clean cancellation.
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


class _ProfileOAuthCallbackHandler(BaseHTTPRequestHandler):
    server: "_ProfileOAuthServer"

    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != CALLBACK_PATH:
            self.send_error(404)
            return

        params = urllib.parse.parse_qs(parsed.query)
        self.server.session.received_state = (params.get("state") or [None])[0]
        self.server.session.received_error = (params.get("error") or [None])[0]
        self.server.session.received_code = (params.get("code") or [None])[0]

        body = (
            b"<!DOCTYPE html><html><head><meta charset='utf-8'><title>Hermes Account Linked</title>"
            b"<style>body{background:#0f172a;color:#f8fafc;font-family:sans-serif;display:flex;align-items:center;"
            b"justify-content:center;height:100vh;margin:0;}.card{background:#1e293b;padding:32px;border-radius:12px;"
            b"border:1px solid #334155;text-align:center;box-shadow:0 10px 25px rgba(0,0,0,0.5);}h1{color:#10b981;font-size:24px;}"
            b"p{color:#94a3b8;margin-top:12px;}</style></head><body>"
            b"<div class='card'><h1>&#10004; Account Authorized</h1>"
            b"<p>You can close this tab and return to the Hermes Account Manager.</p></div></body></html>"
        )
        self.send_response(200)
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

        self.received_code: Optional[str] = None
        self.received_state: Optional[str] = None
        self.received_error: Optional[str] = None

        self.server: Optional[_ProfileOAuthServer] = None
        self.server_thread: Optional[threading.Thread] = None
        self.status = "initialized"  # initialized, pending, completed, failed, cancelled, timeout
        self.error_msg: Optional[str] = None
        self.created_at = time.time()
        self.completed_profile_info: Optional[dict] = None
        self.is_listening = False

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
                    if self.received_code or self.received_error:
                        logger.info("OAUTH callback received")
                        break

                if self.received_error:
                    self.status = "failed"
                    self.error_msg = f"OAuth error from provider: {self.received_error}"
                    logger.warning("OAUTH callback error from provider: %s", self.received_error)
                elif self.received_code:
                    if self.received_state != self.state:
                        self.status = "failed"
                        self.error_msg = "State mismatch in OAuth callback"
                        logger.warning("OAUTH state validation failed")
                    else:
                        logger.info("OAUTH state validated")
                        self._finalize_tokens()
                elif self.status == "pending":
                    self.status = "timeout"
                    self.error_msg = "OAuth login timed out after 5 minutes"
                    logger.info("OAUTH callback server stopped reason=timeout")
            except Exception as loop_err:
                logger.error("OAUTH listener exception: %s: %s", type(loop_err).__name__, loop_err)
                self.status = "failed"
                self.error_msg = f"Listener error: {loop_err}"
            finally:
                self.is_listening = False
                if self.server:
                    try:
                        self.server.server_close()
                    except Exception:
                        pass
                    logger.info("OAUTH callback server stopped reason=%s", self.status)

        self.server_thread = threading.Thread(target=_serve, daemon=True)
        self.server_thread.start()
        _ACTIVE_OAUTH_SESSIONS[self.session_id] = self
        return self.get_auth_url()

    def _finalize_tokens(self) -> None:
        """Exchange code for tokens and save into dedicated profile."""
        try:
            logger.info("OAUTH code exchange started")
            tokens = exchange_code_for_tokens(
                self.received_code,
                redirect_uri=self.redirect_uri,
                code_verifier=self.verifier,
            )
            logger.info("OAUTH code exchange completed")

            email = fetch_user_email(tokens["access_token"])

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
            self.status = "completed"

        except Exception as e:
            logger.error("Error finalizing OAuth for profile=%s: %s: %s", self.profile_id, type(e).__name__, e)
            self.status = "failed"
            self.error_msg = str(e)

    def cancel(self) -> None:
        """Explicitly cancel the session and shutdown listener."""
        self.status = "cancelled"
        self.is_listening = False
        if self.server:
            try:
                self.server.server_close()
            except Exception:
                pass
        logger.info("OAUTH callback server stopped reason=cancelled")


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
