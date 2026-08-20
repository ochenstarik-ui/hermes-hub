"""Hermes Hub provider package.

This explicit package boundary prevents Python from merging the repository and
an older installed plugin copy as a namespace package. A process therefore
loads one coherent source tree instead of a mixture of versions.
"""
from __future__ import annotations

from pathlib import Path

from .version import __version__

PACKAGE_ROOT = Path(__file__).resolve().parent

__all__ = ["PACKAGE_ROOT", "__version__"]
