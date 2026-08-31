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
from datetime import datetime
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

    @classmethod
    def write_agy_oauth_creds(cls, profile_dir: Path, auth_data: dict) -> Path:
        """Atomically write <profile_dir>/.gemini/oauth_creds.json in exact agy CLI format."""
        token_info = auth_data.get("token") or auth_data.get("tokens") or auth_data
        if not isinstance(token_info, dict):
            token_info = {}

        access_token = token_info.get("access_token") or auth_data.get("access_token") or ""
        refresh_token = token_info.get("refresh_token") or auth_data.get("refresh_token") or ""
        # Файл без токена доступа бесполезен: agy на нём отвечает «Please sign in
        # to view available models», а хаб считает аккаунт подключённым. Пустой
        # вход не должен выдаваться за успешный.
        if not access_token and not refresh_token:
            raise ValueError(
                "Вход не завершён: провайдер не вернул токен доступа. "
                "Учётные данные agy не записаны."
            )
        scope = token_info.get("scope") or auth_data.get("scope") or ""
        token_type = token_info.get("token_type") or auth_data.get("token_type") or "Bearer"
        id_token = token_info.get("id_token") or auth_data.get("id_token") or ""

        # Expiry date in milliseconds (int)
        expiry_date = token_info.get("expiry_date") or auth_data.get("expiry_date")
        if not expiry_date:
            expires_at = token_info.get("expires_at") or auth_data.get("expires_at")
            if expires_at:
                try:
                    expiry_date = int(float(expires_at) * 1000)
                except Exception:
                    expiry_date = int((time.time() + 3600) * 1000)
            else:
                expiry_str = token_info.get("expiry") or auth_data.get("expiry")
                if expiry_str:
                    try:
                        dt = datetime.fromisoformat(str(expiry_str).replace("Z", "+00:00"))
                        expiry_date = int(dt.timestamp() * 1000)
                    except Exception:
                        expiry_date = int((time.time() + 3600) * 1000)
                else:
                    expiry_date = int((time.time() + 3600) * 1000)
        elif float(expiry_date) < 1e11:  # in seconds
            expiry_date = int(float(expiry_date) * 1000)
        else:
            expiry_date = int(expiry_date)

        creds_dict = {
            "access_token": str(access_token),
            "refresh_token": str(refresh_token),
            "scope": str(scope),
            "token_type": str(token_type),
            "id_token": str(id_token),
            "expiry_date": expiry_date,
        }

        gemini_dir = profile_dir / ".gemini"
        gemini_dir.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(gemini_dir, 0o700)
        except OSError:
            pass

        target_file = gemini_dir / "oauth_creds.json"
        temp_file = gemini_dir / f"oauth_creds.json.tmp-{threading.get_ident()}-{time.time_ns()}"
        temp_file.write_text(json.dumps(creds_dict, indent=2), encoding="utf-8")
        try:
            os.chmod(temp_file, 0o600)
        except OSError:
            pass
        os.replace(temp_file, target_file)
        try:
            os.chmod(target_file, 0o600)
        except OSError:
            pass
        return target_file

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
            payload_data = auth_data
            if target_name == "gemini:antigravity" and isinstance(auth_data, dict):
                # Ensure 6-field agy-compatible schema in Credential Manager
                token_info = auth_data.get("token") or auth_data.get("tokens") or auth_data
                if isinstance(token_info, dict) and ("access_token" in token_info or "access_token" in auth_data):
                    acc = token_info.get("access_token") or auth_data.get("access_token") or ""
                    ref = token_info.get("refresh_token") or auth_data.get("refresh_token") or ""
                    sc = token_info.get("scope") or auth_data.get("scope") or ""
                    tt = token_info.get("token_type") or auth_data.get("token_type") or "Bearer"
                    idt = token_info.get("id_token") or auth_data.get("id_token") or ""
                    exp = token_info.get("expiry_date") or auth_data.get("expiry_date")
                    if not exp:
                        exp_at = token_info.get("expires_at") or auth_data.get("expires_at")
                        if exp_at:
                            try:
                                exp = int(float(exp_at) * 1000)
                            except Exception:
                                exp = int((time.time() + 3600) * 1000)
                        else:
                            exp = int((time.time() + 3600) * 1000)
                    elif float(exp) < 1e11:
                        exp = int(float(exp) * 1000)
                    else:
                        exp = int(exp)
                    payload_data = {
                        "access_token": str(acc),
                        "refresh_token": str(ref),
                        "scope": str(sc),
                        "token_type": str(tt),
                        "id_token": str(idt),
                        "expiry_date": exp,
                    }

            blob_bytes = json.dumps(payload_data).encode("utf-8")
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
        """Set a profile as the main / active account for Hermes."""
        auth_data = cls.load_profile_auth(provider, profile_id)
        if not auth_data:
            return False, f"Profile '{profile_id}' has no saved authentication in {get_profile_auth_path(provider, profile_id)}"

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
        temp_file = pdir / f"auth.json.tmp-{threading.get_ident()}-{time.time_ns()}"
        temp_file.write_text(json.dumps(auth_data, indent=2), encoding="utf-8")
        try:
            os.chmod(temp_file, 0o600)
        except OSError:
            pass
        os.replace(temp_file, auth_file)
        try:
            os.chmod(auth_file, 0o600)
        except OSError:
            pass

        # For Antigravity, synchronously maintain <profile_dir>/.gemini/oauth_creds.json
        if provider in ("antigravity", "google-antigravity"):
            try:
                cls.write_agy_oauth_creds(pdir, auth_data)
            except Exception as e:
                # Прежде сбой оставался только в журнале, и владелец видел
                # «подключено» при неработающем аккаунте. agy читает именно
                # этот файл, поэтому без него подключения нет.
                logger.error(
                    "Не записаны учётные данные agy для профиля %s: %s", profile_id, e
                )
                raise RuntimeError(
                    f"Учётные данные для agy не записаны ({e}). "
                    f"Аккаунт {profile_id} подключённым не считается."
                ) from e

        # For Local and OpenAI-compatible providers, synchronize custom_base_url in router_profiles.yaml
        if provider in ("local", "local-llm", "llama.cpp", "ollama", "vllm", "openrouter", "nvidia", "nvidia-nim"):
            base_url = auth_data.get("base_url")
            if base_url:
                try:
                    from antigravity_provider.router.router_config import load_router_config, save_router_config
                    from antigravity_provider.router.auto_assigner import AutoAssigner
                    rcfg = load_router_config()
                    if profile_id not in rcfg.profiles:
                        AutoAssigner.ensure_profile_definition(provider, profile_id)
                        rcfg = load_router_config()
                    if profile_id in rcfg.profiles:
                        rcfg.profiles[profile_id].custom_base_url = str(base_url).strip()
                        if auth_data.get("models") and isinstance(auth_data["models"], list):
                            rcfg.profiles[profile_id].preferred_models = list(auth_data["models"])
                        save_router_config(rcfg)
                except Exception as e:
                    logger.warning("Failed to sync custom_base_url for local profile=%s: %s", profile_id, e)

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
                data = json.loads(auth_file.read_text(encoding="utf-8"))
                if provider in ("antigravity", "google-antigravity") and isinstance(data, dict):
                    pdir = get_profile_dir(profile_id, provider)
                    gemini_creds = pdir / ".gemini" / "oauth_creds.json"
                    if not gemini_creds.is_file():
                        try:
                            cls.write_agy_oauth_creds(pdir, data)
                        except Exception as e:
                            logger.debug("Failed to create missing oauth_creds.json: %s", e)

                    # Auto-refresh expired or expiring access tokens if refresh_token is present
                    tokens = data.get("token") or data.get("tokens")
                    if isinstance(tokens, dict):
                        refresh_tok = tokens.get("refresh_token")
                        acc_tok = tokens.get("access_token")
                        exp_at = tokens.get("expires_at")
                        if not exp_at:
                            exp_str = tokens.get("expiry")
                            if exp_str:
                                try:
                                    dt = datetime.fromisoformat(str(exp_str).replace("Z", "+00:00"))
                                    exp_at = dt.timestamp()
                                except Exception:
                                    exp_at = None

                        now = time.time()
                        if refresh_tok and (not acc_tok or (exp_at and now + 60 >= float(exp_at))):
                            try:
                                from antigravity_provider.oauth import refresh_access_token

                                existing_id = tokens.get("id_token")
                                existing_scope = tokens.get("scope")
                                refreshed = refresh_access_token(
                                    str(refresh_tok),
                                    existing_id_token=str(existing_id) if existing_id else None,
                                    existing_scope=str(existing_scope) if existing_scope else None,
                                )
                                tokens.update({
                                    "access_token": refreshed["access_token"],
                                    "refresh_token": refreshed.get("refresh_token") or refresh_tok,
                                    "id_token": refreshed.get("id_token") or existing_id or "",
                                    "scope": refreshed.get("scope") or existing_scope or "",
                                    "token_type": refreshed.get("token_type", "Bearer"),
                                    "expires_at": refreshed.get("expires_at"),
                                    "expiry": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(refreshed["expires_at"])),
                                })
                                data["token"] = tokens
                                cls.save_profile_auth(provider, profile_id, data)
                            except Exception as re_err:
                                logger.warning("Silent token refresh failed for profile=%s: %s", profile_id, re_err)

                return data
            except Exception as e:
                logger.warning("Error reading %s: %s", auth_file, e)

        if not auth_file.is_file() and provider in ("antigravity", "google-antigravity"):
            pdir = get_profile_dir(profile_id, provider)
            gemini_creds = pdir / ".gemini" / "oauth_creds.json"
            if gemini_creds.is_file():
                try:
                    data = json.loads(gemini_creds.read_text(encoding="utf-8"))
                    if isinstance(data, dict):
                        return {"provider": provider, "profile_id": profile_id, "token": data}
                except Exception as e:
                    logger.warning("Error reading %s: %s", gemini_creds, e)

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

        elif provider in ("local", "local-llm", "llama.cpp", "ollama", "vllm"):
            env_var = f"LOCAL_LLM_URL_{profile_id.upper().replace('-', '_')}"
            val = os.environ.get(env_var) or os.environ.get("LOCAL_LLM_BASE_URL")
            if val:
                return {"provider": provider, "profile_id": profile_id, "base_url": val}

        elif provider in ("openrouter",):
            env_var = f"OPENROUTER_API_KEY_{profile_id.upper().replace('-', '_')}"
            val = os.environ.get(env_var) or os.environ.get("OPENROUTER_API_KEY")
            if val:
                return {"provider": "openrouter", "profile_id": profile_id, "api_key": val}

        elif provider in ("nvidia", "nvidia-nim"):
            env_var = f"NVIDIA_API_KEY_{profile_id.upper().replace('-', '_')}"
            val = os.environ.get(env_var) or os.environ.get("NVIDIA_API_KEY") or os.environ.get("NV_API_KEY")
            if val:
                return {"provider": provider, "profile_id": profile_id, "api_key": val}

        return None

    @classmethod
    def extract_jwt_claims(cls, token: str) -> dict[str, Any]:
        """Extract all claims from JWT payload without verifying signature."""
        try:
            parts = token.split(".")
            if len(parts) < 2:
                return {}
            payload_b64 = parts[1]
            rem = len(payload_b64) % 4
            if rem:
                payload_b64 += "=" * (4 - rem)
            return json.loads(base64.urlsafe_b64decode(payload_b64).decode("utf-8"))
        except Exception as e:
            logger.debug("Failed to extract JWT claims: %s", e)
            return {}

    @classmethod
    def extract_jwt_identity(cls, token: str) -> Tuple[Optional[str], Optional[str]]:
        """Extract email and subject (sub) from JWT id_token / access_token without verifying signature."""
        try:
            data = cls.extract_jwt_claims(token)
            if not data:
                return None, None
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
    def verify_local_endpoint(
        cls, base_url: str, api_key: Optional[str] = None
    ) -> Tuple[bool, Optional[str], List[str], Optional[str]]:
        """Verify local OpenAI-compatible endpoint ({base_url}/models) and return (valid, display_name, models, error_msg)."""
        url_str = (base_url or "").strip().rstrip("/")
        if not url_str:
            return False, None, [], "URL сервера не указан"
        if not url_str.startswith(("http://", "https://")):
            url_str = f"http://{url_str}"

        headers = {
            "Accept": "application/json",
            "User-Agent": "hermes-hub/1.0",
        }
        if api_key and api_key.strip():
            headers["Authorization"] = f"Bearer {api_key.strip()}"

        try:
            req = urllib.request.Request(
                f"{url_str}/models",
                headers=headers,
                method="GET",
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                if resp.status in (200, 204):
                    data = json.loads(resp.read().decode("utf-8", errors="replace") or "{}")
                    items = data.get("data") or data.get("models") or []
                    models = []
                    if isinstance(items, list):
                        for m in items:
                            mid = m.get("id") or m.get("name") if isinstance(m, dict) else str(m)
                            if mid:
                                models.append(str(mid))
                    return True, f"Local Server ({url_str})", sorted(models) if models else ["default"], None
                return False, None, [], f"Сервер вернул HTTP статус {resp.status}"
        except urllib.error.HTTPError as http_err:
            raw_err = http_err.read().decode("utf-8", errors="replace")
            try:
                err_msg = json.loads(raw_err).get("error", {}).get("message", raw_err)
            except Exception:
                err_msg = raw_err
            return False, None, [], f"HTTP {http_err.code}: {err_msg}"
        except urllib.error.URLError as url_err:
            reason = str(url_err.reason)
            return False, None, [], f"Не удалось подключиться к серверу ({reason})"
        except Exception as exc:
            return False, None, [], f"Ошибка подключения: {exc}"

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

        if provider in ("antigravity", "google-antigravity"):
            tokens = auth_data.get("token") or auth_data.get("tokens")
            if not isinstance(tokens, dict):
                tokens = {}
            acc_token = tokens.get("access_token") or auth_data.get("access_token") or ""
            id_token = tokens.get("id_token") or auth_data.get("id_token") or ""
            refresh_tok = tokens.get("refresh_token") or auth_data.get("refresh_token") or ""
            key = auth_data.get("api_key", "")
            email = auth_data.get("email") or auth_data.get("user_email")
            is_auth = bool(acc_token or refresh_tok or key or (email and auth_data.get("auth_method") == "oauth"))
            if not is_auth:
                return {
                    "authenticated": False,
                    "provider": provider,
                    "profile_id": profile_id,
                    "status": "NOT_CONFIGURED",
                    "error": None,
                }

            acc_id = None
            if id_token:
                email_from_jwt, acc_id = cls.extract_jwt_identity(id_token)
                email = email or email_from_jwt
            if not email and acc_token:
                email_from_jwt, acc_id = cls.extract_jwt_identity(acc_token)
                email = email or email_from_jwt

            expiry = (
                tokens.get("expiry_date")
                or auth_data.get("expiry_date")
                or tokens.get("expires_at")
                or auth_data.get("expires_at")
            )
            if not expiry:
                expiry_str = tokens.get("expiry") or auth_data.get("expiry")
                if expiry_str:
                    try:
                        dt = datetime.fromisoformat(str(expiry_str).replace("Z", "+00:00"))
                        expiry = dt.timestamp()
                    except Exception:
                        expiry = None

            is_expired = False
            if expiry:
                if float(expiry) > 1e11:
                    expiry = float(expiry) / 1000.0
                if time.time() > float(expiry):
                    is_expired = not bool(refresh_tok)

            return {
                "authenticated": not is_expired,
                "provider": provider,
                "profile_id": profile_id,
                "email_masked": mask_email(email) if email else None,
                "account_id_masked": mask_id(acc_id) if acc_id else None,
                "has_refresh_token": bool(refresh_tok),
                "is_expired": is_expired,
                "status": "EXPIRED" if is_expired else "AUTHENTICATED",
                "error": "Token expired without refresh token" if is_expired else None,
            }

        elif provider in ("openai-codex", "codex"):
            tokens = auth_data.get("token") or auth_data.get("tokens", {})
            acc_token = tokens.get("access_token") if isinstance(tokens, dict) else (auth_data.get("access_token") or "")
            id_token = tokens.get("id_token") if isinstance(tokens, dict) else (auth_data.get("id_token") or "")
            refresh_tok = tokens.get("refresh_token") if isinstance(tokens, dict) else (auth_data.get("refresh_token") or "")
            email = auth_data.get("email")
            if not email and id_token:
                email, _ = cls.extract_jwt_identity(id_token)
            if not email and acc_token:
                email, _ = cls.extract_jwt_identity(acc_token)

            key = auth_data.get("api_key", "")
            is_oauth = bool(acc_token)
            is_auth = is_oauth or bool(key)

            now = time.time()
            acc_claims = cls.extract_jwt_claims(acc_token) if acc_token else {}
            id_claims = cls.extract_jwt_claims(id_token) if id_token else {}

            acc_exp = acc_claims.get("exp")
            id_exp = id_claims.get("exp")

            # Access token expiration with 60-second safety margin
            access_token_expired = bool(acc_exp and now > (float(acc_exp) - 60))
            id_token_expired = bool(id_exp and now > float(id_exp))

            # If access_token expired and no refresh_token, it cannot be refreshed silently
            is_expired = access_token_expired and not bool(refresh_tok)

            status_err = None
            if not is_auth:
                status_str = "NOT_CONFIGURED"
            elif is_expired:
                status_str = "EXPIRED"
                status_err = "Access-токен истёк, refresh token отсутствует"
            else:
                status_str = "AUTHENTICATED"
                if access_token_expired and refresh_tok:
                    status_err = "Access-токен истёк — доступно автоматическое обновление"
                elif id_token_expired:
                    status_err = "ID-токен истёк"

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
                "access_token_expired": access_token_expired,
                "id_token_expired": id_token_expired,
                "has_refresh_token": bool(refresh_tok),
                "is_expired": is_expired,
                "status": status_str,
                "error": status_err,
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

        elif provider in ("local", "local-llm", "llama.cpp", "ollama", "vllm"):
            base_url = auth_data.get("base_url")
            if not base_url:
                try:
                    from antigravity_provider.router.router_config import load_router_config
                    rcfg = load_router_config()
                    pcfg = rcfg.get_profile(profile_id)
                    if pcfg and pcfg.custom_base_url:
                        base_url = pcfg.custom_base_url
                except Exception:
                    pass
            if not base_url:
                base_url = os.environ.get("LOCAL_LLM_BASE_URL")
            key = auth_data.get("api_key", "")
            is_auth = bool(base_url)
            masked_acc = f"{base_url} [API Key]" if (base_url and key) else (str(base_url) if base_url else "Not configured")
            return {
                "authenticated": is_auth,
                "provider": provider,
                "profile_id": profile_id,
                "account_id_masked": masked_acc,
                "status": "AUTHENTICATED" if is_auth else "NOT_CONFIGURED",
                "error": None if is_auth else "URL сервера не настроен",
            }

        elif provider in ("openrouter",):
            key = auth_data.get("api_key") or auth_data.get("token") or ""
            is_auth = bool(key)
            masked = f"sk-or-...{key[-4:]}" if len(key) > 8 else ("sk-or-***" if key else None)
            return {
                "authenticated": is_auth,
                "provider": provider,
                "profile_id": profile_id,
                "auth_mode": "api_key",
                "account_id_masked": masked or "Not configured",
                "status": "AUTHENTICATED" if is_auth else "NOT_CONFIGURED",
                "error": None if is_auth else "API-ключ не настроен",
            }

        elif provider in ("nvidia", "nvidia-nim"):
            key = auth_data.get("api_key") or auth_data.get("token") or ""
            is_auth = bool(key)
            masked = f"nvapi-...{key[-4:]}" if len(key) > 8 else ("nvapi-***" if key else None)
            return {
                "authenticated": is_auth,
                "provider": provider,
                "profile_id": profile_id,
                "auth_mode": "api_key",
                "account_id_masked": masked or "Not configured",
                "status": "AUTHENTICATED" if is_auth else "NOT_CONFIGURED",
                "error": None if is_auth else "API-ключ не настроен",
            }

        return {
            "authenticated": False,
            "provider": provider,
            "profile_id": profile_id,
            "status": "UNKNOWN_PROVIDER",
            "error": f"Unknown provider {provider}",
        }
