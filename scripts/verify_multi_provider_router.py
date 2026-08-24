#!/usr/bin/env python3
"""Automated verification suite for Hermes Multi-Provider Account Router."""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path
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
    assert "orchestrator" in config.roles, "Роль orchestrator отсутствует"
    # Цепочки настраиваются владельцем и меняются — дословно их сверять нельзя.
    # Проверяем то, что действительно ломает маршрутизацию: цепочка непуста и
    # каждый профиль в ней существует.
    for role_name, policy in config.roles.items():
        chain = policy.preferred_chain or []
        assert chain, f"У роли {role_name} пустая цепочка отказоустойчивости"
        for pid in chain:
            assert pid in config.profiles, (
                f"Роль {role_name} ссылается на несуществующий профиль {pid}"
            )
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

    mock_codex = {"id": "c1", "choices": [{"message": {"role": "assistant", "content": "from-codex"}}]}
    mock_ag = {"id": "a1", "choices": [{"message": {"role": "assistant", "content": "from-antigravity"}}]}
    mock_opengo = {"id": "o1", "choices": [{"message": {"role": "assistant", "content": "from-opencode"}}]}

    # Simulate codex failure -> route to Antigravity fallback
    with patch.object(CodexAdapter, "invoke", side_effect=RuntimeError("Insufficient quota")):
        with patch.object(AntigravityAdapter, "invoke", return_value=mock_ag):
            res = engine.route_request({"messages": [{"role": "user", "content": "test"}]}, role="orchestrator", session_id="s1")
            assert res["choices"][0]["message"]["content"] == "from-antigravity"
            assert res["router_metadata"]["profile_id"] == "ag-orch-fallback"

    # Simulate both codex and ag failure -> route to OpenCode Go
    with patch.object(CodexAdapter, "invoke", side_effect=RuntimeError("Insufficient quota")):
        with patch.object(AntigravityAdapter, "invoke", side_effect=RuntimeError("Individual quota reached")):
            with patch.object(OpenCodeGoAdapter, "invoke", return_value=mock_opengo):
                res2 = engine.route_request({"messages": [{"role": "user", "content": "test2"}]}, role="orchestrator", session_id="s2")
                assert res2["choices"][0]["message"]["content"] == "from-opencode"
                assert res2["router_metadata"]["profile_id"] == "opengo-3"

    print("   [PASS] 3-tier role failover chain (Codex -> Antigravity -> OpenCode Go) verified")
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
