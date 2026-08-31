"""A54 isolated UI execution: real local HTTP; synthetic remote credentials only."""
import json
import os
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

os.environ['HERMES_HOME'] = tempfile.mkdtemp(prefix='a54-ui-')
os.environ['HERMES_ROUTER_CONFIG'] = os.path.join(os.environ['HERMES_HOME'], 'router_profiles.yaml')
from antigravity_provider.router.auto_assigner import AutoAssigner
from antigravity_provider.router.profile_manager import ProfileAuthManager
from antigravity_provider.router.router_config import RouterConfig, save_router_config
from antigravity_provider.router.quota_collector import AccountQuotaService
from antigravity_provider.router.model_discovery_service import ModelDiscoveryService
from antigravity_provider.router.web import server


class Fixture(BaseHTTPRequestHandler):
    def do_GET(self):
        invalid = self.path.endswith('/key') and self.headers.get('Authorization') != 'Bearer fixture-valid'
        self.send_response(401 if invalid else 200)
        self.end_headers()
        body = {'error': {'message': 'A54 fixture: invalid key'}} if invalid else ({'models': []} if self.path.endswith('/api/tags') else {'data': [{'id': 'fixture-chat'}]})
        self.wfile.write(json.dumps(body).encode())

    def do_POST(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'{"choices":[{"message":{"content":"fixture OK"}}]}')

    def log_message(self, *a):
        pass


http = ThreadingHTTPServer(('127.0.0.1', 0), Fixture)
threading.Thread(target=http.serve_forever, daemon=True).start()
print('FIXTURE_BASE_URL=http://127.0.0.1:%s/v1' % http.server_port, flush=True)
save_router_config(RouterConfig())
for provider, pid, url in [('local', 'local-1', 'http://127.0.0.1:8081/v1'), ('ollama', 'ollama-1', f'http://127.0.0.1:{http.server_port}'), ('ollama', 'ollama-2', 'http://127.0.0.1:1')]:
    AutoAssigner.ensure_profile_definition(provider, pid)
    ProfileAuthManager.save_profile_auth(provider, pid, {'base_url': url, 'email': 'A54-STAND-' + pid})
# No AG account is used: rendering its 14-model fixture does not verify real OAuth.
AutoAssigner.ensure_profile_definition('antigravity', 'ag-w1')
ProfileAuthManager.save_profile_auth('antigravity', 'ag-w1', {'auth_method': 'oauth', 'email': 'A54-SYNTHETIC-AG'})
original_probe = ModelDiscoveryService.get()._probe_provider
ModelDiscoveryService.get()._probe_provider = lambda provider: ([f'gemini-fixture-{i}' for i in range(14)], None) if provider == 'antigravity' else original_probe(provider)
from antigravity_provider.router import action_handler
original_adapter = action_handler.get_adapter
action_handler.get_adapter = lambda provider: SimpleNamespace(invoke=lambda *a: {'choices': [{'message': {'content': 'AG fixture'}}]}) if provider == 'antigravity' else original_adapter(provider)
AccountQuotaService.get().fetch_all_configured = lambda **kw: None
AccountQuotaService.get().start_background_scheduler = lambda: None
server.UpdateManager.check_for_updates = lambda self: SimpleNamespace(error=None, message='A54 стенд', update_available=False, to_dict=lambda: {})
server.run_web_server(host='127.0.0.1', port=5804)
