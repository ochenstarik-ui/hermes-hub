"""Открытое окно аккаунта обязано обновляться по свежему снапшоту.

Владелец открыл карточку Grok сразу после запуска — до того, как пришли
живые квоты, — и она навсегда осталась с заглушкой «Grok 2h — Н/Д» и
статусом «Не проверялся», хотя сервер уже отдавал 14% расхода подписки и
проверка подключения прошла успешно.

Окно рисовалось один раз при открытии и на опрос не реагировало.
"""

from __future__ import annotations

import pathlib

APP_JS = pathlib.Path("src/antigravity_provider/router/web/static/app.js").read_text(encoding="utf-8")


def test_open_modal_is_tracked_and_redrawn():
    assert "_openAccountModalProfile" in APP_JS, "открытое окно не отслеживается"

    # Объявление обязано идти ДО использования: let не поднимается, и
    # обращение к нему раньше объявления роняет обработчик снапшота.
    declaration = APP_JS.index("let _openAccountModalProfile")
    first_use = APP_JS.index("if (_openAccountModalProfile)")
    assert declaration < first_use, "переменная используется раньше объявления"


def test_modal_redraw_happens_on_snapshot_apply():
    """Перерисовка должна быть привязана к применению снапшота."""
    head = APP_JS[: APP_JS.index("if (_openAccountModalProfile)")]
    assert "currentSnapshot = snapshot" in head, "перерисовка не там, где применяется снапшот"


def test_closing_modal_stops_tracking_and_polling():
    block = APP_JS.split("function closeModal()", 1)[1][:300]
    assert "_openAccountModalProfile = null" in block, "после закрытия окно продолжает перерисовываться"
    assert "stopDeviceAuthPolling" in block, "опрос кода устройства не останавливается при закрытии"
