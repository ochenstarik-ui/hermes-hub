"""Кнопка удаления обязана удалять — и говорить правду, если удалять нечего.

Владелец подключил не тот аккаунт Grok и не смог его убрать: «кнопка не
функционирует». Хуже — действие возвращало ok=True с сообщением об
успехе, а профиль оставался авторизованным.

Причина: сигнатура get_profile_dir — (profile_id, provider), а
do_delete_credentials звала её наоборот. Внутри есть костыль, молча
исправляющий перестановку, но только для antigravity, openai-codex и
opencode-go. Для grok, claude и local путь получался неверным, файл «не
находился», и удаление рапортовало успех, ничего не сделав.
"""

from __future__ import annotations

import json

import pytest

from antigravity_provider.router.action_handler import do_delete_credentials
from antigravity_provider.router.profile_manager import get_profile_auth_path


@pytest.mark.parametrize("provider,profile_id", [
    ("grok", "grok-worker-2"),
    ("claude", "claude-worker-1"),
    ("local", "local-2"),
    ("antigravity", "ag-spare-2"),
])
def test_delete_removes_credentials_for_every_provider(provider, profile_id, monkeypatch, tmp_path):
    """Удаление обязано работать у всех провайдеров, а не у трёх из шести."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))

    auth_path = get_profile_auth_path(provider, profile_id)
    auth_path.parent.mkdir(parents=True, exist_ok=True)
    auth_path.write_text(json.dumps({"api_key": "secret"}), encoding="utf-8")
    assert auth_path.is_file()

    ok, msg = do_delete_credentials(provider, profile_id)

    assert ok, f"{provider}: удаление отчиталось об отказе — {msg}"
    assert not auth_path.is_file(), f"{provider}: файл остался на диске, а действие сообщило успех"


def test_missing_credentials_reported_as_failure(monkeypatch, tmp_path):
    """Отсутствие файла — не успех удаления.

    Раньше такой ответ выглядел для пользователя как «сработало», хотя
    аккаунт оставался подключённым.
    """
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))

    ok, msg = do_delete_credentials("grok", "grok-worker-2")

    assert ok is False
    assert "нечего" in msg or "не найдено" in msg
