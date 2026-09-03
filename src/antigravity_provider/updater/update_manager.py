"""Hermes Hub — Auto-Update & Integrity Verification Engine.

Features:
- Release commit comparison against main repo releases (ochenstarik-ui/hermes-hub).
- SHA-256 package cryptographic hash verification.
- Staged download without touching live executable.
- Hermetic backup and automatic rollback on corrupt/failing update.
- Real-time thread-safe progress tracking and cancellation.
- Isolated process lifecycle management (stopping only own hub processes).
- Non-blocking execution and honest error reporting (rate limits, 404, network errors).
- Zero embedded developer PATs (safe public asset feed / signed release manifests).
"""
from __future__ import annotations

import hashlib
import inspect
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple

from antigravity_provider import paths
from antigravity_provider.version import __version__, CHANNEL, MINIMUM_HERMES_VERSION
from antigravity_provider.agy_subprocess import hidden_process_kwargs

logger = logging.getLogger("hermes.hub.updater")

DEFAULT_RELEASES_API_URL = "https://api.github.com/repos/ochenstarik-ui/hermes-hub/releases/latest"
DEFAULT_UPDATE_URL = DEFAULT_RELEASES_API_URL

ALLOWED_UPDATE_HOSTS = {
    "api.github.com",
    "github.com",
    "raw.githubusercontent.com",
    "objects.githubusercontent.com",
    "github-releases.githubusercontent.com",
}


def get_installed_build_time() -> str:
    """Время установки текущей сборки из deployment_manifest.json (поле deployed_at).

    Нужно, чтобы отличать более новый релиз от более старого. Сравнение
    коммитов на равенство этого не умеет: любое расхождение оно объявляет
    обновлением, включая коммит-предок. Владелец нажимал «Обновить» и
    получал откат программы назад.
    """
    for mf in (
        paths.get_repo_root() / "deployment_manifest.json",
        paths.get_hermes_home() / "plugins" / "antigravity-provider" / "deployment_manifest.json",
    ):
        try:
            if mf.is_file():
                data = json.loads(mf.read_text(encoding="utf-8-sig"))
                val = str(data.get("deployed_at") or "").strip()
                if val:
                    return val
        except Exception as exc:
            logger.debug("Не удалось прочитать %s: %s", mf, exc)
    return ""


def _is_release_older(published_at: str, installed_at: str) -> bool:
    """True, если релиз опубликован раньше, чем установлена текущая сборка."""
    if not published_at or not installed_at:
        return False
    try:
        def _parse(v: str):
            return datetime.fromisoformat(v.strip().replace("Z", "+00:00"))

        return _parse(published_at) < _parse(installed_at)
    except Exception as exc:
        logger.debug("Не удалось сравнить даты %r и %r: %s", published_at, installed_at, exc)
        return False


def get_installed_commit() -> str:
    """Return currently installed git commit hash, checking deployment manifest, env, and git."""
    # 1. Environment variable override
    env_commit = os.environ.get("HERMES_HUB_GIT_COMMIT", "").strip()
    if env_commit:
        return env_commit

    # 2. Check deployment_manifest.json in repo root or hermes home plugin dir
    manifest_candidates = [
        paths.get_repo_root() / "deployment_manifest.json",
        paths.get_hermes_home() / "plugins" / "antigravity-provider" / "deployment_manifest.json",
    ]
    for mf in manifest_candidates:
        if mf.is_file():
            try:
                data = json.loads(mf.read_text(encoding="utf-8"))
                commit = (
                    data.get("git_commit")
                    or data.get("commit")
                    or data.get("build_commit")
                    or ""
                ).strip()
                if commit:
                    return commit
            except Exception as e:
                logger.debug("Failed reading %s: %s", mf, e)

    # 3. If running in a git clone, try git rev-parse HEAD
    repo_root = paths.get_repo_root()
    if (repo_root / ".git").exists() or shutil.which("git"):
        try:
            res = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=str(repo_root),
                capture_output=True,
                text=True,
                timeout=5,
                **hidden_process_kwargs(),
            )
            if res.returncode == 0 and res.stdout.strip():
                return res.stdout.strip()
        except Exception as e:
            logger.debug("git rev-parse HEAD failed: %s", e)

    return "unknown"


def extract_release_commit(release_data: Dict[str, Any]) -> str:
    """Extract published git commit hash from GitHub release or manifest dictionary."""
    # 1. Direct field
    for key in ("git_commit", "build_commit", "commit"):
        val = str(release_data.get(key) or "").strip()
        if val and re.fullmatch(r"[0-9a-f]{7,40}", val, re.IGNORECASE):
            return val.lower()

    # 2. Check target_commitish if it is a hex SHA
    target_commitish = str(release_data.get("target_commitish") or "").strip()
    if re.fullmatch(r"[0-9a-f]{7,40}", target_commitish, re.IGNORECASE):
        return target_commitish.lower()

    # 3. Look for explicit commit markers in body or name
    body = str(release_data.get("body") or "")
    name = str(release_data.get("name") or "")
    tag = str(release_data.get("tag_name") or "")

    combined_text = f"{name}\n{tag}\n{body}"

    # Specific patterns like "commit: <sha>" or "сборка <sha>" or "build: <sha>"
    explicit_match = re.search(
        r"(?:commit|build|сборка|rev|sha)[:\s#]+([0-9a-f]{7,40})\b",
        combined_text,
        re.IGNORECASE,
    )
    if explicit_match:
        return explicit_match.group(1).lower()

    # Generic SHA search in tag, name, body
    for part in (tag, name, body):
        m = re.search(r"\b([0-9a-f]{7,40})\b", part, re.IGNORECASE)
        if m:
            return m.group(1).lower()

    return ""


@dataclass
class UpdateProgress:
    status: str = "idle"  # idle | checking | downloading | verifying | installing | restarting | completed | failed | cancelled
    filename: str = ""
    downloaded_bytes: int = 0
    total_bytes: Optional[int] = None
    progress_percent: Optional[float] = None
    message: str = "Готов к обновлению"
    error: Optional[str] = None
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "filename": self.filename,
            "downloaded_bytes": self.downloaded_bytes,
            "total_bytes": self.total_bytes,
            "progress_percent": round(self.progress_percent, 1) if self.progress_percent is not None else None,
            "message": self.message,
            "error": self.error,
            "updated_at": self.updated_at,
        }


@dataclass
class UpdateManifest:
    version: str
    channel: str = "stable"
    minimum_hermes_version: str = MINIMUM_HERMES_VERSION
    published_at: str = ""
    package_url: str = ""
    sha256: str = ""
    release_notes_url: Optional[str] = None
    changelog: Optional[str] = None
    git_commit: Optional[str] = None
    assets: Dict[str, str] = field(default_factory=dict)
    asset_sizes: Dict[str, int] = field(default_factory=dict)


@dataclass
class UpdateCheckResult:
    update_available: bool
    current_version: str = __version__
    latest_version: str = __version__
    installed_commit: str = "unknown"
    latest_commit: str = ""
    release_tag: str = ""
    published_at: str = ""
    changelog: Optional[str] = None
    release_notes: Optional[str] = None
    assets: Dict[str, str] = field(default_factory=dict)
    asset_sizes: Dict[str, int] = field(default_factory=dict)
    download_size: Optional[int] = None
    manifest: Optional[UpdateManifest] = None
    error: Optional[str] = None
    message: Optional[str] = None
    checked_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "update_available": self.update_available,
            "current_version": self.current_version,
            "latest_version": self.latest_version,
            "installed_commit": self.installed_commit,
            "latest_commit": self.latest_commit,
            "release_tag": self.release_tag,
            "published_at": self.published_at,
            "changelog": self.changelog,
            "release_notes": self.release_notes,
            "assets": self.assets,
            "asset_sizes": self.asset_sizes,
            "download_size": self.download_size,
            "error": self.error,
            "message": self.message,
            "checked_at": self.checked_at,
        }


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


def is_allowed_update_host(url: str, allow_dev_local: bool = False) -> bool:
    """Verify that URL points to an authorized release feed host."""
    is_dev = allow_dev_local or os.environ.get("HERMES_HUB_DEV_MODE") == "1"

    if url.startswith("file://"):
        return is_dev
    if re.match(r"^[a-zA-Z]:[/\\]", url) or url.startswith(("\\\\", "./", "../", ".\\", "..\\")):
        return is_dev
    if not url.startswith("http://") and not url.startswith("https://") and not url.startswith("ftp://"):
        if Path(url).is_absolute() or Path(url).exists():
            return is_dev

    try:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        if parsed.scheme.lower() not in ("https", "http"):
            return False
        if parsed.hostname in ("127.0.0.1", "localhost") and is_dev:
            return True
        if parsed.scheme.lower() != "https":
            return False
        hostname = (parsed.hostname or "").lower()
        return hostname in ALLOWED_UPDATE_HOSTS or any(hostname.endswith("." + h) for h in ALLOWED_UPDATE_HOSTS)
    except Exception:
        return False


def get_last_applied_update_path() -> Path:
    """Path to ~/.hermes/updates/last_applied_update.json."""
    return paths.get_hermes_home() / "updates" / "last_applied_update.json"


def record_last_applied_update(
    prev_version: str,
    prev_commit: str,
    new_version: str,
    new_commit: str,
) -> None:
    """Save record of applied update for post-restart notification."""
    try:
        p = get_last_applied_update_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "prev_version": prev_version,
            "prev_commit": prev_commit,
            "new_version": new_version,
            "new_commit": new_commit,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "acknowledged": False,
        }
        p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        logger.info("Recorded last applied update: %s (%s) -> %s (%s)", prev_version, prev_commit[:7], new_version, new_commit[:7])
    except Exception as exc:
        logger.warning("Failed to record last_applied_update: %s", exc)


def get_last_applied_update() -> Optional[Dict[str, Any]]:
    """Retrieve last applied update info if present."""
    try:
        p = get_last_applied_update_path()
        if p.is_file():
            return json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.debug("Failed reading last_applied_update: %s", exc)
    return None


def acknowledge_last_applied_update() -> None:
    """Mark last applied update as acknowledged."""
    try:
        p = get_last_applied_update_path()
        if p.is_file():
            data = json.loads(p.read_text(encoding="utf-8"))
            data["acknowledged"] = True
            p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception as exc:
        logger.debug("Failed acknowledging last_applied_update: %s", exc)


def stop_running_hub(timeout_sec: float = 10.0) -> bool:
    """Останавливает только процессы хаба текущего пользователя, исключая текущий PID."""
    current_pid = os.getpid()
    is_win = sys.platform == "win32"

    if is_win:
        try:
            cmd = ["wmic", "process", "where", "name='HermesHubWeb.exe'", "get", "ProcessId"]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=5, **hidden_process_kwargs())
            pids = []
            if res.returncode == 0:
                for line in res.stdout.splitlines():
                    val = line.strip()
                    if val.isdigit():
                        pid = int(val)
                        if pid != current_pid:
                            pids.append(pid)
            for pid in pids:
                try:
                    subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True, timeout=5, **hidden_process_kwargs())
                except Exception:
                    pass
            return True
        except Exception as exc:
            logger.debug("Windows stop_running_hub: %s", exc)
            return True
    else:
        try:
            uid = os.getuid()
            pattern = "antigravity_provider.router.web|hermes_hub_web_entry"
            res = subprocess.run(
                ["pgrep", "-u", str(uid), "-f", pattern],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if res.returncode != 0 or not res.stdout.strip():
                logger.debug("No other hub processes found on Linux")
                return True

            pids = [int(p) for p in res.stdout.split() if p.strip().isdigit() and int(p) != current_pid]
            if not pids:
                return True

            logger.info("Stopping hub processes for user %s: %s", uid, pids)
            import signal
            for pid in pids:
                try:
                    os.kill(pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                except Exception as e:
                    logger.debug("Failed to SIGTERM pid %s: %s", pid, e)

            start_t = time.time()
            alive = list(pids)
            while alive and (time.time() - start_t) < timeout_sec:
                time.sleep(0.5)
                still_alive = []
                for pid in alive:
                    try:
                        os.kill(pid, 0)
                        still_alive.append(pid)
                    except ProcessLookupError:
                        pass
                alive = still_alive

            if alive:
                logger.warning("Hub processes still alive after %ss, sending SIGKILL: %s", timeout_sec, alive)
                for pid in alive:
                    try:
                        os.kill(pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    except Exception as e:
                        logger.debug("Failed to SIGKILL pid %s: %s", pid, e)

            return True
        except Exception as exc:
            logger.warning("Linux stop_running_hub error: %s", exc)
            return True


# Почему отмена отклонена — своими словами для владельца, а не кодом состояния.
_CANCEL_REFUSAL = {
    "installing": "Отмена невозможна: установка уже началась",
    "restarting": "Отмена невозможна: Hermes Hub уже перезапускается",
    "completed": "Отменять нечего: обновление уже установлено",
    "failed": "Отменять нечего: обновление уже завершилось ошибкой",
    "cancelled": "Загрузка уже отменена",
    "idle": "Отменять нечего: обновление не запускалось",
}


def _call_progress_cb(cb: Optional[Callable], downloaded: int, total: Optional[int]) -> None:
    """Вызвать обработчик хода загрузки, поддержав обе его формы.

    Старая форма принимает одну долю (0..1), новая — (скачано, всего).

    Доли при неизвестном общем размере не существует, и подставлять вместо неё
    ноль нельзя: обработчик получал бы «0%» на каждом чанке всю загрузку.
    Старую форму в этом случае просто не зовём — молчание честнее выдуманного
    числа, а сам ход всё равно виден через _set_progress.
    """
    if not cb:
        return
    known_total = bool(total and total > 0)
    try:
        sig = inspect.signature(cb)
        single_arg = len(sig.parameters) == 1
    except (TypeError, ValueError):
        single_arg = False

    if single_arg:
        if known_total:
            cb(downloaded / total)
        return

    try:
        cb(downloaded, total)
    except TypeError:
        if known_total:
            cb(downloaded / total)


class UpdateManager:
    """Manages update checks, package download, hash validation, and updater execution."""

    _lock = threading.Lock()
    _progress: UpdateProgress = UpdateProgress()
    _cancel_event = threading.Event()
    _last_check_result: Optional[UpdateCheckResult] = None
    _last_check_time: float = 0.0

    def __init__(self, manifest_url: Optional[str] = None):
        self.manifest_url = manifest_url or os.environ.get("HERMES_HUB_UPDATE_URL", DEFAULT_UPDATE_URL)
        self.updates_dir = paths.get_hermes_home() / "updates"
        self.staging_dir = self.updates_dir / "staging"
        self.backup_dir = self.updates_dir / "backup_prev"
        self.updates_dir.mkdir(parents=True, exist_ok=True)

    @classmethod
    def get_last_check_result(cls) -> Optional[UpdateCheckResult]:
        return cls._last_check_result

    @classmethod
    def get_progress_dict(cls) -> Dict[str, Any]:
        with cls._lock:
            return cls._progress.to_dict()

    @classmethod
    def _set_progress(
        cls,
        status: str,
        message: str = "",
        filename: str = "",
        downloaded_bytes: int = 0,
        total_bytes: Optional[int] = None,
        progress_percent: Optional[float] = None,
        error: Optional[str] = None,
    ) -> None:
        with cls._lock:
            cls._progress = UpdateProgress(
                status=status,
                filename=filename if filename else cls._progress.filename,
                downloaded_bytes=downloaded_bytes,
                total_bytes=total_bytes,
                progress_percent=progress_percent,
                message=message if message else cls._progress.message,
                error=error,
                updated_at=time.time(),
            )

    @classmethod
    def cancel_download(cls) -> Dict[str, Any]:
        """Отменить загрузку обновления и удалить недокачанные файлы.

        Отмена допустима только пока идёт проверка или загрузка. Действие
        `cancel_update` открыто в HTTP-API, и без этой проверки вызов во время
        установки вычищал каталог staging вместе с файлом установщика, который
        в этот момент исполняет bash: установка ломалась на середине, а ответ
        «отменено» сообщал владельцу неправду о том, что происходит с машиной.
        """
        with cls._lock:
            current_status = cls._progress.status
            if current_status not in ("checking", "downloading"):
                refused = cls._progress.to_dict()
                refused["cancel_accepted"] = False
                refused["cancel_refused_reason"] = _CANCEL_REFUSAL.get(
                    current_status,
                    f"Отмена невозможна на этапе «{current_status}»",
                )
                return refused

        cls._cancel_event.set()
        with cls._lock:
            cls._progress = UpdateProgress(
                status="cancelled",
                filename=cls._progress.filename,
                downloaded_bytes=0,
                total_bytes=None,
                progress_percent=None,
                message="Загрузка обновления отменена пользователем",
                error=None,
                updated_at=time.time(),
            )
        try:
            updates_dir = paths.get_hermes_home() / "updates"
            staging_dir = updates_dir / "staging"
            if staging_dir.exists():
                for f in staging_dir.iterdir():
                    if f.is_file():
                        f.unlink(missing_ok=True)
        except Exception as exc:
            logger.debug("Clean staging dir on cancel failed: %s", exc)
        accepted = cls.get_progress_dict()
        accepted["cancel_accepted"] = True
        return accepted

    @classmethod
    def cancel_update(cls) -> Dict[str, Any]:
        """Alias for cancel_download."""
        return cls.cancel_download()

    def get_status_dict(self) -> Dict[str, Any]:
        installed_commit = get_installed_commit()
        if self._last_check_result:
            d = self._last_check_result.to_dict()
            d["installed_commit"] = installed_commit
            return d
        return {
            "update_available": False,
            "current_version": __version__,
            "latest_version": __version__,
            "installed_commit": installed_commit,
            "latest_commit": "",
            "release_tag": "",
            "published_at": "",
            "changelog": None,
            "release_notes": None,
            "assets": {},
            "asset_sizes": {},
            "download_size": None,
            "error": None,
            "message": "Проверка обновлений еще не выполнялась",
            "checked_at": 0.0,
        }

    def check_for_updates(
        self,
        manifest_dict: Optional[Dict[str, Any]] = None,
        release_dict: Optional[Dict[str, Any]] = None,
    ) -> UpdateCheckResult:
        """Check for updates using either passed manifest/release (for tests/local) or remote URL."""
        installed_commit = get_installed_commit()
        data = release_dict if release_dict is not None else manifest_dict

        if not data:
            if not is_allowed_update_host(self.manifest_url, allow_dev_local=False):
                res = UpdateCheckResult(
                    update_available=False,
                    current_version=__version__,
                    latest_version=__version__,
                    installed_commit=installed_commit,
                    error=f"Недопустимый хост источника обновлений: {self.manifest_url}",
                )
                UpdateManager._last_check_result = res
                UpdateManager._last_check_time = time.time()
                return res

            req = urllib.request.Request(
                self.manifest_url,
                headers={
                    "User-Agent": f"HermesHub/{__version__}",
                    "Accept": "application/vnd.github.v3+json",
                },
            )
            try:
                with urllib.request.urlopen(req, timeout=15) as resp:
                    raw_body = resp.read().decode("utf-8-sig")
                    data = json.loads(raw_body)
            except urllib.error.HTTPError as http_err:
                if http_err.code == 403:
                    err_msg = "Превышен лимит запросов к GitHub API"
                elif http_err.code == 404:
                    err_msg = "Релизы не найдены в репозитории (404 Not Found)"
                else:
                    err_msg = f"Ошибка GitHub API (HTTP {http_err.code}): {http_err.reason}"
                logger.warning("Update check HTTP error: %s", err_msg)
                res = UpdateCheckResult(
                    update_available=False,
                    current_version=__version__,
                    latest_version=__version__,
                    installed_commit=installed_commit,
                    error=err_msg,
                )
                UpdateManager._last_check_result = res
                UpdateManager._last_check_time = time.time()
                return res
            except urllib.error.URLError as url_err:
                err_msg = f"Сетевая ошибка при проверке обновлений: {url_err.reason}"
                logger.warning("Update check network error: %s", err_msg)
                res = UpdateCheckResult(
                    update_available=False,
                    current_version=__version__,
                    latest_version=__version__,
                    installed_commit=installed_commit,
                    error=err_msg,
                )
                UpdateManager._last_check_result = res
                UpdateManager._last_check_time = time.time()
                return res
            except Exception as exc:
                err_msg = f"Ошибка проверки обновлений: {exc}"
                logger.warning("Update check failed: %s", exc)
                res = UpdateCheckResult(
                    update_available=False,
                    current_version=__version__,
                    latest_version=__version__,
                    installed_commit=installed_commit,
                    error=err_msg,
                )
                UpdateManager._last_check_result = res
                UpdateManager._last_check_time = time.time()
                return res

        # Process received payload
        try:
            tag_name = str(data.get("tag_name") or "")
            release_name = str(data.get("name") or "")
            body = str(data.get("body") or data.get("changelog") or "")
            published_at = str(data.get("published_at") or "")

            # Extract assets mapping {name: download_url} and asset sizes {name: size_bytes}
            assets_map: Dict[str, str] = {}
            asset_sizes: Dict[str, int] = {}
            raw_assets = data.get("assets", [])
            if isinstance(raw_assets, list):
                for asset in raw_assets:
                    if isinstance(asset, dict) and "name" in asset and "browser_download_url" in asset:
                        assets_map[asset["name"]] = asset["browser_download_url"]
                        if "size" in asset and isinstance(asset["size"], (int, float)):
                            asset_sizes[asset["name"]] = int(asset["size"])
            elif isinstance(raw_assets, dict):
                assets_map = dict(raw_assets)

            latest_commit = extract_release_commit(data)

            # Package URL and SHA256 from manifest or assets
            package_url = data.get("package_url", "")
            sha256_hash = data.get("sha256", "").lower()
            version_str = str(data.get("version") or tag_name or __version__)

            manifest = UpdateManifest(
                version=version_str,
                channel=data.get("channel", CHANNEL),
                minimum_hermes_version=data.get("minimum_hermes_version", MINIMUM_HERMES_VERSION),
                published_at=published_at,
                package_url=package_url,
                sha256=sha256_hash,
                release_notes_url=data.get("html_url") or data.get("release_notes_url"),
                changelog=body,
                git_commit=latest_commit,
                assets=assets_map,
                asset_sizes=asset_sizes,
            )

            # Determine download_size for target platform
            is_win = sys.platform == "win32"
            chosen_size: Optional[int] = None
            if is_win and "HermesHubSetup.exe" in asset_sizes:
                chosen_size = asset_sizes["HermesHubSetup.exe"]
            elif not is_win:
                for linux_name in ("hermes-hub-setup.sh", "install-linux.sh"):
                    if linux_name in asset_sizes:
                        chosen_size = asset_sizes[linux_name]
                        break
            if chosen_size is None:
                for aname, asize in asset_sizes.items():
                    if aname.endswith(".zip"):
                        chosen_size = asize
                        break
            if chosen_size is None and asset_sizes:
                chosen_size = next(iter(asset_sizes.values()), None)

            # Compare commits
            inst_clean = installed_commit.strip().lower()
            lat_clean = latest_commit.strip().lower()

            if lat_clean and inst_clean != "unknown":
                if inst_clean == lat_clean or inst_clean.startswith(lat_clean) or lat_clean.startswith(inst_clean):
                    update_available = False
                    message = "Установлена последняя сборка"
                elif _is_release_older(published_at, get_installed_build_time()):
                    # Коммиты разные, но релиз старше установленной сборки —
                    # это откат назад, а не обновление.
                    update_available = False
                    message = (
                        f"Установлена сборка новее опубликованного релиза "
                        f"({lat_clean[:7]} от {published_at[:10]})"
                    )
                else:
                    update_available = True
                    message = f"Доступно обновление (сборка {lat_clean[:7]})"
            elif lat_clean and inst_clean == "unknown":
                update_available = True
                message = f"Доступно обновление (сборка {lat_clean[:7]})"
            elif not lat_clean and "version" in data and is_newer_version(__version__, data["version"]):
                # Legacy semver fallback
                update_available = True
                message = f"Доступно обновление {data['version']}"
            else:
                update_available = False
                message = "Установлена последняя сборка"

            res = UpdateCheckResult(
                update_available=update_available,
                current_version=__version__,
                latest_version=version_str,
                installed_commit=installed_commit,
                latest_commit=latest_commit,
                release_tag=tag_name or release_name,
                published_at=published_at,
                changelog=body,
                release_notes=body,
                assets=assets_map,
                asset_sizes=asset_sizes,
                download_size=chosen_size,
                manifest=manifest,
                error=None,
                message=message,
                checked_at=time.time(),
            )
            UpdateManager._last_check_result = res
            UpdateManager._last_check_time = time.time()
            return res

        except Exception as exc:
            err_msg = f"Ошибка обработки данных обновления: {exc}"
            logger.warning("Update data processing failed: %s", exc)
            res = UpdateCheckResult(
                update_available=False,
                current_version=__version__,
                latest_version=__version__,
                installed_commit=installed_commit,
                error=err_msg,
            )
            UpdateManager._last_check_result = res
            UpdateManager._last_check_time = time.time()
            return res

    def _download_file(
        self,
        url: str,
        dest_file: Path,
        progress_cb: Optional[Callable] = None,
    ) -> None:
        """Helper to download a file with allowlist check, progress tracking, and cancellation support."""
        if not is_allowed_update_host(url, allow_dev_local=False):
            raise ValueError(f"Недопустимый хост пакета обновления: {url}")

        if self._cancel_event.is_set():
            self._set_progress(status="cancelled", filename=dest_file.name, message="Загрузка отменена")
            raise InterruptedError("Загрузка обновления отменена пользователем")

        if url.startswith("file://") or Path(url).is_file():
            local_src = Path(url.replace("file://", ""))
            total_bytes = local_src.stat().st_size if local_src.exists() else None
            self._set_progress(
                status="downloading",
                filename=dest_file.name,
                downloaded_bytes=0,
                total_bytes=total_bytes,
                progress_percent=0.0 if total_bytes else None,
                message=f"Копирование {dest_file.name}...",
            )
            if self._cancel_event.is_set():
                dest_file.unlink(missing_ok=True)
                self._set_progress(status="cancelled", filename=dest_file.name, message="Загрузка отменена")
                raise InterruptedError("Загрузка обновления отменена пользователем")

            shutil.copy2(local_src, dest_file)
            downloaded = dest_file.stat().st_size
            pct = 100.0 if total_bytes else None
            self._set_progress(
                status="downloading",
                filename=dest_file.name,
                downloaded_bytes=downloaded,
                total_bytes=total_bytes,
                progress_percent=pct,
                message=f"Файл {dest_file.name} скопирован",
            )
            if progress_cb:
                _call_progress_cb(progress_cb, downloaded, total_bytes)
            return

        req = urllib.request.Request(
            url,
            headers={"User-Agent": f"HermesHub/{__version__}"},
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw_len = resp.headers.get("content-length")
            total_len = int(raw_len) if raw_len and raw_len.isdigit() else 0
            total_bytes = total_len if total_len > 0 else None
            downloaded = 0

            self._set_progress(
                status="downloading",
                filename=dest_file.name,
                downloaded_bytes=0,
                total_bytes=total_bytes,
                progress_percent=0.0 if total_bytes else None,
                message=f"Скачивание {dest_file.name}...",
            )

            with open(dest_file, "wb") as out_f:
                while True:
                    if self._cancel_event.is_set():
                        out_f.close()
                        dest_file.unlink(missing_ok=True)
                        self._set_progress(status="cancelled", filename=dest_file.name, message="Загрузка отменена")
                        raise InterruptedError("Загрузка обновления отменена пользователем")

                    chunk = resp.read(65536)
                    if not chunk:
                        break

                    out_f.write(chunk)
                    downloaded += len(chunk)
                    pct = ((downloaded / total_bytes) * 100.0) if (total_bytes and total_bytes > 0) else None
                    self._set_progress(
                        status="downloading",
                        filename=dest_file.name,
                        downloaded_bytes=downloaded,
                        total_bytes=total_bytes,
                        progress_percent=pct,
                        message=f"Скачивание {dest_file.name}...",
                    )
                    if progress_cb:
                        _call_progress_cb(progress_cb, downloaded, total_bytes)

    def download_and_verify(
        self,
        manifest: UpdateManifest,
        progress_cb: Optional[Callable] = None,
    ) -> Tuple[bool, str, Optional[Path]]:
        """Download update package into staging and verify SHA-256 hash."""
        self._cancel_event.clear()
        self.staging_dir.mkdir(parents=True, exist_ok=True)
        dest_file = self.staging_dir / f"hermes-hub-{manifest.version}.zip"

        try:
            self._download_file(manifest.package_url, dest_file, progress_cb)

            # Cryptographic SHA-256 Verification
            self._set_progress(
                status="verifying",
                filename=dest_file.name,
                message=f"Проверка контрольной суммы SHA-256 для {dest_file.name}...",
            )
            calc_hash = compute_sha256(dest_file)
            if manifest.sha256 and calc_hash != manifest.sha256.lower():
                dest_file.unlink(missing_ok=True)
                err = f"SHA-256 hash mismatch! Expected {manifest.sha256}, got {calc_hash}"
                self._set_progress(status="failed", filename=dest_file.name, error=err, message=err)
                return False, err, None

            self._set_progress(
                status="completed",
                filename=dest_file.name,
                message="Пакет успешно загружен и верифицирован",
            )
            return True, "Пакет успешно загружен и верифицирован", dest_file

        except InterruptedError:
            dest_file.unlink(missing_ok=True)
            self._set_progress(status="cancelled", filename=dest_file.name, message="Загрузка обновления отменена")
            return False, "Загрузка обновления отменена пользователем", None
        except Exception as exc:
            dest_file.unlink(missing_ok=True)
            err = f"Ошибка загрузки: {exc}"
            self._set_progress(status="failed", filename=dest_file.name, error=err, message=err)
            return False, err, None

    def install_latest_update(
        self,
        check_result: Optional[UpdateCheckResult] = None,
        progress_cb: Optional[Callable] = None,
        target_dir: Optional[Path] = None,
    ) -> Tuple[bool, str]:
        """Download installer or update package, verify checksums, apply and restart."""
        self._cancel_event.clear()

        if check_result is None:
            self._set_progress(status="checking", message="Проверка наличия обновлений...")
            check_result = self.check_for_updates()

        if check_result.error:
            self._set_progress(status="failed", error=check_result.error, message=check_result.error)
            return False, f"Ошибка проверки обновлений: {check_result.error}"

        if not check_result.update_available:
            self._set_progress(status="idle", message="Обновление не требуется")
            return False, "Обновление не требуется (установлена последняя сборка)"

        self.staging_dir.mkdir(parents=True, exist_ok=True)
        assets = check_result.assets or {}

        # 1. Download checksums.txt if present
        checksums_map: Dict[str, str] = {}
        if "checksums.txt" in assets:
            checksums_url = assets["checksums.txt"]
            try:
                chk_file = self.staging_dir / "checksums.txt"
                self._download_file(checksums_url, chk_file)
                for line in chk_file.read_text(encoding="utf-8").splitlines():
                    parts = line.strip().split()
                    if len(parts) >= 2:
                        sha = parts[0].strip().lower()
                        fname = parts[1].lstrip("*").strip().lower()
                        checksums_map[fname] = sha
            except InterruptedError:
                return False, "Загрузка обновления отменена пользователем"
            except Exception as e:
                logger.warning("Failed to download or parse checksums.txt: %s", e)

        # 2. Determine target asset to download based on platform
        is_win = sys.platform == "win32"
        chosen_asset_name: Optional[str] = None
        chosen_url: Optional[str] = None

        if is_win:
            if "HermesHubSetup.exe" in assets:
                chosen_asset_name = "HermesHubSetup.exe"
                chosen_url = assets["HermesHubSetup.exe"]
        else:
            for linux_name in ("hermes-hub-setup.sh", "install-linux.sh"):
                if linux_name in assets:
                    chosen_asset_name = linux_name
                    chosen_url = assets[linux_name]
                    break

        # Fallback to any .zip package in assets or manifest package_url
        if not chosen_url:
            for a_name, a_url in assets.items():
                if a_name.endswith(".zip"):
                    chosen_asset_name = a_name
                    chosen_url = a_url
                    break

        if not chosen_url:
            for s_name in ("hermes-hub-setup.sh", "install-linux.sh", "HermesHubSetup.exe"):
                if s_name in assets:
                    chosen_asset_name = s_name
                    chosen_url = assets[s_name]
                    break

        if not chosen_url and check_result.manifest and check_result.manifest.package_url:
            chosen_url = check_result.manifest.package_url
            chosen_asset_name = Path(chosen_url).name or f"hermes-hub-{check_result.latest_version}.zip"

        if not chosen_url or not chosen_asset_name:
            err = "В релизе не найден подходящий файл обновления для текущей платформы"
            self._set_progress(status="failed", error=err, message=err)
            return False, err

        # 3. Download target asset into staging
        dest_file = self.staging_dir / chosen_asset_name
        try:
            self._download_file(chosen_url, dest_file, progress_cb)
        except InterruptedError:
            dest_file.unlink(missing_ok=True)
            self._set_progress(status="cancelled", filename=chosen_asset_name, message="Загрузка отменена")
            return False, "Загрузка обновления отменена пользователем"
        except Exception as exc:
            dest_file.unlink(missing_ok=True)
            err = f"Ошибка загрузки {chosen_asset_name}: {exc}"
            self._set_progress(status="failed", filename=chosen_asset_name, error=err, message=err)
            return False, err

        # 4. SHA-256 Checksum Verification
        self._set_progress(
            status="verifying",
            filename=chosen_asset_name,
            message=f"Проверка контрольной суммы SHA-256 для {chosen_asset_name}...",
        )
        calc_sha = compute_sha256(dest_file)
        expected_sha = checksums_map.get(chosen_asset_name.lower())
        if not expected_sha and check_result.manifest and check_result.manifest.sha256:
            expected_sha = check_result.manifest.sha256.lower()

        # Отсутствие суммы — не разрешение. Раньше при недоступном checksums.txt
        # expected_sha оставался пустым, проверка молча пропускалась и скачанный
        # файл всё равно запускался. Здесь запускается загруженный из сети
        # исполняемый код, поэтому непроверенный файл не запускаем вовсе.
        if not expected_sha:
            dest_file.unlink(missing_ok=True)
            err = (
                f"Не удалось получить контрольную сумму для {chosen_asset_name}: "
                "в релизе нет checksums.txt или файл не скачался. "
                "Установка отменена — непроверенный файл не запускается."
            )
            self._set_progress(status="failed", filename=chosen_asset_name, error=err, message=err)
            return False, err

        if calc_sha != expected_sha:
            dest_file.unlink(missing_ok=True)
            err = (
                f"Контрольная сумма SHA-256 не совпала для {chosen_asset_name}! "
                f"Ожидалось {expected_sha}, получено {calc_sha}. Установка отменена."
            )
            self._set_progress(status="failed", filename=chosen_asset_name, error=err, message=err)
            return False, err

        # 5. Stop running hub services before applying update
        self._set_progress(
            status="installing",
            filename=chosen_asset_name,
            message="Остановка работающих служб хаба...",
        )
        stop_running_hub()

        # Record metadata for post-restart notification
        prev_v = __version__
        prev_c = get_installed_commit()
        new_v = check_result.latest_version
        new_c = check_result.latest_commit or ""

        # 6. Apply update based on file type
        self._set_progress(
            status="installing",
            filename=chosen_asset_name,
            message=f"Установка пакета {chosen_asset_name}...",
        )

        def _record_success():
            record_last_applied_update(
                prev_version=prev_v,
                prev_commit=prev_c,
                new_version=new_v,
                new_commit=new_c,
            )

        if chosen_asset_name.endswith(".zip"):
            ok, msg = self.apply_update_sync(dest_file, target_dir=target_dir)
            if not ok:
                self._set_progress(status="failed", filename=chosen_asset_name, error=msg, message=msg)
                return False, msg
            _record_success()
            self._set_progress(status="completed", filename=chosen_asset_name, message=msg)
            return True, "Обновление успешно установлено"

        elif chosen_asset_name == "HermesHubSetup.exe":
            try:
                cmd = [str(dest_file), "/silent", "/reinstall", "/restart"]
                creation_flags = 0
                if hasattr(subprocess, "DETACHED_PROCESS") and hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
                    creation_flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
                proc = subprocess.Popen(cmd, creationflags=creation_flags)
                try:
                    rc = proc.wait(timeout=600)
                except subprocess.TimeoutExpired:
                    err = "Установщик не завершился за 10 минут. Проверьте состояние вручную."
                    self._set_progress(status="failed", filename=chosen_asset_name, error=err, message=err)
                    return False, err
                if rc != 0:
                    err = f"Установщик завершился с кодом {rc}. Обновление не применено."
                    self._set_progress(status="failed", filename=chosen_asset_name, error=err, message=err)
                    return False, err
                _record_success()
                self._set_progress(status="restarting", filename=chosen_asset_name, message="Hermes Hub перезапускается...")
                ok_r, msg_r = self.schedule_restart()
                if not ok_r:
                    self._set_progress(status="completed", filename=chosen_asset_name, message=f"Обновление установлено. {msg_r}")
                    return True, f"Обновление установлено. {msg_r}"
                self._set_progress(status="restarting", filename=chosen_asset_name, message="Обновление установлено, Hermes Hub перезапускается.")
                return True, "Обновление установлено, Hermes Hub перезапускается."
            except Exception as exc:
                err = f"Не удалось запустить установщик: {exc}"
                self._set_progress(status="failed", filename=chosen_asset_name, error=err, message=err)
                return False, err

        elif chosen_asset_name.endswith(".sh"):
            try:
                os.chmod(dest_file, 0o755)
                # Ждём завершения: без этого перезапуск начался бы прямо во
                # время распаковки, а владелец получил бы обещание перезапуска
                # при неизвестном исходе установки.
                res_i = subprocess.run(
                    ["bash", str(dest_file)],
                    capture_output=True, text=True, timeout=600,
                )
                if res_i.returncode != 0:
                    # Код возврата в сообщении обязателен: установщик может
                    # завершиться, не сказав ни слова, и владелец получал
                    # «Установка не удалась: » без единого признака причины.
                    tail = (res_i.stderr or res_i.stdout or "").strip().splitlines()[-3:]
                    if tail:
                        err = f"Установка не удалась (код {res_i.returncode}): " + " / ".join(tail)
                    else:
                        err = f"Установка не удалась (код {res_i.returncode}): установщик ничего не сообщил"
                    self._set_progress(status="failed", filename=chosen_asset_name, error=err, message=err)
                    return False, err
                _record_success()
                self._set_progress(status="restarting", filename=chosen_asset_name, message="Hermes Hub перезапускается...")
                ok_r, msg_r = self.schedule_restart()
                if not ok_r:
                    self._set_progress(status="completed", filename=chosen_asset_name, message=f"Обновление установлено. {msg_r}")
                    return True, f"Обновление установлено. {msg_r}"
                self._set_progress(status="restarting", filename=chosen_asset_name, message="Обновление установлено, Hermes Hub перезапускается.")
                return True, "Обновление установлено, Hermes Hub перезапускается."
            except Exception as exc:
                err = f"Не удалось запустить скрипт установки: {exc}"
                self._set_progress(status="failed", filename=chosen_asset_name, error=err, message=err)
                return False, err

        self._set_progress(status="completed", filename=chosen_asset_name, message="Файл обновления загружен и проверен")
        return True, "Файл обновления загружен и проверен"

    def schedule_restart(self, delay_sec: float = 3.0) -> Tuple[bool, str]:
        """Перезапустить веб-хаб после установки обновления.

        Ни install-linux.sh, ни виндовый установщик в тихом режиме приложение не
        поднимают, а сообщение обещало перезапуск. Владелец оставался со старым
        процессом, продолжавшим отдавать старый код, и делал вывод, что
        обновление не сработало.

        Порядок именно такой: сначала отсоединённый помощник, потом выход
        текущего процесса. Лаунчер считает хаб работающим, если порт отвечает,
        поэтому поднимать новый, не освободив порт, бесполезно.
        """
        home = paths.get_hermes_home()
        if sys.platform == "win32":
            launcher = home / "HermesHubWeb.exe"
        else:
            launcher = Path.home() / ".local" / "bin" / "hermes-hub-web"

        if not launcher.exists():
            return False, f"Лаунчер не найден: {launcher}. Запустите Hermes Hub вручную."

        try:
            if sys.platform == "win32":
                flags = 0
                if hasattr(subprocess, "DETACHED_PROCESS") and hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
                    flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
                subprocess.Popen(
                    ["cmd", "/c", f"timeout /t {int(delay_sec)} >nul & \"{launcher}\""],
                    creationflags=flags,
                )
            else:
                subprocess.Popen(
                    ["nohup", "sh", "-c", f"sleep {delay_sec}; exec '{launcher}'"],
                    start_new_session=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
        except Exception as exc:
            return False, f"Не удалось запланировать перезапуск: {exc}. Запустите Hermes Hub вручную."

        def _exit_soon() -> None:
            time.sleep(max(0.5, delay_sec - 1.5))
            os._exit(0)

        threading.Thread(target=_exit_soon, daemon=True, name="hub-restart").start()
        return True, "Перезапуск запланирован"

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
                **hidden_process_kwargs(),
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
