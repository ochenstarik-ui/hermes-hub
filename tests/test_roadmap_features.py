"""Tests for active roadmap policies and normalized health."""

from antigravity_provider.router.supervisor.policies import PolicyEnforcer, WebPolicyConfig, ToolPolicyConfig
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
                # Must be not_configured, cold_spare, auth_required, or disabled
                assert p.health_state in (STATUS_NOT_CONFIGURED, "cold_spare", STATUS_AUTH_REQUIRED, "disabled")
                assert p.health_state != STATUS_HEALTHY
                assert p.health_state != "quota_exhausted"


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

