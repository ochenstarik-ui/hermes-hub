"""Tests for Roadmap Features (Lifecycle Supervisor, Policies, Skill Registry, Capability Matrix)."""
import pytest
import time
from pathlib import Path

from antigravity_provider.router.supervisor.lifecycle_supervisor import LifecycleSupervisor
from antigravity_provider.router.supervisor.policies import PolicyEnforcer, WebPolicyConfig, ToolPolicyConfig
from antigravity_provider.router.skills.skill_registry import UnifiedSkillRegistry, UnifiedSkill, SkillParameter
from antigravity_provider.router.capability.capability_matrix import CapabilityMatrix
from antigravity_provider.router.unified_health import (
    UnifiedHealthService,
    STATUS_HEALTHY,
    STATUS_NOT_CONFIGURED,
    STATUS_AUTH_REQUIRED,
)


def test_status_resolver_unconfigured_account():
    """Verify that unadded accounts strictly resolve to not_configured, never quota_exhausted or healthy."""
    service = UnifiedHealthService.get()
    profiles_by_prov = service.scan_all(force=True)
    
    for prov, profs in profiles_by_prov.items():
        for p in profs:
            if p.auth_state != "AUTHENTICATED" and p.auth_state != "AUTH_EXPIRED":
                # Must be not_configured or cold_spare
                assert p.health_state in (STATUS_NOT_CONFIGURED, "cold_spare", STATUS_AUTH_REQUIRED)
                assert p.health_state != STATUS_HEALTHY
                assert p.health_state != "quota_exhausted"


def test_lifecycle_supervisor_process_registration_and_lease(tmp_path):
    supervisor = LifecycleSupervisor(state_dir=tmp_path)
    entry = supervisor.register_process(
        pid=12345,
        name="test_worker",
        cmdline=["python", "-m", "worker"],
        owner_app="HermesHub",
        ttl_sec=10.0,
    )
    assert entry.pid == 12345
    assert entry.status == "running"
    
    # Heartbeat
    assert supervisor.heartbeat(entry.process_uuid) is True

    # Acquire lease
    lease1 = supervisor.acquire_lease("antigravity-1", "orchestrator", ttl_sec=5.0)
    assert lease1 is not None
    assert lease1.profile_id == "antigravity-1"

    # Concurrent lease for same profile should fail
    lease2 = supervisor.acquire_lease("antigravity-1", "coder", ttl_sec=5.0)
    assert lease2 is None

    # Release lease
    assert supervisor.release_lease(lease1.lease_id) is True
    # Now coder can acquire
    lease3 = supervisor.acquire_lease("antigravity-1", "coder", ttl_sec=5.0)
    assert lease3 is not None


def test_web_policy_enforcement():
    enforcer = PolicyEnforcer()
    
    # Allowed domains
    ok, _ = enforcer.validate_url("https://generativelanguage.googleapis.com/v1beta/models")
    assert ok is True

    ok, _ = enforcer.validate_url("https://api.openai.com/v1/chat/completions")
    assert ok is True

    # Blocked domains
    ok, _ = enforcer.validate_url("http://169.254.169.254/latest/meta-data")
    assert ok is False

    ok, _ = enforcer.validate_url("https://evil-hacker-site.com/steal")
    assert ok is False


def test_tool_policy_enforcement():
    enforcer = PolicyEnforcer()
    
    # Safe commands
    ok, _ = enforcer.validate_tool_execution("run_command", {"CommandLine": "git status"})
    assert ok is True

    # Dangerous command blocking
    ok, _ = enforcer.validate_tool_execution("run_command", {"CommandLine": "format C: /y"})
    assert ok is False


def test_unified_skill_registry():
    reg = UnifiedSkillRegistry.get()
    skills = reg.list_skills()
    assert len(skills) >= 3

    # Check provider translation
    ag_schema = reg.to_provider_schema("search_web", "antigravity")
    assert ag_schema["name"] == "search_web"
    assert "parameters" in ag_schema
    assert ag_schema["parameters"]["type"] == "OBJECT"

    openai_schema = reg.to_provider_schema("search_web", "openai-codex")
    assert openai_schema["type"] == "function"
    assert openai_schema["function"]["name"] == "search_web"


def test_capability_matrix_role_selection():
    matrix = CapabilityMatrix.get()
    # Find models supporting reasoning and tools
    candidates = matrix.find_best_model_for_role(required_tools=True, required_reasoning=True)
    assert len(candidates) >= 2
    model_ids = [c.model_id for c in candidates]
    assert "gemini-2.5-pro" in model_ids
    assert "gpt-5.3-codex" in model_ids
