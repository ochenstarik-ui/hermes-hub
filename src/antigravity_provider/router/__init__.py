"""Hermes Multi-Provider Account Router Package."""
from __future__ import annotations

from .router_config import RolePolicy, RouterConfig, RouterProfileConfig, load_router_config
from .health_tracker import (
    AUTH_REQUIRED,
    COOLDOWN,
    DISABLED,
    HEALTHY,
    IN_USE,
    QUOTA_EXHAUSTED,
    RATE_LIMITED,
    UNHEALTHY,
    HealthTracker,
    extract_model_family,
)
from .session_affinity import LeaseManager, SessionAffinityRecord, SessionAffinityTracker
from .router_engine import RouterEngine, get_router_engine
from .capability.capability_matrix import CapabilityMatrix, ModelCapability
from .supervisor.lifecycle_supervisor import LifecycleSupervisor
from .skills.skill_registry import UnifiedSkill, UnifiedSkillRegistry

SkillRegistry = UnifiedSkillRegistry

__all__ = [
    "RouterConfig",
    "RouterProfileConfig",
    "RolePolicy",
    "load_router_config",
    "HealthTracker",
    "HEALTHY",
    "IN_USE",
    "QUOTA_EXHAUSTED",
    "RATE_LIMITED",
    "COOLDOWN",
    "AUTH_REQUIRED",
    "DISABLED",
    "UNHEALTHY",
    "extract_model_family",
    "SessionAffinityTracker",
    "SessionAffinityRecord",
    "LeaseManager",
    "RouterEngine",
    "get_router_engine",
    "CapabilityMatrix",
    "ModelCapability",
    "LifecycleSupervisor",
    "SkillRegistry",
    "UnifiedSkillRegistry",
    "UnifiedSkill",
]
