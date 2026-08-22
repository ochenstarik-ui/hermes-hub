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
    "claude-orch": ("Оркестратор (Claude)", "orchestrator", "fallback"),
    "grok-orch": ("Оркестратор (Grok)", "orchestrator", "fallback"),
    "codex-worker-1": ("Кодер 1", "coder", "primary"),
    "claude-worker-1": ("Кодер (Claude)", "coder", "primary"),
    "ag-w1": ("Кодер 2", "coder", "fallback"),
    "grok-worker-1": ("Кодер (Grok)", "coder", "fallback"),
    "codex-worker-2": ("Ревьюер", "reviewer", "primary"),
    "claude-worker-2": ("Ревьюер (Claude)", "reviewer", "primary"),
    "ag-w2": ("Исследователь", "researcher", "primary"),
    "grok-worker-2": ("Исследователь (Grok)", "researcher", "primary"),
    "ag-w3": ("Быстрый агент", "general", "primary"),
    "ag-w4": ("Универсальный субагент", "general", "primary"),
    "opengo-1": ("Кодер (OpenCode)", "coder", "fallback_2"),
    "opengo-2": ("Исследователь (OpenCode)", "researcher", "fallback"),
    "opengo-3": ("Резервный роутер (OpenCode)", "orchestrator", "fallback_2"),
    "ag-spare-1": ("Резерв 1", "spare", "spare"),
    "ag-spare-2": ("Резерв 2", "spare", "spare"),
    "ag-cold-1": ("Холодный резерв 1", "spare", "cold"),
    "ag-cold-2": ("Холодный резерв 2", "spare", "cold"),
    "ag-cold-3": ("Холодный резерв 3", "spare", "cold"),
}


CANONICAL_ROLE_MAP = {
    "orchestrator": "orchestrator",
    "orchestrator_primary": "orchestrator",
    "orchestrator_fallback": "orchestrator",
    "главный оркестратор": "orchestrator",
    "резервный оркестратор": "orchestrator",
    "coder": "coder-primary",
    "coder_1": "coder-primary",
    "coder-1": "coder-primary",
    "coder-primary": "coder-primary",
    "кодер 1": "coder-primary",
    "coder_2": "coder-secondary",
    "coder-2": "coder-secondary",
    "coder-secondary": "coder-secondary",
    "кодер 2": "coder-secondary",
    "reviewer": "reviewer",
    "ревьюер": "reviewer",
    "research": "research",
    "researcher": "research",
    "исследователь": "research",
    "fast": "fast",
    "fast_agent": "fast",
    "быстрый агент": "fast",
    "general": "fast",
    "universal_subagent": "fast",
    "универсальный субагент": "fast",
    "tester": "fast",
    "тестировщик": "fast",
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
            "claude": ["claude-orch", "claude-worker-1", "claude-worker-2"],
            "grok": ["grok-orch", "grok-worker-1", "grok-worker-2"],
        }

        candidates = list(provider_slots.get(provider, []))

        # Priority based on requested role
        if requested_role == "orchestrator":
            if provider == "openai-codex" and "codex-orch" in candidates:
                candidates.remove("codex-orch")
                candidates.insert(0, "codex-orch")
            elif provider == "antigravity" and "ag-orch-fallback" in candidates:
                candidates.remove("ag-orch-fallback")
                candidates.insert(0, "ag-orch-fallback")

        # Find first slot without saved auth that exists in config
        for pid in candidates:
            pcfg = config.get_profile(pid)
            if not pcfg:
                continue
            status = ProfileAuthManager.get_profile_status(provider, pid)
            if not status.get("authenticated"):
                return pid

        return None

    @staticmethod
    def recommend_assignment(provider: str) -> Tuple[str, str, str]:
        """Analyze team health and return (recommended_slot, role_title_ru, reason_ru)."""
        config = load_router_config()

        # Check role chains for missing primary or missing fallback
        for rname, rpol in config.roles.items():
            chain = rpol.preferred_chain
            if not chain:
                continue

            # Check primary
            primary_pid = chain[0]
            pcfg = config.get_profile(primary_pid)
            if pcfg and pcfg.provider == provider:
                status = ProfileAuthManager.get_profile_status(provider, primary_pid)
                if not status.get("authenticated"):
                    dname, _, _ = AutoAssigner.get_display_name_and_role(primary_pid)
                    return primary_pid, dname, f"У ключевой роли '{rname}' сейчас отсутствует основной рабочий аккаунт."

            # Check fallbacks
            for fb_pid in chain[1:]:
                fb_cfg = config.get_profile(fb_pid)
                if fb_cfg and fb_cfg.provider == provider:
                    status = ProfileAuthManager.get_profile_status(provider, fb_pid)
                    if not status.get("authenticated"):
                        dname, _, _ = AutoAssigner.get_display_name_and_role(fb_pid)
                        return fb_pid, dname, f"У роли '{rname}' отсутствует резервный аккаунт для отказоустойчивости."

        # Fallback to general free slot
        slot = AutoAssigner.find_free_slot(provider)
        if slot:
            dname, _, _ = AutoAssigner.get_display_name_and_role(slot)
            return slot, dname, "Оптимальный свободный слот для расширения мощности команды."

        return "", "Нет свободных слотов", "Все доступные слоты провайдера уже подключены либо отсутствуют в конфигурации."

    @staticmethod
    def assign_profile_to_role(profile_id: str, role_name: str, is_primary: bool = True) -> Tuple[bool, str]:
        """Assign a profile to a canonical router role, updating fallback chains and persisting config."""
        config = load_router_config()
        pcfg = config.get_profile(profile_id)
        if not pcfg:
            return False, f"Профиль '{profile_id}' не найден"

        clean_role = role_name.strip().lower()
        if clean_role in {"spare", "резерв", "none", "unassigned"}:
            # Remove profile from all active role chains to keep strictly as spare pool
            for rname, rpolicy in config.roles.items():
                if profile_id in rpolicy.preferred_chain:
                    rpolicy.preferred_chain = [p for p in rpolicy.preferred_chain if p != profile_id]
                    config.roles[rname] = rpolicy
            pcfg.enabled = True
            config.profiles[profile_id] = pcfg
            save_router_config(config)
            return True, f"Профиль '{profile_id}' сохранен в пуле резерва (spare)"

        canonical_role = CANONICAL_ROLE_MAP.get(clean_role, clean_role)

        if canonical_role not in config.roles:
            return False, f"Неизвестная роль маршрутизатора: '{role_name}'"

        rpolicy = config.roles[canonical_role]
        chain = list(rpolicy.preferred_chain)
        if profile_id in chain:
            chain.remove(profile_id)

        if is_primary:
            chain.insert(0, profile_id)
        else:
            chain.append(profile_id)

        rpolicy.preferred_chain = chain
        config.roles[canonical_role] = rpolicy
        save_router_config(config)
        return True, f"Профиль '{profile_id}' назначен на роль '{canonical_role}' ({'основной' if is_primary else 'резервный'})"

    @staticmethod
    def auto_assign_all() -> Dict[str, Any]:
        """Automatically distribute all authenticated profiles across canonical router roles."""
        config = load_router_config()
        authenticated_profiles = []
        for pid, pcfg in config.profiles.items():
            if not pcfg.enabled:
                continue
            st = ProfileAuthManager.get_profile_status(pcfg.provider, pid)
            if st.get("authenticated"):
                authenticated_profiles.append((pid, pcfg))

        changes = []
        canonical_roles_order = ["orchestrator", "coder-primary", "coder-secondary", "reviewer", "research", "fast"]
        for idx, (pid, pcfg) in enumerate(authenticated_profiles):
            target_role = canonical_roles_order[idx % len(canonical_roles_order)]
            ok, msg = AutoAssigner.assign_profile_to_role(pid, target_role, is_primary=(idx < len(canonical_roles_order)))
            if ok:
                changes.append({"profile_id": pid, "role": target_role, "message": msg})

        return {
            "success": True,
            "total_authenticated": len(authenticated_profiles),
            "assigned_count": len(changes),
            "changes": changes,
        }

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

            prov_labels = {
                "antigravity": "Google Antigravity",
                "openai-codex": "OpenAI Codex",
                "codex": "OpenAI Codex",
                "opencode-go": "OpenCode Go",
                "opencode": "OpenCode Go",
                "claude": "Claude",
                "anthropic": "Claude",
                "grok": "Grok",
                "xai": "Grok",
            }
            provider_label = prov_labels.get(pcfg.provider.lower(), pcfg.provider)

            # Get identity & quota
            from antigravity_provider.router.quota_collector import AccountQuotaService
            ident = AccountQuotaService.get().get_identity(pcfg.provider, pid)
            snap = AccountQuotaService.get().get_snapshot(pcfg.provider, pid)

            primary_model = pcfg.preferred_models[0] if pcfg.preferred_models else "default"
            relevant_bucket = snap.get_bucket_for_model(primary_model) if snap else None

            card = {
                "profile_id": pid,
                "display_name": display_name,
                "provider": pcfg.provider,
                "provider_label": provider_label,
                "logical_role": log_role,
                "tier": tier,
                "is_main": (pid == main_ag and pcfg.provider == "antigravity")
                or (pid == main_codex and pcfg.provider == "openai-codex"),
                "identity": ident.primary_identifier() if is_auth else "Не авторизован",
                "plan": ident.plan.display_name if is_auth else "Тариф: неизвестен",
                "quota_str": relevant_bucket.formatted_remaining() if relevant_bucket else "Квота: доступна",
                "quota_bucket": relevant_bucket,
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
        return AutoAssigner.assign_profile_to_role(profile_id, "orchestrator", is_primary=True)
