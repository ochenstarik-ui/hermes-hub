"""Tests for Task A58: Antigravity CLI (agy) Eligibility State Detection and Controls.

Verifies:
- Read-only machine code inspection for x86-64 and arm64 signatures.
- Detection of all 3 states: check_removed, check_active, unknown (with exact reasons).
- Strict read-only guarantee (SHA256 binary integrity preserved).
- State change event bus publishing and audit logging without continuous polling loops.
- Action handlers for run_agy_patch_script, run_agy_update, and refresh_agy_eligibility.
- Web API endpoints (/api/snapshot, /api/settings) returning agy_eligibility.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from antigravity_provider.router.agy_eligibility_service import (
    STATUS_CHECK_ACTIVE,
    STATUS_CHECK_REMOVED,
    STATUS_UNKNOWN,
    AgyEligibilityService,
)
from antigravity_provider.router.event_bus import (
    EVENT_AGY_ELIGIBILITY_CHANGED,
    EventBus,
)
from antigravity_provider.router.settings_service import (
    get_hub_settings,
    save_hub_settings,
)
from antigravity_provider.router.unified_health import EventLogService
from antigravity_provider.router.web.server import app


@pytest.fixture(autouse=True)
def reset_service():
    """Reset singleton cache before and after each test."""
    service = AgyEligibilityService.get()
    service.invalidate_cache()
    service._last_status = None
    service._last_status_label = None
    service._last_sha256 = None
    service._last_binary_path = None
    yield
    service.invalidate_cache()
    service._last_status = None
    service._last_status_label = None
    service._last_sha256 = None
    service._last_binary_path = None


def test_real_agy_binary_if_present():
    """Verify inspection against the real host binary at ~/.local/bin/agy if available."""
    real_path = Path.home() / ".local" / "bin" / "agy"
    if not real_path.is_file():
        pytest.skip("Real agy binary not found on this host")

    with open(real_path, "rb") as f:
        original_bytes = f.read()
    expected_sha = hashlib.sha256(original_bytes).hexdigest()

    service = AgyEligibilityService.get()
    res = service.check_eligibility_state(force=True, custom_binary_path=real_path)

    assert res["binary_path"] == str(real_path)
    assert res["binary_sha256"] == expected_sha
    assert res["binary_size_bytes"] == len(original_bytes)
    assert res["status"] in (STATUS_CHECK_ACTIVE, STATUS_CHECK_REMOVED, STATUS_UNKNOWN)
    assert res["status_label_ru"] != ""

    # Verify 100% read-only integrity: file was not modified
    with open(real_path, "rb") as f:
        after_bytes = f.read()
    assert hashlib.sha256(after_bytes).hexdigest() == expected_sha


def test_x86_unpatched_signature_detected(tmp_path: Path):
    """P0-1 & P0-2: Unpatched x86-64 binary matches check_active."""
    # Machine code: test rax,rax ; je ; cmp byte [rax+8], 0 ; jne ; call
    fake_code = (
        b"\x90\x90"
        b"\x48\x85\xc0\x0f\x84\x0d\x02\x00\x00\x80\x78\x08\x00\x0f\x85\x03\x02\x00\x00\xe8\x48\x9c\xfd\xff"
        b"\x90\x90"
    )
    fake_bin = tmp_path / "fake_agy_x86_orig"
    fake_bin.write_bytes(fake_code)

    service = AgyEligibilityService.get()
    res = service.check_eligibility_state(force=True, custom_binary_path=fake_bin)

    assert res["status"] == STATUS_CHECK_ACTIVE
    assert "Проверка на месте" in res["status_label_ru"]
    assert "Аккаунт может отклоняться" in res["detail_ru"]
    assert res["binary_sha256"] == hashlib.sha256(fake_code).hexdigest()


def test_x86_patched_signature_detected(tmp_path: Path):
    """P0-1 & P0-2: Patched x86-64 binary matches check_removed."""
    # Machine code: test rax,rax ; je ; test rax,rax ; nop ; jne ; call
    fake_code = (
        b"\x90\x90"
        b"\x48\x85\xc0\x0f\x84\x0d\x02\x00\x00\x48\x85\xc0\x90\x0f\x85\x03\x02\x00\x00\xe8\x48\x9c\xfd\xff"
        b"\x90\x90"
    )
    fake_bin = tmp_path / "fake_agy_x86_patched"
    fake_bin.write_bytes(fake_code)

    service = AgyEligibilityService.get()
    res = service.check_eligibility_state(force=True, custom_binary_path=fake_bin)

    assert res["status"] == STATUS_CHECK_REMOVED
    assert "Проверка снята" in res["status_label_ru"]
    assert "Патч начальной проверки" in res["detail_ru"]
    assert res["binary_sha256"] == hashlib.sha256(fake_code).hexdigest()


def test_arm64_signatures_detected(tmp_path: Path):
    """P0-1 & P0-2: ARM64 original and patched detection."""
    # ARM64 unpatched
    arm_orig_code = b"HEADER\x00EPD_ELIGIBILITY\x00\x00\x20\x40\x39\x00\x00TRAILER"
    bin_orig = tmp_path / "fake_agy_arm64_orig"
    bin_orig.write_bytes(arm_orig_code)

    service = AgyEligibilityService.get()
    res_orig = service.check_eligibility_state(force=True, custom_binary_path=bin_orig)
    assert res_orig["status"] == STATUS_CHECK_ACTIVE
    assert "Проверка на месте" in res_orig["status_label_ru"]

    # ARM64 patched (NOP)
    arm_patch_code = b"HEADER\x00EPD_ELIGIBILITY\x00\x1f\x20\x03\xd5\x00\x00TRAILER"
    bin_patch = tmp_path / "fake_agy_arm64_patch"
    bin_patch.write_bytes(arm_patch_code)

    service.invalidate_cache()
    res_patch = service.check_eligibility_state(force=True, custom_binary_path=bin_patch)
    assert res_patch["status"] == STATUS_CHECK_REMOVED
    assert "Проверка снята" in res_patch["status_label_ru"]


def test_unknown_state_unsupported_binary(tmp_path: Path):
    """P0-2: Unsupported binary returns status 'unknown' with truthful reason."""
    fake_code = b"Hello, this is a completely different binary without signatures."
    fake_bin = tmp_path / "fake_agy_unknown"
    fake_bin.write_bytes(fake_code)

    service = AgyEligibilityService.get()
    res = service.check_eligibility_state(force=True, custom_binary_path=fake_bin)

    assert res["status"] == STATUS_UNKNOWN
    assert "Н/Д: сигнатура проверки не найдена" in res["status_label_ru"]
    assert "неподдерживаемая версия" in res["detail_ru"]


def test_unknown_state_missing_file(tmp_path: Path):
    """P0-2: Missing binary path returns status 'unknown'."""
    missing_bin = tmp_path / "non_existent_agy_binary"

    service = AgyEligibilityService.get()
    res = service.check_eligibility_state(force=True, custom_binary_path=missing_bin)

    assert res["status"] == STATUS_UNKNOWN
    assert "Н/Д: файл не найден" in res["status_label_ru"]


def test_read_only_guarantee(tmp_path: Path):
    """Strictly guarantees that checking eligibility NEVER modifies the file."""
    fake_code = b"\x48\x85\xc0\x74\x02\x80\x78\x08\x00\x75\x02"
    fake_bin = tmp_path / "test_bin_readonly"
    fake_bin.write_bytes(fake_code)
    mtime_before = fake_bin.stat().st_mtime
    sha_before = hashlib.sha256(fake_code).hexdigest()

    service = AgyEligibilityService.get()
    res = service.check_eligibility_state(force=True, custom_binary_path=fake_bin)

    assert res["status"] == STATUS_CHECK_ACTIVE
    assert fake_bin.read_bytes() == fake_code
    assert fake_bin.stat().st_mtime == mtime_before
    assert hashlib.sha256(fake_bin.read_bytes()).hexdigest() == sha_before


def test_state_change_event_and_audit_logging(tmp_path: Path):
    """P0-3: State transition publishes EventBus event and logs to EventLogService."""
    events_received = []

    def on_event(event_name, data):
        events_received.append((event_name, data))

    EventBus.get().subscribe(EVENT_AGY_ELIGIBILITY_CHANGED, on_event)

    bin_path = tmp_path / "mutable_test_agy"

    # Step 1: Initial state is check_active
    code_active = b"\x48\x85\xc0\x74\x02\x80\x78\x08\x00\x75\x02"
    bin_path.write_bytes(code_active)

    service = AgyEligibilityService.get()
    res1 = service.check_eligibility_state(force=True, custom_binary_path=bin_path)
    assert res1["status"] == STATUS_CHECK_ACTIVE

    # Step 2: Simulate owner running patch script -> binary transitions to check_removed
    code_patched = b"\x48\x85\xc0\x74\x02\x48\x85\xc0\x90\x75\x02"
    bin_path.write_bytes(code_patched)

    service.invalidate_cache()
    res2 = service.check_eligibility_state(force=True, custom_binary_path=bin_path)
    assert res2["status"] == STATUS_CHECK_REMOVED

    # EventBus must have received the transition event
    assert len(events_received) == 1
    assert events_received[0][0] == EVENT_AGY_ELIGIBILITY_CHANGED
    assert events_received[0][1]["status"] == STATUS_CHECK_REMOVED

    # EventLogService must contain security audit log
    logs = EventLogService.get().get_events(category="security")
    found_logs = [log for log in logs if getattr(log, "action", None) == "agy_eligibility_change" or (isinstance(log, dict) and log.get("action") == "agy_eligibility_change")]
    assert len(found_logs) >= 1
    last_log = found_logs[-1]
    msg = getattr(last_log, "message", None) if not isinstance(last_log, dict) else last_log.get("message", "")
    assert "Проверка на месте → Проверка снята" in msg

    EventBus.get().unsubscribe(EVENT_AGY_ELIGIBILITY_CHANGED, on_event)


def test_action_run_agy_patch_script_not_configured():
    """P0-4: When patch script path is empty, action returns informative message."""
    client = TestClient(app)
    # Ensure setting is empty
    save_hub_settings({"agy_patch_script_path": ""})

    response = client.post("/api/action", json={"action": "run_agy_patch_script"})
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is False
    assert "Н/Д: путь к сценарию патча не указан в настройках" in data["message"]


def test_action_run_agy_patch_script_invalid_path(tmp_path: Path):
    """P0-4: When patch script file does not exist, action returns error."""
    client = TestClient(app)
    missing_script = tmp_path / "non_existent_patch.sh"
    save_hub_settings({"agy_patch_script_path": str(missing_script)})

    response = client.post("/api/action", json={"action": "run_agy_patch_script"})
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is False
    assert "Файл сценария не найден или недоступен" in data["message"]


def test_action_run_agy_patch_script_success(tmp_path: Path):
    """P0-4: Valid patch script launches in terminal and returns new eligibility state."""
    client = TestClient(app)
    patch_script = tmp_path / "fake_patch.sh"
    patch_script.write_text("#!/bin/sh\necho Patched\n")
    patch_script.chmod(0o755)

    save_hub_settings({"agy_patch_script_path": str(patch_script)})

    with patch("antigravity_provider.agy_subprocess.launch_terminal_task") as mock_launch:
        mock_launch.return_value = (True, "Запущено", {"terminal_cmd": "xterm"})
        response = client.post("/api/action", json={"action": "run_agy_patch_script"})
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert "Сценарий патча запущен" in data["message"]
        assert "eligibility" in data["data"]


def test_action_run_agy_update():
    """P0-5: Action run_agy_update launches agy update in terminal."""
    client = TestClient(app)

    with patch("antigravity_provider.agy_subprocess.get_agy_exe", return_value="/bin/agy"), \
         patch("antigravity_provider.agy_subprocess.launch_terminal_task") as mock_launch:
        mock_launch.return_value = (True, "Запущено", {"terminal_cmd": "xterm"})
        response = client.post("/api/action", json={"action": "run_agy_update"})
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert "Обновление agy запущено" in data["message"]
        assert "eligibility" in data["data"]


def test_action_refresh_agy_eligibility():
    """Action refresh_agy_eligibility triggers cache invalidation and recheck."""
    client = TestClient(app)
    response = client.post("/api/action", json={"action": "refresh_agy_eligibility"})
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert "Состояние проверки agy" in data["message"]
    assert "status" in data["data"]


def test_web_api_snapshot_and_settings_include_eligibility():
    """Verify /api/snapshot and /api/settings contain agy_eligibility payload."""
    client = TestClient(app)

    # Snapshot endpoint
    snap_resp = client.get("/api/snapshot")
    assert snap_resp.status_code == 200
    snap_data = snap_resp.json()
    assert "agy_eligibility" in snap_data
    elig = snap_data["agy_eligibility"]
    assert "status" in elig
    assert "status_label_ru" in elig
    assert "binary_sha256" in elig

    # Settings endpoint
    sett_resp = client.get("/api/settings")
    assert sett_resp.status_code == 200
    sett_data = sett_resp.json()
    assert "agy_eligibility" in sett_data
    assert "agy_patch_script_path" in sett_data
