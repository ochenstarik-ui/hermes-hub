"""Model Family Capability Matrix for intelligent routing and capability matching."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set


@dataclass
class ModelCapability:
    model_id: str
    family: str
    provider: str
    context_window: int
    max_output_tokens: int
    supports_tools: bool = True
    supports_vision: bool = False
    supports_json_schema: bool = True
    supports_reasoning: bool = False
    supports_responses_api: bool = False
    relative_cost_score: int = 1  # 1 (low) to 5 (high)
    speed_score: int = 4  # 1 (slow) to 5 (fast)


class CapabilityMatrix:
    """Matrix defining capabilities of all supported model families."""

    _instance: Optional[CapabilityMatrix] = None

    def __init__(self):
        self._models: Dict[str, ModelCapability] = {}
        self._populate_matrix()

    @classmethod
    def get(cls) -> CapabilityMatrix:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _populate_matrix(self):
        # ── Google Antigravity ──
        self.register(ModelCapability(
            model_id="gemini-2.5-pro",
            family="gemini-2.5-pro",
            provider="antigravity",
            context_window=1000000,
            max_output_tokens=65536,
            supports_tools=True,
            supports_vision=True,
            supports_json_schema=True,
            supports_reasoning=True,
            relative_cost_score=4,
            speed_score=3,
        ))
        self.register(ModelCapability(
            model_id="gemini-2.5-flash",
            family="gemini-2.5-flash",
            provider="antigravity",
            context_window=1000000,
            max_output_tokens=65536,
            supports_tools=True,
            supports_vision=True,
            supports_json_schema=True,
            supports_reasoning=False,
            relative_cost_score=1,
            speed_score=5,
        ))
        self.register(ModelCapability(
            model_id="gemini-2.5-flash-thinking",
            family="gemini-2.5-flash-thinking",
            provider="antigravity",
            context_window=1000000,
            max_output_tokens=65536,
            supports_tools=True,
            supports_vision=True,
            supports_json_schema=True,
            supports_reasoning=True,
            relative_cost_score=2,
            speed_score=4,
        ))

        # ── OpenAI Codex ──
        self.register(ModelCapability(
            model_id="gpt-5.3-codex",
            family="gpt-5.3-codex",
            provider="openai-codex",
            context_window=200000,
            max_output_tokens=32768,
            supports_tools=True,
            supports_vision=True,
            supports_json_schema=True,
            supports_reasoning=True,
            supports_responses_api=True,
            relative_cost_score=5,
            speed_score=3,
        ))
        self.register(ModelCapability(
            model_id="gpt-5.1-codex-mini",
            family="gpt-5.1-codex-mini",
            provider="openai-codex",
            context_window=128000,
            max_output_tokens=16384,
            supports_tools=True,
            supports_vision=False,
            supports_json_schema=True,
            supports_reasoning=False,
            supports_responses_api=True,
            relative_cost_score=2,
            speed_score=5,
        ))

        # ── OpenCode Go ──
        self.register(ModelCapability(
            model_id="opencode-go-3",
            family="opencode-go-3",
            provider="opencode-go",
            context_window=64000,
            max_output_tokens=8192,
            supports_tools=True,
            supports_vision=False,
            supports_json_schema=True,
            supports_reasoning=False,
            relative_cost_score=1,
            speed_score=5,
        ))

        # ── DeepSeek (Roadmap) ──
        self.register(ModelCapability(
            model_id="deepseek-chat",
            family="deepseek-chat",
            provider="deepseek",
            context_window=64000,
            max_output_tokens=8192,
            supports_tools=True,
            supports_vision=False,
            supports_json_schema=True,
            supports_reasoning=False,
            supports_responses_api=True,
            relative_cost_score=1,
            speed_score=4,
        ))
        self.register(ModelCapability(
            model_id="deepseek-reasoner",
            family="deepseek-reasoner",
            provider="deepseek",
            context_window=64000,
            max_output_tokens=8192,
            supports_tools=False,
            supports_vision=False,
            supports_json_schema=False,
            supports_reasoning=True,
            supports_responses_api=True,
            relative_cost_score=1,
            speed_score=2,
        ))

    def register(self, cap: ModelCapability):
        self._models[cap.model_id] = cap

    def get_capability(self, model_id: str) -> Optional[ModelCapability]:
        return self._models.get(model_id)

    def find_best_model_for_role(
        self,
        required_tools: bool = True,
        required_reasoning: bool = False,
        min_context: int = 32000,
    ) -> List[ModelCapability]:
        """Filter and rank models meeting specific role constraints."""
        candidates = []
        for m in self._models.values():
            if required_tools and not m.supports_tools:
                continue
            if required_reasoning and not m.supports_reasoning:
                continue
            if m.context_window < min_context:
                continue
            candidates.append(m)

        # Rank by speed and cost
        candidates.sort(key=lambda x: (x.supports_reasoning, -x.relative_cost_score, x.speed_score), reverse=True)
        return candidates
