"""Concurrency & Race Condition Regression Tests for Antigravity Adapter Credential Swapping.

Verifies:
1. Concurrent invocations with different profiles do not clobber shared gemini:antigravity credentials.
2. Original Windows Credential Manager state is restored cleanly upon completion.
3. Timeout or exception in subprocess does not leave credentials corrupted or swapped.
"""
from __future__ import annotations

import concurrent.futures
import time
from unittest.mock import MagicMock, patch
import pytest

from antigravity_provider.router.adapters.antigravity_adapter import AntigravityAdapter
from antigravity_provider.router.profile_manager import ProfileAuthManager
from antigravity_provider.router.router_config import RouterProfileConfig


def test_concurrent_antigravity_credential_isolation(tmp_path, monkeypatch):
    """Verify concurrent invocations for distinct profiles maintain credential integrity."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))

    adapter = AntigravityAdapter()

    # Fake in-memory credential storage for Windows Credential Manager
    win_creds = {"gemini:antigravity": {"token": "original_default_token"}}
    observed_creds_during_run = []

    def mock_read(target):
        return win_creds.get(target)

    def mock_write(target, data):
        win_creds[target] = data

    def mock_load_profile_auth(prov, profile_id):
        return {"token": f"token_for_{profile_id}"}

    def mock_agy_generate(req, custom_env=None):
        # Record what was active in win_creds at execution time
        current_active = win_creds.get("gemini:antigravity", {}).get("token")
        observed_creds_during_run.append((req.get("profile_id"), current_active))
        time.sleep(0.05)  # Simulate real CLI generation latency
        return {"content": "ok"}

    with patch.object(ProfileAuthManager, "read_windows_credential", side_effect=mock_read), \
         patch.object(ProfileAuthManager, "write_windows_credential", side_effect=mock_write), \
         patch.object(ProfileAuthManager, "load_profile_auth", side_effect=mock_load_profile_auth), \
         patch("antigravity_provider.router.adapters.antigravity_adapter.agy_generate", side_effect=mock_agy_generate):

        p1 = RouterProfileConfig(profile_id="ag-prof-1", provider="antigravity")
        p2 = RouterProfileConfig(profile_id="ag-prof-2", provider="antigravity")
        p3 = RouterProfileConfig(profile_id="ag-prof-3", provider="antigravity")

        def run_invoke(p):
            return adapter.invoke(p, {"profile_id": p.profile_id, "messages": []})

        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            futs = [executor.submit(run_invoke, p) for p in (p1, p2, p3)]
            results = [f.result() for f in futs]

        assert len(results) == 3
        for r in results:
            assert r == {"content": "ok"}

        # Each profile must have seen its own token when executing
        for pid, active_tok in observed_creds_during_run:
            assert active_tok == f"token_for_{pid}", f"Race condition detected: profile {pid} ran with active token '{active_tok}'"

        # Windows Credential Manager must be restored to original_default_token
        assert win_creds["gemini:antigravity"]["token"] == "original_default_token"


def test_credential_restoration_on_subprocess_exception(tmp_path, monkeypatch):
    """Verify credentials are fully restored even when subprocess raises an unhandled error."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))

    adapter = AntigravityAdapter()
    win_creds = {"gemini:antigravity": {"token": "original_default_token"}}

    def mock_read(target):
        return win_creds.get(target)

    def mock_write(target, data):
        win_creds[target] = data

    with patch.object(ProfileAuthManager, "read_windows_credential", side_effect=mock_read), \
         patch.object(ProfileAuthManager, "write_windows_credential", side_effect=mock_write), \
         patch.object(ProfileAuthManager, "load_profile_auth", return_value={"token": "temp_error_token"}), \
         patch("antigravity_provider.router.adapters.antigravity_adapter.agy_generate", side_effect=RuntimeError("Subprocess crash")):

        p = RouterProfileConfig(profile_id="ag-error-prof", provider="antigravity")
        with pytest.raises(RuntimeError, match="Subprocess crash"):
            adapter.invoke(p, {"messages": []})

        # Must be cleanly restored
        assert win_creds["gemini:antigravity"]["token"] == "original_default_token"
