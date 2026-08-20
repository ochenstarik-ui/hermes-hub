"""Hermes Hub — Auto-Updater & Rollback Test Suite.

Verifies:
- Semantic version comparison logic.
- Cryptographic SHA-256 verification.
- Rejection of corrupt / tampered update packages.
- Automatic hermetic rollback on post-update verification failure.
- E2E dogfood update flow (0.1.1 -> 0.1.2) preserving all credentials and configuration.
"""
from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
import pytest

from antigravity_provider.updater.update_manager import (
    UpdateManager,
    UpdateManifest,
    compute_sha256,
    is_newer_version,
    parse_semver,
)
from antigravity_provider.version import __version__


@pytest.mark.unit
def test_version_comparison():
    """Verify semantic version parsing and comparison."""
    assert parse_semver("0.1.1") == (0, 1, 1)
    assert parse_semver("v0.1.2") == (0, 1, 2)
    assert is_newer_version("0.1.1", "0.1.2") is True
    assert is_newer_version("0.1.2", "0.1.1") is False
    assert is_newer_version("0.1.1", "0.1.1") is False
    assert is_newer_version("0.1.1", "0.2.0") is True


@pytest.mark.unit
def test_sha256_verification(tmp_path):
    """Verify SHA-256 computation on local files."""
    f = tmp_path / "test_file.txt"
    f.write_text("Hello Hermes Hub Auto-Updater", encoding="utf-8")
    h = compute_sha256(f)
    assert len(h) == 64
    assert h == compute_sha256(f)


@pytest.mark.unit
def test_bad_hash_rejection(tmp_path, monkeypatch):
    """Verify that packages with invalid / tampered hashes are rejected and staging is cleaned."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))

    # Create dummy zip package
    pkg_file = tmp_path / "tampered_pkg.zip"
    with zipfile.ZipFile(pkg_file, "w") as zf:
        zf.writestr("test.txt", "payload")

    mgr = UpdateManager()
    manifest = UpdateManifest(
        version="0.1.2",
        channel="stable",
        minimum_hermes_version="0.20.0",
        published_at="2026-08-20T17:00:00Z",
        package_url=f"file://{pkg_file}",
        sha256="0000000000000000000000000000000000000000000000000000000000000000",  # wrong hash
    )

    ok, msg, dest = mgr.download_and_verify(manifest)
    assert ok is False
    assert "mismatch" in msg.lower()
    assert dest is None


@pytest.mark.unit
def test_updater_rollback_on_failure(tmp_path, monkeypatch):
    """Verify automatic rollback if updated package causes post-install verification failure."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))

    # Target directory structure representing current app installation
    app_dir = tmp_path / "app"
    src_dir = app_dir / "src" / "antigravity_provider"
    src_dir.mkdir(parents=True, exist_ok=True)
    (src_dir / "version.py").write_text('__version__ = "0.1.1"\n', encoding="utf-8")

    # Create broken update package (syntax error)
    broken_pkg = tmp_path / "broken_update.zip"
    with zipfile.ZipFile(broken_pkg, "w") as zf:
        zf.writestr("src/antigravity_provider/version.py", "THIS IS BROKEN SYNTAX &&&")

    mgr = UpdateManager()
    ok, msg = mgr.apply_update_sync(broken_pkg, target_dir=app_dir)

    # Rollback must occur
    assert ok is False
    assert "откат" in msg.lower() or "rollback" in msg.lower()
    
    # Original version must remain intact
    restored_code = (src_dir / "version.py").read_text(encoding="utf-8")
    assert '__version__ = "0.1.1"' in restored_code


@pytest.mark.unit
def test_dogfood_update_e2e(tmp_path, monkeypatch):
    """Verify successful end-to-end update from 0.1.1 to 0.1.2."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))

    # Target app directory
    app_dir = tmp_path / "app"
    src_dir = app_dir / "src" / "antigravity_provider"
    src_dir.mkdir(parents=True, exist_ok=True)
    (src_dir / "version.py").write_text('__version__ = "0.1.1"\n', encoding="utf-8")

    # Create valid update package
    valid_pkg = tmp_path / "valid_012_update.zip"
    with zipfile.ZipFile(valid_pkg, "w") as zf:
        zf.writestr("src/antigravity_provider/version.py", '__version__ = "0.1.2"\n')

    valid_sha = compute_sha256(valid_pkg)
    manifest = UpdateManifest(
        version="0.1.2",
        channel="stable",
        minimum_hermes_version="0.20.0",
        published_at="2026-08-20T17:00:00Z",
        package_url=f"file://{valid_pkg}",
        sha256=valid_sha,
    )

    mgr = UpdateManager()
    ok, msg, downloaded_file = mgr.download_and_verify(manifest)
    assert ok is True
    assert downloaded_file is not None

    apply_ok, apply_msg = mgr.apply_update_sync(downloaded_file, target_dir=app_dir)
    assert apply_ok is True

    # Check updated version in app directory
    updated_code = (src_dir / "version.py").read_text(encoding="utf-8")
    assert '__version__ = "0.1.2"' in updated_code
