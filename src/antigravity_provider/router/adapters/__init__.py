"""Adapter registry for router provider backends."""
from __future__ import annotations

from typing import Dict
from .base_adapter import BaseProviderAdapter
from .antigravity_adapter import AntigravityAdapter
from .codex_adapter import CodexAdapter
from .opencode_adapter import OpenCodeGoAdapter

_ADAPTERS: dict[str, BaseProviderAdapter] = {
    "antigravity": AntigravityAdapter(),
    "google-antigravity": AntigravityAdapter(),
    "openai-codex": CodexAdapter(),
    "codex": CodexAdapter(),
    "opencode-go": OpenCodeGoAdapter(),
    "opencode-zen": OpenCodeGoAdapter(),
    "opencode": OpenCodeGoAdapter(),
}


def get_adapter(provider_name: str) -> BaseProviderAdapter:
    normalized = provider_name.lower().strip()
    if normalized in _ADAPTERS:
        return _ADAPTERS[normalized]
    # Fall back to Antigravity adapter as default
    return _ADAPTERS["antigravity"]
