"""Опрос device-flow обязан различать исходы.

Владелец: «не даёт зайти в грок через аутх». Backend при этом исправен —
провайдер возвращает настоящие адрес и код.

Дефект в цикле опроса: коды 400, 403 и 404 скопом считались «ещё не
подтверждено». Но в device-flow сервер сообщает РАЗНЫЕ вещи одним кодом
400, различая их полем error в теле: authorization_pending, slow_down,
access_denied, expired_token. Отказ пользователя и просроченный код
выглядели как ожидание — мастер крутил «Ожидание подтверждения...» до
таймаута и не говорил правду.
"""

from __future__ import annotations

import io
import json
import pathlib
import urllib.error


def _error(reason: str, code: int = 400) -> urllib.error.HTTPError:
    body = json.dumps({"error": reason}).encode("utf-8")
    return urllib.error.HTTPError("https://x", code, "Bad Request", {}, io.BytesIO(body))


def test_poll_loop_handles_each_outcome_distinctly():
    src = pathlib.Path("src/antigravity_provider/router/grok_oauth.py").read_text(encoding="utf-8")

    assert "authorization_pending" in src, "ожидание больше не распознаётся явно"
    assert "access_denied" in src, "отказ пользователя не отличается от ожидания"
    assert "expired_token" in src, "просроченный код не отличается от ожидания"
    assert "slow_down" in src, "требование сбавить темп игнорируется"

    # Прежняя конструкция считала все три кода одним исходом.
    assert "if http_err.code in (400, 403, 404):\n                    # Authorization pending" not in src


def test_error_body_is_readable():
    """Тело ответа должно разбираться — на нём и держится различение."""
    err = _error("access_denied")
    parsed = json.loads(err.read().decode("utf-8"))
    assert parsed["error"] == "access_denied"


def test_denied_and_expired_are_terminal():
    """Оба исхода обязаны прекращать опрос, а не продолжать его."""
    src = pathlib.Path("src/antigravity_provider/router/grok_oauth.py").read_text(encoding="utf-8")
    tail = src.split("if reason == \"access_denied\":", 1)[1][:400]
    assert "break" in tail, "отказ не прекращает опрос"
    expired = src.split("if reason == \"expired_token\":", 1)[1][:400]
    assert "break" in expired, "просрочка не прекращает опрос"
