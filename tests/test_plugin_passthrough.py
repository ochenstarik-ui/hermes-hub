"""Плагин не должен делать Hermes хуже, чем без него.

Hermes вызывает Hub как middleware `llm_execution` на каждом обращении к
модели, но **роль не передаёт** — в kwargs есть model, provider, session_id,
task_id, а `role` нет. Роутер поэтому сваливается в роль по умолчанию
(`orchestrator`), и если её цепочка исчерпана, раньше он возвращал текст
«⚠️ Hermes Router Failover Exhausted» как ответ ассистента. Пользователь
видел это вместо ответа модели, хотя собственный провайдер Hermes работал.
"""

from __future__ import annotations

from typing import Any, Dict

import pytest

from antigravity_provider import hermes_plugin


class _ExhaustedEngine:
    class config:
        enabled = True

    def route_request(self, request: Dict[str, Any], role: Any = None, session_id: Any = None) -> Dict[str, Any]:
        return {
            "id": "router-fail-1",
            "model": "router-failover",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "⚠️ Hermes Router Failover Exhausted"},
                    "finish_reason": "error",
                }
            ],
            "router_error": True,
            "failover_trail": [{"profile_id": "codex-orch", "status": "failed"}],
        }


@pytest.fixture
def exhausted_router(monkeypatch):
    monkeypatch.setattr(hermes_plugin, "get_router_engine", lambda: _ExhaustedEngine(), raising=False)
    import antigravity_provider.router as router_pkg

    monkeypatch.setattr(router_pkg, "get_router_engine", lambda: _ExhaustedEngine())


def test_exhausted_failover_passes_call_downstream(exhausted_router):
    downstream_calls = []

    def next_call(payload=None):
        downstream_calls.append(payload)
        return {
            "choices": [
                {"index": 0, "message": {"role": "assistant", "content": "настоящий ответ"}, "finish_reason": "stop"}
            ]
        }

    result = hermes_plugin.antigravity_llm_execution(
        request={"messages": [{"role": "user", "content": "ping"}]},
        next_call=next_call,
        provider="gemini",
        model="gemini-3.7-flash",
        session_id="s1",
    )

    assert len(downstream_calls) == 1, "отказ роутера обязан уходить вниз по цепочке, а не подменять ответ"
    content = result["choices"][0]["message"]["content"]
    assert content == "настоящий ответ"
    assert "Failover Exhausted" not in content
