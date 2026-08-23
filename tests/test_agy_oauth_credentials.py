"""Tests for Antigravity OAuth full credentials preservation (P0-1),
writing .gemini/oauth_creds.json (P0-2), and Model Discovery caching (P1-4).
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest

from antigravity_provider.oauth import (
    SCOPES,
    build_auth_url,
    exchange_code_for_tokens,
    refresh_access_token,
    refresh_if_needed,
)
from antigravity_provider.router.profile_manager import ProfileAuthManager, get_profile_dir
from antigravity_provider.router.profile_oauth import ProfileOAuthSession
from antigravity_provider.router.model_discovery_service import ModelDiscoveryService


# ── TEST P0-1: Full Credential Preservation in OAuth ──


@pytest.mark.unit
def test_oauth_scopes_include_openid():
    """P0-1: SCOPES must include 'openid' so Google issues an OpenID Connect id_token."""
    assert "openid" in SCOPES
    url, verifier = build_auth_url()
    assert "openid" in url
    assert "code_challenge=" in url


@pytest.mark.unit
def test_exchange_code_returns_all_required_fields():
    """P0-1: exchange_code_for_tokens must return id_token, scope, token_type, expires_in, expires_at."""
    mock_resp = {
        "access_token": "ya29.mock_access_123",
        "refresh_token": "1//mock_refresh_456",
        "id_token": "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.mock_jwt_payload.signature",
        "scope": "openid https://www.googleapis.com/auth/userinfo.email",
        "token_type": "Bearer",
        "expires_in": 3600,
    }

    with patch("antigravity_provider.oauth._post_form_json", return_value=mock_resp):
        tokens = exchange_code_for_tokens("test_code", code_verifier="test_verifier")

    assert tokens["access_token"] == "ya29.mock_access_123"
    assert tokens["refresh_token"] == "1//mock_refresh_456"
    assert tokens["id_token"] == mock_resp["id_token"]
    assert tokens["scope"] == mock_resp["scope"]
    assert tokens["token_type"] == "Bearer"
    assert tokens["expires_in"] == 3600
    assert isinstance(tokens["expires_at"], int)


@pytest.mark.unit
def test_refresh_access_token_preserves_id_token_and_scope():
    """P0-1: refresh_access_token preserves id_token and scope from response or existing fallback."""
    # Case 1: Google returns updated id_token and scope
    mock_resp_full = {
        "access_token": "ya29.new_access_token",
        "id_token": "eyJhbGciOiJSUzI1NiJ9.new_jwt.sig",
        "scope": "openid email profile",
        "token_type": "Bearer",
        "expires_in": 3600,
    }
    with patch("antigravity_provider.oauth._post_form_json", return_value=mock_resp_full):
        res1 = refresh_access_token("1//mock_refresh")
        assert res1["access_token"] == "ya29.new_access_token"
        assert res1["id_token"] == "eyJhbGciOiJSUzI1NiJ9.new_jwt.sig"
        assert res1["scope"] == "openid email profile"

    # Case 2: Google returns only access_token and expires_in (common on refresh)
    mock_resp_minimal = {
        "access_token": "ya29.refreshed_access",
        "expires_in": 3600,
        "token_type": "Bearer",
    }
    with patch("antigravity_provider.oauth._post_form_json", return_value=mock_resp_minimal):
        res2 = refresh_access_token(
            "1//mock_refresh",
            existing_id_token="eyJhbGciOiJSUzI1NiJ9.preserved_jwt.sig",
            existing_scope="openid https://www.googleapis.com/auth/userinfo.email",
        )
        assert res2["access_token"] == "ya29.refreshed_access"
        assert res2["id_token"] == "eyJhbGciOiJSUzI1NiJ9.preserved_jwt.sig"
        assert res2["scope"] == "openid https://www.googleapis.com/auth/userinfo.email"


@pytest.mark.unit
def test_refresh_if_needed_passes_existing_id_and_scope():
    """P0-1: refresh_if_needed supplies existing id_token and scope to refresh."""
    creds = {
        "refresh_token": "1//test_refresh",
        "access_token": "ya29.old_token",
        "id_token": "eyJhbGci.existing_jwt.sig",
        "scope": "openid email",
        "expires_at": time.time() - 100,  # Expired
    }
    mock_resp = {
        "access_token": "ya29.refreshed_token",
        "expires_in": 3600,
    }
    with patch("antigravity_provider.oauth._post_form_json", return_value=mock_resp):
        updated = refresh_if_needed(creds)

    assert updated["access_token"] == "ya29.refreshed_token"
    assert updated["id_token"] == "eyJhbGci.existing_jwt.sig"
    assert updated["scope"] == "openid email"


# ── TEST P0-2: Writing .gemini/oauth_creds.json in Profile Directory ──


@pytest.mark.unit
def test_save_profile_auth_creates_oauth_creds_json_with_6_fields(tmp_path, monkeypatch):
    """P0-2: Saving an Antigravity profile creates .gemini/oauth_creds.json with exact 6 fields."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))

    profile_id = "ag-test-profile"
    auth_data = {
        "token": {
            "access_token": "ya29.a0AfH6SM...",
            "refresh_token": "1//0gK9...",
            "id_token": "eyJhbGciOiJSUzI1NiIsImtpZCI...",
            "scope": "openid https://www.googleapis.com/auth/userinfo.email",
            "token_type": "Bearer",
            "expires_at": 1786634144.0,
            "expiry": "2026-08-24T12:00:00Z",
        },
        "email": "test.user@gmail.com",
        "auth_method": "oauth",
    }

    saved_path = ProfileAuthManager.save_profile_auth("antigravity", profile_id, auth_data)
    assert saved_path.is_file()

    pdir = get_profile_dir(profile_id, "antigravity")
    oauth_creds_path = pdir / ".gemini" / "oauth_creds.json"
    assert oauth_creds_path.is_file()

    creds_content = json.loads(oauth_creds_path.read_text(encoding="utf-8"))

    # Exact 6 fields
    expected_keys = {"access_token", "refresh_token", "scope", "token_type", "id_token", "expiry_date"}
    assert set(creds_content.keys()) == expected_keys
    assert creds_content["access_token"] == "ya29.a0AfH6SM..."
    assert creds_content["refresh_token"] == "1//0gK9..."
    assert creds_content["id_token"] == "eyJhbGciOiJSUzI1NiIsImtpZCI..."
    assert creds_content["scope"] == "openid https://www.googleapis.com/auth/userinfo.email"
    assert creds_content["token_type"] == "Bearer"

    # expiry_date must be integer milliseconds > 1e12
    assert isinstance(creds_content["expiry_date"], int)
    assert creds_content["expiry_date"] > 1000000000000
    assert creds_content["expiry_date"] == int(1786634144.0 * 1000)


@pytest.mark.unit
def test_oauth_session_callback_persists_full_credentials(tmp_path, monkeypatch):
    """P0-2: Full OAuth session flow populates id_token, scope, and creates oauth_creds.json."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))

    session = ProfileOAuthSession("ag-callback-test")
    session.verifier = "test_verifier"
    session.state = "test_state"

    mock_tokens = {
        "access_token": "ya29.callback_access",
        "refresh_token": "1//callback_refresh",
        "id_token": "eyJhbGciOiJSUzI1NiJ9.test_id_token_jwt.sig",
        "scope": "openid email profile",
        "token_type": "Bearer",
        "expires_at": int(time.time()) + 3600,
    }

    with patch("antigravity_provider.router.profile_oauth.exchange_code_for_tokens", return_value=mock_tokens), \
         patch("antigravity_provider.router.profile_oauth.fetch_user_email", return_value="callback_user@gmail.com"):

        ok, msg = session.handle_callback("test_code", "test_state", source="test")
        assert ok is True

    pdir = get_profile_dir("ag-callback-test", "antigravity")
    auth_json = json.loads((pdir / "auth.json").read_text(encoding="utf-8"))
    assert auth_json["token"]["id_token"] == mock_tokens["id_token"]
    assert auth_json["token"]["scope"] == "openid email profile"

    oauth_creds = json.loads((pdir / ".gemini" / "oauth_creds.json").read_text(encoding="utf-8"))
    assert oauth_creds["id_token"] == mock_tokens["id_token"]
    assert oauth_creds["scope"] == "openid email profile"
    assert isinstance(oauth_creds["expiry_date"], int)
    assert oauth_creds["expiry_date"] > 1e12


# ── TEST P1-4: Model Discovery Caching & Resilience ──


@pytest.mark.unit
def test_model_discovery_cache_persistence(tmp_path):
    """P1-4: Models are persisted to models_cache.json and survive service re-creation."""
    cache_file = tmp_path / "models_cache.json"
    service1 = ModelDiscoveryService(cache_path=cache_file)

    # Initially empty
    assert service1.get_models("antigravity") is None
    meta = service1.get_models_with_metadata("antigravity")
    assert meta["models"] is None
    assert meta["has_cache"] is False

    # Simulate discovery
    mock_models = ["gemini-3.7-flash", "gemini-2.5-pro"]
    with service1._cache_lock:
        service1._cache["antigravity"] = {
            "models": mock_models,
            "discovered_at": time.time(),
        }
        service1._save_cache_to_disk()

    assert cache_file.is_file()

    # Re-instantiate service reading the same file
    service2 = ModelDiscoveryService(cache_path=cache_file)
    cached = service2.get_models("antigravity")
    assert cached == mock_models
    meta2 = service2.get_models_with_metadata("antigravity")
    assert meta2["has_cache"] is True
    assert meta2["is_stale"] is False


@pytest.mark.unit
def test_model_discovery_failure_preserves_existing_cache(tmp_path):
    """P1-4: Background discovery failure/timeout does NOT wipe existing cache."""
    cache_file = tmp_path / "models_cache.json"
    service = ModelDiscoveryService(cache_path=cache_file)

    initial_models = ["gemini-3.7-flash"]
    with service._cache_lock:
        service._cache["antigravity"] = {
            "models": initial_models,
            "discovered_at": time.time() - 7200,  # Stale
        }
        service._save_cache_to_disk()

    # Probe fails (returns None)
    with patch.object(service, "_probe_provider", return_value=None):
        res = service.discover_models_sync("antigravity", timeout=1.0)
        # Retains existing cache
        assert res == initial_models

    # Cache must still contain initial_models
    assert service.get_models("antigravity") == initial_models
