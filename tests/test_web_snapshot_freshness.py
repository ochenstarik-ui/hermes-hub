"""Веб-сервер обязан прогревать квоты и пересобирать снапшот.

Дефект, ради которого написан файл: /api/snapshot отдавал квоты с
source="baseline" и нулём измеренных корзин ВСЕГДА. Две независимые
причины, и лечение только одной из них ничего не давало:

1. state_store наполняет квоты через quota_service.get_snapshot, который
   читает кэш и при промахе отдаёт пустую заглушку, живой опрос не
   запуская. Кэш никто не грел: в десктопе это делал
   _refresh_quotas_on_startup, в вебе аналога не было.

2. HubStateStore.get_snapshot() возвращает кэшированный снапшот и
   пересобирает его только при первом вызове. Даже после прогрева квот
   ответ оставался прежним.
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")


def test_server_declares_startup_refresh():
    """Фоновое обновление должно быть подключено к старту приложения."""
    from antigravity_provider.router.web import server

    assert hasattr(server, "_background_refresh_loop"), (
        "нет фонового цикла: квоты останутся пустыми навсегда"
    )

    handlers = [
        getattr(h, "__name__", "") for h in server.app.router.on_startup
    ]
    assert any("refresh" in name for name in handlers), (
        f"обработчик старта не зарегистрирован, найдено: {handlers}"
    )


def test_refresh_loop_warms_quota_cache_then_rebuilds_snapshot(monkeypatch):
    """Прогрев квот обязан предшествовать пересбору снапшота.

    Порядок важен: снапшот, собранный до прогрева, зафиксирует пустые
    корзины, и следующий пересбор случится только через интервал.
    """
    from antigravity_provider.router.web import server

    order: list[str] = []

    class _Quota:
        @staticmethod
        def get():
            return _Quota()

        def fetch_all_configured(self, force: bool = False):
            order.append("quota_fetch")
            return {}

        def start_background_scheduler(self):
            return None

    class _Store:
        @staticmethod
        def get():
            return _Store()

        def refresh(self, force_scan: bool = True):
            order.append("snapshot_refresh")
            raise KeyboardInterrupt  # прерываем бесконечный цикл

    import antigravity_provider.router.quota_collector as qc

    monkeypatch.setattr(qc, "AccountQuotaService", _Quota)
    monkeypatch.setattr(server, "HubStateStore", _Store)

    with pytest.raises(KeyboardInterrupt):
        server._background_refresh_loop()

    assert order == ["quota_fetch", "snapshot_refresh"], (
        f"нарушен порядок прогрева и пересбора: {order}"
    )
