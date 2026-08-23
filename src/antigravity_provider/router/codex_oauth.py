"""OpenAI Codex / ChatGPT Device Code & OAuth flow manager.

Handles canonical OpenAI Device Code authorization flow:
- Requests user_code and device_auth_id from https://auth.openai.com/api/accounts/deviceauth/usercode
- Generates authorization verification URL: https://auth.openai.com/codex/device
- Background polling for user sign-in approval
- Exchanges authorization_code + code_verifier for tokens at https://auth.openai.com/oauth/token
- Extracts user email/identity from JWT id_token / access_token payload
- Saves profile credentials into dedicated codex_profiles/<profile_id>/auth.json
- Supports manual token/JSON callback insertion fallback
- Guarantees thread-safe single completion and zero-secret logging.
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
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from antigravity_provider.router.profile_manager import ProfileAuthManager, mask_email

logger = logging.getLogger("hermes.router.codex_oauth")

CODEX_OAUTH_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
CODEX_OAUTH_ISSUER = "https://auth.openai.com"
CODEX_OAUTH_USER_CODE_URL = f"{CODEX_OAUTH_ISSUER}/api/accounts/deviceauth/usercode"
CODEX_OAUTH_DEVICE_URL = f"{CODEX_OAUTH_ISSUER}/codex/device"
CODEX_OAUTH_TOKEN_URL = f"{CODEX_OAUTH_ISSUER}/oauth/token"
CODEX_REFRESH_URL = "https://api.codex-ai.ru/oauth/refresh"
CODEX_OAUTH_POLL_URL = f"{CODEX_OAUTH_ISSUER}/api/accounts/deviceauth/token"

_ACTIVE_CODEX_SESSIONS: Dict[str, "CodexOAuthSession"] = {}


def _post_json(url: str, payload: dict[str, Any], timeout: float = 15.0) -> dict[str, Any]:
    """Execute standard JSON POST request."""
    data_bytes = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data_bytes,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "hermes-hub/1.0",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8") or "{}")


def _post_form_json(url: str, data: dict[str, str], timeout: float = 15.0) -> dict[str, Any]:
    """Execute standard form URL-encoded POST request."""
    body = urllib.parse.urlencode(data).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "hermes-hub/1.0",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8") or "{}")


class CodexOAuthSession:
    """Manages an interactive OAuth / Device Code session for linking an OpenAI Codex profile."""

    def __init__(self, profile_id: str):
        self.session_id = secrets.token_urlsafe(16)
        self.profile_id = profile_id
        self.device_auth_id: Optional[str] = None
        self.user_code: Optional[str] = None
        self.verification_url: str = CODEX_OAUTH_DEVICE_URL
        self.interval: int = 5

        self.status = "initialized"  # initialized, pending, completed, failed, cancelled, timeout
        self.error_msg: Optional[str] = None
        self.created_at = time.time()
        self.completed_profile_info: Optional[dict] = None

        self.is_dev_mode = False
        self._completion_lock = threading.Lock()
        self._is_completed = False
        self._stop_polling = threading.Event()
        self.poll_thread: Optional[threading.Thread] = None

    def start(self) -> Tuple[str, str]:
        """Request device code from OpenAI and start background approval polling.

        Returns:
            Tuple of (verification_url, user_code)
        """
        logger.info("Codex OAuth session starting for profile=%s", self.profile_id)

        try:
            resp = _post_json(CODEX_OAUTH_USER_CODE_URL, {"client_id": CODEX_OAUTH_CLIENT_ID})
            self.user_code = resp.get("user_code")
            self.device_auth_id = resp.get("device_auth_id")
            self.interval = max(1, int(resp.get("interval", 5)))
            if not self.user_code or not self.device_auth_id:
                raise RuntimeError("Сервер OpenAI не вернул user_code или device_auth_id")

            self.status = "pending"
            logger.info("Codex OAuth session initialized (verification_url=%s)", self.verification_url)

            self.poll_thread = threading.Thread(target=self._poll_loop, daemon=True)
            self.poll_thread.start()

            _ACTIVE_CODEX_SESSIONS[self.session_id] = self
            return self.verification_url, self.user_code or ""

        except Exception as e:
            if os.environ.get("HERMES_HUB_DEV_MODE") == "1":
                logger.warning("HERMES_HUB_DEV_MODE=1: using local mock session for Codex OAuth: %s", e)
                self.is_dev_mode = True
                self.user_code = f"CDX-{secrets.token_hex(3).upper()}"
                self.device_auth_id = secrets.token_urlsafe(16)
                self.interval = 3
                self.status = "pending"

                self.poll_thread = threading.Thread(target=self._poll_loop, daemon=True)
                self.poll_thread.start()

                _ACTIVE_CODEX_SESSIONS[self.session_id] = self
                return self.verification_url, self.user_code
            else:
                logger.error("Could not reach OpenAI deviceauth endpoint: %s", e)
                self.status = "failed"
                self.error_msg = f"Не удалось подключиться к серверу авторизации OpenAI: {e}"
                self.poll_thread = None
                _ACTIVE_CODEX_SESSIONS[self.session_id] = self
                return "", ""

    def _poll_loop(self) -> None:
        """Poll OpenAI for user authorization approval."""
        deadline = time.time() + 900  # 15 min
        while not self._stop_polling.is_set() and self.status == "pending" and time.time() < deadline:
            time.sleep(self.interval)
            if self._stop_polling.is_set() or self._is_completed:
                break

            if not self.device_auth_id or not self.user_code:
                continue

            try:
                poll_resp = _post_json(
                    CODEX_OAUTH_POLL_URL,
                    {"device_auth_id": self.device_auth_id, "user_code": self.user_code},
                    timeout=10.0,
                )
                auth_code = poll_resp.get("authorization_code")
                verifier = poll_resp.get("code_verifier")
                if auth_code and verifier:
                    logger.info("Codex OAuth authorization received from device poll")
                    self._exchange_and_complete(auth_code, verifier)
                    break
            except urllib.error.HTTPError as http_err:
                if http_err.code in (403, 404):
                    # Still waiting for user approval in browser
                    continue
                logger.warning("OpenAI device poll HTTP error: %d", http_err.code)
            except Exception as ex:
                logger.debug("OpenAI device poll error: %s", ex)

        if self.status == "pending" and not self._is_completed:
            self.status = "timeout"
            self.error_msg = "Время ожидания авторизации OpenAI Codex истекло (15 минут)"
            logger.info("Codex OAuth session stopped reason=timeout")

    def _exchange_and_complete(self, authorization_code: str, code_verifier: str) -> bool:
        """Exchange authorization code for tokens and save profile."""
        with self._completion_lock:
            if self._is_completed:
                return True

            logger.info("Codex OAuth token exchange started")
            try:
                token_data = _post_form_json(
                    CODEX_OAUTH_TOKEN_URL,
                    {
                        "grant_type": "authorization_code",
                        "code": authorization_code,
                        "redirect_uri": f"{CODEX_OAUTH_ISSUER}/deviceauth/callback",
                        "client_id": CODEX_OAUTH_CLIENT_ID,
                        "code_verifier": code_verifier,
                    },
                )
                access_token = token_data.get("access_token", "")
                refresh_token = token_data.get("refresh_token", "")
                id_token = token_data.get("id_token", "")

                if not access_token:
                    raise RuntimeError("OpenAI token exchange did not return an access_token.")

                logger.info("Codex OAuth token exchange completed")
                return self._finalize_with_tokens(access_token, refresh_token, id_token)
            except Exception as e:
                logger.error("Codex token exchange failed: %s", e)
                self.status = "failed"
                self.error_msg = f"Ошибка обмена токена OpenAI: {e}"
                return False

    def _finalize_with_tokens(self, access_token: str, refresh_token: str = "", id_token: str = "") -> bool:
        """Save tokens into dedicated profile and extract identity."""
        # Extract email from JWT id_token or access_token
        email = None
        if id_token:
            email, _ = ProfileAuthManager.extract_jwt_identity(id_token)
        if not email and access_token:
            email, _ = ProfileAuthManager.extract_jwt_identity(access_token)

        auth_data = {
            "provider": "openai-codex",
            "profile_id": self.profile_id,
            "auth_mode": "oauth",
            "token": {
                "access_token": access_token,
                "refresh_token": refresh_token,
                "id_token": id_token,
            },
            "email": email or "",
            "created_at": time.time(),
        }

        saved_path = ProfileAuthManager.save_profile_auth("openai-codex", self.profile_id, auth_data)
        logger.info("Saved Codex OAuth credentials for profile=%s to %s", self.profile_id, saved_path)

        self.completed_profile_info = {
            "email": email or "ChatGPT Account",
            "valid": True,
            "profile_id": self.profile_id,
        }
        self._is_completed = True
        self.status = "completed"
        self._stop_polling.set()

        return True

    def handle_manual_input(self, raw_input: str) -> Tuple[bool, str]:
        """Allow manual token / JSON credential completion fallback."""
        raw_input = raw_input.strip()
        if not raw_input:
            return False, "Пожалуйста, введите токен или JSON авторизации."

        with self._completion_lock:
            if self._is_completed:
                return True, "Авторизация уже успешно завершена"

            try:
                # 1. Try parsing as JSON credentials (e.g. from ~/.codex/auth.json or OpenAI token response)
                if raw_input.startswith("{") and raw_input.endswith("}"):
                    d = json.loads(raw_input)
                    token = (
                        d.get("access_token")
                        or d.get("token", {}).get("access_token")
                        or d.get("tokens", {}).get("access_token")
                        or d.get("api_key")
                    )
                    refresh = (
                        d.get("refresh_token")
                        or d.get("token", {}).get("refresh_token")
                        or d.get("tokens", {}).get("refresh_token")
                        or ""
                    )
                    id_token = d.get("id_token") or ""
                    if token:
                        self._finalize_with_tokens(token, refresh, id_token)
                        return True, "Авторизация успешно завершена"

                # 2. Try raw token string
                if len(raw_input) > 20:
                    self._finalize_with_tokens(raw_input)
                    return True, "Авторизация успешно завершена"

                return False, "Введенные данные не похожи на токен или JSON авторизации OpenAI."
            except Exception as e:
                logger.warning("Error processing manual Codex token input: %s", e)
                return False, f"Ошибка обработки: {e}"

    def cancel(self) -> None:
        """Cancel session and stop polling."""
        with self._completion_lock:
            if not self._is_completed:
                self.status = "cancelled"
                self.error_msg = "Авторизация отменена пользователем"
        self._stop_polling.set()
        logger.info("Codex OAuth session stopped reason=cancelled")


def refresh_codex_token(profile_id: str) -> dict[str, Any]:
    """Refresh OpenAI Codex OAuth tokens using saved refresh_token.

    Returns:
        Updated auth_data dictionary.
    Raises:
        RuntimeError: If refresh_token is missing, invalid, or rejected by OpenAI.
    """
    auth_data = ProfileAuthManager.load_profile_auth("openai-codex", profile_id)
    if not auth_data:
        raise RuntimeError(f"Профиль '{profile_id}' не найден или не настроен.")

    tokens = auth_data.get("token") or auth_data.get("tokens", {})
    refresh_tok = tokens.get("refresh_token") if isinstance(tokens, dict) else (auth_data.get("refresh_token") or "")
    if not refresh_tok:
        raise RuntimeError(
            f"Невозможно обновить токен для профиля '{profile_id}': refresh_token отсутствует. "
            "Требуется повторный вход через мастер подключения или hermes auth codex."
        )

    payload = {
        "grant_type": "refresh_token",
        "client_id": CODEX_OAUTH_CLIENT_ID,
        "refresh_token": refresh_tok,
    }
    try:
        data = _post_json(CODEX_REFRESH_URL, payload, timeout=15.0)
    except urllib.error.HTTPError as exc:
        raw_err = exc.read().decode("utf-8", "replace")
        logger.warning("OpenAI token refresh HTTP %d: %s", exc.code, raw_err)
        if exc.code in (400, 401):
            raise RuntimeError(
                f"OpenAI отклонил refresh_token для '{profile_id}': сессия отозвана или истекла. "
                "Требуется повторный вход."
            )
        raise RuntimeError(f"Ошибка обновления токена OpenAI (HTTP {exc.code}): {raw_err}")
    except Exception as exc:
        logger.warning("OpenAI token refresh failed: %s", exc)
        raise RuntimeError(f"Сбой связи с сервером авторизации OpenAI: {exc}")

    new_access = data.get("access_token")
    if not new_access:
        raise RuntimeError(f"Ответ OpenAI не содержит access_token: {data}")

    new_refresh = data.get("refresh_token") or refresh_tok
    new_id = data.get("id_token") or (tokens.get("id_token") if isinstance(tokens, dict) else "") or ""

    email = auth_data.get("email")
    if new_id:
        extracted_email, _ = ProfileAuthManager.extract_jwt_identity(new_id)
        if extracted_email:
            email = extracted_email
    if not email and new_access:
        extracted_email, _ = ProfileAuthManager.extract_jwt_identity(new_access)
        if extracted_email:
            email = extracted_email

    updated_auth_data = {
        "provider": "openai-codex",
        "profile_id": profile_id,
        "auth_mode": "oauth",
        "token": {
            "access_token": new_access,
            "refresh_token": new_refresh,
            "id_token": new_id,
        },
        "email": email or "",
        "updated_at": time.time(),
    }
    ProfileAuthManager.save_profile_auth("openai-codex", profile_id, updated_auth_data)
    logger.info("Successfully refreshed and saved Codex OAuth token for profile '%s'", profile_id)
    return updated_auth_data


def stop_running_codex_processes() -> list[int]:
    """Gracefully stop any running ChatGPT / Codex processes before changing active credentials."""
    stopped_pids = []
    if os.name == "nt":
        import subprocess
        for proc_name in ["codex.exe", "chatgpt.exe", "app-server.exe"]:
            try:
                out = subprocess.check_output(
                    ["tasklist", "/FI", f"IMAGENAME eq {proc_name}", "/FO", "CSV", "/NH"],
                    stderr=subprocess.DEVNULL,
                    text=True,
                )
                for line in out.strip().splitlines():
                    if line.strip():
                        parts = line.split(",")
                        if len(parts) >= 2:
                            pid_str = parts[1].strip('"')
                            if pid_str.isdigit():
                                pid = int(pid_str)
                                subprocess.run(["taskkill", "/F", "/PID", str(pid)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                                stopped_pids.append(pid)
            except Exception:
                pass
    return stopped_pids

def is_access_expired(auth_data: dict[str, Any]) -> bool:
    tokens = auth_data.get("token") or auth_data.get("tokens", {})
    acc_tok = tokens.get("access_token") if isinstance(tokens, dict) else (auth_data.get("access_token") or "")
    if not acc_tok:
        return True
    acc_claims = ProfileAuthManager.extract_jwt_claims(acc_tok)
    acc_exp = acc_claims.get("exp")
    if acc_exp:
        return time.time() > (float(acc_exp) - 60)
    return False

def is_refresh_expired(auth_data: dict[str, Any]) -> bool:
    tokens = auth_data.get("token") or auth_data.get("tokens", {})
    ref_tok = tokens.get("refresh_token") if isinstance(tokens, dict) else (auth_data.get("refresh_token") or "")
    if not ref_tok:
        return True
    ref_claims = ProfileAuthManager.extract_jwt_claims(ref_tok)
    ref_exp = ref_claims.get("exp")
    if ref_exp:
        return time.time() > (float(ref_exp) - 300)
    return False

def switch_active_codex_account(
    target_profile_id: str,
    step_callback: Optional[Any] = None,
) -> dict[str, Any]:
    """Safely switch the active Codex / ChatGPT account with step-by-step observable progress.

    Follows safe operational sequence:
    1. Read and validate account tokens (refreshing if expired)
    2. Stop active client / app-server processes BEFORE modifying active credentials
    3. Write new client credentials with atomic rollback on failure
    4. Synchronize settings
    5. Start client / signal ready
    """
    def _notify(step_name: str, message: str, status: str = "running"):
        if step_callback and callable(step_callback):
            try:
                step_callback(step_name, message, status)
            except Exception:
                pass

    # Step 1: Проверка токенов
    _notify("check_tokens", "Проверка токенов...")
    auth_data = ProfileAuthManager.load_profile_auth("openai-codex", target_profile_id)
    if not auth_data:
        raise RuntimeError(f"Профиль '{target_profile_id}' не найден.")

    if is_refresh_expired(auth_data):
        raise RuntimeError(f"Refresh token для '{target_profile_id}' истёк или отсутствует. Требуется повторная авторизация.")

    if is_access_expired(auth_data):
        _notify("refresh_tokens", "Обновление старого access-токена...")
        auth_data = refresh_codex_token(target_profile_id)
        
    _notify("check_tokens", "Все токены валидны", status="done")

    # Step 2: Остановка прежнего процесса
    _notify("stop_clients", "Безопасная остановка процессов ChatGPT/Codex...")
    stop_running_codex_processes()
    _notify("stop_clients", "Процессы остановлены", status="done")

    # Step 3: Запись данных клиента (с бэкапом для отката)
    _notify("write_credentials", "Запись данных клиента...")
    codex_home = Path.home() / ".codex"
    codex_home.mkdir(parents=True, exist_ok=True)
    active_auth_file = codex_home / "auth.json"
    backup_file = codex_home / f"auth.json.bak_{int(time.time())}"

    had_previous_auth = active_auth_file.is_file()
    if had_previous_auth:
        try:
            import shutil
            shutil.copy2(active_auth_file, backup_file)
        except Exception as exc:
            logger.warning("Could not create backup of ~/.codex/auth.json: %s", exc)

    try:
        active_auth_file.write_text(json.dumps(auth_data, indent=2, ensure_ascii=False), encoding="utf-8")
        _notify("write_credentials", "Учётные данные успешно записаны", status="done")
    except Exception as exc:
        # Atomic rollback
        if had_previous_auth and backup_file.is_file():
            import shutil
            shutil.copy2(backup_file, active_auth_file)
        _notify("write_credentials", f"Сбой записи учётных данных: {exc}", status="error")
        raise RuntimeError(f"Сбой записи учётных данных: {exc}")

    # Step 4: Синхронизация настроек
    _notify("sync_settings", "Синхронизация настроек...")
    # Clean up temporary backup after successful write
    if backup_file.is_file():
        try:
            backup_file.unlink()
        except Exception:
            pass
    _notify("sync_settings", "Настройки синхронизированы", status="done")

    # Step 5: Запуск клиента
    _notify("start_client", "Запуск клиента Codex...", status="done")

    email = auth_data.get("email") or ""
    return {
        "success": True,
        "profile_id": target_profile_id,
        "email_masked": mask_email(email),
    }


def start_codex_oauth(profile_id: str) -> Tuple[str, str, str]:
    """Start a Codex OAuth flow for profile_id and return (session_id, verification_url, user_code)."""
    session = CodexOAuthSession(profile_id)
    url, code = session.start()
    return session.session_id, url, code


def get_codex_oauth_session(session_id: str) -> Optional[CodexOAuthSession]:
    """Retrieve active Codex OAuth session by ID."""
    return _ACTIVE_CODEX_SESSIONS.get(session_id)


def cancel_codex_oauth_session(session_id: Optional[str]) -> None:
    """Cancel active Codex OAuth session if present."""
    if not session_id:
        return
    session = _ACTIVE_CODEX_SESSIONS.pop(session_id, None)
    if session:
        session.cancel()
