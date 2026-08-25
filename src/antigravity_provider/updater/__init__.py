"""Hermes Hub Auto-Updater Package."""
from .update_manager import (
    UpdateManager,
    UpdateManifest,
    UpdateCheckResult,
    is_newer_version,
    compute_sha256,
    get_installed_commit,
    extract_release_commit,
    is_allowed_update_host,
)

__all__ = [
    "UpdateManager",
    "UpdateManifest",
    "UpdateCheckResult",
    "is_newer_version",
    "compute_sha256",
    "get_installed_commit",
    "extract_release_commit",
    "is_allowed_update_host",
]
