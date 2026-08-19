from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
import uuid
from copy import deepcopy
from typing import Any

from .models import WIRE_PROFILES, clamp_reasoning_effort, normalize_model_id, resolve_wire_model_id, strip_provider_prefix

SKIP_THOUGHT_SIGNATURE = "skip_thought_signature_validator"


def _thinking_budget(logical: str, effort: str) -> int:
    if effort == "off":
        return 0
    if logical == "gemini-3.1-pro":
        return 10001 if effort == "high" else 1001
    if logical == "gemini-3.5-flash":
        return {"low": 1000, "medium": 4000, "high": 10000}.get(effort, 1000)
    if logical in {"gpt-oss-120b", "openai/gpt-oss-120b-maas"}:
        return 8192
    return {"minimal": 1024, "low": 4096, "medium": 8192, "high": 16384}.get(effort, 4096)


def _content_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        texts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                if item.get("type") == "text" and isinstance(item.get("text"), str):
                    texts.append(item["text"])
                elif item.get("type") == "image_url":
                    texts.append("[image omitted]")
        return "\n".join(t for t in texts if t)
    return str(content)


def _parts_from_content(content: Any) -> list[dict[str, Any]]:
    if isinstance(content, list):
        parts: list[dict[str, Any]] = []
        for item in content:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "text" and isinstance(item.get("text"), str) and item["text"].strip():
                parts.append({"text": item["text"]})
            elif item.get("type") == "image_url":
                url = (item.get("image_url") or {}).get("url") if isinstance(item.get("image_url"), dict) else None
                if isinstance(url, str) and url.startswith("data:") and ";base64," in url:
                    meta, data = url.split(",", 1)
                    mime = meta[5:].split(";", 1)[0] or "application/octet-stream"
                    # ponytail: trust data URL shape; provider validates bytes.
                    parts.append({"inlineData": {"mimeType": mime, "data": data}})
                else:
                    parts.append({"text": "[image omitted]"})
        return parts
    text = _content_text(content)
    return [{"text": text}] if text.strip() else []


def _parse_args(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {"value": parsed}
        except json.JSONDecodeError:
            return {"value": raw}
    return {}


def _schema(schema: Any) -> dict[str, Any]:
    if not isinstance(schema, dict):
        return {"type": "object", "properties": {}}
    banned = {"$schema", "$defs", "definitions", "additionalProperties", "patternProperties", "unevaluatedProperties"}
    def clean(value: Any) -> Any:
        if isinstance(value, dict):
            return {k: clean(v) for k, v in value.items() if k not in banned}
        if isinstance(value, list):
            return [clean(v) for v in value]
        return value
    out = clean(deepcopy(schema))
    if "type" not in out:
        out["type"] = "object"
    out.setdefault("properties", {})
    return out


def _tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
    declarations = []
    for tool in tools or []:
        if not isinstance(tool, dict) or tool.get("type") != "function":
            continue
        fn = tool.get("function") or {}
        if not isinstance(fn, dict) or not fn.get("name"):
            continue
        declarations.append(
            {
                "name": fn["name"],
                "description": fn.get("description") or "",
                "parameters": _schema(fn.get("parameters")),
            }
        )
    return [{"functionDeclarations": declarations}] if declarations else None


def _tool_config(tools: list[dict[str, Any]], tool_choice: Any, wire_model: str) -> dict[str, Any] | None:
    if isinstance(tool_choice, str):
        choice = tool_choice.lower()
        if choice == "none":
            return {"functionCallingConfig": {"mode": "NONE"}}
        if choice in {"required", "any"}:
            return {"functionCallingConfig": {"mode": "ANY"}}
    if isinstance(tool_choice, dict):
        fn = tool_choice.get("function") if tool_choice.get("type") == "function" else None
        name = fn.get("name") if isinstance(fn, dict) else None
        if name:
            return {"functionCallingConfig": {"mode": "ANY", "allowedFunctionNames": [name]}}
    if tools or wire_model.startswith("claude-"):
        return {"functionCallingConfig": {"mode": "VALIDATED"}}
    return None


def _session_id(messages: list[dict[str, Any]]) -> str:
    for message in messages:
        if message.get("role") == "user":
            text = _content_text(message.get("content"))
            if text.strip():
                digest = hashlib.sha256(text.encode("utf-8")).digest()[:8]
                return "-" + str(int.from_bytes(digest, "big") & ((1 << 63) - 1))
    return "-" + str(secrets.randbelow(9_000_000_000_000_000_000))


def _envelope_labels(wire_model: str, step: int = 2) -> dict[str, str]:
    labels = {
        "last_step_index": str(step - 1),
        "trajectory_id": str(uuid.uuid4()),
        "used_claude": str(wire_model.startswith("claude-")).lower(),
        "used_claude_conservative": str(wire_model.startswith("claude-")).lower(),
    }
    profile = WIRE_PROFILES.get(wire_model) or {}
    if profile.get("modelEnum"):
        labels["model_enum"] = str(profile["modelEnum"])
    return labels


def build_generate_content_request(
    *,
    model: str,
    project_id: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
    reasoning_effort: str | None = None,
    max_tokens: int | None = None,
    temperature: float | None = None,
    top_p: float | None = None,
    tool_choice: Any = None,
) -> dict[str, Any]:
    logical = strip_provider_prefix(normalize_model_id(model))
    effort = clamp_reasoning_effort(model, reasoning_effort)
    wire_model = resolve_wire_model_id(model, effort)
    system_parts: list[dict[str, str]] = []
    contents: list[dict[str, Any]] = []
    call_names: dict[str, str] = {}

    for msg in messages:
        role = msg.get("role")
        if role in {"system", "developer"}:
            text = _content_text(msg.get("content"))
            if text.strip():
                system_parts.append({"text": text})
        elif role == "user":
            parts = _parts_from_content(msg.get("content"))
            if parts:
                contents.append({"role": "user", "parts": parts})
        elif role == "assistant":
            parts = _parts_from_content(msg.get("content"))
            for tool_call in msg.get("tool_calls") or []:
                if not isinstance(tool_call, dict):
                    continue
                fn = tool_call.get("function") or {}
                name = fn.get("name") if isinstance(fn, dict) else None
                if not name:
                    continue
                if tool_call.get("id"):
                    call_names[str(tool_call["id"])] = name
                part = {"functionCall": {"name": name, "args": _parse_args(fn.get("arguments") if isinstance(fn, dict) else None)}}
                if wire_model.startswith("gemini-3") or wire_model.startswith("gemini-pro"):
                    part["thoughtSignature"] = SKIP_THOUGHT_SIGNATURE
                parts.append(part)
            if parts:
                contents.append({"role": "model", "parts": parts})
        elif role == "tool":
            name = msg.get("name") or call_names.get(str(msg.get("tool_call_id") or "")) or "tool"
            part = {"functionResponse": {"name": name, "response": {"output": _content_text(msg.get("content"))}}}
            if contents and contents[-1].get("role") == "user" and any("functionResponse" in p for p in contents[-1].get("parts", [])):
                contents[-1]["parts"].append(part)
            else:
                contents.append({"role": "user", "parts": [part]})

    if not contents:
        contents.append({"role": "user", "parts": [{"text": "Continue."}]})

    profile = WIRE_PROFILES.get(wire_model, {})
    cap = int(profile.get("maxOutputTokens") or 65535)
    generation_config: dict[str, Any] = {
        "maxOutputTokens": min(max_tokens, cap) if isinstance(max_tokens, int) and max_tokens > 0 else cap,
        "thinkingConfig": {"includeThoughts": effort != "off", "thinkingBudget": _thinking_budget(logical, effort)},
    }
    if temperature is not None:
        generation_config["temperature"] = temperature
    if top_p is not None:
        generation_config["topP"] = top_p

    request: dict[str, Any] = {
        "contents": contents,
        "generationConfig": generation_config,
        "sessionId": _session_id(messages),
        "labels": _envelope_labels(wire_model),
    }
    if system_parts:
        request["systemInstruction"] = {"role": "system", "parts": system_parts}
    converted_tools = _tools(tools or [])
    if converted_tools:
        request["tools"] = converted_tools
    config = _tool_config(tools or [], tool_choice, wire_model)
    if config:
        request["toolConfig"] = config

    return {
        "project": project_id,
        "model": wire_model,
        "request": request,
        "requestType": "agent",
        "userAgent": "antigravity",
        "requestId": f"agent/{uuid.uuid4()}/{int(time.time() * 1000)}/{uuid.uuid4()}/2",
    }
