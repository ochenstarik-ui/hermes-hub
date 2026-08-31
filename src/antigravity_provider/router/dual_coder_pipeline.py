"""Hermes Hub Dual Coder Pipeline with Cloud Judge (Пара кодеров и облачный судья).

Implements P0-9 for Task A52:
- Independent generation by Coder A (developer-1) and Coder B (local secondary)
- Review and verdict by Cloud Judge (developer-2 / configurable model)
- Iteration limit control (max_rounds / max_iterations)
- Stagnation detection (round with identical code outputs)
- Judge call expenditure tracking and metrics
- Safe toggle via router configuration
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class JudgeVerdict(str, Enum):
    ACCEPTED_A = "ACCEPTED_A"
    ACCEPTED_B = "ACCEPTED_B"
    REWORK_BOTH = "REWORK_BOTH"
    STAGNATION = "STAGNATION"
    ROUNDS_EXHAUSTED = "ROUNDS_EXHAUSTED"


@dataclass
class CoderAttempt:
    round_index: int
    coder_id: str
    solution_code: str
    tokens_generated: int
    elapsed_sec: float
    feedback_received: str = ""
    error: Optional[str] = None


@dataclass
class JudgeEvaluation:
    round_index: int
    verdict: JudgeVerdict
    chosen_coder: Optional[str]
    judge_commentary: str
    feedback_for_a: str
    feedback_for_b: str
    judge_model_used: str
    judge_tokens_consumed: int
    elapsed_sec: float


@dataclass
class DualCoderResult:
    success: bool
    final_verdict: JudgeVerdict
    winning_coder: Optional[str]
    final_code: str
    total_rounds: int
    total_judge_calls: int
    total_judge_tokens: int
    total_coder_tokens: int
    total_wall_time_sec: float
    history: List[Dict[str, Any]] = field(default_factory=list)
    failure_reason: Optional[str] = None


class DualCoderPipeline:
    """Orchestrates independent dual-coder problem solving with cloud judge synthesis."""

    DEFAULT_MAX_ROUNDS: int = 3

    def __init__(
        self,
        coder_a_fn: Callable[[str, str], Dict[str, Any]],
        coder_b_fn: Callable[[str, str], Dict[str, Any]],
        judge_fn: Callable[[str, str, str, str], Dict[str, Any]],
        max_rounds: int = DEFAULT_MAX_ROUNDS,
        enabled: bool = False,
    ):
        self.coder_a_fn = coder_a_fn
        self.coder_b_fn = coder_b_fn
        self.judge_fn = judge_fn
        self.max_rounds = max_rounds
        self.enabled = enabled

    def _hash_solution(self, text: str) -> str:
        """Compute SHA-256 fingerprint of normalized solution text."""
        normalized = "\n".join(line.rstrip() for line in text.strip().splitlines())
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    def run_pipeline(
        self,
        task_prompt: str,
        judge_model_name: str = "cloud-judge",
    ) -> DualCoderResult:
        """Execute iterative dual-coder tournament until resolution, stagnation, or round exhaustion."""
        t0 = time.monotonic()

        history: List[Dict[str, Any]] = []
        feedback_a = ""
        feedback_b = ""

        prev_hash_a = ""
        prev_hash_b = ""

        total_judge_calls = 0
        total_judge_tokens = 0
        total_coder_tokens = 0

        last_code_a = ""
        last_code_b = ""
        last_judge_commentary = ""

        for round_idx in range(1, self.max_rounds + 1):
            logger.info("Starting Dual-Coder Tournament Round %d / %d", round_idx, self.max_rounds)

            # 1. Independent Coder A generation
            t_ca = time.monotonic()
            try:
                res_a = self.coder_a_fn(task_prompt, feedback_a)
                code_a = res_a.get("content", "")
                tokens_a = res_a.get("tokens_generated", 0)
                err_a = None
            except Exception as e:
                code_a = ""
                tokens_a = 0
                err_a = str(e)
            elapsed_ca = time.monotonic() - t_ca

            # 2. Independent Coder B generation
            t_cb = time.monotonic()
            try:
                res_b = self.coder_b_fn(task_prompt, feedback_b)
                code_b = res_b.get("content", "")
                tokens_b = res_b.get("tokens_generated", 0)
                err_b = None
            except Exception as e:
                code_b = ""
                tokens_b = 0
                err_b = str(e)
            elapsed_cb = time.monotonic() - t_cb

            total_coder_tokens += (tokens_a + tokens_b)
            last_code_a = code_a
            last_code_b = code_b

            hash_a = self._hash_solution(code_a)
            hash_b = self._hash_solution(code_b)

            # Check Stagnation (both returned identical code as previous round)
            if round_idx > 1 and hash_a == prev_hash_a and hash_b == prev_hash_b:
                logger.warning("Stagnation detected in round %d: both coders repeated previous responses", round_idx)
                return DualCoderResult(
                    success=False,
                    final_verdict=JudgeVerdict.STAGNATION,
                    winning_coder=None,
                    final_code=code_a or code_b,
                    total_rounds=round_idx,
                    total_judge_calls=total_judge_calls,
                    total_judge_tokens=total_judge_tokens,
                    total_coder_tokens=total_coder_tokens,
                    total_wall_time_sec=round(time.monotonic() - t0, 3),
                    history=history,
                    failure_reason="Застревание: оба кодера вернули идентичный код без учета правок судьи.",
                )

            prev_hash_a = hash_a
            prev_hash_b = hash_b

            # 3. Call Cloud Judge
            t_judge = time.monotonic()
            total_judge_calls += 1
            try:
                judge_res = self.judge_fn(task_prompt, code_a, code_b, judge_model_name)
                verdict_str = judge_res.get("verdict", "REWORK_BOTH").upper()
                verdict = JudgeVerdict(verdict_str) if verdict_str in JudgeVerdict.__members__ else JudgeVerdict.REWORK_BOTH
                judge_comm = judge_res.get("commentary", "")
                fb_a = judge_res.get("feedback_for_a", "")
                fb_b = judge_res.get("feedback_for_b", "")
                j_tokens = judge_res.get("tokens_consumed", 0)
            except Exception as e:
                logger.error("Cloud judge call failed in round %d: %s", round_idx, e)
                verdict = JudgeVerdict.REWORK_BOTH
                judge_comm = f"Ошибка вызова судьи: {e}"
                fb_a = "Повторите попытку реализации"
                fb_b = "Повторите попытку реализации"
                j_tokens = 0

            elapsed_judge = time.monotonic() - t_judge
            total_judge_tokens += j_tokens
            last_judge_commentary = judge_comm

            round_record = {
                "round": round_idx,
                "coder_a": {"tokens": tokens_a, "elapsed_sec": round(elapsed_ca, 2), "error": err_a},
                "coder_b": {"tokens": tokens_b, "elapsed_sec": round(elapsed_cb, 2), "error": err_b},
                "judge": {
                    "verdict": verdict.value,
                    "model": judge_model_name,
                    "tokens": j_tokens,
                    "elapsed_sec": round(elapsed_judge, 2),
                    "commentary": judge_comm,
                }
            }
            history.append(round_record)

            if verdict == JudgeVerdict.ACCEPTED_A:
                return DualCoderResult(
                    success=True,
                    final_verdict=JudgeVerdict.ACCEPTED_A,
                    winning_coder="coder-a",
                    final_code=code_a,
                    total_rounds=round_idx,
                    total_judge_calls=total_judge_calls,
                    total_judge_tokens=total_judge_tokens,
                    total_coder_tokens=total_coder_tokens,
                    total_wall_time_sec=round(time.monotonic() - t0, 3),
                    history=history,
                )
            elif verdict == JudgeVerdict.ACCEPTED_B:
                return DualCoderResult(
                    success=True,
                    final_verdict=JudgeVerdict.ACCEPTED_B,
                    winning_coder="coder-b",
                    final_code=code_b,
                    total_rounds=round_idx,
                    total_judge_calls=total_judge_calls,
                    total_judge_tokens=total_judge_tokens,
                    total_coder_tokens=total_coder_tokens,
                    total_wall_time_sec=round(time.monotonic() - t0, 3),
                    history=history,
                )

            # Rework requested
            feedback_a = fb_a
            feedback_b = fb_b

        # Exhausted max rounds
        return DualCoderResult(
            success=False,
            final_verdict=JudgeVerdict.ROUNDS_EXHAUSTED,
            winning_coder=None,
            final_code=last_code_a or last_code_b,
            total_rounds=self.max_rounds,
            total_judge_calls=total_judge_calls,
            total_judge_tokens=total_judge_tokens,
            total_coder_tokens=total_coder_tokens,
            total_wall_time_sec=round(time.monotonic() - t0, 3),
            history=history,
            failure_reason=(
                f"Исчерпан лимит кругов доработки ({self.max_rounds}). "
                f"Последний вердикт судьи: {last_judge_commentary}"
            ),
        )
