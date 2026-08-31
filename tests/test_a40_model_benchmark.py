"""Unit tests for A40 Model Benchmark Suite and Integrity Harnesses."""
from __future__ import annotations

import json
import sys
from pathlib import Path
import yaml
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from benchmarks.benchmark_suite import BENCHMARK_TASKS, _compile_and_get
# gguf — зависимость только стенда замеров. На машине без неё модуль
# ронял СБОР всех тестов, а не один этот файл.
pytest.importorskip("gguf", reason="gguf ставится дополнением benchmarks")

from benchmarks.run_benchmark import get_gguf_metadata


def test_benchmark_tasks_count_and_uniqueness():
    """Verify that exactly 12 diverse real-world repository tasks are registered."""
    assert len(BENCHMARK_TASKS) == 12
    task_ids = [t.task_id for t in BENCHMARK_TASKS]
    assert len(set(task_ids)) == 12


def test_reference_solutions_pass_all_12_tasks():
    """Verify each task harness against a correct reference Python implementation."""
    reference_implementations = {
        "T01_extract_model_family": """
def extract_model_family(model_name: str) -> str:
    m = str(model_name or "").lower()
    for fam in ["gemini", "claude", "gpt", "deepseek", "kimi", "qwen", "grok", "glm"]:
        if fam in m:
            return fam
    return "unknown"
""",
        "T02_verify_auth_token": """
import secrets
def verify_auth_token(given_token: str | None, required_token: str) -> bool:
    if given_token is None:
        return False
    g_bytes = str(given_token).encode('utf-8')
    r_bytes = str(required_token).encode('utf-8')
    return secrets.compare_digest(g_bytes, r_bytes)
""",
        "T03_scrub_secrets": """
import re
def scrub_secrets(data):
    if isinstance(data, dict):
        res = {}
        for k, v in data.items():
            if any(s in str(k).lower() for s in ['token', 'secret', 'api_key', 'password', 'bearer']):
                res[k] = '***'
            else:
                res[k] = scrub_secrets(v)
        return res
    elif isinstance(data, list):
        return [scrub_secrets(x) for x in data]
    elif isinstance(data, str):
        s = re.sub(r'sk-[a-zA-Z0-9_\\-]+', '***', data)
        return re.sub(r'Bearer\\s+[^\\s]+', 'Bearer ***', s)
    return data
""",
        "T04_cycle_tracker": """
class CycleTracker:
    def __init__(self):
        self.counts = {}
    def record_edge_traversal(self, edge_id: str, max_iterations: int) -> bool:
        self.counts[edge_id] = self.counts.get(edge_id, 0) + 1
        return self.counts[edge_id] <= max_iterations
""",
        "T05_validate_file_path": """
from pathlib import Path
def validate_file_path(target_path: str, allowed_root: str, forbidden_patterns: list[str]) -> tuple[bool, str]:
    t = Path(target_path).resolve()
    r = Path(allowed_root).resolve()
    for f in forbidden_patterns:
        if f.lower() in str(t).lower():
            return False, 'Forbidden path pattern'
    try:
        t.relative_to(r)
        return True, 'OK'
    except ValueError:
        return False, 'Path outside boundary'
""",
        "T06_is_destructive_command": """
import shlex
def is_destructive_command(cmd_line: str) -> tuple[bool, str, list[str]]:
    tokens = shlex.split(cmd_line)
    if not tokens:
        return False, '', []
    cmd = tokens[0].lower()
    if cmd in {'rm', 'rmdir', 'unlink', 'del', 'erase', 'remove-item', 'rd'}:
        targets = [t for t in tokens[1:] if not t.startswith('-') and not (t.startswith('/') and len(t) <= 3 and '/' not in t[1:])]
        return True, cmd, targets
    return False, cmd, []
""",
        "T07_is_outbound_allowed": """
import urllib.parse
def is_outbound_allowed(url_or_host: str, allowed_hosts: set[str]) -> bool:
    if '://' in url_or_host:
        h = (urllib.parse.urlparse(url_or_host).hostname or '').lower()
    else:
        h = url_or_host.split(':')[0].lower()
    if h in {'127.0.0.1', 'localhost'} or h in allowed_hosts:
        return True
    return any(h.endswith('.' + a) for a in allowed_hosts)
""",
        "T08_sanitize_hermes_response": """
def sanitize_hermes_response(completion: dict, fallback_message: str) -> dict:
    res = dict(completion)
    if res.get('router_error'):
        res['content'] = fallback_message
        res['router_fallback'] = True
    return res
""",
        "T09_resolve_role": """
def resolve_role(explicit_role: str | None, model: str | None, session_role: str | None, default_role: str = 'manager') -> tuple[str, str]:
    if explicit_role:
        return explicit_role, 'explicit'
    m = str(model or '').lower()
    if 'claude' in m:
        return 'code-reviewer', 'model_match'
    if 'gemini-3.1' in m:
        return 'developer-2', 'model_match'
    if 'gemini-3.7' in m:
        return 'developer-1', 'model_match'
    if session_role:
        return session_role, 'session_affinity'
    return default_role, 'default_fallback'
""",
        "T10_build_safe_env": """
def build_safe_env(base_env: dict[str, str], allowed_keys: set[str], overrides: dict[str, str]) -> dict[str, str]:
    res = {}
    for k, v in base_env.items():
        if k in allowed_keys:
            if not any(s in k.lower() for s in ['api_key', 'token', 'secret', 'password']):
                res[k] = v
    if overrides:
        res.update(overrides)
    return res
""",
        "T11_determine_profile_health": """
def determine_profile_health(is_enabled: bool, is_authenticated: bool, is_auth_expired: bool, cooldown_sec: int, is_cold_spare: bool) -> str:
    if not is_enabled:
        return 'disabled'
    if not is_authenticated:
        if is_auth_expired:
            return 'auth_expired'
        if is_cold_spare:
            return 'cold_spare'
        return 'not_configured'
    if cooldown_sec > 0:
        return 'quota_exhausted'
    return 'healthy'
""",
        "T12_long_context_lease_manager": """
import threading
import uuid
class LeaseManager:
    def __init__(self, default_max_concurrency: int = 2, default_lease_timeout: float = 30.0):
        self.default_max = default_max_concurrency
        self.timeout = default_lease_timeout
        self.leases = {}
        self.lock = threading.Lock()
    def acquire(self, profile_id: str, max_concurrency: int | None = None) -> dict:
        limit = max_concurrency if max_concurrency is not None else self.default_max
        with self.lock:
            active = self.leases.setdefault(profile_id, set())
            if len(active) < limit:
                lid = str(uuid.uuid4())
                active.add(lid)
                return {'granted': True, 'lease_id': lid, 'active_count': len(active)}
            return {'granted': False, 'active_count': len(active)}
    def release(self, profile_id: str, lease_id: str) -> bool:
        with self.lock:
            active = self.leases.get(profile_id, set())
            if lease_id in active:
                active.remove(lease_id)
                return True
            return False
""",
    }

    for task in BENCHMARK_TASKS:
        code = reference_implementations[task.task_id]
        fn, err = _compile_and_get(code, task.expected_function_name)
        assert err is None, f"Failed to compile reference solution for {task.task_id}: {err}"
        ok, msg = task.test_function(fn)
        assert ok is True, f"Reference solution failed for {task.task_id}: {msg}"


def test_gguf_metadata_extraction_non_existent():
    """Verify get_gguf_metadata returns exists=False for missing files."""
    meta = get_gguf_metadata("/tmp/non_existent_model.gguf")
    assert meta["exists"] is False
    assert "not found" in meta["error"]
