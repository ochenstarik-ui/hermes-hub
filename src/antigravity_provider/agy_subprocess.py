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

    # 2. Standard Windows location
    local_app = os.environ.get("LOCALAPPDATA", "")
    if local_app:
        candidate = Path(local_app) / "agy" / "bin" / "agy.exe"
        if candidate.is_file():
            return str(candidate)

    # 3. PATH
    found = shutil.which("agy") or shutil.which("agy.exe")
    if found:
        return found

    raise FileNotFoundError(
        "agy executable not found.  Set the AGY_EXE_PATH environment "
        "variable, install agy, or ensure it is on PATH."
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


def discover_models() -> dict[str, str]:
    """Discover available models by querying ``agy`` with an invalid model.

    Returns a dict mapping *hermes-style* model ids
    (``google-antigravity/gemini-3.7-flash``) to *agy CLI* model ids
    (``gemini-3.7-flash``).  The result is cached for the process lifetime.

    Also populates :data:`_AGY_EFFORT_MAP` with supported efforts per model.
    """
    global _AGY_MODEL_CACHE, _AGY_EFFORT_MAP
    if _AGY_MODEL_CACHE is not None:
        return dict(_AGY_MODEL_CACHE)

    exe = get_agy_exe()
    try:
        result = subprocess.run(
            [exe, "-p", "x", "--model", "__invalid_probe__",
             "--output-format", "json", "--print-timeout", "10s"],
            capture_output=True,
            text=True,
            timeout=20,
            encoding="utf-8",
            errors="replace",
        )
        raw = result.stdout.strip()
        if not raw:
            logger.warning("discover_models: agy returned empty output")
            _AGY_MODEL_CACHE = {}
            return {}
        data = json.loads(raw)
        error_text = data.get("error", "")
    except Exception as exc:
        logger.warning("discover_models failed: %s", exc)
        _AGY_MODEL_CACHE = {}
        return {}

    models: dict[str, str] = {}
    effort_map: dict[str, set[str]] = {}
    if "Available models:" in error_text:
        lines = error_text.split("Available models:")[1].strip().splitlines()
        for line in lines:
            line = line.strip()
            if not line:
                continue
            cli_model, effort = _display_to_cli(line)
            if not cli_model:
                continue
            hermes_id = f"google-antigravity/{cli_model}"
            models[hermes_id] = cli_model
            if cli_model not in effort_map:
                effort_map[cli_model] = set()
            # Only accept actual effort levels; parenthetical labels like
            # "Thinking" are model variant markers, not --effort values.
            if effort in ("low", "medium", "high"):
                effort_map[cli_model].add(effort)

    _AGY_MODEL_CACHE = models
    _AGY_EFFORT_MAP = effort_map
    logger.info(
        "discover_models: found %d models, efforts=%s",
        len(models),
        {k: sorted(v) for k, v in effort_map.items()},
    )
    return dict(models)


def _model_supported_efforts(agy_model: str) -> set[str]:
    """Return the set of effort levels supported by *agy_model*."""
    # Ensure discovery has run
    discover_models()
    return _AGY_EFFORT_MAP.get(agy_model, set())


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

_STRIP_PATTERNS = (
    "hermes_api",
    "hermes_secret",
    "anthropic_api",
    "openai_api",
    "openrouter_api",
    "google_api_key",
)


def _safe_env() -> dict[str, str]:
    """Copy ``os.environ`` with provider API keys stripped out."""
    env = dict(os.environ)
    for key in list(env):
        lower = key.lower()
        if any(pat in lower for pat in _STRIP_PATTERNS):
            del env[key]
    return env


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def agy_generate(
    request: dict[str, Any],
    custom_env: dict[str, str] | None = None,
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
    supported = _model_supported_efforts(agy_model)
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
            env=custom_env or os.environ,
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
    """Build an OpenAI-shaped error completion."""
    logger.error("agy_generate error: %s", error_msg)
    return {
        "id": "chatcmpl-agy-err-" + uuid.uuid4().hex[:12],
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model or "google-antigravity/unknown",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": f"Antigravity (agy) error: {error_msg}",
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        },
    }
