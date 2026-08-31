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
                raise RuntimeError(f"agy models: код {result.returncode}; каталог не получен")
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
    A22 Requirement: Detection without credential logging or stream interception.
    """
    from antigravity_provider.router.adapters.antigravity_adapter import get_profile_env_dir

    profile_dir = get_profile_env_dir(profile_id)
    gemini_dir = profile_dir / ".gemini"
    creds_file = gemini_dir / "oauth_creds.json"
    accounts_file = gemini_dir / "google_accounts.json"

    if not creds_file.is_file() or creds_file.stat().st_size == 0:
        return False, None, None

    try:
        creds_data = json.loads(creds_file.read_text(encoding="utf-8"))
        if not isinstance(creds_data, dict):
            return False, None, None

        # Verify essential fields
        access_token = creds_data.get("access_token")
        refresh_token = creds_data.get("refresh_token")
        if not access_token and not refresh_token:
            return False, None, None

        email = None
        if accounts_file.is_file() and accounts_file.stat().st_size > 0:
            try:
                acc_data = json.loads(accounts_file.read_text(encoding="utf-8"))
                if isinstance(acc_data, dict):
                    email = acc_data.get("active")
            except Exception:
                email = None

        if not email:
            auth_file = profile_dir / "auth.json"
            if auth_file.is_file():
                try:
                    a_data = json.loads(auth_file.read_text(encoding="utf-8"))
                    if isinstance(a_data, dict):
                        email = a_data.get("email") or a_data.get("user_email")
                except Exception:
                    pass

        if not email:
            from antigravity_provider.router.profile_manager import ProfileAuthManager

            id_token = creds_data.get("id_token")
            if id_token:
                email, _ = ProfileAuthManager.extract_jwt_identity(str(id_token))

        auth_data = {
            "auth_method": "oauth",
            "email": email or "Google Account",
            "token": creds_data,
            "updated_at": time.time(),
        }

        # Keep profile's auth.json in sync
        auth_file = profile_dir / "auth.json"
        if not auth_file.is_file():
            auth_file.write_text(json.dumps(auth_data, indent=2), encoding="utf-8")

        return True, email, auth_data
    except Exception as exc:
        logger.debug("check_profile_native_auth_status error: %s", exc)
        return False, None, None


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
    "TMPDIR", "TERM", "PWD",
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

