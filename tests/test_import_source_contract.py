"""The repository and installed plugin must never merge into one namespace."""
from __future__ import annotations

from pathlib import Path

import antigravity_provider
import antigravity_provider.runtime as runtime


def test_provider_is_regular_package_from_repository() -> None:
    repo_src = (Path(__file__).resolve().parent.parent / "src").resolve()
    package_file = Path(antigravity_provider.__file__).resolve()
    runtime_file = Path(runtime.__file__).resolve()

    assert package_file.is_relative_to(repo_src)
    assert runtime_file.is_relative_to(repo_src)
    assert hasattr(runtime, "format_antigravity_error")
    assert list(antigravity_provider.__path__) == [str(package_file.parent)]
