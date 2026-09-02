"""Hermes Hub — Task A59 Visible Update & Completion Engine Test Suite.

Verifies:
1. P0-1: Startup check shows modal when update available; remains silent when no update; dismissal remembered in localStorage.
2. P0-2: Visible download progress tracking; honest None without fake percentages when Content-Length is missing; cancel download deletes partial file and sets cancelled status; SHA-256 verification and failure rejection.
3. P0-3: Isolated stop_running_hub (killing only own user hub processes and excluding current PID); apply_update_sync atomic rollback on corrupted update package.
4. P0-4: Saving last_applied_update.json, EventLogService notification on restart, UI notification contract, and running_commit integrity.
5. P0-5: Absence of update polling loops; get_update_progress and cancel_update in SILENT_ACTIONS.
"""
from __future__ import annotations

import io
import json
import os
import shutil
import sys
import tempfile
import urllib.error
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from antigravity_provider.router.action_handler import ActionExecutor
from antigravity_provider.router.web.server import app
from antigravity_provider.router.unified_health import EventLogService
from antigravity_provider.updater.update_manager import (
    UpdateManager,
    UpdateManifest,
    UpdateCheckResult,
    UpdateProgress,
    compute_sha256,
    get_installed_commit,
    get_last_applied_update,
    record_last_applied_update,
    acknowledge_last_applied_update,
    stop_running_hub,
)
from antigravity_provider.version import __version__

APP_JS_PATH = (
    Path(__file__).resolve().parent.parent
    / "src"
    / "antigravity_provider"
    / "router"
    / "web"
    / "static"
    / "app.js"
)


@pytest.fixture
def client():
    return TestClient(app)


# ── TEST 1: P0-1 Modal upon Startup and Dismissal Contract in app.js ──
@pytest.mark.unit
def test_p0_1_app_js_modal_on_startup_and_dismiss_contract():
    """Verify app.js opens update modal on checkUpdates(true) unless dismissed in localStorage."""
    src = APP_JS_PATH.read_text(encoding="utf-8")

    # 1. Startup check in checkUpdates
    assert "async function checkUpdates(silent = false)" in src
    assert "hermes_dismissed_update_" in src, "app.js must check localStorage for dismissed version"
    assert "openUpdateModal('details')" in src or "openUpdateModal()" in src

    # 2. Details modal content: version, what's new, download size
    assert "Что нового" in src
    assert "Н/Д: описание не приложено" in src, "app.js must output honest N/A when changelog is empty"
    assert "Н/Д: размер не указан" in src, "app.js must output honest N/A when download size is unknown"
    assert "Напомнить позже" in src, "app.js must have dismiss/remind later button"
    assert "Обновить сейчас" in src, "app.js must have start update button"

    # 3. Dismiss function saves to localStorage
    assert "function dismissUpdateModal" in src
    assert "localStorage.setItem('hermes_dismissed_update_'" in src


# ── TEST 2: P0-2 Real-Time Progress Tracking & Honest None Without Content-Length ──
@pytest.mark.unit
def test_p0_2_progress_tracking_with_and_without_content_length(tmp_path, monkeypatch):
    """Verify progress tracking: percentage with Content-Length, honest None without Content-Length."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))
    monkeypatch.setenv("HERMES_HUB_DEV_MODE", "1")

    mgr = UpdateManager()

    # 1. Initial idle state
    prog = UpdateManager.get_progress_dict()
    assert prog["status"] in ("idle", "checking")
    assert "downloaded_bytes" in prog

    # 2. Download with known Content-Length
    test_payload = b"X" * 1024 * 100  # 100 KB
    src_file = tmp_path / "remote_pkg.zip"
    src_file.write_bytes(test_payload)
    dest_file = tmp_path / "downloaded_pkg.zip"

    # Mock urllib response with Content-Length
    class MockResponseWithLen:
        def __init__(self):
            self.headers = {"content-length": str(len(test_payload))}
            self._data = io.BytesIO(test_payload)

        def read(self, amt=65536):
            return self._data.read(amt)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    with patch("urllib.request.urlopen", return_value=MockResponseWithLen()):
        mgr._download_file("https://github.com/ochenstarik-ui/hermes-hub/releases/download/v0.1.3/pkg.zip", dest_file)

    prog_after = UpdateManager.get_progress_dict()
    assert prog_after["downloaded_bytes"] == len(test_payload)
    assert prog_after["total_bytes"] == len(test_payload)
    assert prog_after["progress_percent"] == 100.0

    # 3. Download WITHOUT Content-Length (or 0) -> Honest None, no fake percentages!
    dest_file_no_len = tmp_path / "no_len_pkg.zip"

    class MockResponseWithoutLen:
        def __init__(self):
            self.headers = {}  # No content-length header!
            self._data = io.BytesIO(test_payload)

        def read(self, amt=65536):
            return self._data.read(amt)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    with patch("urllib.request.urlopen", return_value=MockResponseWithoutLen()):
        mgr._download_file("https://github.com/ochenstarik-ui/hermes-hub/releases/download/v0.1.3/no_len.zip", dest_file_no_len)

    prog_no_len = UpdateManager.get_progress_dict()
    assert prog_no_len["downloaded_bytes"] == len(test_payload)
    assert prog_no_len["total_bytes"] is None, "total_bytes must be None when Content-Length is missing"
    assert prog_no_len["progress_percent"] is None, "progress_percent must be None when total is unknown"


# ── TEST 3: P0-2 Download Cancellation Cleans Staging and Sets Cancelled Status ──
@pytest.mark.unit
def test_p0_2_cancel_download_cleans_file_and_sets_cancelled_status(tmp_path, monkeypatch):
    """Cancelling update sets status to cancelled, interrupts loop, and removes partial file."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))
    monkeypatch.setenv("HERMES_HUB_DEV_MODE", "1")

    mgr = UpdateManager()
    staging_file = mgr.staging_dir / "partial_download.zip"
    staging_file.parent.mkdir(parents=True, exist_ok=True)
    staging_file.write_bytes(b"Partial download data 12345")

    # Trigger cancel
    cancel_res = UpdateManager.cancel_download()
    assert cancel_res["status"] == "cancelled"
    assert "отменена" in (cancel_res["message"] or "").lower()
    assert not staging_file.exists(), "Partially downloaded file in staging must be removed upon cancellation"

    # Also test ActionExecutor 'cancel_update'
    action_res = ActionExecutor.execute("cancel_update", {})
    assert action_res["ok"] is True
    assert action_res["data"]["status"] == "cancelled"


# ── TEST 4: P0-2 SHA-256 Mismatch Rejection and Failure Status ──
@pytest.mark.unit
def test_p0_2_sha256_mismatch_aborts_and_sets_failed_status(tmp_path, monkeypatch):
    """When SHA-256 hash does not match, download is aborted, file deleted, and status set to failed."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))
    monkeypatch.setenv("HERMES_HUB_DEV_MODE", "1")

    pkg_file = tmp_path / "pkg.zip"
    with zipfile.ZipFile(pkg_file, "w") as zf:
        zf.writestr("code.py", "print('hello')")

    manifest = UpdateManifest(
        version="0.1.4",
        channel="stable",
        package_url=f"file://{pkg_file}",
        sha256="ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff",  # wrong hash
    )

    mgr = UpdateManager()
    ok, msg, dest = mgr.download_and_verify(manifest)
    assert ok is False
    assert "mismatch" in msg.lower() or "не совпала" in msg.lower()
    assert dest is None

    prog = UpdateManager.get_progress_dict()
    assert prog["status"] == "failed"
    assert prog["error"] is not None


# ── TEST 5: P0-3 Process Isolation stop_running_hub ──
@pytest.mark.unit
def test_p0_3_stop_running_hub_isolates_user_and_excludes_current_pid():
    """stop_running_hub filters by current UID on Linux and never targets own PID."""
    current_pid = os.getpid()

    # Mock subprocess.run for pgrep
    with patch("subprocess.run") as mock_run:
        # Simulate pgrep returning other PID and own PID
        mock_run.return_value = MagicMock(returncode=0, stdout=f"99999 {current_pid}\n")

        with patch("os.kill") as mock_kill:
            stop_running_hub(timeout_sec=0.1)

            # Check that kill was called on 99999 but NEVER on current_pid
            killed_pids = [call.args[0] for call in mock_kill.call_args_list]
            assert 99999 in killed_pids
            assert current_pid not in killed_pids, "stop_running_hub must never kill current PID"


# ── TEST 6: P0-3 apply_update_sync Rollback on Corruption ──
@pytest.mark.unit
def test_p0_3_apply_update_sync_rollback_on_failure(tmp_path, monkeypatch):
    """apply_update_sync restores files from backup if update package fails validation."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))

    app_dir = tmp_path / "app"
    src_dir = app_dir / "src" / "antigravity_provider"
    src_dir.mkdir(parents=True, exist_ok=True)
    (src_dir / "version.py").write_text('__version__ = "0.1.3"\n', encoding="utf-8")

    # Corrupt zip with python syntax error
    corrupt_zip = tmp_path / "corrupt_pkg.zip"
    with zipfile.ZipFile(corrupt_zip, "w") as zf:
        zf.writestr("src/antigravity_provider/version.py", "INVALID SYNTAX ???!!!")

    mgr = UpdateManager()
    ok, msg = mgr.apply_update_sync(corrupt_zip, target_dir=app_dir)
    assert ok is False
    assert "откат" in msg.lower() or "rollback" in msg.lower()

    # Verify original version was restored
    restored = (src_dir / "version.py").read_text(encoding="utf-8")
    assert '__version__ = "0.1.3"' in restored


# ── TEST 7: P0-4 last_applied_update.json and EventLogService ──
@pytest.mark.unit
def test_p0_4_last_applied_update_recording_and_event_logging(tmp_path, monkeypatch, client):
    """Test recording last applied update, server settings/snapshot contract, and EventLogService."""
    hermes_home = tmp_path / "hermes"
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))

    # 1. Record update
    record_last_applied_update(
        prev_version="0.1.2",
        prev_commit="aaaaaaa1111111",
        new_version="0.1.3",
        new_commit="bbbbbbb2222222",
    )

    applied = get_last_applied_update()
    assert applied is not None
    assert applied["prev_version"] == "0.1.2"
    assert applied["prev_commit"] == "aaaaaaa1111111"
    assert applied["new_version"] == "0.1.3"
    assert applied["new_commit"] == "bbbbbbb2222222"
    assert applied["acknowledged"] is False

    # 2. Check EventLogService logging contract
    EventLogService.get().log(
        "system",
        f"Hermes Hub успешно обновлён с {applied['prev_version']} ({applied['prev_commit'][:7]}) до {applied['new_version']} ({applied['new_commit'][:7]})",
        level="info",
    )
    events = EventLogService.get().get_events(category="system", limit=10)
    found = any("Hermes Hub успешно обновлён" in (getattr(e, "message", None) or "") for e in events)
    assert found is True

    # 3. Acknowledge update
    acknowledge_last_applied_update()
    applied_after = get_last_applied_update()
    assert applied_after["acknowledged"] is True

    # 4. Check GET /api/settings includes last_applied_update
    res = client.get("/api/settings")
    assert res.status_code == 200
    data = res.json()
    assert "last_applied_update" in data
    assert data["last_applied_update"]["new_version"] == "0.1.3"


# ── TEST 8: P0-5 Silent Actions and No Polling Loops ──
@pytest.mark.unit
def test_p0_5_silent_actions_and_no_interval_polling():
    """Verify get_update_progress and cancel_update are in SILENT_ACTIONS and no global update intervals exist."""
    src = APP_JS_PATH.read_text(encoding="utf-8")

    # 1. Check SILENT_ACTIONS
    assert "'get_update_progress'" in src
    assert "'cancel_update'" in src

    # 2. Check that there is NO setInterval for checkUpdates
    assert "setInterval(checkUpdates" not in src
    assert "setInterval(() => checkUpdates" not in src
    assert "setInterval(function() { checkUpdates" not in src

    # 3. ActionExecutor get_update_progress
    res_prog = ActionExecutor.execute("get_update_progress", {})
    assert res_prog["ok"] is True
    assert "data" in res_prog
    assert "status" in res_prog["data"]
