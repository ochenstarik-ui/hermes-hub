"""Пустой ответ локальной модели — отказ, а не успех.

Сервер владельца поднят с ``--reasoning on --reasoning-budget 4096``. При
скромном ``max_tokens`` весь бюджет уходит на рассуждения: llama.cpp
возвращает 200, заполняет ``reasoning_content`` и оставляет ``content``
пустым. Проверено на живой модели через SSH-туннель: с max_tokens=40
ответа нет, с 200 приходит «ОК».

Если отдать такой ответ дальше как успешный, роутер засчитает вызов, а
пользователь не получит ничего и не узнает почему.
"""

from __future__ import annotations

import pytest

from antigravity_provider.router.adapters.local_adapter import LocalLLMAdapter


def test_answer_with_content_passes():
    data = {
        "choices": [
            {"index": 0, "message": {"role": "assistant", "content": "ОК"}, "finish_reason": "stop"}
        ]
    }
    LocalLLMAdapter._reject_empty_answer(data)  # не должно бросать


def test_reasoning_ate_the_budget_is_rejected():
    data = {
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "", "reasoning_content": "долгие раздумья"},
                "finish_reason": "length",
            }
        ]
    }
    with pytest.raises(RuntimeError, match="рассужд"):
        LocalLLMAdapter._reject_empty_answer(data)


def test_empty_choices_is_rejected():
    with pytest.raises(RuntimeError, match="choices"):
        LocalLLMAdapter._reject_empty_answer({"choices": []})


def test_blank_content_without_reasoning_is_rejected():
    data = {"choices": [{"index": 0, "message": {"content": "   "}, "finish_reason": "stop"}]}
    with pytest.raises(RuntimeError, match="пустой"):
        LocalLLMAdapter._reject_empty_answer(data)
