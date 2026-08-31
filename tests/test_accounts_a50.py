"""A50 regressions: real local HTTP rejection and isolated account configuration."""
import io
import json
import threading
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from antigravity_provider.router.account_probe_service import AccountProbeService
from antigravity_provider.router.action_handler import ActionExecutor, do_test_profile
from antigravity_provider.router.auto_assigner import AutoAssigner
from antigravity_provider.router.model_discovery_service import ModelDiscoveryService
from antigravity_provider.router.router_config import RouterConfig, load_router_config, save_router_config


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    save_router_config(RouterConfig())
    service = AccountProbeService()
    monkeypatch.setattr(AccountProbeService, "_instance", service)
    discovery = ModelDiscoveryService(tmp_path / "test-model-cache.json")
    monkeypatch.setattr(ModelDiscoveryService, "_instance", discovery)
    monkeypatch.setattr("antigravity_provider.router.action_handler._rescan_after_auth", lambda: None)
    monkeypatch.setattr("antigravity_provider.router.state_store.HubStateStore.refresh", lambda *a, **kw: None)
    ActionExecutor._pending_connections.clear()
    yield service, discovery
    service._pool.shutdown(wait=True)


@pytest.mark.parametrize("provider", ["nvidia", "openrouter", "grok", "claude"])
def test_foreign_slot_rejected_before_write(isolated, provider):
    result = ActionExecutor.execute("add_account", {"provider": provider, "profile_id": "ag-w1", "token": "intentionally-invalid"})
    assert not result["ok"]
    assert "не принадлежит" in result["message"]
    assert not load_router_config().profiles


@pytest.mark.parametrize("slot", ["../ag-w1", "/tmp/slot", "nvidia-1/evil"])
def test_unsafe_slot_rejected(isolated, slot):
    assert not AutoAssigner.ensure_profile_definition("nvidia", slot)[0]


@pytest.mark.parametrize("provider", ["nvidia", "openrouter"])
def test_invalid_key_real_http_correct_slot(isolated, provider):
    class Reject(BaseHTTPRequestHandler):
        def do_POST(self):
            self.send_response(401)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": {"message": "Invalid API key (A50 fixture)"}}).encode())

        def do_GET(self):
            self.do_POST()

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Reject)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        result = ActionExecutor.execute("add_account", {
            "provider": provider, "token": "intentionally-invalid",
            "base_url": f"http://127.0.0.1:{server.server_port}/v1",
        })
        assert result["ok"]
        pid = result["data"]["profile_id"]
        assert pid.startswith(provider + "-")
        assert load_router_config().get_profile(pid).provider == provider
        probe = do_test_profile(provider, pid)
        assert not probe["success"]
        assert "401" in probe["error"] and "Invalid API key" in probe["error"]
        discovery = isolated[1]
        assert discovery.discover_models_sync(provider, profile_id=pid) is None
        assert "Invalid API key" in discovery.get_models_with_metadata(provider, pid)["error"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_parallel_probe_dedup_and_failure_state(isolated, monkeypatch):
    service, discovery = isolated
    service.enabled = True
    entered = threading.Event()
    release = threading.Event()
    def probe(*args, **kwargs):
        entered.set()
        assert release.wait(2)
        return {"success": False, "error": "HTTP 401: Invalid API key"}
    monkeypatch.setattr("antigravity_provider.router.action_handler.do_test_profile", probe)
    monkeypatch.setattr(discovery, "discover_models_sync", lambda *a, **kw: [])
    assert service.state("nvidia-1")["state"] == "never_checked"
    assert service.schedule("nvidia", "nvidia-1")
    assert entered.wait(2)
    assert service.state("nvidia-1")["state"] == "checking"
    assert not service.schedule("nvidia", "nvidia-1", force=True)
    release.set()
    service._pool.shutdown(wait=True)
    assert service.state("nvidia-1")["state"] == "failed"
    assert "401" in service.state("nvidia-1")["message"]
    assert service.state("nvidia-1")["checked_at"]


def test_model_caches_are_account_scoped(isolated, monkeypatch):
    _, service = isolated
    monkeypatch.setattr(service, "_probe_provider", lambda p: ([service._probe_context.profile_id], None))
    service.discover_models_sync("grok", profile_id="grok-1")
    service.discover_models_sync("grok", profile_id="grok-2")
    assert service.get_models_with_metadata("grok", "grok-1")["models"] == ["grok-1"]
    assert service.get_models_with_metadata("grok", "grok-2")["models"] == ["grok-2"]


def test_model_error_retains_timestamped_cache(isolated, monkeypatch):
    _, service = isolated
    monkeypatch.setattr(service, "_probe_provider", lambda p: (["known-model"], None))
    service.discover_models_sync("grok", profile_id="grok-1")
    timestamp = service.get_models_with_metadata("grok", "grok-1")["discovered_at"]
    monkeypatch.setattr(service, "_probe_provider", lambda p: (None, "HTTP 403: account refused"))
    service.discover_models_sync("grok", profile_id="grok-1")
    cached = service.get_models_with_metadata("grok", "grok-1")
    assert cached["discovered_at"] == timestamp
    assert cached["models"] == ["known-model"]
    assert "403" in cached["error"]


def test_cloud_catalog_documented_url_no_credentials(isolated, monkeypatch):
    _, service = isolated
    def urlopen(request, **kwargs):
        assert request.full_url == "https://ollama.com/api/tags"
        assert not request.has_header("Authorization")
        return io.BytesIO(b'{"models":[{"name":"test-cloud"}]}')
    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    result = service.discover_ollama_cloud()
    assert result["models"] == ["test-cloud"]
    assert result["discovered_at"]


def test_llama_cpp_label_does_not_rename_id(isolated):
    assert AutoAssigner.ensure_profile_definition("local", "local-1")[0]
    assert AutoAssigner.get_display_name_and_role("local-1")[0] == "llama.cpp 1"
    assert load_router_config().get_profile("local-1").provider == "local"


def test_periodic_checks_start_automatically_and_respect_interval(isolated, monkeypatch):
    service, _ = isolated
    service.enabled = True
    calls = []
    monkeypatch.setattr(service, "schedule_all", lambda **kw: calls.append(kw) or 1)
    assert service.tick(now=1000) == 1
    assert service.tick(now=1001) == 0
    assert service.tick(now=1299) == 0
    assert service.tick(now=1300) == 1
    assert calls == [{"force": True}, {"force": True}]


def test_http_plaintext_error_preserved(isolated):
    _, service = isolated
    error = urllib.error.HTTPError("https://example.invalid/models", 403, "Forbidden", {}, io.BytesIO(b"Account disabled by provider"))
    assert service._extract_http_error(error) == "HTTP 403: Account disabled by provider"


def test_slow_action_does_not_block_web_health(isolated, monkeypatch):
    import asyncio
    import httpx
    from antigravity_provider.router.web.server import app
    entered = threading.Event()
    release = threading.Event()
    def slow_action(*args, **kwargs):
        entered.set()
        release.wait(2)
        return {"ok": True, "message": "test fixture"}
    monkeypatch.setattr(ActionExecutor, "execute", slow_action)
    async def exercise():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            pending = asyncio.create_task(client.post("/api/action", json={"action": "add_account"}))
            try:
                assert await asyncio.to_thread(entered.wait, 1)
                response = await client.get("/api/health")
                assert response.status_code == 200
                assert not pending.done(), "A slow account action blocked the event loop"
            finally:
                release.set()
                await pending
    asyncio.run(exercise())


def test_repeated_connection_rejected_while_checking(isolated, monkeypatch):
    service, _ = isolated
    service.enabled = True
    monkeypatch.setattr(service._pool, "submit", lambda *args: None)
    payload = {"provider": "nvidia", "token": "intentionally-invalid-repeated"}
    first = ActionExecutor.execute("add_account", payload)
    second = ActionExecutor.execute("add_account", payload)
    assert first["ok"] and first["data"]["profile_id"] == "nvidia-1"
    assert not second["ok"] and "проверяется" in second["message"]
    assert list(load_router_config().profiles) == ["nvidia-1"]
