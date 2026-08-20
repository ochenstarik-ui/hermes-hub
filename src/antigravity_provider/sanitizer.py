"""Central Sanitizer for Hermes Hub Logs and Exceptions.

Redacts:
- Authorization: Bearer <tokens>
- OpenAI API keys (sk-...)
- OpenCode API keys (opencode-...)
- Google OAuth access / refresh / id tokens
- Password / Secret fields in JSON
"""
from __future__ import annotations

import re
from typing import Any

_PATTERNS = [
    (re.compile(r"Bearer\s+([A-Za-z0-9\-_.~+/=]+)", re.IGNORECASE), r"Bearer [REDACTED]"),
    (re.compile(r"\b(sk-[A-Za-z0-9_\-]{8})[A-Za-z0-9_\-]+", re.IGNORECASE), r"\1...[REDACTED]"),
    (re.compile(r"\b(opencode-[A-Za-z0-9_\-]{6})[A-Za-z0-9_\-]+", re.IGNORECASE), r"\1...[REDACTED]"),
    (re.compile(r'("(?:access_token|refresh_token|id_token|api_key|client_secret)"\s*:\s*)"([^"]+)"', re.IGNORECASE), r'\1"[REDACTED]"'),
    (re.compile(r"((?:access_token|refresh_token|id_token|api_key|client_secret)\s*=\s*)([^\s&,]+)", re.IGNORECASE), r"\1[REDACTED]"),
]


def sanitize_text(text: str) -> str:
    """Redact sensitive credentials, keys, and tokens from any string."""
    if not text:
        return text
    sanitized = str(text)
    for pattern, replacement in _PATTERNS:
        sanitized = pattern.sub(replacement, sanitized)
    return sanitized


def sanitize_data(data: Any) -> Any:
    """Recursively sanitize dict, list, or primitive values."""
    if isinstance(data, dict):
        cleaned = {}
        for k, v in data.items():
            lower_k = str(k).lower()
            if any(s in lower_k for s in ("token", "secret", "password", "api_key", "credential", "auth")):
                cleaned[k] = "[REDACTED]"
            else:
                cleaned[k] = sanitize_data(v)
        return cleaned
    elif isinstance(data, list):
        return [sanitize_data(item) for item in data]
    elif isinstance(data, str):
        return sanitize_text(data)
    return data
