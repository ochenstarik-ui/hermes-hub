"""Hermes Multi-Provider Account Router — Unified Role Registry."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

if TYPE_CHECKING:
    from antigravity_provider.router.router_config import RolePolicy



STATUS_DECLARED_UNIMPLEMENTED = "DECLARED_UNIMPLEMENTED"
STATUS_DECLARED_UNIMPLEMENTED_LABEL_RU = "Роль объявлена, исполнение не реализовано"

@dataclass(frozen=True)
class RoleDefinition:
    role_id: str
    display_name_ru: str
    short_name_ru: str
    description_ru: str
    is_implemented: bool = True
    unimplemented_reason_ru: Optional[str] = None
    capabilities: List[str] = field(default_factory=list)
    fallback_capabilities: List[str] = field(default_factory=list)
    default_preferred_chain: List[str] = field(default_factory=list)
    default_model: Optional[str] = None
    max_failover_attempts: int = 3
    session_affinity_enabled: bool = True
    is_orchestrator: bool = False
    tier: str = "core"

CANONICAL_ROLES: Dict[str, RoleDefinition] = {
    "manager": RoleDefinition(
        role_id="manager",
        display_name_ru="Менеджер проекта (Оркестратор)",
        short_name_ru="Менеджер",
        description_ru="Координация работы субагентов, планирование, контроль исполнения и распределение задач.",
        is_implemented=True,
        is_orchestrator=True,
        capabilities=["orchestrator", "reasoning", "management", "planning"],
        fallback_capabilities=["orchestrator", "reasoning"],
        default_preferred_chain=["codex-orch", "ag-orch-fallback", "claude-orch", "grok-orch", "opengo-3"],
        default_model="gemini-3.7-flash",
        max_failover_attempts=3,
        tier="core",
    ),
    "developer-1": RoleDefinition(
        role_id="developer-1",
        display_name_ru="Ведущий разработчик (Кодер 1)",
        short_name_ru="Кодер 1",
        description_ru="Пишет код, реализует функционал, исправляет ошибки.",
        is_implemented=True,
        capabilities=["coding", "developer-1", "reasoning", "tools", "structured_output"],
        fallback_capabilities=["coding"],
        default_preferred_chain=["codex-worker-1", "claude-worker-1", "ag-w1", "opengo-1"],
        max_failover_attempts=3,
        tier="core",
    ),
    "developer-2": RoleDefinition(
        role_id="developer-2",
        display_name_ru="Вспомогательный разработчик (Кодер 2)",
        short_name_ru="Кодер 2",
        description_ru="Проверяет код Разработчика 1 и выдаёт ему задание на исправление.",
        is_implemented=True,
        capabilities=["coding", "developer-2", "reviewer", "tools"],
        fallback_capabilities=["coding", "reviewer"],
        default_preferred_chain=["ag-w1", "grok-worker-1", "codex-worker-2", "opengo-3"],
        max_failover_attempts=3,
        tier="core",
    ),
    "code-reviewer": RoleDefinition(
        role_id="code-reviewer",
        display_name_ru="Ревьюер кода",
        short_name_ru="Код-ревьювер",
        description_ru="Анализирует код на ошибки, проблемы безопасности и соответствие стандартам. Работает после Разработчика 2.",
        is_implemented=True,
        capabilities=["code-reviewer", "reviewer", "coding", "security_analysis"],
        fallback_capabilities=["reviewer", "coding"],
        default_preferred_chain=["claude-worker-2", "codex-worker-2", "ag-w2", "opengo-2"],
        max_failover_attempts=3,
        tier="core",
    ),
    "researcher": RoleDefinition(
        role_id="researcher",
        display_name_ru="Исследователь",
        short_name_ru="Исследователь",
        description_ru="Изучает данные, кодовую базу, документацию и внешние источники, чтобы собрать информацию для решения задачи.",
        is_implemented=True,
        capabilities=["researcher", "research", "search", "long_context"],
        fallback_capabilities=["research", "search"],
        default_preferred_chain=["ag-w3", "grok-worker-2", "opengo-2", "opengo-1"],
        max_failover_attempts=3,
        tier="core",
    ),
    "tester": RoleDefinition(
        role_id="tester",
        display_name_ru="Тестировщик (QA)",
        short_name_ru="Тестировщик",
        description_ru="Создаёт тесты, проверяет корректность работы кода, находит дефекты.",
        is_implemented=True,
        capabilities=["tester", "testing", "fast", "automation"],
        fallback_capabilities=["fast", "testing"],
        default_preferred_chain=["ag-w4", "opengo-1", "ag-spare-1"],
        max_failover_attempts=3,
        tier="qa_doc",
    ),
    "tech-writer": RoleDefinition(
        role_id="tech-writer",
        display_name_ru="Технический писатель",
        short_name_ru="Техписатель",
        description_ru="Создаёт документацию, инструкции, README.",
        is_implemented=True,
        capabilities=["tech-writer", "documentation", "reasoning", "structured_output"],
        fallback_capabilities=["documentation", "reasoning"],
        default_preferred_chain=["claude-worker-2", "ag-w3", "ag-w2"],
        max_failover_attempts=3,
        tier="qa_doc",
    ),
    "analyst": RoleDefinition(
        role_id="analyst",
        display_name_ru="Системный аналитик",
        short_name_ru="Аналитик",
        description_ru="Проводит глубокий анализ данных, выявляет тренды, строит прогнозы.",
        is_implemented=True,
        capabilities=["analyst", "reasoning", "research", "planning"],
        fallback_capabilities=["reasoning", "research"],
        default_preferred_chain=["grok-worker-2", "opengo-2", "ag-w3"],
        max_failover_attempts=3,
        tier="qa_doc",
    ),
    "guardian": RoleDefinition(
        role_id="guardian",
        display_name_ru="Надзиратель (агент безопасности)",
        short_name_ru="Надзиратель",
        description_ru="Проверяет входящие инструкции на промпт-инъекции, анализирует планы и вызовы инструментов, блокирует обход системных правил, не допускает утечки секретов, следит за границами песочницы.",
        is_implemented=False,
        unimplemented_reason_ru=STATUS_DECLARED_UNIMPLEMENTED_LABEL_RU,
        capabilities=["guardian", "security", "sandboxing"],
        fallback_capabilities=["guardian", "security"],
        default_preferred_chain=[],
        max_failover_attempts=0,
        tier="governance",
    ),
    "cost-controller": RoleDefinition(
        role_id="cost-controller",
        display_name_ru="Агент контроля затрат",
        short_name_ru="Контроль затрат",
        description_ru="Оценивает планируемый расход токенов, сравнивает с остатком бюджета, предлагает упрощения, сверяет факт с прогнозом, останавливает цепочку при исчерпании лимита.",
        is_implemented=False,
        unimplemented_reason_ru=STATUS_DECLARED_UNIMPLEMENTED_LABEL_RU,
        capabilities=["cost-controller", "budget", "analytics"],
        fallback_capabilities=["cost-controller", "budget"],
        default_preferred_chain=[],
        max_failover_attempts=0,
        tier="governance",
    ),
    "integration-expert": RoleDefinition(
        role_id="integration-expert",
        display_name_ru="Специалист по интеграции",
        short_name_ru="Интегратор",
        description_ru="Работает с API и внешними сервисами, отправляет вебхуки.",
        is_implemented=True,
        capabilities=["integration-expert", "integration", "coding", "networking"],
        fallback_capabilities=["integration", "coding"],
        default_preferred_chain=["opengo-3", "codex-worker-1", "ag-w4"],
        max_failover_attempts=3,
        tier="expert",
    ),
    "security-expert": RoleDefinition(
        role_id="security-expert",
        display_name_ru="Юрист / специалист по безопасности",
        short_name_ru="Безопасник",
        description_ru="Проверяет код и данные на уязвимости.",
        is_implemented=True,
        capabilities=["security-expert", "security", "code-reviewer", "audit"],
        fallback_capabilities=["security", "code-reviewer"],
        default_preferred_chain=["claude-worker-1", "codex-worker-2", "ag-w2"],
        max_failover_attempts=3,
        tier="expert",
    ),
    "dependency-agent": RoleDefinition(
        role_id="dependency-agent",
        display_name_ru="Проверяющий готовность",
        short_name_ru="Готовность",
        description_ru="До начала задачи убеждается, что на месте всё необходимое — исполняемые файлы и CLI, библиотеки, учётные данные, права доступа, доступность локальных серверов. Сообщает о нехватке до запуска.",
        is_implemented=True,
        capabilities=["dependency-agent", "preflight", "environment", "system_checks", "fast"],
        fallback_capabilities=["dependency-agent", "preflight"],
        default_preferred_chain=["opengo-1", "ag-w1", "codex-worker-1"],
        max_failover_attempts=3,
        tier="qa_doc",
    ),
}

_CANONICAL_ROLE_ALIASES: Dict[str, str] = {
    "orchestrator": "manager",
    "главный оркестратор": "manager",
    "оркестратор": "manager",
    "менеджер": "manager",
    "coder": "developer-1",
    "coder-primary": "developer-1",
    "developer": "developer-1",
    "кодер": "developer-1",
    "кодер 1": "developer-1",
    "разработчик": "developer-1",
    "разработчик 1": "developer-1",
    "coder-secondary": "developer-2",
    "кодер 2": "developer-2",
    "разработчик 2": "developer-2",
    "reviewer": "code-reviewer",
    "ревьюер": "code-reviewer",
    "код-ревьювер": "code-reviewer",
    "код-ревьюер": "code-reviewer",
    "research": "researcher",
    "исследователь": "researcher",
    "fast": "tester",
    "general": "tester",
    "тестировщик": "tester",
    "быстрый агент": "tester",
    "tech_writer": "tech-writer",
    "технический писатель": "tech-writer",
    "аналитик": "analyst",
    "надзиратель": "guardian",
    "контроль затрат": "cost-controller",
    "агент контроля затрат": "cost-controller",
    "интеграция": "integration-expert",
    "специалист по интеграции": "integration-expert",
    "безопасность": "security-expert",
    "специалист по безопасности": "security-expert",
    "dependency-agent": "dependency-agent",
    "dependency_agent": "dependency-agent",
    "preflight": "dependency-agent",
    "проверяющий готовность": "dependency-agent",
    "агент зависимостей": "dependency-agent",
    "готовность": "dependency-agent",
    "dependency": "dependency-agent",
}

class RoleRegistry:
    @classmethod
    def get_all_roles(cls) -> Dict[str, RoleDefinition]:
        return dict(CANONICAL_ROLES)

    @classmethod
    def get_role(cls, role_id: str) -> Optional[RoleDefinition]:
        canonical_id = cls.resolve_canonical_role(role_id)
        return CANONICAL_ROLES.get(canonical_id)

    @classmethod
    def get_role_ids(cls) -> List[str]:
        return list(CANONICAL_ROLES.keys())

    @classmethod
    def get_executable_role_ids(cls) -> List[str]:
        return [r_id for r_id, r_def in CANONICAL_ROLES.items() if r_def.is_implemented]

    @classmethod
    def get_unimplemented_role_ids(cls) -> List[str]:
        return [r_id for r_id, r_def in CANONICAL_ROLES.items() if not r_def.is_implemented]

    @classmethod
    def is_role_implemented(cls, role_id: str) -> bool:
        r_def = cls.get_role(role_id)
        return r_def.is_implemented if r_def else False

    @classmethod
    def get_role_name_ru(cls, role_id: str, default: Optional[str] = None) -> str:
        r_def = cls.get_role(role_id)
        if r_def:
            return r_def.display_name_ru
        return default or role_id

    @classmethod
    def get_role_short_name_ru(cls, role_id: str, default: Optional[str] = None) -> str:
        r_def = cls.get_role(role_id)
        if r_def:
            return r_def.short_name_ru
        return default or role_id

    @classmethod
    def get_role_description_ru(cls, role_id: str) -> str:
        r_def = cls.get_role(role_id)
        if r_def:
            return r_def.description_ru
        return ""

    @classmethod
    def resolve_canonical_role(cls, name_or_alias: str) -> str:
        if not name_or_alias:
            return "manager"
        clean = name_or_alias.strip().lower()
        return _CANONICAL_ROLE_ALIASES.get(clean, clean)

    @classmethod
    def resolve_role_name(cls, name_or_alias: str) -> str:
        return cls.resolve_canonical_role(name_or_alias)

    @classmethod
    def get_canonical_role_map(cls) -> Dict[str, str]:
        return dict(_CANONICAL_ROLE_ALIASES)

    @classmethod
    def get_human_role_labels(cls) -> Dict[str, str]:
        labels = {}
        for r_id, r_def in CANONICAL_ROLES.items():
            labels[r_id] = r_def.short_name_ru
        labels.update({
            "spare_1": "Резерв 1",
            "spare_2": "Резерв 2",
            "cold_spare": "Холодный резерв",
        })
        return labels

    @classmethod
    def get_default_role_policies(cls) -> Dict[str, "RolePolicy"]:
        from antigravity_provider.router.router_config import RolePolicy
        policies: Dict[str, "RolePolicy"] = {}
        for r_id, r_def in CANONICAL_ROLES.items():
            policies[r_id] = RolePolicy(
                role_name=r_id,
                preferred_chain=list(r_def.default_preferred_chain),
                fallback_capabilities=list(r_def.fallback_capabilities),
                max_failover_attempts=r_def.max_failover_attempts,
                session_affinity_enabled=r_def.session_affinity_enabled,
                default_model=r_def.default_model,
            )
        return policies

    @classmethod
    def migrate_legacy_roles(cls, current_roles: Dict[str, "RolePolicy"]) -> Tuple[Dict[str, "RolePolicy"], bool]:
        from antigravity_provider.router.router_config import RolePolicy
        migrated: Dict[str, "RolePolicy"] = {}
        was_modified = False
        default_policies = cls.get_default_role_policies()

        for rname, rpol in current_roles.items():
            canonical_id = cls.resolve_canonical_role(rname)
            if canonical_id != rname:
                was_modified = True
                if canonical_id not in migrated:
                    migrated[canonical_id] = RolePolicy(
                        role_name=canonical_id,
                        preferred_chain=list(rpol.preferred_chain),
                        fallback_capabilities=list(rpol.fallback_capabilities) or list(default_policies[canonical_id].fallback_capabilities),
                        max_failover_attempts=rpol.max_failover_attempts,
                        session_affinity_enabled=rpol.session_affinity_enabled,
                        default_model=rpol.default_model or default_policies[canonical_id].default_model,
                    )
            else:
                migrated[rname] = rpol

        for canon_id, def_policy in default_policies.items():
            if canon_id not in migrated:
                migrated[canon_id] = def_policy
                was_modified = True

        return migrated, was_modified
