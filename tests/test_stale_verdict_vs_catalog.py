"""Вердикт проверки не должен переживать более свежий каталог моделей.

В карточке владельца рядом стояли «Проверен: не работает — Please sign in» и
«Получено 11 моделей · 13:25:53». Источники разные и обновляются независимо:
красная строка берётся из состояния проверки, список — из кэша каталога.
Каталог был получен ПОЗЖЕ отказа, то есть провайдер с тех пор ответил.

Утверждать отказ в такой ситуации нельзя. Объявлять аккаунт рабочим — тоже
не за что: проверка после этого не выполнялась. Честный ответ один: вердикт
устарел, нужна новая проверка.
"""
from __future__ import annotations

import time

import pytest

from antigravity_provider.router.account_probe_service import AccountProbeService
from antigravity_provider.router.model_discovery_service import ModelDiscoveryService
from antigravity_provider.router.profile_manager import ProfileAuthManager
from antigravity_provider.router.router_config import (
    RouterConfig,
    RouterProfileConfig,
    save_router_config,
)
from antigravity_provider.router.unified_health import (
    STATUS_NOT_TESTED,
    STATUS_UNHEALTHY,
    UnifiedHealthService,
)


def _prepare(failed_at: float, catalog_at: float | None, catalog_error=None):
    cfg = RouterConfig()
    cfg.profiles["ag-5"] = RouterProfileConfig(
        profile_id="ag-5",
        provider="antigravity",
        account_id="ag-5",
        preferred_models=[],
        enabled=True,
    )
    save_router_config(cfg)
    ProfileAuthManager.save_profile_auth(
        "antigravity",
        "ag-5",
        {
            # Запись входа Antigravity по праву отказывает без токена доступа,
            # поэтому в проверке он должен быть настоящим по форме.
            "token": {
                "access_token": "ya29.TEST",
                "refresh_token": "1//TEST",
                "token_type": "Bearer",
                "expiry_date": int((time.time() + 3600) * 1000),
            },
            "email": "owner@gmail.com",
            "auth_method": "oauth",
        },
    )

    probe = AccountProbeService.get()
    with probe._lock:
        probe._states["ag-5"] = {
            "state": "failed",
            "provider": "antigravity",
            "checked_at": failed_at,
            "message": "agy models: код 1. Please sign in to view available models.",
        }

    discovery = ModelDiscoveryService.get()
    with discovery._cache_lock:
        discovery._cache["antigravity:ag-5"] = {
            "models": ["gemini-3.1-pro-high", "claude-sonnet-4-6"],
            "discovered_at": catalog_at,
            "error": catalog_error,
        }
    return UnifiedHealthService.get()


def _view(service):
    profiles = service.scan_all(force=True)
    return next(p for p in profiles["antigravity"] if p.profile_id == "ag-5")


@pytest.mark.unit
def test_newer_catalog_makes_the_failed_verdict_stale(tmp_path):
    now = time.time()
    view = _view(_prepare(failed_at=now - 60, catalog_at=now - 20))

    assert view.health_state == STATUS_NOT_TESTED
    assert "устарела" in view.health_label_ru
    assert "Please sign in" not in view.health_label_ru


@pytest.mark.unit
def test_failure_stands_when_it_is_the_newer_fact(tmp_path):
    now = time.time()
    view = _view(_prepare(failed_at=now - 10, catalog_at=now - 300))

    assert view.health_state == STATUS_UNHEALTHY
    assert "Please sign in" in view.health_label_ru


@pytest.mark.unit
def test_failure_stands_when_catalog_itself_errored(tmp_path):
    now = time.time()
    view = _view(
        _prepare(failed_at=now - 60, catalog_at=now - 20, catalog_error="Сервер отказал")
    )

    assert view.health_state == STATUS_UNHEALTHY


@pytest.mark.unit
def test_failure_stands_when_catalog_was_never_obtained(tmp_path):
    now = time.time()
    view = _view(_prepare(failed_at=now - 60, catalog_at=None))

    assert view.health_state == STATUS_UNHEALTHY
