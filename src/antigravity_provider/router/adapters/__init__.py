"""Adapter registry for router provider backends."""
from __future__ import annotations


from .antigravity_adapter import AntigravityAdapter
from .base_adapter import BaseProviderAdapter
from .claude_adapter import ClaudeAdapter
from .codex_adapter import CodexAdapter
from .deepseek_adapter import DeepSeekResponsesAdapter
from .grok_adapter import GrokAdapter
from .local_adapter import LocalLLMAdapter
from .opencode_adapter import OpenCodeGoAdapter

_ADAPTERS: dict[str, BaseProviderAdapter] = {
    "antigravity": AntigravityAdapter(),
    "google-antigravity": AntigravityAdapter(),
    "openai-codex": CodexAdapter(),
    "codex": CodexAdapter(),
    "opencode-go": OpenCodeGoAdapter(),
    "opencode-zen": OpenCodeGoAdapter(),
    "opencode": OpenCodeGoAdapter(),
    "claude": ClaudeAdapter(),
    "anthropic": ClaudeAdapter(),
    "grok": GrokAdapter(),
    "xai": GrokAdapter(),
    "xai-oauth": GrokAdapter(),
    "deepseek": DeepSeekResponsesAdapter(),
    "local": LocalLLMAdapter(),
    "local-llm": LocalLLMAdapter(),
    "llama.cpp": LocalLLMAdapter(),
    "ollama": LocalLLMAdapter(),
    "vllm": LocalLLMAdapter(),
}


def get_adapter(provider: str) -> BaseProviderAdapter:
    """Return the provider adapter for the given provider key."""
    norm = provider.strip().lower()
    if norm in _ADAPTERS:
        return _ADAPTERS[norm]
    raise ValueError(f"Unknown provider '{provider}'. Supported: {list(_ADAPTERS.keys())}")
