from __future__ import annotations

from types import SimpleNamespace

import pytest

pytest.importorskip("customtkinter")

from antigravity_provider.router.ui import routing_graph as graph_module
from antigravity_provider.router.ui import add_account_wizard as wizard_module
from antigravity_provider.router import hermes_hub_app as app_module
from antigravity_provider.router.ui.routing_graph import (
    GraphEdge,
    GraphNode,
    RoutingGraph,
    RoutingGraphController,
    RoutingGraphStore,
    default_graph,
    validate_graph,
)


def _config():
    profiles = {
        "orch": SimpleNamespace(provider="openai-codex", preferred_models=["gpt-5"]),
        "coder": SimpleNamespace(provider="antigravity", preferred_models=["gemini"]),
    }
    roles = {
        "orchestrator": SimpleNamespace(preferred_chain=["orch"]),
        "coder-primary": SimpleNamespace(preferred_chain=["coder"]),
        "coder-secondary": SimpleNamespace(preferred_chain=["coder"]),
        "reviewer": SimpleNamespace(preferred_chain=["coder"]),
        "research": SimpleNamespace(preferred_chain=["coder"]),
        "fast": SimpleNamespace(preferred_chain=["coder"]),
    }
    return SimpleNamespace(roles=roles, profiles=profiles)


def test_default_graph_migrates_six_roles_without_changing_chains():
    config = _config()
    before = {key: list(value.preferred_chain) for key, value in config.roles.items()}
    graph = default_graph(config)
    assert {node.role_id for node in graph.nodes} == set(config.roles)
    assert {edge.edge_type for edge in graph.edges} == {"DELEGATE"}
    assert before == {key: value.preferred_chain for key, value in config.roles.items()}


def test_graph_layout_zoom_and_viewport_survive_restart(tmp_path):
    path = tmp_path / "routing_graph.json"
    store = RoutingGraphStore(path)
    graph = default_graph(_config())
    graph.nodes[0].x = 777
    graph.zoom = 1.35
    graph.viewport_x = 42
    store.save(graph)
    loaded = store.load(_config())
    assert loaded.nodes[0].x == 777
    assert loaded.zoom == 1.35
    assert loaded.viewport_x == 42
    assert loaded.schema_version == 1


def test_validation_finds_cycle_unreachable_and_missing_profile():
    config = _config()
    config.roles["reviewer"].preferred_chain = ["ghost"]
    graph = RoutingGraph(
        nodes=[
            GraphNode("orchestrator", 0, 0),
            GraphNode("coder-primary", 1, 0),
            GraphNode("reviewer", 2, 0),
        ],
        edges=[
            GraphEdge("orchestrator", "coder-primary"),
            GraphEdge("coder-primary", "orchestrator"),
        ],
    )
    codes = {issue.code for issue in validate_graph(graph, config)}
    assert {"cycle", "unreachable", "missing-profile"} <= codes


def test_profile_edge_updates_yaml_via_auto_assigner(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(graph_module, "load_router_config", _config)
    monkeypatch.setattr(
        graph_module.AutoAssigner,
        "assign_profile_to_role",
        lambda profile, role, is_primary: calls.append((profile, role, is_primary)) or (True, "ok"),
    )
    controller = RoutingGraphController(RoutingGraphStore(tmp_path / "graph.json"))
    ok, _message = controller.add_edge("orchestrator", "coder-primary", "FALLBACK", "orch")
    assert ok
    assert calls == [("orch", "coder-primary", False)]


def test_undo_redo_and_dirty_state(monkeypatch, tmp_path):
    monkeypatch.setattr(graph_module, "load_router_config", _config)
    controller = RoutingGraphController(RoutingGraphStore(tmp_path / "graph.json"))
    original = controller.graph.nodes[0].x
    controller.move_node("orchestrator", original + 100, 50)
    assert controller.dirty
    assert controller.undo()
    assert controller.graph.nodes[0].x == original
    assert controller.redo()
    assert controller.graph.nodes[0].x == original + 100


def test_graph_store_handles_twenty_nodes(tmp_path):
    graph = RoutingGraph(nodes=[GraphNode(f"role-{index}", index * 70, index * 35) for index in range(20)])
    store = RoutingGraphStore(tmp_path / "routing_graph.json")
    store.save(graph)
    assert len(store.load(_config()).nodes) == 20


def test_wizard_keeps_existing_chain_rank_and_assigns_missing_slot(monkeypatch):
    config = _config()
    calls = []
    monkeypatch.setattr(wizard_module, "load_router_config", lambda: config)
    monkeypatch.setattr(
        wizard_module.AutoAssigner,
        "assign_profile_to_role",
        lambda profile, role, is_primary: calls.append((profile, role, is_primary)) or (True, "ok"),
    )
    assert wizard_module.ensure_profile_in_routing("orch")[0]
    assert calls == []
    monkeypatch.setattr(
        wizard_module.AutoAssigner,
        "get_display_name_and_role",
        lambda _profile: ("Новый кодер", "coder", "fallback"),
    )
    assert wizard_module.ensure_profile_in_routing("new-slot")[0]
    assert calls == [("new-slot", "coder", False)]


def test_profile_test_does_not_invoke_model_or_oauth(monkeypatch):
    profile = SimpleNamespace(provider="antigravity", preferred_models=["gemini"], profile_id="connected")
    config = SimpleNamespace(get_profile=lambda _profile_id: profile)

    class Adapter:
        @staticmethod
        def health_check(_profile):
            return True

        @staticmethod
        def invoke(*_args, **_kwargs):
            raise AssertionError("profile test must never invoke inference")

    monkeypatch.setattr(app_module, "load_router_config", lambda: config)
    monkeypatch.setattr(app_module.ProfileAuthManager, "get_profile_status", lambda *_args: {"authenticated": True})
    monkeypatch.setattr(app_module.ProfileAuthManager, "load_profile_auth", lambda *_args: {"token": "present"})
    monkeypatch.setattr(app_module, "get_adapter", lambda _provider: Adapter())
    monkeypatch.setattr(app_module.EventLogService, "get", lambda: SimpleNamespace(log=lambda *_args, **_kwargs: None))

    result = app_module.do_test_profile("antigravity", "connected")
    assert result["success"] is True
    assert "runtime" in result["response"]


def test_wizard_finish_closes_logs_and_clears_reused_slot(monkeypatch):
    calls = []
    monkeypatch.setattr(wizard_module, "ensure_profile_in_routing", lambda _profile: (True, "ok"))
    monkeypatch.setattr(
        wizard_module.EventLogService,
        "get",
        lambda: SimpleNamespace(log=lambda *args, **kwargs: calls.append(("log", args, kwargs))),
    )
    from antigravity_provider.router import router_engine

    monkeypatch.setattr(
        router_engine,
        "get_router_engine",
        lambda: SimpleNamespace(health=SimpleNamespace(clear_cooldown=lambda profile: calls.append(("clear", profile)))),
    )
    fake = SimpleNamespace(
        target_slot="ag-orch-fallback",
        selected_provider="antigravity",
        discovered_identity="account",
        finish_status_lbl=SimpleNamespace(configure=lambda **_kwargs: None),
        on_complete=lambda payload: calls.append(("complete", payload)),
        destroy=lambda: calls.append(("destroy",)),
    )
    wizard_module.AddAccountWizard._finish(fake)
    assert ("clear", "ag-orch-fallback") in calls
    assert any(item[0] == "log" for item in calls)
    assert calls[-1] == ("destroy",)
