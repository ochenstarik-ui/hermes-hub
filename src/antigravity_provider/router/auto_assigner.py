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

from antigravity_provider import paths
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

CANONICAL_ROLE_MAP = RoleRegistry.get_canonical_role_map()


class AutoAssigner:
    """Manages team view structure, auto-slot allocation, and duplicate checking."""

    @staticmethod
    def get_display_name_and_role(profile_id: str) -> Tuple[str, str, str]:
        """Get human-readable display name, logical role, and tier for a profile."""
        prov_map = {
            "ag": "Antigravity",
            "codex": "Codex",
            "opengo": "OpenCode",
            "claude": "Claude",
            "grok": "Grok",
            "local": "Локальный сервер",
            "openrouter": "OpenRouter",
            "nvidia": "NVIDIA NIM",
            "ollama": "Ollama",
            "vllm": "vLLM",
        }
        parts = profile_id.split("-")
        if len(parts) == 2 and parts[0] in prov_map and parts[1].isdigit():
            clean_name = f"{prov_map[parts[0]]} {parts[1]}"
            return (clean_name, "unassigned", "spare")
        clean_name = profile_id.replace("-", " ").title()
        return (clean_name, "unassigned", "spare")

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

        Generates clean numbered slots starting from 1 (codex-1, ag-1, claude-1,
        grok-1, opengo-1, local-1, openrouter-1, nvidia-1, ollama-1) upon first addition.
        """
        config = load_router_config()
        provider_norm = (provider or "").strip().lower()

        def _get_prefix(prov: str) -> str:
            p = (prov or "").strip().lower()
            if p in ("antigravity", "google-antigravity", "agy"):
                return "ag"
            if p in ("openai-codex", "codex", "openai"):
                return "codex"
            if p in ("opencode-go", "opencode", "opengo"):
                return "opengo"
            if p in ("claude", "anthropic"):
                return "claude"
            if p in ("grok", "xai"):
                return "grok"
            if p in ("local", "local-llm", "llama.cpp"):
                return "local"
            if p in ("openrouter",):
                return "openrouter"
            if p in ("nvidia", "nvidia-nim"):
                return "nvidia"
            if p in ("ollama",):
                return "ollama"
            if p in ("vllm",):
                return "vllm"
            return p

        prefix = _get_prefix(provider_norm)

        # 1. First check existing candidate profiles already in config
        for pid, pcfg in config.profiles.items():
            if _get_prefix(pcfg.provider) == prefix or pcfg.provider == provider_norm:
                status = ProfileAuthManager.get_profile_status(pcfg.provider, pid)
                if not status.get("authenticated"):
                    return pid

        # 2. Dynamically generate clean numbered slots (codex-1, ag-1, claude-1, etc.)
        for i in range(1, 200):
            candidate_pid = f"{prefix}-{i}"
            if candidate_pid in config.profiles:
                pcfg = config.profiles[candidate_pid]
                status = ProfileAuthManager.get_profile_status(pcfg.provider, candidate_pid)
                if status.get("authenticated"):
                    continue
            status = ProfileAuthManager.get_profile_status(provider, candidate_pid)
            if not status.get("authenticated"):
                AutoAssigner.ensure_profile_definition(provider, candidate_pid)
                return candidate_pid

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
            "xai": ["reasoning", "coding", "research"],
            "claude": ["reasoning", "coding", "review"],
            "anthropic": ["reasoning", "coding", "review"],
            "opencode-go": ["coding", "research", "fast"],
            "opencode": ["coding", "research", "fast"],
            "openai-codex": ["coding", "reasoning"],
            "codex": ["coding", "reasoning"],
            "antigravity": ["coding", "reasoning", "research", "fast"],
            "google-antigravity": ["coding", "reasoning", "research", "fast"],
            "local": ["reviewer", "coding", "reasoning", "fast", "research"],
            "local-llm": ["reviewer", "coding", "reasoning", "fast", "research"],
            "llama.cpp": ["reviewer", "coding", "reasoning", "fast", "research"],
            "ollama": ["reviewer", "coding", "reasoning", "fast", "research"],
            "vllm": ["reviewer", "coding", "reasoning", "fast", "research"],
            "openrouter": ["coding", "reasoning", "research", "fast", "reviewer"],
            "nvidia": ["coding", "reasoning", "fast"],
            "nvidia-nim": ["coding", "reasoning", "fast"],
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
            inferred_prov = None
            for prefix, prov in [
                ("ag-", "antigravity"),
                ("codex-", "openai-codex"),
                ("opengo-", "opencode-go"),
                ("claude-", "claude"),
                ("grok-", "grok"),
                ("local-", "local"),
                ("openrouter-", "openrouter"),
                ("nvidia-", "nvidia"),
                ("ollama-", "ollama"),
                ("vllm-", "vllm"),
            ]:
                if profile_id.startswith(prefix):
                    inferred_prov = prov
                    break
            if inferred_prov:
                AutoAssigner.ensure_profile_definition(inferred_prov, profile_id)
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
    def _calculate_auto_assignment(config: RouterConfig) -> Tuple[bool, List[Tuple[str, RouterProfileConfig]], Dict[str, List[str]], List[Dict[str, Any]]]:
        """Compute candidate auto-assignment chains and changes without writing to disk."""
        authenticated_profiles: List[Tuple[str, RouterProfileConfig]] = []
        for pid, pcfg in config.profiles.items():
            if not pcfg.enabled:
                continue
            st = ProfileAuthManager.get_profile_status(pcfg.provider, pid)
            if st.get("authenticated"):
                authenticated_profiles.append((pid, pcfg))

        if not authenticated_profiles:
            return False, [], {}, []

        canonical_roles = [r for r in RoleRegistry.get_role_ids() if RoleRegistry.is_role_implemented(r)]
        proposed_chains: Dict[str, List[str]] = {}
        changes: List[Dict[str, Any]] = []

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
            if p in ("nvidia-nim", "nvidia"):
                return "nvidia"
            return p

        unique_providers = set(_norm_prov(pcfg.provider) for _, pcfg in authenticated_profiles)

        if len(authenticated_profiles) == 1:
            single_pid, _ = authenticated_profiles[0]
            for role_name in canonical_roles:
                proposed_chains[role_name] = [single_pid]
                curr = list(config.roles[role_name].preferred_chain) if role_name in config.roles else []
                changes.append({
                    "role": role_name,
                    "role_name_ru": RoleRegistry.get_role_name_ru(role_name, role_name),
                    "current_chain": curr,
                    "proposed_chain": [single_pid],
                    "primary_profile": single_pid,
                    "message": f"Профиль '{single_pid}' назначен основным на роль '{role_name}'",
                })
        elif len(unique_providers) == 1:
            pids = [pid for pid, _ in authenticated_profiles]
            num_accs = len(pids)
            for idx, role_name in enumerate(canonical_roles):
                primary_pid = pids[idx % num_accs]
                fallbacks = [p for p in pids if p != primary_pid]
                chain = [primary_pid] + fallbacks
                proposed_chains[role_name] = chain
                curr = list(config.roles[role_name].preferred_chain) if role_name in config.roles else []
                changes.append({
                    "role": role_name,
                    "role_name_ru": RoleRegistry.get_role_name_ru(role_name, role_name),
                    "current_chain": curr,
                    "proposed_chain": chain,
                    "primary_profile": primary_pid,
                    "message": f"Профиль '{primary_pid}' назначен на роль '{role_name}' с ротацией квот",
                })
        else:
            role_provider_preferences = {
                "manager": ["codex", "antigravity", "opencode", "claude", "grok", "local", "openrouter", "nvidia"],
                "developer-1": ["codex", "antigravity", "opencode", "claude", "grok", "local", "openrouter", "nvidia"],
                "developer-2": ["codex", "antigravity", "opencode", "claude", "grok", "local", "openrouter", "nvidia"],
                "code-reviewer": ["codex", "opencode", "antigravity", "claude", "grok", "local", "openrouter", "nvidia"],
                "researcher": ["opencode", "antigravity", "grok", "claude", "codex", "local", "openrouter", "nvidia"],
                "tester": ["opencode", "antigravity", "local", "grok", "codex", "claude", "openrouter", "nvidia"],
                "integration-expert": ["codex", "antigravity", "opencode", "claude", "grok", "local", "openrouter", "nvidia"],
                "security-expert": ["claude", "codex", "antigravity", "grok", "opencode", "local", "openrouter", "nvidia"],
                "tech-writer": ["claude", "antigravity", "codex", "grok", "opencode", "local", "openrouter", "nvidia"],
                "analyst": ["claude", "antigravity", "codex", "grok", "opencode", "local", "openrouter", "nvidia"],
                "dependency-agent": ["antigravity", "codex", "opencode", "local", "claude", "grok", "openrouter", "nvidia"],
            }

            by_prov: Dict[str, List[str]] = {}
            for pid, pcfg in authenticated_profiles:
                norm = _norm_prov(pcfg.provider)
                by_prov.setdefault(norm, []).append(pid)

            prov_cursors: Dict[str, int] = {k: 0 for k in by_prov}

            for role_name in canonical_roles:
                pref_order = role_provider_preferences.get(role_name, ["codex", "antigravity", "opencode"])
                chain: List[str] = []

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

                for prov in pref_order:
                    if prov in by_prov:
                        for p in by_prov[prov]:
                            if p not in chain:
                                chain.append(p)
                for pid, _ in authenticated_profiles:
                    if pid not in chain:
                        chain.append(pid)

                proposed_chains[role_name] = chain
                curr = list(config.roles[role_name].preferred_chain) if role_name in config.roles else []
                changes.append({
                    "role": role_name,
                    "role_name_ru": RoleRegistry.get_role_name_ru(role_name, role_name),
                    "current_chain": curr,
                    "proposed_chain": chain,
                    "primary_profile": chosen_primary,
                    "message": f"Профиль '{chosen_primary}' назначен основным на роль '{role_name}'",
                })

        return True, authenticated_profiles, proposed_chains, changes

    @staticmethod
    def preview_auto_assign() -> Dict[str, Any]:
        """Calculate proposed auto-assignment changes without modifying configuration on disk."""
        config = load_router_config()
        # Scan on-disk profiles and ensure their definition in in-memory config
        prov_prefix_map = {
            "antigravity": "agy_profiles",
            "openai-codex": "codex_profiles",
            "opencode-go": "opengo_profiles",
            "claude": "claude_profiles",
            "grok": "grok_profiles",
            "local": "local_profiles",
            "openrouter": "openrouter_profiles",
            "nvidia": "nvidia_profiles",
            "ollama": "ollama_profiles",
            "vllm": "vllm_profiles",
        }
        for prov, subdir in prov_prefix_map.items():
            base_dir = paths.get_hermes_home() / subdir
            if base_dir.is_dir():
                for p_entry in base_dir.iterdir():
                    if p_entry.is_dir():
                        pid = p_entry.name
                        if pid not in config.profiles:
                            st = ProfileAuthManager.get_profile_status(prov, pid)
                            if st.get("authenticated"):
                                config.profiles[pid] = RouterProfileConfig(
                                    profile_id=pid,
                                    provider=prov,
                                    account_id=pid,
                                    enabled=True,
                                )

        ok, auth_profs, proposed_chains, changes = AutoAssigner._calculate_auto_assignment(config)
        if not ok or not auth_profs:
            return {
                "success": False,
                "message": "Нет подключённых аккаунтов для распределения",
                "total_authenticated": 0,
                "assigned_count": 0,
                "changes": [],
                "proposed_chains": {},
            }

        return {
            "success": True,
            "total_authenticated": len(auth_profs),
            "assigned_count": len(changes),
            "changes": changes,
            "proposed_chains": proposed_chains,
            "message": f"Сформирован план распределения {len(auth_profs)} аккаунтов",
        }

    @staticmethod
    def auto_assign_all() -> Dict[str, Any]:
        """Automatically distribute all authenticated profiles across canonical router roles (P0-4)."""
        config = load_router_config()
        # Scan on-disk profiles and ensure their definition in config.profiles
        prov_prefix_map = {
            "antigravity": "agy_profiles",
            "openai-codex": "codex_profiles",
            "opencode-go": "opengo_profiles",
            "claude": "claude_profiles",
            "grok": "grok_profiles",
            "local": "local_profiles",
            "openrouter": "openrouter_profiles",
            "nvidia": "nvidia_profiles",
            "ollama": "ollama_profiles",
            "vllm": "vllm_profiles",
        }
        for prov, subdir in prov_prefix_map.items():
            base_dir = paths.get_hermes_home() / subdir
            if base_dir.is_dir():
                for p_entry in base_dir.iterdir():
                    if p_entry.is_dir():
                        pid = p_entry.name
                        if pid not in config.profiles:
                            st = ProfileAuthManager.get_profile_status(prov, pid)
                            if st.get("authenticated"):
                                AutoAssigner.ensure_profile_definition(prov, pid)

        config = load_router_config()
        ok, auth_profs, proposed_chains, changes = AutoAssigner._calculate_auto_assignment(config)
        if not ok or not auth_profs:
            return {
                "success": False,
                "message": "Нет подключённых аккаунтов для распределения",
                "total_authenticated": 0,
                "assigned_count": 0,
                "changes": [],
            }

        for rname, chain in proposed_chains.items():
            if rname not in config.roles:
                config.roles[rname] = RolePolicy(role_name=rname)
            config.roles[rname].preferred_chain = list(chain)

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
                f"Авто-распределение завершено: {len(auth_profs)} аккаунтов распределены по ролям.",
                level="info",
            )
        except Exception:
            pass

        return {
            "success": True,
            "total_authenticated": len(auth_profs),
            "assigned_count": len(changes),
            "changes": changes,
            "message": f"Успешно распределено {len(auth_profs)} аккаунтов",
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
                "openrouter": "OpenRouter",
                "nvidia": "NVIDIA NIM",
                "nvidia-nim": "NVIDIA NIM",
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

    pcfg = config.get_profile(profile_id)
    provider = pcfg.provider if pcfg else ""
    if not provider:
        provider = profile_id.split("-")[0]

    target_role = "developer-1"
    pid_lower = profile_id.lower()
    if "orch" in pid_lower or "manager" in pid_lower or provider in ("claude", "anthropic"):
        target_role = "manager"
    elif "worker" in pid_lower or "coder" in pid_lower or provider in ("grok", "xai", "openai-codex", "codex", "opencode-go", "opencode"):
        target_role = "developer-1"
    elif "research" in pid_lower or provider in ("openrouter",):
        target_role = "researcher"
    elif "reviewer" in pid_lower or provider in ("local", "ollama", "vllm"):
        target_role = "code-reviewer"

    return AutoAssigner.assign_profile_to_role(profile_id, target_role, is_primary=True)
