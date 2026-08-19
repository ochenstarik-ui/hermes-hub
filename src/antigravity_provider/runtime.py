from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from .antigravity_client import AntigravityClient
from .cloudcode import load_or_onboard_project
from .credentials import CredentialStore, load_agy_keychain_credentials
from .errors import ProxyError, TokenExpired
from .oauth import refresh_access_token
from .openai_compat import ChatRequest, parse_chat_request, to_openai_completion
from .transform import build_generate_content_request


def load_antigravity_credentials(store: Any | None = None) -> dict[str, Any]:
    """Load, refresh, and persist credentials for plugin use."""
    if store is None:
        store = CredentialStore.default()
    keychain = load_agy_keychain_credentials()
    from_keychain = bool(keychain)
    stored = {} if from_keychain else store.load()
    creds = {**stored, **keychain}
    dirty = False

    access = creds.get("access_token") or creds.get("access") or creds.get("token")
    refresh = creds.get("refresh_token") or creds.get("refresh")
    project = creds.get("project_id") or creds.get("projectId")
    if not access and not refresh:
        raise ProxyError(
            "Missing Antigravity credentials. Run `hermes agy login`.",
            status=401,
            error_type="invalid_request_error",
        )
    expires = creds.get("expires_at") or creds.get("expires")
    if refresh and (not access or (isinstance(expires, (int, float)) and time.time() + 60 >= float(expires))):
        refreshed = refresh_access_token(str(refresh))
        creds.update(refreshed)
        access = refreshed["access_token"]
        refresh = creds.get("refresh_token") or creds.get("refresh")
        dirty = not from_keychain
    if not project:
        if not access:
            raise ProxyError(
                "Missing access token for Antigravity project discovery",
                status=401,
                error_type="invalid_request_error",
            )
        project = load_or_onboard_project(str(access))
        creds["project_id"] = project
        dirty = not from_keychain
    if dirty:
        store.save(creds)
    return {
        "access_token": str(access or creds["access_token"]),
        "refresh_token": str(refresh or creds.get("refresh_token") or ""),
        "project_id": str(project),
        "source": "agy-keychain" if from_keychain else "store",
    }


def build_upstream_body(request: ChatRequest, *, store: Any | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    creds = load_antigravity_credentials(store)
    body = build_generate_content_request(
        model=request.model,
        project_id=creds["project_id"],
        messages=request.messages,
        tools=request.tools,
        reasoning_effort=request.reasoning_effort,
        max_tokens=request.max_tokens,
        temperature=request.temperature,
        top_p=request.top_p,
        tool_choice=request.tool_choice,
    )
    return body, creds


def generate_chat_completion(
    payload: dict[str, Any],
    *,
    client: Any | None = None,
    store: Any | None = None,
) -> dict[str, Any]:
    """Execute one OpenAI-shaped chat request against Antigravity in-process."""
    request = parse_chat_request(payload)
    if client is None:
        client = AntigravityClient()
    if store is None:
        store = CredentialStore.default()
    body, creds = build_upstream_body(request, store=store)
    try:
        upstream = client.generate(access_token=creds["access_token"], body=body)
    except TokenExpired:
        if not creds.get("refresh_token"):
            raise
        refreshed = refresh_access_token(creds["refresh_token"])
        if creds.get("source") == "store":
            saved = store.load()
            saved.update(refreshed)
            store.save(saved)
        upstream = client.generate(access_token=refreshed["access_token"], body=body)
    return to_openai_completion(request.model, upstream)


def _namespace(value: Any) -> Any:
    if isinstance(value, dict):
        return SimpleNamespace(**{k: _namespace(v) for k, v in value.items()})
    if isinstance(value, list):
        return [_namespace(v) for v in value]
    return value


def openai_completion_object(completion: dict[str, Any]) -> SimpleNamespace:
    """Return an object compatible with Hermes' ChatCompletionsTransport."""
    completion = dict(completion)
    choices = []
    for raw_choice in completion.get("choices") or []:
        choice = dict(raw_choice)
        message = dict(choice.get("message") or {})
        message.setdefault("content", None)
        message.setdefault("tool_calls", None)
        choice["message"] = message
        choices.append(choice)
    completion["choices"] = choices
    completion.setdefault("usage", {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0})
    return _namespace(completion)


def ensure_provider_profile_files(root: Path | None = None) -> Path:
    """Install the tiny model-provider profile that makes `hermes model` see Antigravity."""
    if root is None:
        try:
            from hermes_constants import get_hermes_home

            root = get_hermes_home()
        except Exception:
            root = Path.home() / ".hermes"
    plugin_dir = Path(root).expanduser() / "plugins" / "model-providers" / "antigravity"
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / "__init__.py").write_text(
        "from antigravity_provider.hermes_provider import register_provider_profile\n"
        "register_provider_profile()\n",
        encoding="utf-8",
    )
    (plugin_dir / "plugin.yaml").write_text(
        "name: antigravity\n"
        "kind: model-provider\n"
        "version: 0.1.0\n"
        "description: Google Antigravity provider profile\n",
        encoding="utf-8",
    )
    return plugin_dir
