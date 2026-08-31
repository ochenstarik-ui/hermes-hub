"""Isolated UI preview with synthetic accounts and a loopback HTTP provider.

Run with PYTHONPATH=src python tests/manual/a50_preview.py. No owner data used.
"""
import json
import os
import tempfile
import threading
import time
from types import SimpleNamespace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

os.environ["HERMES_HOME"] = tempfile.mkdtemp(prefix="a50-ui-test-")

from antigravity_provider.router.auto_assigner import AutoAssigner
from antigravity_provider.router.profile_manager import ProfileAuthManager
from antigravity_provider.router.router_config import RouterConfig, save_router_config
from antigravity_provider.router.quota_collector import AccountQuotaService
from antigravity_provider.router.web import server


class FixtureProvider(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'{"data":[{"id":"qwen3:fixture"}]}')

    def do_POST(self):
        time.sleep(20)
        healthy = "/working/" in self.path
        self.send_response(200 if healthy else 401)
        self.end_headers()
        data = {"choices": [{"message": {"content": "fixture OK"}}]} if healthy else {"error": {"message": "Invalid API key — A50 test fixture"}}
        self.wfile.write(json.dumps(data).encode())

    def log_message(self, *args):
        pass


http = ThreadingHTTPServer(("127.0.0.1", 5813), FixtureProvider)
threading.Thread(target=http.serve_forever, daemon=True).start()
save_router_config(RouterConfig())
for provider, pid, mode in [("nvidia", "nvidia-1", "failed"), ("nvidia", "nvidia-2", "working"), ("openrouter", "openrouter-1", "failed"), ("local", "local-1", "working")]:
    AutoAssigner.ensure_profile_definition(provider, pid)
    ProfileAuthManager.save_profile_auth(provider, pid, {"api_key": "intentionally-invalid-a50-fixture", "base_url": f"http://127.0.0.1:5813/{mode}/v1", "email": f"A50-TEST-{pid}"})
# No quota/OAuth/update network in this isolated UI fixture.
AccountQuotaService.get().fetch_all_configured = lambda **kw: None
AccountQuotaService.get().start_background_scheduler = lambda: None
server.UpdateManager.check_for_updates = lambda self: SimpleNamespace(error=None, message="Обновления отключены на тестовом стенде A50", update_available=False, to_dict=lambda: {})
server.run_web_server(host="127.0.0.1", port=5803)
