"""Hermes Hub — Unified Skills Service & SkillDoctor Diagnostic Engine.

Provides:
1. Skills discovery from standard paths (~/.hermes/skills, ~/.claude/skills, .agents/skills).
2. Frontmatter parsing & validation.
3. Subagent skill assignments persistence (workflow_state.json).
4. Truthful skill call usage tracking (skills_usage.json).
5. SkillDoctor diagnostics: single-line description strictness, 3-part triggers, 5 test queries, auto-fixing.
"""
from __future__ import annotations

import datetime
import json
import logging
import os
import re
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from antigravity_provider import paths
from antigravity_provider.router.settings_service import get_hub_settings

logger = logging.getLogger("hermes.router.skills")


@dataclass
class SkillInfo:
    name: str
    description: str
    path: str
    source_dir: str
    tags: List[str] = field(default_factory=list)
    body: str = ""
    assigned_agents: List[str] = field(default_factory=list)
    usage_count: int = 0
    success_count: int = 0
    last_used_at: Optional[str] = None
    is_valid: bool = True
    critical_errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class SkillDiagnosis:
    skill_name: str
    file_name: str
    file_path: str
    is_valid: bool
    critical_errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    checks: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    test_queries: Dict[str, List[str]] = field(default_factory=lambda: {"positive": [], "negative": []})
    original_description: str = ""
    fixed_description: str = ""
    report_markdown: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _utc_timestamp() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def parse_skill_frontmatter(content: str) -> Tuple[Dict[str, Any], str, List[str]]:
    """Parse YAML frontmatter and markdown body from SKILL.md.
    
    Returns (frontmatter_dict, body_text, raw_errors).
    """
    errors: List[str] = []
    if not content.startswith("---"):
        return {}, content, ["Файл не начинается с разделителя frontmatter '---'"]

    lines = content.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return {}, content, ["Файл должен начинаться с разделителя frontmatter '---' на первой строке"]

    closing_index = -1
    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            closing_index = idx
            break

    if closing_index == -1:
        return {}, content, ["Не найден закрывающий разделитель frontmatter '---'"]

    fm_lines = lines[1:closing_index]
    body_lines = lines[closing_index + 1 :]
    body = "".join(body_lines).strip()

    frontmatter: Dict[str, Any] = {}

    for idx, l in enumerate(fm_lines):
        if re.match(r"^\s*description\s*:", l):
            stripped = l.strip()
            if stripped in ("description:", "description: |", "description: >", "description: |-", "description: >-"):
                errors.append("Критическая ошибка: description оформлен многострочным блоком (| / >). Должен быть строго в одну строку!")
            elif idx + 1 < len(fm_lines) and (fm_lines[idx + 1].startswith("  ") or fm_lines[idx + 1].startswith("\t")):
                errors.append("Критическая ошибка: description разбит на несколько строк с отступом. Должен быть строго в одну строку!")
            break

    current_key: Optional[str] = None
    list_accumulator: List[str] = []

    for l in fm_lines:
        line_stripped = l.strip()
        if not line_stripped or line_stripped.startswith("#"):
            continue

        kv_match = re.match(r"^([a-zA-Z0-9_-]+)\s*:\s*(.*)$", line_stripped)
        if kv_match:
            if current_key and list_accumulator:
                frontmatter[current_key] = list(list_accumulator)
                list_accumulator = []

            k = kv_match.group(1).strip()
            v = kv_match.group(2).strip()
            current_key = k

            if v.startswith("[") and v.endswith("]"):
                try:
                    frontmatter[k] = json.loads(v)
                except Exception:
                    items = [item.strip().strip("'\"") for item in v[1:-1].split(",") if item.strip()]
                    frontmatter[k] = items
            elif v == "" or v in ("|", ">", "|-", ">-"):
                frontmatter[k] = ""
            else:
                clean_v = v.strip("'\"")
                frontmatter[k] = clean_v
        elif line_stripped.startswith("- ") and current_key:
            list_accumulator.append(line_stripped[2:].strip().strip("'\""))
        elif (l.startswith("  ") or l.startswith("\t")) and current_key:
            if isinstance(frontmatter.get(current_key), str):
                if frontmatter[current_key]:
                    frontmatter[current_key] += " " + line_stripped
                else:
                    frontmatter[current_key] = line_stripped

    if current_key and list_accumulator:
        frontmatter[current_key] = list(list_accumulator)

    if "tags" in frontmatter:
        raw_tags = frontmatter["tags"]
        if isinstance(raw_tags, str):
            frontmatter["tags"] = [t.strip() for t in raw_tags.split(",") if t.strip()]
        elif isinstance(raw_tags, list):
            frontmatter["tags"] = [str(t).strip() for t in raw_tags if str(t).strip()]
        else:
            frontmatter["tags"] = []
    else:
        frontmatter["tags"] = []

    return frontmatter, body, errors


class SkillDoctor:
    """Diagnoses and repairs SKILL.md files according to strict standard requirements."""

    @classmethod
    def diagnose(
        cls,
        content: str,
        filename: str = "SKILL.md",
        filepath: str = "",
    ) -> SkillDiagnosis:
        critical_errors: List[str] = []
        warnings: List[str] = []
        checks: Dict[str, Dict[str, Any]] = {}

        clean_fn = Path(filename).name
        fn_passed = (clean_fn == "SKILL.md")
        checks["filename"] = {
            "name": "Имя файла ровно SKILL.md",
            "passed": fn_passed,
            "details": f"Имя файла: '{clean_fn}' (ожидается строго 'SKILL.md')",
        }
        if not fn_passed:
            critical_errors.append(f"Файл должен называться ровно 'SKILL.md', получено: '{clean_fn}'")

        fm, body, raw_fm_errors = parse_skill_frontmatter(content)
        fm_passed = len(raw_fm_errors) == 0
        checks["frontmatter_delimiters"] = {
            "name": "Границы frontmatter (---)",
            "passed": fm_passed,
            "details": "Корректно открыт и закрыт разделителями '---'" if fm_passed else "; ".join(raw_fm_errors),
        }
        for err in raw_fm_errors:
            critical_errors.append(err)

        skill_name = str(fm.get("name") or "").strip()
        if not skill_name and filepath:
            skill_name = Path(filepath).parent.name

        name_slug_valid = bool(re.match(r"^[a-zA-Z0-9_-]+$", skill_name)) if skill_name else False
        checks["name_format"] = {
            "name": "Формат имени (name: slug латиницей)",
            "passed": bool(skill_name and name_slug_valid),
            "details": f"name: '{skill_name}'" if (skill_name and name_slug_valid) else "Имя отсутствует или содержит недопустимые символы (разрешены a-z, 0-9, _, -)",
        }
        if not skill_name:
            critical_errors.append("Отсутствует обязательное поле 'name' во frontmatter")
        elif not name_slug_valid:
            critical_errors.append(f"Поле 'name' ('{skill_name}') должно содержать только символы латиницы, цифры, дефис или подчёркивание")

        raw_desc = fm.get("description", "")
        desc_is_multiline = False
        raw_lines = content.splitlines()
        for idx, line in enumerate(raw_lines):
            if re.match(r"^\s*description\s*:", line):
                for next_line in raw_lines[idx + 1:]:
                    if next_line.strip() == "---" or re.match(r"^[a-zA-Z0-9_-]+\s*:", next_line):
                        break
                    if next_line.startswith("  ") or next_line.startswith("\t"):
                        desc_is_multiline = True
                        break
                break

        if "\n" in str(raw_desc) or "\r" in str(raw_desc) or desc_is_multiline:
            desc_is_multiline = True

        single_line_passed = bool(raw_desc) and not desc_is_multiline
        checks["single_line_description"] = {
            "name": "Строго однострочный description",
            "passed": single_line_passed,
            "details": "Description оформлен в одну строку" if single_line_passed else "КРИТИЧЕСКАЯ ОШИБКА: description разбит на несколько строк или содержит переносы",
        }
        if desc_is_multiline:
            critical_errors.append("Критическая ошибка: description должен быть строго в одну строку без переносов!")
        elif not raw_desc:
            critical_errors.append("Отсутствует обязательное поле 'description' во frontmatter")

        desc_text = str(raw_desc).replace("\n", " ").replace("\r", " ").strip()

        has_positive_triggers = bool(
            re.search(r"(?:use (?:when|for|to)|запускать (?:когда|если|для)|применя(?:ть|ется)|use this|whenever|использовать (?:когда|если|для))\b", desc_text, re.IGNORECASE)
            or re.search(r"(?:when |когда |если )\b", desc_text, re.IGNORECASE)
        )
        has_negative_triggers = bool(
            re.search(r"(?:do not use|don't use|never use|avoid|не запускать|не использовать|избегать|не применять|исключ)\b", desc_text, re.IGNORECASE)
        )

        checks["description_triggers"] = {
            "name": "Триггеры запуска (позитивные и негативные)",
            "passed": bool(has_positive_triggers and has_negative_triggers),
            "details": (
                "Обнаружены и позитивные, и негативные триггеры"
                if (has_positive_triggers and has_negative_triggers)
                else f"Позитивные триггеры: {'есть' if has_positive_triggers else 'нет'}, Негативные триггеры (when NOT to use): {'есть' if has_negative_triggers else 'нет'}"
            ),
        }
        if not has_positive_triggers:
            warnings.append("В description не найдены явные условия запуска / фразы пользователя ('Use when...', 'Запускать когда...')")
        if not has_negative_triggers:
            warnings.append("В description не найдены явные негативные триггеры / ограничения ('Do NOT use when...', 'Не использовать для...')")

        body_lower = body.lower()
        has_instructions = len(body) > 40 and bool(re.search(r"(?:instruction|guideline|rule|порядок|правил|инструкц|шаг|step|usage)", body_lower))
        has_examples = bool(re.search(r"(?:example|пример|образец|case|scenario|```)", body_lower))

        checks["body_instructions"] = {
            "name": "Инструкции в теле документа",
            "passed": bool(has_instructions),
            "details": "Инструкции присутствуют" if has_instructions else "Тело документа не содержит явных инструкций по использованию",
        }
        checks["body_examples"] = {
            "name": "Примеры использования в теле документа",
            "passed": bool(has_examples),
            "details": "Примеры и сценарии найдены" if has_examples else "Рекомендуется добавить конкретные примеры вызовов или блоков кода",
        }
        if not has_instructions:
            warnings.append("В теле SKILL.md отсутствуют подробные инструкции")
        if not has_examples:
            warnings.append("В теле SKILL.md отсутствуют примеры использования")

        test_queries = cls._generate_test_queries(skill_name or "skill", desc_text, body)
        fixed_desc = cls._generate_fixed_description(skill_name, desc_text, body)

        is_valid = len(critical_errors) == 0
        report_md = cls._format_report(
            skill_name=skill_name or clean_fn,
            filepath=filepath or clean_fn,
            is_valid=is_valid,
            critical_errors=critical_errors,
            warnings=warnings,
            checks=checks,
            test_queries=test_queries,
            original_desc=desc_text,
            fixed_desc=fixed_desc,
        )

        return SkillDiagnosis(
            skill_name=skill_name or clean_fn,
            file_name=clean_fn,
            file_path=filepath,
            is_valid=is_valid,
            critical_errors=critical_errors,
            warnings=warnings,
            checks=checks,
            test_queries=test_queries,
            original_description=desc_text,
            fixed_description=fixed_desc,
            report_markdown=report_md,
        )

    @classmethod
    def _generate_test_queries(cls, name: str, desc: str, body: str) -> Dict[str, List[str]]:
        name_clean = name.replace("-", " ").replace("_", " ").title()
        
        if "design" in name.lower() or "frontend" in name.lower() or "ui" in name.lower():
            positive = [
                f"Сверстай современный адаптивный дашборд с использованием принципов {name_clean}.",
                "Сделай редизайн интерфейса страницы в стиле Linear с четкой типографикой и акцентными цветами.",
                "Проверь верстку на соответствие дизайн-системе и исправь неаккуратные отступы.",
            ]
            negative = [
                "Напиши SQL-запрос для миграции базы данных пользователей.",
                "Сконфигурируй firewall и правила iptables на сервере.",
            ]
        elif "doctor" in name.lower() or "diag" in name.lower() or "skill" in name.lower():
            positive = [
                "Проверь файл SKILL.md на ошибки и сформируй правильный однострочный description.",
                "Продиагностируй скиллы в проекте и исправь многострочные описания.",
                "Сгенерируй тестовые позитивные и негативные запросы для нового скилла.",
            ]
            negative = [
                "Настрой балансировщик нагрузки nginx для веб-приложения.",
                "Оптимизируй производительность вычислений на GPU CUDA.",
            ]
        elif "test" in name.lower() or "qa" in name.lower():
            positive = [
                f"Напиши интеграционные тесты для проверки функционала {name_clean}.",
                "Проверь крайние случаи и сценарии сбоев в обработке запросов.",
                "Составь отчет о тестовом покрытии и упавших тестах.",
            ]
            negative = [
                "Нарисуй макет логотипа для мобильного приложения.",
                "Составь финансовый отчет о расходах на маркетинг.",
            ]
        else:
            positive = [
                f"Примени навык {name_clean} для решения профильной задачи в проекте.",
                f"Используй инструкции из {name_clean}, когда требуется выполнить целевую операцию.",
                f"Помоги с пошаговым выполнением сценария {name_clean}.",
            ]
            negative = [
                "Расскажи прогноз погоды на следующую неделю.",
                "Выполни не связанную системную задачу вне рамок данного навыка.",
            ]

        return {"positive": positive, "negative": negative}

    @classmethod
    def _generate_fixed_description(cls, name: str, original_desc: str, body: str) -> str:
        name_slug = name or "skill"
        clean = " ".join(original_desc.split()).strip()

        if clean and len(clean) > 50 and ("use when" in clean.lower() or "запускать" in clean.lower()) and ("do not use" in clean.lower() or "не использовать" in clean.lower()):
            return clean

        purpose = clean
        if not purpose or len(purpose) < 10:
            purpose = f"Provides expert capabilities and guidance for {name_slug}."
        else:
            purpose = re.split(r"(?:use when|запускать когда|when to use|do not use|не использовать)", purpose, flags=re.IGNORECASE)[0].strip(". ") + "."

        if not purpose.endswith("."):
            purpose += "."

        if "design" in name_slug.lower() or "frontend" in name_slug.lower():
            pos = "Use when creating web interfaces, styling UI components, refining typography and layout, or reviewing frontend design."
            neg = "Do NOT use for backend-only logic, database migrations, or server configuration."
        elif "doctor" in name_slug.lower() or "skill" in name_slug.lower():
            pos = "Use when validating SKILL.md files, fixing multiline descriptions, checking trigger conditions, or running skill diagnostics."
            neg = "Do NOT use for general code refactoring unrelated to agent skills."
        else:
            pos = f"Use when working with {name_slug}, requesting {name_slug} execution, troubleshooting {name_slug} workflows, or optimizing related tasks."
            neg = f"Do NOT use for general unrelated queries or routine tasks outside {name_slug} domain."

        return f"{purpose} {pos} {neg}".strip()

    @classmethod
    def _format_report(
        cls,
        skill_name: str,
        filepath: str,
        is_valid: bool,
        critical_errors: List[str],
        warnings: List[str],
        checks: Dict[str, Dict[str, Any]],
        test_queries: Dict[str, List[str]],
        original_desc: str,
        fixed_desc: str,
    ) -> str:
        status_badge = "🟢 ВАЛИДЕН" if is_valid else "🔴 ОБНАРУЖЕНЫ КРИТИЧЕСКИЕ ОШИБКИ"
        lines = [
            f"# Диагностический отчёт: `{skill_name}`",
            f"**Статус**: {status_badge}  ",
            f"**Файл**: `{filepath}`  ",
            f"**Дата проверки**: `{_utc_timestamp()}`\n",
            "## 1. Результаты проверок чек-листа\n",
        ]

        for _, check in checks.items():
            icon = "✅" if check["passed"] else "❌"
            lines.append(f"- {icon} **{check['name']}**: {check['details']}")

        if critical_errors:
            lines.append("\n## 2. Критические ошибки (требуют обязательного исправления)\n")
            for err in critical_errors:
                lines.append(f"- ⛔ **{err}**")

        if warnings:
            lines.append("\n## 3. Предупреждения и рекомендации\n")
            for warn in warnings:
                lines.append(f"- ⚠️ {warn}")

        lines.append("\n## 4. Проверочные запросы (5 контрольных сценариев)\n")
        lines.append("### Позитивные триггеры (скилл ДОЛЖЕН запускаться):")
        for q in test_queries.get("positive", []):
            lines.append(f"1. *«{q}»*")

        lines.append("\n### Негативные триггеры (скилл НЕ ДОЛЖЕН запускаться):")
        for q in test_queries.get("negative", []):
            lines.append(f"1. *«{q}»*")

        lines.append("\n## 5. Рекомендованное исправление `description`\n")
        lines.append("```yaml")
        lines.append(f"description: {fixed_desc}")
        lines.append("```")

        return "\n".join(lines)


class SkillsService:
    """Central singleton service for discovering, managing, assigning, and tracking skills."""

    _instance: Optional["SkillsService"] = None
    _instance_lock = threading.Lock()

    def __init__(self, usage_path: Optional[Path] = None) -> None:
        self.usage_path = usage_path or (paths.get_config_dir() / "skills_usage.json")
        self._lock = threading.RLock()
        self._usage_cache: Dict[str, Any] = {}
        self._load_usage()

    @classmethod
    def get(cls) -> "SkillsService":
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def _load_usage(self) -> None:
        if self.usage_path.is_file():
            try:
                data = json.loads(self.usage_path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    self._usage_cache = data
            except Exception as exc:
                logger.warning("Could not read skills_usage.json: %s", exc)
                self._usage_cache = {}

    def _save_usage(self) -> None:
        try:
            self.usage_path.parent.mkdir(parents=True, exist_ok=True)
            temp = self.usage_path.with_suffix(".tmp")
            temp.write_text(json.dumps(self._usage_cache, ensure_ascii=False, indent=2), encoding="utf-8")
            temp.replace(self.usage_path)
        except Exception as exc:
            logger.error("Failed to save skills_usage.json: %s", exc)

    def get_discovery_paths(self) -> List[Path]:
        """Return list of standard directories to scan for skills."""
        search_dirs: List[Path] = []

        hermes_skills = paths.get_hermes_home() / "skills"
        search_dirs.append(hermes_skills)

        claude_skills = Path.home() / ".claude" / "skills"
        search_dirs.append(claude_skills)

        dot_hermes_skills = Path.home() / ".hermes" / "skills"
        if dot_hermes_skills not in search_dirs:
            search_dirs.append(dot_hermes_skills)

        repo_agents = paths.get_repo_root() / ".agents" / "skills"
        search_dirs.append(repo_agents)

        try:
            settings = get_hub_settings()
            custom_paths = settings.get("skills_paths") or []
            if isinstance(custom_paths, str):
                custom_paths = [p.strip() for p in custom_paths.split(",") if p.strip()]
            for cp in custom_paths:
                p = Path(cp).expanduser().resolve()
                if p not in search_dirs:
                    search_dirs.append(p)
        except Exception:
            pass

        return search_dirs

    def discover_skills(self, extra_paths: Optional[List[Path | str]] = None) -> List[SkillInfo]:
        """Scan directories and return all discovered skills."""
        with self._lock:
            all_dirs = self.get_discovery_paths()
            if extra_paths:
                for ep in extra_paths:
                    p = Path(ep).expanduser().resolve()
                    if p not in all_dirs:
                        all_dirs.append(p)

            discovered: Dict[str, SkillInfo] = {}

            for base_dir in all_dirs:
                if not base_dir.is_dir():
                    continue

                try:
                    for skill_file in base_dir.glob("**/SKILL.md"):
                        if not skill_file.is_file():
                            continue
                        try:
                            content = skill_file.read_text(encoding="utf-8")
                        except Exception:
                            continue

                        fm, body, errors = parse_skill_frontmatter(content)
                        skill_name = str(fm.get("name") or skill_file.parent.name).strip()
                        if not skill_name:
                            skill_name = skill_file.parent.name

                        diagnosis = SkillDoctor.diagnose(content, filename=skill_file.name, filepath=str(skill_file))

                        assigned = self._get_assigned_agents(skill_name)

                        usage_data = self._usage_cache.get(skill_name, {})
                        usage_count = int(usage_data.get("usage_count", 0))
                        success_count = int(usage_data.get("success_count", 0))
                        last_used = usage_data.get("last_used_at")

                        info = SkillInfo(
                            name=skill_name,
                            description=str(fm.get("description") or ""),
                            path=str(skill_file),
                            source_dir=str(base_dir),
                            tags=list(fm.get("tags") or []),
                            body=body,
                            assigned_agents=assigned,
                            usage_count=usage_count,
                            success_count=success_count,
                            last_used_at=last_used,
                            is_valid=diagnosis.is_valid,
                            critical_errors=diagnosis.critical_errors,
                            warnings=diagnosis.warnings,
                        )

                        if skill_name not in discovered or str(skill_file).startswith(str(paths.get_repo_root())):
                            discovered[skill_name] = info
                except Exception as exc:
                    logger.debug("Error scanning directory %s for skills: %s", base_dir, exc)

            return sorted(discovered.values(), key=lambda s: s.name)

    def _get_assigned_agents(self, skill_name: str) -> List[str]:
        """Find which agents in workflow_state.json have this skill assigned."""
        from antigravity_provider.router.workflow_service import WorkflowService

        try:
            wf_service = WorkflowService.get()
            assigned: List[str] = []
            for agent in wf_service.agents.values():
                tools = agent.tools or []
                skills_meta = agent.metadata.get("skills", []) if agent.metadata else []
                if skill_name in tools or f"skill:{skill_name}" in tools or skill_name in skills_meta:
                    assigned.append(agent.id)
            return assigned
        except Exception:
            return []

    def get_skill(self, name_or_slug: str) -> Optional[SkillInfo]:
        """Find a single skill by name."""
        all_skills = self.discover_skills()
        for s in all_skills:
            if s.name == name_or_slug or Path(s.path).parent.name == name_or_slug:
                return s
        return None

    def assign_skill(self, skill_name: str, agent_id: str) -> Dict[str, Any]:
        """Assign skill to an agent in workflow_state.json."""
        from antigravity_provider.router.workflow_service import WorkflowService

        with self._lock:
            wf = WorkflowService.get()
            if agent_id not in wf.agents:
                raise ValueError(f"Субагент '{agent_id}' не найден в конфигурации")

            agent = wf.agents[agent_id]
            skill_tag = f"skill:{skill_name}"

            current_tools = list(agent.tools or [])
            if skill_name not in current_tools and skill_tag not in current_tools:
                current_tools.append(skill_tag)
                agent.tools = current_tools

            if not isinstance(agent.metadata, dict):
                agent.metadata = {}
            current_skills = list(agent.metadata.get("skills", []))
            if skill_name not in current_skills:
                current_skills.append(skill_name)
                agent.metadata["skills"] = current_skills

            wf._save()
            wf._event("SKILL_ASSIGNED", f"Скилл '{skill_name}' назначен субагенту '{agent.name}'", agent_id=agent_id)

            return {
                "ok": True,
                "message": f"Скилл '{skill_name}' успешно назначен агенту '{agent.name}'",
                "agent_id": agent_id,
                "skill_name": skill_name,
                "tools": agent.tools,
            }

    def unassign_skill(self, skill_name: str, agent_id: str) -> Dict[str, Any]:
        """Remove assigned skill from an agent in workflow_state.json."""
        from antigravity_provider.router.workflow_service import WorkflowService

        with self._lock:
            wf = WorkflowService.get()
            if agent_id not in wf.agents:
                raise ValueError(f"Субагент '{agent_id}' не найден в конфигурации")

            agent = wf.agents[agent_id]
            skill_tag = f"skill:{skill_name}"

            current_tools = [t for t in (agent.tools or []) if t != skill_name and t != skill_tag]
            agent.tools = current_tools

            if isinstance(agent.metadata, dict) and "skills" in agent.metadata:
                agent.metadata["skills"] = [s for s in agent.metadata["skills"] if s != skill_name]

            wf._save()
            wf._event("SKILL_UNASSIGNED", f"Скилл '{skill_name}' снят с субагента '{agent.name}'", agent_id=agent_id)

            return {
                "ok": True,
                "message": f"Скилл '{skill_name}' удалён у агента '{agent.name}'",
                "agent_id": agent_id,
                "skill_name": skill_name,
                "tools": agent.tools,
            }

    def record_skill_usage(
        self,
        skill_name: str,
        agent_id: str,
        caller_id: Optional[str] = None,
        success: bool = True,
        duration_ms: Optional[float] = None,
    ) -> None:
        """Record skill invocation for truthful analytics."""
        with self._lock:
            entry = self._usage_cache.setdefault(
                skill_name,
                {
                    "skill_name": skill_name,
                    "usage_count": 0,
                    "success_count": 0,
                    "failed_count": 0,
                    "last_used_at": None,
                    "last_agent_id": None,
                    "call_history": [],
                },
            )
            entry["usage_count"] = int(entry.get("usage_count", 0)) + 1
            if success:
                entry["success_count"] = int(entry.get("success_count", 0)) + 1
            else:
                entry["failed_count"] = int(entry.get("failed_count", 0)) + 1
            now = _utc_timestamp()
            entry["last_used_at"] = now
            entry["last_agent_id"] = agent_id

            calls = entry.setdefault("call_history", [])
            calls.append({
                "timestamp": now,
                "agent_id": agent_id,
                "caller_id": caller_id,
                "success": success,
                "duration_ms": duration_ms,
            })
            entry["call_history"] = calls[-50:]

            self._save_usage()

    def get_skills_usage(self) -> Dict[str, Any]:
        """Return truthful statistics of skill invocations across the system."""
        with self._lock:
            total_calls = sum(int(item.get("usage_count", 0)) for item in self._usage_cache.values())
            if total_calls == 0:
                return {
                    "total_calls": 0,
                    "has_usage": False,
                    "message": "Н/Д: вызовы со скиллами ещё не регистрировались",
                    "skills": {},
                }

            return {
                "total_calls": total_calls,
                "has_usage": True,
                "message": f"Зарегистрировано {total_calls} вызовов скиллов",
                "skills": dict(self._usage_cache),
            }

    def diagnose_skill(
        self,
        skill_name: Optional[str] = None,
        filepath: Optional[str] = None,
        content: Optional[str] = None,
    ) -> SkillDiagnosis:
        """Run SkillDoctor diagnostics on a skill by name, path or content."""
        if content is not None:
            fn = Path(filepath).name if filepath else "SKILL.md"
            return SkillDoctor.diagnose(content, filename=fn, filepath=filepath or "")

        if filepath:
            p = Path(filepath)
            if not p.is_file():
                raise FileNotFoundError(f"Файл скилла '{filepath}' не найден")
            return SkillDoctor.diagnose(p.read_text(encoding="utf-8"), filename=p.name, filepath=str(p))

        if skill_name:
            skill = self.get_skill(skill_name)
            if not skill:
                raise FileNotFoundError(f"Скилл '{skill_name}' не найден среди обнаруженных скиллов")
            p = Path(skill.path)
            return SkillDoctor.diagnose(p.read_text(encoding="utf-8"), filename=p.name, filepath=str(p))

        raise ValueError("Укажите skill_name, filepath или content для диагностики")
