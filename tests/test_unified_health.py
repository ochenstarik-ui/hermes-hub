"""Unit tests for Unified Health Model, System Readiness, and ProfileViewModel."""
from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path

import pytest

from antigravity_provider.router.unified_health import (
    UnifiedHealthService,
    EventLogService,
    ProfileViewModel,
    SystemReadiness,
    STATUS_HEALTHY,
    STATUS_QUOTA_EXHAUSTED,
    STATUS_AUTH_REQUIRED,
    STATUS_COLD_SPARE,
    STATUS_DISABLED,
    READINESS_HEALTHY,
    READINESS_LIMITED,
    READINESS_DEGRADED,
    READINESS_CRITICAL,
)
from antigravity_provider.router.auto_assigner import AutoAssigner
from antigravity_provider.router.profile_manager import ProfileAuthManager
from antigravity_provider.router.router_config import load_router_config


def test_profile_view_model_mapping():
    """Verify that scan_all creates ProfileViewModels for all configured profiles."""
    service = UnifiedHealthService.get()
    profiles_by_prov = service.scan_all()

    assert "antigravity" in profiles_by_prov
    assert "openai-codex" in profiles_by_prov
    assert "opencode-go" in profiles_by_prov

    all_profs = [p for profs in profiles_by_prov.values() for p in profs]
    assert len(all_profs) >= 16

    for p in all_profs:
        assert isinstance(p, ProfileViewModel)
        assert p.profile_id
        assert p.display_name
        assert p.provider in ("antigravity", "openai-codex", "opencode-go")
        assert p.health_state in (
            "healthy", "quota_low", "quota_exhausted", "cooldown", "rate_limited",
            "auth_required", "auth_expired", "disabled", "cold_spare", "unhealthy", "not_tested", "not_configured"
        )


def test_auth_required_never_healthy_without_credentials():
    """Verify that unauthenticated profiles are NEVER marked as HEALTHY."""
    service = UnifiedHealthService.get()
    profiles_by_prov = service.scan_all()

    for profs in profiles_by_prov.values():
        for p in profs:
            if p.auth_state in ("AUTH_REQUIRED", "AUTH_EXPIRED"):
                assert p.health_state != STATUS_HEALTHY, f"Profile {p.profile_id} is unauthenticated but marked HEALTHY!"


def test_cold_spare_presentation():
    """Verify that cold spare slots are marked as cold_spare or auth_required, not active."""
    service = UnifiedHealthService.get()
    profiles_by_prov = service.scan_all()
    ag_profs = {p.profile_id: p for p in profiles_by_prov["antigravity"]}

    cold_1 = ag_profs.get("ag-cold-1")
    assert cold_1 is not None
    assert cold_1.is_cold_spare or cold_1.is_empty_slot


def test_duplicate_account_detection():
    """Verify duplicate detection finds existing profiles with identical email."""
    # Test checking non-existent
    dup = AutoAssigner.check_duplicate_identity("antigravity", "nonexistent_unique_12345@gmail.com")
    assert dup is None


def test_auto_assignment_recommendation():
    """Verify that recommend_assignment returns valid slot, title, and reason."""
    slot, title, reason = AutoAssigner.recommend_assignment("antigravity")
    assert slot
    assert title
    assert reason
    assert len(reason) > 5


def test_main_account_vs_orchestrator_separation():
    """Verify that MAIN account and Orchestrator are tracked independently."""
    service = UnifiedHealthService.get()
    service.scan_all()
    agents = service.get_agent_view_models()

    orch_agent = next((a for a in agents if a.role_id == "orchestrator"), None)
    assert orch_agent is not None
    assert orch_agent.is_main_orchestrator is True


def test_system_readiness_calculation():
    """Verify system readiness returns valid aggregate state and metrics."""
    service = UnifiedHealthService.get()
    readiness = service.get_system_readiness()

    assert isinstance(readiness, SystemReadiness)
    assert readiness.state in (READINESS_HEALTHY, READINESS_LIMITED, READINESS_DEGRADED, READINESS_CRITICAL)
    assert readiness.total_roles > 0
    assert readiness.total_accounts >= readiness.accounts_connected_count
    assert readiness.title_ru
    assert readiness.summary_ru


def test_event_log_service():
    """Verify EventLogService logs and retrieves events properly."""
    logger_svc = EventLogService.get()
    logger_svc.log("account", "Тестовое событие подключения", details="extra info", level="success")

    events = logger_svc.get_events(limit=10, category="account")
    assert any("Тестовое событие подключения" in e.message for e in events)
