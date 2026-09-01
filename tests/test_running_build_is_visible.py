"""Владелец должен видеть, какой код сейчас работает.

На Linux строка сборки в боковой панели оставалась пустой: она заполнялась из
панели обновлений, а та подтягивается только при открытии. Понять, дошло ли
обновление, было нельзя.

Глубже: поле commit читается из манифеста на диске при каждом запросе, поэтому
переживший обновление процесс рапортует свежий номер при старом поведении.
Отличить сборки по нему невозможно — это уже подводило при разборе окон
консоли. running_commit снимается один раз, при старте процесса, и отвечает на
настоящий вопрос: какой код в памяти.
"""
from __future__ import annotations

import time

from fastapi.testclient import TestClient

from antigravity_provider.router.web.server import (
    PROCESS_STARTED_AT,
    RUNNING_COMMIT,
    app,
)


def test_health_reports_the_running_build():
    payload = TestClient(app).get("/api/health").json()

    assert payload["running_commit"] == RUNNING_COMMIT
    assert payload["started_at"] == PROCESS_STARTED_AT


def test_snapshot_reports_the_running_build():
    snap = TestClient(app).get("/api/snapshot").json()

    assert snap["running_commit"] == RUNNING_COMMIT
    assert snap["started_at"] == PROCESS_STARTED_AT


def test_running_commit_is_taken_once_and_does_not_follow_the_disk(monkeypatch):
    """Подмена манифеста на диске не должна менять номер работающей сборки."""
    from antigravity_provider.router.web import server

    monkeypatch.setattr(server, "get_installed_commit", lambda: "deadbee")
    payload = TestClient(app).get("/api/health").json()

    assert payload["commit"] == "deadbee", "поле commit отражает диск"
    assert payload["running_commit"] == RUNNING_COMMIT, (
        "а running_commit — то, что реально запущено"
    )
    assert payload["running_commit"] != "deadbee"


def test_start_time_is_plausible():
    assert PROCESS_STARTED_AT > 0
    assert PROCESS_STARTED_AT <= time.time()
