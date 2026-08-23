"""Мастер подключения обязан закрываться по кнопке «Завершить».

Дефект, ради которого написан файл: `_finish` вызывал
`EventLogService.log_event` — метода, которого у сервиса нет. Под `pythonw`
консоли нет, трейсбек Tk уходил в никуда, и для пользователя кнопка
«Завершить подключение» просто не работала: окно оставалось открытым,
аккаунт в маршрутизацию не попадал.
"""

from __future__ import annotations

import pytest

pytest.importorskip("customtkinter")

import customtkinter as ctk

from antigravity_provider.router.ui.add_account_wizard import AddAccountWizard


@pytest.fixture(scope="module")
def ui_root(tk_root):
    app = ctk.CTkToplevel(tk_root)
    app.withdraw()
    yield app
    try:
        app.destroy()
    except Exception:
        pass


def _wizard(root, on_complete=None):
    w = AddAccountWizard(root, on_complete=on_complete)
    w.withdraw()
    w.selected_provider = "antigravity"
    w.target_slot = "ag-w2"
    w.discovered_identity = "user@example.com"
    return w


@pytest.mark.ui
def test_finish_closes_wizard_and_reports_result(ui_root):
    seen = []
    w = _wizard(ui_root, on_complete=seen.append)

    w._finish()

    assert w.winfo_exists() == 0, "окно мастера осталось открытым после «Завершить»"
    assert seen == [
        {"provider": "antigravity", "profile_id": "ag-w2", "identity": "user@example.com"}
    ]


@pytest.mark.ui
def test_finish_closes_even_if_callback_raises(ui_root):
    """Сбой в обработчике владельца не должен запирать пользователя в мастере."""

    def boom(_result):
        raise RuntimeError("обновление данных упало")

    w = _wizard(ui_root, on_complete=boom)

    w._finish()

    assert w.winfo_exists() == 0
