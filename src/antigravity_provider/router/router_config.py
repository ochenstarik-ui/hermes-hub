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
    request_options: dict[str, Any] = field(default_factory=dict)


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
    default_role: str = "manager"
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
    """Generate default clean multi-provider configuration (0 profiles, 13 canonical roles with empty chains)."""
    roles = RoleRegistry.get_default_role_policies()

    return RouterConfig(
        enabled=True,
        default_role="manager",
        roles=roles,
        profiles={},
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
            req_opts = pdata.get("request_options")
            if not isinstance(req_opts, dict):
                req_opts = {}
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
                request_options=dict(req_opts),
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
        raw_default_role = str(r_block.get("default_role", data.get("default_role", "manager"))).strip().lower()
        default_role = RoleRegistry.resolve_canonical_role(raw_default_role) if raw_default_role else "manager"
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

        # Automatic Idempotent Migration (A41 Clean Install)
        # Merge missing default roles into loaded user configuration without injecting fake profiles
        default_cfg = get_default_router_config()
        migration_needed = False
        new_roles_added: list[str] = []

        if not profiles:
            profiles = {}

        if not roles:
            roles = default_cfg.roles
            migration_needed = True
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
            if pcfg.request_options:
                profiles_data[pid]["request_options"] = pcfg.request_options

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

