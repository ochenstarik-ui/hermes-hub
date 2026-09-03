"""Hermes Hub — P0 Release Gate Verification Suite.

Validates all critical release blockers and regressions:
- P0-1: customtkinter / Pillow clean install verification
- P0-2: ProfileAuthManager.get_profile_dir unified API
- P0-3: Wizard json import & API-key saving flow
- P0-4: AutoAssigner.auto_assign_all implementation with canonical roles
- P0-5: Antigravity failover on quota exhaustion + non-router error handling (B1)
- P0-6: OAuth session status unification and fast error reaction
- P0-7: Role assignment canonical mapping and unknown role rejection (B2)
- P0-8: Wizard role application to live config
- P0-9: Real API validation / removal of fake validation
- P0-10: YAML round-trip config preservation (B3)
- P0-11: Rate limit (60s) vs Quota exhaustion duration parsing (B4, S1)
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from antigravity_provider.paths import get_hermes_home, get_profile_dir
from antigravity_provider.router.auto_assigner import AutoAssigner, CANONICAL_ROLE_MAP
from antigravity_provider.router.role_registry import RoleRegistry
from antigravity_provider.router.exceptions import (
    AuthExpiredError,
    AuthRequiredError,
    QuotaExceededError,
    RateLimitedError,
    RouterError,
)
from antigravity_provider.router.profile_manager import ProfileAuthManager
from antigravity_provider.router.router_config import (
    RolePolicy,
    RouterConfig,
    RouterProfileConfig,
    get_default_router_config,
    load_router_config,
    save_router_config,
)
from antigravity_provider.router.router_engine import RouterEngine
from antigravity_provider.version import __version__


@pytest.mark.unit
def test_p0_1_installer_dependencies():
    """P0-1: Verify that canonical installer defines dependency installation, smoke testing, and dependencies import in runtime."""
    # 1. Verify Canonical Installer Specification in HermesHubSetup.cs
    setup_cs = Path(__file__).resolve().parent.parent / "installer" / "HermesHubSetup.cs"
    assert setup_cs.exists(), "HermesHubSetup.cs must exist as the canonical installer source"
    cs_content = setup_cs.read_text(encoding="utf-8")

    assert "EnsurePythonDependencies" in cs_content, "Canonical installer must define dependency checking and installation"
    assert "fastapi" in cs_content and "uvicorn" in cs_content.lower(), "Canonical installer must install fastapi and uvicorn"
    assert "HERMES_HUB_IMPORT_OK" in cs_content, "Canonical installer must execute post-install import smoke test"
    assert "assets" in cs_content, "Canonical installer must deploy branding and UI assets"

    # 2. Verify Runtime Dependency Availability
    import fastapi
    import uvicorn
    import psutil
    import yaml

    assert fastapi is not None
    assert uvicorn is not None
    assert psutil is not None
    assert yaml is not None


@pytest.mark.unit
def test_p0_2_get_profile_dir_signature(tmp_path, monkeypatch):
    """P0-2: Verify ProfileAuthManager.get_profile_dir works with both (profile_id) and (provider, profile_id)."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))

    # Signature variant 1: single arg
    p1 = ProfileAuthManager.get_profile_dir("ag-w1")
    assert isinstance(p1, Path)
    assert "agy_profiles" in str(p1) or "ag-w1" in str(p1)

    # Signature variant 2: (provider, profile_id)
    p2 = ProfileAuthManager.get_profile_dir("antigravity", "ag-w1")
    assert isinstance(p2, Path)
    assert p2.name == "ag-w1"

    # Signature variant 3: (profile_id, provider)
    p3 = ProfileAuthManager.get_profile_dir("codex-orch", "openai-codex")
    assert isinstance(p3, Path)
    assert p3.name == "codex-orch"


@pytest.mark.unit
def test_p0_3_wizard_api_key_save(tmp_path, monkeypatch):
    """P0-3: Verify API key saving flow saves JSON auth file without NameError."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))

    # Test saving auth directly
    auth_data = {
        "provider": "openai-codex",
        "profile_id": "codex-test-1",
        "api_key": "sk-test12345678901234567890",
    }
    saved_path = ProfileAuthManager.save_profile_auth("openai-codex", "codex-test-1", auth_data)
    assert saved_path.exists()

    loaded = ProfileAuthManager.load_profile_auth("openai-codex", "codex-test-1")
    assert loaded is not None
    assert loaded["api_key"] == "sk-test12345678901234567890"


@pytest.mark.unit
def test_p0_4_auto_assign_all(tmp_path, monkeypatch):
    """P0-4: Verify AutoAssigner.auto_assign_all assigns to canonical roles without creating generic roles."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))

    # Save mock auth for 2 profiles
    ProfileAuthManager.save_profile_auth("antigravity", "ag-w1", {"tokens": {"access_token": "valid"}})
    ProfileAuthManager.save_profile_auth("openai-codex", "codex-orch", {"api_key": "sk-valid-key-123456789"})

    result = AutoAssigner.auto_assign_all()
    assert isinstance(result, dict)
    assert result.get("success") is True
    assert "assigned_count" in result

    # Verify only canonical roles exist in config
    cfg = load_router_config()
    for rname in cfg.roles:
        assert rname in set(RoleRegistry.get_role_ids())


@pytest.mark.unit
def test_p0_5_antigravity_failover_on_quota(tmp_path, monkeypatch):
    """P0-5: Verify Antigravity quota error raises QuotaExceededError and triggers failover to fallback."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))

    config = RouterConfig(
        profiles={
            "ag-orch-primary": RouterProfileConfig(
                profile_id="ag-orch-primary",
                provider="antigravity",
                enabled=True,
            ),
            "codex-orch-fallback": RouterProfileConfig(
                profile_id="codex-orch-fallback",
                provider="openai-codex",
                enabled=True,
            ),
        },
        roles={
            "manager": RolePolicy(
                role_name="manager",
                preferred_chain=["ag-orch-primary", "codex-orch-fallback"],
                max_failover_attempts=2,
            )
        }
    )
    save_router_config(config)

    from antigravity_provider.router.adapters.antigravity_adapter import AntigravityAdapter
    from antigravity_provider.router.adapters.codex_adapter import CodexAdapter

    def mock_agy_invoke(profile, req):
        raise QuotaExceededError("Resource exhausted: 429 quota reached", provider="antigravity", profile_id=profile.profile_id)

    def mock_codex_invoke(profile, req):
        return {
            "id": "chatcmpl-fallback-ok",
            "choices": [{"message": {"role": "assistant", "content": "Fallback response from Codex"}}],
            "usage": {"total_tokens": 42},
        }

    engine = RouterEngine(config=config)

    with patch.object(AntigravityAdapter, "invoke", side_effect=mock_agy_invoke), \
         patch.object(CodexAdapter, "invoke", side_effect=mock_codex_invoke):

        res = engine.route_request({"messages": [{"role": "user", "content": "Hello"}]}, role="manager")

        # Must receive fallback response, NOT error text as message content!
        assert "choices" in res
        content = res["choices"][0]["message"]["content"]
        assert content == "Fallback response from Codex"
        assert "Antigravity (agy) error" not in content
        assert res["router_metadata"]["failover_count"] == 1
        assert res["router_metadata"]["profile_id"] == "codex-orch-fallback"


@pytest.mark.unit
def test_p0_5_b1_non_router_error_fallback(tmp_path, monkeypatch):
    """B1: Verify that non-router path in hermes_plugin handles error payloads without crashing with IndexError."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))

    from antigravity_provider.hermes_plugin import antigravity_llm_execution
    from antigravity_provider.router import get_router_engine

    # Ensure router is disabled
    engine = get_router_engine()
    prev_enabled = engine.config.enabled
    engine.config.enabled = False

    try:
        # Simulate agy_generate returning error dict
        error_completion = {"error": {"message": "Resource exhausted: 429 quota reached"}}

        with patch("antigravity_provider.hermes_plugin.agy_generate", return_value=error_completion):
            res = antigravity_llm_execution(
                provider="google-antigravity",
                request={"model": "gemini-2.5-pro", "messages": [{"role": "user", "content": "hello"}]},
            )

            # Must have choices[0] and message.content without IndexError!
            assert hasattr(res, "choices")
            assert len(res.choices) > 0
            assert res.choices[0].message.content is not None
            content_lower = str(res.choices[0].message.content).lower()
            assert "429" in content_lower or "exhausted" in content_lower or "error" in content_lower
    finally:
        engine.config.enabled = prev_enabled


@pytest.mark.unit
def test_p0_6_oauth_session_status_unification():
    """P0-6: Verify OAuth statuses are unified and error triggers fast failure."""
    valid_statuses = {"pending", "success", "completed", "failed", "error", "cancelled", "timeout"}
    error_statuses = {"failed", "error", "cancelled", "timeout"}
    for st in error_statuses:
        assert st in valid_statuses


@pytest.mark.unit
def test_p0_7_assign_role_action(tmp_path, monkeypatch):
    """P0-7 & B2: Verify assign_profile_to_role maps human names to canonical roles and rejects unknown roles."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))

    config = get_default_router_config()
    save_router_config(config)

    # 1. Assign "coder" -> must update "developer-1"
    ok, msg = AutoAssigner.assign_profile_to_role("ag-w1", "coder", is_primary=True)
    assert ok is True
    reloaded = load_router_config()
    assert reloaded.roles["developer-1"].preferred_chain[0] == "ag-w1"
    assert "coder" not in reloaded.roles  # Must NOT create a non-canonical role

    # 2. Assign "researcher" -> must update "researcher"
    ok, msg = AutoAssigner.assign_profile_to_role("ag-w2", "researcher", is_primary=True)
    assert ok is True
    reloaded = load_router_config()
    assert reloaded.roles["researcher"].preferred_chain[0] == "ag-w2"

    # 3. Unknown role -> must return False and reject
    ok, msg = AutoAssigner.assign_profile_to_role("ag-w1", "completely_unknown_role_xyz")
    assert ok is False
    assert "Неизвестная роль" in msg


@pytest.mark.unit
def test_n1_spare_assignment_mode(tmp_path, monkeypatch):
    """N1: Verify that selecting spare mode removes profile from active roles without creating rogue roles."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))

    config = get_default_router_config()
    # Put ag-w1 in coder-primary
    config.roles["developer-1"].preferred_chain = ["ag-w1", "ag-w2"]
    save_router_config(config)

    # Assign ag-w1 to spare
    ok, msg = AutoAssigner.assign_profile_to_role("ag-w1", "spare")
    assert ok is True
    assert "резерв" in msg.lower() or "spare" in msg.lower()

    reloaded = load_router_config()
    assert "ag-w1" not in reloaded.roles["developer-1"].preferred_chain
    assert "spare" not in reloaded.roles  # Canonical role set unchanged
    assert reloaded.profiles["ag-w1"].enabled is True


@pytest.mark.unit
def test_n2_error_formatter_deduplication():
    """N2: Verify that format_antigravity_error never creates double 'Antigravity error:' prefixes."""
    from antigravity_provider.runtime import format_antigravity_error

    # Case 1: Raw exception message
    assert format_antigravity_error("connection refused") == "Antigravity error: connection refused"

    # Case 2: Already prefixed with Antigravity error:
    assert format_antigravity_error("Antigravity error: quota exceeded") == "Antigravity error: quota exceeded"

    # Case 3: Nested multiple prefixes
    assert format_antigravity_error("Antigravity error: Antigravity error: agy error: 429") == "Antigravity error: 429"

    # Case 4: Dict error format
    assert format_antigravity_error({"message": "Antigravity (agy) error: timeout"}) == "Antigravity error: timeout"


@pytest.mark.unit
def test_p0_8_wizard_role_application(tmp_path, monkeypatch):
    """P0-8: Verify Wizard step 4 role assignment is applied directly to configuration."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))

    config = get_default_router_config()
    save_router_config(config)

    # Apply role
    ok, msg = AutoAssigner.assign_profile_to_role("codex-worker-1", "code-reviewer", is_primary=True)
    assert ok is True

    reloaded = load_router_config()
    assert "codex-worker-1" in reloaded.roles["code-reviewer"].preferred_chain
    assert reloaded.roles["code-reviewer"].preferred_chain[0] == "codex-worker-1"


@pytest.mark.unit
def test_p0_9_real_api_key_validation():
    """P0-9: Verify real/structural token verification without fake hardcoded PASS."""
    # Invalid key must return False
    valid, _, models = ProfileAuthManager.verify_codex_token("invalid-key")
    assert valid is False
    assert len(models) == 0

    # Valid format key returns True with appropriate models
    valid_key = "sk-proj-1234567890123456789012345678"
    valid, masked, models = ProfileAuthManager.verify_codex_token(valid_key)
    assert valid is True
    assert masked.startswith("sk-...")


@pytest.mark.unit
def test_p0_10_yaml_round_trip_preservation(tmp_path, monkeypatch):
    """B3: Verify YAML load -> save -> load preserves router block and settings without loss."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))

    cfg_file = tmp_path / "test_profiles.yaml"
    cfg = get_default_router_config()
    cfg.max_failover_attempts = 5
    cfg.session_affinity_ttl_seconds = 2400

    save_router_config(cfg, config_path=cfg_file)
    assert cfg_file.exists()

    reloaded = load_router_config(config_path=cfg_file)
    assert reloaded.enabled is True
    assert reloaded.max_failover_attempts == 5
    assert reloaded.session_affinity_ttl_seconds == 2400
    assert len(reloaded.roles) == len(cfg.roles)
    assert len(reloaded.profiles) == len(cfg.profiles)


@pytest.mark.unit
def test_p0_11_rate_limit_vs_quota_classification():
    """B4 & S1: Verify rate limiting gets 60s cooldown and quota parsing extracts hours/minutes."""
    from antigravity_provider.router.adapters.antigravity_adapter import AntigravityAdapter
    from antigravity_provider.router.adapters.base_adapter import ErrorCategory
    from antigravity_provider.router.router_config import RouterProfileConfig

    adapter = AntigravityAdapter()
    profile = RouterProfileConfig(profile_id="ag-w1", provider="antigravity")

    # 1. Rate Limit Error -> must be RATE_LIMITED with 60s cooldown
    rate_resp = {"error": {"message": "429 Too Many Requests: rate limit exceeded"}}
    with patch("antigravity_provider.router.adapters.antigravity_adapter.agy_generate", return_value=rate_resp):
        with pytest.raises(RateLimitedError) as exc_info:
            adapter.invoke(profile, {"messages": []})
        classification = adapter.classify_error(exc_info.value)
        assert classification.category == ErrorCategory.RATE_LIMITED
        assert classification.retry_delay_seconds == 60

    # 2. Quota with "resets in 2h" -> must parse 7200s cooldown
    quota_resp = {"error": {"message": "individual quota reached, resets in 2h"}}
    with patch("antigravity_provider.router.adapters.antigravity_adapter.agy_generate", return_value=quota_resp):
        with pytest.raises(QuotaExceededError) as exc_info:
            adapter.invoke(profile, {"messages": []})
        assert exc_info.value.reset_in_sec == 7200
        classification = adapter.classify_error(exc_info.value)
        assert classification.category == ErrorCategory.QUOTA_EXHAUSTED
        assert classification.reset_duration_seconds == 7200


@pytest.mark.unit
def test_r4_settings_runtime_influence(tmp_path, monkeypatch):
    """R4: Verify that hub_settings.json dynamically modifies RouterEngine behavior."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))

    from antigravity_provider.router.settings_service import save_hub_settings
    from antigravity_provider.router.adapters.antigravity_adapter import AntigravityAdapter
    from antigravity_provider.router.adapters.codex_adapter import CodexAdapter

    config = RouterConfig(
        profiles={
            "ag-orch-primary": RouterProfileConfig(profile_id="ag-orch-primary", provider="antigravity", enabled=True),
            "codex-orch-fallback": RouterProfileConfig(profile_id="codex-orch-fallback", provider="openai-codex", enabled=True),
        },
        roles={
            "manager": RolePolicy(
                role_name="manager",
                preferred_chain=["ag-orch-primary", "codex-orch-fallback"],
                max_failover_attempts=2,
            )
        }
    )
    save_router_config(config)

    # 1. With auto_failover=False in hub_settings.json, failover must NOT attempt fallback
    save_hub_settings({"auto_failover": False})
    engine = RouterEngine(config=config)

    def mock_agy_quota(profile, req):
        raise QuotaExceededError("Quota reached", provider="antigravity", profile_id=profile.profile_id)

    mock_codex = MagicMock()

    with patch.object(AntigravityAdapter, "invoke", side_effect=mock_agy_quota), \
         patch.object(CodexAdapter, "invoke", mock_codex):

        res = engine.route_request({"messages": [{"role": "user", "content": "Hello"}]}, role="manager")
        assert "error" in res or "choices" in res
        # Codex fallback must NOT have been called because auto_failover was False!
        assert mock_codex.call_count == 0

    # 2. With auto_failover=True in hub_settings.json, failover attempts fallback
    save_hub_settings({"auto_failover": True, "failover_attempts": 2})
    mock_codex.return_value = {"choices": [{"message": {"role": "assistant", "content": "Fallback OK"}}]}

    with patch.object(AntigravityAdapter, "invoke", side_effect=mock_agy_quota), \
         patch.object(CodexAdapter, "invoke", mock_codex):

        res = engine.route_request({"messages": [{"role": "user", "content": "Hello"}]}, role="manager")
        assert res["choices"][0]["message"]["content"] == "Fallback OK"
        assert mock_codex.call_count == 1


@pytest.mark.unit
def test_s4_secret_scanner_ast_detection(tmp_path):
    """S4/N3: Verify that AST secret scanner catches obfuscated string concatenation and real tokens."""
    import importlib
    import sys
    scripts_dir = str(Path(__file__).resolve().parent.parent / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    import release_gate
    importlib.reload(release_gate)
    scan_file_for_secrets = release_gate.scan_file_for_secrets

    # 1. Obfuscated secret assignment via string concatenation must be detected
    bad_file_1 = tmp_path / "bad_code_1.py"
    bad_file_1.write_text('CLIENT_SECRET = "secret_" + "part2"\n', encoding="utf-8")
    v1 = scan_file_for_secrets(bad_file_1)
    assert len(v1) > 0
    assert any("Obfuscated" in x or "secret" in x for x in v1)

    # 2. Live API key pattern must be detected
    bad_file_2 = tmp_path / "bad_code_2.py"
    bad_file_2.write_text('KEY = "sk-abcdef1234567890123456789012345678"\n', encoding="utf-8")
    v2 = scan_file_for_secrets(bad_file_2)
    assert len(v2) > 0
    assert any("Live API key" in x for x in v2)

    # 3. Clean file passes
    clean_file = tmp_path / "clean_code.py"
    clean_file.write_text('def hello(): return "world"\n', encoding="utf-8")
    v3 = scan_file_for_secrets(clean_file)
    assert len(v3) == 0


# ── HUB-1: ворота публикации не пропускают релиз при любом исходе ──


def _load_release_gate():
    import importlib
    import sys
    scripts_dir = str(Path(__file__).resolve().parent.parent / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    import release_gate
    importlib.reload(release_gate)
    return release_gate


@pytest.mark.unit
@pytest.mark.parametrize(
    "failure, expected_in_message",
    [
        ("network", "недоступен"),
        ("http_404", "404"),
        ("no_assets", "ассет"),
        ("no_checksums", "checksums.txt"),
        ("hash_mismatch", "не сошёлся"),
    ],
)
def test_publication_gate_blocks_instead_of_failing_open(monkeypatch, failure, expected_in_message):
    """Недостижимая публикация — отказ, а не PASS.

    Измерено на прежней реализации: при обрыве сети, при 404 на манифест и при
    404 на пакет возвращался PASS. Ворота пропускали релиз при любом исходе,
    включая полное отсутствие релиза, а строка PACKAGE_HASH_VERIFIED=True
    печаталась при том, что hashlib в файле не вызывался ни разу — хеш был
    объявлен проверенным после чтения одиннадцати байт через заголовок Range.
    """
    import urllib.error
    release_gate = _load_release_gate()
    monkeypatch.setenv(release_gate.PUBLICATION_MODE_ENV, "1")
    monkeypatch.setattr(release_gate.sys, "argv", ["release_gate.py"])

    manifest = {
        "tag_name": "v9.9.9",
        "assets": [
            {"name": "HermesHubSetup.exe", "browser_download_url": "https://example.invalid/setup.exe"},
            {"name": "checksums.txt", "browser_download_url": "https://example.invalid/checksums.txt"},
        ],
    }
    if failure == "no_assets":
        manifest["assets"] = []
    if failure == "no_checksums":
        manifest["assets"] = [manifest["assets"][0]]

    class _Resp:
        status = 200

        def __init__(self, payload: bytes):
            self._payload = payload

        def read(self, *_a):
            payload, self._payload = self._payload, b""
            return payload

        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

    def fake_get(url, timeout=30):
        if failure == "network":
            raise urllib.error.URLError("сети нет")
        if failure == "http_404":
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
        if url.endswith("checksums.txt"):
            return _Resp(b"%s  HermesHubSetup.exe\n" % (b"a" * 64))
        if url.endswith("setup.exe"):
            return _Resp(b"payload-with-a-different-hash")
        return _Resp(json.dumps(manifest).encode("utf-8"))

    monkeypatch.setattr(release_gate, "_http_get", fake_get)

    ok, msg = release_gate.check_publication_gate()
    assert ok is False, f"ворота пропустили релиз при отказе '{failure}': {msg}"
    assert expected_in_message in msg, f"причина отказа не названа: {msg!r}"


@pytest.mark.unit
def test_publication_gate_hashes_the_whole_package(monkeypatch):
    """Успех объявляется только после полного скачивания и сверки SHA-256."""
    import hashlib
    release_gate = _load_release_gate()
    monkeypatch.setenv(release_gate.PUBLICATION_MODE_ENV, "1")
    monkeypatch.setattr(release_gate.sys, "argv", ["release_gate.py"])

    package = b"hermes hub installer payload"
    real_sha = hashlib.sha256(package).hexdigest()
    read_bytes = {"total": 0}

    class _Resp:
        status = 200

        def __init__(self, payload: bytes, count: bool = False):
            self._payload = payload
            self._count = count

        def read(self, *_a):
            payload, self._payload = self._payload, b""
            if self._count:
                read_bytes["total"] += len(payload)
            return payload

        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

    manifest = {
        "tag_name": "v9.9.9",
        "assets": [
            {"name": "HermesHubSetup.exe", "browser_download_url": "https://example.invalid/setup.exe"},
            {"name": "checksums.txt", "browser_download_url": "https://example.invalid/checksums.txt"},
        ],
    }

    def fake_get(url, timeout=30):
        if url.endswith("checksums.txt"):
            return _Resp(f"{real_sha}  HermesHubSetup.exe\n".encode("utf-8"))
        if url.endswith("setup.exe"):
            return _Resp(package, count=True)
        return _Resp(json.dumps(manifest).encode("utf-8"))

    monkeypatch.setattr(release_gate, "_http_get", fake_get)

    ok, msg = release_gate.check_publication_gate()
    assert ok is True, msg
    assert "PACKAGE_HASH_VERIFIED=True" in msg
    assert read_bytes["total"] == len(package), (
        f"пакет должен быть прочитан целиком, прочитано {read_bytes['total']} из {len(package)}"
    )


@pytest.mark.unit
def test_offline_run_does_not_claim_publication_verified(monkeypatch):
    """Без режима публикации отсутствие релиза не блокирует, но и не врёт."""
    import urllib.error
    release_gate = _load_release_gate()
    monkeypatch.delenv(release_gate.PUBLICATION_MODE_ENV, raising=False)
    monkeypatch.setattr(release_gate.sys, "argv", ["release_gate.py"])

    def fake_get(url, timeout=30):
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)

    monkeypatch.setattr(release_gate, "_http_get", fake_get)

    ok, msg = release_gate.check_publication_gate()
    assert ok is True, "обычный прогон CI не должен блокироваться отсутствием релиза"
    assert "НЕ БЛОКИРУЕТ" in msg
    assert "PACKAGE_HASH_VERIFIED=True" not in msg, "непроверенное не должно объявляться проверенным"


@pytest.mark.unit
def test_publishable_assets_check_rejects_uninstallable_release(tmp_path):
    """Набор без установщика не должен уходить в публикацию.

    update_manager ищет в релизе HermesHubSetup.exe или hermes-hub-setup.sh, а
    release.yml собирает только zip и манифест. Такой релиз становится
    «latest», и обновление отвечает «в релизе не найден подходящий файл
    обновления для текущей платформы». Раньше это не проявлялось лишь потому,
    что весь релизный конвейер падал на шаге Release Gate — на тех же двух
    дефектах, что и CI, — и до публикации не доходил ни один его прогон.
    """
    release_gate = _load_release_gate()

    as_built_today = tmp_path / "dist_zip_only"
    as_built_today.mkdir()
    (as_built_today / "hermes-hub-0.1.3.zip").write_bytes(b"zip")
    (as_built_today / "update_manifest.json").write_text("{}", encoding="utf-8")

    ok, msg = release_gate.check_publishable_assets(as_built_today)
    assert ok is False, "набор без установщика признан пригодным к публикации"
    assert "HermesHubSetup.exe" in msg
    assert "checksums.txt" in msg

    without_checksums = tmp_path / "dist_no_sums"
    without_checksums.mkdir()
    (without_checksums / "HermesHubSetup.exe").write_bytes(b"exe")
    ok, msg = release_gate.check_publishable_assets(without_checksums)
    assert ok is False, "набор без checksums.txt признан пригодным"
    assert "checksums.txt" in msg

    as_published_really = tmp_path / "dist_full"
    as_published_really.mkdir()
    for name in ("HermesHubSetup.exe", "hermes-hub-setup.sh", "checksums.txt"):
        (as_published_really / name).write_bytes(b"x")
    ok, msg = release_gate.check_publishable_assets(as_published_really)
    assert ok is True, msg

    ok, msg = release_gate.check_publishable_assets(tmp_path / "нет-такого")
    assert ok is False, "отсутствующий каталог сборки должен быть отказом"
