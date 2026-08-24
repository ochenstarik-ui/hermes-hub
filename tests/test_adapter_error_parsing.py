"""Обработчик ошибок не должен падать сам.

Найдено на живом Grok владельца: поле ``error`` пришло строкой, а код
безусловно звал у результата ``.get``. Обработчик падал с AttributeError,
настоящая причина (403, токен не проходит проверку) терялась, и
маршрутизация обрывалась вместо перехода к резерву — сбой ровно там, где
обрабатывался другой сбой.

Та же конструкция стояла ещё в пяти адаптерах.
"""

from __future__ import annotations

import json

import pytest

from antigravity_provider.router.adapters.base_adapter import extract_api_error_message


@pytest.mark.parametrize(
    "raw,expected_fragment",
    [
        (json.dumps({"error": {"message": "quota exceeded"}}), "quota exceeded"),
        (json.dumps({"error": "The OAuth2 access token could not be validated."}), "OAuth2"),
        # Без поля error возвращается сырой ответ целиком — это правильно:
        # лучше отдать всё, что прислал провайдер, чем потерять причину.
        (json.dumps({"detail": "boom"}), "boom"),
        ("<html>502 Bad Gateway</html>", "502"),
        ("", ""),
    ],
)
def test_error_message_extracted_from_any_shape(raw, expected_fragment):
    """Строковая и объектная формы разбираются одинаково спокойно."""
    assert expected_fragment in extract_api_error_message(raw)


def test_string_error_does_not_raise():
    """Именно эта форма роняла обработчик у Grok."""
    result = extract_api_error_message(json.dumps({"error": "plain string"}))
    assert result == "plain string"


def test_all_adapters_use_shared_parser():
    """Копии хрупкой конструкции не должны вернуться."""
    import pathlib

    adapters = pathlib.Path("src/antigravity_provider/router/adapters")
    offenders = [
        f.name
        for f in adapters.glob("*_adapter.py")
        if '.get("error", {}).get(' in f.read_text(encoding="utf-8")
    ]
    assert not offenders, f"хрупкий разбор ошибки вернулся в: {offenders}"
