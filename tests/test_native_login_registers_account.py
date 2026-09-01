"""Вход через терминал должен регистрировать аккаунт, а не только записывать ключи.

Владелец: «в программе нет аккаунтов. я добавил первый… аккаунты так и не
появились». При этом вход проходил, agy отдавал одиннадцать моделей.

Причина: список аккаунтов строится по конфигурации маршрутизатора, а вход через
терминал завершается своим путём, мимо add_account, и записи в конфигурации не
создаёт. Учётные данные на диске, профиль числится подключённым — и его нигде
не видно.
"""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from antigravity_provider import paths
from antigravity_provider.router.action_handler import ActionExecutor
from antigravity_provider.router.router_config import load_router_config
from antigravity_provider.router.unified_health import UnifiedHealthService


def _profile_with_agy_credentials(slot: str = "ag-5"):
    pdir = paths.get_profile_dir(slot, "antigravity", create=True)
    cli = pdir / ".gemini" / "antigravity-cli"
    cli.mkdir(parents=True, exist_ok=True)
    (cli / "antigravity-oauth-token").write_text(
        json.dumps(
            {
                "auth_method": "consumer",
                "token": {"access_token": "ya29.TEST", "refresh_token": "1//TEST"},
            }
        ),
        encoding="utf-8",
    )
    return pdir


def _completed(slot: str = "ag-5"):
    return (
        True,
        "Авторизация успешно завершена через agy CLI",
        {"status": "completed", "profile_id": slot, "email": "owner@gmail.com"},
    )


@pytest.mark.unit
def test_completed_login_registers_the_profile():
    _profile_with_agy_credentials()

    with patch(
        "antigravity_provider.agy_subprocess.poll_native_agy_login",
        return_value=_completed(),
    ):
        res = ActionExecutor.execute("poll_native_auth", {"session_id": "s1"})

    assert res["ok"], res
    assert "ag-5" in load_router_config().profiles, (
        "без записи в конфигурации аккаунт нигде не появится"
    )


@pytest.mark.unit
def test_registered_profile_is_visible_in_the_interface():
    _profile_with_agy_credentials()

    with patch(
        "antigravity_provider.agy_subprocess.poll_native_agy_login",
        return_value=_completed(),
    ):
        ActionExecutor.execute("poll_native_auth", {"session_id": "s1"})

    shown = [
        view.profile_id
        for group in UnifiedHealthService.get().scan_all(force=True).values()
        for view in group
    ]
    assert "ag-5" in shown


@pytest.mark.unit
def test_failed_registration_is_reported_not_swallowed():
    """Молчаливый успех при незарегистрированном аккаунте — то же зависание вслепую."""
    _profile_with_agy_credentials()

    with patch(
        "antigravity_provider.agy_subprocess.poll_native_agy_login",
        return_value=_completed(),
    ), patch(
        "antigravity_provider.router.auto_assigner.AutoAssigner.ensure_profile_definition",
        return_value=(False, "слот занят другим провайдером"),
    ):
        res = ActionExecutor.execute("poll_native_auth", {"session_id": "s1"})

    assert not res["ok"]
    assert "не зарегистрирован" in res["message"]
    assert "слот занят другим провайдером" in res["message"]


@pytest.mark.unit
def test_login_still_in_progress_registers_nothing():
    with patch(
        "antigravity_provider.agy_subprocess.poll_native_agy_login",
        return_value=(True, "Ожидание завершения авторизации в терминале...", {"status": "pending"}),
    ):
        res = ActionExecutor.execute("poll_native_auth", {"session_id": "s1"})

    assert res["ok"]
    assert not load_router_config().profiles
