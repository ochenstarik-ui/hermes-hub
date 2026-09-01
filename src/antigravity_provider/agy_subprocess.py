"""AGY subprocess backend for the Antigravity Hermes provider plugin.

Routes chat-completion requests through the locally-installed ``agy`` CLI
instead of making direct HTTP calls to the Cloud Code Assist API.  This
avoids the 429 RESOURCE_EXHAUSTED errors seen with direct API access while
reusing agy's existing authentication session.

Usage (from hermes_plugin.py middleware)::

    from .agy_subprocess import agy_generate
    completion_dict = agy_generate(openai_request_dict)
"""

from __future__ import annotations

import json
import logging
import os
import re
import secrets
import shlex
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# AGY executable discovery
# ---------------------------------------------------------------------------

_agy_exe_cache: str | None = None


def _find_agy_exe() -> str:
    """Locate the ``agy`` (or ``agy.exe``) binary.

    Resolution order:
      1. ``AGY_EXE_PATH`` environment variable (explicit override)
      2. ``%LOCALAPPDATA%/agy/bin/agy.exe`` (standard Windows install)
      3. ``PATH`` lookup via :func:`shutil.which`
    """
    # 1. Explicit env var
    env = os.environ.get("AGY_EXE_PATH", "").strip()
    if env and Path(env).is_file():
        return env

    # 2. Стандартные места установки.
    #
    # Раньше проверялась только раскладка Windows (%LOCALAPPDATA%/agy/bin), а в
    # Linux agy ставится в ~/.local/bin. Хаб запускается с урезанным окружением,
    # где этого каталога в PATH нет, и вход в Antigravity падал с «agy executable
    # not found» при установленной и работающей утилите.
    from antigravity_provider.paths import get_hermes_home

    exe_name = "agy.exe" if os.name == "nt" else "agy"
    candidates = [
        get_hermes_home().parent / "agy" / "bin" / exe_name,
        Path.home() / ".local" / "bin" / exe_name,
        Path("/usr/local/bin") / exe_name,
        Path("/usr/bin") / exe_name,
        Path("/snap/bin") / exe_name,
    ]
    checked = []
    for candidate in candidates:
        checked.append(str(candidate))
        try:
            if candidate.is_file():
                return str(candidate)
        except OSError as exc:
            # Каталог может быть закрыт правами: это «не смогли проверить»,
            # а не «файла нет».
            checked[-1] = f"{candidate} (нет доступа: {exc.strerror or exc})"

    # 3. PATH
    found = shutil.which("agy") or shutil.which("agy.exe")
    if found:
        return found

    raise FileNotFoundError(
        "Утилита agy не найдена. Проверено: "
        + "; ".join(checked)
        + "; и PATH процесса. Задайте путь переменной AGY_EXE_PATH либо установите agy."
    )


def get_agy_exe() -> str:
    """Return the cached path to the ``agy`` binary."""
    global _agy_exe_cache
    if _agy_exe_cache is None:
        _agy_exe_cache = _find_agy_exe()
    return _agy_exe_cache


# ---------------------------------------------------------------------------
# Model discovery (dynamic — no hard-coded catalog)
# ---------------------------------------------------------------------------

# Maps *display* base names (lowered, dashed) → confirmed agy CLI model ids.
# Populated lazily by :func:`discover_models`.
_AGY_MODEL_CACHE: dict[str, str] | None = None

# Maps agy CLI model id → set of supported effort levels.
# Populated alongside _AGY_MODEL_CACHE by :func:`discover_models`.
_AGY_EFFORT_MAP: dict[str, set[str]] = {}


def _display_to_cli(display_name: str) -> tuple[str, str]:
    """Convert ``'Gemini 3.7 Flash (High)'`` → ``('gemini-3.7-flash', 'high')``.

    Returns ``(cli_model, effort)``.
    """
    m = re.match(r"^(.+?)\s*\((\w+)\)\s*$", display_name.strip())
    if not m:
        return display_name.strip().lower().replace(" ", "-"), ""
    raw_name = m.group(1).strip()
    effort = m.group(2).strip().lower()
    # Normalise: lower-case, replace spaces with dashes
    cli = raw_name.lower().replace(" ", "-")
    # "4.6" → "4-6" only for non-gemini (gemini keeps dots: 3.7, 3.6 …)
    if not cli.startswith("gemini"):
        cli = cli.replace(".", "-")
    return cli, effort


def discover_models(profile_id: str | None = None) -> dict[str, str]:
    """Discover available models by querying ``agy models``.

    Returns a dict mapping *hermes-style* model ids
    (``google-antigravity/gemini-3.7-flash``) to *agy CLI* model ids
    (``gemini-3.7-flash``).  The result is cached for the process lifetime.

    Also populates :data:`_AGY_EFFORT_MAP` with supported efforts per model.
    """
    global _AGY_MODEL_CACHE, _AGY_EFFORT_MAP
    if profile_id is None and _AGY_MODEL_CACHE:
        return dict(_AGY_MODEL_CACHE)

    exe = get_agy_exe()

    # agy читает учётные данные из $HOME/$USERPROFILE, а адаптер подменяет их
    # на каталог профиля — так шесть аккаунтов и сосуществуют. Раньше эта
    # команда запускалась в ГЛОБАЛЬНОМ окружении, где вход не выполнен, и
    # отвечала «Please sign in to view available models» — при шести рабочих
    # OAuth-профилях. Список моделей поэтому был пуст всегда.
    target_profile_id = profile_id
    if target_profile_id:
        try:
            from antigravity_provider.router.profile_manager import ProfileAuthManager
            st = ProfileAuthManager.get_profile_status("antigravity", target_profile_id)
            if not st.get("authenticated") and not ProfileAuthManager.load_profile_auth("antigravity", target_profile_id):
                target_profile_id = None
        except Exception:
            pass

    if not target_profile_id:
        try:
            from antigravity_provider.paths import get_hermes_home
            from antigravity_provider.router.profile_manager import ProfileAuthManager
            from antigravity_provider.router.router_config import load_router_config

            candidate_pids: list[str] = []
            try:
                cfg = load_router_config()
                for pid, pcfg in cfg.profiles.items():
                    if pcfg.provider.lower() in ("antigravity", "google-antigravity") and pid not in candidate_pids:
                        candidate_pids.append(pid)
            except Exception:
                pass

            main_p = ProfileAuthManager.get_main_profile("antigravity")
            if main_p and main_p not in candidate_pids:
                candidate_pids.append(main_p)

            standard_slots = (
                ["ag-orch-primary", "ag-orch-fallback"]
                + [f"ag-{i}" for i in range(1, 21)]
                + [f"ag-w{i}" for i in range(1, 11)]
            )
            for s in standard_slots:
                if s not in candidate_pids:
                    candidate_pids.append(s)

            try:
                agy_dir = get_hermes_home() / "agy_profiles"
                if agy_dir.is_dir():
                    for sub in sorted(agy_dir.iterdir()):
                        if sub.is_dir() and sub.name not in candidate_pids:
                            candidate_pids.append(sub.name)
            except Exception:
                pass

            for candidate in candidate_pids:
                st = ProfileAuthManager.get_profile_status("antigravity", candidate)
                if st.get("authenticated") or ProfileAuthManager.load_profile_auth("antigravity", candidate):
                    target_profile_id = candidate
                    break
        except Exception:
            target_profile_id = None

    if target_profile_id:
        from antigravity_provider.router.adapters.antigravity_adapter import get_profile_env_dir

        profile_dir = get_profile_env_dir(target_profile_id)
        env = build_safe_subprocess_env(
            overrides={
                "USERPROFILE": str(profile_dir),
                "HOME": str(profile_dir),
                "HOMEPATH": str(profile_dir),
            }
        )
    else:
        env = build_safe_subprocess_env()

    try:
        result = subprocess.run(
            [exe, "models"],
            capture_output=True,
            text=True,
            timeout=60,
            encoding="utf-8",
            errors="replace",
            env=env,
            stdin=subprocess.DEVNULL,
            **hidden_process_kwargs(),
        )
        raw = result.stdout.strip()
        if not raw or result.returncode != 0:
            if profile_id:
                # Прежнее сообщение «код 1; каталог не получен» скрывало причину.
                # agy пишет её в stderr, и без неё непонятно главное: он
                # запускается с HOME, подменённым на каталог профиля (ради
                # изоляции учётных данных между аккаунтами). Если вход
                # выполнялся обычным agy в оболочке, ключи легли в настоящий
                # домашний каталог, и профиль пуст — отсюда отказ.
                detail = (result.stderr or "").strip() or (result.stdout or "").strip()
                detail = detail.splitlines()[-1][:300] if detail else "вывод пуст"
                raise RuntimeError(
                    f"agy models: код {result.returncode}. Ответ agy: {detail}. "
                    f"Запуск с HOME={env.get('HOME') or env.get('USERPROFILE') or 'не задан'}"
                )
            return dict(_AGY_MODEL_CACHE or {})
    except Exception:
        if profile_id:
            raise
        return dict(_AGY_MODEL_CACHE or {})

    models: dict[str, str] = {}
    effort_map: dict[str, set[str]] = {}
    
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.lower().startswith("model"):
            continue
            
        parts = line.split('\t')
        cli_model = parts[0].strip()
        if not cli_model:
            continue
            
        hermes_id = f"google-antigravity/{cli_model}"
        models[hermes_id] = cli_model
        if cli_model not in effort_map:
            effort_map[cli_model] = set()
            
        # Parse effort from description or known capabilities if needed
        # Assuming effort is not explicitly provided in the tabbed output or we extract it
        if len(parts) > 1:
            desc = parts[1].strip().lower()
            if "(high)" in desc:
                effort_map[cli_model].add("high")
            if "(low)" in desc:
                effort_map[cli_model].add("low")
            if "(medium)" in desc:
                effort_map[cli_model].add("medium")

    _AGY_MODEL_CACHE = models
    _AGY_EFFORT_MAP = effort_map
    logger.info(
        "discover_models: found %d models, efforts=%s",
        len(models),
        {k: sorted(v) for k, v in effort_map.items()},
    )
    return dict(models)


def check_profile_native_auth_status(profile_id: str) -> tuple[bool, str | None, dict[str, Any] | None]:
    """Check if agy native authentication has completed in profile's directory.

    Returns (is_authenticated, email, auth_data).
    A22/A57 Requirement: Detection without credential logging or stream interception.
    Checks .gemini/antigravity-cli/antigravity-oauth-token first, then .gemini/oauth_creds.json.
    """
    from antigravity_provider.router.adapters.antigravity_adapter import get_profile_env_dir

    profile_dir = get_profile_env_dir(profile_id)
    gemini_dir = profile_dir / ".gemini"
    cli_dir = gemini_dir / "antigravity-cli"
    cli_token_file = cli_dir / "antigravity-oauth-token"
    creds_file = gemini_dir / "oauth_creds.json"
    accounts_file = gemini_dir / "google_accounts.json"
    auth_file = profile_dir / "auth.json"

    token_data: dict[str, Any] | None = None
    auth_method: str = "consumer"

    # 1. Primary source: agy 2.0 native token file (.gemini/antigravity-cli/antigravity-oauth-token)
    if cli_token_file.is_file() and cli_token_file.stat().st_size > 0:
        try:
            cli_raw = json.loads(cli_token_file.read_text(encoding="utf-8"))
            if isinstance(cli_raw, dict):
                auth_method = cli_raw.get("auth_method", "consumer")
                inner = cli_raw.get("token")
                if isinstance(inner, dict):
                    token_data = inner
                elif "access_token" in cli_raw or "refresh_token" in cli_raw:
                    token_data = cli_raw
        except Exception as exc:
            logger.debug("Error reading cli_token_file for %s: %s", profile_id, exc)

    # 2. Secondary source: Gemini CLI legacy credentials (.gemini/oauth_creds.json)
    if not token_data and creds_file.is_file() and creds_file.stat().st_size > 0:
        try:
            creds_raw = json.loads(creds_file.read_text(encoding="utf-8"))
            if isinstance(creds_raw, dict):
                token_data = creds_raw
                auth_method = "oauth"
        except Exception as exc:
            logger.debug("Error reading creds_file for %s: %s", profile_id, exc)

    # 3. Third source: existing auth.json
    if not token_data and auth_file.is_file() and auth_file.stat().st_size > 0:
        try:
            a_raw = json.loads(auth_file.read_text(encoding="utf-8"))
            if isinstance(a_raw, dict):
                inner = a_raw.get("token") or a_raw.get("tokens")
                if isinstance(inner, dict):
                    token_data = inner
                    auth_method = a_raw.get("auth_method", "oauth")
        except Exception as exc:
            logger.debug("Error reading auth_file for %s: %s", profile_id, exc)

    if not token_data or not isinstance(token_data, dict):
        return False, None, None

    access_token = token_data.get("access_token")
    refresh_token = token_data.get("refresh_token")
    if not access_token and not refresh_token:
        return False, None, None

    # Extract email identity truthfully (P0-3: do not invent)
    email: str | None = None
    if accounts_file.is_file() and accounts_file.stat().st_size > 0:
        try:
            acc_data = json.loads(accounts_file.read_text(encoding="utf-8"))
            if isinstance(acc_data, dict) and acc_data.get("active"):
                em = str(acc_data["active"]).strip()
                if "@" in em:
                    email = em
        except Exception:
            email = None

    if not email and auth_file.is_file():
        try:
            a_data = json.loads(auth_file.read_text(encoding="utf-8"))
            if isinstance(a_data, dict):
                em = a_data.get("email") or a_data.get("user_email")
                if em and "@" in str(em):
                    email = str(em).strip()
        except Exception:
            pass

    if not email:
        from antigravity_provider.router.profile_manager import ProfileAuthManager

        id_token = token_data.get("id_token")
        if id_token:
            jwt_email, _ = ProfileAuthManager.extract_jwt_identity(str(id_token))
            if jwt_email and "@" in jwt_email:
                email = jwt_email

    # Токен доступа Google (ya29....) — не JWT, разбирать его как JWT
    # бессмысленно. Почту по нему отдаёт UserInfo, и этим же путём её узнаёт
    # браузерный вход. Без почты не срабатывает проверка двойников, и один
    # аккаунт снова расползётся по слотам — ровно та беда, которую чинили.
    #
    # Спрашиваем провайдера, только если в самом профиле почты не нашлось:
    # у свежего слота нет ни google_accounts.json, ни auth.json, а файл
    # antigravity-oauth-token (505 байт у владельца) id_token не содержит.
    if not email and access_token:
        try:
            from antigravity_provider.oauth import fetch_user_email

            remote_email = fetch_user_email(str(access_token))
            if remote_email and "@" in remote_email:
                email = remote_email.strip()
        except Exception as exc:
            # Отказ сети не должен ронять вход: аккаунт подключён, почта — Н/Д.
            logger.info("Почту через UserInfo установить не удалось: %s", exc)

    auth_data = {
        "auth_method": auth_method,
        "email": email or "",
        "token": token_data,
        "updated_at": time.time(),
    }

    # Keep profile's auth.json in sync
    auth_file = profile_dir / "auth.json"
    if not auth_file.is_file():
        try:
            auth_file.write_text(json.dumps(auth_data, indent=2, ensure_ascii=False), encoding="utf-8")
            os.chmod(auth_file, 0o600)
        except Exception:
            pass

    # Ensure profile permissions (0700 on dirs, 0600 on files)
    try:
        os.chmod(profile_dir, 0o700)
        if gemini_dir.is_dir():
            os.chmod(gemini_dir, 0o700)
        if cli_dir.is_dir():
            os.chmod(cli_dir, 0o700)
        if cli_token_file.is_file():
            os.chmod(cli_token_file, 0o600)
        if creds_file.is_file():
            os.chmod(creds_file, 0o600)
        if auth_file.is_file():
            os.chmod(auth_file, 0o600)
    except OSError:
        pass

    return True, email, auth_data


def _model_supported_efforts(agy_model: str, profile_id: str | None = None) -> set[str]:
    """Return the set of effort levels supported by *agy_model*.

    Профиль обязателен: обнаружение читает учётные данные из HOME, и без
    подмены окружения оно выполняется в глобальном, где вход не сделан.
    Карта усилий тогда остаётся пустой, подстановка уровня по умолчанию не
    срабатывает, и agy отвергает вызов с «requires --effort» — при том что
    сама модель совершенно настоящая.
    """
    discover_models(profile_id=profile_id)
    efforts = _AGY_EFFORT_MAP.get(agy_model, set())
    if efforts:
        return efforts

    # Запасной источник: сохранённый на диске список моделей. Обнаружение
    # ходит через КОНКРЕТНЫЙ профиль, и если именно у него вход не сделан,
    # карта усилий остаётся пустой — тогда уровень не подставляется и agy
    # отвергает вызов, хотя модель настоящая. Уровни усилия — свойство
    # модели, а не аккаунта, поэтому их можно взять из склеенных
    # идентификаторов вида "gemini-3.7-flash-high", уже лежащих в кэше.
    try:
        from antigravity_provider.router.model_discovery import ModelDiscoveryService

        cached = ModelDiscoveryService.get().get_models("antigravity") or []
    except Exception:
        return efforts

    known = {"low", "medium", "high"}
    derived = {
        suffix
        for model_id in cached
        for base, _, suffix in [model_id.rpartition("-")]
        if base == agy_model and suffix in known
    }
    return derived


# Effort values understood by both hermes and agy
_EFFORT_NORMALISE: dict[str, str] = {
    "off": "",
    "none": "",
    "disabled": "",
    "minimal": "low",
    "minimum": "low",
    "low": "low",
    "medium": "medium",
    "normal": "medium",
    "high": "high",
    "xhigh": "high",
    "max": "high",
}


def _resolve_effort(raw: str | None) -> str:
    """Normalise a hermes reasoning_effort value to an agy ``--effort`` arg."""
    if not raw:
        return ""
    return _EFFORT_NORMALISE.get(raw.strip().lower().replace("_", "-"), "")


def _resolve_model(hermes_model: str) -> str:
    """Convert a hermes model id to an agy ``--model`` arg.

    Falls back to stripping the ``google-antigravity/`` prefix.
    """
    catalog = discover_models()
    if hermes_model in catalog:
        return catalog[hermes_model]
    # Strip provider prefix
    if "/" in hermes_model:
        return hermes_model.split("/", 1)[1]
    return hermes_model


# ---------------------------------------------------------------------------
# Conversation serialisation
# ---------------------------------------------------------------------------

def _content_text(content: Any) -> str:
    """Extract plain text from an OpenAI ``content`` field."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                if item.get("type") == "text":
                    parts.append(str(item.get("text", "")))
                elif item.get("type") == "image_url":
                    parts.append("[image]")
        return "\n".join(parts)
    return str(content)


def _serialize_tool_defs(tools: list[dict[str, Any]]) -> str:
    """Serialise OpenAI tool definitions into a readable block."""
    lines: list[str] = []
    for tool in tools:
        if not isinstance(tool, dict) or tool.get("type") != "function":
            continue
        fn = tool.get("function") or {}
        if not isinstance(fn, dict) or not fn.get("name"):
            continue
        lines.append(json.dumps(fn, indent=2, ensure_ascii=False))
    if not lines:
        return ""
    return (
        "## SYSTEM DIRECTIVE: FUNCTION CALLING MODE\n"
        "You are acting as an API LLM backend for Hermes Agent. You do NOT possess any built-in tools, shell access, or local file system access.\n"
        "To perform any operation, inspect files, or call functions, you MUST output a tool call block using the exact format below. Do NOT attempt to run commands or read files yourself.\n\n"
        "```tool_call\n"
        '{"name": "<tool_name>", "arguments": {<args>}}\n'
        "```\n\n"
        "### Available Client Functions:\n"
        + "\n---\n".join(lines)
    )


def serialize_messages(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
) -> str:
    """Flatten an OpenAI messages array (+ tools) into a single text prompt.

    For simple system-plus-one-user prompts (no tools, no history) the output
    is a clean concatenation — no role tags — so the model behaves as if it
    received a direct instruction.

    For multi-turn or tool-bearing conversations each turn is tagged with
    ``[User]``, ``[Assistant]``, ``[Tool …]`` to preserve structure.
    """
    system_parts: list[str] = []
    turns: list[tuple[str, str]] = []   # (role_tag, text)

    for msg in messages:
        role = msg.get("role", "")
        content = _content_text(msg.get("content"))

        if role in ("system", "developer"):
            if content.strip():
                system_parts.append(content)

        elif role == "user":
            if content.strip():
                turns.append(("user", content))

        elif role == "assistant":
            parts: list[str] = []
            if content and content.strip():
                parts.append(content)
            for tc in msg.get("tool_calls") or []:
                if not isinstance(tc, dict):
                    continue
                fn = tc.get("function") or {}
                if isinstance(fn, dict) and fn.get("name"):
                    parts.append(
                        f'[Tool call: {fn["name"]}'
                        f'({fn.get("arguments", "{}")})]'
                    )
            if parts:
                turns.append(("assistant", "\n".join(parts)))

        elif role == "tool":
            name = msg.get("name", "tool")
            if content.strip():
                turns.append(("tool", f"[Tool result ({name})]: {content}"))

    # --- simple case: system + single user, no tools ---
    if (
        len(turns) == 1
        and turns[0][0] == "user"
        and not tools
    ):
        prefix = "\n\n".join(system_parts)
        body = turns[0][1]
        return f"{prefix}\n\n{body}" if prefix else body

    # --- complex case: multi-turn / tools ---
    sections: list[str] = []
    if system_parts:
        sections.append("\n\n".join(system_parts))

    if tools:
        td = _serialize_tool_defs(tools)
        if td:
            sections.append(td)

    for tag, text in turns:
        if tag == "user":
            sections.append(f"[User]\n{text}")
        elif tag == "assistant":
            sections.append(f"[Assistant]\n{text}")
        elif tag == "tool":
            sections.append(text)

    return "\n\n".join(sections)


# ---------------------------------------------------------------------------
# Tool-call extraction from model text
# ---------------------------------------------------------------------------

def _extract_tool_calls(text: str) -> list[dict[str, Any]] | None:
    """Best-effort extraction of ``tool_call`` blocks from model output."""
    pattern = r"```tool_call\s*\n(.*?)\n```"
    matches = re.findall(pattern, text, re.DOTALL)
    if not matches:
        return None

    calls: list[dict[str, Any]] = []
    for raw in matches:
        try:
            data = json.loads(raw.strip())
            name = data.get("name", "")
            args = data.get("arguments", {})
            if not name:
                continue
            if not isinstance(args, dict):
                try:
                    args = json.loads(str(args))
                except (json.JSONDecodeError, TypeError):
                    args = {}
            calls.append(
                {
                    "id": "call_" + uuid.uuid4().hex[:12],
                    "type": "function",
                    "function": {
                        "name": name,
                        "arguments": json.dumps(
                            args, separators=(",", ":"), ensure_ascii=False
                        ),
                    },
                }
            )
        except (json.JSONDecodeError, AttributeError):
            continue

    return calls if calls else None


def _strip_tool_call_blocks(text: str) -> str:
    """Remove ``tool_call`` fenced blocks from the response text."""
    cleaned = re.sub(r"```tool_call\s*\n.*?\n```", "", text, flags=re.DOTALL)
    return cleaned.strip()


# ---------------------------------------------------------------------------
# Safe environment (no hermes secrets in subprocess)
# ---------------------------------------------------------------------------

SAFE_SYSTEM_ENV_VARS: set[str] = {
    # Windows standard environment
    "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC", "PATH", "PATHEXT",
    "TEMP", "TMP", "LOCALAPPDATA", "APPDATA", "PROGRAMDATA", "PROGRAMFILES",
    "PROGRAMFILES(X86)", "COMMONPROGRAMFILES", "COMMONPROGRAMFILES(X86)",
    "USERPROFILE", "HOME", "HOMEDRIVE", "HOMEPATH",
    "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE", "PROCESSOR_IDENTIFIER",
    "OS", "COMPUTERNAME", "LOGONSERVER", "USERDOMAIN", "USERNAME",
    # Unix standard environment
    "USER", "LOGNAME", "SHELL", "LANG", "LC_ALL", "LC_CTYPE", "LC_MESSAGES",
    "TMPDIR", "TERM", "PWD", "COLORTERM",
    # GUI Display and session environment (for terminal emulators)
    "DISPLAY", "WAYLAND_DISPLAY", "XAUTHORITY", "DBUS_SESSION_BUS_ADDRESS",
    "XDG_RUNTIME_DIR", "XDG_SESSION_TYPE", "XDG_CURRENT_DESKTOP", "XDG_SESSION_DESKTOP",
    # Networking & Proxy & SSL certificates
    "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "ALL_PROXY",
    "http_proxy", "https_proxy", "no_proxy", "all_proxy",
    "SSL_CERT_FILE", "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE", "NODE_EXTRA_CA_CERTS",
    # Specific toolchain overrides (non-secret)
    "AGY_EXE_PATH", "AGY_CONFIG_PATH", "HERMES_HOME", "HERMES_HUB_DEV_MODE",
    "NODE_OPTIONS", "PYTHONUTF8", "PYTHONIOENCODING",
}

BLOCKED_SECRET_PATTERNS: tuple[str, ...] = (
    "api_key", "token", "secret", "auth", "password", "bearer", "private_key",
    "openai", "codex", "anthropic", "claude", "deepseek", "opencode", "xai", "grok",
    "hermes_api", "hermes_secret", "google_api_key", "gemini_api",
)


def detect_graphical_session() -> tuple[dict[str, str], list[str]]:
    """Найти графический сеанс владельца. Вернуть (переменные, что проверено).

    Хаб запускается через nohup и наследует окружение той оболочки, из которой
    его запустили. Запуск по SSH или из службы оставляет процесс без DISPLAY —
    и хаб отказывался открыть терминал, стоя при этом на рабочем столе.

    Наследование не единственный источник. systemd знает про сеанс: на сервере
    владельца `loginctl show-user <user> -p Display` даёт c1, а
    `loginctl show-session c1` — Type=x11, Display=:10, Active=yes. Спросить у
    системы честнее, чем сдаться.

    XAUTHORITY не выставляем: клиенты X11 по умолчанию берут ~/.Xauthority
    того же пользователя, а хаб работает под ним же.
    """
    checked: list[str] = []
    found: dict[str, str] = {}

    for var in ("DISPLAY", "WAYLAND_DISPLAY", "MIR_SOCKET"):
        value = os.environ.get(var, "").strip()
        checked.append(f"{var} ({'задан: ' + value if value else 'не задан'})")
        if value:
            found[var] = value

    if found:
        return found, checked

    loginctl = shutil.which("loginctl")
    if not loginctl:
        checked.append("loginctl (не найден)")
        return {}, checked

    def _ask(args: list[str]) -> str:
        try:
            res = subprocess.run(
                [loginctl, *args],
                capture_output=True, text=True, timeout=5,
                encoding="utf-8", errors="replace",
                stdin=subprocess.DEVNULL,
            )
            return res.stdout.strip() if res.returncode == 0 else ""
        except Exception:
            return ""

    user = os.environ.get("USER") or os.environ.get("LOGNAME") or ""
    session = _ask(["show-user", user, "--value", "-p", "Display"]) if user else ""
    if not session:
        checked.append(f"loginctl show-user {user or '<пользователь неизвестен>'} (сеанс не назван)")
        return {}, checked

    stype = _ask(["show-session", session, "--value", "-p", "Type"])
    display = _ask(["show-session", session, "--value", "-p", "Display"])
    checked.append(f"loginctl сеанс {session} (тип: {stype or 'Н/Д'}, дисплей: {display or 'Н/Д'})")

    if stype == "wayland" and display:
        found["WAYLAND_DISPLAY"] = display
    elif display:
        found["DISPLAY"] = display

    return found, checked


def _is_windows() -> bool:
    """Отдельная проверка системы, чтобы тестам не подменять os.name.

    Подмена глобального os.name задевает pathlib: он выбирает по нему
    класс пути, и на Windows создание PosixPath падает — ломая не только
    проверяемый код, но и сам pytest.
    """
    return os.name == "nt"


def write_login_helper(profile_dir: Path, agy_exe: str, profile_id: str) -> Path:
    """Создать сценарий, который терминал запустит вместо самой agy.

    Три причины, все проверены на сервере владельца.

    Окружение задаётся внутри сценария, а не наследуется. Многие эмуляторы —
    xfce4-terminal, gnome-terminal — держат один процесс на сеанс: новый вызов
    передаёт задание уже работающему экземпляру и немедленно умирает (в ps
    остаётся [xfce4-terminal] <defunct>). Команда при этом выполняется в
    окружении СТАРОГО экземпляра, и подменённый HOME не применяется — вход
    ушёл бы в настоящий домашний каталог владельца мимо изоляции слотов.

    Окно не закрывается по завершении agy: с ключом -e терминал исчезает
    вместе с командой, и владелец не успевает прочитать причину отказа.

    Видно, куда идёт вход: путь к каталогу профиля печатается до запуска.
    """
    helper_path = profile_dir / ".hermes-agy-login.sh"
    lines = [
        "#!/bin/sh",
        "# Создан Hermes Hub для входа в слот " + profile_id + ".",
        "# Секретов не содержит: только пути.",
        "HOME=" + shlex.quote(str(profile_dir)),
        "USERPROFILE=" + shlex.quote(str(profile_dir)),
        "HOMEPATH=" + shlex.quote(str(profile_dir)),
        "export HOME USERPROFILE HOMEPATH",
        "cd " + shlex.quote(str(profile_dir)) + " || exit 1",
        'echo "Вход Antigravity в слот ' + profile_id + '"',
        'echo "Каталог профиля: $HOME"',
        'echo',
        shlex.quote(agy_exe),
        "status=$?",
        'echo',
        'echo "agy завершился с кодом $status. Окно можно закрыть."',
        'printf "Нажмите Enter... "',
        "read _ignored",
    ]
    helper_path.write_text(chr(10).join(lines) + chr(10), encoding="utf-8")
    try:
        os.chmod(helper_path, 0o700)
    except OSError:
        pass
    return helper_path


def find_terminal_emulator(
    profile_id: str,
    agy_exe: str,
    profile_dir: Path,
) -> tuple[list[str] | None, str | None, list[str]]:
    """Locate an available GUI terminal emulator on the host system to run native agy CLI login.

    Returns:
        (command_args, error_message, checked_candidates)
    """
    title = f"Antigravity Login ({profile_id})"

    if _is_windows():
        checked = ["Windows Terminal (wt.exe)", "cmd.exe", "powershell.exe"]
        wt_path = shutil.which("wt.exe") or shutil.which("wt")
        if wt_path:
            cmd = [wt_path, "-w", "0", "nt", "-d", str(profile_dir), "--title", title, agy_exe]
            return cmd, None, checked

        cmd_path = shutil.which("cmd.exe") or shutil.which("cmd") or "cmd.exe"
        # /k вместо /c: иначе окно исчезает вместе с agy и причина отказа
        # остаётся непрочитанной.
        cmd = [cmd_path, "/c", "start", title, "cmd", "/k", agy_exe]
        return cmd, None, checked

    # Linux / Unix / macOS
    session_env, checked = detect_graphical_session()
    if not session_env:
        err_msg = (
            "Графический сеанс не обнаружен: ни в окружении хаба, ни у systemd. "
            "Для входа на машине без графического интерфейса используйте вход по ссылке "
            "через браузер."
        )
        return None, err_msg, checked

    # Что запускаем, решает вызывающий: поиск терминала не должен ничего
    # создавать. Нативный вход передаёт сюда путь сценария входа, а не саму
    # agy — см. write_login_helper.
    launch = agy_exe

    # Конкретные эмуляторы идут раньше x-terminal-emulator: это обёртка над
    # альтернативами Debian, лишний слой между нами и настоящей программой.
    # У xfce4-terminal обязателен --disable-server, иначе вызов передаётся
    # уже работающему экземпляру и наш процесс умирает, не открыв окна, —
    # именно это владелец и увидел.
    candidates: list[tuple[str, Any]] = [
        ("xfce4-terminal", lambda p: [p, "--disable-server", "--title", title, "-e", launch]),
        ("konsole", lambda p: [p, "-p", f"tabtitle={title}", "-e", launch]),
        ("tilix", lambda p: [p, "-t", title, "-e", launch]),
        ("alacritty", lambda p: [p, "-t", title, "-e", launch]),
        ("kitty", lambda p: [p, "--title", title, launch]),
        ("terminator", lambda p: [p, "-T", title, "-e", launch]),
        ("urxvt", lambda p: [p, "-title", title, "-e", launch]),
        ("foot", lambda p: [p, "--title", title, launch]),
        ("xterm", lambda p: [p, "-title", title, "-e", launch]),
        ("gnome-terminal", lambda p: [p, "--title", title, "--", launch]),
        ("x-terminal-emulator", lambda p: [p, "-e", launch]),
    ]

    checked = []
    for name, cmd_builder in candidates:
        found_path = shutil.which(name)
        if found_path:
            checked.append(f"{name} (найден: {found_path})")
            return cmd_builder(found_path), None, checked
        else:
            checked.append(f"{name} (не найден)")

    err_msg = (
        "Терминал не найден на сервере. Проверено: "
        + "; ".join(checked)
        + "; и PATH процесса. Запустите вход через браузер либо установите терминал "
        "(например, gnome-terminal, xfce4-terminal или xterm)."
    )
    return None, err_msg, checked


class NativeAgySession:
    """Tracks a native agy CLI terminal login session."""

    def __init__(self, profile_id: str, profile_dir: Path, timeout_sec: int = 600):
        self.session_id = secrets.token_urlsafe(16)
        self.profile_id = profile_id
        self.profile_dir = profile_dir
        self.timeout_sec = timeout_sec
        self.created_at = time.time()
        self.status = "pending"  # pending, completed, timeout, failed, cancelled
        self.error_msg: str | None = None
        self.terminal_cmd: list[str] | None = None
        self.token_path = profile_dir / ".gemini" / "antigravity-cli" / "antigravity-oauth-token"
        self.creds_path = profile_dir / ".gemini" / "oauth_creds.json"
        self.initial_token_mtime = self._get_token_mtime()

    def _get_token_mtime(self) -> float:
        mtime = 0.0
        if self.token_path.is_file():
            try:
                mtime = max(mtime, self.token_path.stat().st_mtime)
            except OSError:
                pass
        if self.creds_path.is_file():
            try:
                mtime = max(mtime, self.creds_path.stat().st_mtime)
            except OSError:
                pass
        return mtime

    def check_status(self) -> tuple[bool, str, dict[str, Any]]:
        """Poll the filesystem to verify if agy created the authentication credentials."""
        if self.status == "completed":
            return True, "Авторизация успешно завершена", {
                "status": "completed",
                "profile_id": self.profile_id,
            }
        if self.status in ("failed", "cancelled"):
            return False, self.error_msg or "Авторизация отменена", {
                "status": self.status,
                "profile_id": self.profile_id,
            }

        now = time.time()
        if now - self.created_at > self.timeout_sec:
            self.status = "timeout"
            self.error_msg = (
                f"Время ожидания авторизации в терминале истекло ({int(self.timeout_sec // 60)} минут). "
                f"Файл учётных данных не появился в {self.profile_dir}."
            )
            return False, self.error_msg, {
                "status": "timeout",
                "profile_id": self.profile_id,
                "home": str(self.profile_dir),
            }

        is_authenticated, email, auth_data = check_profile_native_auth_status(self.profile_id)
        current_mtime = self._get_token_mtime()

        if is_authenticated and (current_mtime >= (self.created_at - 2.0) or self.initial_token_mtime == 0.0):
            # Check duplicate identity
            if email:
                try:
                    from antigravity_provider.router.auto_assigner import AutoAssigner

                    existing = AutoAssigner.check_duplicate_identity(
                        "antigravity", email, exclude_profile_id=self.profile_id
                    )
                    if existing and existing != self.profile_id:
                        logger.info(
                            "Native agy login: identity %s already exists in %s, syncing from %s",
                            email, existing, self.profile_id,
                        )
                        from antigravity_provider.router.adapters.antigravity_adapter import get_profile_env_dir

                        target_dir = get_profile_env_dir(existing)
                        target_gemini = target_dir / ".gemini"
                        target_gemini.mkdir(parents=True, exist_ok=True)
                        src_gemini = self.profile_dir / ".gemini"
                        if src_gemini.is_dir():
                            shutil.copytree(src_gemini, target_gemini, dirs_exist_ok=True)
                        self.profile_id = existing
                except Exception as exc:
                    logger.warning("Error checking duplicate identity: %s", exc)

            # Ensure profile definition and role assignment
            from antigravity_provider.router.auto_assigner import AutoAssigner

            AutoAssigner.ensure_profile_definition("antigravity", self.profile_id)

            self.status = "completed"

            # Trigger background probe without blocking
            try:
                from antigravity_provider.router.account_probe_service import AccountProbeService

                AccountProbeService.get().schedule("antigravity", self.profile_id, force=True)
            except Exception:
                pass

            return True, "Авторизация успешно завершена через agy CLI", {
                "status": "completed",
                "profile_id": self.profile_id,
                "email": email or "Н/Д (почта не передана провайдером)",
            }

        elapsed = int(now - self.created_at)
        return True, "Ожидание завершения авторизации в терминале...", {
            "status": "pending",
            "profile_id": self.profile_id,
            "elapsed_sec": elapsed,
            "timeout_sec": self.timeout_sec,
        }


_ACTIVE_NATIVE_SESSIONS: dict[str, NativeAgySession] = {}


def get_native_agy_session(session_id: str) -> NativeAgySession | None:
    return _ACTIVE_NATIVE_SESSIONS.get(session_id)


def start_native_agy_login(
    profile_id: str | None = None,
    force: bool = False,
) -> tuple[bool, str, dict[str, Any]]:
    """Launch agy CLI in a new host terminal window with isolated HOME pointing to profile directory.

    Returns:
        (ok, message, data)
    """
    from antigravity_provider.router.adapters.antigravity_adapter import get_profile_env_dir
    from antigravity_provider.router.auto_assigner import AutoAssigner
    from antigravity_provider.router.profile_manager import ProfileAuthManager

    slot = profile_id or AutoAssigner.find_free_slot("antigravity") or "ag-1"
    valid, reason = AutoAssigner.validate_slot("antigravity", slot)
    if not valid:
        return False, reason, {"profile_id": slot}

    # P0-2.2: Do not overwrite occupied slot without explicit confirmation
    if not force:
        status = ProfileAuthManager.get_profile_status("antigravity", slot)
        if status.get("authenticated"):
            email_info = status.get("email_masked") or "Google Account"
            return False, f"Слот {slot} уже занят аккаунтом ({email_info}). Подтвердите перезапись учётных данных.", {
                "confirmation_required": True,
                "profile_id": slot,
                "email": email_info,
            }

    profile_dir = get_profile_env_dir(slot)
    try:
        profile_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(profile_dir, 0o700)
    except OSError as exc:
        return False, f"Не удалось создать каталог профиля {profile_dir}: {exc}", {"profile_id": slot}

    try:
        agy_exe = get_agy_exe()
    except Exception as exc:
        return False, str(exc), {"profile_id": slot, "home": str(profile_dir)}

    # Терминал запускает сценарий, а не agy напрямую: сценарий сам задаёт HOME
    # и не даёт окну закрыться вместе с командой.
    launch_script = str(write_login_helper(profile_dir, agy_exe, slot))
    term_cmd, err_msg, checked = find_terminal_emulator(slot, launch_script, profile_dir)
    if err_msg or not term_cmd:
        return False, err_msg or "Терминал не найден", {
            "profile_id": slot,
            "home": str(profile_dir),
            "checked_terminals": checked,
        }

    # HOME терминалу НЕ подменяем. Клиенты X11 берут ключ авторизации из
    # ~/.Xauthority, и с подменённым HOME его там нет: xfce4-terminal не мог
    # подключиться к дисплею и выходил с кодом 1, не открыв окна. Изоляцию
    # обеспечивает сценарий входа — он задаёт HOME сам, уже внутри терминала,
    # непосредственно перед запуском agy.
    #
    # Дисплей, найденный у systemd, наоборот, обязан попасть в окружение: в
    # окружении самого хаба его может не быть, если хаб запущен по SSH.
    session_env, _checked = detect_graphical_session()
    env = build_safe_subprocess_env(overrides=dict(session_env))

    try:
        proc = subprocess.Popen(
            term_cmd,
            env=env,
            cwd=str(profile_dir),
            stdin=None,
            stdout=None,
            stderr=None,
        )
        # Popen возвращается сразу и об открытии окна не говорит ничего.
        # Владелец видел «Терминал запущен», а окна не было: процесс умирал
        # мгновенно, оставляя зомби. Даём ему секунду и смотрим, жив ли он.
        time.sleep(1.0)
        exit_code = proc.poll()
        # Только настоящий ненулевой код считаем отказом: в проверках
        # Popen подменяется заглушкой, и её poll() возвращает объект.
        if isinstance(exit_code, int) and exit_code != 0:
            return False, (
                f"Терминал {term_cmd[0]} завершился сразу с кодом {exit_code}, "
                f"окно не открылось. Запуск с HOME={profile_dir}"
            ), {
                "profile_id": slot,
                "home": str(profile_dir),
                "checked_terminals": checked,
                "terminal_cmd": term_cmd[0],
                "exit_code": exit_code,
            }
    except Exception as launch_exc:
        return False, f"Не удалось запустить терминал ({term_cmd[0]}): {launch_exc}. Запуск с HOME={profile_dir}", {
            "profile_id": slot,
            "home": str(profile_dir),
            "checked_terminals": checked,
        }

    session = NativeAgySession(profile_id=slot, profile_dir=profile_dir)
    session.terminal_cmd = term_cmd
    _ACTIVE_NATIVE_SESSIONS[session.session_id] = session

    logger.info("Started native agy login session=%s profile=%s in terminal=%s", session.session_id, slot, term_cmd[0])
    return True, "Терминал успешно запущен. Пройдите авторизацию в открывшемся окне.", {
        "session_id": session.session_id,
        "profile_id": slot,
        "profile_dir": str(profile_dir),
        "terminal_cmd": term_cmd[0],
        "timeout_sec": session.timeout_sec,
    }


def poll_native_agy_login(session_id: str) -> tuple[bool, str, dict[str, Any]]:
    """Check the status of an ongoing native agy login session."""
    session = get_native_agy_session(session_id)
    if not session:
        return False, "Сессия авторизации не найдена или уже завершена", {"status": "not_found"}
    return session.check_status()


def cancel_native_agy_login(session_id: str) -> tuple[bool, str]:
    """Cancel an ongoing native agy login session."""
    session = get_native_agy_session(session_id)
    if session:
        session.status = "cancelled"
        session.error_msg = "Авторизация отменена пользователем"
        return True, "Авторизация отменена"
    return False, "Сессия не найдена"


def hidden_process_kwargs() -> dict:
    """Флаги запуска подпроцесса без видимого окна консоли (только Windows).

    Хаб — оконное приложение без консоли, поэтому каждый запуск консольного
    exe (agy.exe и прочие) открывал отдельное чёрное окно. Пока проверка шла
    по нажатию, это было незаметно. После A50 проверка аккаунтов запускается
    сама раз в минуту, и окна стали появляться постоянно, мешая работе.

    Применять ко всем ФОНОВЫМ вызовам. Для входа по OAuth окно нужно
    видимым — там сознательно используется CREATE_NEW_CONSOLE.
    """
    if os.name != "nt":
        return {}
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = subprocess.SW_HIDE
    return {"creationflags": flags, "startupinfo": startupinfo}


def build_safe_subprocess_env(
    base_env: dict[str, str] | None = None,
    allow_extra_keys: set[str] | list[str] | None = None,
    overrides: dict[str, str] | None = None,
) -> dict[str, str]:
    """Construct an explicitly isolated and sanitized environment dictionary for child subprocesses.

    Copies ONLY explicitly permitted system variables from base_env (defaulting to os.environ),
    strips out any provider API keys or secrets, and applies explicit overrides.
    """
    src = os.environ if base_env is None else base_env
    allow = set(k.upper() for k in SAFE_SYSTEM_ENV_VARS)
    if allow_extra_keys:
        allow.update(k.upper() for k in allow_extra_keys)

    clean_env: dict[str, str] = {}
    for k, v in src.items():
        k_upper = k.upper()
        k_lower = k.lower()
        if k_upper in allow:
            # Strip secret-bearing keys even if matching an allow pattern unless explicitly in allow_extra_keys
            if not allow_extra_keys or k not in allow_extra_keys:
                if any(pat in k_lower for pat in BLOCKED_SECRET_PATTERNS):
                    continue
            clean_env[k] = v

    if overrides:
        for k, v in overrides.items():
            clean_env[k] = str(v)

    return clean_env


def _safe_env() -> dict[str, str]:
    """Backward-compatible wrapper for build_safe_subprocess_env."""
    return build_safe_subprocess_env()


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def agy_generate(
    request: dict[str, Any],
    custom_env: dict[str, str] | None = None,
    profile_id: str | None = None,
) -> dict[str, Any]:
    """Execute a chat completion via the ``agy`` subprocess."""
    exe = get_agy_exe()
    timeout = int(request.get("timeout") or 180)
    messages = request.get("messages") or []
    tools = request.get("tools") if isinstance(request.get("tools"), list) else None
    model_raw = str(request.get("model") or "")

    # Build the flat text prompt
    prompt = serialize_messages(messages, tools)
    if not prompt.strip():
        prompt = "Continue."

    # Resolve model & effort
    agy_model = _resolve_model(model_raw)

    reasoning_effort = request.get("reasoning_effort")
    if reasoning_effort is None and isinstance(request.get("reasoning"), dict):
        reasoning_effort = request["reasoning"].get("effort")
    if reasoning_effort is None and isinstance(request.get("extra_body"), dict):
        eb = request["extra_body"]
        if isinstance(eb.get("reasoning"), dict):
            reasoning_effort = eb["reasoning"].get("effort")
    agy_effort = _resolve_effort(reasoning_effort)

    # Smart effort selection based on model capabilities.
    # Some models (gemini) REQUIRE --effort, others (claude, gpt) DON'T SUPPORT it.
    supported = _model_supported_efforts(agy_model, profile_id=profile_id)
    if supported:
        # Model supports specific efforts
        if not agy_effort:
            # Default: pick "low" if available, else first sorted effort
            agy_effort = "low" if "low" in supported else sorted(supported)[0]
        elif agy_effort not in supported:
            # Requested effort not supported — pick closest
            logger.warning(
                "effort %r not supported for %s (available: %s), using fallback",
                agy_effort, agy_model, sorted(supported),
            )
            agy_effort = "low" if "low" in supported else sorted(supported)[0]
    else:
        # Model has NO effort entries — don't pass --effort at all
        agy_effort = ""

    # Build command.
    # Prompt is delivered via stdin (--input-format text), NOT via -p argv.
    # This avoids Windows CreateProcess 32767-char command-line limit.
    cmd = [
        exe,
        "--input-format", "text",
        "--output-format", "json",
        "--dangerously-skip-permissions",
        "--disable-slash-commands",
        "--print-timeout", f"{timeout}s",
    ]
    # Каталог agy отдаёт идентификаторы с уровнем усилия: gemini-3.7-flash-high,
    # -medium, -low. В профиле же хранится голое имя, и вызов уходил с пустым
    # --effort: agy отвечал «gemini-3.7-flash requires --effort (available: low,
    # medium, high)» и работа не начиналась.
    if agy_model and not agy_effort:
        base, _, tail = str(agy_model).rpartition("-")
        if base and tail in ("low", "medium", "high"):
            # Уровень зашит в самом имени — отделяем его.
            agy_model, agy_effort = base, tail
        else:
            known = _AGY_EFFORT_MAP.get(agy_model) or set()
            if known:
                # Берём средний уровень, если он есть: он и по названию средний,
                # и по расходу квоты. Иначе — любой доступный, по порядку.
                for candidate in ("medium", "high", "low"):
                    if candidate in known:
                        agy_effort = candidate
                        break
                if not agy_effort:
                    agy_effort = sorted(known)[0]
                logger.info(
                    "agy_generate: у модели %s не задан уровень усилия, выбран %s из %s",
                    agy_model, agy_effort, sorted(known),
                )

    if agy_model:
        cmd.extend(["--model", agy_model])
    if agy_effort:
        cmd.extend(["--effort", agy_effort])

    logger.info(
        "agy_generate: model=%s effort=%s prompt_len=%d",
        agy_model, agy_effort, len(prompt),
    )

    # Pre-flight: verify exe still exists
    if not os.path.isfile(exe):
        return _error_completion(
            model_raw,
            f"agy binary does not exist at {exe}",
        )

    # --- run subprocess ---
    t0 = time.monotonic()
    try:
        result = subprocess.run(
            cmd,
            input=prompt,
            capture_output=True,
            text=True,
            timeout=timeout + 30,
            encoding="utf-8",
            errors="replace",
            env=custom_env if custom_env is not None else build_safe_subprocess_env(),
            **hidden_process_kwargs(),
        )
    except subprocess.TimeoutExpired:
        return _error_completion(model_raw, "agy subprocess timed out")
    except FileNotFoundError as exc:
        return _error_completion(model_raw, f"agy binary not found: {exc}")
    except OSError as exc:
        return _error_completion(model_raw, f"agy OS error: {exc}")
    except Exception as exc:
        return _error_completion(
            model_raw, f"agy subprocess error: {type(exc).__name__}: {exc}"
        )
    elapsed = time.monotonic() - t0

    # --- parse stdout ---
    stdout = result.stdout.strip()
    if not stdout:
        stderr = (result.stderr or "").strip()[:500]
        return _error_completion(
            model_raw,
            f"agy returned empty output (exit {result.returncode}): {stderr}",
        )

    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        return _error_completion(
            model_raw, f"agy returned invalid JSON: {stdout[:500]}"
        )

    status = data.get("status", "")
    if status == "ERROR":
        return _error_completion(
            model_raw, f"agy error: {data.get('error', 'unknown')}"
        )

    response_text = data.get("response", "")
    usage = data.get("usage") or {}

    logger.info(
        "agy_generate: status=%s elapsed=%.1fs tokens=%s",
        status, elapsed, usage.get("total_tokens"),
    )

    # --- try to extract tool calls ---
    tool_calls = _extract_tool_calls(response_text)

    message: dict[str, Any] = {
        "role": "assistant",
        "content": (
            _strip_tool_call_blocks(response_text)
            if tool_calls
            else response_text
        ) or None,
    }
    if tool_calls:
        message["tool_calls"] = tool_calls

    return {
        "id": "chatcmpl-agy-" + uuid.uuid4().hex[:16],
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model_raw or "google-antigravity/unknown",
        "choices": [
            {
                "index": 0,
                "message": message,
                "finish_reason": (
                    "tool_calls" if tool_calls else "stop"
                ),
            }
        ],
        "usage": {
            "prompt_tokens": int(usage.get("input_tokens") or 0),
            "completion_tokens": int(usage.get("output_tokens") or 0),
            "total_tokens": int(usage.get("total_tokens") or 0),
        },
    }


def _error_completion(model: str, error_msg: str) -> dict[str, Any]:
    """Build a structured provider error object for router failover."""
    logger.error("agy_generate error: %s", error_msg)
    return {
        "error": {
            "message": f"Antigravity error: {error_msg}",
            "type": "provider_error",
            "model": model or "google-antigravity/unknown",
        }
    }

