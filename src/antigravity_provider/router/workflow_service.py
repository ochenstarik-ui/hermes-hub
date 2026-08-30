"""Hermes Hub A30 / A36 workflow runtime and persistence layer."""
from __future__ import annotations

import datetime
import json
import logging
import re
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

from antigravity_provider import paths
from antigravity_provider.router.router_config import (
    RolePolicy,
    load_router_config,
    save_router_config,
)

logger = logging.getLogger("hermes.router.workflow")


_AUTH_BEARER_RE = re.compile(r"Bearer\s+[A-Za-z0-9._~+/-]+", re.IGNORECASE)
_ACCESS_TOKEN_PARAM_RE = re.compile(r"(access_token=)[^&]+", re.IGNORECASE)


def sanitize_run_data(data: Any) -> Any:
    """Sanitize data for saving to workflow_run_state.json, masking secrets and tokens."""
    if isinstance(data, dict):
        result = {}
        for k, v in data.items():
            k_lower = str(k).lower()
            if any(s in k_lower for s in ["api_key", "token", "password", "secret", "client_secret", "jwt"]):
                result[k] = "***"
            elif isinstance(v, (dict, list)):
                result[k] = sanitize_run_data(v)
            elif isinstance(v, str):
                s_val = _AUTH_BEARER_RE.sub("Bearer ***", v)
                s_val = _ACCESS_TOKEN_PARAM_RE.sub(r"\1***", s_val)
                result[k] = s_val
            else:
                result[k] = v
        return result
    elif isinstance(data, list):
        return [sanitize_run_data(item) for item in data]
    elif isinstance(data, str):
        s_val = _AUTH_BEARER_RE.sub("Bearer ***", data)
        s_val = _ACCESS_TOKEN_PARAM_RE.sub(r"\1***", s_val)
        return s_val
    return data


def get_last_run_state(path: Optional[Path] = None) -> Optional[dict[str, Any]]:
    """Return the last saved run state from workflow_run_state.json."""
    target_path = path or paths.get_workflow_run_state_path()
    if not target_path.is_file():
        return None
    try:
        data = json.loads(target_path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None

EDGE_CONDITIONS = {
    "SUCCESS",
    "ALWAYS",
    "NEXT",
    "REVIEW_PASSED",
    "REVIEW_FAILED",
    "ERROR",
    "COMPLETED",
    "ACCEPTED",
}


def _utc_timestamp() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _slug(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_-]+", "-", value.strip()).strip("-").lower()
    return cleaned or f"agent-{uuid.uuid4().hex[:6]}"


def _safe_agent_file(path_str: str, agent_id: str) -> tuple[Path, str]:
    home = paths.get_hermes_home().resolve()
    if not path_str or not path_str.strip():
        relative = f"agents/{_slug(agent_id)}.md"
        return (home / relative).resolve(), relative

    raw = Path(path_str.strip())
    if raw.is_absolute():
        resolved = raw.resolve()
    else:
        resolved = (home / raw).resolve()

    try:
        rel = resolved.relative_to(home).as_posix()
    except ValueError as exc:
        raise ValueError("Agent File должен находиться внутри каталога HERMES_HOME") from exc
    return resolved, rel


@dataclass
class AgentDefinition:
    id: str
    name: str
    role: str
    description: str = ""
    agent_file: str = ""
    tools: list[str] = field(default_factory=list)
    memory_configuration: dict[str, Any] = field(default_factory=dict)
    execution_policy: dict[str, Any] = field(default_factory=dict)
    timeout: int = 180
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    position: dict[str, float] = field(default_factory=lambda: {"x": 80.0, "y": 80.0})
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class WorkflowEdge:
    id: str
    source: str
    target: str
    condition: str = "SUCCESS"
    label: str = ""
    max_iterations: Optional[int] = None


@dataclass
class WorkflowDefinition:
    id: str = "main"
    name: str = "Основной workflow"
    edges: list[WorkflowEdge] = field(default_factory=list)
    max_iterations: int = 5
    escalation_agent_id: Optional[str] = None
    start_agent_id: Optional[str] = None


def get_canonical_a36_pipeline() -> WorkflowDefinition:
    """Return canonical Antigravity 4-agent workflow with nested feedback loops."""
    return WorkflowDefinition(
        id="a36-pipeline",
        name="Конвейер Antigravity (Оркестратор, 2 кодера, ревьюер)",
        start_agent_id="manager",
        max_iterations=5,
        edges=[
            WorkflowEdge(
                id="edge-manager-to-dev1",
                source="manager",
                target="developer-1",
                condition="SUCCESS",
                label="Постановка задачи",
            ),
            WorkflowEdge(
                id="edge-dev1-to-dev2",
                source="developer-1",
                target="developer-2",
                condition="SUCCESS",
                label="Реализация на проверку",
            ),
            WorkflowEdge(
                id="edge-dev2-to-dev1",
                source="developer-2",
                target="developer-1",
                condition="REVIEW_FAILED",
                label="Доработка Кодеру 1",
                max_iterations=5,
            ),
            WorkflowEdge(
                id="edge-dev2-to-reviewer",
                source="developer-2",
                target="code-reviewer",
                condition="REVIEW_PASSED",
                label="Одобрено Кодером 2",
            ),
            WorkflowEdge(
                id="edge-reviewer-to-dev2",
                source="code-reviewer",
                target="developer-2",
                condition="REVIEW_FAILED",
                label="Переделка Кодеру 2",
                max_iterations=5,
            ),
            WorkflowEdge(
                id="edge-reviewer-to-manager",
                source="code-reviewer",
                target="manager",
                condition="REVIEW_PASSED",
                label="Приёмка",
            ),
        ],
    )


@dataclass
class WorkflowEvent:
    timestamp: str
    type: str
    message: str
    level: str = "info"
    run_id: Optional[str] = None
    agent_id: Optional[str] = None
    iteration: Optional[int] = None
    provider: Optional[str] = None
    account: Optional[str] = None
    model: Optional[str] = None
    duration_seconds: Optional[float] = None
    error: Optional[str] = None


class WorkflowService:
    _instance: Optional["WorkflowService"] = None
    _instance_lock = threading.Lock()

    def __init__(self, state_path: Optional[Path] = None, run_state_path: Optional[Path] = None) -> None:
        self.state_path = state_path or paths.get_workflow_state_path()
        self.run_state_path = run_state_path or paths.get_workflow_run_state_path()
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.agents: dict[str, AgentDefinition] = {}
        self.workflow = WorkflowDefinition()
        self.events: list[WorkflowEvent] = []
        self.run: dict[str, Any] = self._idle_run()
        self._completed_steps: list[dict[str, Any]] = []
        self._load()
        self._migrate_router_roles()

    @classmethod
    def get(cls) -> "WorkflowService":
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    @staticmethod
    def _idle_run() -> dict[str, Any]:
        return {
            "id": None,
            "status": "idle",
            "current_agent_id": None,
            "current_task": None,
            "iteration": 0,
            "started_at": None,
            "finished_at": None,
            "elapsed_seconds": None,
            "last_result": None,
            "error": None,
            "agent_states": {},
        }

    def _load(self) -> None:
        # 1. Load run state from workflow_run_state.json
        if self.run_state_path.is_file():
            try:
                run_state = json.loads(self.run_state_path.read_text(encoding="utf-8"))
                if isinstance(run_state, dict):
                    self._completed_steps = list(run_state.get("completed_steps", []))
                    if run_state.get("status") in {"RUNNING", "running", "STOPPING", "stopping"}:
                        run_state["status"] = "INTERRUPTED"
                        run_state["interruption_reason"] = "Прогон был прерван перезапуском сервера или сбоем процесса"
                        run_state["updated_at"] = _utc_timestamp()
                        sanitized = sanitize_run_data(run_state)
                        self.run_state_path.parent.mkdir(parents=True, exist_ok=True)
                        temp = self.run_state_path.with_suffix(".tmp")
                        temp.write_text(json.dumps(sanitized, ensure_ascii=False, indent=2), encoding="utf-8")
                        temp.replace(self.run_state_path)
            except Exception:
                self._completed_steps = []

        # 2. Load workflow definition and events from workflow_state.json
        if not self.state_path.is_file():
            return
        try:
            raw = json.loads(self.state_path.read_text(encoding="utf-8"))
            from antigravity_provider.router.role_registry import RoleRegistry

            def _canon(agent_id: str) -> str:
                try:
                    return RoleRegistry.resolve_canonical_role(agent_id)
                except Exception:
                    return agent_id

            self.agents = {}
            for item in raw.get("agents", []):
                if not isinstance(item, dict) or not item.get("id"):
                    continue
                item = dict(item)
                item["id"] = _canon(item["id"])
                if item.get("role"):
                    item["role"] = _canon(item["role"])
                self.agents.setdefault(item["id"], AgentDefinition(**item))

            wf = raw.get("workflow") or {}
            edges = []
            valid_edge_keys = {
                "id",
                "source",
                "target",
                "condition",
                "label",
                "max_iterations",
            }
            for edge in wf.pop("edges", []):
                if not isinstance(edge, dict):
                    continue
                edge = dict(edge)
                for key in ("source", "target", "from_agent", "to_agent"):
                    if edge.get(key):
                        edge[key] = _canon(edge[key])
                filtered_edge = {k: v for k, v in edge.items() if k in valid_edge_keys}
                edges.append(WorkflowEdge(**filtered_edge))
            self.workflow = WorkflowDefinition(edges=edges, **wf)
            self.events = [WorkflowEvent(**event) for event in raw.get("events", [])[-200:]]
            self.run = raw.get("run") or self._idle_run()
            if self.run.get("status") in {"running", "stopping"}:
                self.run["status"] = "interrupted"
                self.run["error"] = "Выполнение прервано перезапуском Hermes Hub; checkpoint сохранён"
                self._event("WORKFLOW_INTERRUPTED", self.run["error"], level="warning")
        except (OSError, ValueError, TypeError):
            self.agents = {}
            self.workflow = WorkflowDefinition()
            self.events = []
            self.run = self._idle_run()

    def _save_run_state(
        self,
        status: str,
        step_index: int = 0,
        current_agent: Optional[str] = None,
        iteration: int = 1,
        completed_step: Optional[dict[str, Any]] = None,
        interruption_reason: Optional[str] = None,
    ) -> None:
        if completed_step:
            self._completed_steps.append(sanitize_run_data(completed_step))

        state_payload = {
            "run_id": self.run.get("id"),
            "status": status.upper(),
            "started_at": self.run.get("started_at"),
            "updated_at": _utc_timestamp(),
            "current_step_index": step_index,
            "current_agent_id": current_agent,
            "iteration_count": iteration,
            "completed_steps": list(self._completed_steps),
            "interruption_reason": interruption_reason,
        }
        sanitized = sanitize_run_data(state_payload)
        try:
            self.run_state_path.parent.mkdir(parents=True, exist_ok=True)
            temp = self.run_state_path.with_suffix(".tmp")
            temp.write_text(json.dumps(sanitized, ensure_ascii=False, indent=2), encoding="utf-8")
            temp.replace(self.run_state_path)
        except Exception:
            pass

    def get_last_run_state(self) -> Optional[dict[str, Any]]:
        """Return the last saved run state from workflow_run_state.json."""
        return get_last_run_state(self.run_state_path)

    def _save(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": 1,
            "agents": [asdict(agent) for agent in self.agents.values()],
            "workflow": asdict(self.workflow),
            "events": [asdict(event) for event in self.events[-200:]],
            "run": self.run,
        }
        temp = self.state_path.with_suffix(".tmp")
        temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(self.state_path)

    def _migrate_router_roles(self) -> None:
        config = load_router_config()
        changed = False
        for index, (role_id, policy) in enumerate(config.roles.items()):
            if role_id in self.agents:
                continue
            target, relative = _safe_agent_file("", role_id)
            name = role_id.replace("-", " ").title()
            description = ""
            try:
                from antigravity_provider.router.role_registry import get_role_definition

                definition = get_role_definition(role_id)
                name = getattr(definition, "display_name_ru", None) or getattr(definition, "name", None) or name
                description = getattr(definition, "description_ru", "") or getattr(definition, "description", "")
            except (ImportError, AttributeError, TypeError):
                pass
            agent = AgentDefinition(
                id=role_id,
                name=name,
                role=role_id,
                description=description,
                agent_file=relative,
                position={"x": 70.0 + (index % 2) * 280.0, "y": 45.0 + (index // 2) * 125.0},
            )
            self.agents[role_id] = agent
            self._ensure_file(target, agent)
            changed = True

        if not self.workflow.edges:
            a36_roles = {"manager", "developer-1", "developer-2", "code-reviewer"}
            if a36_roles.issubset(self.agents.keys()):
                self.workflow = get_canonical_a36_pipeline()
                if "manager" in self.agents:
                    self.agents["manager"].position = {"x": 60.0, "y": 140.0}
                if "developer-1" in self.agents:
                    self.agents["developer-1"].position = {"x": 320.0, "y": 140.0}
                if "developer-2" in self.agents:
                    self.agents["developer-2"].position = {"x": 580.0, "y": 140.0}
                if "code-reviewer" in self.agents:
                    self.agents["code-reviewer"].position = {"x": 840.0, "y": 140.0}
                changed = True

        if changed:
            self._save()

    @staticmethod
    def _ensure_file(target: Path, agent: AgentDefinition) -> None:
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            body = f"# {agent.name}\n\n## Роль\n\n{agent.role}\n\n## Назначение\n\n{agent.description or 'Инструкции ещё не заполнены.'}\n"
            target.write_text(body, encoding="utf-8")

    def _execution_config(self, agent: AgentDefinition) -> dict[str, Any]:
        config = load_router_config()
        policy = config.roles.get(agent.role)
        profile_id = policy.preferred_chain[0] if policy and policy.preferred_chain else None
        profile = config.profiles.get(profile_id) if profile_id else None
        model = policy.default_model if policy else None
        if not model and profile and profile.preferred_models:
            model = profile.preferred_models[0]
        return {
            "provider": profile.provider if profile else None,
            "account": profile_id,
            "model": model,
            "timeout": agent.timeout,
            "temperature": agent.temperature,
            "max_tokens": agent.max_tokens,
            "unavailable_reason": None if profile else "Для роли не назначен доступный аккаунт",
        }

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            agents = []
            for agent in self.agents.values():
                item = asdict(agent)
                target, relative = _safe_agent_file(agent.agent_file, agent.id)
                item["agent_file"] = relative
                item["agent_file_exists"] = target.is_file()
                item["execution_config"] = self._execution_config(agent)
                item["runtime_state"] = (self.run.get("agent_states") or {}).get(agent.id, "waiting")
                agents.append(item)
            return {
                "agents": agents,
                "definition": asdict(self.workflow),
                "run": dict(self.run),
                "events": [asdict(event) for event in self.events[-60:]],
                "is_loading": False,
            }

    def read_agent_file(self, agent_id: str) -> dict[str, Any]:
        with self._lock:
            agent = self._require_agent(agent_id)
            target, relative = _safe_agent_file(agent.agent_file, agent.id)
            if not target.is_file():
                return {"path": relative, "exists": False, "content": None, "reason": "Файл не найден на диске"}
            return {"path": relative, "exists": True, "content": target.read_text(encoding="utf-8")}

    def save_agent_file(self, agent_id: str, content: str) -> dict[str, Any]:
        with self._lock:
            agent = self._require_agent(agent_id)
            target, relative = _safe_agent_file(agent.agent_file, agent.id)
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_suffix(".md.tmp")
            temporary.write_text(str(content), encoding="utf-8")
            temporary.replace(target)
            self._event("AGENT_FILE_SAVED", f"Сохранён Agent File {relative}", agent_id=agent_id)
            self._save()
            return {"path": relative, "exists": True}

    def create_agent(self, data: dict[str, Any]) -> AgentDefinition:
        name = str(data.get("name") or "").strip()
        role = _slug(str(data.get("role") or name))
        agent_id = _slug(str(data.get("id") or role))
        if not name:
            raise ValueError("Укажите название агента")
        with self._lock:
            if self.run.get("status") in {"running", "stopping"}:
                raise ValueError("Нельзя менять конфигурацию агентов во время выполнения workflow")
            if agent_id in self.agents:
                raise ValueError("Агент с таким идентификатором уже существует")
            profile_id = str(data.get("account") or data.get("profile_id") or "").strip()
            config = load_router_config()
            if profile_id and profile_id not in config.profiles:
                raise ValueError("Выбранный аккаунт отсутствует в маршрутизаторе")
            config.roles[role] = RolePolicy(
                role_name=role,
                preferred_chain=[profile_id] if profile_id else [],
                fallback_capabilities=list(data.get("fallback_capabilities") or [role]),
                default_model=data.get("model") or None,
            )
            if not save_router_config(config):
                raise OSError("Не удалось сохранить назначение агента")
            target, relative = _safe_agent_file(str(data.get("agent_file") or ""), agent_id)
            agent = AgentDefinition(
                id=agent_id,
                name=name,
                role=role,
                description=str(data.get("description") or ""),
                agent_file=relative,
                tools=[str(item) for item in data.get("tools", [])],
                memory_configuration=dict(data.get("memory_configuration") or {}),
                execution_policy=dict(data.get("execution_policy") or {}),
                timeout=max(1, int(data.get("timeout") or 180)),
                temperature=float(data["temperature"]) if data.get("temperature") is not None else None,
                max_tokens=int(data["max_tokens"]) if data.get("max_tokens") is not None else None,
                position=dict(data.get("position") or {"x": 80.0, "y": 80.0}),
            )
            self.agents[agent_id] = agent
            copy_from = data.get("copy_from")
            if copy_from:
                source = self.read_agent_file(str(copy_from))
                target.write_text(source.get("content") or "", encoding="utf-8")
            else:
                self._ensure_file(target, agent)
            self._event("AGENT_CREATED", f"Создан агент «{name}»", agent_id=agent_id)
            self._save()
            return agent

    def update_agent(self, agent_id: str, data: dict[str, Any]) -> AgentDefinition:
        with self._lock:
            if self.run.get("status") in {"running", "stopping"}:
                raise ValueError("Нельзя менять конфигурацию агентов во время выполнения workflow")
            agent = self._require_agent(agent_id)
            config = load_router_config()
            policy = config.roles.get(agent.role)
            if not policy:
                policy = RolePolicy(role_name=agent.role)
                config.roles[agent.role] = policy
            profile_id = str(data.get("account") or data.get("profile_id") or "").strip()
            if profile_id:
                profile = config.profiles.get(profile_id)
                if not profile:
                    raise ValueError("Выбранный аккаунт отсутствует в маршрутизаторе")
                requested_provider = str(data.get("provider") or "").strip()
                if requested_provider and profile.provider != requested_provider:
                    raise ValueError("Аккаунт не принадлежит выбранному провайдеру")
                policy.preferred_chain = [profile_id] + [item for item in policy.preferred_chain if item != profile_id]
            if "model" in data:
                model = str(data.get("model") or "").strip() or None
                if model and policy.preferred_chain:
                    eff_profile_id = policy.preferred_chain[0]
                    eff_profile = config.profiles.get(eff_profile_id)
                    if eff_profile and eff_profile.preferred_models and model not in eff_profile.preferred_models:
                        raise ValueError(f"Модель {model} не доступна для профиля {eff_profile_id}")
                policy.default_model = model
            if not save_router_config(config):
                raise OSError("Не удалось сохранить назначение агента")
            for attr in ("name", "description"):
                if attr in data:
                    setattr(agent, attr, str(data[attr]).strip())
            for attr in ("tools", "memory_configuration", "execution_policy", "position"):
                if attr in data:
                    setattr(agent, attr, type(getattr(agent, attr))(data[attr]))
            for attr in ("timeout", "max_tokens"):
                if attr in data and data[attr] is not None:
                    setattr(agent, attr, int(data[attr]))
            if "temperature" in data:
                agent.temperature = float(data["temperature"]) if data["temperature"] is not None else None
            self._event("AGENT_UPDATED", f"Обновлён агент «{agent.name}»", agent_id=agent_id)
            self._save()
            return agent

    def delete_agent(self, agent_id: str, force: bool = False) -> dict[str, Any]:
        with self._lock:
            if self.run.get("status") in {"running", "stopping"}:
                raise ValueError("Нельзя удалять агентов во время выполнения workflow")
            agent = self._require_agent(agent_id)
            edge_ids = [edge.id for edge in self.workflow.edges if edge.source == agent_id or edge.target == agent_id]
            route_used = bool(load_router_config().roles.get(agent.role))
            consequences = {"workflow_edges": edge_ids, "routing_role": agent.role if route_used else None}
            if (edge_ids or route_used) and not force:
                return {"deleted": False, "confirmation_required": True, "consequences": consequences}
            config = load_router_config()
            config.roles.pop(agent.role, None)
            if not save_router_config(config):
                raise OSError("Не удалось удалить роль из маршрутизатора")
            self.workflow.edges = [edge for edge in self.workflow.edges if edge.id not in edge_ids]
            if self.workflow.start_agent_id == agent_id:
                self.workflow.start_agent_id = None
            if self.workflow.escalation_agent_id == agent_id:
                self.workflow.escalation_agent_id = None
            target, _ = _safe_agent_file(agent.agent_file, agent.id)
            if target.exists():
                try:
                    target.unlink()
                except OSError:
                    pass
            self.agents.pop(agent_id, None)
            self._event("AGENT_DELETED", f"Удалён агент «{agent.name}»", agent_id=agent_id, level="warning")
            self._save()
            return {"deleted": True, "consequences": consequences}

    def save_workflow(self, data: dict[str, Any]) -> WorkflowDefinition:
        with self._lock:
            if self.run.get("status") in {"running", "stopping"}:
                raise ValueError("Нельзя менять граф в режиме LIVE во время выполнения")
            edges: list[WorkflowEdge] = []
            seen: set[str] = set()
            for raw_edge in data.get("edges", []):
                source, target = str(raw_edge.get("source") or ""), str(raw_edge.get("target") or "")
                condition = str(raw_edge.get("condition") or "SUCCESS").upper()
                if source not in self.agents or target not in self.agents:
                    raise ValueError("Ребро ссылается на отсутствующего агента")
                if condition not in EDGE_CONDITIONS:
                    raise ValueError(f"Неизвестное условие перехода: {condition}")
                edge_id = str(raw_edge.get("id") or f"edge-{uuid.uuid4().hex[:10]}")
                if edge_id in seen:
                    raise ValueError("Идентификаторы рёбер должны быть уникальны")
                seen.add(edge_id)
                edge_max_it = raw_edge.get("max_iterations")
                if edge_max_it is not None:
                    try:
                        edge_max_it = int(edge_max_it)
                        if not 1 <= edge_max_it <= 100:
                            edge_max_it = None
                    except (ValueError, TypeError):
                        edge_max_it = None
                edges.append(
                    WorkflowEdge(
                        id=edge_id,
                        source=source,
                        target=target,
                        condition=condition,
                        label=str(raw_edge.get("label") or ""),
                        max_iterations=edge_max_it,
                    )
                )
            max_iterations = int(data.get("max_iterations") or self.workflow.max_iterations)
            if not 1 <= max_iterations <= 100:
                raise ValueError("Предел итераций должен быть от 1 до 100")
            for raw_agent in data.get("agents", []):
                agent = self.agents.get(str(raw_agent.get("id") or ""))
                pos = raw_agent.get("position")
                if agent and isinstance(pos, dict):
                    agent.position = {"x": float(pos.get("x", 0)), "y": float(pos.get("y", 0))}
            self.workflow = WorkflowDefinition(
                id=str(data.get("id") or self.workflow.id),
                name=str(data.get("name") or self.workflow.name),
                edges=edges,
                max_iterations=max_iterations,
                escalation_agent_id=data.get("escalation_agent_id") or None,
                start_agent_id=data.get("start_agent_id") or None,
            )
            self._event("WORKFLOW_SAVED", f"Сохранён workflow «{self.workflow.name}»")
            self._save()
            return self.workflow

    def start(self, task: str) -> dict[str, Any]:
        task = str(task or "").strip()
        if not task:
            raise ValueError("Для запуска укажите реальную задачу")
        with self._lock:
            if self._thread and self._thread.is_alive():
                raise ValueError("Workflow уже выполняется")
            start_id = self.workflow.start_agent_id or (next(iter(self.agents), None))
            if not start_id or start_id not in self.agents:
                raise ValueError("В workflow нет стартового агента")
            self._stop.clear()
            self._completed_steps = []
            self.run = self._idle_run()
            self.run.update({
                "id": uuid.uuid4().hex,
                "status": "running",
                "current_agent_id": start_id,
                "current_task": task,
                "iteration": 1,
                "started_at": _utc_timestamp(),
            })
            self._event("WORKFLOW_STARTED", "Workflow запущен", run_id=self.run["id"], iteration=1)
            self._save()
            self._save_run_state("RUNNING", step_index=0, current_agent=start_id, iteration=1)
            self._thread = threading.Thread(target=self._execute, name="HermesWorkflow", daemon=True)
            self._thread.start()
            return dict(self.run)

    def stop(self) -> dict[str, Any]:
        with self._lock:
            if self.run.get("status") != "running":
                raise ValueError("Нет выполняющегося workflow")
            self.run["status"] = "stopping"
            self._stop.set()
            self._event("WORKFLOW_STOP_REQUESTED", "Запрошена остановка workflow", level="warning")
            self._save()
            self._save_run_state(
                "STOPPED",
                step_index=len(self._completed_steps),
                current_agent=self.run.get("current_agent_id"),
                iteration=self.run.get("iteration", 1),
                interruption_reason="Остановлено пользователем",
            )
            return dict(self.run)

    def _execute(self) -> None:
        from antigravity_provider.router.router_engine import get_router_engine

        started = time.monotonic()
        context = str(self.run.get("current_task") or "")
        current = str(self.run.get("current_agent_id") or "")
        visited: dict[str, int] = {}
        edge_counts: dict[str, int] = {}
        try:
            engine = get_router_engine()
            engine.reload_config()
            while current and not self._stop.is_set():
                with self._lock:
                    agent = self._require_agent(current)
                    visited[current] = visited.get(current, 0) + 1
                    iteration = visited[current]
                    global_iteration = sum(visited.values())
                    self.run.update({
                        "current_agent_id": current,
                        "iteration": iteration,
                        "global_iteration": global_iteration,
                        "max_iterations": self.workflow.max_iterations,
                    })
                    step_idx = len(self._completed_steps)
                    if iteration > self.workflow.max_iterations:
                        message = f"Достигнут предел итераций: {self.workflow.max_iterations}"
                        self.run.update({"status": "failed", "error": message})
                        self._event("WORKFLOW_MAX_ITERATIONS", message, level="error", agent_id=current, iteration=iteration)
                        self._save_run_state("FAILED", step_index=step_idx, current_agent=current, iteration=iteration, interruption_reason=message)
                        break
                    file_data = self.read_agent_file(current)
                    if not file_data["exists"]:
                        raise FileNotFoundError(f"{file_data['path']}: {file_data.get('reason')}")
                    self.run.setdefault("agent_states", {})[current] = (
                        "reviewing" if "review" in agent.role.lower() else "working"
                    )
                    self._event("AGENT_STARTED", f"{agent.name} начал выполнение", agent_id=current, iteration=iteration)
                    self._save()
                    self._save_run_state("RUNNING", step_index=step_idx, current_agent=current, iteration=iteration)
                request = {
                    "model": self._execution_config(agent).get("model"),
                    "messages": [
                        {"role": "system", "content": file_data["content"]},
                        {"role": "user", "content": context},
                    ],
                    "timeout": agent.timeout,
                    "metadata": {"role": agent.role, "workflow_run_id": self.run["id"]},
                }
                if agent.temperature is not None:
                    request["temperature"] = agent.temperature
                if agent.max_tokens is not None:
                    request["max_tokens"] = agent.max_tokens
                step_started = time.monotonic()
                response = engine.route_request(request, role=agent.role, session_id=self.run["id"])
                duration = round(time.monotonic() - step_started, 3)
                text = self._response_text(response)
                status = self._result_status(response, text)
                metadata = response.get("router_metadata", {}) if isinstance(response, dict) else {}
                with self._lock:
                    self.run["last_result"] = {"status": status, "content": text, "router_metadata": metadata}
                    self.run.setdefault("agent_states", {})[current] = (
                        "error" if status in {"ERROR", "REVIEW_FAILED"} else "completed"
                    )
                    self._event(
                        "AGENT_COMPLETED",
                        f"{agent.name}: {status}",
                        level="success" if status not in {"ERROR", "REVIEW_FAILED"} else "warning",
                        agent_id=current,
                        iteration=iteration,
                        provider=metadata.get("provider"),
                        account=metadata.get("profile_id"),
                        model=metadata.get("selected_model") or (metadata.get("selection_trace") or {}).get("selected_model"),
                        duration_seconds=duration,
                        error=text if status == "ERROR" else None,
                    )
                    step_summary = {
                        "step_index": step_idx,
                        "agent_id": current,
                        "agent_name": agent.name,
                        "iteration": iteration,
                        "status": status,
                        "duration_seconds": duration,
                        "provider": metadata.get("provider"),
                        "account": metadata.get("profile_id"),
                        "model": metadata.get("selected_model") or (metadata.get("selection_trace") or {}).get("selected_model"),
                        "error": text if status in {"ERROR", "REVIEW_FAILED"} else None,
                        "timestamp": _utc_timestamp(),
                    }
                    edge = next(
                        (item for item in self.workflow.edges if item.source == current and item.condition in {status, "ALWAYS"}),
                        None,
                    )
                    if not edge and status in {"SUCCESS", "NEXT"}:
                        edge = next(
                            (item for item in self.workflow.edges if item.source == current and item.condition in {"SUCCESS", "NEXT"}),
                            None,
                        )
                    if not edge:
                        self.run["status"] = "failed" if status in {"ERROR", "REVIEW_FAILED"} else "completed"
                        if status == "ERROR":
                            self.run["error"] = text or "Провайдер вернул ERROR без текста"
                        self._event(
                            "WORKFLOW_FAILED" if self.run["status"] == "failed" else "WORKFLOW_COMPLETED",
                            f"Workflow завершён со статусом {status}",
                            level="error" if self.run["status"] == "failed" else "success",
                            agent_id=current,
                            iteration=iteration,
                            error=self.run.get("error") if self.run["status"] == "failed" else None,
                        )
                        if status == "ERROR":
                            try:
                                from antigravity_provider.router.unified_health import EventLogService

                                EventLogService.get().log(
                                    "workflow",
                                    f"Ошибка агента «{agent.name}»",
                                    details=self.run["error"],
                                    level="error",
                                )
                            except Exception:
                                pass
                        self._save_run_state(
                            "FAILED" if self.run["status"] == "failed" else "COMPLETED",
                            step_index=step_idx + 1,
                            current_agent=current,
                            iteration=iteration,
                            completed_step=step_summary,
                            interruption_reason=self.run.get("error") if self.run["status"] == "failed" else None,
                        )
                        break

                    edge_counts[edge.id] = edge_counts.get(edge.id, 0) + 1
                    edge_limit = edge.max_iterations if edge.max_iterations is not None else self.workflow.max_iterations
                    if edge_counts[edge.id] > edge_limit:
                        message = f"Достигнут предел итераций для перехода {edge.source} → {edge.target}: {edge_limit}"
                        self.run.update({"status": "failed", "error": message})
                        self._event("WORKFLOW_MAX_ITERATIONS", message, level="error", agent_id=current, iteration=iteration)
                        self._save_run_state("FAILED", step_index=step_idx + 1, current_agent=current, iteration=iteration, interruption_reason=message)
                        break

                    self._event(
                        "WORKFLOW_TRANSITION",
                        f"Переход {current} → {edge.target}: {edge.condition}",
                        agent_id=current,
                        iteration=iteration,
                    )
                    context = json.dumps({
                        "original_task": self.run["current_task"],
                        "previous_agent": current,
                        "structured_result": {"status": status, "content": text},
                    }, ensure_ascii=False)
                    current = edge.target
                    self._save()
                    self._save_run_state(
                        "RUNNING",
                        step_index=step_idx + 1,
                        current_agent=current,
                        iteration=iteration,
                        completed_step=step_summary,
                    )
            with self._lock:
                if self._stop.is_set():
                    self.run.update({"status": "stopped", "error": "Остановлено пользователем"})
                    self._event("WORKFLOW_STOPPED", "Workflow остановлен пользователем", level="warning")
                    self._save_run_state("STOPPED", step_index=len(self._completed_steps), current_agent=current, iteration=iteration, interruption_reason="Остановлено пользователем")
        except Exception as exc:
            with self._lock:
                self.run.update({"status": "failed", "error": str(exc)})
                self._event("PROVIDER_ERROR", "Ошибка выполнения workflow", level="error", agent_id=current, error=str(exc))
                try:
                    from antigravity_provider.router.unified_health import EventLogService

                    EventLogService.get().log("workflow", "Ошибка выполнения workflow", details=str(exc), level="error")
                except Exception:
                    pass
                self._save_run_state("FAILED", step_index=len(self._completed_steps), current_agent=current, iteration=visited.get(current, 1), interruption_reason=str(exc))
        finally:
            with self._lock:
                self.run["finished_at"] = _utc_timestamp()
                self.run["elapsed_seconds"] = round(time.monotonic() - started, 3)
                self.run["current_agent_id"] = current or self.run.get("current_agent_id")
                self._save()

    @staticmethod
    def _response_text(response: Any) -> str:
        if not isinstance(response, dict):
            return str(response)
        choices = response.get("choices")
        if isinstance(choices, list) and choices:
            message = choices[0].get("message", {})
            return str(message.get("content") or choices[0].get("text") or "")
        return str(response.get("content") or response.get("text") or response.get("output") or "")

    @staticmethod
    def _result_status(response: Any, text: str) -> str:
        if isinstance(response, dict):
            explicit = response.get("status") or response.get("structured_status")
            if explicit and str(explicit).upper() in EDGE_CONDITIONS:
                return str(explicit).upper()

        text_upper = text.upper()
        # 1. Match leading status keyword or STATUS: <keyword>
        prefix_match = re.search(
            r"^\s*(?:STATUS\s*:\s*|\[STATUS\s*:\s*)?(REVIEW_FAILED|REVIEW_PASSED|COMPLETED|ACCEPTED|SUCCESS|ERROR)\b",
            text_upper,
            re.MULTILINE,
        )
        if prefix_match:
            return prefix_match.group(1)

        # 2. Match multi-word distinct statuses anywhere
        for status in ("REVIEW_FAILED", "REVIEW_PASSED", "COMPLETED", "ACCEPTED"):
            if re.search(rf"\b{status}\b", text_upper):
                return status

        # 3. Explicit error status markers vs regular discussion of errors
        if re.search(r"\bSTATUS\s*:\s*ERROR\b", text_upper) or re.search(r"\b\[ERROR\]\b", text_upper):
            return "ERROR"

        return "SUCCESS"

    def _event(self, event_type: str, message: str, **kwargs: Any) -> None:
        self.events.append(WorkflowEvent(_utc_timestamp(), event_type, message, **kwargs))
        self.events = self.events[-200:]

    def _require_agent(self, agent_id: str) -> AgentDefinition:
        agent = self.agents.get(agent_id)
        if not agent:
            raise ValueError("Агент не найден")
        return agent


def execute_workflow_action(action: str, data: dict[str, Any]) -> dict[str, Any]:
    """Execute a workflow action through the shared ActionExecutor layer."""
    service = WorkflowService.get()
    if action == "create_agent":
        result = asdict(service.create_agent(data))
    elif action == "update_agent":
        result = asdict(service.update_agent(str(data.get("agent_id") or ""), data))
    elif action == "delete_agent":
        result = service.delete_agent(str(data.get("agent_id") or ""), bool(data.get("force")))
    elif action == "read_agent_file":
        result = service.read_agent_file(str(data.get("agent_id") or ""))
    elif action == "save_agent_file":
        result = service.save_agent_file(str(data.get("agent_id") or ""), str(data.get("content") or ""))
    elif action == "save_workflow":
        result = asdict(service.save_workflow(data))
    elif action == "start_workflow":
        result = service.start(str(data.get("task") or ""))
    elif action == "stop_workflow":
        result = service.stop()
    else:
        raise ValueError("Неизвестное действие workflow")
    if action in {"create_agent", "update_agent", "delete_agent"}:
        try:
            from antigravity_provider.router.state_store import HubStateStore

            HubStateStore.get().refresh(force_scan=False)
        except Exception:
            pass
    return {"ok": True, "message": "Выполнено", "data": result}


# Alias for execution service compatibility
WorkflowExecutionService = WorkflowService
