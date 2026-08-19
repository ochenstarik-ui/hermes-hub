from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Callable, Iterable

from .cloudcode import antigravity_user_agent
from .errors import ProxyError, TokenExpired

ANTIGRAVITY_ENDPOINTS = [
    "https://daily-cloudcode-pa.googleapis.com",
    "https://daily-cloudcode-pa.sandbox.googleapis.com",
]
STREAM_PATH = "/v1internal:streamGenerateContent?alt=sse"


def _sse_json_lines(response: Iterable[bytes]) -> Iterable[dict[str, Any]]:
    data_lines: list[str] = []
    for raw in response:
        line = raw.decode("utf-8", "replace").rstrip("\r\n")
        if not line:
            if data_lines:
                data = "\n".join(data_lines)
                data_lines = []
                if data != "[DONE]":
                    yield json.loads(data)
            continue
        if line.startswith(":"):
            continue
        if line.startswith("data:"):
            data_lines.append(line[5:].strip())
    if data_lines:
        data = "\n".join(data_lines)
        if data != "[DONE]":
            yield json.loads(data)


def _meaningful(resp: dict[str, Any]) -> bool:
    for candidate in resp.get("candidates") or []:
        for part in ((candidate.get("content") or {}).get("parts") or []):
            if part.get("functionCall"):
                return True
            if isinstance(part.get("text"), str) and part["text"].strip() and not part.get("thought"):
                return True
    return False


class AntigravityClient:
    def __init__(
        self,
        *,
        endpoints: list[str] | None = None,
        post_json: Callable[[str, dict[str, Any], dict[str, str]], dict[str, Any]] | None = None,
    ):
        self.endpoints = [e.rstrip("/") for e in (endpoints or ANTIGRAVITY_ENDPOINTS)]
        self.post_json = post_json

    def _headers(self, access_token: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            "User-Agent": antigravity_user_agent(),
        }

    def stream_generate(self, *, access_token: str, body: dict[str, Any]) -> Iterable[dict[str, Any]]:
        payload = json.dumps(body).encode("utf-8")
        headers = self._headers(access_token)
        last_error: Exception | None = None
        for endpoint in self.endpoints:
            req = urllib.request.Request(endpoint + STREAM_PATH, data=payload, headers=headers, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=300) as resp:
                    for event in _sse_json_lines(resp):
                        if event.get("error"):
                            code = int(event.get("error", {}).get("code") or 500)
                            if code == 401:
                                raise TokenExpired()
                            raise ProxyError(event["error"].get("message") or "Antigravity stream error", status=code)
                        yield event.get("response") if isinstance(event.get("response"), dict) else event
                    return
            except urllib.error.HTTPError as e:
                detail = e.read().decode("utf-8", "replace")
                if e.code == 401:
                    raise TokenExpired() from e
                last_error = ProxyError(f"Cloud Code Assist API error ({e.code}): {detail}", status=e.code)
                if e.code < 500:
                    break
            except urllib.error.URLError as e:
                last_error = ProxyError(f"Cloud Code Assist connection failed: {e}", status=502)
        if last_error:
            raise last_error

    def generate(self, *, access_token: str, body: dict[str, Any]) -> dict[str, Any]:
        if self.post_json is not None:
            return self.post_json(self.endpoints[0] + STREAM_PATH, body, self._headers(access_token))

        last: dict[str, Any] = {"candidates": [{"content": {"role": "model", "parts": []}, "finishReason": "STOP"}]}
        for attempt in range(2):
            parts: list[dict[str, Any]] = []
            finish = "STOP"
            usage: dict[str, Any] = {}
            response_id: str | None = None
            for chunk in self.stream_generate(access_token=access_token, body=body):
                response_id = chunk.get("responseId") or response_id
                usage = chunk.get("usageMetadata") or usage
                candidate = (chunk.get("candidates") or [{}])[0]
                parts.extend(((candidate.get("content") or {}).get("parts") or []))
                finish = candidate.get("finishReason") or finish
            last = {"candidates": [{"content": {"role": "model", "parts": parts}, "finishReason": finish}], "usageMetadata": usage}
            if response_id:
                last["responseId"] = response_id
            if _meaningful(last) or attempt == 1:
                return last
        return last
