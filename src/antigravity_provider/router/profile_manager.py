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
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    if local_app_data:
        return Path(local_app_data) / "hermes"
    return Path.home() / ".hermes"


def get_profile_dir(provider: str, profile_id: str) -> Path:
    """Get isolated directory for a profile."""
    base = get_hermes_base_dir()
    if provider == "antigravity":
        return base / "agy_profiles" / profile_id
    elif provider == "openai-codex":
        return base / "codex_profiles" / profile_id
    elif provider == "opencode-go":
        return base / "opengo_profiles" / profile_id
    return base / "profiles" / profile_id


def get_profile_auth_path(provider: str, profile_id: str) -> Path:
    """Get path to the profile's auth.json file."""
    return get_profile_dir(provider, profile_id) / "auth.json"


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
        state_file = get_hermes_base_dir() / "router_active_profile.json"
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

        state_file = get_hermes_base_dir() / "router_active_profile.json"
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
        """Save credentials to profile-specific auth.json."""
        pdir = get_profile_dir(provider, profile_id)
        pdir.mkdir(parents=True, exist_ok=True)
        auth_file = pdir / "auth.json"
        auth_file.write_text(json.dumps(auth_data, indent=2), encoding="utf-8")
        return auth_file

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
            # Check env var CODEX_TOKEN_<PROFILE_ID>
            env_var = f"CODEX_TOKEN_{profile_id.upper().replace('-', '_')}"
            val = os.environ.get(env_var)
            if val:
                return {"access_token": val, "auth_mode": "env_token"}
            # Check ~/.codex/auth.json for primary profile
            if profile_id == "codex-orch":
                codex_p = Path.home() / ".codex" / "auth.json"
                if codex_p.is_file():
                    try:
                        return json.loads(codex_p.read_text(encoding="utf-8"))
                    except Exception:
                        pass

        elif provider == "opencode-go":
            env_var = f"OPENCODE_GO_KEY_{profile_id.upper().replace('-', '_')}"
            val = os.environ.get(env_var) or os.environ.get("OPENCODE_GO_API_KEY")
            if val:
                return {"api_key": val, "auth_mode": "api_key"}

        elif provider == "antigravity":
            # For primary profile, can check current Windows Credential Manager
            if profile_id in ("ag-orch-fallback", "ag-w1"):
                cm_data = cls.read_windows_credential("gemini:antigravity")
                if cm_data:
                    return cm_data

        return None

    @classmethod
    def verify_antigravity_profile(cls, profile_id: str) -> Dict[str, Any]:
        """Verify an Antigravity profile's credentials against Google Tokeninfo API."""
        auth = cls.load_profile_auth("antigravity", profile_id)
        if not auth or not isinstance(auth, dict):
            return {"authenticated": False, "error": "No credentials stored for profile", "profile_id": profile_id}

        tok = auth.get("token", {}) if "token" in auth else auth
        access_token = tok.get("access_token")
        if not access_token:
            return {"authenticated": False, "error": "No access_token found", "profile_id": profile_id}

        url = f"https://www.googleapis.com/oauth2/v3/tokeninfo?access_token={access_token}"
        req = urllib.request.Request(url)
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
                email = data.get("email", "(unknown email)")
                sub = data.get("sub", "(unknown sub)")
                expires_in = int(data.get("expires_in", 0))

                return {
                    "authenticated": True,
                    "provider": "antigravity",
                    "profile_id": profile_id,
                    "email": email,
                    "email_masked": mask_email(email),
                    "account_id": sub,
                    "account_id_masked": mask_id(sub),
                    "expires_in": expires_in,
                    "scope": data.get("scope", ""),
                    "storage": str(get_profile_auth_path("antigravity", profile_id)),
                }
        except urllib.error.HTTPError as he:
            return {
                "authenticated": False,
                "error": f"HTTP {he.code}: token expired or invalid",
                "profile_id": profile_id,
                "storage": str(get_profile_auth_path("antigravity", profile_id)),
            }
        except Exception as e:
            return {
                "authenticated": False,
                "error": f"Verification error: {e}",
                "profile_id": profile_id,
                "storage": str(get_profile_auth_path("antigravity", profile_id)),
            }

    @classmethod
    def verify_codex_profile(cls, profile_id: str) -> Dict[str, Any]:
        """Verify an OpenAI Codex profile's credentials."""
        auth = cls.load_profile_auth("openai-codex", profile_id)
        if not auth or not isinstance(auth, dict):
            return {"authenticated": False, "error": "No credentials stored for profile", "profile_id": profile_id}

        tokens = auth.get("tokens", {}) if "tokens" in auth else auth
        id_token = tokens.get("id_token")
        account_id = tokens.get("account_id") or ""
        email = "(unknown)"

        if id_token and "." in id_token:
            try:
                parts = id_token.split(".")
                payload_b64 = parts[1] + "=" * (-len(parts[1]) % 4)
                payload = json.loads(base64.urlsafe_b64decode(payload_b64).decode("utf-8", errors="ignore"))
                email = payload.get("email") or "(openai-user)"
                if not account_id:
                    account_id = payload.get("sub") or ""
            except Exception:
                pass

        if not account_id and "access_token" in tokens:
            account_id = f"tok-{profile_id}"

        if not tokens.get("access_token") and not tokens.get("api_key"):
            return {"authenticated": False, "error": "Missing access token / API key", "profile_id": profile_id}

        return {
            "authenticated": True,
            "provider": "openai-codex",
            "profile_id": profile_id,
            "email": email,
            "email_masked": mask_email(email) if email != "(unknown)" else mask_id(account_id),
            "account_id": account_id,
            "account_id_masked": mask_id(account_id),
            "storage": str(get_profile_auth_path("openai-codex", profile_id)),
        }

    @classmethod
    def verify_opencode_profile(cls, profile_id: str) -> Dict[str, Any]:
        """Verify OpenCode Go profile credentials against models endpoint."""
        auth = cls.load_profile_auth("opencode-go", profile_id)
        if not auth or not isinstance(auth, dict):
            return {"authenticated": False, "error": "No API key stored for profile", "profile_id": profile_id}

        api_key = auth.get("api_key") or auth.get("token")
        if not api_key:
            return {"authenticated": False, "error": "Missing API key", "profile_id": profile_id}

        base_url = auth.get("base_url") or "https://opencode.ai/zen/go/v1"
        url = f"{base_url.rstrip('/')}/models"
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {api_key}"})
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
                models = [m.get("id") for m in data.get("data", []) if isinstance(m, dict)]
                return {
                    "authenticated": True,
                    "provider": "opencode-go",
                    "profile_id": profile_id,
                    "email_masked": f"key:{api_key[:6]}...{api_key[-4:]}",
                    "account_id": f"acc-{profile_id}",
                    "account_id_masked": f"acc-{profile_id}",
                    "models_count": len(models),
                    "models": models,
                    "storage": str(get_profile_auth_path("opencode-go", profile_id)),
                }
        except urllib.error.HTTPError as he:
            return {
                "authenticated": False,
                "error": f"HTTP {he.code}: API key rejected",
                "profile_id": profile_id,
                "storage": str(get_profile_auth_path("opencode-go", profile_id)),
            }
        except Exception as e:
            # If endpoint is network-restricted, return unauthenticated with error
            return {
                "authenticated": False,
                "error": f"Connection failed: {e}",
                "profile_id": profile_id,
                "storage": str(get_profile_auth_path("opencode-go", profile_id)),
            }

    @classmethod
    def get_profile_status(cls, provider: str, profile_id: str) -> Dict[str, Any]:
        """Get verified authentication status for any profile."""
        if provider == "antigravity":
            return cls.verify_antigravity_profile(profile_id)
        elif provider == "openai-codex":
            return cls.verify_codex_profile(profile_id)
        elif provider == "opencode-go":
            return cls.verify_opencode_profile(profile_id)
        return {"authenticated": False, "error": f"Unknown provider {provider}", "profile_id": profile_id}
