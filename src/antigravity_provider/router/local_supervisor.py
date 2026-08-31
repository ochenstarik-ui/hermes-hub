"""Hermes Hub Local Model Supervisor (Надзиратель локальных моделей).

Implements P0-4, P0-5, P0-6, P0-7, P0-8 for Task A52:
- P0-4: Automated supervisor role for local providers (local, llama.cpp, ollama, vllm)
- P0-5: Measured context limits via /props and exact token counting via /tokenize
- P0-6: Semantic task splitting across file/class/function boundaries with sequential delivery
- P0-7: Execution monitoring, distinguishing SUCCESS, TIMEOUT, ERROR, and REASONING_EXHAUSTED (A39)
- P0-8: Shared memory tracking in AI-Memory by GGUF build metadata
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

SHARED_MEMORY_VAULT = Path("/srv/projects/AI-Memory")
LOCAL_MEMORY_FILE = SHARED_MEMORY_VAULT / "01_PROJECTS" / "hermes-hub" / "local_models_memory.json"


class SupervisorOutcome(str, Enum):
    SUCCESS = "SUCCESS"
    TIMEOUT = "TIMEOUT"
    ERROR = "ERROR"
    REASONING_EXHAUSTED = "REASONING_EXHAUSTED"


class IndivisibleTaskError(Exception):
    """Raised when a single code block cannot be semantically split and exceeds model context."""
    pass


class ContextExhaustedError(Exception):
    """Raised when maximum split retries are exhausted without successful generation."""
    pass


@dataclass
class TokenCountResult:
    tokens_count: int
    is_estimated: bool
    method: str  # "tokenize_api" or "char_heuristic"


@dataclass
class ServerPropsResult:
    n_ctx: int
    total_slots: int
    model_name: str
    model_path: str
    is_measured: bool


@dataclass
class ModelMemoryRecord:
    gguf_name: str
    safe_chunk_tokens: int
    max_tested_tokens: int
    successful_dispatches: int
    failed_dispatches: int
    last_working_context: int
    avg_generation_tps: float
    last_updated: str
    history: List[Dict[str, Any]] = field(default_factory=list)


class LocalSupervisor:
    """Oversees and regulates work dispatch to local models."""

    DEFAULT_SAFETY_MARGIN_TOKENS: int = 1024
    DEFAULT_RESPONSE_MARGIN_TOKENS: int = 4096
    MAX_SPLIT_ATTEMPTS: int = 3

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8081",
        memory_path: Optional[Path] = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.memory_path = memory_path or LOCAL_MEMORY_FILE

    # -------------------------------------------------------------
    # P0-5: Measured limits via /props and /tokenize
    # -------------------------------------------------------------
    def query_server_props(self, timeout_sec: float = 3.0) -> ServerPropsResult:
        """Query real model properties and context limits from live server."""
        props_url = f"{self.base_url}/props"
        try:
            req = urllib.request.Request(props_url, headers={"User-Agent": "Hermes-LocalSupervisor/1.0"})
            with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                gen_settings = data.get("default_generation_settings", {})
                n_ctx = int(gen_settings.get("n_ctx") or data.get("n_ctx") or 65536)
                total_slots = int(data.get("total_slots", 1))
                model_path = str(data.get("model_path") or data.get("model_alias") or "")
                
                # Extract clean GGUF model name
                model_name = Path(model_path).stem if model_path else "local-model"
                return ServerPropsResult(
                    n_ctx=n_ctx,
                    total_slots=total_slots,
                    model_name=model_name,
                    model_path=model_path,
                    is_measured=True,
                )
        except Exception as err:
            logger.warning("Failed to query /props from %s: %s (using unverified fallback)", props_url, err)
            return ServerPropsResult(
                n_ctx=65536,
                total_slots=1,
                model_name="local-model-unverified",
                model_path="",
                is_measured=False,
            )

    def count_tokens(self, text: str, timeout_sec: float = 3.0) -> TokenCountResult:
        """Count tokens accurately via /tokenize endpoint with fallback character heuristic."""
        if not text:
            return TokenCountResult(tokens_count=0, is_estimated=False, method="exact_empty")

        tok_url = f"{self.base_url}/tokenize"
        try:
            payload = json.dumps({"content": text}).encode("utf-8")
            req = urllib.request.Request(
                tok_url,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                tokens = data.get("tokens", [])
                return TokenCountResult(
                    tokens_count=len(tokens),
                    is_estimated=False,
                    method="tokenize_api",
                )
        except Exception as err:
            logger.warning("Failed to /tokenize with %s: %s. Using heuristic estimate.", tok_url, err)
            # Standard heuristic for mixed code/russian/english: ~3.5 chars per token
            est_tokens = max(1, int(len(text) / 3.5))
            return TokenCountResult(
                tokens_count=est_tokens,
                is_estimated=True,
                method="char_heuristic",
            )

    # -------------------------------------------------------------
    # P0-6: Semantic Task Splitting
    # -------------------------------------------------------------
    def calculate_effective_prompt_limit(
        self,
        server_n_ctx: int,
        expected_response_tokens: int = DEFAULT_RESPONSE_MARGIN_TOKENS,
        safety_margin_tokens: int = DEFAULT_SAFETY_MARGIN_TOKENS,
        model_name: Optional[str] = None,
    ) -> int:
        """Calculate safe prompt limit considering response budget, safety buffer, and past memory."""
        base_limit = max(1024, server_n_ctx - expected_response_tokens - safety_margin_tokens)
        
        # Check if memory has a smaller known safe working volume
        if model_name:
            rec = self.get_model_memory(model_name)
            if rec and rec.safe_chunk_tokens > 0 and rec.safe_chunk_tokens < base_limit:
                return rec.safe_chunk_tokens
        return base_limit

    def split_task_semantically(
        self,
        task_text: str,
        max_chunk_tokens: int,
        prompt_template: str = "",
    ) -> List[str]:
        """Split a code or textual task across semantic boundaries (file, class, function, markdown).
        
        If the entire text fits, returns [task_text].
        If an individual unit is indivisible and exceeds limit, raises IndivisibleTaskError.
        """
        template_tokens = self.count_tokens(prompt_template).tokens_count if prompt_template else 0
        usable_budget = max(1, max_chunk_tokens - template_tokens)

        full_count = self.count_tokens(task_text).tokens_count
        if full_count <= usable_budget:
            return [task_text]

        # Semantic splitting strategy:
        # Step 1: Detect File Boundaries (e.g. diffs, markdown files, --- file: ...)
        file_splits = re.split(r"(?=(?:^|\n)\s*(?:diff --git|--- [a-zA-Z0-9_/.-]+|### File:|```[a-zA-Z0-9_-]+\s*# [a-zA-Z0-9_/.-]+))", task_text)
        file_splits = [s for s in file_splits if s.strip()]

        if len(file_splits) > 1 and all(self.count_tokens(f).tokens_count <= usable_budget for f in file_splits):
            return self._pack_chunks(file_splits, usable_budget)

        # Step 2: Detect Code Function/Class Boundaries
        # Match class/def/function/sections (including indented methods)
        code_units = []
        for segment in (file_splits if len(file_splits) > 1 else [task_text]):
            seg_tokens = self.count_tokens(segment).tokens_count
            if seg_tokens <= usable_budget and len(file_splits) > 1:
                code_units.append(segment)
            else:
                sub_splits = re.split(r"(?=(?:^|\n)\s*(?:class\s+[A-Za-z0-9_]+|def\s+[A-Za-z0-9_]+|async\s+def\s+[A-Za-z0-9_]+|function\s+[A-Za-z0-9_]+|##+\s+))", segment)
                sub_splits = [s for s in sub_splits if s.strip()]
                if len(sub_splits) > 1:
                    for sub in sub_splits:
                        if self.count_tokens(sub).tokens_count > usable_budget:
                            para_splits = re.split(r"(?=\n\n+)", sub)
                            para_splits = [p for p in para_splits if p.strip()]
                            for p in para_splits:
                                if self.count_tokens(p).tokens_count > usable_budget:
                                    raise IndivisibleTaskError(
                                        f"Неделимый фрагмент ({self.count_tokens(p).tokens_count} токенов) превышает лимит ({usable_budget} токенов)."
                                    )
                                code_units.append(p)
                        else:
                            code_units.append(sub)
                else:
                    para_splits = re.split(r"(?=\n\n+)", segment)
                    para_splits = [p for p in para_splits if p.strip()]
                    for p in para_splits:
                        if self.count_tokens(p).tokens_count > usable_budget:
                            raise IndivisibleTaskError(
                                f"Неделимый фрагмент ({self.count_tokens(p).tokens_count} токенов) превышает лимит ({usable_budget} токенов)."
                            )
                        code_units.append(p)

        return self._pack_chunks(code_units, usable_budget)

    def _pack_chunks(self, units: List[str], max_tokens: int) -> List[str]:
        """Greedily pack atomic units into contiguous chunks up to max_tokens."""
        chunks: List[str] = []
        current_chunk: List[str] = []
        current_tokens = 0

        for unit in units:
            unit_tokens = self.count_tokens(unit).tokens_count
            if current_chunk and (current_tokens + unit_tokens > max_tokens):
                chunks.append("".join(current_chunk))
                current_chunk = [unit]
                current_tokens = unit_tokens
            else:
                current_chunk.append(unit)
                current_tokens += unit_tokens

        if current_chunk:
            chunks.append("".join(current_chunk))
        return chunks

    # -------------------------------------------------------------
    # P0-7: Outcome & Reasoning-Exhaustion Detection
    # -------------------------------------------------------------
    def detect_outcome(
        self,
        response_data: Optional[Dict[str, Any]],
        error: Optional[Exception] = None,
        elapsed_sec: float = 0.0,
        timeout_threshold_sec: float = 180.0,
    ) -> Tuple[SupervisorOutcome, str]:
        """Classify generation outcome distinguishing timeout, error, success, and A39 reasoning exhaustion."""
        if error is not None:
            err_msg = str(error).lower()
            if "timeout" in err_msg or "timed out" in err_msg or elapsed_sec >= timeout_threshold_sec:
                return SupervisorOutcome.TIMEOUT, f"Превышен таймаут исполнения ({elapsed_sec:.1f}s >= {timeout_threshold_sec:.1f}s)"
            return SupervisorOutcome.ERROR, f"Ошибка вызова: {error}"

        if not response_data:
            return SupervisorOutcome.ERROR, "Пустой ответ от сервера"

        # Check choices / content
        choices = response_data.get("choices", [])
        if not choices:
            return SupervisorOutcome.ERROR, "Отсутствуют варианты ответа (choices empty)"

        msg = choices[0].get("message", {})
        content = msg.get("content", "")
        reasoning_content = msg.get("reasoning_content", "")
        timings = response_data.get("timings", {})
        predicted_n = timings.get("predicted_n", 0)

        # A39 Case: Model spent all tokens thinking/looping with 0 actual output content
        if (not content or content.strip() == "") and (predicted_n > 50 or bool(reasoning_content)):
            return SupervisorOutcome.REASONING_EXHAUSTED, (
                f"Кейс A39: потрачено {predicted_n} токенов на рассуждения, но 0 символов полезного ответа. "
                "Требуется отключение thinking через request_options (enable_thinking: false)."
            )

        if not content or content.strip() == "":
            return SupervisorOutcome.ERROR, "Модель вернула пустой контент"

        return SupervisorOutcome.SUCCESS, f"Успешно сгенерировано ({len(content)} символов, {predicted_n} токенов за {elapsed_sec:.2f}s)"

    # -------------------------------------------------------------
    # P0-8: AI-Memory Tracking by GGUF Build Metadata
    # -------------------------------------------------------------
    def _load_all_memories(self) -> Dict[str, Dict[str, Any]]:
        if not self.memory_path.exists():
            return {}
        try:
            with open(self.memory_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning("Error reading local model memory from %s: %s", self.memory_path, e)
            return {}

    def get_model_memory(self, gguf_name: str) -> Optional[ModelMemoryRecord]:
        """Fetch historical performance and safe working volume for model."""
        clean_name = self._normalize_gguf_name(gguf_name)
        data = self._load_all_memories()
        rec_data = data.get(clean_name)
        if not rec_data:
            return None
        return ModelMemoryRecord(**rec_data)

    def record_working_volume(
        self,
        gguf_name: str,
        prompt_tokens: int,
        output_tokens: int,
        outcome: SupervisorOutcome,
        speed_tps: float,
        task_id: str = "general",
    ) -> ModelMemoryRecord:
        """Record successful or failed dispatch to canonical AI-Memory."""
        clean_name = self._normalize_gguf_name(gguf_name)
        data = self._load_all_memories()

        now_iso = datetime.now(timezone.utc).isoformat()
        current = data.get(clean_name)

        if current:
            rec = ModelMemoryRecord(**current)
        else:
            rec = ModelMemoryRecord(
                gguf_name=clean_name,
                safe_chunk_tokens=prompt_tokens if outcome == SupervisorOutcome.SUCCESS else 4096,
                max_tested_tokens=prompt_tokens,
                successful_dispatches=0,
                failed_dispatches=0,
                last_working_context=prompt_tokens if outcome == SupervisorOutcome.SUCCESS else 0,
                avg_generation_tps=speed_tps,
                last_updated=now_iso,
            )

        if outcome == SupervisorOutcome.SUCCESS:
            rec.successful_dispatches += 1
            rec.last_working_context = prompt_tokens
            rec.max_tested_tokens = max(rec.max_tested_tokens, prompt_tokens)
            # Smooth exponential safe chunk adjustment
            if prompt_tokens > rec.safe_chunk_tokens:
                rec.safe_chunk_tokens = prompt_tokens
            if speed_tps > 0:
                rec.avg_generation_tps = round((rec.avg_generation_tps * 0.7) + (speed_tps * 0.3), 2)
        else:
            rec.failed_dispatches += 1
            # If failed at this volume, reduce safe chunk tokens by 20%
            if prompt_tokens >= rec.safe_chunk_tokens and rec.safe_chunk_tokens > 2048:
                rec.safe_chunk_tokens = max(2048, int(prompt_tokens * 0.8))

        rec.last_updated = now_iso
        rec.history.append({
            "timestamp": now_iso,
            "task_id": task_id,
            "prompt_tokens": prompt_tokens,
            "output_tokens": output_tokens,
            "outcome": outcome.value,
            "speed_tps": round(speed_tps, 2),
        })
        if len(rec.history) > 50:
            rec.history = rec.history[-50:]

        data[clean_name] = asdict(rec)
        self._save_all_memories(data)
        return rec

    def _save_all_memories(self, data: Dict[str, Dict[str, Any]]):
        try:
            self.memory_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.memory_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error("Failed to save local model memory to %s: %s", self.memory_path, e)

    def _normalize_gguf_name(self, name: str) -> str:
        """Extract clean model canonical identity from path or filename."""
        clean = Path(name).stem
        clean = clean.replace(".gguf", "").replace("-Q4_K_M", "").replace("-Instruct", "").strip()
        return clean or "local-model"
