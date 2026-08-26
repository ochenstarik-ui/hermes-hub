"""Acceptance tests for the approved three-theme mockup redesign."""

from __future__ import annotations

import ast
from pathlib import Path
import re
from types import SimpleNamespace

import pytest

pytest.importorskip("customtkinter")

import customtkinter as ctk

from antigravity_provider.router.ui.components import AccountCardWidget
from antigravity_provider.router.ui.theme import Theme
from antigravity_provider.router import hermes_hub_app as app_module


@pytest.fixture(scope="module")
def ui_root(tk_root):
    root = ctk.CTkToplevel(tk_root)
    root.withdraw()
    yield root
    root.destroy()


@pytest.mark.unit
def test_every_restored_account_handler_has_a_ui_trigger() -> None:
    required = {"test", "set_main", "set_orchestrator", "assign_role"}
    configured = {action for action, _label in AccountCardWidget.MANAGEMENT_ACTIONS}
    assert configured == required

    app_path = Path("src/antigravity_provider/router/hermes_hub_app.py")
    tree = ast.parse(app_path.read_text(encoding="utf-8"))
    handled = {
        node.comparators[0].value
        for node in ast.walk(tree)
        if isinstance(node, ast.Compare)
        and isinstance(node.left, ast.Name)
        and node.left.id == "action"
        and len(node.ops) == 1
        and isinstance(node.ops[0], ast.Eq)
        and len(node.comparators) == 1
        and isinstance(node.comparators[0], ast.Constant)
        and isinstance(node.comparators[0].value, str)
    }
    assert required <= handled


@pytest.mark.unit
def test_three_schemes_have_identical_token_coverage() -> None:
    assert set(Theme.PALETTES) == {"dark", "hybrid", "light"}
    token_sets = [set(palette) for palette in Theme.PALETTES.values()]
    assert token_sets[0] == token_sets[1] == token_sets[2]
    backgrounds = {palette["BG_WINDOW"] for palette in Theme.PALETTES.values()}
    assert len(backgrounds) == 3


@pytest.mark.unit
def test_ui_colors_are_centralized_in_theme_tokens() -> None:
    roots = [
        Path("src/antigravity_provider/router/ui"),
        Path("src/antigravity_provider/router/hermes_hub_app.py"),
    ]
    offenders = []
    for root in roots:
        files = [root] if root.is_file() else list(root.rglob("*.py"))
        for file in files:
            if file.name == "theme.py":
                continue
            if re.search(r"#[0-9A-Fa-f]{3,8}", file.read_text(encoding="utf-8")):
                offenders.append(str(file))
    assert offenders == []


@pytest.mark.unit
def test_approved_mockup_numbers_are_not_shipped_as_placeholders() -> None:
    source_files = list(Path("src/antigravity_provider/router/ui").rglob("*.py"))
    source_files.append(Path("src/antigravity_provider/router/hermes_hub_app.py"))
    source = "\n".join(file.read_text(encoding="utf-8") for file in source_files)
    for fictional_value in ("78%", "09:00–21:00", "842 rps", "99.98%", "42 Мбит/с"):
        assert fictional_value not in source


@pytest.mark.unit
def test_approved_logo_and_consistent_sidebar_icon_system_are_wired() -> None:
    assert Path("assets/branding/logo/logo_approved.png").is_file()
    assets_source = Path("src/antigravity_provider/router/ui/assets.py").read_text(encoding="utf-8")
    app_source = Path("src/antigravity_provider/router/hermes_hub_app.py").read_text(encoding="utf-8")
    assert 'self.logo_dir / "logo_approved.png"' in assets_source
    assert "def get_nav_icon" in assets_source
    assert "get_nav_icon(icon, size=19)" in app_source


@pytest.mark.unit
def test_apply_scheme_updates_shared_semantic_aliases() -> None:
    original = Theme.current_scheme
    try:
        for scheme in Theme.SCHEMES:
            assert Theme.apply_scheme(scheme) == scheme
            assert Theme.COLOR_POSITIVE == Theme.STATUS_HEALTHY
            assert Theme.COLOR_CAUTION == Theme.STATUS_WARNING
            assert Theme.COLOR_BRAND == Theme.ACCENT
    finally:
        Theme.apply_scheme(original)


@pytest.mark.ui
def test_restored_account_buttons_invoke_each_action(ui_root) -> None:
    calls = []
    card = AccountCardWidget(
        ui_root,
        "profile-1",
        "user@example.test",
        "OpenAI Codex",
        on_action=lambda action, profile: calls.append((action, profile.profile_id)),
    )
    card.profile_model = SimpleNamespace(profile_id="profile-1")
    try:
        card.pack()
        for action, _label in AccountCardWidget.MANAGEMENT_ACTIONS:
            card.action_buttons[action].invoke()
        assert calls == [(action, "profile-1") for action, _label in AccountCardWidget.MANAGEMENT_ACTIONS]
    finally:
        card.destroy()


@pytest.mark.ui
def test_assign_role_error_stays_visible_in_open_modal(ui_root, monkeypatch) -> None:
    policy = SimpleNamespace(preferred_chain=[])
    monkeypatch.setattr(app_module, "load_router_config", lambda: SimpleNamespace(roles={"manager": policy}))
    monkeypatch.setattr(
        app_module.AutoAssigner,
        "assign_profile_to_role",
        lambda *_args, **_kwargs: (False, "Профиль не найден"),
    )
    ui_root._show_account_action_result = lambda *_args: None
    modal = app_module.HermesHubApp._open_assign_role_modal(ui_root, "missing", "Claude")
    try:
        modal.save_button.invoke()
        modal.update_idletasks()
        assert modal.winfo_exists()
        assert "Профиль не найден" in modal.result_label.cget("text")
    finally:
        modal.destroy()
