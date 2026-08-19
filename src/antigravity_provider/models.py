from __future__ import annotations

ANTIGRAVITY_PREFIX = "google-antigravity/"
DEFAULT_MODEL = "google-antigravity/gemini-3.5-flash"

KNOWN_MODELS: dict[str, int] = {
    "google-antigravity/gemini-3.7-flash": 65536,
    "google-antigravity/gemini-3.6-flash": 65536,
    "google-antigravity/gemini-3.5-flash": 65536,
    "google-antigravity/gemini-3.1-pro": 65535,
    "google-antigravity/claude-sonnet-4-6": 64000,
    "google-antigravity/claude-opus-4-6": 64000,
    "google-antigravity/gpt-oss-120b": 65536,
}

WIRE_PROFILES: dict[str, dict[str, object]] = {
    "gemini-3.5-flash-extra-low": {"modelEnum": "MODEL_PLACEHOLDER_M187", "maxOutputTokens": 65536},
    "gemini-3.5-flash-low": {"modelEnum": "MODEL_PLACEHOLDER_M20", "maxOutputTokens": 65536},
    "gemini-3-flash-agent": {"modelEnum": "MODEL_PLACEHOLDER_M132", "maxOutputTokens": 65536},
    "gemini-3.1-pro-low": {"modelEnum": "MODEL_PLACEHOLDER_M36", "maxOutputTokens": 65535},
    "gemini-pro-agent": {"modelEnum": "MODEL_PLACEHOLDER_M16", "maxOutputTokens": 65535},
    "claude-sonnet-4-6": {"maxOutputTokens": 64000},
    "claude-opus-4-6-thinking": {"maxOutputTokens": 64000},
    "openai/gpt-oss-120b-maas": {"maxOutputTokens": 65536},
}


def strip_provider_prefix(model: str) -> str:
    model = (model or "").strip()
    return model[len(ANTIGRAVITY_PREFIX) :] if model.startswith(ANTIGRAVITY_PREFIX) else model


def normalize_model_id(model: str) -> str:
    model = (model or "").strip()
    if not model:
        return DEFAULT_MODEL
    if "/" not in model:
        return f"{ANTIGRAVITY_PREFIX}{model}"
    return model


def _effort(effort: str | None) -> str:
    value = (effort or "low").lower().replace("_", "-")
    if value in {"none", "off", "disabled"}:
        return "off"
    if value in {"minimum", "minimal"}:
        return "minimal"
    if value in {"medium", "normal"}:
        return "medium"
    if value in {"high", "xhigh", "max"}:
        return "high"
    return "low"


def clamp_reasoning_effort(model: str, reasoning_effort: str | None = None) -> str:
    logical = strip_provider_prefix(normalize_model_id(model))
    effort = _effort(reasoning_effort)
    if effort == "off":
        return "off"
    if logical == "gemini-3.1-pro":
        return "high" if effort == "high" else "low"
    if logical == "gemini-3.5-flash":
        if effort == "high":
            return "high"
        if effort == "medium":
            return "medium"
        return "low"
    if logical in {"gpt-oss-120b", "openai/gpt-oss-120b-maas"}:
        return "medium"
    return effort


def resolve_wire_model_id(model: str, reasoning_effort: str | None = None) -> str:
    logical = strip_provider_prefix(normalize_model_id(model))
    effort = clamp_reasoning_effort(model, reasoning_effort)
    if logical == "gemini-3.1-pro":
        return "gemini-pro-agent" if effort == "high" else "gemini-3.1-pro-low"
    if logical == "gemini-3.5-flash":
        if effort == "high":
            return "gemini-3-flash-agent"
        if effort == "medium":
            return "gemini-3.5-flash-low"
        return "gemini-3.5-flash-extra-low"
    if logical == "claude-opus-4-6":
        return "claude-opus-4-6-thinking"
    if logical == "claude-sonnet-4-6":
        return "claude-sonnet-4-6"
    if logical in {"gpt-oss-120b", "openai/gpt-oss-120b-maas"}:
        return "openai/gpt-oss-120b-maas"
    return logical
