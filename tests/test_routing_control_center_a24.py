"""Tests for Routing Control Center & Web Navigation (A24).

Verifies:
1. AutoAssigner.persist_role_chain saves reordered chains to YAML and survives reload.
2. ActionExecutor handles 'save_chain', 'reorder_chain', 'edit_route', 'assign_role'.
3. Model assignment via ActionExecutor('set_model') updates profile and role default.
4. Web client navigation contains exactly 7 primary sections in order.
5. Redundant views (team, providers) are removed from navigation and client script.
"""

from pathlib import Path
from typing import List

import pytest
from antigravity_provider.router.action_handler import ActionExecutor
from antigravity_provider.router.auto_assigner import AutoAssigner
from antigravity_provider.router.router_config import (
    RolePolicy,
    RouterConfig,
    RouterProfileConfig,
    load_router_config,
    save_router_config,
)


@pytest.fixture
def temp_router_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Creates an isolated temporary router configuration."""
    cfg_path = tmp_path / "router_profiles.yaml"
    monkeypatch.setenv("HERMES_ROUTER_CONFIG", str(cfg_path))

    # Initialize sample profiles and roles
    config = RouterConfig(
        enabled=True,
        default_role="manager",
        profiles={
            "ag-w1": RouterProfileConfig(
                profile_id="ag-w1",
                provider="antigravity",
                account_id="ag-dev-1",
                preferred_models=["gemini-2.5-pro"],
            ),
            "ag-w2": RouterProfileConfig(
                profile_id="ag-w2",
                provider="antigravity",
                account_id="ag-dev-2",
                preferred_models=["gemini-2.5-flash"],
            ),
            "op-1": RouterProfileConfig(
                profile_id="op-1",
                provider="opencode-go",
                account_id="op-primary",
                preferred_models=["glm-4.7"],
            ),
            "cl-1": RouterProfileConfig(
                profile_id="cl-1",
                provider="claude",
                account_id="cl-fast",
                preferred_models=["claude-3-5-sonnet"],
            ),
        },
        roles={
            "developer-1": RolePolicy(
                role_name="developer-1",
                preferred_chain=["ag-w1", "ag-w2", "op-1"],
                default_model="gemini-2.5-pro",
            ),
            "developer-2": RolePolicy(
                role_name="developer-2",
                preferred_chain=["ag-w2", "op-1"],
                default_model="gemini-2.5-flash",
            ),
        },
    )
    save_router_config(config)
    return cfg_path


def test_persist_role_chain_reorder_and_persistence(temp_router_config: Path):
    """Verify persist_role_chain updates preferred_chain and primary_profile_id and survives reload."""
    new_chain: List[str] = ["op-1", "ag-w2", "ag-w1"]
    ok, msg = AutoAssigner.persist_role_chain("developer-1", new_chain)

    assert ok is True
    assert "успешно сохранена" in msg

    # Reload from disk
    reloaded = load_router_config()
    role_cfg = reloaded.roles["developer-1"]
    assert role_cfg.preferred_chain == new_chain
    assert role_cfg.preferred_chain[0] == "op-1"


def test_persist_role_chain_canonical_name_mapping(temp_router_config: Path):
    """Verify persist_role_chain resolves Russian aliases and canonical names."""
    new_chain = ["ag-w2", "ag-w1"]
    ok, msg = AutoAssigner.persist_role_chain("кодер 1", new_chain)

    assert ok is True
    reloaded = load_router_config()
    assert reloaded.roles["developer-1"].preferred_chain == new_chain


def test_persist_role_chain_validation_errors(temp_router_config: Path):
    """Verify persist_role_chain rejects invalid profiles and duplicates."""
    # Unknown profile
    ok, msg = AutoAssigner.persist_role_chain("developer-1", ["ag-w1", "non-existent-profile"])
    assert ok is False
    assert "не найден" in msg

    # Duplicate profile in chain
    ok, msg = AutoAssigner.persist_role_chain("developer-1", ["ag-w1", "ag-w1"])
    assert ok is False
    assert "повторяться" in msg or "дублир" in msg

    # Non-existent role
    ok, msg = AutoAssigner.persist_role_chain("unknown-role-xyz", ["ag-w1"])
    assert ok is False
    assert "Неизвестная роль" in msg or "неизвестн" in msg.lower()


def test_action_executor_save_chain(temp_router_config: Path):
    """Verify ActionExecutor executes 'save_chain', 'reorder_chain', and 'edit_route'."""
    executor = ActionExecutor()

    # save_chain
    res1 = executor.execute("save_chain", {"role_id": "developer-1", "chain": ["ag-w2", "ag-w1"]})
    assert res1["ok"] is True

    # reorder_chain
    res2 = executor.execute("reorder_chain", {"role_id": "developer-1", "desired_chain": ["op-1", "ag-w1"]})
    assert res2["ok"] is True

    # edit_route
    res3 = executor.execute("edit_route", {"role_id": "developer-2", "chain": ["op-1", "ag-w2"]})
    assert res3["ok"] is True

    reloaded = load_router_config()
    assert reloaded.roles["developer-1"].preferred_chain == ["op-1", "ag-w1"]
    assert reloaded.roles["developer-2"].preferred_chain == ["op-1", "ag-w2"]


def test_action_executor_set_model_updates_profile_and_role(temp_router_config: Path):
    """Verify ActionExecutor('set_model') updates profile preferred_models and role default_model."""
    executor = ActionExecutor()

    res = executor.execute("set_model", {
        "profile_id": "ag-w1",
        "model": "gemini-3.1-pro",
        "role_id": "developer-1",
    })
    assert res["ok"] is True

    reloaded = load_router_config()
    assert reloaded.profiles["ag-w1"].preferred_models[0] == "gemini-3.1-pro"
    assert reloaded.roles["developer-1"].default_model == "gemini-3.1-pro"


def test_web_client_7_views_exact_order_and_no_redundant_views():
    """Verify index.html navigation items match exactly 7 sections in required order."""
    static_dir = Path(__file__).parent.parent / "src" / "antigravity_provider" / "router" / "web" / "static"
    index_html = (static_dir / "index.html").read_text(encoding="utf-8")
    app_js = (static_dir / "app.js").read_text(encoding="utf-8")

    expected_views = [
        "overview",
        "accounts",
        "routing",
        "analytics",
        "health",
        "logs",
        "settings",
    ]

    # Verify presence in exact order in index.html nav-menu
    nav_positions = [index_html.find(f'data-view="{v}"') for v in expected_views]
    assert all(pos != -1 for pos in nav_positions), "All 7 views must be present in index.html"
    assert nav_positions == sorted(nav_positions), "Views in index.html must be in exact specified order"

    # Verify absence of removed views
    assert 'data-view="providers"' not in index_html
    assert 'data-view="team"' not in index_html
    assert "renderProvidersView" not in app_js
    assert "renderTeamView" not in app_js
