"""Profile OAuth manager for interactive Google / Antigravity account linking."""
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
        self.end_headers()
        self.wfile.write(body)

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
        self.port = port
        self.state = secrets.token_urlsafe(24)
        self.verifier, self.challenge = _pkce_pair()
        self.redirect_uri = f"http://{CALLBACK_HOST}:{self.port}{CALLBACK_PATH}"

        self.received_code: Optional[str] = None
        self.received_state: Optional[str] = None
        self.received_error: Optional[str] = None

        self.server: Optional[_ProfileOAuthServer] = None
        self.server_thread: Optional[threading.Thread] = None
        self.status = "pending"  # pending, completed, failed, cancelled
        self.error_msg: Optional[str] = None
        self.created_at = time.time()
        self.completed_profile_info: Optional[dict] = None

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
        """Start the background HTTP listener and return the auth URL."""
        try:
            self.server = _ProfileOAuthServer((CALLBACK_HOST, self.port), self)
        except OSError:
            # Fallback to dynamic port if default is busy
            self.server = _ProfileOAuthServer((CALLBACK_HOST, 0), self)
            self.port = self.server.server_port
            self.redirect_uri = f"http://{CALLBACK_HOST}:{self.port}{CALLBACK_PATH}"

        self.server.timeout = 1.0

        def _serve():
            while self.status == "pending" and time.time() - self.created_at < 300:
                if self.server:
                    self.server.handle_request()
                if self.received_code or self.received_error:
                    break

            if self.received_error:
                self.status = "failed"
                self.error_msg = f"OAuth error from provider: {self.received_error}"
            elif self.received_code:
                if self.received_state != self.state:
                    self.status = "failed"
                    self.error_msg = "State mismatch in OAuth callback"
                else:
                    self._finalize_tokens()
            elif self.status == "pending":
                self.status = "failed"
                self.error_msg = "OAuth login timed out after 5 minutes"

            if self.server:
                self.server.server_close()

        self.server_thread = threading.Thread(target=_serve, daemon=True)
        self.server_thread.start()
        _ACTIVE_OAUTH_SESSIONS[self.session_id] = self
        return self.get_auth_url()

    def _finalize_tokens(self) -> None:
        """Exchange code for tokens and save into dedicated profile."""
        try:
            tokens = exchange_code_for_tokens(
                self.received_code,
                redirect_uri=self.redirect_uri,
                code_verifier=self.verifier,
            )

            # Format in standard gemini:antigravity shape
            auth_data = {
                "token": {
                    "access_token": tokens["access_token"],
                    "refresh_token": tokens["refresh_token"],
                    "expiry": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(tokens["expires_at"])),
                },
                "auth_method": "oauth",
            }

            # Save strictly to the chosen profile
            saved_path = ProfileAuthManager.save_profile_auth("antigravity", self.profile_id, auth_data)
            logger.info("Saved OAuth credentials for %s to %s", self.profile_id, saved_path)

            # Verify and extract identity
            ver = ProfileAuthManager.verify_antigravity_profile(self.profile_id)
            self.completed_profile_info = ver
            self.status = "completed"

        except Exception as e:
            logger.error("Error finalizing OAuth for %s: %s", self.profile_id, e)
            self.status = "failed"
            self.error_msg = str(e)

    def cancel(self) -> None:
        self.status = "cancelled"
        if self.server:
            try:
                self.server.server_close()
            except Exception:
                pass


def start_profile_oauth(profile_id: str) -> Tuple[str, str]:
    """Start an OAuth flow for profile_id and return (session_id, auth_url)."""
    session = ProfileOAuthSession(profile_id)
    url = session.start()
    return session.session_id, url


def get_oauth_session(session_id: str) -> Optional[ProfileOAuthSession]:
    return _ACTIVE_OAUTH_SESSIONS.get(session_id)
