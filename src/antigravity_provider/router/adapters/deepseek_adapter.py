"""DeepSeek Responses API Adapter."""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional
import urllib.request
import urllib.error

from antigravity_provider.router.adapters import ProviderAdapter
from antigravity_provider.router.router_config import ProfileConfig

logger = logging.getLogger("hermes.router.adapter.deepseek")


class DeepSeekResponsesAdapter(ProviderAdapter):
    """Adapter for DeepSeek OpenAI-compatible and Responses APIs."""

    def invoke(self, profile: ProfileConfig, request: Dict[str, Any]) -> Dict[str, Any]:
        api_key = profile.extra.get("api_key", "")
        base_url = profile.extra.get("base_url", "https://api.deepseek.com/v1").rstrip("/")

        if not api_key:
            raise ValueError(f"DeepSeek profile '{profile.profile_id}' missing API key")

        model = request.get("model", "deepseek-chat")
        messages = request.get("messages", [])
        temperature = request.get("temperature", 0.7)

        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
        }

        if "tools" in request:
            payload["tools"] = request["tools"]
        if "response_format" in request:
            payload["response_format"] = request["response_format"]

        req_bytes = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{base_url}/chat/completions",
            data=req_bytes,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=45) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return data
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="ignore")
            logger.error(f"DeepSeek HTTP error {e.code}: {err_body}")
            raise RuntimeError(f"DeepSeek API error ({e.code}): {err_body}")
        except Exception as e:
            raise RuntimeError(f"DeepSeek connection error: {e}")
