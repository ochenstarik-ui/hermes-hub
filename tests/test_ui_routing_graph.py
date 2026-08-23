from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("customtkinter")

from antigravity_provider.router.ui import routing_graph as graph_module
from antigravity_provider.router import action_handler
from antigravity_provider.router.ui import add_account_wizard as wizard_module
from antigravity_provider.router.ui.views import team_view as team_module
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


def test_agent_catalog_uses_backend_cache_without_literal_fallback(monkeypatch):
    from antigravity_provider.router.ui import model_catalog

    service = SimpleNamespace(get_cached=lambda _provider: {"models": ["provider-model-a", "provider-model-b"]})
    monkeypatch.setattr(model_catalog, "_service", lambda: service)
    cached = model_catalog.get_cached_models("antigravity")
    assert cached.models == ("provider-model-a", "provider-model-b")


def test_agent_catalog_empty_cache_is_explicit(monkeypatch):
    from antigravity_provider.router.ui import model_catalog

    monkeypatch.setattr(model_catalog, "_service", lambda: None)
    cached = model_catalog.get_cached_models("antigravity")
    assert cached.models == ()
    assert "ещё не подключена" in cached.unavailable_reason


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


def test_profile_test_invokes_model_with_timeout_and_records_success(monkeypatch):
    profile = SimpleNamespace(provider="antigravity", preferred_models=["gemini"], profile_id="connected")
    config = SimpleNamespace(get_profile=lambda _profile_id: profile)

    class Adapter:
        @staticmethod
        def invoke(profile, req, *args, **kwargs):
            return {"choices": [{"message": {"content": "pong"}}]}

    monkeypatch.setattr(action_handler, "load_router_config", lambda: config)
    monkeypatch.setattr(action_handler.ProfileAuthManager, "get_profile_status", lambda *_args: {"authenticated": True, "is_expired": False})
    monkeypatch.setattr(action_handler.ProfileAuthManager, "load_profile_auth", lambda *_args: {"token": "present"})
    monkeypatch.setattr(action_handler, "get_adapter", lambda _provider: Adapter())
    monkeypatch.setattr(action_handler.EventLogService, "get", lambda: SimpleNamespace(log=lambda *_args, **_kwargs: None))

    def mock_mark_success(self, p, m):
        self.marked = True
    monkeypatch.setattr("antigravity_provider.router.health_tracker.HealthTracker.mark_success", mock_mark_success)

    result = action_handler.do_test_profile("antigravity", "connected")
    assert result["success"] is True
    assert "Авторизация подтверждена" in result["response"]


def test_profile_test_expired_credentials_fail_immediately(monkeypatch):
    profile = SimpleNamespace(provider="antigravity", preferred_models=["gemini"], profile_id="connected")
    config = SimpleNamespace(get_profile=lambda _profile_id: profile)

    monkeypatch.setattr(action_handler, "load_router_config", lambda: config)
    monkeypatch.setattr(action_handler.ProfileAuthManager, "get_profile_status", lambda *_args: {"authenticated": True, "is_expired": True})

    result = action_handler.do_test_profile("antigravity", "connected")
    assert result["success"] is False
    assert "Авторизация истекла" in result["error"]


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


def test_wizard_stops_when_provider_has_no_real_free_slot(monkeypatch):
    calls = []
    monkeypatch.setattr(wizard_module.AutoAssigner, "find_free_slot", lambda _provider: None)
    fake = SimpleNamespace(
        selected_provider="grok",
        target_slot="old-value",
        _clear_body=lambda: calls.append("clear"),
        title_lbl=SimpleNamespace(configure=lambda **_kwargs: None),
        _show_no_free_slot=lambda: calls.append("no-slot"),
    )

    wizard_module.AddAccountWizard._show_step_2_auth(fake)

    assert fake.target_slot == ""
    assert calls == ["clear", "no-slot"]


def test_wizard_finish_without_slot_shows_error_and_does_not_assign(monkeypatch):
    updates = []
    monkeypatch.setattr(
        wizard_module,
        "ensure_profile_in_routing",
        lambda _profile: pytest.fail("an invented or empty slot must not be assigned"),
    )
    fake = SimpleNamespace(
        target_slot="",
        finish_status_lbl=SimpleNamespace(configure=lambda **kwargs: updates.append(kwargs)),
    )

    wizard_module.AddAccountWizard._finish(fake)

    assert "свободный слот" in updates[-1]["text"]


def test_role_chain_order_and_removal_persist_through_auto_assigner(monkeypatch):
    config = SimpleNamespace(
        profiles={key: SimpleNamespace() for key in ("a", "b", "c")},
        roles={
            "orchestrator": SimpleNamespace(preferred_chain=["a", "b", "c"]),
            "reviewer": SimpleNamespace(preferred_chain=["b"]),
        },
    )
    calls = []

    def assign(profile_id, role_id, is_primary=True):
        calls.append((profile_id, role_id, is_primary))
        if role_id == "spare":
            for policy in config.roles.values():
                policy.preferred_chain = [item for item in policy.preferred_chain if item != profile_id]
            return True, "spare"
        chain = config.roles[role_id].preferred_chain
        chain = [item for item in chain if item != profile_id]
        if is_primary:
            chain.insert(0, profile_id)
        else:
            chain.append(profile_id)
        config.roles[role_id].preferred_chain = chain
        return True, "assigned"

    monkeypatch.setattr(team_module, "load_router_config", lambda: config)
    monkeypatch.setattr(team_module.AutoAssigner, "assign_profile_to_role", assign)

    ok, _message = team_module.persist_role_chain("orchestrator", ["c", "a"])

    assert ok
    assert config.roles["orchestrator"].preferred_chain == ["c", "a"]
    assert config.roles["reviewer"].preferred_chain == ["b"]
    assert ("b", "spare", False) in calls


def test_account_action_result_is_sent_to_originating_card():
    calls = []
    accounts = SimpleNamespace(
        show_action_result=lambda profile_id, message, success: calls.append(
            ("card", profile_id, message, success)
        )
    )
    fake = SimpleNamespace(
        _views={"accounts": accounts},
        _show_toast=lambda message: calls.append(("toast", message)),
    )

    app_module.HermesHubApp._show_account_action_result(fake, "profile-1", "Не найден", False)

    assert calls[0] == ("card", "profile-1", "Не найден", False)
    assert calls[1][0] == "toast"


def test_device_code_step_contains_numbered_instructions_and_copy_actions():
    source = Path(wizard_module.__file__).read_text(encoding="utf-8")
    assert "1. Откройте ссылку" in source
    assert "2. Введите на странице код:" in source
    assert "3. Подтвердите доступ" in source
    assert source.count('text="Копировать ссылку"') == 2
    assert source.count('text="📋 Копировать код"') == 2


def test_grok_slot_is_registered_before_role_assignment(monkeypatch):
    config = SimpleNamespace(profiles={})
    saved = []
    monkeypatch.setattr(wizard_module, "load_router_config", lambda: config)
    monkeypatch.setattr(
        "antigravity_provider.router.auto_assigner.load_router_config",
        lambda: config,
    )
    monkeypatch.setattr(
        "antigravity_provider.router.auto_assigner.save_router_config",
        lambda current: saved.append(current) or True,
    )

    ok, _message = wizard_module.AutoAssigner.ensure_profile_definition("grok", "grok-orch")

    assert ok
    assert config.profiles["grok-orch"].provider == "grok"
    # Список моделей заполняется обнаружением у провайдера, а не литералом.
    # Пока обнаружение не выполнено, профиль остаётся без моделей: профиль
    # без списка честнее профиля с выдуманным. Раньше сюда подставлялось
    # "grok-3", и по тому же образцу в конфигурацию владельца попал
    # gemini-3.7-flash, которого у провайдера не существует.
    assert config.profiles["grok-orch"].preferred_models == []
    assert saved == [config]


def test_opencode_paste_targets_entry_and_reports_success():
    calls = []
    entry = SimpleNamespace(
        clipboard_get=lambda: "  opencode-token-123  ",
        delete=lambda *_args: calls.append("delete"),
        insert=lambda *_args: calls.append(("insert", _args[-1])),
        focus_set=lambda: calls.append("focus"),
        icursor=lambda *_args: calls.append("cursor"),
    )
    status = SimpleNamespace(configure=lambda **kwargs: calls.append(("status", kwargs["text"])))
    fake = SimpleNamespace(key_entry=entry, key_status_lbl=status)

    wizard_module.AddAccountWizard._paste_into_entry(fake, entry)

    assert ("insert", "opencode-token-123") in calls
    assert ("status", "✓ Ключ вставлен. Нажмите «Проверить и продолжить».") in calls
