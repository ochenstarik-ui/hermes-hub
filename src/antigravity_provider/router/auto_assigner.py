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
from antigravity_provider.router.role_registry import RoleRegistry
from antigravity_provider.router.router_config import (
    RolePolicy,
    RouterConfig,
    RouterProfileConfig,
    load_router_config,
    save_router_config,
)

logger = logging.getLogger("hermes.router.auto_assigner")

HUMAN_ROLE_LABELS = RoleRegistry.get_human_role_labels()

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
    "local-1": ("Локальный сервер 1", "coder", "primary"),
    "local-2": ("Локальный сервер 2", "fast", "primary"),
    "ag-spare-1": ("Резерв 1", "spare", "spare"),
    "ag-spare-2": ("Резерв 2", "spare", "spare"),
    "ag-cold-1": ("Холодный резерв 1", "spare", "cold"),
    "ag-cold-2": ("Холодный резерв 2", "spare", "cold"),
    "ag-cold-3": ("Холодный резерв 3", "spare", "cold"),
}


CANONICAL_ROLE_MAP = RoleRegistry.get_canonical_role_map()


class AutoAssigner:
    """Manages team view structure, auto-slot allocation, and duplicate checking."""

    @staticmethod
    def get_display_name_and_role(profile_id: str) -> Tuple[str, str, str]:
        """Get human-readable display name, logical role, and tier for a profile."""
        if profile_id in DEFAULT_SLOT_ROLES:
            return DEFAULT_SLOT_ROLES[profile_id]
        clean_name = profile_id.replace("-", " ").title()
        return (clean_name, "worker", "primary")

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
        """Find the optimal free internal profile slot for a provider.

        When all predefined candidate slots are authenticated/occupied, dynamically
        generates the next free profile ID without capping account count (P0-1).
        """
        config = load_router_config()
        provider_norm = (provider or "").strip().lower()

        provider_slots = {
            "antigravity": [
                "ag-orch-fallback", "ag-w1", "ag-w2", "ag-w3", "ag-w4",
                "ag-spare-1", "ag-spare-2", "ag-cold-1", "ag-cold-2", "ag-cold-3"
            ],
            "openai-codex": ["codex-orch", "codex-worker-1", "codex-worker-2"],
            "codex": ["codex-orch", "codex-worker-1", "codex-worker-2"],
            "opencode-go": ["opengo-1", "opengo-2", "opengo-3"],
            "opencode": ["opengo-1", "opengo-2", "opengo-3"],
            "claude": ["claude-orch", "claude-worker-1", "claude-worker-2"],
            "anthropic": ["claude-orch", "claude-worker-1", "claude-worker-2"],
            "grok": ["grok-orch", "grok-worker-1", "grok-worker-2"],
            "xai": ["grok-orch", "grok-worker-1", "grok-worker-2"],
            "local": ["local-1", "local-2"],
            "local-llm": ["local-1", "local-2"],
            "llama.cpp": ["local-1", "local-2"],
            "ollama": ["local-1", "local-2"],
            "vllm": ["local-1", "local-2"],
        }

        candidates = list(provider_slots.get(provider_norm, []))

        # Priority based on requested role
        if requested_role == "manager":
            if provider_norm in ("openai-codex", "codex") and "codex-orch" in candidates:
                candidates.remove("codex-orch")
                candidates.insert(0, "codex-orch")
            elif provider_norm == "antigravity" and "ag-orch-fallback" in candidates:
                candidates.remove("ag-orch-fallback")
                candidates.insert(0, "ag-orch-fallback")
        # 1. First check existing candidate profiles already in config
        for pid in candidates:
            pcfg = config.get_profile(pid)
            if not pcfg:
                continue
            status = ProfileAuthManager.get_profile_status(provider, pid)
            if not status.get("authenticated"):
                return pid

        # 2. Check remaining predefined slots and ensure definition
        for pid in candidates:
            status = ProfileAuthManager.get_profile_status(provider, pid)
            if not status.get("authenticated"):
                AutoAssigner.ensure_profile_definition(provider, pid)
                return pid

        # 3. Predefined slots occupied: dynamically generate unlimited candidates
        def _generate_candidates(prov: str):
            p = prov.lower()
            if p == "antigravity":
                for i in range(5, 200):
                    yield f"ag-w{i}"
            elif p in ("openai-codex", "codex"):
                for i in range(4, 200):
                    yield f"codex-{i}"
            elif p in ("opencode-go", "opencode"):
                for i in range(4, 200):
                    yield f"opengo-{i}"
            elif p in ("claude", "anthropic"):
                for i in range(3, 200):
                    yield f"claude-worker-{i}"
            elif p in ("grok", "xai"):
                for i in range(3, 200):
                    yield f"grok-worker-{i}"
            elif p in ("local", "local-llm", "llama.cpp", "ollama", "vllm"):
                for i in range(3, 200):
                    yield f"local-{i}"
            else:
                for i in range(1, 200):
                    yield f"{p}-{i}"

        for dynamic_pid in _generate_candidates(provider_norm):
            status = ProfileAuthManager.get_profile_status(provider, dynamic_pid)
            if not status.get("authenticated"):
                AutoAssigner.ensure_profile_definition(provider, dynamic_pid)
                return dynamic_pid

        return None

    @staticmethod
    def ensure_profile_definition(provider: str, profile_id: str) -> Tuple[bool, str]:
        """Persist a router profile for provider slots introduced by the UI.

        Model lists are sourced dynamically from ModelDiscoveryService (P0-3).
        If discovery has not run yet, preferred_models remains empty [] instead
        of inventing unsupported model literals.
        """
        config = load_router_config()
        if profile_id in config.profiles:
            return True, "Профиль уже зарегистрирован"

        from antigravity_provider.router.model_discovery_service import ModelDiscoveryService
        discovered_models = ModelDiscoveryService.get().get_models(provider) or []

        capabilities_map = {
            "grok": ["reasoning", "coding", "research"],
            "claude": ["reasoning", "coding", "review"],
            "opencode-go": ["coding", "research", "fast"],
            "openai-codex": ["coding", "reasoning"],
            "antigravity": ["coding", "reasoning", "research", "fast"],
            "local": ["reviewer", "coding", "reasoning", "fast", "research"],
            "local-llm": ["reviewer", "coding", "reasoning", "fast", "research"],
            "llama.cpp": ["reviewer", "coding", "reasoning", "fast", "research"],
            "ollama": ["reviewer", "coding", "reasoning", "fast", "research"],
            "vllm": ["reviewer", "coding", "reasoning", "fast", "research"],
        }
        capabilities = capabilities_map.get(provider, ["coding", "reasoning"])

        config.profiles[profile_id] = RouterProfileConfig(
            profile_id=profile_id,
            provider=provider,
            account_id=profile_id,
            capabilities=list(capabilities),
            preferred_models=list(discovered_models),
            enabled=True,
            max_concurrency=1,
        )
        if not save_router_config(config):
            return False, f"Не удалось сохранить профиль '{profile_id}' в конфигурации"
        return True, f"Профиль '{profile_id}' зарегистрирован"

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
        """Automatically distribute all authenticated profiles across canonical router roles (P0-4)."""
        config = load_router_config()
        authenticated_profiles: List[Tuple[str, RouterProfileConfig]] = []
        for pid, pcfg in config.profiles.items():
            if not pcfg.enabled:
                continue
            st = ProfileAuthManager.get_profile_status(pcfg.provider, pid)
            if st.get("authenticated"):
                authenticated_profiles.append((pid, pcfg))

        if not authenticated_profiles:
            return {
                "success": False,
                "message": "Нет подключённых аккаунтов для распределения",
                "total_authenticated": 0,
                "assigned_count": 0,
                "changes": [],
            }

        canonical_roles = [r for r in RoleRegistry.get_role_ids() if RoleRegistry.is_role_implemented(r)]
        changes: List[Dict[str, Any]] = []

        # Ensure canonical roles exist in config
        for rname in canonical_roles:
            if rname not in config.roles:
                config.roles[rname] = RolePolicy(role_name=rname)

        def _norm_prov(p: str) -> str:
            p = (p or "").lower().strip()
            if p in ("openai-codex", "codex"):
                return "codex"
            if p in ("opencode-go", "opencode"):
                return "opencode"
            if p in ("local-llm", "llama.cpp", "ollama", "vllm", "local"):
                return "local"
            if p in ("claude", "anthropic"):
                return "claude"
            if p in ("grok", "xai"):
                return "grok"
            return p

        unique_providers = set(_norm_prov(pcfg.provider) for _, pcfg in authenticated_profiles)

        if len(authenticated_profiles) == 1:
            # Case 1: Exactly 1 account connected -> assign as primary to all 6 roles
            single_pid, _ = authenticated_profiles[0]
            for role_name in canonical_roles:
                config.roles[role_name].preferred_chain = [single_pid]
                changes.append({
                    "profile_id": single_pid,
                    "role": role_name,
                    "message": f"Профиль '{single_pid}' назначен основным во все 6 ролей",
                })
        elif len(unique_providers) == 1:
            # Case 2: Multiple accounts of the same provider -> distribute / rotate across roles
            pids = [pid for pid, _ in authenticated_profiles]
            num_accs = len(pids)
            for idx, role_name in enumerate(canonical_roles):
                primary_pid = pids[idx % num_accs]
                fallbacks = [p for p in pids if p != primary_pid]
                config.roles[role_name].preferred_chain = [primary_pid] + fallbacks
                changes.append({
                    "profile_id": primary_pid,
                    "role": role_name,
                    "message": f"Профиль '{primary_pid}' назначен на роль '{role_name}' с ротацией квот",
                })
        else:
            # Case 3: Multiple providers connected -> distribute by role provider preferences
            role_provider_preferences = {
                "manager": ["codex", "antigravity", "opencode", "claude", "grok", "local"],
                "developer-1": ["codex", "antigravity", "opencode", "claude", "grok", "local"],
                "developer-2": ["codex", "antigravity", "opencode", "claude", "grok", "local"],
                "code-reviewer": ["codex", "opencode", "antigravity", "claude", "grok", "local"],
                "researcher": ["opencode", "antigravity", "grok", "claude", "codex", "local"],
                "tester": ["opencode", "antigravity", "local", "grok", "codex", "claude"],
            }

            by_prov: Dict[str, List[str]] = {}
            for pid, pcfg in authenticated_profiles:
                norm = _norm_prov(pcfg.provider)
                by_prov.setdefault(norm, []).append(pid)

            prov_cursors: Dict[str, int] = {k: 0 for k in by_prov}

            for role_name in canonical_roles:
                pref_order = role_provider_preferences.get(role_name, ["codex", "antigravity", "opencode"])
                chain: List[str] = []

                # Find primary for this role
                chosen_primary = None
                for prov in pref_order:
                    if prov in by_prov and by_prov[prov]:
                        acc_list = by_prov[prov]
                        cur = prov_cursors[prov]
                        chosen_primary = acc_list[cur % len(acc_list)]
                        prov_cursors[prov] = cur + 1
                        break

                if not chosen_primary:
                    all_pids = [pid for pid, _ in authenticated_profiles]
                    chosen_primary = all_pids[0]

                chain.append(chosen_primary)

                # Add remaining profiles as fallbacks in preference order
                for prov in pref_order:
                    if prov in by_prov:
                        for p in by_prov[prov]:
                            if p not in chain:
                                chain.append(p)
                for pid, _ in authenticated_profiles:
                    if pid not in chain:
                        chain.append(pid)

                config.roles[role_name].preferred_chain = chain
                changes.append({
                    "profile_id": chosen_primary,
                    "role": role_name,
                    "message": f"Профиль '{chosen_primary}' назначен основным на роль '{role_name}'",
                })

        save_router_config(config)

        try:
            from antigravity_provider.router.state_store import HubStateStore
            HubStateStore.get().refresh(force_scan=True)
        except Exception:
            pass

        try:
            from antigravity_provider.router.unified_health import EventLogService
            EventLogService.get().log(
                "routing",
                f"Авто-распределение завершено: {len(authenticated_profiles)} аккаунтов распределены по 6 ролям.",
                level="info",
            )
        except Exception:
            pass

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
            "manager": [],
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
                "local": "Local LLM",
                "local-llm": "Local LLM",
                "llama.cpp": "Local LLM (llama.cpp)",
                "ollama": "Ollama",
                "vllm": "vLLM",
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

    @staticmethod
    def persist_role_chain(role_id: str, desired_chain: List[str]) -> Tuple[bool, str]:
        """Persist a custom role chain order into router configuration."""
        if not role_id or not isinstance(role_id, str):
            return False, "Не указана роль для обновления цепочки"

        config = load_router_config()
        clean_role = role_id.strip().lower()
        canonical_role = role_id.strip() if role_id in config.roles else CANONICAL_ROLE_MAP.get(clean_role, role_id.strip())

        if canonical_role not in config.roles:
            return False, f"Неизвестная роль маршрутизатора: '{role_id}'"

        if len(desired_chain) != len(set(desired_chain)):
            return False, "Профиль не может повторяться в одной цепочке"

        missing = [pid for pid in desired_chain if pid not in config.profiles]
        if missing:
            return False, f"Профиль '{missing[0]}' не найден в конфигурации"

        policy = config.roles[canonical_role]
        policy.preferred_chain = list(desired_chain)
        config.roles[canonical_role] = policy

        if not save_router_config(config):
            return False, f"Не удалось сохранить цепочку роли '{canonical_role}' в конфигурации"

        try:
            from antigravity_provider.router.state_store import HubStateStore
            HubStateStore.get().refresh(force_scan=True)
        except Exception:
            pass

        from antigravity_provider.router.unified_health import EventLogService
        EventLogService.get().log(
            "routing",
            f"Для роли '{canonical_role}' сохранена новая цепочка: {list(desired_chain)}.",
            level="info",
        )
        return True, f"Цепочка роли '{canonical_role}' успешно сохранена: {', '.join(desired_chain)}"


def ensure_profile_in_routing(profile_id: str) -> tuple[bool, str]:
    """Keep existing chain rank or route a newly introduced profile slot.

    Lives outside the GUI wizard so hermetic tests can import it without customtkinter.
    """
    config = load_router_config()
    assigned_role = next(
        (role_id for role_id, policy in config.roles.items() if profile_id in policy.preferred_chain),
        "",
    )
    if assigned_role:
        return True, f"Профиль уже входит в цепочку '{assigned_role}'"
    _display_name, role_code, tier = AutoAssigner.get_display_name_and_role(profile_id)
    return AutoAssigner.assign_profile_to_role(profile_id, role_code, is_primary=tier == "primary")
