"""Versioned presentation model for the Team routing graph.

The router YAML remains the source of truth for profiles and role chains.  This
module stores only topology/layout metadata next to it and applies profile
assignments through :class:`AutoAssigner`.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import copy
import json
from pathlib import Path
from typing import Any, Iterable, Optional
from uuid import uuid4

from antigravity_provider import paths
from antigravity_provider.router.auto_assigner import AutoAssigner
from antigravity_provider.router.router_config import RouterConfig, load_router_config

SCHEMA_VERSION = 1
EDGE_TYPES = ("PRIMARY", "FALLBACK", "DELEGATE")
CANONICAL_ROLES = ("orchestrator", "coder-primary", "coder-secondary", "reviewer", "research", "fast")
ROLE_LABELS = {
    "orchestrator": "Оркестратор",
    "coder-primary": "Основной кодер",
    "coder-secondary": "Резервный кодер",
    "reviewer": "Ревьюер",
    "research": "Исследователь",
    "fast": "Быстрый агент",
}


@dataclass
class GraphNode:
    role_id: str
    x: float
    y: float
    label: str = ""


@dataclass
class GraphEdge:
    source: str
    target: str
    edge_type: str = "DELEGATE"
    profile_id: str = ""
    edge_id: str = field(default_factory=lambda: uuid4().hex[:12])


@dataclass
class GraphIssue:
    code: str
    message: str
    node_id: str = ""
    edge_id: str = ""


@dataclass
class RoutingGraph:
    schema_version: int = SCHEMA_VERSION
    nodes: list[GraphNode] = field(default_factory=list)
    edges: list[GraphEdge] = field(default_factory=list)
    zoom: float = 1.0
    viewport_x: float = 0.0
    viewport_y: float = 0.0

    def clone(self) -> "RoutingGraph":
        return copy.deepcopy(self)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "RoutingGraph":
        if int(value.get("schema_version", 0)) != SCHEMA_VERSION:
            raise ValueError("Unsupported routing graph schema")
        return cls(
            schema_version=SCHEMA_VERSION,
            nodes=[GraphNode(**item) for item in value.get("nodes", [])],
            edges=[GraphEdge(**item) for item in value.get("edges", [])],
            zoom=float(value.get("zoom", 1.0)),
            viewport_x=float(value.get("viewport_x", 0.0)),
            viewport_y=float(value.get("viewport_y", 0.0)),
        )


def default_graph(config: Optional[RouterConfig] = None) -> RoutingGraph:
    """Migrate current configured roles without touching their chains."""
    config = config or load_router_config()
    roles = [role for role in CANONICAL_ROLES if role in config.roles]
    roles.extend(role for role in config.roles if role not in roles)
    nodes: list[GraphNode] = []
    for index, role_id in enumerate(roles):
        if role_id == "orchestrator":
            x, y = 90.0, 240.0
        else:
            slot = index - (1 if "orchestrator" in roles else 0)
            x, y = 390.0 + (slot // 3) * 300.0, 80.0 + (slot % 3) * 160.0
        nodes.append(GraphNode(role_id, x, y, ROLE_LABELS.get(role_id, role_id)))
    root = "orchestrator" if "orchestrator" in roles else (roles[0] if roles else "")
    edges = [GraphEdge(root, role, "DELEGATE") for role in roles if root and role != root]
    return RoutingGraph(nodes=nodes, edges=edges)


class RoutingGraphStore:
    def __init__(self, path: Optional[Path] = None):
        self.path = path or (paths.get_hermes_home() / "routing_graph.json")

    def load(self, config: Optional[RouterConfig] = None) -> RoutingGraph:
        try:
            return RoutingGraph.from_dict(json.loads(self.path.read_text(encoding="utf-8")))
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            return default_graph(config)

    def save(self, graph: RoutingGraph) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(graph.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)


def validate_graph(graph: RoutingGraph, config: Optional[RouterConfig] = None) -> list[GraphIssue]:
    config = config or load_router_config()
    issues: list[GraphIssue] = []
    node_ids = [node.role_id for node in graph.nodes]
    node_set = set(node_ids)
    for role_id in sorted({item for item in node_ids if node_ids.count(item) > 1}):
        issues.append(GraphIssue("duplicate-node", f"Роль {role_id} добавлена дважды", role_id))
    if "orchestrator" not in node_set:
        issues.append(GraphIssue("missing-orchestrator", "Отсутствует узел оркестратора"))
    for node in graph.nodes:
        policy = config.roles.get(node.role_id)
        if policy is None:
            issues.append(GraphIssue("missing-role", f"Роль {node.role_id} отсутствует в конфигурации", node.role_id))
        elif not policy.preferred_chain:
            issues.append(GraphIssue("empty-chain", f"У роли {node.label or node.role_id} нет профилей", node.role_id))
        else:
            for profile_id in policy.preferred_chain:
                if profile_id not in config.profiles:
                    issues.append(
                        GraphIssue("missing-profile", f"Профиль {profile_id} не существует", node.role_id)
                    )
    seen_edges: set[tuple[str, str, str, str]] = set()
    adjacency: dict[str, list[str]] = {node_id: [] for node_id in node_set}
    for edge in graph.edges:
        key = (edge.source, edge.target, edge.edge_type, edge.profile_id)
        if key in seen_edges:
            issues.append(GraphIssue("duplicate-edge", "Дублирующая связь", edge_id=edge.edge_id))
        seen_edges.add(key)
        if edge.edge_type not in EDGE_TYPES:
            issues.append(GraphIssue("edge-type", f"Неизвестный тип {edge.edge_type}", edge_id=edge.edge_id))
        if edge.source not in node_set or edge.target not in node_set:
            issues.append(GraphIssue("dangling-edge", "Связь ведёт к отсутствующей роли", edge_id=edge.edge_id))
            continue
        adjacency[edge.source].append(edge.target)
        if edge.profile_id and edge.profile_id not in config.profiles:
            issues.append(GraphIssue("missing-profile", f"Профиль {edge.profile_id} не существует", edge.target, edge.edge_id))

    visited: set[str] = set()
    active: set[str] = set()

    def visit(role_id: str) -> None:
        if role_id in active:
            issues.append(GraphIssue("cycle", f"Цикл маршрутизации через {role_id}", role_id))
            return
        if role_id in visited:
            return
        visited.add(role_id)
        active.add(role_id)
        for target in adjacency.get(role_id, []):
            visit(target)
        active.remove(role_id)

    if "orchestrator" in node_set:
        visit("orchestrator")
        for role_id in sorted(node_set - visited):
            issues.append(GraphIssue("unreachable", f"Роль {role_id} недостижима от оркестратора", role_id))
    return issues


class RoutingGraphController:
    """Undoable graph editor whose assignments go through AutoAssigner."""

    def __init__(self, store: Optional[RoutingGraphStore] = None):
        self.store = store or RoutingGraphStore()
        self.graph = self.store.load()
        self._undo: list[RoutingGraph] = []
        self._redo: list[RoutingGraph] = []
        self.dirty = False

    def _checkpoint(self) -> None:
        self._undo.append(self.graph.clone())
        self._undo = self._undo[-50:]
        self._redo.clear()
        self.dirty = True

    def move_node(self, role_id: str, x: float, y: float) -> None:
        node = next((item for item in self.graph.nodes if item.role_id == role_id), None)
        if node and (node.x, node.y) != (x, y):
            self._checkpoint()
            node.x, node.y = x, y

    def add_edge(self, source: str, target: str, edge_type: str, profile_id: str = "") -> tuple[bool, str]:
        if edge_type not in EDGE_TYPES:
            return False, "Неизвестный тип связи"
        self._checkpoint()
        self.graph.edges.append(GraphEdge(source, target, edge_type, profile_id))
        if profile_id and edge_type in {"PRIMARY", "FALLBACK"}:
            ok, message = AutoAssigner.assign_profile_to_role(profile_id, target, edge_type == "PRIMARY")
            if not ok:
                self.undo()
                return False, message
        return True, "Связь добавлена"

    def delete_edge(self, edge_id: str) -> None:
        if any(edge.edge_id == edge_id for edge in self.graph.edges):
            self._checkpoint()
            self.graph.edges = [edge for edge in self.graph.edges if edge.edge_id != edge_id]

    def set_edge_type(
        self, edge_id: str, edge_type: str, profile_id: Optional[str] = None
    ) -> tuple[bool, str]:
        edge = next((item for item in self.graph.edges if item.edge_id == edge_id), None)
        if edge is None or edge_type not in EDGE_TYPES:
            return False, "Связь не найдена"
        self._checkpoint()
        edge.edge_type = edge_type
        if profile_id is not None:
            edge.profile_id = profile_id
        if edge.profile_id and edge_type in {"PRIMARY", "FALLBACK"}:
            ok, message = AutoAssigner.assign_profile_to_role(edge.profile_id, edge.target, edge_type == "PRIMARY")
            if not ok:
                self.undo()
            return ok, message
        return True, "Тип связи изменён"

    def auto_layout(self) -> None:
        self._checkpoint()
        root = next((node for node in self.graph.nodes if node.role_id == "orchestrator"), None)
        if root:
            root.x, root.y = 80.0, 240.0
        others = [node for node in self.graph.nodes if node.role_id != "orchestrator"]
        for index, node in enumerate(others):
            node.x = 390.0 + (index // 4) * 290.0
            node.y = 55.0 + (index % 4) * 135.0

    def undo(self) -> bool:
        if not self._undo:
            return False
        self._redo.append(self.graph.clone())
        self.graph = self._undo.pop()
        self.dirty = True
        return True

    def redo(self) -> bool:
        if not self._redo:
            return False
        self._undo.append(self.graph.clone())
        self.graph = self._redo.pop()
        self.dirty = True
        return True

    def save(self) -> list[GraphIssue]:
        issues = validate_graph(self.graph)
        if not issues:
            self.store.save(self.graph)
            self.dirty = False
        return issues

    def role_chain(self, role_id: str) -> Iterable[str]:
        policy = load_router_config().roles.get(role_id)
        return tuple(policy.preferred_chain if policy else ())
