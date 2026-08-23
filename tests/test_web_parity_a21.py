"""
Hermes Hub — Task A21 Web Parity Test Suite
Verifies endpoints /api/events, /api/settings, security, and full 9-view parity.
"""

from __future__ import annotations

import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from antigravity_provider.router.web.server import app, sanitize_snapshot
from antigravity_provider.router.unified_health import EventLogService
from antigravity_provider import paths

REPO_ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = REPO_ROOT / "src" / "antigravity_provider" / "router" / "web" / "static"


@pytest.fixture
def client():
    return TestClient(app)


def test_api_events_endpoint_and_security(client):
    """Verify GET /api/events returns reverse-chronological sanitized events list."""
    event_svc = EventLogService.get()
    event_svc.log("system", "Test event 1 — normal log", level="info")
    event_svc.log("account", "Test event 2 with bearer token access_token=secret_12345", level="warning")
    event_svc.log("quota", "Test event 3 — quota exhausted", level="error")

    res = client.get("/api/events?limit=10")
    assert res.status_code == 200
    data = res.json()
    assert "events" in data
    events = data["events"]
    assert len(events) >= 3

    # Check reverse chronological order (latest event first)
    assert events[0]["message"] == "Test event 3 — quota exhausted"
    assert events[0]["level"] == "error"
    assert events[0]["category"] == "quota"

    # Verify secret sanitization on event payload
    raw_str = json.dumps(data)
    assert "secret_12345" not in raw_str


def test_api_events_category_filter(client):
    """Verify category filtering in GET /api/events."""
    event_svc = EventLogService.get()
    event_svc.log("routing", "Route failover test event", level="info")

    res = client.get("/api/events?category=routing&limit=50")
    assert res.status_code == 200
    data = res.json()
    assert "events" in data
    for ev in data["events"]:
        assert ev["category"] == "routing"


def test_api_settings_endpoint_no_raw_tokens(client, tmp_path, monkeypatch):
    """Verify GET /api/settings never exposes raw web_api_token, returns paths and boolean configured flag."""
    settings_file = paths.get_hermes_home() / "hub_settings.json"
    orig_content = settings_file.read_text(encoding="utf-8") if settings_file.exists() else "{}"

    try:
        # Write test settings with a secret token
        settings_file.write_text(json.dumps({
            "web_api_host": "127.0.0.1",
            "web_api_port": 5800,
            "web_api_token": "super_secret_hub_token_xyz",
            "theme": "dark",
            "quota_refresh_interval_sec": 120
        }), encoding="utf-8")

        res = client.get("/api/settings")
        assert res.status_code == 200
        data = res.json()

        # Token must NEVER be exposed
        assert "web_api_token" not in data
        assert "super_secret_hub_token_xyz" not in json.dumps(data)

        # Configured flag must be true
        assert data.get("web_api_token_configured") is True
        assert data.get("web_api_host") == "127.0.0.1"
        assert data.get("web_api_port") == 5800
        assert data.get("theme") == "dark"
        assert data.get("quota_refresh_interval_sec") == 120
        assert "hermes_home" in data
        assert "config_dir" in data
        assert "log_file" in data
    finally:
        if orig_content != "{}":
            settings_file.write_text(orig_content, encoding="utf-8")
        elif settings_file.exists():
            settings_file.unlink()


def test_web_client_html_and_js_9_views_parity():
    """Verify index.html and app.js implement all 9 views required for desktop parity."""
    index_html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    app_js = (STATIC_DIR / "app.js").read_text(encoding="utf-8")

    expected_views = [
        "accounts", "overview", "routing", "providers",
        "team", "analytics", "health", "logs", "settings"
    ]

    for v in expected_views:
        # Nav item exists
        assert f'data-view="{v}"' in index_html, f"Missing nav button for view: {v}"
        # Section container exists
        assert f'id="view-{v}"' in index_html, f"Missing section #view-{v} in index.html"

    # Analytics view elements
    assert "analytics-total-calls" in index_html
    assert "analytics-error-rate" in index_html
    assert "analytics-latency-p50" in index_html
    assert "analytics-tokens-total" in index_html
    assert "renderAnalyticsView" in app_js

    # Health view elements
    assert "health-readiness-banner" in index_html
    assert "health-host-resources" in index_html
    assert "health-warnings-list" in index_html
    assert "renderHealthView" in app_js

    # Logs view elements
    assert "logs-filter-level" in index_html
    assert "logs-filter-category" in index_html
    assert "logs-search" in index_html
    assert "renderLogsView" in app_js

    # Settings view elements
    assert "setting-server-host" in index_html
    assert "setting-server-port" in index_html
    assert "setting-theme" in index_html
    assert "renderSettingsView" in app_js
    assert "saveHubServerSettings" in app_js
