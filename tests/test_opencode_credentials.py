"""Адаптер OpenCode Go обязан читать ключ из хранилища профилей.

Дефект: мастер подключения сохраняет ключ через ProfileAuthManager, а
_resolve_api_key смотрел только в auth_config из YAML и в переменные
окружения. Аккаунт, подключённый через интерфейс, не работал никогда —
маршрутизация падала с «No API key found», хотя ключ лежал на диске, а
карточка показывала «Работает».

Остальные адаптеры (grok, claude, codex) хранилище читают; этот — нет.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from antigravity_provider.router.adapters.opencode_adapter import OpenCodeGoAdapter


@pytest.fixture
def profile():
    return SimpleNamespace(profile_id="opengo-1", account_id="acc-1", auth_config={})


def test_api_key_is_read_from_profile_store(monkeypatch, profile):
    import antigravity_provider.router.profile_manager as pm

    monkeypatch.setattr(
        pm.ProfileAuthManager,
        "load_profile_auth",
        staticmethod(lambda provider, pid: {"api_key": "stored-key-123", "auth_mode": "api_key"}),
    )
    for var in ("OPENCODE_GO_API_KEY", "OPENCODE_ZEN_API_KEY", "OPENCODE_API_KEY"):
        monkeypatch.delenv(var, raising=False)

    assert OpenCodeGoAdapter()._resolve_api_key(profile) == "stored-key-123"


def test_health_check_passes_when_only_profile_store_has_key(monkeypatch, profile):
    """Именно это расхождение показывало «Работает» на нерабочем аккаунте."""
    import antigravity_provider.router.profile_manager as pm

    monkeypatch.setattr(
        pm.ProfileAuthManager,
        "load_profile_auth",
        staticmethod(lambda provider, pid: {"api_key": "stored-key-123"}),
    )
    for var in ("OPENCODE_GO_API_KEY", "OPENCODE_ZEN_API_KEY", "OPENCODE_API_KEY"):
        monkeypatch.delenv(var, raising=False)

    assert OpenCodeGoAdapter().health_check(profile) is True


def test_missing_credentials_still_report_no_key(monkeypatch, profile):
    """Пустое хранилище не должно давать ложноположительный результат."""
    import antigravity_provider.router.profile_manager as pm

    monkeypatch.setattr(
        pm.ProfileAuthManager, "load_profile_auth", staticmethod(lambda provider, pid: {})
    )
    for var in ("OPENCODE_GO_API_KEY", "OPENCODE_ZEN_API_KEY", "OPENCODE_API_KEY"):
        monkeypatch.delenv(var, raising=False)

    assert OpenCodeGoAdapter()._resolve_api_key(profile) is None
    assert OpenCodeGoAdapter().health_check(profile) is False
