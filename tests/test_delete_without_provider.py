"""Удаление должно работать, когда провайдер не передан.

Владелец: «удалить так и не могу ненужный». Backend был уже починен, но
веб-клиент отправлял только profile_id, без provider. Сервер не знал, в
каком каталоге искать файл, и снова отвечал «удалять нечего» — кнопка
по-прежнему выглядела неработающей.

Идентификатор профиля однозначен, поэтому провайдер берётся из
конфигурации, и действие работает независимо от того, кто его вызвал.
"""

from __future__ import annotations

import json

import pytest

from antigravity_provider.router.action_handler import ActionExecutor
from antigravity_provider.router.profile_manager import get_profile_auth_path


@pytest.mark.parametrize("profile_id,provider", [
    ("grok-worker-2", "grok"),
    ("ag-spare-2", "antigravity"),
    ("opengo-2", "opencode-go"),
])
def test_delete_works_without_provider_argument(profile_id, provider, monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))

    auth_path = get_profile_auth_path(provider, profile_id)
    auth_path.parent.mkdir(parents=True, exist_ok=True)
    auth_path.write_text(json.dumps({"api_key": "x"}), encoding="utf-8")

    # Ровно то, что шлёт веб-клиент: без provider.
    result = ActionExecutor().execute("delete_credentials", {"profile_id": profile_id})

    assert result.get("ok"), f"{profile_id}: {result.get('message')}"
    assert not auth_path.is_file(), f"{profile_id}: файл остался, а действие отчиталось об успехе"


def test_client_confirms_before_deleting():
    """Необратимое действие обязано спрашивать подтверждение."""
    import pathlib

    app_js = pathlib.Path(
        "src/antigravity_provider/router/web/static/app.js"
    ).read_text(encoding="utf-8")

    assert "handleDeleteCredentials" in app_js
    block = app_js.split("function handleDeleteCredentials", 1)[1][:600]
    assert "confirm(" in block, "удаление выполняется без подтверждения"
    assert "fetchSnapshot" in block, "экран не обновляется после удаления"
