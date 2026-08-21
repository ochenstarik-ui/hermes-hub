"""Startup contract for UI views — runs without customtkinter.

Guards the crash that took the app down on launch:

    TeamView.__init__ forwarded its legacy ``app_state`` dict into
    ``update_data(snapshot)``. The guard there only handled ``None``, so ``{}``
    slipped through and ``snapshot.readiness`` raised
    ``'dict' object has no attribute 'readiness'``. "Команда" is the default
    view, so the failure happened before the window ever appeared.

These checks are static: they read the view sources rather than build widgets,
so they run in headless environments where the GUI toolkit is absent.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

VIEWS_DIR = Path(__file__).resolve().parent.parent / "src" / "antigravity_provider" / "router" / "ui" / "views"


def _view_files() -> list[Path]:
    return sorted(VIEWS_DIR.glob("*_view.py"))


def _self_update_data_calls(tree: ast.AST, inside: str) -> list[ast.Call]:
    """Return self.update_data(...) calls made from the named method."""
    calls: list[ast.Call] = []
    for cls in (n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)):
        for fn in (n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == inside):
            for node in ast.walk(fn):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "update_data"
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "self"
                ):
                    calls.append(node)
    return calls


@pytest.mark.unit
@pytest.mark.parametrize("view_path", _view_files(), ids=lambda p: p.stem.replace("_view", ""))
def test_constructor_does_not_forward_app_state_to_update_data(view_path: Path) -> None:
    """A view constructor must not pass its legacy app_state into update_data."""
    tree = ast.parse(view_path.read_text(encoding="utf-8"))
    for call in _self_update_data_calls(tree, inside="__init__"):
        assert not call.args and not call.keywords, (
            f"{view_path.name}: __init__ calls self.update_data(...) with an argument. "
            "update_data expects a HubSnapshot; constructors hold app_state dicts. "
            "Call self.update_data() and let it pull the current snapshot."
        )


@pytest.mark.unit
@pytest.mark.parametrize("view_path", _view_files(), ids=lambda p: p.stem.replace("_view", ""))
def test_update_data_guard_rejects_non_snapshot(view_path: Path) -> None:
    """update_data must fall back on anything that is not a HubSnapshot, not just None."""
    source = view_path.read_text(encoding="utf-8")
    if "def update_data" not in source or "snapshot" not in source:
        pytest.skip("view has no snapshot-driven update_data")
    # Views are pure renderers now: they either fall back to the store or return
    # early. Either way the guard must reject anything that is not a snapshot —
    # `snapshot is None` alone lets a legacy app_state dict through, which is
    # what crashed the app on launch.
    assert "isinstance(snapshot, HubSnapshot)" in source, (
        f"{view_path.name}: update_data does not guard with isinstance(snapshot, HubSnapshot). "
        "A legacy dict would pass a `snapshot is None` check and then fail on attribute access."
    )
