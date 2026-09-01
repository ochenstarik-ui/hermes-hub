"""Экран настроек не должен молча терять поля.

Владелец не нашёл настройку прокси. Она была в разметке, но исчезала при
открытии экрана: arrangeSettingsPanels пересобирает настройки по жёсткому
списку идентификаторов, а исходную карточку удаляет целиком — вместе со всем,
чего в списке нет.

Поле существовало в файле, но его не было на экране, и никакая проверка этого
не ловила.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parent.parent / "src" / "antigravity_provider" / "router" / "web" / "static"


@pytest.fixture(scope="module")
def markup() -> str:
    return (STATIC / "index.html").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def workspace() -> str:
    return (STATIC / "workspace.js").read_text(encoding="utf-8")


def _grouped_ids(workspace: str) -> list[str]:
    block = workspace.split("const groups = [")[1].split("];")[0]
    return re.findall(r"'(setting-[a-z0-9-]+)'", block)


def test_every_grouped_id_exists_in_the_markup(markup, workspace):
    for element_id in _grouped_ids(workspace):
        assert f'id="{element_id}"' in markup, f"{element_id} перечислен в группах, но его нет в разметке"


def test_proxy_setting_is_reachable(markup, workspace):
    assert 'id="setting-provider-proxy-url"' in markup
    assert "setting-provider-proxy-url" in _grouped_ids(workspace), (
        "негруппированная строка удаляется вместе с исходной карточкой"
    )


def test_unlisted_rows_are_kept_not_deleted(workspace):
    """Забыть настройку в списке можно, потерять её с экрана — нет."""
    body = workspace.split("function arrangeSettingsPanels")[1].split("function ")[0]

    assert "leftovers" in body, "остаток строк должен собираться, а не выбрасываться"
    assert body.index("leftovers") < body.index("first.remove()"), (
        "остаток надо забрать до удаления исходной карточки"
    )


def test_missing_element_does_not_break_the_screen(workspace):
    """Опечатка в списке не должна ронять сборку экрана целиком."""
    body = workspace.split("function arrangeSettingsPanels")[1].split("function ")[0]
    assert "?.closest" in body, "обращение к возможному null должно быть защищено"
