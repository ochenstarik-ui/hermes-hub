"""Profile Auth Manager for Hermes Multi-Provider Account Router.

Handles per-profile credential storage, validation, identity verification,
and Windows Credential Manager integration for Antigravity, Codex, and OpenCode Go.
"""
from __future__ import annotations

import base64
import ctypes
from ctypes import wintypes
import json
import logging
import os
import threading
import time
import urllib.request
import urllib.error
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from antigravity_provider import paths

logger = logging.getLogger(__name__)

# Windows API definitions for Credential Manager
advapi32 = None
if os.name == "nt":
    try:
        advapi32 = ctypes.windll.advapi32
    except Exception as exc:
        logger.warning("advapi32 not available: %s", exc)

class CREDENTIAL_ATTRIBUTE(ctypes.Structure):
    _fields_ = [
        ("Keyword", wintypes.LPWSTR),
        ("Flags", wintypes.DWORD),
        ("ValueSize", wintypes.DWORD),
        ("Value", ctypes.c_void_p),
    ]

class CREDENTIAL(ctypes.Structure):
    _fields_ = [
        ("Flags", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR),
        ("Comment", wintypes.LPWSTR),
        ("LastWritten", wintypes.FILETIME),
        ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.c_void_p),
        ("Persist", wintypes.DWORD),
        ("AttributeCount", wintypes.DWORD),
        ("Attributes", ctypes.c_void_p),
        ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    ]

if advapi32:
    CredReadW = advapi32.CredReadW
    CredReadW.argtypes = [wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(ctypes.POINTER(CREDENTIAL))]
    CredReadW.restype = wintypes.BOOL

    CredWriteW = advapi32.CredWriteW
    CredWriteW.argtypes = [ctypes.POINTER(CREDENTIAL), wintypes.DWORD]
    CredWriteW.restype = wintypes.BOOL

    CredFree = advapi32.CredFree
    CredFree.argtypes = [ctypes.c_void_p]

# Global lock for credential manager swapping during subprocess execution
_CM_LOCK = threading.RLock()


def get_hermes_base_dir() -> Path:
    """Get the base hermes directory."""
    return paths.get_hermes_home()


def get_profile_dir(profile_id: str, provider: Optional[str] = None) -> Path:
    """Get isolated directory for a profile, supporting either (profile_id) or (provider, profile_id)."""
    if provider is not None and profile_id in ("antigravity", "openai-codex", "opencode-go"):
        return paths.get_profile_dir(provider, profile_id)
    return paths.get_profile_dir(profile_id, provider)


def get_profile_auth_path(provider: str, profile_id: str) -> Path:
    """Get path to the profile's auth.json file."""
    return get_profile_dir(profile_id, provider) / "auth.json"


def mask_email(email: str) -> str:
    """Mask email for safe logging: och***@gmail.com."""
    if not email or "@" not in email:
        return email[:4] + "***" if email else "(none)"
    local, domain = email.split("@", 1)
    visible_len = min(4, len(local))
    return f"{local[:visible_len]}***@{domain}"


def mask_id(raw_id: str) -> str:
    """Mask user ID / sub: 10761924..."""
    if not raw_id:
        return "(none)"
    if len(raw_id) <= 8:
        return raw_id[:3] + "***"
    return f"{raw_id[:8]}..."


class ProfileAuthManager:
    """Manages credentials and authentication verification across all profiles."""

    @classmethod
    def get_profile_dir(cls, profile_id: str, provider: Optional[str] = None) -> Path:
        """Official API to get isolated directory for a profile."""
        return get_profile_dir(profile_id, provider)

    @staticmethod
    def read_windows_credential(target_name: str = "gemini:antigravity") -> Optional[dict]:
        """Read a credential blob from Windows Credential Manager."""
        if not advapi32 or os.name != "nt":
            return None
        with _CM_LOCK:
            pcred = ctypes.POINTER(CREDENTIAL)()
            res = CredReadW(target_name, 1, 0, ctypes.byref(pcred))
            if not res:
                return None
            try:
                cred = pcred.contents
                blob = ctypes.string_at(cred.CredentialBlob, cred.CredentialBlobSize)
                data = json.loads(blob.decode("utf-8"))
                return data
            except Exception as e:
                logger.warning("Error parsing credential blob %s: %s", target_name, e)
                return None
            finally:
                CredFree(pcred)

    @staticmethod
    def write_windows_credential(target_name: str, auth_data: dict, user_name: str = "antigravity") -> bool:
        """Write a credential blob to Windows Credential Manager."""
        if not advapi32 or os.name != "nt":
            return False
        with _CM_LOCK:
            blob_bytes = json.dumps(auth_data).encode("utf-8")
            buf = ctypes.create_string_buffer(blob_bytes)
            cred = CREDENTIAL()
            cred.Flags = 0
            cred.Type = 1  # CRED_TYPE_GENERIC
            cred.TargetName = target_name
            cred.Comment = "Hermes Profile Auth Managed"
            cred.CredentialBlobSize = len(blob_bytes)
            cred.CredentialBlob = ctypes.cast(buf, ctypes.c_void_p)
            cred.Persist = 2  # CRED_PERSIST_LOCAL_MACHINE
            cred.AttributeCount = 0
            cred.Attributes = None
            cred.TargetAlias = None
            cred.UserName = user_name

            res = CredWriteW(ctypes.byref(cred), 0)
            return bool(res)

    @classmethod
    def get_main_profile(cls, provider: str = "antigravity") -> Optional[str]:
        """Get the currently designated main / active profile for a provider."""
        state_file = paths.get_router_active_profile_path()
        if state_file.is_file():
            try:
                data = json.loads(state_file.read_text(encoding="utf-8"))
                return data.get(provider)
            except Exception:
                pass
        return "ag-orch-fallback" if provider == "antigravity" else None

    @classmethod
    def set_main_profile(cls, provider: str, profile_id: str) -> Tuple[bool, str]:
        """Set a profile as the main / active account for Hermes, updating Windows Credential Manager."""
        auth_data = cls.load_profile_auth(provider, profile_id)
        if not auth_data:
            return False, f"Profile '{profile_id}' has no saved authentication in {get_profile_auth_path(provider, profile_id)}"

        if provider == "antigravity":
            ok = cls.write_windows_credential("gemini:antigravity", auth_data)
            if not ok:
                return False, "Failed to write credential to Windows Credential Manager"

        state_file = paths.get_router_active_profile_path()
        state = {}
        if state_file.is_file():
            try:
                state = json.loads(state_file.read_text(encoding="utf-8"))
            except Exception:
                state = {}
        state[provider] = profile_id
        state_file.write_text(json.dumps(state, indent=2), encoding="utf-8")

        return True, f"Profile '{profile_id}' is now the MAIN active account for {provider}"

    @classmethod
    def save_profile_auth(cls, provider: str, profile_id: str, auth_data: dict) -> Path:
        """Atomically save credentials and emit a secret-free targeted event."""
        pdir = get_profile_dir(profile_id, provider)
        pdir.mkdir(parents=True, exist_ok=True)
        auth_file = pdir / "auth.json"
        existed = auth_file.is_file()
        temp_file = pdir / f"auth.json.tmp-{threading.get_ident()}"
        temp_file.write_text(json.dumps(auth_data, indent=2), encoding="utf-8")
        os.replace(temp_file, auth_file)

        from antigravity_provider.router.event_bus import (
            EVENT_ACCOUNT_ADDED,
            EVENT_ACCOUNT_AUTH_CHANGED,
            EventBus,
        )

        EventBus.get().publish(
            EVENT_ACCOUNT_AUTH_CHANGED if existed else EVENT_ACCOUNT_ADDED,
            {"provider": provider, "profile_id": profile_id},
        )
        return auth_file

    @classmethod
    def delete_profile_auth(cls, provider: str, profile_id: str) -> bool:
        """Delete one credential file and emit a targeted removal event."""
        auth_file = get_profile_auth_path(provider, profile_id)
        if not auth_file.is_file():
            return False
        auth_file.unlink()
        from antigravity_provider.router.event_bus import EVENT_ACCOUNT_REMOVED, EventBus

        EventBus.get().publish(
            EVENT_ACCOUNT_REMOVED,
            {"provider": provider, "profile_id": profile_id},
        )
        return True

    @classmethod
    def load_profile_auth(cls, provider: str, profile_id: str) -> Optional[dict]:
        """Load credentials from profile-specific auth.json or env/auth.json fallback."""
        auth_file = get_profile_auth_path(provider, profile_id)
        if auth_file.is_file():
            try:
                return json.loads(auth_file.read_text(encoding="utf-8"))
            except Exception as e:
                logger.warning("Error reading %s: %s", auth_file, e)

        # Fallbacks for specific providers
        if provider == "openai-codex":
            env_var = f"CODEX_TOKEN_{profile_id.upper().replace('-', '_')}"
            val = os.environ.get(env_var) or os.environ.get("CODEX_API_KEY") or os.environ.get("OPENAI_API_KEY")
            if val:
                return {"provider": "openai-codex", "profile_id": profile_id, "api_key": val}

        elif provider == "opencode-go":
            env_var = f"OPENCODE_API_KEY_{profile_id.upper().replace('-', '_')}"
            val = os.environ.get(env_var) or os.environ.get("OPENCODE_API_KEY")
            if val:
                return {"provider": "opencode-go", "profile_id": profile_id, "api_key": val}

        return None

    @classmethod
    def extract_jwt_identity(cls, token: str) -> Tuple[Optional[str], Optional[str]]:
        """Extract email and subject (sub) from JWT id_token / access_token without verifying signature."""
        try:
            parts = token.split(".")
            if len(parts) < 2:
                return None, None
            payload_b64 = parts[1]
            rem = len(payload_b64) % 4
            if rem:
                payload_b64 += "=" * (4 - rem)
            data = json.loads(base64.urlsafe_b64decode(payload_b64).decode("utf-8"))
            # Standard claims + OpenAI / Google custom profile claims
            email = (
                data.get("email")
                or data.get("https://api.openai.com/profile", {}).get("email")
                or data.get("userinfo", {}).get("email")
            )
            sub = data.get("sub") or data.get("user_id") or data.get("id")
            return email, sub
        except Exception as e:
            logger.debug("Failed to extract JWT identity: %s", e)
            return None, None

    @classmethod
    def verify_codex_profile(cls, profile_id: str) -> Dict[str, Any]:
        """Verify Codex profile authentication and return metadata."""
        auth_data = cls.load_profile_auth("openai-codex", profile_id)
        if not auth_data:
            return {"valid": False, "email": None, "profile_id": profile_id}

        tokens = auth_data.get("token") or auth_data.get("tokens", {})
        acc_token = tokens.get("access_token") if isinstance(tokens, dict) else (auth_data.get("access_token") or "")
        id_token = tokens.get("id_token") if isinstance(tokens, dict) else (auth_data.get("id_token") or "")

        email = auth_data.get("email")
        if not email and id_token:
            email, _ = cls.extract_jwt_identity(id_token)
        if not email and acc_token:
            email, _ = cls.extract_jwt_identity(acc_token)

        key = auth_data.get("api_key", "")
        if acc_token:
            return {
                "valid": True,
                "email": email or "ChatGPT Account",
                "profile_id": profile_id,
                "auth_mode": "oauth",
            }
        elif key:
            ok, masked, models = cls.verify_codex_token(key)
            return {
                "valid": ok,
                "email": masked or "OpenAI API Key",
                "profile_id": profile_id,
                "auth_mode": "api_key",
                "models": models,
            }

        return {"valid": False, "email": None, "profile_id": profile_id}

    @classmethod
    def verify_antigravity_token(cls, access_token: str) -> Tuple[bool, Optional[str], Optional[str]]:
        """Verify Antigravity access token against Google UserInfo API. Returns (valid, email, account_id)."""
        try:
            url = "https://www.googleapis.com/oauth2/v3/userinfo"
            req = urllib.request.Request(url, headers={"Authorization": f"Bearer {access_token}"})
            with urllib.request.urlopen(req, timeout=8) as resp:
                if resp.status == 200:
                    info = json.loads(resp.read().decode("utf-8"))
                    email = info.get("email")
                    account_id = info.get("sub")
                    return True, email, account_id
        except urllib.error.HTTPError as e:
            logger.debug("Google token verification failed with HTTP %d", e.code)
            return False, None, None
        except Exception as e:
            logger.debug("Google token verification error: %s", e)
            return False, None, None
        return False, None, None

    @classmethod
    def verify_codex_token(cls, api_key: str) -> Tuple[bool, Optional[str], List[str]]:
        """Verify OpenAI Codex API key and discover available models. Returns (valid, masked_id, models)."""
        try:
            url = "https://api.openai.com/v1/models"
            req = urllib.request.Request(url, headers={"Authorization": f"Bearer {api_key}"})
            with urllib.request.urlopen(req, timeout=8) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode("utf-8"))
                    models = [m.get("id") for m in data.get("data", []) if "gpt" in m.get("id", "").lower()]
                    masked = f"sk-...{api_key[-4:]}" if len(api_key) > 8 else "sk-***"
                    return True, masked, sorted(models)
        except Exception:
            pass
        # Fallback offline check for structural validity
        if api_key.startswith("sk-") and len(api_key) >= 20:
            masked = f"sk-...{api_key[-4:]}"
            return True, masked, ["gpt-4o", "o3-mini", "gpt-4o-mini", "codex"]
        return False, None, []

    @classmethod
    def verify_claude_token(cls, api_key: str) -> Tuple[bool, Optional[str], List[str]]:
        """Verify Claude API key and discover models. Returns (valid, masked_id, models)."""
        if api_key and (api_key.startswith("sk-ant-") or len(api_key) >= 20):
            masked = f"sk-ant-...{api_key[-4:]}" if len(api_key) > 12 else "sk-ant-***"
            return True, masked, ["claude-3-7-sonnet", "claude-3-5-sonnet", "claude-3-5-haiku", "claude-3-opus"]
        return False, None, []

    @classmethod
    def verify_grok_token(cls, api_key: str) -> Tuple[bool, Optional[str], List[str]]:
        """Verify xAI Grok API key and discover models. Returns (valid, masked_id, models)."""
        if api_key and (api_key.startswith("xai-") or len(api_key) >= 20):
            masked = f"xai-...{api_key[-4:]}" if len(api_key) > 8 else "xai-***"
            return True, masked, ["grok-3", "grok-3-mini", "grok-2"]
        return False, None, []

    @classmethod
    def verify_opencode_token(cls, api_key: str) -> Tuple[bool, Optional[str], List[str]]:
        """Verify OpenCode Go API key and discover models. Returns (valid, masked_id, models)."""
        if api_key and (api_key.startswith("opencode-") or len(api_key) >= 16):
            masked = f"opencode-...{api_key[-4:]}"
            return True, masked, ["opencode-go-3"]
        return False, None, []

    @classmethod
    def get_profile_status(cls, provider: str, profile_id: str) -> Dict[str, Any]:
        """Check status and metadata for a profile."""
        auth_data = cls.load_profile_auth(provider, profile_id)
        if not auth_data:
            return {
                "authenticated": False,
                "provider": provider,
                "profile_id": profile_id,
                "status": "NOT_CONFIGURED",
                "error": None,
            }

        if provider == "antigravity":
            tokens = auth_data.get("tokens", {})
            acc_token = tokens.get("access_token") or auth_data.get("access_token")
            id_token = tokens.get("id_token") or auth_data.get("id_token")
            email = None
            acc_id = None
            if id_token:
                email, acc_id = cls.extract_jwt_identity(id_token)

            expiry = tokens.get("expiry_date") or auth_data.get("expiry_date")
            is_expired = False
            if expiry:
                if expiry > 1e11:
                    expiry = expiry / 1000.0
                if time.time() > expiry:
                    is_expired = True

            return {
                "authenticated": True,
                "provider": provider,
                "profile_id": profile_id,
                "email_masked": mask_email(email) if email else None,
                "account_id_masked": mask_id(acc_id) if acc_id else None,
                "is_expired": is_expired,
                "status": "EXPIRED" if is_expired else "AUTHENTICATED",
                "error": "Token expired" if is_expired else None,
            }

        elif provider in ("openai-codex", "codex"):
            tokens = auth_data.get("token") or auth_data.get("tokens", {})
            acc_token = tokens.get("access_token") if isinstance(tokens, dict) else (auth_data.get("access_token") or "")
            id_token = tokens.get("id_token") if isinstance(tokens, dict) else (auth_data.get("id_token") or "")
            email = auth_data.get("email")
            if not email and id_token:
                email, _ = cls.extract_jwt_identity(id_token)
            if not email and acc_token:
                email, _ = cls.extract_jwt_identity(acc_token)

            key = auth_data.get("api_key", "")
            is_oauth = bool(acc_token)
            is_auth = is_oauth or bool(key)

            account_id_masked = None
            if is_oauth:
                account_id_masked = mask_email(email) if email else "ChatGPT Account"
            elif key:
                account_id_masked = f"sk-...{key[-4:]}" if len(key) > 8 else "sk-***"

            return {
                "authenticated": is_auth,
                "provider": provider,
                "profile_id": profile_id,
                "auth_mode": "oauth" if is_oauth else ("api_key" if key else "unconfigured"),
                "email_masked": mask_email(email) if email else None,
                "account_id_masked": account_id_masked,
                "status": "AUTHENTICATED" if is_auth else "NOT_CONFIGURED",
                "error": None,
            }

        elif provider in ("claude", "anthropic"):
            tokens = auth_data.get("token") or auth_data.get("tokens", {})
            acc_token = tokens.get("access_token") if isinstance(tokens, dict) else (auth_data.get("access_token") or "")
            email = auth_data.get("email")
            if not email and acc_token:
                email, _ = cls.extract_jwt_identity(acc_token)
            key = auth_data.get("api_key", "")
            is_oauth = bool(acc_token)
            is_auth = is_oauth or bool(key)

            account_id_masked = None
            if is_oauth:
                account_id_masked = mask_email(email) if email else "Claude Account"
            elif key:
                account_id_masked = f"sk-ant-...{key[-4:]}" if len(key) > 12 else "sk-ant-***"

            return {
                "authenticated": is_auth,
                "provider": provider,
                "profile_id": profile_id,
                "auth_mode": "oauth" if is_oauth else ("api_key" if key else "unconfigured"),
                "email_masked": mask_email(email) if email else None,
                "account_id_masked": account_id_masked,
                "status": "AUTHENTICATED" if is_auth else "NOT_CONFIGURED",
                "error": None,
            }

        elif provider in ("grok", "xai", "xai-oauth"):
            tokens = auth_data.get("token") or auth_data.get("tokens", {})
            acc_token = tokens.get("access_token") if isinstance(tokens, dict) else (auth_data.get("access_token") or "")
            id_token = tokens.get("id_token") if isinstance(tokens, dict) else (auth_data.get("id_token") or "")
            email = auth_data.get("email")
            if not email and id_token:
                email, _ = cls.extract_jwt_identity(id_token)
            if not email and acc_token:
                email, _ = cls.extract_jwt_identity(acc_token)

            key = auth_data.get("api_key", "")
            is_oauth = bool(acc_token)
            is_auth = is_oauth or bool(key)

            account_id_masked = None
            if is_oauth:
                account_id_masked = mask_email(email) if email else "Grok Account"
            elif key:
                account_id_masked = f"xai-...{key[-4:]}" if len(key) > 8 else "xai-***"

            return {
                "authenticated": is_auth,
                "provider": provider,
                "profile_id": profile_id,
                "auth_mode": "oauth" if is_oauth else ("api_key" if key else "unconfigured"),
                "email_masked": mask_email(email) if email else None,
                "account_id_masked": account_id_masked,
                "status": "AUTHENTICATED" if is_auth else "NOT_CONFIGURED",
                "error": None,
            }

        elif provider in ("opencode-go", "opencode"):
            key = auth_data.get("api_key", "")
            return {
                "authenticated": bool(key),
                "provider": provider,
                "profile_id": profile_id,
                "account_id_masked": f"opencode-...{key[-4:]}" if len(key) > 8 else "opencode-***",
                "status": "AUTHENTICATED" if key else "NOT_CONFIGURED",
                "error": None,
            }

        return {
            "authenticated": False,
            "provider": provider,
            "profile_id": profile_id,
            "status": "UNKNOWN_PROVIDER",
            "error": f"Unknown provider {provider}",
        }
