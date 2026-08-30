"""Import invariants for the whole package.

Guards against two classes of rot that unit tests do not catch:

1. Dead-on-arrival modules — code that references project-internal names which
   do not exist, so the module has never been imported by anything.
   (Found in review: ``deepseek_adapter`` imported ``ProviderAdapter`` and
   ``ProfileConfig``, neither of which exists anywhere in ``src/``.)

2. Missing ``pytest.importorskip`` guards — a test module that imports an
   optional UI dependency at module scope aborts collection of the ENTIRE
   session instead of skipping itself.

Missing *third-party* optional dependencies (customtkinter, PIL, ...) are
skipped, not failed: those are legitimately absent in headless environments.
Broken *internal* references always fail.
"""

from __future__ import annotations

import ast
import importlib
import pkgutil
from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).resolve().parent
# ``antigravity_provider`` is a PEP 420 namespace package whose ``__path__`` also
# contains the *installed* plugin copy under %LOCALAPPDATA%. Walk only the
# repository sources, so the suite never grades a different deployed version.
PACKAGE_ROOT = TESTS_DIR.parent / "src" / "antigravity_provider"

# Third-party packages that may legitimately be absent (GUI / optional extras).
OPTIONAL_EXTERNAL_MODULES = {
    "customtkinter",
    "tkinter",
    "PIL",
    "psutil",
    "fastapi",
    "uvicorn",
    "pydantic",
}


def _iter_module_names() -> list[str]:
    names: list[str] = []
    for mod in pkgutil.walk_packages([str(PACKAGE_ROOT)], prefix="antigravity_provider."):
        names.append(mod.name)
    return sorted(names)


def _missing_external(exc: ImportError) -> str | None:
    """Return the optional third-party module name if *exc* is caused by one."""
    name = getattr(exc, "name", None) or ""
    root = name.split(".")[0]
    if root in OPTIONAL_EXTERNAL_MODULES:
        return root
    msg = str(exc)
    for mod in sorted(OPTIONAL_EXTERNAL_MODULES, key=len, reverse=True):
        if f"No module named '{mod}'" in msg or f'No module named "{mod}"' in msg:
            return mod
        if f"No module named {mod}" in msg:
            return mod
    return None


@pytest.mark.unit
@pytest.mark.parametrize("module_name", _iter_module_names())
def test_module_is_importable(module_name: str) -> None:
    """Every shipped module must import, or fail only on an absent optional extra."""
    try:
        importlib.import_module(module_name)
    except ImportError as exc:
        external = _missing_external(exc)
        if external:
            pytest.skip(f"optional dependency '{external}' not installed")
        pytest.fail(
            f"{module_name} is not importable — broken internal reference: {exc}\n"
            "The module ships in the package but has never been executed by anything."
        )


@pytest.mark.unit
def test_no_tests_import_removed_desktop_ui() -> None:
    """Verify that no test modules import the removed CustomTkinter desktop UI."""
    GUI_BEARING_PREFIXES = (
        "customtkinter",
        "antigravity_provider.router.ui",
        "antigravity_provider.router.hermes_hub_app",
    )

    def _imports_gui(tree: ast.AST) -> bool:
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                if any(a.name.startswith(GUI_BEARING_PREFIXES) for a in node.names):
                    return True
            elif isinstance(node, ast.ImportFrom):
                if (node.module or "").startswith(GUI_BEARING_PREFIXES):
                    return True
        return False

    offenders: list[str] = []
    for path in sorted(TESTS_DIR.glob("test_*.py")):
        text = path.read_text(encoding="utf-8-sig", errors="ignore")
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        if _imports_gui(tree):
            offenders.append(path.name)

    assert not offenders, f"The following test files still import removed desktop UI: {offenders}"


@pytest.mark.unit
def test_antigravity_provider_loads_from_repo() -> None:
    """Verify that antigravity_provider is loaded from the repository src, not from %LOCALAPPDATA%."""
    import antigravity_provider
    import antigravity_provider.runtime

    pkg_file = Path(antigravity_provider.__file__).resolve()
    runtime_file = Path(antigravity_provider.runtime.__file__).resolve()

    assert str(PACKAGE_ROOT.resolve()) in str(pkg_file) or str(PACKAGE_ROOT.resolve()) in str(pkg_file.parent)
    assert str(PACKAGE_ROOT.resolve()) in str(runtime_file)
