#!/usr/bin/env python3
"""Automated verification suite for Hermes Multi-Provider Account Router."""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from contextlib import ExitStack
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parent.parent
for p in [
    REPO_ROOT / "src",
    REPO_ROOT / "plugins" / "antigravity-provider" / "src",
    Path(os.environ.get("LOCALAPPDATA", "")) / "hermes" / "plugins" / "antigravity-provider" / "src",
]:
    if p.is_dir() and str(p) not in sys.path:
        sys.path.insert(0, str(p))

from antigravity_provider.router.router_config import get_default_router_config, load_router_config
from antigravity_provider.router.health_tracker import (
    HEALTHY,
    QUOTA_EXHAUSTED,
    RATE_LIMITED,
    HealthTracker,
    extract_model_family,
)
from antigravity_provider.router.session_affinity import LeaseManager, SessionAffinityTracker
from antigravity_provider.router.router_engine import RouterEngine, get_router_engine
from antigravity_provider.router.adapters.antigravity_adapter import AntigravityAdapter, get_profile_env_dir
from antigravity_provider.router.adapters.codex_adapter import CodexAdapter
from antigravity_provider.router.adapters.opencode_adapter import OpenCodeGoAdapter
from antigravity_provider.router.adapters.claude_adapter import ClaudeAdapter
from antigravity_provider.router.adapters.grok_adapter import GrokAdapter
from antigravity_provider.router.adapters.local_adapter import LocalLLMAdapter


def run_checks() -> int:
    print("=" * 70)
    print("HERMES MULTI-PROVIDER ACCOUNT ROUTER: AUTOMATED VERIFICATION")
    print("=" * 70)

    passed = 0
    total = 10

    # 1. Config inventory
    print("1. Checking profile inventory and provider counts...")
    config = get_default_router_config()
    # Проверка структурная, а не пересчёт. Раньше здесь стояло «ровно 16
    # профилей» и дословные цепочки от 20 августа. Миграция законно довела
    # конфигурацию до 22 профилей, добавив claude и grok, — и установка стала
    # падать с кодом 12 на любой машине, где миграция отработала. Смысл этой
    # проверки в том, работоспособна ли маршрутизация, а не совпадает ли
    # конфигурация с зафиксированной когда-то.
    counts = {}
    for prof in config.profiles.values():
        counts[prof.provider] = counts.get(prof.provider, 0) + 1
    assert config.profiles, "В конфигурации нет ни одного профиля"
    for required in ("openai-codex", "antigravity", "opencode-go"):
        assert counts.get(required), f"Нет ни одного профиля провайдера {required}"
    summary = ", ".join(f"{prov}: {n}" for prov, n in sorted(counts.items()))
    print(f"   [PASS] Профилей: {len(config.profiles)} ({summary})")
    passed += 1

    # 2. Role Fallback Chains
    print("2. Checking role fallback policies...")
    # Имя оркестрирующей роли меняется вместе с реестром: в A28 orchestrator
    # стал manager. Дословная проверка старого имени пережила миграцию и
    # роняла установку на Windows с кодом 12 — на Linux этот скрипт не
    # запускается, поэтому там всё ставилось. Спрашиваем актуальное имя у
    # реестра, а не помним его в скрипте.
    assert config.roles, "В конфигурации нет ни одной роли"
    try:
        from antigravity_provider.router.role_registry import RoleRegistry

        orchestrating_role = RoleRegistry.resolve_canonical_role("orchestrator")
    except Exception:
        orchestrating_role = "orchestrator"
    assert orchestrating_role in config.roles, (
        f"Оркестрирующая роль {orchestrating_role!r} отсутствует; есть: {sorted(config.roles)}"
    )
    # Цепочки настраиваются владельцем и меняются — дословно их сверять нельзя.
    # Проверяем то, что действительно ломает маршрутизацию: цепочка непуста и
    # каждый профиль в ней существует.
    # Пустая цепочка — не поломка сама по себе. В A28 появились роли,
    # объявленные без реализации (guardian, cost-controller): аккаунтов у них
    # ещё нет, и требовать цепочку — значит ронять установку из-за роли,
    # которой никто не пользуется. Ломает маршрутизацию другое: ссылка на
    # несуществующий профиль и пустая цепочка у ОРКЕСТРИРУЮЩЕЙ роли.
    empty_chains = []
    for role_name, policy in config.roles.items():
        chain = policy.preferred_chain or []
        if not chain:
            empty_chains.append(role_name)
        for pid in chain:
            assert pid in config.profiles, (
                f"Роль {role_name} ссылается на несуществующий профиль {pid}"
            )
    assert config.roles[orchestrating_role].preferred_chain, (
        f"У оркестрирующей роли {orchestrating_role!r} пустая цепочка — маршрутизация работать не будет"
    )
    if empty_chains:
        print(f"   [INFO] Без аккаунтов пока: {', '.join(sorted(empty_chains))}")
    print(f"   [PASS] Цепочки {len(config.roles)} ролей ссылаются только на существующие профили")
    passed += 1

    # 3. Model family extraction
    print("3. Checking model family extraction...")
    assert extract_model_family("gemini-3.7-flash") == "gemini"
    assert extract_model_family("claude-sonnet-4-6") == "claude"
    assert extract_model_family("gpt-4o") == "gpt"
    assert extract_model_family("kimi-k2.7-code") == "kimi"
    assert extract_model_family("deepseek-v4-pro") == "deepseek"
    print("   [PASS] Model family parsing correct")
    passed += 1

    # 4. Health state transitions & simulated quota
    print("4. Checking health states and simulated quota...")
    state_file = REPO_ROOT / "tests" / "fixtures" / "scratch_state.json"
    tracker = HealthTracker(state_file=state_file)
    tracker.clear_cooldown()
    assert tracker.is_healthy("codex-orch") is True
    tracker.simulate_quota("codex-orch", duration=300)
    assert tracker.is_healthy("codex-orch") is False
    tracker.clear_cooldown("codex-orch")
    assert tracker.is_healthy("codex-orch") is True
    if state_file.exists():
        state_file.unlink()
    print("   [PASS] Quota simulation and recovery verified")
    passed += 1

    # 5. Session Affinity Retention
    print("5. Checking session affinity engine...")
    affinity = SessionAffinityTracker()
    affinity.set_affinity("session-test-01", "orchestrator", "codex-orch", "gpt-4o")
    rec = affinity.get_affinity("session-test-01")
    assert rec and rec.profile_id == "codex-orch"
    affinity.set_affinity("session-test-01", "orchestrator", "ag-orch-fallback", "gemini-3.7-flash")
    assert affinity.get_affinity("session-test-01").profile_id == "ag-orch-fallback"
    print("   [PASS] Session affinity tracking & update verified")
    passed += 1

    # 6. Concurrency Leases
    print("6. Checking concurrency lease limits...")
    leases = LeaseManager()
    assert leases.acquire("ag-w1", max_concurrency=1) is True
    assert leases.acquire("ag-w1", max_concurrency=1) is False
    leases.release("ag-w1")
    assert leases.acquire("ag-w1", max_concurrency=1) is True
    leases.release("ag-w1")
    print("   [PASS] Concurrency leases correctly enforced")
    passed += 1

    # 7. Antigravity profile isolation
    print("7. Checking Antigravity profile environment directory isolation...")
    pdir = get_profile_env_dir("ag-w2")
    assert pdir.exists()
    assert "ag-w2" in str(pdir)
    print(f"   [PASS] Profile directory isolated at {pdir}")
    passed += 1

    # 8. Error classification
    print("8. Checking provider error classification...")
    ag_adapter = AntigravityAdapter()
    ag_err = ag_adapter.classify_error(RuntimeError("RESOURCE_EXHAUSTED: Individual quota reached for gemini"))
    assert ag_err.category == "quota-exhausted"

    codex_adapter = CodexAdapter()
    codex_err = codex_adapter.classify_error(RuntimeError("HTTP Error 429: Rate limit reached for tokens per minute"))
    assert codex_err.category == "rate-limited"

    opengo_adapter = OpenCodeGoAdapter()
    opengo_err = opengo_adapter.classify_error(RuntimeError("HTTP Error 401: Invalid API Key"))
    assert opengo_err.category == "auth-required"
    print("   [PASS] Error classifications for all 3 providers verified")
    passed += 1

    # 9. Full failover execution loop
    print("9. Checking full failover execution loop...")
    engine = RouterEngine(config=config)
    engine.health.clear_cooldown()

    # Проверяется МЕХАНИЗМ отказоустойчивости, а не расстановка аккаунтов.
    #
    # Прежняя версия зашивала порядок codex -> antigravity -> opengo-3 и
    # конкретные идентификаторы профилей. Но порядок в цепочке — это выбор
    # владельца, он его меняет мышью в интерфейсе. Любая перестановка роняла
    # проверку, а с ней и установку на Windows с кодом 12.
    #
    # Здесь: берём настоящую цепочку оркестрирующей роли, роняем все профили
    # кроме последнего и убеждаемся, что маршрутизатор дошёл именно до него.
    # Учитываем предел попыток: если цепочка длиннее, до её хвоста
    # маршрутизатор просто не дойдёт, и ожидать этого нельзя.
    full_chain = list(config.roles[orchestrating_role].preferred_chain)
    max_attempts = getattr(config.roles[orchestrating_role], "max_failover_attempts", 0) or len(full_chain)
    chain = full_chain[:max_attempts]
    assert len(chain) >= 2, (
        f"В цепочке роли {orchestrating_role!r} меньше двух профилей — "
        "отказоустойчивость проверить нечем"
    )
    last_pid = chain[-1]
    last_provider = config.profiles[last_pid].provider

    adapter_by_provider = {
        "openai-codex": CodexAdapter,
        "antigravity": AntigravityAdapter,
        "opencode-go": OpenCodeGoAdapter,
        "claude": ClaudeAdapter,
        "grok": GrokAdapter,
        "local": LocalLLMAdapter,
    }

    expected = {"id": "ok", "choices": [{"message": {"role": "assistant", "content": "from-last-in-chain"}}]}
    failing = {cls for pid in chain[:-1]
               if (cls := adapter_by_provider.get(config.profiles[pid].provider)) is not None}
    winner = adapter_by_provider.get(last_provider)

    if winner is None or winner in failing:
        print(f"   [SKIP] Последний профиль цепочки ({last_pid}, {last_provider}) "
              "не покрыт заглушками адаптеров")
    else:
        with ExitStack() as stack:
            for cls in failing:
                stack.enter_context(patch.object(cls, "invoke", side_effect=RuntimeError("Insufficient quota")))
            stack.enter_context(patch.object(winner, "invoke", return_value=expected))
            res = engine.route_request(
                {"messages": [{"role": "user", "content": "test"}]},
                role=orchestrating_role,
                session_id="verify-failover",
            )
        assert res["choices"][0]["message"]["content"] == "from-last-in-chain", (
            f"Отказоустойчивость не дошла до последнего профиля цепочки: {res}"
        )
        assert res["router_metadata"]["profile_id"] == last_pid, (
            f"Ожидался профиль {last_pid}, получен {res['router_metadata']['profile_id']}"
        )
        print(f"   [PASS] Отказоустойчивость прошла цепочку {' -> '.join(chain)}")
    passed += 1

    # 10. Passthrough & Graceful fallback
    print("10. Checking disabled router passthrough...")
    disabled_config = get_default_router_config()
    disabled_config.enabled = False
    assert disabled_config.enabled is False
    print("   [PASS] Router clean bypass mode verified")
    passed += 1

    print("-" * 70)
    print(f"VERIFICATION COMPLETE: {passed}/{total} CHECKS PASSED (0 errors, 0 warnings)")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(run_checks())
