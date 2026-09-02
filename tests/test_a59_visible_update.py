"""Hermes Hub — Task A59 Visible Update & Completion Engine Test Suite.

Verifies:
1. P0-1: Startup check shows modal when update available; remains silent when no update; dismissal remembered in localStorage.
2. P0-2: Visible download progress tracking; honest None without fake percentages when Content-Length is missing; cancel download deletes partial file and sets cancelled status; SHA-256 verification and failure rejection.
3. P0-3: Isolated stop_running_hub (killing only own user hub processes and excluding current PID); apply_update_sync atomic rollback on corrupted update package.
4. P0-4: Saving last_applied_update.json, EventLogService notification on restart, UI notification contract, and running_commit integrity.
5. P0-5: Absence of update polling loops; get_update_progress and cancel_update in SILENT_ACTIONS.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import re
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

    # Отмена осмысленна только пока идёт загрузка — ставим это состояние явно,
    # иначе тест проверял бы отмену того, чего не происходит.
    UpdateManager._set_progress(
        status="downloading",
        filename="partial_download.zip",
        downloaded_bytes=27,
        message="Скачивание partial_download.zip...",
    )

    # Trigger cancel
    cancel_res = UpdateManager.cancel_download()
    assert cancel_res["status"] == "cancelled"
    assert cancel_res["cancel_accepted"] is True
    assert "отменена" in (cancel_res["message"] or "").lower()
    assert not staging_file.exists(), "Partially downloaded file in staging must be removed upon cancellation"

    # Also test ActionExecutor 'cancel_update'
    UpdateManager._set_progress(status="downloading", filename="partial_download.zip")
    action_res = ActionExecutor.execute("cancel_update", {})
    assert action_res["ok"] is True
    assert action_res["data"]["status"] == "cancelled"


# ── TEST 3b: отмена после начала установки отклоняется, а не врёт ──
@pytest.mark.unit
def test_p0_2_cancel_refused_after_install_started(tmp_path, monkeypatch):
    """Отмена во время установки не трогает staging и честно сообщает отказ.

    Действие cancel_update открыто в HTTP-API. Раньше вызов на этапе installing
    чистил каталог staging вместе с исполняемым в этот момент установщиком и
    отвечал «отменено», хотя установка продолжалась.
    """
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))
    monkeypatch.setenv("HERMES_HUB_DEV_MODE", "1")

    mgr = UpdateManager()
    installer = mgr.staging_dir / "hermes-hub-setup.sh"
    installer.parent.mkdir(parents=True, exist_ok=True)
    installer.write_bytes(b"#!/bin/bash\necho installing\n")

    UpdateManager._set_progress(
        status="installing",
        filename="hermes-hub-setup.sh",
        message="Установка пакета hermes-hub-setup.sh...",
    )

    res = UpdateManager.cancel_download()
    assert res["cancel_accepted"] is False
    assert res["status"] == "installing", "Статус не должен подменяться на cancelled"
    assert "установка уже началась" in res["cancel_refused_reason"].lower()
    assert installer.exists(), "Файл исполняемого установщика удалять нельзя"

    action_res = ActionExecutor.execute("cancel_update", {})
    assert action_res["ok"] is False
    assert "отмена невозможна" in action_res["message"].lower()

    UpdateManager._set_progress(status="idle", message="Готов к обновлению")


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
@pytest.mark.parametrize("simulated_os", ["linux", "windows"])
@pytest.mark.unit
def test_p0_3_stop_running_hub_isolates_user_and_excludes_current_pid(simulated_os):
    """Чужие процессы хаба останавливаются, собственный — никогда.

    Проверяется на обеих ветках, а не на той, где случился прогон. Ветки
    останавливают процессы по-разному: на Linux — os.kill по списку от pgrep,
    на Windows — taskkill по списку от wmic. Тест знал только про первую и на
    Windows-раннере падал на пустом списке убитых, хотя проверять надо один и
    тот же инвариант — «свой PID не трогаем».
    """
    current_pid = os.getpid()
    is_win = simulated_os == "windows"

    with patch("antigravity_provider.updater.update_manager.sys") as mock_sys:
        mock_sys.platform = "win32" if is_win else "linux"

        # На Windows os.getuid не существует; ветка Linux падала бы на нём в
        # общий except и возвращала «остановлено» никого не остановив. create=True
        # позволяет подставить его там, где его нет.
        with patch("os.getuid", return_value=1000, create=True), patch("subprocess.run") as mock_run:
            # wmic и pgrep перечисляют один и тот же набор: чужой PID и свой.
            mock_run.return_value = MagicMock(returncode=0, stdout=f"99999\n{current_pid}\n")

            with patch("os.kill") as mock_kill:
                stop_running_hub(timeout_sec=0.1)

                if is_win:
                    killed_pids = [
                        int(call.args[0][-1])
                        for call in mock_run.call_args_list
                        if call.args and call.args[0] and call.args[0][0] == "taskkill"
                    ]
                else:
                    killed_pids = [call.args[0] for call in mock_kill.call_args_list]

    assert 99999 in killed_pids, f"[{simulated_os}] чужой процесс хаба не остановлен: {killed_pids}"
    assert current_pid not in killed_pids, f"[{simulated_os}] остановлен собственный процесс"


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


# ── TEST 9: P0-4 провалившаяся установка не выдаёт себя за успешную ──
@pytest.mark.unit
def test_p0_4_failed_install_records_nothing_and_names_exit_code(tmp_path, monkeypatch):
    """Установщик упал — записи о применённом обновлении быть не должно.

    record_last_applied_update вызывался ДО запуска установщика. При падении
    запись оставалась на диске, и при следующем старте хаб писал в журнал
    «успешно обновлён», а интерфейс показывал тост об успехе — владельцу
    сообщали о версии, которая не установилась.

    Заодно проверяется, что причина отказа не пустая: установщик может
    завершиться, не сказав ни слова, и сообщение «Установка не удалась: »
    не давало ни одного признака причины.
    """
    import hashlib

    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))
    monkeypatch.setenv("HERMES_HUB_DEV_MODE", "1")

    with platform_installer(tmp_path, exit_code=3) as (asset_name, installer):
        sha = hashlib.sha256(installer.read_bytes()).hexdigest()

        check_result = UpdateCheckResult(
            update_available=True,
            current_version="0.1.3",
            latest_version="0.1.4",
            latest_commit="deadbeefdeadbeef",
            installed_commit="0000000aaaa",
            assets={
                asset_name: f"file://{installer}",
                "checksums.txt": "file:///nonexistent",
            },
        )

        mgr = UpdateManager()
        real_download = UpdateManager._download_file

        def fake_download(self, url, dest, progress_cb=None):
            if dest.name == "checksums.txt":
                dest.write_text(f"{sha}  {asset_name}\n", encoding="utf-8")
                return
            return real_download(self, url, dest, progress_cb)

        with patch.object(UpdateManager, "_download_file", fake_download):
            with patch("antigravity_provider.updater.update_manager.stop_running_hub", return_value=True):
                ok, msg = mgr.install_latest_update(check_result=check_result)

    assert ok is False
    assert get_last_applied_update() is None, (
        "После провалившейся установки записи о применённом обновлении быть не должно"
    )
    # Проверяется, что код назван, а не как он склоняется: ветки формулируют
    # по-разному («код 3» и «кодом 3»), инвариант же один.
    assert re.search(r"код\w*\s+3", msg), (
        f"Причина отказа должна называть код возврата, получено: {msg!r}"
    )

    prog = UpdateManager.get_progress_dict()
    assert prog["status"] == "failed"

    UpdateManager._set_progress(status="idle", message="Готов к обновлению")


# ── Установщик под ту систему, на которой идёт прогон ──
#
# Ветки установки различаются: на Windows выбирается HermesHubSetup.exe и
# запускается через Popen, на Linux — hermes-hub-setup.sh через bash. Тесты
# ниже проверяют не установщик, а учёт его результата, поэтому подставляется
# тот файл, который данная система действительно выбирает. Раньше в них был
# зашит bash-скрипт, и на Windows-раннере установка отвечала «в релизе не
# найден подходящий файл обновления» — падало допущение теста, не продукт.

@contextlib.contextmanager
def platform_installer(tmp_path, exit_code: int):
    """Отдать (имя ассета, путь) и заставить установщик вернуть exit_code."""
    if sys.platform == "win32":
        installer = tmp_path / "HermesHubSetup.exe"
        # Содержимое не исполняется: запуск подменён, проверяется учёт кода.
        installer.write_bytes(b"MZ\x90\x00 hermes hub test installer\n")
        with patch("subprocess.Popen") as mock_popen:
            mock_popen.return_value = MagicMock(wait=MagicMock(return_value=exit_code))
            yield "HermesHubSetup.exe", installer
    else:
        installer = tmp_path / "hermes-hub-setup.sh"
        installer.write_bytes(f"#!/bin/bash\nexit {exit_code}\n".encode("utf-8"))
        yield "hermes-hub-setup.sh", installer


# ── TEST 10: P0-4 успешная установка запись всё-таки делает ──
@pytest.mark.unit
def test_p0_4_successful_install_records_previous_and_new_build(tmp_path, monkeypatch):
    """Успех записывает и «было», и «стало», причём «было» снято до установки."""
    import hashlib

    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))
    monkeypatch.setenv("HERMES_HUB_DEV_MODE", "1")

    with platform_installer(tmp_path, exit_code=0) as (asset_name, installer):
        sha = hashlib.sha256(installer.read_bytes()).hexdigest()

        check_result = UpdateCheckResult(
            update_available=True,
            current_version="0.1.3",
            latest_version="0.1.4",
            latest_commit="deadbeefdeadbeef",
            installed_commit="0000000aaaa",
            assets={
                asset_name: f"file://{installer}",
                "checksums.txt": "file:///nonexistent",
            },
        )

        mgr = UpdateManager()
        real_download = UpdateManager._download_file

        def fake_download(self, url, dest, progress_cb=None):
            if dest.name == "checksums.txt":
                dest.write_text(f"{sha}  {asset_name}\n", encoding="utf-8")
                return
            return real_download(self, url, dest, progress_cb)

        with patch.object(UpdateManager, "_download_file", fake_download):
            with patch("antigravity_provider.updater.update_manager.stop_running_hub", return_value=True):
                with patch.object(UpdateManager, "schedule_restart", return_value=(True, "перезапуск запущен")):
                    ok, msg = mgr.install_latest_update(check_result=check_result)

    assert ok is True
    rec = get_last_applied_update()
    assert rec is not None
    assert rec["new_version"] == "0.1.4"
    assert rec["new_commit"] == "deadbeefdeadbeef"
    assert rec["prev_commit"] != rec["new_commit"], (
        "«Было» снимается до установки, иначе прежняя сборка совпадёт с новой"
    )
    assert rec["acknowledged"] is False

    UpdateManager._set_progress(status="idle", message="Готов к обновлению")


# ── TEST 11: P0-2 полоса не изображает процент при неизвестном размере ──
@pytest.mark.unit
def test_p0_2_app_js_indeterminate_bar_when_size_unknown():
    """При неизвестном размере полоса бежит, а не заполняется целиком.

    Текст рядом был честным («Н/Д: сервер не сообщил размер»), а полоса при этом
    рисовалась на всю ширину: `downloaded > 0 ? '100%' : '20%'`. Полная полоса
    читается как «готово» — тот же выдуманный процент, только нарисованный.
    """
    src = APP_JS_PATH.read_text(encoding="utf-8")

    assert "downloaded > 0 ? '100%' : '20%'" not in src, (
        "Полоса не должна заполняться на всю ширину при неизвестном размере"
    )
    assert "Н/Д: сервер не сообщил размер" in src
    assert "INDETERMINATE_ACTIVE_STATUSES" in src, "нужен список этапов с неопределённой полосой"
    assert "@keyframes indeterminate-bar" in src, "нужна анимация бегущего отрезка"
    assert "indeterminate-bar-style" in src, "стиль вставляется один раз по id"


# ── TEST 12: P0-2 интерфейс не принимает отказ в отмене за отмену ──
@pytest.mark.unit
def test_p0_2_app_js_handles_refused_cancel():
    """Отказ в отмене возвращает опрос хода, а не оставляет окно замершим."""
    src = APP_JS_PATH.read_text(encoding="utf-8")

    assert "cancel_accepted" in src, "app.js обязан различать принятую и отклонённую отмену"
    idx = src.index("async function cancelUpdateProcess()")
    tail = src[idx:idx + 1200]
    assert "setInterval(pollUpdateProgress" in tail, (
        "после отклонённой отмены опрос хода загрузки должен возобновляться"
    )


# ── HUB-1: распаковка обновления не выпускает записи за пределы каталога ──


@pytest.mark.unit
def test_update_package_cannot_write_outside_target(tmp_path):
    """Ни одна запись архива не должна оказаться вне каталога установки.

    Измерено на CPython: extractall сам отбрасывает "..", ведущие разделители
    и буквы дисков, а запись-ссылку кладёт обычным файлом — побега добиться не
    удалось, вопреки формулировке аудита. Но это свойство реализации, а не
    обещание формата, и распаковка идёт в корень установки. Тест закрепляет
    границу как собственный инвариант.
    """
    import stat as _stat
    import zipfile as _zipfile
    from antigravity_provider.updater.update_manager import _extract_within

    dest = tmp_path / "dest"
    dest.mkdir()
    outside = tmp_path / "outside.txt"

    hostile = [
        ("выход через ..", "../outside.txt"),
        ("абсолютный путь", "/etc/passwd"),
        ("путь с буквой диска", "C:/Windows/x.txt"),
    ]
    for index, (label, arcname) in enumerate(hostile):
        archive = tmp_path / f"hostile_{index}.zip"
        with _zipfile.ZipFile(archive, "w") as zf:
            zf.writestr(arcname, "побег")
        with _zipfile.ZipFile(archive) as zf:
            with pytest.raises(ValueError):
                _extract_within(zf, dest)
        assert not outside.exists(), f"{label}: запись оказалась вне каталога установки"

    # Символическая ссылка — тоже отказ, а не молчаливая распаковка файлом.
    link_zip = tmp_path / "link.zip"
    with _zipfile.ZipFile(link_zip, "w") as zf:
        info = _zipfile.ZipInfo("link")
        info.external_attr = (_stat.S_IFLNK | 0o777) << 16
        zf.writestr(info, "/etc/passwd")
    with _zipfile.ZipFile(link_zip) as zf:
        with pytest.raises(ValueError):
            _extract_within(zf, dest)

    # Обычный пакет распаковывается как прежде.
    good = tmp_path / "good.zip"
    with _zipfile.ZipFile(good, "w") as zf:
        zf.writestr("src/module.py", "x = 1\n")
        zf.writestr("assets/logo.txt", "logo")
    with _zipfile.ZipFile(good) as zf:
        _extract_within(zf, dest)
    assert (dest / "src" / "module.py").read_text(encoding="utf-8") == "x = 1\n"
    assert (dest / "assets" / "logo.txt").is_file()
