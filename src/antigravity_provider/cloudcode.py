from __future__ import annotations

import json
import os
import platform
import time
import urllib.error
import urllib.request
from typing import Any, Callable

from .errors import ProxyError

CLOUD_CODE_ENDPOINT = "https://cloudcode-pa.googleapis.com"
ANTIGRAVITY_LOAD_CODE_ASSIST_METADATA = {
    "ideType": "ANTIGRAVITY",
    "platform": "PLATFORM_UNSPECIFIED",
    "pluginType": "GEMINI",
}
TIER_LEGACY = "legacy-tier"
PROJECT_ONBOARD_MAX_ATTEMPTS = 5
PROJECT_ONBOARD_INTERVAL_SECONDS = 2


def antigravity_user_agent() -> str:
    version = os.getenv("PI_AI_ANTIGRAVITY_VERSION") or "2.1.4"
    system = platform.system().lower()
    os_name = "windows" if system.startswith("win") else ("darwin" if system == "darwin" else system or "linux")
    machine = platform.machine().lower()
    arch = "amd64" if machine in {"x86_64", "x64"} else ("386" if machine in {"i386", "i686"} else machine or "arm64")
    return f"antigravity/hub/{version} {os_name}/{arch}"


def _post_json(url: str, body: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")
        raise ProxyError(f"Cloud Code Assist API error ({e.code}): {detail}", status=e.code) from e


def read_project_id(value: object) -> str | None:
    if isinstance(value, str) and value:
        return value
    if isinstance(value, dict) and isinstance(value.get("id"), str) and value["id"]:
        return value["id"]
    return None


def read_default_tier(allowed_tiers: object) -> str:
    if not isinstance(allowed_tiers, list):
        return TIER_LEGACY
    for tier in allowed_tiers:
        if isinstance(tier, dict) and tier.get("isDefault") and isinstance(tier.get("id"), str) and tier["id"]:
            return tier["id"]
    return TIER_LEGACY


def load_or_onboard_project(
    access_token: str,
    *,
    post_json: Callable[[str, dict[str, Any], dict[str, str]], dict[str, Any]] | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> str:
    post_json = post_json or _post_json
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "User-Agent": antigravity_user_agent(),
    }
    load_payload = post_json(
        f"{CLOUD_CODE_ENDPOINT}/v1internal:loadCodeAssist",
        {"metadata": ANTIGRAVITY_LOAD_CODE_ASSIST_METADATA},
        headers,
    )
    existing = read_project_id(load_payload.get("cloudaicompanionProject"))
    if existing:
        return existing

    onboard_body = {
        "tierId": read_default_tier(load_payload.get("allowedTiers")),
        "metadata": ANTIGRAVITY_LOAD_CODE_ASSIST_METADATA,
    }
    for attempt in range(1, PROJECT_ONBOARD_MAX_ATTEMPTS + 1):
        if attempt > 1:
            sleep(PROJECT_ONBOARD_INTERVAL_SECONDS)
        op = post_json(f"{CLOUD_CODE_ENDPOINT}/v1internal:onboardUser", onboard_body, headers)
        if not op.get("done"):
            continue
        project_id = read_project_id((op.get("response") or {}).get("cloudaicompanionProject"))
        if project_id:
            return project_id
    raise ProxyError("onboardUser did not return a project id", status=502)
