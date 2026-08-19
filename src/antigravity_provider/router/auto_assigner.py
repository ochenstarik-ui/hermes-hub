"""Auto Assignment Engine for Hermes Multi-Provider Account Router.

Translates internal profile slots into human-readable team roles:
- "Главный оркестратор", "Резервный оркестратор"
- "Кодер 1", "Кодер 2", "Ревьюер", "Исследователь", "Быстрый агент", "Универсальный субагент"
- "Резерв 1", "Резерв 2", "Холодный резерв"

Automatically assigns slots, detects duplicate accounts, and rebuilds routing chains.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from antigravity_provider.router.profile_manager import ProfileAuthManager, mask_email, mask_id
from antigravity_provider.router.router_config import (
    RolePolicy,
    RouterConfig,
    RouterProfileConfig,
    load_router_config,
    save_router_config,
)

logger = logging.getLogger("hermes.router.auto_assigner")

HUMAN_ROLE_LABELS = {
    "orchestrator_primary": "Главный оркестратор",
    "orchestrator_fallback": "Резервный оркестратор",
    "coder_1": "Кодер 1",
    "coder_2": "Кодер 2",
    "reviewer": "Ревьюер",
    "researcher": "Исследователь",
    "fast_agent": "Быстрый агент",
    "universal_subagent": "Универсальный субагент",
    "spare_1": "Резерв 1",
    "spare_2": "Резерв 2",
    "cold_spare": "Холодный резерв",
}

DEFAULT_SLOT_ROLES = {
    "codex-orch": ("Главный оркестратор", "orchestrator", "primary"),
    "ag-orch-fallback": ("Резервный оркестратор", "orchestrator", "fallback"),
    "codex-worker-1": ("Кодер 1", "coder-primary", "primary"),
    "ag-w1": ("Кодер 2", "coder-primary", "fallback"),
    "codex-worker-2": ("Ревьюер", "reviewer", "primary"),
    "ag-w2": ("Исследователь", "research", "primary"),
    "ag-w3": ("Быстрый агент", "fast", "primary"),
    "ag-w4": ("Универсальный субагент", "universal", "primary"),
    "opengo-1": ("Кодер (OpenCode)", "coder-primary", "fallback_2"),
    "opengo-2": ("Исследователь (OpenCode)", "research", "fallback"),
    "opengo-3": ("Резервный роутер (OpenCode)", "orchestrator", "fallback_2"),
    "ag-spare-1": ("Резерв 1", "spare", "spare"),
    "ag-spare-2": ("Резерв 2", "spare", "spare"),
    "ag-cold-1": ("Холодный резерв 1", "spare", "cold"),
    "ag-cold-2": ("Холодный резерв 2", "spare", "cold"),
    "ag-cold-3": ("Холодный резерв 3", "spare", "cold"),
}


class AutoAssigner:
    """Manages team view structure, auto-slot allocation, and duplicate checking."""

    @staticmethod
    def get_display_name_and_role(profile_id: str) -> Tuple[str, str, str]:
        """Get human-readable display name, logical role, and tier for a profile."""
        return DEFAULT_SLOT_ROLES.get(profile_id, (profile_id, "worker", "primary"))

    @staticmethod
    def check_duplicate_identity(provider: str, email_or_id: str, exclude_profile_id: Optional[str] = None) -> Optional[str]:
        """Check if an account with the same email / account_id is already assigned to another profile."""
        if not email_or_id or "@" not in email_or_id:
            return None

        clean_target = email_or_id.strip().lower()
        config = load_router_config()

        for pid, pcfg in config.profiles.items():
            if pid == exclude_profile_id:
                continue
            if pcfg.provider != provider:
                continue

            status = ProfileAuthManager.get_profile_status(provider, pid)
            if not status.get("authenticated"):
                continue

            # Compare raw verified email from auth.json
            auth_data = ProfileAuthManager.load_profile_auth(provider, pid)
            if not auth_data:
                continue

            saved_email = auth_data.get("email") or auth_data.get("user_email")
            if saved_email and saved_email.strip().lower() == clean_target:
                return pid

        return None

    @staticmethod
    def find_free_slot(provider: str, requested_role: str = "auto") -> Optional[str]:
        """Find the optimal free internal profile slot for a provider."""
        config = load_router_config()

        provider_slots = {
            "antigravity": [
                "ag-orch-fallback", "ag-w1", "ag-w2", "ag-w3", "ag-w4",
                "ag-spare-1", "ag-spare-2", "ag-cold-1", "ag-cold-2", "ag-cold-3"
            ],
            "openai-codex": ["codex-orch", "codex-worker-1", "codex-worker-2"],
            "opencode-go": ["opengo-1", "opengo-2", "opengo-3"],
        }

        candidates = provider_slots.get(provider, [])

        # Priority based on requested role
        if requested_role == "orchestrator":
            if provider == "openai-codex" and "codex-orch" in candidates:
                candidates.insert(0, "codex-orch")
            elif provider == "antigravity" and "ag-orch-fallback" in candidates:
                candidates.insert(0, "ag-orch-fallback")

        # Find first slot without saved auth
        for pid in candidates:
            pcfg = config.get_profile(pid)
            if not pcfg:
                continue
            status = ProfileAuthManager.get_profile_status(provider, pid)
            if not status.get("authenticated"):
                return pid

        return candidates[0] if candidates else None

    @staticmethod
    def build_team_hierarchy() -> Dict[str, Any]:
        """Build the structured Hermes Team hierarchy for the Cockpit UI."""
        config = load_router_config()
        main_ag = ProfileAuthManager.get_main_profile("antigravity")
        main_codex = ProfileAuthManager.get_main_profile("openai-codex")

        team = {
            "orchestrator": [],
            "subagents": [],
            "spares": [],
            "summary": {
                "total": len(config.profiles),
                "active_authenticated": 0,
                "needs_auth": 0,
                "main_antigravity": main_ag,
                "main_codex": main_codex,
            }
        }

        # Categories
        for pid, pcfg in sorted(config.profiles.items()):
            display_name, log_role, tier = AutoAssigner.get_display_name_and_role(pid)
            status = ProfileAuthManager.get_profile_status(pcfg.provider, pid)
            is_auth = status.get("authenticated", False)

            if is_auth and pcfg.enabled:
                team["summary"]["active_authenticated"] += 1
            elif pcfg.enabled:
                team["summary"]["needs_auth"] += 1

            is_main = (pid == main_ag and pcfg.provider == "antigravity") or (pid == main_codex and pcfg.provider == "openai-codex")
            identity = status.get("email_masked") or status.get("account_id_masked") or status.get("error") or "Не авторизован"

            card = {
                "profile_id": pid,
                "display_name": display_name,
                "provider": pcfg.provider,
                "provider_label": "Google Antigravity" if pcfg.provider == "antigravity" else ("OpenAI Codex" if pcfg.provider == "openai-codex" else "OpenCode Go"),
                "logical_role": log_role,
                "tier": tier,
                "is_main": is_main,
                "identity": identity,
                "authenticated": is_auth,
                "enabled": pcfg.enabled,
                "preferred_models": pcfg.preferred_models,
                "storage": status.get("storage", "-"),
            }

            if "оркестратор" in display_name.lower():
                team["orchestrator"].append(card)
            elif "резерв" in display_name.lower() or tier in ("spare", "cold"):
                team["spares"].append(card)
            else:
                team["subagents"].append(card)

        return team

    @staticmethod
    def set_primary_orchestrator(profile_id: str) -> Tuple[bool, str]:
        """Designate a profile as the primary orchestrator and adjust fallback chains."""
        config = load_router_config()
        pcfg = config.get_profile(profile_id)
        if not pcfg:
            return False, f"Profile '{profile_id}' not found"

        # Update orchestrator role chain in router_profiles.yaml
        orch_policy = config.get_role_policy("orchestrator")
        current_chain = list(orch_policy.preferred_chain)

        if profile_id in current_chain:
            current_chain.remove(profile_id)
        current_chain.insert(0, profile_id)

        orch_policy.preferred_chain = current_chain
        config.roles["orchestrator"] = orch_policy
        save_router_config(config)

        display_name, _, _ = AutoAssigner.get_display_name_and_role(profile_id)
        return True, f"'{display_name}' ({profile_id}) назначен главным оркестратором роутера"
