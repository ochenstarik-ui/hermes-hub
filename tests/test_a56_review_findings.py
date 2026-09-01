"""Проверки по итогам разбора A56 ревьюером.

Три находки, каждая подтверждена измерением на сервере владельца:

1. `/props` и `/tokenize` у llama.cpp живут в корне, а не под `/v1`.
   Измерено: `/props` → 200, `/v1/props` → 404; то же с `/tokenize`.
   Адаптер передаёт супервизору адрес вида `.../v1`, поэтому счёт токенов
   молча падал на посимвольную оценку, и порог сжатия считался от выдуманного
   числа.

2. Заявленные «100% сохранения фактов» модель не даёт. Измерено на живом
   компрессоре: 5667 токенов на входе, 624 на выходе, 37 фактов из 38 —
   97,4%, потерян `001cd1f`. Сто процентов получаются дописыванием
   недостающих фактов списком. Механизм верный, но подменять им измеренное
   число нельзя: иначе ухудшение модели останется незамеченным.

3. Порт 8082 был зашит в коде как запасной адрес. Задание это прямо
   запрещает: сегодня он такой, завтра другой.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from antigravity_provider.router.context_compressor import (
    CompressionOutcome,
    ContextCompressor,
)
from antigravity_provider.router.local_supervisor import LocalSupervisor


# ── Находка 1: адрес /props и /tokenize ──

@pytest.mark.unit
@pytest.mark.parametrize(
    "given, expected_root",
    [
        ("http://127.0.0.1:8081/v1", "http://127.0.0.1:8081"),
        ("http://127.0.0.1:8081/v1/", "http://127.0.0.1:8081"),
        ("http://127.0.0.1:8081", "http://127.0.0.1:8081"),
        ("http://server.local:9000/v1", "http://server.local:9000"),
    ],
)
def test_props_and_tokenize_go_to_the_root(given, expected_root):
    assert LocalSupervisor(base_url=given).root_url == expected_root


@pytest.mark.unit
def test_tokenize_request_url_has_no_v1():
    supervisor = LocalSupervisor(base_url="http://127.0.0.1:8081/v1")
    seen = {}

    def _fake_urlopen(req, timeout=None):
        seen["url"] = req.full_url
        raise RuntimeError("сеть в тесте недоступна")

    with patch("urllib.request.urlopen", _fake_urlopen):
        supervisor.count_tokens("проверка")

    assert seen["url"] == "http://127.0.0.1:8081/tokenize"


@pytest.mark.unit
def test_props_request_url_has_no_v1():
    supervisor = LocalSupervisor(base_url="http://127.0.0.1:8081/v1")
    seen = {}

    def _fake_urlopen(req, timeout=None):
        seen["url"] = req.full_url
        raise RuntimeError("сеть в тесте недоступна")

    with patch("urllib.request.urlopen", _fake_urlopen):
        supervisor.query_server_props()

    assert seen["url"] == "http://127.0.0.1:8081/props"


@pytest.mark.unit
def test_unmeasured_limit_is_marked_as_such():
    """Недоступный /props даёт запасное значение — и оно обязано быть помечено."""
    supervisor = LocalSupervisor(base_url="http://127.0.0.1:8081/v1")

    def _fake_urlopen(req, timeout=None):
        raise RuntimeError("сервер не отвечает")

    with patch("urllib.request.urlopen", _fake_urlopen):
        result = supervisor.query_server_props()

    assert result.is_measured is False


# ── Находка 2: полнота фактов не подменяется исправленной ──

class _Profile:
    custom_base_url = "http://127.0.0.1:9999/v1"
    preferred_models = ["compressor"]
    auth_config: dict = {}


def _compress_with_summary(summary: str):
    payload = {"choices": [{"message": {"content": summary}}], "model": "test-gguf"}

    class _Resp:
        def read(self):
            import json

            return json.dumps(payload).encode()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    messages = [
        {"role": "system", "content": "система"},
        {"role": "user", "content": "Правка в коммите 001cd1f, порт 8082, файл /srv/app/main.py"},
        {"role": "assistant", "content": "Скорость 107.4 tok/s на версии v0.1.3"},
        {"role": "user", "content": "свежее 1"},
        {"role": "user", "content": "свежее 2"},
        {"role": "user", "content": "свежее 3"},
    ]
    compressor = ContextCompressor()
    with patch("urllib.request.urlopen", return_value=_Resp()), \
         patch.object(ContextCompressor, "_record_to_shared_memory", lambda self, o: None):
        _, outcome = compressor.compress_messages_if_needed(
            messages=messages,
            target_context_limit=1000,
            current_token_count=900,
            compressor_profile=_Profile(),
        )
    return outcome


@pytest.mark.unit
def test_model_retention_is_reported_separately_when_facts_were_added():
    # Сводка намеренно теряет часть фактов — их дописывает страховка.
    outcome = _compress_with_summary("Кратко: правка внесена, порт 8082.")

    assert outcome.status == "SUCCESS"
    assert outcome.facts_added_by_safeguard, "страховка обязана была сработать"
    assert outcome.model_retention_percent < 100.0
    assert outcome.retention_percent == pytest.approx(100.0)
    assert "дописано списком" in outcome.status_message
    assert f"{outcome.model_retention_percent:.1f}%" in outcome.status_message


@pytest.mark.unit
def test_full_model_retention_is_stated_as_the_model_s_own():
    summary = "Коммит 001cd1f, порт 8082, файл /srv/app/main.py, 107.4 tok/s, v0.1.3"
    outcome = _compress_with_summary(summary)

    assert not outcome.facts_added_by_safeguard
    assert outcome.model_retention_percent == pytest.approx(100.0)
    assert "самой моделью" in outcome.status_message


@pytest.mark.unit
def test_status_message_never_hardcodes_a_hundred_percent():
    import inspect

    from antigravity_provider.router import context_compressor

    source = inspect.getsource(context_compressor)
    assert "(100%)." not in source, "полнота обязана браться из замера, а не из строки"


# ── Находка 3: порт компрессора не зашит ──

@pytest.mark.unit
def test_compressor_port_is_not_hardcoded():
    import inspect

    from antigravity_provider.router import context_compressor

    code_lines = [
        line
        for line in inspect.getsource(context_compressor).splitlines()
        if not line.lstrip().startswith("#")
    ]
    assert not any("127.0.0.1:8082" in line for line in code_lines)


@pytest.mark.unit
def test_profile_without_address_is_unconfigured_not_port_8082(monkeypatch):
    monkeypatch.delenv("LOCAL_COMPRESSOR_BASE_URL", raising=False)

    class _NoAddress:
        custom_base_url = None
        preferred_models: list = []
        auth_config: dict = {}

    _, outcome = ContextCompressor().compress_messages_if_needed(
        messages=[{"role": "user", "content": "x"}],
        target_context_limit=1000,
        current_token_count=900,
        compressor_profile=_NoAddress(),
    )

    assert outcome.status == "UNCONFIGURED"
    assert "адрес" in outcome.status_message


# ── Итог сжатия пересчитывается токенизатором ──

@pytest.mark.unit
def test_result_size_is_recounted_by_the_tokenizer():
    supervisor = LocalSupervisor(base_url="http://127.0.0.1:8081/v1")
    outcome = CompressionOutcome(
        status="SUCCESS", status_message="", tokens_before=900, tokens_after=1
    )

    with patch.object(
        ContextCompressor,
        "compress_messages_if_needed",
        return_value=([{"role": "user", "content": "сводка"}], outcome),
    ), patch.object(
        LocalSupervisor,
        "count_tokens",
        side_effect=[
            type("T", (), {"tokens_count": 900, "is_estimated": False})(),
            type("T", (), {"tokens_count": 120, "is_estimated": False})(),
        ],
    ):
        _, result = supervisor.compress_context_if_needed(
            messages=[{"role": "user", "content": "длинная история"}],
            target_context_limit=1000,
        )

    assert result.tokens_after == 120
    assert result.tokens_after_is_estimate is False
    assert result.saved_tokens == 780
