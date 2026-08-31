"""Unit test suite for Task A52: Local Models, Supervisor, and Dual Coder Pipeline."""
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from antigravity_provider.router.dual_coder_pipeline import (
    DualCoderPipeline,
    DualCoderResult,
    JudgeVerdict,
)
from antigravity_provider.router.local_supervisor import (
    ContextExhaustedError,
    IndivisibleTaskError,
    LocalSupervisor,
    ModelMemoryRecord,
    ServerPropsResult,
    SupervisorOutcome,
    TokenCountResult,
)
from antigravity_provider.router.role_registry import CANONICAL_ROLES, RoleRegistry


# =====================================================================
# 1. Role Registry Tests (P0-4)
# =====================================================================
def test_role_registry_contains_local_supervisor():
    """Verify local-supervisor canonical role is properly defined in RoleRegistry."""
    assert "local-supervisor" in CANONICAL_ROLES
    role = RoleRegistry.get_role("local-supervisor")
    assert role is not None
    assert role.role_id == "local-supervisor"
    assert role.display_name_ru == "Надзиратель локальных моделей"
    assert role.tier == "governance"
    assert "task-splitter" in role.capabilities
    assert "token-counter" in role.capabilities
    assert "memory-tracker" in role.capabilities
    assert role.is_implemented is True


def test_role_registry_local_supervisor_aliases():
    """Verify all aliases resolve to local-supervisor."""
    for alias in ["local-supervisor", "local_supervisor", "надзиратель локальных моделей", "supervisor", "локальный надзиратель"]:
        assert RoleRegistry.resolve_canonical_role(alias) == "local-supervisor"


# =====================================================================
# 2. Local Supervisor Props & Token Counting Tests (P0-5)
# =====================================================================
def test_supervisor_query_props_success():
    supervisor = LocalSupervisor(base_url="http://mock-server:8081")
    fake_props_response = json.dumps({
        "default_generation_settings": {"n_ctx": 65536},
        "total_slots": 1,
        "model_path": "/srv/ai/models/qwen3-coder-30b-a3b/Qwen3-Coder-30B-A3B-Instruct-Q4_K_M.gguf",
    }).encode("utf-8")

    mock_resp = MagicMock()
    mock_resp.read.return_value = fake_props_response
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        res = supervisor.query_server_props()
        assert res.n_ctx == 65536
        assert res.total_slots == 1
        assert "Qwen3-Coder-30B" in res.model_name
        assert res.is_measured is True


def test_supervisor_query_props_offline_fallback():
    supervisor = LocalSupervisor(base_url="http://unreachable-host:8081")
    with patch("urllib.request.urlopen", side_effect=Exception("Connection refused")):
        res = supervisor.query_server_props()
        assert res.n_ctx == 65536
        assert res.is_measured is False


def test_supervisor_count_tokens_exact_via_api():
    supervisor = LocalSupervisor(base_url="http://mock-server:8081")
    fake_tok_response = json.dumps({
        "tokens": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    }).encode("utf-8")

    mock_resp = MagicMock()
    mock_resp.read.return_value = fake_tok_response
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        res = supervisor.count_tokens("def add(a, b): return a + b")
        assert res.tokens_count == 10
        assert res.is_estimated is False
        assert res.method == "tokenize_api"


def test_supervisor_count_tokens_fallback_heuristic():
    supervisor = LocalSupervisor(base_url="http://unreachable-host:8081")
    with patch("urllib.request.urlopen", side_effect=Exception("Timeout")):
        sample_text = "A" * 70
        res = supervisor.count_tokens(sample_text)
        assert res.is_estimated is True
        assert res.tokens_count == int(70 / 3.5)
        assert res.method == "char_heuristic"


# =====================================================================
# 3. Semantic Task Splitting Tests (P0-6)
# =====================================================================
def test_supervisor_split_task_fits_in_single_chunk():
    supervisor = LocalSupervisor()
    with patch.object(supervisor, "count_tokens", return_value=TokenCountResult(tokens_count=500, is_estimated=False, method="mock")):
        chunks = supervisor.split_task_semantically("def small_task(): pass", max_chunk_tokens=2000)
        assert len(chunks) == 1
        assert chunks[0] == "def small_task(): pass"


def test_supervisor_split_task_across_files():
    supervisor = LocalSupervisor()
    task = """--- file: a.py
def func_a():
    pass

--- file: b.py
def func_b():
    pass
"""
    def mock_count(text):
        if "a.py" in text and "b.py" in text:
            return TokenCountResult(tokens_count=250, is_estimated=False, method="mock")
        return TokenCountResult(tokens_count=80, is_estimated=False, method="mock")

    with patch.object(supervisor, "count_tokens", side_effect=mock_count):
        chunks = supervisor.split_task_semantically(task, max_chunk_tokens=150)
        assert len(chunks) == 2
        assert "a.py" in chunks[0]
        assert "b.py" in chunks[1]


def test_supervisor_split_task_across_functions():
    supervisor = LocalSupervisor()
    task = """class MyService:
    def method_one(self):
        print("1")

    def method_two(self):
        print("2")
"""
    def mock_count(text):
        if "method_one" in text and "method_two" in text:
            return TokenCountResult(tokens_count=200, is_estimated=False, method="mock")
        return TokenCountResult(tokens_count=40, is_estimated=False, method="mock")

    with patch.object(supervisor, "count_tokens", side_effect=mock_count):
        chunks = supervisor.split_task_semantically(task, max_chunk_tokens=100)
        assert len(chunks) >= 2


def test_supervisor_indivisible_task_raises_error():
    supervisor = LocalSupervisor()
    indivisible_giant_line = "x = " + ("1+" * 5000)
    with patch.object(supervisor, "count_tokens", return_value=TokenCountResult(tokens_count=10000, is_estimated=False, method="mock")):
        with pytest.raises(IndivisibleTaskError):
            supervisor.split_task_semantically(indivisible_giant_line, max_chunk_tokens=500)


# =====================================================================
# 4. Outcome & Reasoning Exhaustion (A39) Tests (P0-7)
# =====================================================================
def test_supervisor_detect_outcome_success():
    supervisor = LocalSupervisor()
    resp = {
        "choices": [{"message": {"content": "def add(a, b): return a + b"}}],
        "timings": {"predicted_n": 25},
    }
    outcome, desc = supervisor.detect_outcome(resp, elapsed_sec=2.5)
    assert outcome == SupervisorOutcome.SUCCESS
    assert "Успешно" in desc


def test_supervisor_detect_outcome_timeout():
    supervisor = LocalSupervisor()
    outcome, desc = supervisor.detect_outcome(None, error=TimeoutError("Request timed out"), elapsed_sec=185.0)
    assert outcome == SupervisorOutcome.TIMEOUT
    assert "Превышен таймаут" in desc


def test_supervisor_detect_outcome_a39_reasoning_exhaustion():
    supervisor = LocalSupervisor()
    # Case A39: content is empty or whitespace, but predicted_n > 50 or reasoning_content exists
    resp = {
        "choices": [{
            "message": {
                "content": "",
                "reasoning_content": "Let me think about how to write the adder function... wait..."
            },
            "finish_reason": "length"
        }],
        "timings": {"predicted_n": 1500},
    }
    outcome, desc = supervisor.detect_outcome(resp, elapsed_sec=45.0)
    assert outcome == SupervisorOutcome.REASONING_EXHAUSTED
    assert "A39" in desc
    assert "enable_thinking: false" in desc


# =====================================================================
# 5. AI-Memory Integration Tests (P0-8)
# =====================================================================
def test_supervisor_memory_tracking_roundtrip(tmp_path: Path):
    mem_file = tmp_path / "local_models_memory.json"
    supervisor = LocalSupervisor(memory_path=mem_file)

    rec1 = supervisor.record_working_volume(
        gguf_name="Qwen3-Coder-30B-A3B",
        prompt_tokens=16000,
        output_tokens=250,
        outcome=SupervisorOutcome.SUCCESS,
        speed_tps=110.5,
        task_id="T01",
    )
    assert rec1.successful_dispatches == 1
    assert rec1.safe_chunk_tokens == 16000
    assert rec1.avg_generation_tps > 100.0

    # Fetch from memory
    fetched = supervisor.get_model_memory("Qwen3-Coder-30B-A3B")
    assert fetched is not None
    assert fetched.last_working_context == 16000

    # Record failure -> safe chunk reduced
    rec2 = supervisor.record_working_volume(
        gguf_name="Qwen3-Coder-30B-A3B",
        prompt_tokens=48000,
        output_tokens=0,
        outcome=SupervisorOutcome.TIMEOUT,
        speed_tps=0.0,
        task_id="T02",
    )
    assert rec2.failed_dispatches == 1
    assert rec2.safe_chunk_tokens < 48000


# =====================================================================
# 6. Dual Coder Pipeline Tests (P0-9)
# =====================================================================
def test_dual_coder_pipeline_success_winner_a():
    coder_a = MagicMock(return_value={"content": "def solution_a(): return True", "tokens_generated": 40})
    coder_b = MagicMock(return_value={"content": "def solution_b(): return False", "tokens_generated": 45})
    judge = MagicMock(return_value={
        "verdict": "ACCEPTED_A",
        "commentary": "Solution A is correct and handles edge cases.",
        "tokens_consumed": 120,
    })

    pipeline = DualCoderPipeline(coder_a_fn=coder_a, coder_b_fn=coder_b, judge_fn=judge, max_rounds=3, enabled=True)
    result = pipeline.run_pipeline("Write boolean check", judge_model_name="claude-3-5-sonnet")

    assert result.success is True
    assert result.final_verdict == JudgeVerdict.ACCEPTED_A
    assert result.winning_coder == "coder-a"
    assert result.total_rounds == 1
    assert result.total_judge_calls == 1
    assert result.total_judge_tokens == 120
    assert "solution_a" in result.final_code


def test_dual_coder_pipeline_rework_then_winner_b():
    call_count = {"judge": 0}

    def mock_coder_a(prompt, feedback):
        return {"content": f"code_a_round_{call_count['judge']}", "tokens_generated": 30}

    def mock_coder_b(prompt, feedback):
        return {"content": f"code_b_round_{call_count['judge']}", "tokens_generated": 35}

    def mock_judge(prompt, code_a, code_b, model):
        call_count["judge"] += 1
        if call_count["judge"] == 1:
            return {
                "verdict": "REWORK_BOTH",
                "commentary": "Both missing docstrings.",
                "feedback_for_a": "Add docstring to A",
                "feedback_for_b": "Add docstring to B",
                "tokens_consumed": 100,
            }
        return {
            "verdict": "ACCEPTED_B",
            "commentary": "B added perfect docstrings.",
            "tokens_consumed": 110,
        }

    pipeline = DualCoderPipeline(coder_a_fn=mock_coder_a, coder_b_fn=mock_coder_b, judge_fn=mock_judge, max_rounds=3, enabled=True)
    result = pipeline.run_pipeline("Write function with docs")

    assert result.success is True
    assert result.final_verdict == JudgeVerdict.ACCEPTED_B
    assert result.winning_coder == "coder-b"
    assert result.total_rounds == 2
    assert result.total_judge_calls == 2
    assert result.total_judge_tokens == 210


def test_dual_coder_pipeline_stagnation_detection():
    # Both coders return identical unchanged code on round 2
    coder_a = MagicMock(return_value={"content": "unchanged_code_a", "tokens_generated": 20})
    coder_b = MagicMock(return_value={"content": "unchanged_code_b", "tokens_generated": 25})
    judge = MagicMock(return_value={"verdict": "REWORK_BOTH", "commentary": "Still broken", "tokens_consumed": 50})

    pipeline = DualCoderPipeline(coder_a_fn=coder_a, coder_b_fn=coder_b, judge_fn=judge, max_rounds=3, enabled=True)
    result = pipeline.run_pipeline("Fix algorithm")

    assert result.success is False
    assert result.final_verdict == JudgeVerdict.STAGNATION
    assert "Застревание" in result.failure_reason
    assert result.total_rounds == 2


def test_dual_coder_pipeline_rounds_exhausted():
    round_cnt = [0]
    def mock_a(prompt, fb):
        round_cnt[0] += 1
        return {"content": f"varying_code_a_step_{round_cnt[0]}", "tokens_generated": 20}

    def mock_b(prompt, fb):
        return {"content": f"varying_code_b_step_{round_cnt[0]}", "tokens_generated": 25}

    judge = lambda prompt, ca, cb, m: {"verdict": "REWORK_BOTH", "commentary": "Needs more work", "tokens_consumed": 50}

    pipeline = DualCoderPipeline(coder_a_fn=mock_a, coder_b_fn=mock_b, judge_fn=judge, max_rounds=3, enabled=True)
    result = pipeline.run_pipeline("Tough problem")

    assert result.success is False
    assert result.final_verdict == JudgeVerdict.ROUNDS_EXHAUSTED
    assert result.total_rounds == 3
    assert result.total_judge_calls == 3
    assert result.total_judge_tokens == 150
