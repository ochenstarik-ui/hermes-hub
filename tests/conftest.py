"""Pytest configuration and global hermetic test isolation fixtures.

Enforces:
1. Zero modification to real user credentials or router_profiles.yaml.
2. Complete filesystem sandboxing in temporary directory via HERMES_HOME.
3. Offline execution for default test runs (network / live require explicit -m markers).
4. No accidental connects to local llama.cpp (8081/8082) or non-loopback hosts.
"""
from __future__ import annotations

import os
import socket
import sys
from pathlib import Path
import pytest

REPO_SRC = Path(__file__).resolve().parent.parent / "src"
if str(REPO_SRC) not in sys.path or sys.path[0] != str(REPO_SRC):
    sys.path.insert(0, str(REPO_SRC))

BLOCKED_INFERENCE_PORTS = {8081, 8082}
LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost", "0.0.0.0", "::"}


@pytest.fixture(autouse=True)
def isolate_hermes_environment(tmp_path, monkeypatch):
    """Automatically sandbox all file I/O to a temporary HERMES_HOME directory."""
    temp_hermes = tmp_path / "hermes_test_home"
    temp_hermes.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HERMES_HOME", str(temp_hermes))

    # Isolate all provider profile dirs
    (temp_hermes / "agy_profiles").mkdir(exist_ok=True)
    (temp_hermes / "codex_profiles").mkdir(exist_ok=True)
    (temp_hermes / "opengo_profiles").mkdir(exist_ok=True)
    (temp_hermes / "claude_profiles").mkdir(exist_ok=True)
    (temp_hermes / "grok_profiles").mkdir(exist_ok=True)
    (temp_hermes / "logs").mkdir(exist_ok=True)

    yield temp_hermes


def _socket_host_port(address) -> tuple[str | None, int | None]:
    if isinstance(address, tuple) and len(address) >= 2:
        host = address[0]
        port = address[1]
        if isinstance(host, bytes):
            host = host.decode("utf-8", errors="replace")
        try:
            return str(host), int(port)
        except (TypeError, ValueError):
            return str(host), None
    return None, None


def _reject_hermetic_connect(address) -> None:
    host, port = _socket_host_port(address)
    if port in BLOCKED_INFERENCE_PORTS:
        raise RuntimeError(
            f"hermetic tests must not contact local inference at {host}:{port}; "
            "mock check_local_servers / urllib.request.urlopen"
        )
    if host and host not in LOOPBACK_HOSTS and not host.startswith("127."):
        raise RuntimeError(
            f"hermetic tests must not open network connections to {host}:{port}; "
            "mark the test live/network or mock the call"
        )


@pytest.fixture(autouse=True)
def block_external_network_in_hermetic_tests(request, monkeypatch):
    """Fail fast instead of hanging on llama.cpp or cloud APIs."""
    if request.node.get_closest_marker("live") or request.node.get_closest_marker("network"):
        yield
        return

    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex
    real_create_connection = socket.create_connection

    def guarded_connect(self, address):
        _reject_hermetic_connect(address)
        return real_connect(self, address)

    def guarded_connect_ex(self, address):
        _reject_hermetic_connect(address)
        return real_connect_ex(self, address)

    def guarded_create_connection(address, *args, **kwargs):
        _reject_hermetic_connect(address)
        return real_create_connection(address, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", guarded_connect_ex)
    monkeypatch.setattr(socket, "create_connection", guarded_create_connection)
    yield


def pytest_configure(config):
    config.addinivalue_line("markers", "ui: mark test as requiring UI environment")

