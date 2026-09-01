"""Подключение аккаунта не должно ждать опроса провайдера.

Мастер владельца замирал на шаге 3 с надписью «сохранение аккаунта и запуск
проверки». Зависанием это не было: действие честно ждало проверку Antigravity
через CLI — до 90 с на захват замка профиля, до 65 на каталог моделей и до 90
на пробный вызов. Около четырёх минут молчания при обещанной «минуте на этап».

Сохранение и назначение роли занимают миллисекунды. Опрос провайдера идёт в
фоне, а карточка обновляется, когда он закончится.
"""
from __future__ import annotations

import time
from unittest.mock import patch

from antigravity_provider.router.account_probe_service import AccountProbeService
from antigravity_provider.router.action_handler import ActionExecutor
from antigravity_provider.router.auto_assigner import AutoAssigner
from antigravity_provider.router.profile_manager import ProfileAuthManager


def _connect_authenticated_antigravity():
    with patch.object(ProfileAuthManager, "get_profile_status", return_value={"authenticated": True}), \
         patch.object(ProfileAuthManager, "load_profile_auth", return_value={"email": "x@gmail.com"}), \
         patch.object(ProfileAuthManager, "save_profile_auth", return_value="/tmp/auth.json"), \
         patch.object(AutoAssigner, "ensure_profile_definition", return_value=(True, "ok")), \
         patch.object(AutoAssigner, "assign_profile_to_role", return_value=(True, "ok")):
        return ActionExecutor.execute(
            "add_account",
            {"provider": "antigravity", "profile_id": "ag-1", "target_role": "orchestrator"},
        )


def test_connect_returns_without_waiting_for_provider():
    slow_call = []

    def _slow_check_now(self, provider, profile_id, models_only=False):
        slow_call.append(profile_id)
        time.sleep(5)  # изображаем опрос провайдера
        return {"ok": True, "message": "проверено"}

    with patch.object(AccountProbeService, "schedule", return_value=True) as scheduled, \
         patch.object(AccountProbeService, "check_now", _slow_check_now):
        started = time.monotonic()
        res = _connect_authenticated_antigravity()
        elapsed = time.monotonic() - started

    assert res["ok"], res
    assert not slow_call, "действие не должно ждать опрос провайдера"
    assert scheduled.called, "проверка обязана быть поставлена в фон"
    assert elapsed < 2, f"ответ занял {elapsed:.1f} с"
    assert res["data"]["check"] == "running"


def test_result_reaches_owner_when_background_service_is_down():
    """Служба не работает — проверяем здесь, иначе результата не будет вовсе."""
    with patch.object(AccountProbeService, "schedule", return_value=False), \
         patch.object(AccountProbeService, "state", return_value={"state": "never_checked"}), \
         patch.object(
             AccountProbeService,
             "check_now",
             return_value={"ok": False, "message": "провайдер отказал", "data": {}},
         ) as checked:
        res = _connect_authenticated_antigravity()

    assert checked.called, "без фоновой службы проверка выполняется на месте"
    assert res["message"] == "провайдер отказал"


def test_check_already_running_is_not_awaited():
    with patch.object(AccountProbeService, "schedule", return_value=False), \
         patch.object(AccountProbeService, "state", return_value={"state": "checking"}), \
         patch.object(AccountProbeService, "check_now") as checked:
        res = _connect_authenticated_antigravity()

    assert not checked.called, "уже идущую проверку не ждём и не дублируем"
    assert res["ok"] and res["data"]["check"] == "running"
