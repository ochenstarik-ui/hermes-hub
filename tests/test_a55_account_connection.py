"""Tests for Task A55: Account Connection Defect Fixes (P0-1 through P0-5)."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from antigravity_provider.version import __version__, VERSION_INFO
from antigravity_provider.router.action_handler import ActionExecutor
from antigravity_provider.router.profile_manager import ProfileAuthManager
from antigravity_provider.router.adapters.ollama_adapter import OllamaAdapter, DEFAULT_OLLAMA_BASE_URL
from antigravity_provider.router.connection_preflight import validate_connection
from antigravity_provider.router.model_discovery_service import ModelDiscoveryService
from antigravity_provider.router.web.server import app


# ── P0-1: Antigravity & Browser Auth Tests ──

def test_p0_1_add_account_unauthenticated_browser_auth_error_message():
    """add_account should return Russian browser auth message for antigravity and claude."""
    with patch.object(ProfileAuthManager, "get_profile_status", return_value={"authenticated": False}):
        # Antigravity without token/completed auth
        res_ag = ActionExecutor.execute("add_account", {
            "provider": "antigravity",
            "profile_id": "ag-1",
            "token": "",
        })
        assert not res_ag["ok"]
        assert "Авторизация через браузер не завершена. Пожалуйста, откройте ссылку входа или вставьте адрес возврата." in res_ag["message"]

        # Claude without token/completed auth
        res_cl = ActionExecutor.execute("add_account", {
            "provider": "claude",
            "profile_id": "claude-1",
            "token": "",
        })
        assert not res_cl["ok"]
        assert "Авторизация через браузер не завершена. Пожалуйста, откройте ссылку входа или вставьте адрес возврата." in res_cl["message"]


def test_p0_1_profile_auth_manager_get_profile_status_antigravity():
    """get_profile_status should return authenticated: False when auth_data is empty or invalid."""
    # Unauthenticated/empty auth_data
    with patch.object(ProfileAuthManager, "load_profile_auth", return_value={}):
        st = ProfileAuthManager.get_profile_status("antigravity", "ag-1")
        assert st["authenticated"] is False
        assert st["status"] == "NOT_CONFIGURED"

    # Authenticated with access_token
    with patch.object(ProfileAuthManager, "load_profile_auth", return_value={"token": {"access_token": "ya29.valid-token"}}):
        st = ProfileAuthManager.get_profile_status("antigravity", "ag-1")
        assert st["authenticated"] is True
        assert st["status"] == "AUTHENTICATED"


def test_p0_1_load_profile_auth_gemini_oauth_creds_fallback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """load_profile_auth should check .gemini/oauth_creds.json if auth.json is missing."""
    monkeypatch.setattr("antigravity_provider.paths.get_hermes_home", lambda: tmp_path)
    pdir = tmp_path / "agy_profiles" / "ag-5"
    gemini_dir = pdir / ".gemini"
    gemini_dir.mkdir(parents=True, exist_ok=True)
    creds_file = gemini_dir / "oauth_creds.json"
    creds_file.write_text(json.dumps({"access_token": "token-123", "refresh_token": "refresh-456"}), encoding="utf-8")

    auth = ProfileAuthManager.load_profile_auth("antigravity", "ag-5")
    assert auth is not None
    assert auth.get("provider") == "antigravity"
    assert auth.get("token", {}).get("access_token") == "token-123"


# ── P0-2: Ollama Base URL & Connection Error Tests ──

def test_p0_2_ollama_default_base_url():
    """DEFAULT_OLLAMA_BASE_URL must be http://127.0.0.1:11434 (without trailing /v1)."""
    assert DEFAULT_OLLAMA_BASE_URL == "http://127.0.0.1:11434"


def test_p0_2_ollama_adapter_url_builders():
    """OllamaAdapter URL methods should handle base_urls with or without /v1 cleanly."""
    adapter = OllamaAdapter()
    
    # Standard base url without /v1
    assert adapter._get_native_host("http://127.0.0.1:11434") == "http://127.0.0.1:11434"
    assert adapter._get_chat_url("http://127.0.0.1:11434") == "http://127.0.0.1:11434/v1/chat/completions"
    assert adapter._get_models_url("http://127.0.0.1:11434") == "http://127.0.0.1:11434/v1/models"

    # Base url with /v1
    assert adapter._get_native_host("http://192.168.1.81:11434/v1") == "http://192.168.1.81:11434"
    assert adapter._get_chat_url("http://192.168.1.81:11434/v1") == "http://192.168.1.81:11434/v1/chat/completions"
    assert adapter._get_models_url("http://192.168.1.81:11434/v1") == "http://192.168.1.81:11434/v1/models"

    # Base url with trailing slash
    assert adapter._get_native_host("http://192.168.1.81:11434/") == "http://192.168.1.81:11434"
    assert adapter._get_chat_url("http://192.168.1.81:11434/") == "http://192.168.1.81:11434/v1/chat/completions"


def test_p0_2_ollama_connection_refused_helpful_message():
    """Ollama connection refused error should provide network IP guidance."""
    # Test connection preflight when endpoint is down
    res = validate_connection("ollama", token="", base_url="http://127.0.0.1:11434")
    assert not res["ok"]
    assert "Не удалось подключиться к http://127.0.0.1:11434 (Connection refused)" in res["message"]
    assert "http://192.168.1.81:11434" in res["message"]


# ── P0-3: Antigravity Dynamic Model Discovery Tests ──

def test_p0_3_antigravity_dynamic_model_discovery():
    """ModelDiscoveryService probe should find and query any authenticated Antigravity profile."""
    discovery = ModelDiscoveryService.get()
    
    with patch("antigravity_provider.router.profile_manager.ProfileAuthManager.get_profile_status") as mock_st, \
         patch("antigravity_provider.agy_subprocess.discover_models", return_value={"gemini-2.5-pro": "gemini-2.5-pro"}) as mock_disc:
        
        # Simulate ag-3 being authenticated
        def status_side_effect(prov, pid):
            if pid == "ag-3":
                return {"authenticated": True, "provider": prov, "profile_id": pid}
            return {"authenticated": False, "provider": prov, "profile_id": pid}
        
        mock_st.side_effect = status_side_effect
        
        models, err = discovery._probe_provider("antigravity")
        assert err is None
        assert models == ["gemini-2.5-pro"]
        mock_disc.assert_called_with(profile_id="ag-3")


# ── P0-4: Version Info & API Propagation Tests ──

def test_p0_4_version_single_source_of_truth():
    """Номер версии и VERSION_INFO обязаны совпадать между собой.

    Сверять с записанным в тесте числом бессмысленно: при каждой сборке его
    пришлось бы править, и тест превращался бы в напоминание, а не в проверку.
    Смысл требования — единый источник, его и проверяем.
    """
    assert VERSION_INFO == tuple(int(part) for part in __version__.split("."))


def test_p0_4_version_in_api_endpoints():
    """Все точки API обязаны отдавать ту же версию, что и пакет."""
    client = TestClient(app)

    # /api/health
    res_health = client.get("/api/health")
    assert res_health.status_code == 200
    assert res_health.json().get("version") == __version__

    # /api/settings
    res_settings = client.get("/api/settings")
    assert res_settings.status_code == 200
    assert res_settings.json().get("version") == __version__

    # /api/snapshot
    res_snap = client.get("/api/snapshot")
    assert res_snap.status_code == 200
    snap = res_snap.json()
    assert snap.get("version") == __version__
    assert (snap.get("metrics") or {}).get("version") == __version__


# ── P0-5: Settings View & System Paths Tests ──

def test_p0_5_settings_api_returns_system_paths_and_hub_settings():
    """GET /api/settings must return system_paths, server host/port, token status, and hub settings."""
    client = TestClient(app)
    res = client.get("/api/settings")
    assert res.status_code == 200
    data = res.json()

    # System paths dict
    assert "system_paths" in data
    sys_paths = data["system_paths"]
    assert "hermes_home" in sys_paths
    assert "config_dir" in sys_paths
    assert "log_file" in sys_paths

    # Server settings & tokens
    assert "web_api_host" in data
    assert "web_api_port" in data
    assert "web_api_token_configured" in data

    # Snapshot includes system_paths
    res_snap = client.get("/api/snapshot")
    assert res_snap.status_code == 200
    snap = res_snap.json()
    assert "system_paths" in snap
    assert snap["system_paths"]["hermes_home"] == sys_paths["hermes_home"]
