"""Unified Skill Registry supporting Hermes Agent, Google Antigravity, OpenAI Codex, and OpenCode."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class SkillParameter:
    name: str
    type_name: str
    description: str
    required: bool = True
    default: Optional[Any] = None


@dataclass
class UnifiedSkill:
    skill_id: str
    name: str
    description: str
    parameters: List[SkillParameter] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    supported_providers: List[str] = field(default_factory=lambda: ["antigravity", "openai-codex", "opencode-go"])
    requires_approval: bool = False


class UnifiedSkillRegistry:
    """Central registry normalizing skills across multi-provider formats."""

    _instance: Optional[UnifiedSkillRegistry] = None

    def __init__(self):
        self._skills: Dict[str, UnifiedSkill] = {}
        self._register_default_skills()

    @classmethod
    def get(cls) -> UnifiedSkillRegistry:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def register(self, skill: UnifiedSkill):
        self._skills[skill.skill_id] = skill

    def get_skill(self, skill_id: str) -> Optional[UnifiedSkill]:
        return self._skills.get(skill_id)

    def list_skills(self, provider: Optional[str] = None) -> List[UnifiedSkill]:
        if not provider:
            return list(self._skills.values())
        return [s for s in self._skills.values() if provider in s.supported_providers]

    def to_provider_schema(self, skill_id: str, provider: str) -> Dict[str, Any]:
        """Translate unified skill into provider-specific tool call declaration."""
        skill = self._skills.get(skill_id)
        if not skill:
            raise KeyError(f"Skill '{skill_id}' not found")

        props = {}
        required = []
        for p in skill.parameters:
            props[p.name] = {
                "type": p.type_name,
                "description": p.description,
            }
            if p.required:
                required.append(p.name)

        if "antigravity" in provider or "google" in provider:
            return {
                "name": skill.name,
                "description": skill.description,
                "parameters": {
                    "type": "OBJECT",
                    "properties": props,
                    "required": required,
                },
            }
        else:  # OpenAI / OpenCode format
            return {
                "type": "function",
                "function": {
                    "name": skill.name,
                    "description": skill.description,
                    "parameters": {
                        "type": "object",
                        "properties": props,
                        "required": required,
                    },
                },
            }

    def _register_default_skills(self):
        self.register(
            UnifiedSkill(
                skill_id="search_web",
                name="search_web",
                description="Performs internet web search queries",
                parameters=[
                    SkillParameter(name="query", type_name="string", description="The search term"),
                ],
                tags=["search", "web", "research"],
            )
        )
        self.register(
            UnifiedSkill(
                skill_id="run_command",
                name="run_command",
                description="Execute commands safely in the target terminal shell",
                parameters=[
                    SkillParameter(name="CommandLine", type_name="string", description="Exact command line string"),
                    SkillParameter(name="Cwd", type_name="string", description="Working directory"),
                ],
                tags=["terminal", "execution"],
            )
        )
        self.register(
            UnifiedSkill(
                skill_id="view_file",
                name="view_file",
                description="View contents of a file from filesystem",
                parameters=[
                    SkillParameter(name="AbsolutePath", type_name="string", description="Target file path"),
                ],
                tags=["file", "read"],
            )
        )
