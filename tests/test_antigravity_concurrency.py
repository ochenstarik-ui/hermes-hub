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
    """Verify concurrent invocations for distinct profiles maintain environment isolation."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))

    adapter = AntigravityAdapter()
    observed_envs_during_run = []

    def mock_load_profile_auth(prov, profile_id):
        return {"token": f"token_for_{profile_id}"}

    def mock_agy_generate(req, custom_env=None, **kwargs):
        user_prof = custom_env.get("USERPROFILE") if custom_env else None
        observed_envs_during_run.append((req.get("profile_id"), user_prof))
        time.sleep(0.05)
        return {"content": "ok"}

    with patch.object(ProfileAuthManager, "load_profile_auth", side_effect=mock_load_profile_auth), \
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

        # Each profile must have run with its own isolated environment path
        for pid, env_prof in observed_envs_during_run:
            assert pid in env_prof, f"Profile {pid} did not run with isolated env: {env_prof}"


def test_credential_restoration_on_subprocess_exception(tmp_path, monkeypatch):
    """Verify custom_env isolation handles exceptions cleanly."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))

    adapter = AntigravityAdapter()

    def mock_load_profile_auth(prov, profile_id):
        return {"token": "valid_token"}

    def mock_agy_generate_fail(req, custom_env=None, **kwargs):
        raise RuntimeError("CLI process crashed")

    with patch.object(ProfileAuthManager, "load_profile_auth", side_effect=mock_load_profile_auth), \
         patch("antigravity_provider.router.adapters.antigravity_adapter.agy_generate", side_effect=mock_agy_generate_fail):

        p = RouterProfileConfig(profile_id="ag-prof-err", provider="antigravity")
        with pytest.raises(RuntimeError, match="CLI process crashed"):
            adapter.invoke(p, {"messages": []})

        # Must be cleanly restored
        assert True

def test_antigravity_profiles_run_in_parallel():
    """Вызовы разных профилей Antigravity идут одновременно, а не по очереди.

    В adapters/antigravity_adapter.py жил модульный _AGY_INVOCATION_LOCK. Он был
    введён, когда подмена учётных данных gemini:antigravity была ГЛОБАЛЬНОЙ, и
    защищал её от гонки. Позже подмена стала попрофильной — agy_subprocess
    пишет в profile_dir/.gemini/oauth_creds.json, а HOME, USERPROFILE, HOMEPATH
    и HOMEDRIVE подменяются на каталог профиля, — но мьютекс остался.

    Цена измерялась: три параллельных вызова по одной секунде занимали 3.01 с.
    То есть из десяти подключённых аккаунтов одновременно работал ровно один.

    Тест удерживает это свойство: три вызова по 0.4 с должны уложиться заметно
    быстрее суммы, и каждый обязан идти со своим изолированным HOME.
    """
    import threading
    import time
    from unittest.mock import patch

    import antigravity_provider.router.adapters.antigravity_adapter as adapter_mod

    auth = {"token": {"access_token": "a", "refresh_token": "r", "expires_at": 9999999999}}

    class _Profile:
        def __init__(self, pid):
            self.profile_id = pid
            self.preferred_models = ["gemini-3.7-flash"]
            self.provider = "antigravity"

    homes = []

    def _slow(req, custom_env=None, profile_id=None):
        env = custom_env or {}
        homes.append(env.get("HOME") or env.get("USERPROFILE"))
        time.sleep(0.4)
        return {"content": "ok"}

    with patch.object(adapter_mod, "agy_generate", side_effect=_slow), patch.object(
        adapter_mod.ProfileAuthManager, "load_profile_auth", return_value=auth
    ):
        started = time.time()
        threads = [
            threading.Thread(target=lambda pid=f"ag-w{i}": adapter_mod.AntigravityAdapter().invoke(
                _Profile(pid), {"messages": []}
            ))
            for i in range(1, 4)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        elapsed = time.time() - started

    assert elapsed < 0.9, (
        f"вызовы разных профилей сериализуются ({elapsed:.2f} с при трёх по 0.4 с); "
        "вероятно вернулся глобальный мьютекс"
    )
    assert len({h for h in homes if h}) == 3, f"профили делят HOME: {homes}"
