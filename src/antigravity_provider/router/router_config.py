"""Configuration schema and loader for Hermes Multi-Provider Account Router."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from antigravity_provider.router.role_registry import RoleRegistry
from pathlib import Path
from typing import Any, Dict, List, Optional
import yaml


@dataclass
class RouterProfileConfig:
    profile_id: str
    provider: str  # "openai-codex", "antigravity", "opencode-go"
    account_id: str = ""
    capabilities: list[str] = field(default_factory=list)
    preferred_models: list[str] = field(default_factory=list)
    fallback_models: list[str] = field(default_factory=list)
    auth_config: dict[str, Any] = field(default_factory=dict)
    enabled: bool = True
    max_concurrency: int = 1  # 1 for stateful process, >1 for stateless REST
    custom_base_url: Optional[str] = None


@dataclass
class RolePolicy:
    role_name: str
    preferred_chain: list[str] = field(default_factory=list)  # list of profile_id
    fallback_capabilities: list[str] = field(default_factory=list)
    max_failover_attempts: int = 4
    session_affinity_enabled: bool = True
    default_model: Optional[str] = None


@dataclass
class RouterConfig:
    enabled: bool = True
    default_role: str = "orchestrator"
    quota_cooldown_seconds: int = 1800  # 30 min default
    rate_limit_cooldown_seconds: int = 60  # 1 min default
    max_failover_attempts: int = 3
    cooldown_base_seconds: int = 300
    cooldown_max_seconds: int = 3600
    session_affinity_ttl_seconds: int = 1800
    quota_threshold_percent: float = 10.0
    quota_threshold_action: str = "notify"  # "notify" | "switch"
    roles: dict[str, RolePolicy] = field(default_factory=dict)
    profiles: dict[str, RouterProfileConfig] = field(default_factory=dict)
    pricing: dict[str, dict[str, float]] = field(default_factory=dict)
    raw_router_block: dict[str, Any] = field(default_factory=dict)

    def get_profile(self, profile_id: str) -> Optional[RouterProfileConfig]:
        return self.profiles.get(profile_id)

    def get_role_policy(self, role: str) -> RolePolicy:
        if role in self.roles:
            return self.roles[role]
        # Return generic fallback policy
        return RolePolicy(
            role_name=role,
            preferred_chain=list(self.profiles.keys()),
            fallback_capabilities=[role],
            max_failover_attempts=len(self.profiles),
            session_affinity_enabled=True,
        )


def get_default_router_config() -> RouterConfig:
    """Generate default built-in multi-provider configuration (16 profiles across 3 providers)."""
    profiles: dict[str, RouterProfileConfig] = {
        # 1. Codex Pool (3 accounts)
        "codex-orch": RouterProfileConfig(
            profile_id="codex-orch",
            provider="openai-codex",
            account_id="codex-acc-1",
            capabilities=["orchestrator", "coding", "reasoning"],
            preferred_models=["gpt-4o", "o3-mini", "codex"],
            fallback_models=["gpt-4o-mini"],
            max_concurrency=1,
        ),
        "codex-worker-1": RouterProfileConfig(
            profile_id="codex-worker-1",
            provider="openai-codex",
            account_id="codex-acc-2",
            capabilities=["coding", "coder-primary", "reasoning"],
            preferred_models=["gpt-4o", "o3-mini", "codex"],
            max_concurrency=1,
        ),
        "codex-worker-2": RouterProfileConfig(
            profile_id="codex-worker-2",
            provider="openai-codex",
            account_id="codex-acc-3",
            capabilities=["coding", "coder-secondary", "reviewer", "review"],
            preferred_models=["gpt-4o", "o3-mini", "codex"],
            max_concurrency=1,
        ),
        # 2. Antigravity Pool (10 accounts, 7 active, 3 cold)
        "ag-orch-fallback": RouterProfileConfig(
            profile_id="ag-orch-fallback",
            provider="antigravity",
            account_id="ag-acc-orch",
            capabilities=["orchestrator", "reasoning", "coding"],
            preferred_models=["gemini-3.7-flash", "claude-sonnet-4-6", "gemini-3.5-flash"],
            max_concurrency=1,
        ),
        "ag-w1": RouterProfileConfig(
            profile_id="ag-w1",
            provider="antigravity",
            account_id="ag-acc-w1",
            capabilities=["coding", "coder-primary", "reasoning"],
            preferred_models=["gemini-3.7-flash", "claude-sonnet-4-6", "gemini-3.5-flash"],
            max_concurrency=1,
        ),
        "ag-w2": RouterProfileConfig(
            profile_id="ag-w2",
            provider="antigravity",
            account_id="ag-acc-w2",
            capabilities=["coding", "coder-secondary", "reviewer", "review"],
            preferred_models=["gemini-3.7-flash", "gemini-3.5-flash"],
            max_concurrency=1,
        ),
        "ag-w3": RouterProfileConfig(
            profile_id="ag-w3",
            provider="antigravity",
            account_id="ag-acc-w3",
            capabilities=["research", "reasoning", "search"],
            preferred_models=["gemini-3.7-flash", "claude-sonnet-4-6"],
            max_concurrency=1,
        ),
        "ag-w4": RouterProfileConfig(
            profile_id="ag-w4",
            provider="antigravity",
            account_id="ag-acc-w4",
            capabilities=["coding", "reasoning", "fast"],
            preferred_models=["gemini-3.5-flash", "gemini-3.7-flash"],
            max_concurrency=1,
        ),
        "ag-spare-1": RouterProfileConfig(
            profile_id="ag-spare-1",
            provider="antigravity",
            account_id="ag-acc-sp1",
            capabilities=["hot-spare", "coding", "reasoning", "orchestrator", "research", "fast"],
            preferred_models=["gemini-3.7-flash", "gemini-3.5-flash"],
            max_concurrency=1,
        ),
        "ag-spare-2": RouterProfileConfig(
            profile_id="ag-spare-2",
            provider="antigravity",
            account_id="ag-acc-sp2",
            capabilities=["hot-spare", "coding", "reasoning", "orchestrator", "research", "fast"],
            preferred_models=["gemini-3.7-flash", "gemini-3.5-flash"],
            max_concurrency=1,
        ),
        "ag-cold-1": RouterProfileConfig(
            profile_id="ag-cold-1",
            provider="antigravity",
            account_id="ag-acc-c1",
            capabilities=["cold-spare", "coding", "reasoning"],
            preferred_models=["gemini-3.5-flash"],
            enabled=False,
            max_concurrency=1,
        ),
        "ag-cold-2": RouterProfileConfig(
            profile_id="ag-cold-2",
            provider="antigravity",
            account_id="ag-acc-c2",
            capabilities=["cold-spare", "coding", "reasoning"],
            preferred_models=["gemini-3.5-flash"],
            enabled=False,
            max_concurrency=1,
        ),
        "ag-cold-3": RouterProfileConfig(
            profile_id="ag-cold-3",
            provider="antigravity",
            account_id="ag-acc-c3",
            capabilities=["cold-spare", "coding", "reasoning"],
            preferred_models=["gemini-3.5-flash"],
            enabled=False,
            max_concurrency=1,
        ),
        # 3. OpenCode Go Pool (3 accounts)
        "opengo-1": RouterProfileConfig(
            profile_id="opengo-1",
            provider="opencode-go",
            account_id="opengo-acc-1",
            capabilities=["coding", "fast", "multimodal"],
            preferred_models=["deepseek-r1", "qwen-2.5-coder-32b", "deepseek-v3"],
            max_concurrency=5,
        ),
        "opengo-2": RouterProfileConfig(
            profile_id="opengo-2",
            provider="opencode-go",
            account_id="opengo-acc-2",
            capabilities=["research", "coding", "multimodal"],
            preferred_models=["deepseek-v3", "qwen-2.5-coder-32b", "deepseek-r1"],
            max_concurrency=5,
        ),
        "opengo-3": RouterProfileConfig(
            profile_id="opengo-3",
            provider="opencode-go",
            account_id="opengo-acc-3",
            capabilities=["fallback", "coding", "reasoning"],
            preferred_models=["deepseek-r1", "deepseek-v3", "qwen-2.5-coder-32b"],
            max_concurrency=5,
        ),
        # 4. Claude Pool (3 accounts)
        "claude-orch": RouterProfileConfig(
            profile_id="claude-orch",
            provider="claude",
            account_id="claude-acc-1",
            capabilities=["orchestrator", "coding", "reasoning"],
            preferred_models=["claude-3-7-sonnet", "claude-3-5-haiku", "claude-sonnet-4-6"],
            max_concurrency=2,
        ),
        "claude-worker-1": RouterProfileConfig(
            profile_id="claude-worker-1",
            provider="claude",
            account_id="claude-acc-2",
            capabilities=["coding", "coder-primary", "reasoning"],
            preferred_models=["claude-3-7-sonnet", "claude-3-5-haiku", "claude-sonnet-4-6"],
            max_concurrency=2,
        ),
        "claude-worker-2": RouterProfileConfig(
            profile_id="claude-worker-2",
            provider="claude",
            account_id="claude-acc-3",
            capabilities=["coding", "coder-secondary", "reviewer", "review"],
            preferred_models=["claude-3-7-sonnet", "claude-3-5-haiku"],
            max_concurrency=2,
        ),
        # 5. Grok Pool (3 accounts)
        "grok-orch": RouterProfileConfig(
            profile_id="grok-orch",
            provider="grok",
            account_id="grok-acc-1",
            capabilities=["orchestrator", "coding", "reasoning"],
            preferred_models=["grok-3", "grok-3-mini", "grok-4.5"],
            max_concurrency=2,
        ),
        "grok-worker-1": RouterProfileConfig(
            profile_id="grok-worker-1",
            provider="grok",
            account_id="grok-acc-2",
            capabilities=["coding", "coder-primary", "reasoning"],
            preferred_models=["grok-3", "grok-3-mini", "grok-4.5"],
            max_concurrency=2,
        ),
        "grok-worker-2": RouterProfileConfig(
            profile_id="grok-worker-2",
            provider="grok",
            account_id="grok-acc-3",
            capabilities=["research", "reasoning", "fast"],
            preferred_models=["grok-3", "grok-3-mini"],
            max_concurrency=2,
        ),
        # 6. Local LLM Pool (2 accounts)
        "local-1": RouterProfileConfig(
            profile_id="local-1",
            provider="local",
            account_id="local-acc-1",
            capabilities=["code-reviewer", "reviewer", "coder-secondary", "reasoning", "coding"],
            preferred_models=["Qwen3.8-27B-Q4_K_M.gguf", "default"],
            max_concurrency=1,
        ),
        "local-2": RouterProfileConfig(
            profile_id="local-2",
            provider="local",
            account_id="local-acc-2",
            capabilities=["tester", "fast", "research", "coding"],
            preferred_models=["Qwen3-4B-Instruct-2507-Q4_K_M.gguf", "default"],
            max_concurrency=1,
        ),
    }

    roles = RoleRegistry.get_default_role_policies()

    return RouterConfig(
        enabled=True,
        default_role="orchestrator",
        roles=roles,
        profiles=profiles,
    )


def load_router_config(config_path: Optional[Path] = None) -> RouterConfig:
    """Load RouterConfig from YAML file or return default built-in configuration."""
    if config_path is None:
        env_config = os.environ.get("HERMES_ROUTER_CONFIG", "").strip()
        if env_config:
            config_path = Path(env_config).expanduser()
        else:
            from antigravity_provider.paths import get_router_profiles_path
            config_path = get_router_profiles_path()

    if not config_path.is_file():
        return get_default_router_config()

    try:
        data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        r_block = data.get("router") if isinstance(data.get("router"), dict) else {}

        profiles_raw = data.get("profiles", {})
        profiles: dict[str, RouterProfileConfig] = {}
        for pid, pdata in profiles_raw.items():
            provider = pdata.get("provider", "antigravity")
            max_concurrency = int(pdata.get("max_concurrency", 1))
            if provider == "local":
                max_concurrency = 1
            profiles[pid] = RouterProfileConfig(
                profile_id=pid,
                provider=provider,
                account_id=pdata.get("account_id", pid),
                capabilities=list(pdata.get("capabilities", [])),
                preferred_models=list(pdata.get("preferred_models", [])),
                fallback_models=list(pdata.get("fallback_models", [])),
                auth_config=dict(pdata.get("auth_config", {})),
                enabled=bool(pdata.get("enabled", True)),
                max_concurrency=max_concurrency,
                custom_base_url=pdata.get("custom_base_url"),
            )

        roles_raw = data.get("roles", {})
        roles: dict[str, RolePolicy] = {}
        for rname, rdata in roles_raw.items():
            roles[rname] = RolePolicy(
                role_name=rname,
                preferred_chain=list(rdata.get("preferred_chain", [])),
                fallback_capabilities=list(rdata.get("fallback_capabilities", [])),
                max_failover_attempts=int(rdata.get("max_failover_attempts", 4)),
                session_affinity_enabled=bool(rdata.get("session_affinity_enabled", True)),
                default_model=rdata.get("default_model"),
            )

        pricing_raw = data.get("pricing", {})
        pricing: dict[str, dict[str, float]] = {}
        if isinstance(pricing_raw, dict):
            for m_name, p_entry in pricing_raw.items():
                if isinstance(p_entry, dict):
                    pricing[m_name] = {
                        "input_cost_per_m": float(p_entry.get("input_cost_per_m", 0.0)),
                        "output_cost_per_m": float(p_entry.get("output_cost_per_m", 0.0)),
                    }

        enabled = bool(r_block.get("enabled", data.get("enabled", True)))
        default_role = str(r_block.get("default_role", data.get("default_role", "orchestrator")))
        max_failover = int(r_block.get("max_failover_attempts", data.get("max_failover_attempts", 3)))
        cooldown_base = int(r_block.get("cooldown_base_seconds", data.get("cooldown_base_seconds", 300)))
        cooldown_max = int(r_block.get("cooldown_max_seconds", data.get("cooldown_max_seconds", 3600)))
        session_ttl = int(r_block.get("session_affinity_ttl_seconds", data.get("session_affinity_ttl_seconds", 1800)))
        quota_cooldown = int(r_block.get("quota_cooldown_seconds", data.get("quota_cooldown_seconds", 1800)))
        rate_cooldown = int(r_block.get("rate_limit_cooldown_seconds", data.get("rate_limit_cooldown_seconds", 60)))
        try:
            quota_threshold_percent = float(r_block.get("quota_threshold_percent", data.get("quota_threshold_percent", 10.0)))
        except (ValueError, TypeError):
            quota_threshold_percent = 10.0
        quota_threshold_action = str(r_block.get("quota_threshold_action", data.get("quota_threshold_action", "notify"))).strip().lower()
        if quota_threshold_action not in ("notify", "switch"):
            quota_threshold_action = "notify"

        # Automatic Idempotent Migration (P0-0.1)
        # Merge missing default profiles and roles into loaded user configuration
        default_cfg = get_default_router_config()
        migration_needed = False
        new_profiles_added: list[str] = []
        new_roles_added: list[str] = []

        if not profiles:
            profiles = default_cfg.profiles
        else:
            for def_pid, def_pcfg in default_cfg.profiles.items():
                if def_pid not in profiles:
                    profiles[def_pid] = def_pcfg
                    new_profiles_added.append(def_pid)
                    migration_needed = True

        if not roles:
            roles = default_cfg.roles
        else:
            # Сначала переименование старых ролей в канонические, и только
            # потом дополнение недостающими.
            #
            # Раньше здесь просто дописывались отсутствующие умолчания, а
            # RoleRegistry.migrate_legacy_roles не вызывалась ниоткуда —
            # проверено поиском по всему коду. В результате старые роли
            # оставались рядом с новыми: на конфигурации владельца интерфейс
            # показывал 19 агентов вместо 13, причём шесть пар были неотличимы
            # по названию (orchestrator и manager — оба «Менеджер проекта»,
            # reviewer и code-reviewer — оба «Ревьюер кода»). Разложить
            # аккаунты по такому списку невозможно.
            #
            # migrate_legacy_roles переносит preferred_chain дословно, поэтому
            # порядок аккаунтов, выставленный владельцем, сохраняется.
            renamed, renamed_any = RoleRegistry.migrate_legacy_roles(roles)
            if renamed_any:
                new_roles_added.extend(sorted(set(renamed) - set(roles)))
                roles = renamed
                migration_needed = True

            for def_rname, def_rpolicy in default_cfg.roles.items():
                if def_rname not in roles:
                    roles[def_rname] = def_rpolicy
                    new_roles_added.append(def_rname)
                    migration_needed = True

        if migration_needed and config_path.is_file():
            # 1. Create a backup file
            try:
                import shutil
                import time
                backup_path = config_path.with_name(f"{config_path.name}.bak_{int(time.time())}")
                if not backup_path.exists():
                    shutil.copy2(config_path, backup_path)
            except Exception as b_err:
                pass

            # 2. Save migrated config back
            try:
                cfg_to_save = RouterConfig(
                    enabled=enabled,
                    default_role=default_role,
                    quota_cooldown_seconds=quota_cooldown,
                    rate_limit_cooldown_seconds=rate_cooldown,
                    max_failover_attempts=max_failover,
                    cooldown_base_seconds=cooldown_base,
                    cooldown_max_seconds=cooldown_max,
                    session_affinity_ttl_seconds=session_ttl,
                    quota_threshold_percent=quota_threshold_percent,
                    quota_threshold_action=quota_threshold_action,
                    roles=roles,
                    profiles=profiles,
                    pricing=pricing,
                    raw_router_block=r_block,
                )
                save_router_config(cfg_to_save, config_path)
            except Exception:
                pass

        return RouterConfig(
            enabled=enabled,
            default_role=default_role,
            quota_cooldown_seconds=quota_cooldown,
            rate_limit_cooldown_seconds=rate_cooldown,
            max_failover_attempts=max_failover,
            cooldown_base_seconds=cooldown_base,
            cooldown_max_seconds=cooldown_max,
            session_affinity_ttl_seconds=session_ttl,
            quota_threshold_percent=quota_threshold_percent,
            quota_threshold_action=quota_threshold_action,
            roles=roles,
            profiles=profiles,
            pricing=pricing,
            raw_router_block=r_block,
        )
    except Exception:
        # Fall back gracefully to built-in defaults on YAML error
        return get_default_router_config()


def save_router_config(config: RouterConfig, config_path: Optional[Path] = None) -> bool:
    """Save RouterConfig to YAML file preserving canonical router block schema."""
    if config_path is None:
        env_config = os.environ.get("HERMES_ROUTER_CONFIG", "").strip()
        if env_config:
            config_path = Path(env_config).expanduser()
        else:
            from antigravity_provider.paths import get_router_profiles_path
            config_path = get_router_profiles_path()

    try:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        profiles_data = {}
        for pid, pcfg in config.profiles.items():
            profiles_data[pid] = {
                "provider": pcfg.provider,
                "account_id": pcfg.account_id,
                "capabilities": pcfg.capabilities,
                "preferred_models": pcfg.preferred_models,
                "fallback_models": pcfg.fallback_models,
                "enabled": pcfg.enabled,
                "max_concurrency": pcfg.max_concurrency,
            }
            if pcfg.custom_base_url:
                profiles_data[pid]["custom_base_url"] = pcfg.custom_base_url

        roles_data = {}
        for rname, rpol in config.roles.items():
            roles_data[rname] = {
                "role_name": rname,
                "preferred_chain": rpol.preferred_chain,
                "fallback_capabilities": rpol.fallback_capabilities,
                "max_failover_attempts": rpol.max_failover_attempts,
                "session_affinity_enabled": rpol.session_affinity_enabled,
            }
            if rpol.default_model:
                roles_data[rname]["default_model"] = rpol.default_model

        router_block = dict(config.raw_router_block) if config.raw_router_block else {}
        router_block.update({
            "enabled": config.enabled,
            "default_role": config.default_role,
            "max_failover_attempts": config.max_failover_attempts,
            "cooldown_base_seconds": config.cooldown_base_seconds,
            "cooldown_max_seconds": config.cooldown_max_seconds,
            "session_affinity_ttl_seconds": config.session_affinity_ttl_seconds,
            "quota_threshold_percent": config.quota_threshold_percent,
            "quota_threshold_action": config.quota_threshold_action,
        })

        data = {
            "router": router_block,
            "roles": roles_data,
            "profiles": profiles_data,
        }
        if config.pricing:
            data["pricing"] = config.pricing

        existing_comments = []
        if config_path.exists():
            try:
                for line in config_path.read_text(encoding="utf-8").splitlines():
                    if line.strip().startswith("#"):
                        existing_comments.append(line)
                    elif not line.strip():
                        if existing_comments:
                            existing_comments.append(line)
                    else:
                        break
            except Exception:
                pass

        dumped_yaml = yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
        if existing_comments:
            content = "\n".join(existing_comments).rstrip() + "\n\n" + dumped_yaml
        else:
            content = "# Hermes Router Configuration\n# Multi-Provider Profile and Role Routing Rules\n\n" + dumped_yaml

        config_path.write_text(content, encoding="utf-8")
        return True
    except Exception:
        return False

