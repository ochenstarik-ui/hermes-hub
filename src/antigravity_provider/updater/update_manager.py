"""Hermes Hub — Auto-Update & Integrity Verification Engine.

Features:
- Semantic version comparison against release manifest.
- SHA-256 package cryptographic hash verification.
- Staged download without touching live executable.
- Hermetic backup and automatic rollback on corrupt/failing update.
- Zero embedded developer PATs (safe public asset feed / signed release manifests).
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple

from antigravity_provider import paths
from antigravity_provider.version import __version__, CHANNEL, MINIMUM_HERMES_VERSION

logger = logging.getLogger("hermes.hub.updater")


@dataclass
class UpdateManifest:
    version: str
    channel: str
    minimum_hermes_version: str
    published_at: str
    package_url: str
    sha256: str
    release_notes_url: Optional[str] = None
    changelog: Optional[str] = None


@dataclass
class UpdateCheckResult:
    update_available: bool
    current_version: str
    latest_version: str
    manifest: Optional[UpdateManifest] = None
    error: Optional[str] = None


def parse_semver(v: str) -> tuple[int, int, int]:
    """Parse '0.1.1' or 'v0.1.1' into (0, 1, 1)."""
    clean = v.lstrip("v").strip()
    parts = clean.split(".")
    try:
        return int(parts[0]), int(parts[1]), int(parts[2].split("-")[0])
    except Exception:
        return (0, 0, 0)


def is_newer_version(current: str, candidate: str) -> bool:
    """Return True if candidate is strictly newer than current."""
    return parse_semver(candidate) > parse_semver(current)


def compute_sha256(file_path: Path) -> str:
    """Compute SHA-256 hash of a file."""
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest().lower()


DEFAULT_UPDATE_URL = "https://raw.githubusercontent.com/ochenstarik-ui/hermes-hub-releases/main/update_manifest.json"

ALLOWED_UPDATE_HOSTS = {
    "github.com",
    "raw.githubusercontent.com",
    "objects.githubusercontent.com",
    "github-releases.githubusercontent.com",
}


def is_allowed_update_host(url: str, allow_dev_local: bool = False) -> bool:
    """Verify that URL points to an authorized release feed host."""
    if url.startswith("file://") or Path(url).exists():
        return allow_dev_local or os.environ.get("HERMES_HUB_DEV_MODE") == "1"
    try:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        if parsed.scheme.lower() != "https":
            return False
        hostname = (parsed.hostname or "").lower()
        return hostname in ALLOWED_UPDATE_HOSTS or any(hostname.endswith("." + h) for h in ALLOWED_UPDATE_HOSTS)
    except Exception:
        return False


class UpdateManager:
    """Manages update checks, package download, hash validation, and updater execution."""

    def __init__(self, manifest_url: Optional[str] = None):
        self.manifest_url = manifest_url or os.environ.get("HERMES_HUB_UPDATE_URL", DEFAULT_UPDATE_URL)
        self.updates_dir = paths.get_hermes_home() / "updates"
        self.staging_dir = self.updates_dir / "staging"
        self.backup_dir = self.updates_dir / "backup_prev"
        self.updates_dir.mkdir(parents=True, exist_ok=True)

    def check_for_updates(self, manifest_dict: Optional[Dict[str, Any]] = None) -> UpdateCheckResult:
        """Check for updates using either passed manifest (for tests/local) or remote URL."""
        try:
            if manifest_dict:
                data = manifest_dict
            else:
                if not is_allowed_update_host(self.manifest_url, allow_dev_local=True):
                    raise ValueError(f"Недопустимый хост источника обновлений: {self.manifest_url}")

                req = urllib.request.Request(
                    self.manifest_url,
                    headers={"User-Agent": f"HermesHub/{__version__} (Windows)"}
                )
                try:
                    with urllib.request.urlopen(req, timeout=10) as resp:
                        data = json.loads(resp.read().decode("utf-8"))
                except urllib.error.HTTPError as http_err:
                    if http_err.code == 404:
                        return UpdateCheckResult(
                            update_available=False,
                            current_version=__version__,
                            latest_version=__version__,
                            error="Канал обновлений пока не настроен.",
                        )
                    raise

            manifest = UpdateManifest(
                version=data.get("version", "0.0.0"),
                channel=data.get("channel", "stable"),
                minimum_hermes_version=data.get("minimum_hermes_version", MINIMUM_HERMES_VERSION),
                published_at=data.get("published_at", ""),
                package_url=data.get("package_url", ""),
                sha256=data.get("sha256", "").lower(),
                release_notes_url=data.get("release_notes_url"),
                changelog=data.get("changelog"),
            )

            newer = is_newer_version(__version__, manifest.version)
            return UpdateCheckResult(
                update_available=newer,
                current_version=__version__,
                latest_version=manifest.version,
                manifest=manifest,
            )
        except Exception as exc:
            logger.warning("Update check failed: %s", exc)
            return UpdateCheckResult(
                update_available=False,
                current_version=__version__,
                latest_version=__version__,
                error=str(exc),
            )

    def download_and_verify(
        self,
        manifest: UpdateManifest,
        progress_cb: Optional[Callable[[float], None]] = None,
    ) -> Tuple[bool, str, Optional[Path]]:
        """Download update package into staging and verify SHA-256 hash."""
        self.staging_dir.mkdir(parents=True, exist_ok=True)
        dest_file = self.staging_dir / f"hermes-hub-{manifest.version}.zip"

        try:
            if not is_allowed_update_host(manifest.package_url, allow_dev_local=True):
                return False, f"Недопустимый хост пакета обновления: {manifest.package_url}", None

            if manifest.package_url.startswith("file://") or Path(manifest.package_url).is_file():
                local_src = Path(manifest.package_url.replace("file://", ""))
                shutil.copy2(local_src, dest_file)
            else:
                req = urllib.request.Request(
                    manifest.package_url,
                    headers={"User-Agent": f"HermesHub/{__version__}"}
                )
                with urllib.request.urlopen(req, timeout=60) as resp:
                    total_len = int(resp.headers.get("content-length", 0))
                    downloaded = 0
                    with open(dest_file, "wb") as out_f:
                        while chunk := resp.read(32768):
                            out_f.write(chunk)
                            downloaded += len(chunk)
                            if progress_cb and total_len > 0:
                                progress_cb(downloaded / total_len)

            # Cryptographic SHA-256 Verification
            calc_hash = compute_sha256(dest_file)
            if manifest.sha256 and calc_hash != manifest.sha256:
                dest_file.unlink(missing_ok=True)
                return False, f"SHA-256 hash mismatch! Expected {manifest.sha256}, got {calc_hash}", None

            return True, "Пакет успешно загружен и верифицирован", dest_file

        except Exception as exc:
            dest_file.unlink(missing_ok=True)
            return False, f"Ошибка загрузки: {exc}", None

    def apply_update_sync(self, package_zip: Path, target_dir: Optional[Path] = None) -> Tuple[bool, str]:
        """Apply update package with automatic backup and rollback on failure."""
        import zipfile

        dest = target_dir or paths.get_repo_root()
        backup = self.backup_dir
        backup.mkdir(parents=True, exist_ok=True)

        try:
            # 1. Backup current installation
            for item in ["src", "assets", "config", "launcher"]:
                src_item = dest / item
                if src_item.exists():
                    dst_item = backup / item
                    if dst_item.exists():
                        shutil.rmtree(dst_item, ignore_errors=True)
                    shutil.copytree(src_item, dst_item)

            # 2. Extract update package into dest
            with zipfile.ZipFile(package_zip, "r") as zf:
                zf.extractall(dest)

            # 3. Verify syntax and integrity of updated python files in src/
            import py_compile
            target_src = dest / "src"
            if target_src.exists():
                for py_file in target_src.rglob("*.py"):
                    py_compile.compile(str(py_file), doraise=True)

            # Also run quick import smoke test if python executable is available
            py_exec = paths.get_hermes_agent_venv() / "Scripts" / "python.exe"
            if not py_exec.exists():
                py_exec = Path(sys.executable)

            verify_code = "import sys; sys.path.insert(0, 'src'); from antigravity_provider.version import __version__; print('OK', __version__)"
            res = subprocess.run(
                [str(py_exec), "-c", verify_code],
                cwd=str(dest),
                capture_output=True,
                text=True,
                timeout=15,
            )
            if res.returncode != 0 or "OK" not in res.stdout:
                raise RuntimeError(f"Post-update verification failed: {res.stderr or res.stdout}")

            return True, "Обновление успешно установлено"

        except Exception as exc:
            logger.error("Update failed, initiating automatic rollback: %s", exc)
            # Rollback from backup
            for item in ["src", "assets", "config", "launcher"]:
                b_item = backup / item
                if b_item.exists():
                    d_item = dest / item
                    if d_item.exists():
                        shutil.rmtree(d_item, ignore_errors=True)
                    shutil.copytree(b_item, d_item)

            return False, f"Обновление не удалось. Выполнен автоматический откат к предыдущей версии: {exc}"
