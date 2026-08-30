"""Test suite for Task A37: Agent Isolation, Credential Protection, Workspace Boundaries, and Forensic Audit."""
from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch
import pytest

from fastapi.testclient import TestClient

from antigravity_provider.router.security_guard import (
    WorkspaceBoundaryGuard,
    NetworkBoundaryGuard,
    AgentWorkspaceGuard,
    BoundaryViolationError,
    NetworkBoundaryViolationError,
    scrub_secrets,
    scrub_string,
    get_workspace_guard,
)
from antigravity_provider.router.unified_health import EventLogService
from antigravity_provider.router.action_handler import ActionExecutor, do_delete_credentials
from antigravity_provider.router.web.server import app


# ═══════════════════════════════════════════════════════════════
#  P0-1: Workspace Boundary & Destructive Operations Guard Tests
# ═══════════════════════════════════════════════════════════════


class TestWorkspaceBoundaryGuard:
    """Tests for workspace boundaries, traversal prevention, and credential defense."""

    def test_deletion_outside_allowed_workspace_is_blocked(self, tmp_path):
        guard = WorkspaceBoundaryGuard(additional_allowed_roots=[tmp_path / "allowed_workspace"])
        (tmp_path / "allowed_workspace").mkdir(parents=True, exist_ok=True)
        outside_file = tmp_path / "outside_workspace" / "sensitive_file.txt"
        outside_file.parent.mkdir(parents=True, exist_ok=True)
        outside_file.write_text("critical data", encoding="utf-8")

        ok, reason, safe_alt = guard.validate_path(outside_file, operation="delete")
        assert ok is False
        assert "за пределами разрешённых рабочих областей" in reason
        assert safe_alt is not None

        with pytest.raises(BoundaryViolationError):
            guard.safe_delete_file(outside_file)

    def test_unconditional_protection_of_credential_pools_and_ssh(self, tmp_path, monkeypatch):
        hermes_home = tmp_path / ".hermes"
        monkeypatch.setenv("HERMES_HOME", str(hermes_home))

        guard = WorkspaceBoundaryGuard(additional_allowed_roots=[hermes_home])

        # 1. agy_profiles
        agy_profile = hermes_home / "agy_profiles" / "ag-w1" / "auth.json"
        agy_profile.parent.mkdir(parents=True, exist_ok=True)
        agy_profile.write_text("token", encoding="utf-8")

        ok, reason, alt = guard.validate_path(agy_profile, operation="delete")
        assert ok is False
        assert "защищённого каталога учётных данных" in reason or "защищённым" in reason
        assert "delete_credentials" in alt

        # 2. hub_settings.json
        settings_p = hermes_home / "hub_settings.json"
        settings_p.write_text("{}", encoding="utf-8")
        ok, reason, _ = guard.validate_path(settings_p, operation="delete")
        assert ok is False

        # 3. .ssh
        fake_ssh = Path.home() / ".ssh" / "id_rsa"
        ok, reason, _ = guard.validate_path(fake_ssh, operation="delete")
        assert ok is False

    def test_path_traversal_and_symlink_bypass_prevention(self, tmp_path):
        ws_dir = tmp_path / "workspace"
        ws_dir.mkdir(parents=True, exist_ok=True)
        secret_outside = tmp_path / "secret.txt"
        secret_outside.write_text("secret", encoding="utf-8")

        guard = WorkspaceBoundaryGuard(additional_allowed_roots=[ws_dir])

        # Relative path traversal attack: workspace/../../secret.txt
        traversal_path = ws_dir / "subdir" / ".." / ".." / "secret.txt"
        ok, reason, _ = guard.validate_path(traversal_path, operation="delete")
        assert ok is False
        assert "за пределами" in reason

        # Symlink attack: symlink inside workspace pointing outside
        link_inside = ws_dir / "link_to_outside"
        try:
            link_inside.symlink_to(secret_outside)
            ok_symlink, reason_symlink, _ = guard.validate_path(link_inside, operation="delete")
            assert ok_symlink is False
            assert "за пределами" in reason_symlink
        except OSError:
            # On platforms without symlink privileges, skip symlink creation
            pass

    def test_shell_command_analysis_and_classification(self, tmp_path):
        guard = WorkspaceBoundaryGuard(additional_allowed_roots=[tmp_path / "project"])
        project_dir = tmp_path / "project"
        project_dir.mkdir(parents=True, exist_ok=True)

        # 1. Dangerous rm -rf / or outside
        ok, reason, _ = guard.validate_command("rm -rf /etc/passwd", cwd=project_dir)
        assert ok is False

        # 2. Windows del C:\Windows
        ok, reason, _ = guard.validate_command("del /f /q C:\\Windows\\System32", cwd=project_dir)
        assert ok is False

        # 3. Safe rm within project
        ok, reason, _ = guard.validate_command("rm temp_file.log", cwd=project_dir)
        assert ok is True

    def test_dry_run_deletion_reports_metadata_without_deleting(self, tmp_path):
        guard = WorkspaceBoundaryGuard(additional_allowed_roots=[tmp_path])
        test_dir = tmp_path / "to_delete"
        test_dir.mkdir(parents=True, exist_ok=True)
        file1 = test_dir / "file1.txt"
        file2 = test_dir / "file2.txt"
        file1.write_text("hello 1", encoding="utf-8")
        file2.write_text("hello 222", encoding="utf-8")

        res = guard.dry_run_deletion([test_dir])
        assert res["dry_run"] is True
        assert res["allowed"] is True
        assert res["total_dirs"] >= 1
        assert res["total_files"] == 0  # directory item
        assert res["total_bytes"] == len("hello 1".encode()) + len("hello 222".encode())
        assert file1.exists()
        assert file2.exists()


# ═══════════════════════════════════════════════════════════════
#  P0-2: Agent Isolation & Credential Separation Tests
# ═══════════════════════════════════════════════════════════════


class TestAgentIsolation:
    """Tests for dedicated agent workspaces, role-scoped credentials, and actor attribution."""

    def test_dedicated_agent_workspace_creation(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HERMES_HOME", str(tmp_path))

        ws_dev1 = AgentWorkspaceGuard.get_agent_workspace_dir("developer-1")
        ws_rev = AgentWorkspaceGuard.get_agent_workspace_dir("code-reviewer")

        assert ws_dev1.is_dir()
        assert ws_rev.is_dir()
        assert ws_dev1 != ws_rev
        assert "agent-developer-1" in str(ws_dev1)
        assert "agent-code-reviewer" in str(ws_rev)

    def test_role_scoped_credential_isolation(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HERMES_HOME", str(tmp_path))

        env_dev1 = AgentWorkspaceGuard.build_agent_subprocess_env(
            agent_id="developer-1",
            role="coder",
            assigned_profile_id="ag-w1",
        )

        assert env_dev1["HERMES_AGENT_ID"] == "developer-1"
        assert env_dev1["HERMES_AGENT_ROLE"] == "coder"
        assert "ag-w1" in env_dev1["HOME"]
        assert "ag-w1" in env_dev1["USERPROFILE"]

        # Ensure no cross-agent foreign API keys leak
        assert "ANTHROPIC_API_KEY" not in env_dev1
        assert "OPENAI_API_KEY" not in env_dev1

    def test_actor_attribution_in_action_executor(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HERMES_HOME", str(tmp_path))

        EventLogService._instance = None
        event_svc = EventLogService.get()

        res = ActionExecutor.execute(
            action="dry_run_delete",
            data={"paths": [str(tmp_path)]},
            actor="agent:developer-1",
        )

        assert res["ok"] is True
        events = event_svc.get_events(limit=5)
        actor_events = [e for e in events if e.actor == "agent:developer-1"]
        assert len(actor_events) > 0
        assert actor_events[0].action == "dry_run_delete"
        assert actor_events[0].outcome == "dry_run"


# ═══════════════════════════════════════════════════════════════
#  P0-3: Network Boundary Guard & CORS Tests
# ═══════════════════════════════════════════════════════════════


class TestNetworkBoundaryAndCORS:
    """Tests for outbound destination whitelist, strict CORS, and network HTTP disclosures."""

    def test_outbound_destination_whitelist(self):
        # Allowed AI providers & releases
        assert NetworkBoundaryGuard.is_host_allowed("https://api.anthropic.com/v1/messages") is True
        assert NetworkBoundaryGuard.is_host_allowed("https://generativelanguage.googleapis.com") is True
        assert NetworkBoundaryGuard.is_host_allowed("https://api.github.com/repos/releases") is True
        assert NetworkBoundaryGuard.is_host_allowed("http://127.0.0.1:11434/api/tags") is True
        assert NetworkBoundaryGuard.is_host_allowed("http://localhost:8000/v1/models") is True

        # Blocked external / rogue hosts
        assert NetworkBoundaryGuard.is_host_allowed("https://evil-hacker.com/exfil") is False
        assert NetworkBoundaryGuard.is_host_allowed("http://internal-artifactory.local:8081") is False

        with pytest.raises(NetworkBoundaryViolationError):
            NetworkBoundaryGuard.validate_outbound_url("http://internal-artifactory.local/coordination")

    def test_cors_rejects_wildcard_with_credentials(self, client):
        response = client.options(
            "/api/snapshot",
            headers={"Origin": "https://attacker.example.com", "Access-Control-Request-Method": "GET"},
        )
        # Should NOT return allow-origin: * or echo back attacker origin
        allow_origin = response.headers.get("access-control-allow-origin")
        assert allow_origin != "*"
        assert allow_origin != "https://attacker.example.com"

    def test_network_http_warning_on_external_bind(self, client, monkeypatch):
        from antigravity_provider.router import settings_service

        fake_settings = {
            "web_api_host": "0.0.0.0",
            "web_api_token": "secret_token_123",
        }
        monkeypatch.setattr(settings_service, "get_hub_settings", lambda: fake_settings)

        res = client.get("/api/settings", headers={"X-Hub-Token": "secret_token_123"})
        assert res.status_code == 200
        data = res.json()
        assert "network_security" in data
        assert data["network_security"]["is_external_bind"] is True
        assert "открытого HTTP" in data["network_security"]["warning"]


# ═══════════════════════════════════════════════════════════════
#  P0-4: Forensic Audit Logging & Secret Scrubbing Tests
# ═══════════════════════════════════════════════════════════════


class TestForensicAuditAndSecretScrubbing:
    """Tests for secret scrubbing and forensic traceability."""

    def test_secret_scrubbing_removes_tokens_and_bearer_headers(self):
        dirty = {
            "user_prompt": "Please summarize this commit",
            "auth_header": "Bearer sk-proj-1234567890abcdef123456",
            "api_key": "secret_api_key_value",
            "nested": {
                "token": "ghp_12345678901234567890",
                "safe_field": "visible value",
            },
        }

        clean = scrub_secrets(dirty)
        assert clean["api_key"] == "***"
        assert clean["nested"]["token"] == "***"
        assert clean["nested"]["safe_field"] == "visible value"
        assert "sk-proj" not in clean["auth_header"]

    def test_string_scrubber_masks_inline_secrets(self):
        msg = "Request failed with error: Bearer ghp_abcdef1234567890 on host https://api.openai.com?access_token=sk-9876543210"
        scrubbed = scrub_string(msg)
        assert "ghp_abcdef" not in scrubbed
        assert "sk-987654" not in scrubbed
        assert "Bearer ***" in scrubbed
        assert "access_token=***" in scrubbed

    def test_audit_log_captures_actor_and_outcome(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HERMES_HOME", str(tmp_path))
        EventLogService._instance = None
        svc = EventLogService.get()

        svc.log(
            category="account",
            message="Удаление профиля grok-worker-1",
            actor="reviewer:manual",
            action="delete_credentials",
            target_profile="grok-worker-1",
            target_role="code-reviewer",
            outcome="success",
            level="warning",
        )

        events = svc.get_events(limit=5)
        assert len(events) >= 1
        ev = events[0]
        assert ev.actor == "reviewer:manual"
        assert ev.action == "delete_credentials"
        assert ev.target_profile == "grok-worker-1"
        assert ev.target_role == "code-reviewer"
        assert ev.outcome == "success"


# ═══════════════════════════════════════════════════════════════
#  P0-5: Live Deletion Confirmation & Safe Operations Tests
# ═══════════════════════════════════════════════════════════════


class TestCredentialsDeletionGuard:
    """Tests for explicit credential deletion confirmation and dry-run."""

    def test_delete_credentials_dry_run(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HERMES_HOME", str(tmp_path))
        from antigravity_provider.router.profile_manager import get_profile_auth_path

        auth_p = get_profile_auth_path("grok", "grok-worker-1")
        auth_p.parent.mkdir(parents=True, exist_ok=True)
        auth_p.write_text("{\"key\": \"val\"}", encoding="utf-8")

        res = ActionExecutor.execute(
            action="delete_credentials",
            data={"provider": "grok", "profile_id": "grok-worker-1", "dry_run": True},
            actor="reviewer:manual",
        )

        assert res["ok"] is True
        assert res.get("dry_run") is True
        assert auth_p.is_file()  # File MUST NOT be deleted during dry-run

    def test_delete_credentials_unconfirmed_request(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HERMES_HOME", str(tmp_path))
        from antigravity_provider.router.profile_manager import get_profile_auth_path

        auth_p = get_profile_auth_path("grok", "grok-worker-1")
        auth_p.parent.mkdir(parents=True, exist_ok=True)
        auth_p.write_text("{\"key\": \"val\"}", encoding="utf-8")

        res = ActionExecutor.execute(
            action="delete_credentials",
            data={"provider": "grok", "profile_id": "grok-worker-1", "confirmed": False},
            actor="agent:developer-1",
        )

        assert res["ok"] is False
        assert res.get("confirmation_required") is True
        assert auth_p.is_file()  # File MUST NOT be deleted without confirmation

    def test_delete_credentials_confirmed_success(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HERMES_HOME", str(tmp_path))
        from antigravity_provider.router.profile_manager import get_profile_auth_path

        auth_p = get_profile_auth_path("grok", "grok-worker-1")
        auth_p.parent.mkdir(parents=True, exist_ok=True)
        auth_p.write_text("{\"key\": \"val\"}", encoding="utf-8")

        res = ActionExecutor.execute(
            action="delete_credentials",
            data={"provider": "grok", "profile_id": "grok-worker-1", "confirmed": True},
            actor="user:web",
        )

        assert res["ok"] is True
        assert not auth_p.is_file()


@pytest.fixture
def client():
    return TestClient(app)

def test_destructive_command_with_tilde_is_rejected(monkeypatch, tmp_path):
    """Команда с тильдой не должна обходить защиту каталогов учётных данных.

    validate_command не раскрывал "~" и "$HOME" перед проверкой. Путь
    "~/.hermes/agy_profiles" не считался абсолютным, склеивался с каталогом
    проекта в путь с буквальным "~" внутри и признавался допустимым.

    Измерено на реализации: "rm -rf ~/.hermes/agy_profiles" проходило, а та же
    команда с абсолютным путём отклонялась. То есть самый естественный способ
    написать опасную команду обходил защиту ровно в том месте, ради которого
    она и делалась.
    """
    from antigravity_provider.router.security_guard import WorkspaceBoundaryGuard

    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))
    guard = WorkspaceBoundaryGuard()

    must_reject = [
        "rm -rf ~/.hermes/agy_profiles",
        "rm -rf ~/.ssh",
        "rm -rf $HOME/.hermes",
    ]
    for cmd in must_reject:
        allowed, reason, _alt = guard.validate_command(cmd)
        assert not allowed, f"команда с тильдой прошла мимо защиты: {cmd} ({reason})"

    # Обычная работа внутри проекта не должна страдать.
    allowed, _reason, _alt = guard.validate_command("rm src/temp_file.py")
    assert allowed, "защита мешает штатной работе внутри проекта"
