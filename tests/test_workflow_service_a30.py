from __future__ import annotations

import json

import pytest

from antigravity_provider.router.router_config import (
    RolePolicy,
    RouterConfig,
    RouterProfileConfig,
    save_router_config,
)
from antigravity_provider.router.workflow_service import WorkflowService


@pytest.fixture
def workflow_service(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    config = RouterConfig(
        profiles={
            "account-a": RouterProfileConfig(
                profile_id="account-a",
                provider="openai-codex",
                preferred_models=["model-real-from-config"],
            )
        },
        roles={"developer": RolePolicy(role_name="developer", preferred_chain=["account-a"])},
    )
    save_router_config(config)
    return WorkflowService(tmp_path / "workflow_state.json")


def test_router_roles_migrate_to_agents_and_create_real_files(workflow_service, tmp_path):
    snapshot = workflow_service.snapshot()
    assert "developer" in [agent["id"] for agent in snapshot["agents"]]
    agent = next(item for item in snapshot["agents"] if item["id"] == "developer")
    assert agent["agent_file"] == "agents/developer.md"
    assert agent["agent_file_exists"] is True
    assert (tmp_path / "agents" / "developer.md").is_file()
    assert agent["execution_config"]["account"] == "account-a"
    assert agent["execution_config"]["model"] == "model-real-from-config"


def test_create_update_file_and_restart_persistence(workflow_service, tmp_path):
    created = workflow_service.create_agent({
        "name": "Security Reviewer",
        "role": "security-reviewer",
        "account": "account-a",
        "model": "model-real-from-config",
        "description": "Проверяет безопасность",
    })
    workflow_service.save_agent_file(created.id, "# Security\n\nOnly measured facts.")
    workflow_service.update_agent(created.id, {"timeout": 91, "position": {"x": 33, "y": 44}})

    restarted = WorkflowService(tmp_path / "workflow_state.json")
    item = next(agent for agent in restarted.snapshot()["agents"] if agent["id"] == created.id)
    assert item["timeout"] == 91
    assert item["position"] == {"x": 33, "y": 44}
    assert restarted.read_agent_file(created.id)["content"].endswith("Only measured facts.")


def test_delete_requires_explicit_confirmation_when_referenced(workflow_service):
    workflow_service.create_agent({"name": "Test Reviewer", "role": "test-reviewer", "account": "account-a"})
    workflow_service.save_workflow({
        "start_agent_id": "developer",
        "max_iterations": 3,
        "edges": [{"id": "review", "source": "developer", "target": "test-reviewer", "condition": "SUCCESS"}],
    })
    warning = workflow_service.delete_agent("test-reviewer")
    assert warning["confirmation_required"] is True
    assert warning["consequences"]["workflow_edges"] == ["review"]
    result = workflow_service.delete_agent("test-reviewer", force=True)
    assert result["deleted"] is True
    assert workflow_service.workflow.edges == []


def test_cycles_are_valid_and_iteration_limit_is_persisted(workflow_service):
    workflow_service.create_agent({"name": "Test Reviewer", "role": "test-reviewer", "account": "account-a"})
    definition = workflow_service.save_workflow({
        "start_agent_id": "developer",
        "max_iterations": 2,
        "edges": [
            {"source": "developer", "target": "test-reviewer", "condition": "SUCCESS"},
            {"source": "test-reviewer", "target": "developer", "condition": "REVIEW_FAILED"},
        ],
    })
    assert definition.max_iterations == 2
    assert definition.edges[1].condition == "REVIEW_FAILED"
    payload = json.loads(workflow_service.state_path.read_text(encoding="utf-8"))
    assert payload["workflow"]["max_iterations"] == 2


def test_invalid_edge_and_unknown_model_are_rejected(workflow_service):
    with pytest.raises(ValueError, match="отсутствующего агента"):
        workflow_service.save_workflow({"edges": [{"source": "developer", "target": "missing"}]})
    with pytest.raises(ValueError, match="не доступна"):
        workflow_service.update_agent("developer", {"account": "account-a", "model": "invented-model"})


def test_interrupted_run_is_reported_not_silently_completed(workflow_service, tmp_path):
    workflow_service.run.update({"id": "run-1", "status": "running", "current_agent_id": "developer"})
    workflow_service._save()
    restarted = WorkflowService(tmp_path / "workflow_state.json")
    assert restarted.run["status"] == "interrupted"
    assert "перезапуском" in restarted.run["error"]
    assert restarted.events[-1].type == "WORKFLOW_INTERRUPTED"


def test_live_cycle_stops_with_explicit_iteration_limit_event(workflow_service, monkeypatch):
    workflow_service.create_agent({"name": "Loop Reviewer", "role": "loop-reviewer", "account": "account-a"})
    workflow_service.save_workflow({
        "start_agent_id": "developer",
        "max_iterations": 2,
        "edges": [
            {"source": "developer", "target": "loop-reviewer", "condition": "SUCCESS"},
            {"source": "loop-reviewer", "target": "developer", "condition": "REVIEW_FAILED"},
        ],
    })

    class FakeEngine:
        def reload_config(self):
            return None

        def route_request(self, request, role=None, session_id=None):
            status = "REVIEW_FAILED" if role == "loop-reviewer" else "SUCCESS"
            return {
                "choices": [{"message": {"content": status}}],
                "router_metadata": {
                    "provider": "measured-provider",
                    "profile_id": "account-a",
                    "selection_trace": {"selected_model": "model-real-from-config"},
                },
            }

    monkeypatch.setattr("antigravity_provider.router.router_engine.get_router_engine", lambda: FakeEngine())
    workflow_service.start("Проверить реальный цикл")
    thread = workflow_service._thread
    assert thread is not None
    thread.join(timeout=3)
    assert not thread.is_alive(), "Workflow execution thread leaked after join"

    assert workflow_service.run["status"] == "failed"
    assert workflow_service.run["error"] == "Достигнут предел итераций: 2"
    assert any(event.type == "WORKFLOW_MAX_ITERATIONS" for event in workflow_service.events)


def test_provider_error_text_reaches_run_and_events(workflow_service, monkeypatch):
    provider_text = "Provider Error: authentication token missing for account-a"

    class ErrorEngine:
        def reload_config(self):
            return None

        def route_request(self, request, role=None, session_id=None):
            return {"choices": [{"message": {"content": f"ERROR\n{provider_text}"}}]}

    monkeypatch.setattr("antigravity_provider.router.router_engine.get_router_engine", lambda: ErrorEngine())
    workflow_service.workflow.start_agent_id = "developer"
    workflow_service.workflow.edges = []
    workflow_service.start("Проверить ошибку")
    thread = workflow_service._thread
    assert thread is not None
    thread.join(timeout=3)
    assert not thread.is_alive(), "Workflow execution thread leaked after join"

    assert workflow_service.run["status"] == "failed"
    assert provider_text in workflow_service.run["error"]
    assert any(provider_text in (event.error or "") for event in workflow_service.events)
    assert workflow_service.snapshot()["agents"][0]["runtime_state"] == "error"
