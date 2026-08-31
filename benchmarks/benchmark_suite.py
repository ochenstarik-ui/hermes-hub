"""Automated Evaluation Suite for Local LLM Benchmarking on Hermes Hub Codebase Tasks."""
from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple


@dataclass
class BenchmarkTask:
    task_id: str
    title: str
    category: str
    prompt: str
    expected_function_name: str
    test_function: Callable[[Any], Tuple[bool, str]]
    is_long_context: bool = False
    context_data: Optional[str] = None


def _clean_code(text: str) -> str:
    """Extract python code from model output, stripping markdown, thoughts, and conversational fluff."""
    if not text:
        return ""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    code_block = re.search(r"```(?:python|py)?\s*(.*?)\s*```", text, re.DOTALL)
    if code_block:
        return code_block.group(1).strip()
    return text.strip()


def _compile_and_get(code_str: str, target_symbol: str) -> Tuple[Optional[Any], Optional[str]]:
    """Compile Python code and retrieve the target symbol in a clean namespace."""
    clean = _clean_code(code_str)
    try:
        ast.parse(clean)
    except SyntaxError as e:
        return None, f"SyntaxError: {e}"

    namespace: Dict[str, Any] = {}
    try:
        exec(clean, namespace)
    except Exception as e:
        return None, f"RuntimeError on load: {type(e).__name__}: {e}"

    if target_symbol not in namespace:
        return None, f"Symbol '{target_symbol}' not found in generated code"

    return namespace[target_symbol], None


# Task 1
def test_t1(fn) -> Tuple[bool, str]:
    cases = [
        ("gemini-3.7-flash", "gemini"),
        ("claude-opus-4-6-thinking", "claude"),
        ("gpt-4o-mini", "gpt"),
        ("deepseek-v4-pro", "deepseek"),
        ("kimi-k2.7-code", "kimi"),
        ("qwen3.8-max", "qwen"),
        ("grok-4.5", "grok"),
        ("glm-5.3", "glm"),
    ]
    for model_name, expected in cases:
        try:
            res = fn(model_name)
            if res != expected:
                return False, f"extract_model_family('{model_name}') = '{res}', expected '{expected}'"
        except Exception as exc:
            return False, f"Exception on '{model_name}': {exc}"
    return True, "All 8 model families correctly extracted"


# Task 2
def test_t2(fn) -> Tuple[bool, str]:
    try:
        if not fn("secret123", "secret123"):
            return False, "Failed on exact match"
        if fn("secret123", "wrong"):
            return False, "Failed on mismatch (returned True)"
        if fn(None, "secret123"):
            return False, "Failed on None given token"
        if not fn("секретный_токен", "секретный_токен"):
            return False, "Failed on Cyrillic token match"
        if fn("секретный_токен", "другой_токен"):
            return False, "Failed on Cyrillic token mismatch"
    except Exception as exc:
        return False, f"Exception during token verify: {exc}"
    return True, "Constant-time byte comparison passed all cases"


# Task 3
def test_t3(fn) -> Tuple[bool, str]:
    data = {
        "user": "alice",
        "api_key": "sk-1234567890abcdef",
        "nested": {
            "token": "ghp_secret987654321",
            "safe_url": "https://example.com",
        },
        "log_msg": "Failed: Bearer sk-secret-token-xyz on host",
    }
    try:
        cleaned = fn(data)
        if cleaned["user"] != "alice":
            return False, "Modified safe field 'user'"
        if cleaned["api_key"] != "***":
            return False, f"Failed to mask 'api_key': {cleaned['api_key']}"
        if cleaned["nested"]["token"] != "***":
            return False, f"Failed to mask nested 'token': {cleaned['nested']['token']}"
        if cleaned["nested"]["safe_url"] != "https://example.com":
            return False, "Modified safe nested URL"
        if "sk-secret-token" in str(cleaned["log_msg"]):
            return False, "Leaked inline secret token in log_msg"
    except Exception as exc:
        return False, f"Exception during secret scrub: {exc}"
    return True, "Secret scrubbing passed recursive and string checks"


# Task 4
def test_t4(cls) -> Tuple[bool, str]:
    try:
        tracker = cls()
        for i in range(3):
            if not tracker.record_edge_traversal("edge-1", max_iterations=3):
                return False, f"Iteration {i+1} of edge-1 was rejected early"
        if tracker.record_edge_traversal("edge-1", max_iterations=3):
            return False, "Iteration 4 of edge-1 was allowed when max was 3"
        if not tracker.record_edge_traversal("edge-2", max_iterations=2):
            return False, "Edge-2 was blocked by edge-1 count"
    except Exception as exc:
        return False, f"Exception in CycleTracker: {exc}"
    return True, "CycleTracker correctly enforced edge iteration limits"


# Task 5
def test_t5(fn) -> Tuple[bool, str]:
    try:
        allowed_root = "/srv/projects/my-project"
        forbidden = ["agy_profiles", "auth.json", ".ssh"]

        ok, _ = fn("/srv/projects/my-project/src/main.py", allowed_root, forbidden)
        if not ok:
            return False, "Rejected valid path inside allowed root"

        ok, _ = fn("/etc/passwd", allowed_root, forbidden)
        if ok:
            return False, "Allowed path outside allowed root (/etc/passwd)"

        ok, _ = fn("/srv/projects/my-project/../../etc/shadow", allowed_root, forbidden)
        if ok:
            return False, "Allowed path traversal ../../etc/shadow"

        ok, _ = fn("/srv/projects/my-project/agy_profiles/key.json", allowed_root, forbidden)
        if ok:
            return False, "Allowed forbidden pattern 'agy_profiles'"
    except Exception as exc:
        return False, f"Exception in validate_file_path: {exc}"
    return True, "Path boundary validation passed all containment and forbidden checks"


# Task 6
def test_t6(fn) -> Tuple[bool, str]:
    try:
        is_dest, cmd, targets = fn("rm -rf /tmp/test_dir /tmp/other")
        if not is_dest or cmd != "rm" or "/tmp/test_dir" not in targets:
            return False, f"Failed on 'rm -rf': got is_dest={is_dest}, cmd={cmd}, targets={targets}"

        is_dest, cmd, targets = fn("del /f /q C:/temp/file.txt")
        if not is_dest or cmd != "del" or any("file.txt" not in t for t in targets):
            return False, f"Failed on 'del': got is_dest={is_dest}, cmd={cmd}, targets={targets}"

        is_dest, _, _ = fn("git status")
        if is_dest:
            return False, "Marked safe command 'git status' as destructive"

        is_dest, _, _ = fn("ls -la /var/log")
        if is_dest:
            return False, "Marked safe command 'ls' as destructive"
    except Exception as exc:
        return False, f"Exception in is_destructive_command: {exc}"
    return True, "Shell command classification passed"


# Task 7
def test_t7(fn) -> Tuple[bool, str]:
    allowed = {"api.anthropic.com", "api.github.com", "generativelanguage.googleapis.com"}
    try:
        if not fn("https://api.anthropic.com/v1/messages", allowed):
            return False, "Blocked allowed host api.anthropic.com"
        if not fn("http://127.0.0.1:8080/health", allowed):
            return False, "Blocked loopback 127.0.0.1"
        if not fn("http://localhost:11434/api/tags", allowed):
            return False, "Blocked loopback localhost"
        if fn("http://internal-artifactory.local:8081", allowed):
            return False, "Allowed rogue internal host"
        if fn("https://evil-hacker.com/exfil", allowed):
            return False, "Allowed rogue external host"
    except Exception as exc:
        return False, f"Exception in is_outbound_allowed: {exc}"
    return True, "Network whitelist passed"


# Task 8
def test_t8(fn) -> Tuple[bool, str]:
    try:
        err_comp = {"router_error": True, "error_details": "Failover exhausted", "content": "Raw router error string"}
        res = fn(err_comp, "Fallback: next_call")
        if res.get("content") == "Raw router error string":
            return False, "Router error string was returned as assistant content"
        if res.get("content") != "Fallback: next_call":
            return False, f"Unexpected content: {res.get('content')}"
        if not res.get("router_fallback"):
            return False, "Missing metadata 'router_fallback'"

        normal_comp = {"router_error": False, "content": "Assistant answer"}
        res_norm = fn(normal_comp, "Fallback")
        if res_norm.get("content") != "Assistant answer":
            return False, "Normal response was corrupted"
    except Exception as exc:
        return False, f"Exception in sanitize_hermes_response: {exc}"
    return True, "Router safety fuse response sanitization passed"


# Task 9
def test_t9(fn) -> Tuple[bool, str]:
    try:
        r, src = fn(explicit_role="developer-1", model="claude-opus", session_role="manager")
        if r != "developer-1" or src != "explicit":
            return False, f"Level 1 failed: got ({r}, {src}), expected ('developer-1', 'explicit')"

        r, src = fn(explicit_role=None, model="claude-opus-4-6", session_role="manager")
        if r != "code-reviewer" or src != "model_match":
            return False, f"Level 2 failed: got ({r}, {src}), expected ('code-reviewer', 'model_match')"

        r, src = fn(explicit_role=None, model="unknown-model", session_role="developer-2")
        if r != "developer-2" or src != "session_affinity":
            return False, f"Level 3 failed: got ({r}, {src}), expected ('developer-2', 'session_affinity')"

        r, src = fn(explicit_role=None, model="unknown-model", session_role=None, default_role="manager")
        if r != "manager" or src != "default_fallback":
            return False, f"Level 4 failed: got ({r}, {src}), expected ('manager', 'default_fallback')"
    except Exception as exc:
        return False, f"Exception in resolve_role: {exc}"
    return True, "4-level role resolution passed in strict hierarchy"


# Task 10
def test_t10(fn) -> Tuple[bool, str]:
    base = {
        "PATH": "/usr/bin:/bin",
        "HOME": "/home/user",
        "OPENAI_API_KEY": "sk-secret123",
        "MY_TOKEN": "token_val",
        "LANG": "en_US.UTF-8",
    }
    allowed = {"PATH", "HOME", "LANG", "OPENAI_API_KEY"}
    overrides = {"USERPROFILE": "/srv/profile_1"}

    try:
        clean = fn(base, allowed, overrides)
        if "PATH" not in clean or clean["PATH"] != "/usr/bin:/bin":
            return False, "Missing allowed 'PATH'"
        if "OPENAI_API_KEY" in clean:
            return False, "Leaked 'OPENAI_API_KEY' despite being in allowed list"
        if "MY_TOKEN" in clean:
            return False, "Leaked 'MY_TOKEN'"
        if clean.get("USERPROFILE") != "/srv/profile_1":
            return False, "Override 'USERPROFILE' was not applied"
    except Exception as exc:
        return False, f"Exception in build_safe_env: {exc}"
    return True, "Safe environment constructor passed"


# Task 11
def test_t11(fn) -> Tuple[bool, str]:
    try:
        if fn(is_enabled=False, is_authenticated=True, is_auth_expired=False, cooldown_sec=0, is_cold_spare=False) != "disabled":
            return False, "Failed disabled check"
        if fn(is_enabled=True, is_authenticated=False, is_auth_expired=True, cooldown_sec=0, is_cold_spare=False) != "auth_expired":
            return False, "Failed auth_expired check"
        if fn(is_enabled=True, is_authenticated=False, is_auth_expired=False, cooldown_sec=0, is_cold_spare=True) != "cold_spare":
            return False, "Failed cold_spare check"
        if fn(is_enabled=True, is_authenticated=False, is_auth_expired=False, cooldown_sec=0, is_cold_spare=False) != "not_configured":
            return False, "Failed not_configured check"
        if fn(is_enabled=True, is_authenticated=True, is_auth_expired=False, cooldown_sec=120, is_cold_spare=False) != "quota_exhausted":
            return False, "Failed quota_exhausted check"
        if fn(is_enabled=True, is_authenticated=True, is_auth_expired=False, cooldown_sec=0, is_cold_spare=False) != "healthy":
            return False, "Failed healthy check"
    except Exception as exc:
        return False, f"Exception in determine_profile_health: {exc}"
    return True, "Unified health status priority passed"


# Task 12
def test_t12(cls) -> Tuple[bool, str]:
    try:
        lm = cls(default_max_concurrency=2, default_lease_timeout=5.0)
        l1 = lm.acquire("profile-1")
        if not l1.get("granted"):
            return False, "Failed to acquire first lease for profile-1"
        l2 = lm.acquire("profile-1")
        if not l2.get("granted"):
            return False, "Failed to acquire second lease for profile-1"
        l3 = lm.acquire("profile-1")
        if l3.get("granted"):
            return False, "Granted 3rd lease when max concurrency was 2"

        lm.release("profile-1", l1["lease_id"])
        l4 = lm.acquire("profile-1")
        if not l4.get("granted"):
            return False, "Failed to acquire lease after release"
    except Exception as exc:
        return False, f"Exception in Long-Context LeaseManager: {exc}"
    return True, "Long-context LeaseManager correctly implemented concurrent slots and release"


BENCHMARK_TASKS: List[BenchmarkTask] = [
    BenchmarkTask(
        task_id="T01_extract_model_family",
        title="Extract Model Family",
        category="routing",
        prompt="Write a Python function `extract_model_family(model_name: str) -> str` that inspects a model identifier string (e.g. 'gemini-3.7-flash', 'claude-opus-4-6', 'gpt-4o', 'deepseek-v4-pro', 'kimi-k2.7', 'qwen3.8-max', 'grok-4.5', 'glm-5.3') and returns the canonical lower-case family name ('gemini', 'claude', 'gpt', 'deepseek', 'kimi', 'qwen', 'grok', 'glm'). If no family is recognized, return 'unknown'. Output only the Python code without extra conversational text.",
        expected_function_name="extract_model_family",
        test_function=test_t1,
    ),
    BenchmarkTask(
        task_id="T02_verify_auth_token",
        title="Constant-Time Byte Token Comparison",
        category="security",
        prompt="Write a Python function `verify_auth_token(given_token: str | None, required_token: str) -> bool` that performs a constant-time byte-level comparison using `secrets.compare_digest`. It must handle `given_token` being `None` or non-ASCII characters without raising `TypeError`. Return `True` if tokens match, `False` otherwise. Output only the Python code without extra conversational text.",
        expected_function_name="verify_auth_token",
        test_function=test_t2,
    ),
    BenchmarkTask(
        task_id="T03_scrub_secrets",
        title="Recursive Secret & PII Scrubbing",
        category="security",
        prompt="Write a Python function `scrub_secrets(data: Any) -> Any` that recursively processes dictionaries, lists, and strings. If a dictionary key contains (case-insensitive) 'token', 'secret', 'api_key', 'password', or 'bearer', its value must be replaced with '***'. Strings containing patterns like 'Bearer <token>' or 'sk-<token>' must have the token replaced with '***'. All other keys and values must be preserved intact. Output only the Python code.",
        expected_function_name="scrub_secrets",
        test_function=test_t3,
    ),
    BenchmarkTask(
        task_id="T04_cycle_tracker",
        title="DAG Loop & Cycle Iteration Tracker",
        category="workflow",
        prompt="Write a Python class `CycleTracker` with method `record_edge_traversal(self, edge_id: str, max_iterations: int) -> bool`. It tracks traversal counts per `edge_id`. If traversal count <= max_iterations, return `True`. If it exceeds max_iterations, return `False`. Output only the Python code.",
        expected_function_name="CycleTracker",
        test_function=test_t4,
    ),
    BenchmarkTask(
        task_id="T05_validate_file_path",
        title="Safe File Path Boundary Validation",
        category="security",
        prompt="Write a Python function `validate_file_path(target_path: str, allowed_root: str, forbidden_patterns: list[str]) -> tuple[bool, str]` using `pathlib.Path`. Resolve both paths to prevent `../` traversal attacks. Ensure `target_path` is strictly within `allowed_root`. If any forbidden pattern (case-insensitive substring) is present in the path, return `(False, 'Forbidden path pattern')`. If outside allowed root, return `(False, 'Path outside boundary')`. Otherwise return `(True, 'OK')`. Output only the Python code.",
        expected_function_name="validate_file_path",
        test_function=test_t5,
    ),
    BenchmarkTask(
        task_id="T06_is_destructive_command",
        title="Shell Command Classifier",
        category="security",
        prompt="Write a Python function `is_destructive_command(cmd_line: str) -> tuple[bool, str, list[str]]`. Parse the command line (using `shlex.split`). If the executable is in {'rm', 'rmdir', 'unlink', 'del', 'erase', 'remove-item', 'rd'}, return `(True, command_name, list_of_target_paths)` filtering out argument flags (e.g. starting with '-' or Windows flags like '/f', '/q'). Otherwise return `(False, command_name, [])`. Output only the Python code.",
        expected_function_name="is_destructive_command",
        test_function=test_t6,
    ),
    BenchmarkTask(
        task_id="T07_is_outbound_allowed",
        title="Outbound Destination Network Whitelist",
        category="network",
        prompt="Write a Python function `is_outbound_allowed(url_or_host: str, allowed_hosts: set[str]) -> bool` using `urllib.parse`. Extract the hostname in lower-case. Return `True` if hostname is in `allowed_hosts`, is a subdomain of an allowed host, or is loopback ('127.0.0.1', 'localhost'). Otherwise return `False`. Output only the Python code.",
        expected_function_name="is_outbound_allowed",
        test_function=test_t7,
    ),
    BenchmarkTask(
        task_id="T08_sanitize_hermes_response",
        title="Router Safety Fuse Response Sanitizer",
        category="router",
        prompt="Write a Python function `sanitize_hermes_response(completion: dict, fallback_message: str) -> dict`. If `completion.get('router_error')` is True, replace `content` with `fallback_message` and set `router_fallback: True`. Otherwise return a copy of `completion` with original `content`. Never allow raw router errors to become assistant content. Output only the Python code.",
        expected_function_name="sanitize_hermes_response",
        test_function=test_t8,
    ),
    BenchmarkTask(
        task_id="T09_resolve_role",
        title="4-Level Dynamic Role Resolver",
        category="router",
        prompt="Write a Python function `resolve_role(explicit_role: str | None, model: str | None, session_role: str | None, default_role: str = 'manager') -> tuple[str, str]`. Resolve role strictly in 4 hierarchical levels: 1. `explicit_role` -> return (explicit_role, 'explicit'); 2. `model` contains 'claude' -> return ('code-reviewer', 'model_match'), 'gemini-3.1' -> ('developer-2', 'model_match'), 'gemini-3.7' -> ('developer-1', 'model_match'); 3. `session_role` -> return (session_role, 'session_affinity'); 4. return (default_role, 'default_fallback'). Never use regex prompt guessing. Output only the Python code.",
        expected_function_name="resolve_role",
        test_function=test_t9,
    ),
    BenchmarkTask(
        task_id="T10_build_safe_env",
        title="Isolated Subprocess Environment Constructor",
        category="security",
        prompt="Write a Python function `build_safe_env(base_env: dict[str, str], allowed_keys: set[str], overrides: dict[str, str]) -> dict[str, str]`. Copy only keys present in `allowed_keys`. Strip any key containing (case-insensitive) 'api_key', 'token', 'secret', or 'password'. Apply `overrides` at the end. Output only the Python code.",
        expected_function_name="build_safe_env",
        test_function=test_t10,
    ),
    BenchmarkTask(
        task_id="T11_determine_profile_health",
        title="Unified Health Status Priority Resolver",
        category="health",
        prompt="Write a Python function `determine_profile_health(is_enabled: bool, is_authenticated: bool, is_auth_expired: bool, cooldown_sec: int, is_cold_spare: bool) -> str`. Resolve status in exact priority: 1. not is_enabled -> 'disabled'; 2. not is_authenticated: if is_auth_expired -> 'auth_expired', elif is_cold_spare -> 'cold_spare', else -> 'not_configured'; 3. cooldown_sec > 0 -> 'quota_exhausted'; 4. else -> 'healthy'. Output only the Python code.",
        expected_function_name="determine_profile_health",
        test_function=test_t11,
    ),
    BenchmarkTask(
        task_id="T12_long_context_lease_manager",
        title="Long Context (32k+) Thread-Safe Lease Manager",
        category="concurrency",
        prompt="Write a Python class `LeaseManager` with `__init__(self, default_max_concurrency: int = 2, default_lease_timeout: float = 30.0)`, `acquire(self, profile_id: str, max_concurrency: int | None = None) -> dict`, and `release(self, profile_id: str, lease_id: str) -> bool`. `acquire` returns `{'granted': True, 'lease_id': lid, 'active_count': int}` if current active leases < max_concurrency, else `{'granted': False, 'active_count': int}`. `release` removes the lease by `lease_id` and returns `True` if found. Ensure thread-safety using `threading.Lock`. Output only the Python code.",
        expected_function_name="LeaseManager",
        test_function=test_t12,
        is_long_context=True,
    ),
]
