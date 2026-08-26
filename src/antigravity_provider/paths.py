"""Single Source of Truth for Hermes Hub Filesystem Paths.

Ensures zero hardcoded absolute developer directories or usernames.
Fully respects HERMES_HOME for complete hermetic test isolation.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional


def get_hermes_home() -> Path:
    """Return base hermes home directory, respecting HERMES_HOME environment variable."""
    env_home = os.environ.get("HERMES_HOME")
    if env_home:
        p = Path(env_home).resolve()
        p.mkdir(parents=True, exist_ok=True)
        return p
    
    local_app = os.environ.get("LOCALAPPDATA", "")
    if local_app:
        p = Path(local_app) / "hermes"
    else:
        p = Path.home() / ".hermes"
    p.mkdir(parents=True, exist_ok=True)
    return p


def get_repo_root() -> Path:
    """Find repository / installation root containing assets and launcher."""
    cur = Path(__file__).resolve()
    for parent in [cur.parents[3], cur.parents[2], cur.parents[1]]:
        if (parent / "assets").exists() or (parent / "pyproject.toml").exists():
            return parent
    # Fallback to plugin directory in hermes home
    plugin_dir = get_hermes_home() / "plugins" / "antigravity-provider"
    if plugin_dir.exists():
        return plugin_dir
    return cur.parents[2]


def get_assets_dir() -> Path:
    return get_repo_root() / "assets"


def get_branding_dir() -> Path:
    return get_assets_dir() / "branding"


def get_providers_assets_dir() -> Path:
    return get_assets_dir() / "providers"


def get_logs_dir() -> Path:
    d = get_hermes_home() / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_log_file() -> Path:
    return get_logs_dir() / "hermes-hub.log"


def get_startup_log_file() -> Path:
    return get_logs_dir() / "startup.log"


def get_config_dir() -> Path:
    d = get_hermes_home()
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_router_profiles_path() -> Path:
    return get_config_dir() / "router_profiles.yaml"


def get_router_state_path() -> Path:
    return get_config_dir() / "router_state.json"


def get_router_active_profile_path() -> Path:
    return get_config_dir() / "router_active_profile.json"


def get_workflow_state_path() -> Path:
    """Return the persisted agent/workflow state sidecar.

    Logical roles and their execution routes remain canonical in
    ``router_profiles.yaml``.  This file stores only the extra agent metadata,
    graph layout and execution checkpoints which do not belong to routing.
    """
    return get_config_dir() / "workflow_state.json"


def get_agent_files_dir() -> Path:
    """Return the user-editable directory containing real Agent Files."""
    directory = get_hermes_home() / "agents"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def get_compatibility_path() -> Path:
    return get_config_dir() / "compatibility.json"


def get_profile_dir(profile_id: str, provider: Optional[str] = None) -> Path:
    """Return isolated storage directory for a profile.
    
    Accepts both (profile_id) and (provider, profile_id) or (profile_id, provider) gracefully.
    """
    # If first argument looks like a provider or swapped, resolve cleanly
    p_id = profile_id
    prov = provider

    if prov is None:
        p_lower = p_id.lower()
        if p_lower.startswith("ag-") or "antigravity" in p_lower:
            folder_prefix = "agy_profiles"
        elif p_lower.startswith("codex-") or "codex" in p_lower:
            folder_prefix = "codex_profiles"
        elif p_lower.startswith("opengo-") or "opencode" in p_lower:
            folder_prefix = "opengo_profiles"
        elif p_lower.startswith("claude-") or "claude" in p_lower or "anthropic" in p_lower:
            folder_prefix = "claude_profiles"
        elif p_lower.startswith("grok-") or "grok" in p_lower or "xai" in p_lower:
            folder_prefix = "grok_profiles"
        else:
            folder_prefix = f"{p_lower}_profiles"
    else:
        # Provider explicitly passed
        prov_lower = prov.lower()
        if "antigravity" in prov_lower or "agy" in prov_lower:
            folder_prefix = "agy_profiles"
        elif "codex" in prov_lower or "openai" in prov_lower:
            folder_prefix = "codex_profiles"
        elif "opencode" in prov_lower or "opengo" in prov_lower:
            folder_prefix = "opengo_profiles"
        elif "claude" in prov_lower or "anthropic" in prov_lower:
            folder_prefix = "claude_profiles"
        elif "grok" in prov_lower or "xai" in prov_lower:
            folder_prefix = "grok_profiles"
        else:
            folder_prefix = f"{prov_lower}_profiles"

    d = get_hermes_home() / folder_prefix / p_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_hermes_agent_dir() -> Path:
    return get_hermes_home() / "hermes-agent"


def get_hermes_agent_venv() -> Path:
    return get_hermes_agent_dir() / "venv"
