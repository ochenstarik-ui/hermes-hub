"""Опросы интерфейса не должны заливать владельца уведомлениями и кормить себя.

Владелец: «справа постоянно выходят статусы, прям без остановки. я вообще
ничего не вижу за ними».

Это был не таймер, а замкнутый круг: отрисовка настроек запускала опрос
состояния сжатия, executeAction на успехе вызывал fetchSnapshot, тот снова
перерисовывал настройки — и так без конца. Заодно каждый оборот показывал два
тоста: на запрос и на ответ.

Тем же путём заливали «poll_native_auth» во время входа.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

APP_JS = (
    Path(__file__).resolve().parent.parent
    / "src" / "antigravity_provider" / "router" / "web" / "static" / "app.js"
)


@pytest.fixture(scope="module")
def source() -> str:
    return APP_JS.read_text(encoding="utf-8")


def test_polling_actions_are_listed_as_silent(source):
    assert "SILENT_ACTIONS" in source
    for action in (
        "get_compression_status",
        "poll_native_auth",
        "poll_redirect_auth",
        "poll_device_auth",
    ):
        assert f"'{action}'" in source, f"{action} обязан быть среди молчаливых"


def test_silent_actions_show_no_toasts(source):
    """Все четыре места, где executeAction показывает тост, под охраной silent."""
    body = source.split("async function executeAction")[1].split("// ── GLOBAL HEADER")[0]

    start, success, failure, network = (
        body.split("try {")[0],
        body.split("if (result.ok)")[1].split("} else {")[0],
        body.split("} else {")[1].split("} catch")[0],
        body.split("} catch")[1],
    )
    for part, where in (
        (start, "начало действия"),
        (success, "успех"),
        (failure, "отказ"),
        (network, "сбой сети"),
    ):
        assert "showToast(" in part, f"место не найдено: {where}"
        assert part.index("if (!silent)") < part.index("showToast("), (
            f"тост без проверки молчаливости: {where}"
        )


def test_silent_actions_do_not_refetch_the_snapshot(source):
    """Круг замыкался именно здесь: успех опроса тянул за собой снапшот."""
    body = source.split("async function executeAction")[1].split("// ── GLOBAL HEADER")[0]
    success_block = body.split("if (result.ok)")[1].split("} else {")[0]
    assert "if (!silent)" in success_block
    assert success_block.index("if (!silent)") < success_block.index("fetchSnapshot(")


def test_settings_render_does_not_start_a_poll(source):
    """Опрос из отрисовки убран — она идёт на каждом обновлении снапшота."""
    render = source.split("function populateCompressorProfiles")[0]
    render_tail = render[-2000:]
    calls = re.findall(r"^\s*checkCompressionStatus\(\);", render_tail, re.MULTILINE)
    assert not calls, "опрос из отрисовки настроек запускать нельзя"


def test_status_is_requested_when_the_screen_opens(source):
    opening = source.split("if (viewName === 'settings')")[1][:400]
    assert "checkCompressionStatus()" in opening
