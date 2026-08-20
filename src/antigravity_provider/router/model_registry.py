"""Hermes Hub — Dynamic Model Registry, Capability Policies, and Smart Scoring Engine.

Eliminates hardcoded model names by providing:
- Rich capability annotations (coding, reasoning, tools, structured output, long context, latency class, cost, quota buckets)
- Declarative role requirements (Fast, Researcher, Core Coder, Routine Coder, Reviewer)
- Multi-dimensional scoring (Capability hard filter > Quota/Health > Quality/Reasoning/Latency/Cost/Diversity)
- Antigravity quota bucket isolation (Claude vs Gemini independent buckets)
- Explainable selection traces (RouterSelectionTrace)
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger("hermes.router.model_registry")


@dataclass
class ModelDescriptor:
    """Metadata describing a specific model's capabilities, cost, and quota bucket."""
    model_id: str
    display_name: str
    provider: str
    family: str  # "gemini" | "claude" | "gpt" | "grok" | "deepseek" | "qwen" | "other"
    capabilities: List[str] = field(default_factory=list)
    context_window: int = 128000
    supports_tools: bool = True
    supports_reasoning: bool = False
    latency_class: str = "medium"  # "ultra_low" | "low" | "medium" | "high"
    cost_input_per_m: float = 1.0
    cost_output_per_m: float = 3.0
    quota_bucket: str = "default"  # e.g. "antigravity.claude", "antigravity.gemini", "openai-codex"
    quality_tier: int = 4  # 1 (lowest) to 5 (highest)
    enabled: bool = True


@dataclass
class RoleRequirements:
    """Declarative capability and priority profile for a logical agent role."""
    role_id: str
    display_name_ru: str
    required_capabilities: List[str] = field(default_factory=list)
    min_context_window: int = 8000
    requires_tools: bool = False
    min_quality_tier: int = 1
    cost_priority: float = 0.5        # 0.0 (ignore cost) to 1.0 (maximize cheapness)
    latency_priority: float = 0.5     # 0.0 (ignore latency) to 1.0 (maximize speed)
    reasoning_priority: float = 0.5   # 0.0 to 1.0
    quality_priority: float = 0.5     # 0.0 to 1.0
    quota_priority: float = 1.0       # Prefer model families with measured quota remaining
    diversity_priority: float = 0.0   # 0.0 to 1.0 (prefer different provider/family from reference)
    allow_model_fallback: bool = True


@dataclass
class RouterSelectionTrace:
    """Explainable trace of the model & profile selection decision."""
    role: str
    session_id: Optional[str]
    required_capabilities: List[str]
    candidates_evaluated: int
    selected_profile_id: str
    selected_provider: str
    selected_model: str
    decision_rationale: str
    fallback_chain: List[Dict[str, Any]] = field(default_factory=list)


# ── Standard Role Requirements Catalog ──
DEFAULT_ROLE_REQUIREMENTS: Dict[str, RoleRequirements] = {
    "fast": RoleRequirements(
        role_id="fast",
        display_name_ru="Быстрый агент / Диспетчер",
        required_capabilities=["classification", "routing"],
        min_context_window=16000,
        requires_tools=False,
        min_quality_tier=2,
        latency_priority=1.0,
        cost_priority=0.9,
        reasoning_priority=0.2,
        quality_priority=0.4,
    ),
    "dispatcher": RoleRequirements(
        role_id="dispatcher",
        display_name_ru="Диспетчер запросов",
        required_capabilities=["classification"],
        min_context_window=16000,
        latency_priority=1.0,
        cost_priority=0.9,
    ),
    "research": RoleRequirements(
        role_id="research",
        display_name_ru="Исследователь",
        required_capabilities=["reasoning", "long_context"],
        min_context_window=64000,
        requires_tools=True,
        min_quality_tier=4,
        quality_priority=0.9,
        reasoning_priority=0.9,
        latency_priority=0.3,
        cost_priority=0.4,
    ),
    "coder-primary": RoleRequirements(
        role_id="coder-primary",
        display_name_ru="Главный кодер",
        required_capabilities=["coding", "tools", "structured_output"],
        min_context_window=32000,
        requires_tools=True,
        min_quality_tier=4,
        quality_priority=0.95,
        reasoning_priority=0.85,
        latency_priority=0.4,
        cost_priority=0.3,
    ),
    "coder-secondary": RoleRequirements(
        role_id="coder-secondary",
        display_name_ru="Вспомогательный кодер",
        required_capabilities=["coding", "structured_output"],
        min_context_window=32000,
        requires_tools=True,
        min_quality_tier=3,
        quality_priority=0.7,
        cost_priority=0.8,
        latency_priority=0.6,
    ),
    "routine-coder": RoleRequirements(
        role_id="routine-coder",
        display_name_ru="Рутинный кодер",
        required_capabilities=["coding", "structured_output"],
        min_context_window=16000,
        min_quality_tier=3,
        cost_priority=0.9,
        quality_priority=0.6,
        latency_priority=0.7,
    ),
    "reviewer": RoleRequirements(
        role_id="reviewer",
        display_name_ru="Ревьюер кода",
        required_capabilities=["coding", "reasoning", "security_analysis"],
        min_context_window=32000,
        min_quality_tier=4,
        reasoning_priority=0.95,
        quality_priority=0.9,
        diversity_priority=0.8,  # Prefer model family distinct from author
        cost_priority=0.4,
        latency_priority=0.3,
    ),
    "orchestrator": RoleRequirements(
        role_id="orchestrator",
        display_name_ru="Главный оркестратор",
        required_capabilities=["reasoning", "structured_output", "planning"],
        min_context_window=64000,
        requires_tools=True,
        min_quality_tier=5,
        quality_priority=1.0,
        reasoning_priority=0.95,
        latency_priority=0.4,
        cost_priority=0.2,
    ),
}


class ModelRegistry:
    """Central registry of known models across providers with dynamic capability inspection."""

    _instance: Optional[ModelRegistry] = None
    _instance_lock = threading.Lock()

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._models: Dict[str, ModelDescriptor] = {}
        self._role_reqs: Dict[str, RoleRequirements] = dict(DEFAULT_ROLE_REQUIREMENTS)
        self._init_default_models()

    @classmethod
    def get(cls) -> ModelRegistry:
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def _init_default_models(self):
        """Populate initial canonical models and capabilities."""
        models = [
            # Google Antigravity (Gemini family)
            ModelDescriptor(
                model_id="google-antigravity/gemini-2.5-pro",
                display_name="Gemini 2.5 Pro",
                provider="antigravity",
                family="gemini",
                capabilities=["coding", "reasoning", "tools", "structured_output", "long_context", "planning", "security_analysis"],
                context_window=1000000,
                supports_tools=True,
                supports_reasoning=True,
                latency_class="medium",
                cost_input_per_m=1.25,
                cost_output_per_m=5.0,
                quota_bucket="antigravity.gemini",
                quality_tier=5,
            ),
            ModelDescriptor(
                model_id="google-antigravity/gemini-2.5-flash",
                display_name="Gemini 2.5 Flash",
                provider="antigravity",
                family="gemini",
                capabilities=["coding", "tools", "structured_output", "classification", "routing", "long_context"],
                context_window=1000000,
                supports_tools=True,
                supports_reasoning=False,
                latency_class="ultra_low",
                cost_input_per_m=0.15,
                cost_output_per_m=0.6,
                quota_bucket="antigravity.gemini",
                quality_tier=3,
            ),
            # Google Antigravity (Claude family inside AGY)
            ModelDescriptor(
                model_id="google-antigravity/claude-3-7-sonnet",
                display_name="Claude 3.7 Sonnet (AGY)",
                provider="antigravity",
                family="claude",
                capabilities=["coding", "reasoning", "tools", "structured_output", "security_analysis", "planning"],
                context_window=200000,
                supports_tools=True,
                supports_reasoning=True,
                latency_class="medium",
                cost_input_per_m=3.0,
                cost_output_per_m=15.0,
                quota_bucket="antigravity.claude",
                quality_tier=5,
            ),
            ModelDescriptor(
                model_id="google-antigravity/claude-3-5-sonnet",
                display_name="Claude 3.5 Sonnet (AGY)",
                provider="antigravity",
                family="claude",
                capabilities=["coding", "reasoning", "tools", "structured_output", "security_analysis"],
                context_window=200000,
                supports_tools=True,
                supports_reasoning=True,
                latency_class="medium",
                cost_input_per_m=3.0,
                cost_output_per_m=15.0,
                quota_bucket="antigravity.claude",
                quality_tier=5,
            ),
            # OpenAI Codex
            ModelDescriptor(
                model_id="openai/gpt-4o",
                display_name="GPT-4o",
                provider="openai-codex",
                family="gpt",
                capabilities=["coding", "reasoning", "tools", "structured_output", "planning", "security_analysis"],
                context_window=128000,
                supports_tools=True,
                supports_reasoning=False,
                latency_class="low",
                cost_input_per_m=2.5,
                cost_output_per_m=10.0,
                quota_bucket="openai-codex",
                quality_tier=5,
            ),
            ModelDescriptor(
                model_id="openai/gpt-4o-mini",
                display_name="GPT-4o Mini",
                provider="openai-codex",
                family="gpt",
                capabilities=["coding", "tools", "structured_output", "classification", "routing"],
                context_window=128000,
                supports_tools=True,
                supports_reasoning=False,
                latency_class="ultra_low",
                cost_input_per_m=0.15,
                cost_output_per_m=0.6,
                quota_bucket="openai-codex",
                quality_tier=3,
            ),
            # Claude (Anthropic Direct)
            ModelDescriptor(
                model_id="claude-3-7-sonnet-20250219",
                display_name="Claude 3.7 Sonnet",
                provider="claude",
                family="claude",
                capabilities=["coding", "reasoning", "tools", "structured_output", "security_analysis", "planning"],
                context_window=200000,
                supports_tools=True,
                supports_reasoning=True,
                latency_class="medium",
                cost_input_per_m=3.0,
                cost_output_per_m=15.0,
                quota_bucket="claude",
                quality_tier=5,
            ),
            ModelDescriptor(
                model_id="claude-3-5-haiku-20241022",
                display_name="Claude 3.5 Haiku",
                provider="claude",
                family="claude",
                capabilities=["coding", "tools", "structured_output", "classification", "routing"],
                context_window=200000,
                supports_tools=True,
                supports_reasoning=False,
                latency_class="ultra_low",
                cost_input_per_m=0.8,
                cost_output_per_m=4.0,
                quota_bucket="claude",
                quality_tier=3,
            ),
            # Grok (xAI)
            ModelDescriptor(
                model_id="grok-2-1212",
                display_name="Grok 2",
                provider="grok",
                family="grok",
                capabilities=["coding", "reasoning", "tools", "structured_output", "security_analysis"],
                context_window=128000,
                supports_tools=True,
                supports_reasoning=True,
                latency_class="low",
                cost_input_per_m=2.0,
                cost_output_per_m=10.0,
                quota_bucket="grok",
                quality_tier=4,
            ),
            # OpenCode Go
            ModelDescriptor(
                model_id="opencode/deepseek-v3",
                display_name="DeepSeek V3",
                provider="opencode-go",
                family="deepseek",
                capabilities=["coding", "reasoning", "tools", "structured_output", "long_context"],
                context_window=64000,
                supports_tools=True,
                supports_reasoning=False,
                latency_class="low",
                cost_input_per_m=0.27,
                cost_output_per_m=1.1,
                quota_bucket="opencode-go",
                quality_tier=4,
            ),
        ]

        for m in models:
            self._models[m.model_id] = m

    def get_model(self, model_id: str) -> Optional[ModelDescriptor]:
        with self._lock:
            # Direct match
            if model_id in self._models:
                return self._models[model_id]
            # Suffix match
            for m_id, desc in self._models.items():
                if m_id.endswith(model_id) or model_id.endswith(m_id):
                    return desc
            return None

    def register_model(self, descriptor: ModelDescriptor) -> None:
        with self._lock:
            self._models[descriptor.model_id] = descriptor

    def get_role_requirements(self, role: str) -> RoleRequirements:
        with self._lock:
            normalized = role.strip().lower()
            if normalized in self._role_reqs:
                return self._role_reqs[normalized]
            # Default fallback for custom roles
            return RoleRequirements(
                role_id=normalized,
                display_name_ru=role,
                required_capabilities=["coding"],
                min_quality_tier=3,
            )

    def evaluate_model_score(
        self,
        descriptor: ModelDescriptor,
        reqs: RoleRequirements,
        reference_author_family: Optional[str] = None,
        quota_remaining_percent: Optional[float] = None,
    ) -> Tuple[bool, float, str]:
        """Evaluate whether model satisfies hard requirements and calculate multidimensional score."""
        # 1. Hard Filter: Required capabilities
        for cap in reqs.required_capabilities:
            if cap not in descriptor.capabilities:
                return False, 0.0, f"Missing required capability: '{cap}'"

        # 2. Hard Filter: Tools support
        if reqs.requires_tools and not descriptor.supports_tools:
            return False, 0.0, "Missing required tool calling support"

        # 3. Hard Filter: Context window
        if descriptor.context_window < reqs.min_context_window:
            return False, 0.0, f"Context window {descriptor.context_window} < required {reqs.min_context_window}"

        # 4. Hard Filter: Minimum quality tier
        if descriptor.quality_tier < reqs.min_quality_tier:
            return False, 0.0, f"Quality tier {descriptor.quality_tier} < required {reqs.min_quality_tier}"
        if quota_remaining_percent is not None and quota_remaining_percent <= 0:
            return False, 0.0, "Quota bucket exhausted"

        # ── Weighted Multi-Dimensional Score ──
        # Normalized quality: 0.2 to 1.0
        qual_score = descriptor.quality_tier / 5.0

        # Normalized reasoning
        reas_score = 1.0 if descriptor.supports_reasoning else 0.4

        # Normalized latency: ultra_low=1.0, low=0.8, medium=0.5, high=0.2
        lat_map = {"ultra_low": 1.0, "low": 0.8, "medium": 0.5, "high": 0.2}
        lat_score = lat_map.get(descriptor.latency_class, 0.5)

        # Normalized cost (cheaper = higher score): input cost scaled inverse
        cost_score = max(0.1, min(1.0, 3.0 / (descriptor.cost_input_per_m + 0.5)))

        # Diversity bonus (e.g. for code reviewer)
        div_score = 0.5
        if reqs.diversity_priority > 0 and reference_author_family:
            div_score = 1.0 if descriptor.family != reference_author_family else 0.2

        # Unknown quota remains neutral; it is never treated as 100% available.
        quota_score = 0.5 if quota_remaining_percent is None else max(
            0.0,
            min(1.0, quota_remaining_percent / 100.0),
        )

        total_score = (
            qual_score * reqs.quality_priority
            + reas_score * reqs.reasoning_priority
            + lat_score * reqs.latency_priority
            + cost_score * reqs.cost_priority
            + div_score * reqs.diversity_priority
            + quota_score * reqs.quota_priority
        )

        return True, round(total_score, 4), "Satisfies all capability and quality requirements"
