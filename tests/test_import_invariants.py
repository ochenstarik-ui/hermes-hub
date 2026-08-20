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
def test_gui_test_modules_guard_optional_ui_dependency() -> None:
    """Test modules touching customtkinter must call pytest.importorskip.

    Without the guard a headless environment aborts collection of the whole
    session ("Interrupted: 1 error during collection") instead of skipping the
    affected module, which takes the release gate down with it.
    """
    offenders: list[str] = []
    for path in sorted(TESTS_DIR.glob("test_*.py")):
        text = path.read_text(encoding="utf-8", errors="ignore")
        if "customtkinter" not in text:
            continue
        if "importorskip" not in text:
            offenders.append(path.name)

    assert not offenders, (
        "test modules import customtkinter without pytest.importorskip: "
        + ", ".join(offenders)
        + " — add pytest.importorskip('customtkinter') above the import"
    )
