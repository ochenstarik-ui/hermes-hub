"""Single Source of Truth for Hermes Hub Versioning."""
from __future__ import annotations

__version__ = "0.1.3"
VERSION_INFO = (0, 1, 3)
CHANNEL = "stable"
MINIMUM_HERMES_VERSION = "0.20.0"

def get_version() -> str:
    return __version__

def get_version_info() -> tuple[int, int, int]:
    return VERSION_INFO
