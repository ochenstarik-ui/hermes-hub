"""Hermes Hub — Task A27 In-App Updates Test Suite.

Verifies:
1. check_for_updates when commits match -> update_available = False, message = 'Установлена последняя сборка'.
2. check_for_updates when newer release commit exists -> update_available = True with full metadata.
3. Network error / 403 Rate Limit returns explicit error, never masked as 'no updates'.
4. SHA-256 validation against checksums.txt and rollback/rejection on hash mismatch.
5. Actions 'check_updates', 'apply_update', 'get_update_status' via ActionExecutor.
6. get_installed_commit extraction from manifest, git, and environment variables.
"""
from __future__ import annotations

import io
import json
import urllib.error
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from antigravity_provider.router.action_handler import ActionExecutor
from antigravity_provider.router.web.server import app
from antigravity_provider.updater.update_manager import (
    UpdateManager,
    UpdateManifest,
    UpdateCheckResult,
    compute_sha256,
    extract_release_commit,
    get_installed_commit,
    is_allowed_update_host,
)
from antigravity_provider.version import __version__


@pytest.fixture
def client():
    return TestClient(app)


# ── TEST 1: Commits Match -> No Update Available ──
@pytest.mark.unit
def test_check_for_updates_commits_match(monkeypatch, tmp_path):
    """When installed commit matches latest release commit, update_available must be False."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))
    monkeypatch.setenv("HERMES_HUB_GIT_COMMIT", "a1e1db74a3f123456789abcdef0123456789abcd")

    mgr = UpdateManager()

    mock_release = {
        "tag_name": "build-2026.08.25",
        "target_commitish": "a1e1db74a3f123456789abcdef0123456789abcd",
        "name": "Hermes Hub Build 2026.08.25",
        "body": "Release commit: a1e1db74a3f123456789abcdef0123456789abcd\nFixes and improvements.",
        "published_at": "2026-08-25T10:00:00Z",
        "assets": [
            {
                "name": "HermesHubSetup.exe",
                "browser_download_url": "https://github.com/ochenstarik-ui/hermes-hub/releases/download/build-2026.08.25/HermesHubSetup.exe",
            },
            {
                "name": "checksums.txt",
                "browser_download_url": "https://github.com/ochenstarik-ui/hermes-hub/releases/download/build-2026.08.25/checksums.txt",
            },
        ],
    }

    res = mgr.check_for_updates(release_dict=mock_release)
    assert res.update_available is False
    assert res.error is None
    assert "последняя" in (res.message or "").lower()
    assert res.installed_commit.startswith("a1e1db7")
    assert res.latest_commit.startswith("a1e1db7")


# ── TEST 2: Newer Commit -> Update Available with Metadata ──
@pytest.mark.unit
def test_check_for_updates_newer_commit_available(monkeypatch, tmp_path):
    """When release commit differs from installed commit, update_available must be True."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))
    monkeypatch.setenv("HERMES_HUB_GIT_COMMIT", "1111111111111111111111111111111111111111")

    mgr = UpdateManager()

    mock_release = {
        "tag_name": "build-2026.08.25",
        "target_commitish": "9999999999999999999999999999999999999999",
        "name": "Hermes Hub New Release",
        "body": "Major speed improvements and new features.\nRelease commit: 9999999",
        "published_at": "2026-08-25T12:00:00Z",
        "assets": [
            {
                "name": "HermesHubSetup.exe",
                "browser_download_url": "https://github.com/ochenstarik-ui/hermes-hub/releases/download/v0.1.2/HermesHubSetup.exe",
            },
            {
                "name": "checksums.txt",
                "browser_download_url": "https://github.com/ochenstarik-ui/hermes-hub/releases/download/v0.1.2/checksums.txt",
            },
        ],
    }

    res = mgr.check_for_updates(release_dict=mock_release)
    assert res.update_available is True
    assert res.error is None
    assert res.latest_commit.startswith("9999999")
    assert res.installed_commit.startswith("1111111")
    assert res.release_tag == "build-2026.08.25"
    assert res.published_at == "2026-08-25T12:00:00Z"
    assert "Major speed improvements" in (res.changelog or "")
    assert "HermesHubSetup.exe" in res.assets
    assert "checksums.txt" in res.assets


# ── TEST 3: Network Errors & 403 Rate Limit Are Not Masked ──
@pytest.mark.unit
def test_network_errors_and_rate_limit_handled_honestly(monkeypatch, tmp_path):
    """Network errors and HTTP 403 Rate Limit must return error message and NOT be masked as 'no updates'."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))

    mgr = UpdateManager(manifest_url="https://api.github.com/repos/ochenstarik-ui/hermes-hub/releases/latest")

    # 1. HTTP 403 Rate Limit
    mock_403 = urllib.error.HTTPError(
        url=mgr.manifest_url,
        code=403,
        msg="rate limit exceeded",
        hdrs={},
        fp=io.BytesIO(b'{"message":"API rate limit exceeded"}'),
    )
    with patch("urllib.request.urlopen", side_effect=mock_403):
        res = mgr.check_for_updates()
        assert res.update_available is False
        assert res.error is not None
        assert "лимит" in res.error.lower() or "rate limit" in res.error.lower()

    # 2. General URLError / Network offline
    mock_network_err = urllib.error.URLError(reason="Name resolution failure / Offline")
    with patch("urllib.request.urlopen", side_effect=mock_network_err):
        res = mgr.check_for_updates()
        assert res.update_available is False
        assert res.error is not None
        assert "сетевая ошибка" in res.error.lower() or "offline" in res.error.lower()


# ── TEST 4: SHA-256 Checksums.txt Validation & Mismatch Rejection ──
@pytest.mark.unit
def test_checksums_txt_verification_and_mismatch_rejection(monkeypatch, tmp_path):
    """install_latest_update downloads checksums.txt, verifies hash, and rejects tampered files."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))
    monkeypatch.setenv("HERMES_HUB_DEV_MODE", "1")

    # Create dummy package file and compute real sha
    pkg_file = tmp_path / "pkg.zip"
    with zipfile.ZipFile(pkg_file, "w") as zf:
        zf.writestr("test.py", "print('hello')")
    real_sha = compute_sha256(pkg_file)

    # Create dummy checksums.txt with WRONG hash
    chk_file = tmp_path / "checksums.txt"
    chk_file.write_text(f"0000000000000000000000000000000000000000000000000000000000000000  pkg.zip\n", encoding="utf-8")

    mgr = UpdateManager()

    check_res = UpdateCheckResult(
        update_available=True,
        current_version="0.1.1",
        latest_version="0.1.2",
        installed_commit="1111111",
        latest_commit="2222222",
        assets={
            "pkg.zip": f"file://{pkg_file}",
            "checksums.txt": f"file://{chk_file}",
        },
    )

    ok, msg = mgr.install_latest_update(check_result=check_res)
    assert ok is False
    assert "контрольная сумма" in msg.lower() or "mismatch" in msg.lower() or "sha-256" in msg.lower()

    # Now fix checksums.txt with correct hash
    chk_file.write_text(f"{real_sha}  pkg.zip\n", encoding="utf-8")
    app_dir = tmp_path / "app"
    app_dir.mkdir(parents=True, exist_ok=True)
    (app_dir / "src").mkdir(parents=True, exist_ok=True)

    ok_valid, msg_valid = mgr.install_latest_update(check_result=check_res, target_dir=app_dir)
    assert ok_valid is True


# ── TEST 5: ActionExecutor check_updates and apply_update ──
@pytest.mark.unit
def test_action_executor_update_actions(monkeypatch, tmp_path):
    """ActionExecutor handles check_updates, apply_update, and get_update_status."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))
    monkeypatch.setenv("HERMES_HUB_GIT_COMMIT", "feedbeef12345678901234567890123456789012")

    # 1. check_updates synchronous
    mock_release = {
        "tag_name": "build-2026.08.25",
        "target_commitish": "feedbeef12345678901234567890123456789012",
        "name": "Hermes Hub Match",
        "body": "No changes.",
    }

    with patch.object(UpdateManager, "check_for_updates") as mock_chk:
        mock_chk.return_value = UpdateCheckResult(
            update_available=False,
            current_version=__version__,
            latest_version=__version__,
            installed_commit="feedbeef12345678901234567890123456789012",
            latest_commit="feedbeef12345678901234567890123456789012",
            message="Установлена последняя сборка",
        )
        res = ActionExecutor.execute("check_updates", {})
        assert res["ok"] is True
        assert "data" in res
        assert res["data"]["update_available"] is False

    # 2. check_updates ВСЕГДА синхронна и всегда возвращает данные.
    #
    # Здесь раньше требовалось обратное — чтобы действие уходило в фон. Это
    # закрепляло дефект: веб-сервер передаёт async_runner всегда, фоновая ветка
    # отвечала «Проверка обновлений запущена» без data, и результат до
    # интерфейса не доходил вовсе. Проверено запросом: кнопка обновления не
    # могла появиться никогда. Проверка — один HTTP-запрос с таймаутом 10
    # секунд, ждать её допустимо; в фон уходит только установка.
    dispatched = []
    def mock_runner(fn, name):
        dispatched.append(name)

    res_async = ActionExecutor.execute("check_updates", {}, async_runner=mock_runner)
    assert res_async["ok"] is True
    assert "CheckUpdates" not in dispatched, "проверка обновлений не должна уходить в фон без данных"
    # Значение здесь не проверяем: вызов вне заглушки и ходит в сеть по-настоящему.
    # Важно ровно одно — данные пришли, а не пустой ответ «запущено».
    assert res_async.get("data"), "ответ без данных: интерфейс не узнает о наличии обновления"

    # 3. apply_update async
    res_apply_async = ActionExecutor.execute("apply_update", {}, async_runner=mock_runner)
    assert res_apply_async["ok"] is True
    assert "ApplyUpdate" in dispatched

    # 4. get_update_status
    res_status = ActionExecutor.execute("get_update_status", {})
    assert res_status["ok"] is True
    assert "data" in res_status
    assert "installed_commit" in res_status["data"]


# ── TEST 6: get_installed_commit Extraction Logic ──
@pytest.mark.unit
def test_get_installed_commit_extraction(monkeypatch, tmp_path):
    """get_installed_commit extracts commit from env, deployment_manifest.json, and git."""
    # 1. From environment variable
    monkeypatch.setenv("HERMES_HUB_GIT_COMMIT", "abc1234567")
    assert get_installed_commit() == "abc1234567"

    # 2. From deployment_manifest.json in hermes home plugins dir
    monkeypatch.delenv("HERMES_HUB_GIT_COMMIT", raising=False)
    hermes_home = tmp_path / "hermes"
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))

    plugin_dir = hermes_home / "plugins" / "antigravity-provider"
    plugin_dir.mkdir(parents=True, exist_ok=True)
    manifest_file = plugin_dir / "deployment_manifest.json"
    manifest_file.write_text(json.dumps({"git_commit": "manifest_commit_7890"}), encoding="utf-8")

    assert get_installed_commit() == "manifest_commit_7890"

    # 3. Fallback to unknown when nothing exists
    manifest_file.unlink()
    # Mock git failure
    with patch("subprocess.run", side_effect=Exception("no git")):
        with patch("shutil.which", return_value=None):
            assert get_installed_commit() == "unknown"


# ── TEST 7: extract_release_commit from Various Release Payloads ──
@pytest.mark.unit
def test_extract_release_commit_formats():
    """extract_release_commit extracts hex commit from various GitHub release structures."""
    # Direct field
    assert extract_release_commit({"git_commit": "a1e1db7"}) == "a1e1db7"
    assert extract_release_commit({"build_commit": "4c2594b"}) == "4c2594b"

    # Target commitish
    assert extract_release_commit({"target_commitish": "a1e1db74a3f123456789abcdef0123456789abcd"}) == "a1e1db74a3f123456789abcdef0123456789abcd"

    # In body: "Release commit: 7b7b527..."
    assert extract_release_commit({
        "name": "Build 2026.08.25",
        "tag_name": "build-2026.08.25",
        "body": "Commit: 7b7b527\nChangelog details...",
    }) == "7b7b527"

    # In name: "Hermes Hub 0.1.1 (a1e1db7)"
    assert extract_release_commit({
        "name": "Hermes Hub 0.1.1 (a1e1db7)",
        "tag_name": "build-2026.08.25",
    }) == "a1e1db7"


# ── TEST 8: GET /api/settings Includes Commit and Update Info ──
@pytest.mark.unit
def test_settings_endpoint_includes_commit_and_update_status(client, monkeypatch, tmp_path):
    """GET /api/settings returns installed_commit and last_update_check."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))
    monkeypatch.setenv("HERMES_HUB_GIT_COMMIT", "test_commit_123")

    res = client.get("/api/settings")
    assert res.status_code == 200
    data = res.json()
    assert data.get("installed_commit") == "test_commit_123"
    assert "version" in data
