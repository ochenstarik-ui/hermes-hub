"""A54: real loopback HTTP, no owner credentials, no inference-service load."""
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import pytest

from antigravity_provider.router.account_probe_service import AccountProbeService
from antigravity_provider.router.action_handler import ActionExecutor, do_delete_credentials
from antigravity_provider.router.auto_assigner import AutoAssigner
from antigravity_provider.router.connection_preflight import validate_connection
from antigravity_provider.router.model_discovery_service import ModelDiscoveryService
from antigravity_provider.router.profile_manager import ProfileAuthManager, get_profile_auth_path
from antigravity_provider.router.router_config import RouterConfig, load_router_config, save_router_config


@pytest.fixture
def services(tmp_path, monkeypatch):
    save_router_config(RouterConfig())
    probe = AccountProbeService()
    discovery = ModelDiscoveryService(tmp_path / 'models.json')
    monkeypatch.setattr(AccountProbeService, '_instance', probe)
    monkeypatch.setattr(ModelDiscoveryService, '_instance', discovery)
    monkeypatch.setattr('antigravity_provider.router.action_handler._rescan_after_auth', lambda *a: None)
    yield probe, discovery
    probe.shutdown()


@pytest.fixture
def http_provider():
    calls = []
    class Provider(BaseHTTPRequestHandler):
        def do_GET(self):
            calls.append(self.path)
            invalid = self.headers.get('Authorization') == 'Bearer bad' and self.path.endswith('/key')
            body = {'error': {'message': 'Invalid key'}} if invalid else ({'models': []} if self.path.endswith('/api/tags') else {'data': [{'id': 'fixture-chat'}]})
            self.send_response(401 if invalid else 200)
            self.end_headers()
            self.wfile.write(json.dumps(body).encode())

        def do_POST(self):
            calls.append(self.path)
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            assert body['max_tokens'] == 1
            valid = self.headers.get('Authorization') == 'Bearer fixture-valid'
            self.send_response(200 if valid else 401)
            self.end_headers()
            self.wfile.write(json.dumps({'choices': [{'message': {'content': 'ok'}}]} if valid else {'error': {'message': 'Invalid key'}}).encode())

        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Provider)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f'http://127.0.0.1:{server.server_port}/v1', calls
    server.shutdown()
    server.server_close()
    thread.join()


def test_manual_check_works_when_periodic_disabled(services, monkeypatch):
    probe, discovery = services
    calls = []
    monkeypatch.setattr(discovery, 'discover_models_sync', lambda *a, **kw: ['fixture'])
    def invoke(*a, **kw):
        calls.append(kw)
        return {'success': True, 'response': 'Provider answered'}
    monkeypatch.setattr('antigravity_provider.router.action_handler.do_test_profile', invoke)
    assert probe.enabled is False
    result = probe.check_now('local', 'local-1')
    assert result['ok'] and result['message'] == 'Provider answered'
    assert len(calls) == 1 and calls[0]['discovered_models'] == ['fixture']


def test_models_only_empty_is_success_without_inference(services, http_provider, monkeypatch):
    probe, _ = services
    url, calls = http_provider
    AutoAssigner.ensure_profile_definition('ollama', 'ollama-1')
    ProfileAuthManager.save_profile_auth('ollama', 'ollama-1', {'base_url': url})
    monkeypatch.setattr('antigravity_provider.router.action_handler.do_test_profile', lambda *a, **kw: pytest.fail('catalog called inference'))
    result = probe.check_now('ollama', 'ollama-1', models_only=True)
    assert result['ok'] and result['data']['models'] == []
    assert calls == ['/api/tags']


@pytest.mark.parametrize('provider', ['openrouter', 'nvidia'])
def test_invalid_key_never_creates_profile(services, http_provider, provider):
    url, _ = http_provider
    result = ActionExecutor.execute('add_account', {'provider': provider, 'token': 'bad', 'base_url': url})
    assert not result['ok'] and '401' in result['message']
    assert not load_router_config().profiles
    assert not get_profile_auth_path(provider, provider + '-1').exists()


@pytest.mark.parametrize('provider', ['openrouter', 'nvidia', 'local', 'ollama'])
def test_valid_preflight_returns_catalog(services, http_provider, provider):
    url, calls = http_provider
    result = validate_connection(provider, 'fixture-valid', url)
    assert result['ok'] and result['message']
    assert result['data']['models'] == ([] if provider == 'ollama' else ['fixture-chat'])
    assert ('/v1/chat/completions' in calls) == (provider == 'nvidia')


@pytest.mark.parametrize('url', ['bad-url', 'http://user:pass@localhost/v1', 'http://localhost/v1?key=abc', 'file:///tmp/models'])
def test_preflight_rejects_invalid_urls(url):
    result = validate_connection('local', '', url)
    assert not result['ok'] and result['message']


def test_empty_exception_is_visible(services, monkeypatch):
    probe, discovery = services
    def fail(*a, **kw):
        raise RuntimeError()
    monkeypatch.setattr(discovery, 'discover_models_sync', fail)
    result = probe.check_now('local', 'local-1')
    assert not result['ok'] and result['message'] == 'RuntimeError'


def test_periodic_failure_visible_and_retry(services, monkeypatch):
    probe, _ = services
    probe.enabled = True
    monkeypatch.setattr(probe, 'schedule_all', lambda **kw: (_ for _ in ()).throw(ValueError('sweep failed')))
    assert probe.tick(1) == 0 and probe.status()['error'] == 'sweep failed'
    monkeypatch.setattr(probe, 'schedule_all', lambda **kw: 3)
    assert probe.tick(2) == 3
    assert probe.status()['last_tick'] and probe.status()['error'] is None


def test_manual_background_do_not_overlap(services, monkeypatch):
    probe, discovery = services
    probe.enabled = True
    entered, release = threading.Event(), threading.Event()
    concurrent, maximum = 0, 0
    def discover(*a, **kw):
        nonlocal concurrent, maximum
        concurrent += 1
        maximum = max(maximum, concurrent)
        entered.set()
        assert release.wait(3)
        concurrent -= 1
        return ['fixture']
    monkeypatch.setattr(discovery, 'discover_models_sync', discover)
    monkeypatch.setattr('antigravity_provider.router.action_handler.do_test_profile', lambda *a, **kw: {'success': True, 'response': 'ok'})
    assert probe.schedule('local', 'local-1')
    assert entered.wait(2)
    result = []
    manual = threading.Thread(target=lambda: result.append(probe.check_now('local', 'local-1')))
    manual.start()
    assert not probe.schedule('local', 'local-1', force=True)
    release.set()
    manual.join(3)
    assert result[0]['ok'] and maximum == 1


def test_delete_fast_and_bulk_protects_antigravity(services, monkeypatch):
    from antigravity_provider.router.state_store import HubStateStore
    removed = []
    monkeypatch.setattr(HubStateStore, 'get', lambda: SimpleNamespace(apply_delta_account_removed=lambda *a: removed.append(a)))
    for provider, pid in [('antigravity', 'ag-w1'), ('nvidia', 'nvidia-1'), ('local', 'local-1')]:
        AutoAssigner.ensure_profile_definition(provider, pid)
        path = get_profile_auth_path(provider, pid)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"fixture":true}')
    protected = get_profile_auth_path('antigravity', 'ag-w1')
    before = protected.read_bytes()
    started = time.monotonic()
    assert do_delete_credentials('local', 'local-1')[0]
    assert time.monotonic() - started < 0.5
    preview = ActionExecutor.execute('clear_accounts', {})
    assert 'ag-w1' in preview['data']['protected']
    assert protected.read_bytes() == before
    result = ActionExecutor.execute('clear_accounts', {'confirmed': True, 'targets': preview['data']['targets']})
    assert result['ok'] and protected.read_bytes() == before
    assert not get_profile_auth_path('nvidia', 'nvidia-1').exists()
    assert len(removed) == 2


def test_bulk_stale_preview_rejected(services):
    result = ActionExecutor.execute('clear_accounts', {'confirmed': True, 'targets': [{'profile_id': 'forged'}]})
    assert not result['ok'] and 'изменился' in result['message']


def test_antigravity_explicit_catalog_ignores_global_cache(monkeypatch):
    from antigravity_provider import agy_subprocess as agy
    monkeypatch.setattr(agy, '_AGY_MODEL_CACHE', {'old': 'old'})
    monkeypatch.setattr(agy, 'get_agy_exe', lambda: 'fixture-agy')
    monkeypatch.setattr(agy.subprocess, 'run', lambda *a, **kw: SimpleNamespace(returncode=0, stdout='\n'.join(f'gemini-{i}\tfixture' for i in range(14))))
    assert len(agy.discover_models('ag-w1')) == 14


def test_valid_add_remembers_check_and_selected_model(services, http_provider):
    probe, discovery = services
    url, _ = http_provider
    result = ActionExecutor.execute('add_account', {'provider': 'openrouter', 'token': 'fixture-valid', 'base_url': url, 'preferred_model': 'fixture-chat'})
    assert result['ok']
    pid = result['data']['profile_id']
    assert probe.state(pid)['state'] == 'working'
    assert discovery.get_models_with_metadata('openrouter', pid)['models'] == ['fixture-chat']
    assert load_router_config().get_profile(pid).preferred_models[0] == 'fixture-chat'


def test_timeout_keeps_inference_reserved(services, monkeypatch):
    from antigravity_provider.router.action_handler import do_test_profile
    AutoAssigner.ensure_profile_definition('local', 'local-1')
    ProfileAuthManager.save_profile_auth('local', 'local-1', {'base_url': 'http://127.0.0.1:1/v1'})
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    calls = []
    def invoke(*a, **kw):
        calls.append(1)
        entered.set()
        try:
            assert release.wait(2)
            return {}
        finally:
            finished.set()
    monkeypatch.setattr('antigravity_provider.router.action_handler.get_adapter', lambda p: SimpleNamespace(invoke=invoke))
    try:
        first = do_test_profile('local', 'local-1', timeout=0.02, discovered_models=['fixture'])
        assert entered.is_set() and not first['success']
        second = do_test_profile('local', 'local-1', timeout=0.02, discovered_models=['fixture'])
        assert not second['success'] and 'ещё не завершился' in second['error']
        assert calls == [1]
    finally:
        release.set()
        assert finished.wait(2)


def test_bulk_protects_symlink_into_ag(services, tmp_path):
    AutoAssigner.ensure_profile_definition('local', 'local-1')
    target = get_profile_auth_path('antigravity', 'ag-w1')
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text('protected fixture')
    link = get_profile_auth_path('local', 'local-1')
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(target)
    preview = ActionExecutor.execute('clear_accounts', {})
    assert 'local-1' in preview['data']['protected']
    assert preview['data']['targets'] == []
    assert ActionExecutor.execute('clear_accounts', {'confirmed': True, 'targets': []})['ok']
    assert target.read_text() == 'protected fixture'
