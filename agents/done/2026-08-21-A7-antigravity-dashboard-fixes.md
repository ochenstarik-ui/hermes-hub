# Отчёт: Задание A7 — исправление двух дефектов в данных дашборда

Дата: 2026-08-21

## Идентификаторы и границы

- **START_HEAD (BASE_SHA)**: `09d5e5d1ae62c16f2c3d52dd2b2e88a09f3e4987`
- **Ветка**: `antigravity/dashboard-fixes`
- **origin/main**: `09d5e5d1ae62c16f2c3d52dd2b2e88a09f3e4987`
- **Граница зоны Codex**: ни один файл в `src/antigravity_provider/router/ui/**`, `hermes_hub_app.py`, `tests/test_ui_*.py` **НЕ изменялся** (`git diff --name-only` по этим путям пуст).
- **Тег `v0.1.1`**: **НЕ создавался** (в репозитории `hermes-hub`).

---

## 1. Исправление `active_calls` и унификация `LeaseManager` (P0-1)

- **Причина дефекта**: `RouterEngine` по умолчанию создавал собственный экземпляр `LeaseManager()`, в то время как `state_store.py` и `health_tracker.py` опрашивали синглтон `LeaseManager.get()`.
- **Исправление**:
  - `RouterEngine.__init__` теперь инициализирует `self.leases = leases if leases is not None else LeaseManager.get()`.
  - `state_store.py` считывает активные лизы через `get_router_engine().leases` (с запасным обращением к `LeaseManager.get()`), обеспечивая единый источник истины.
  - `ProfileHealthRecord.active_leases` в `health_tracker.py` заполняется реальным числом занятых лизов для каждого профиля.
  - В `cli_commands.py:print_router_status` добавлен вывод активных лизов в столбце `STATE` (`healthy (1 active)`), если `precord.active_leases > 0`.
  - **Тест**: добавлен тест `test_active_calls_and_hub_snapshot_integration`, захватывающий лиз через путь роутера (`engine.leases.acquire("ag-w1")`) и проверяющий, что `HubSnapshot.metrics["active_calls_total"] == 1`, `metrics["active_calls_by_profile"]["ag-w1"] == 1` и `snapshot.get_profile("ag-w1").active_leases == 1`.

---

## 2. Устранение холодного 0% CPU на первом замере (P0-2)

- **Причина дефекта**: `psutil.cpu_percent(interval=None)` без предварительного замера по спецификации `psutil` возвращает `0.0%`.
- **Исправление**:
  - При первом холодном вызове `HostMetricsService.collect()` выполняется прогрев счетчика через короткий неблокирующий интервал `psutil.cpu_percent(interval=0.05)`, после чего последующие вызовы считывают накопленный дельта-дифференциал через `interval=None`.
  - Также счетчик `psutil` предварительно калибруется при импорте модуля `host_metrics.py`.
  - **Тест**: добавлен юнит-тест `test_host_metrics_cpu_warmup_avoids_cold_zero`, проверяющий прогрев на холодном старте.

---

## 3. Расчет реальной скорости сети и семантика счетчиков (P1-4)

- В `HostMetricsService` и `HostMetricsSnapshot` реализован расчет мгновенной скорости сети в Мбит/с на основе дельты времени и переданных байт между выборками:
  - `net_speed_mbps`: общая скорость сети (Mbps = (delta_sent + delta_recv) * 8 / (dt * 1_000_000));
  - `net_sent_mbps` / `net_recv_mbps`: скорость отдачи / приема (Mbps);
  - `net_bytes_sent` / `net_bytes_recv`: накопительные счетчики с момента загрузки машины (с явной семантикой в контракте).
- **Тест**: добавлен юнит-тест `test_host_metrics_network_live_speed`, проверяющий расчет Mbps между замерами.

---

## 4. Обновление контракта и статус YAML (P1-3, P1-5)

- В `docs/UI_STATE_CONTRACT.md`:
  - В разделе 8.2 детально описаны поля сетевой скорости (`net_speed_mbps`, `net_sent_mbps`, `net_recv_mbps`) и накопительных байт (`net_bytes_sent`, `net_bytes_recv`).
  - Добавлено примечание о warm-up поведении CPU.
  - Добавлен раздел 9 **Configuration Preservation Status** с честной фиксацией статуса:
    - Заголовочные комментарии и пустые строки до первого ключа сохраняются (`supported`);
    - Внутренние комментарии внутри словарей нормализуются стандартным `safe_dump` (статус **«частично» / «partially supported»**).

---

## 5. Результаты проверок

- **Headless pytest** (Python 3.8):
  `pytest -v` → **195 passed, 26 skipped, 3 deselected in 11.79s**
- **Full pytest** (Python 3.12 с `customtkinter`, `pillow`, `psutil`):
  `& "C:\Users\trush\AppData\Local\Programs\Python\Python312\python.exe" -m pytest -v` → **195 passed, 26 skipped, 3 deselected in 11.02s**
- **Ruff linter**:
  `ruff check .` → **All checks passed!**
- **Release Gate**:
  `python scripts/release_gate.py` → **7/7 PASSED** (`[RELEASE GATE: PASSED] All criteria verified. Ready for Candidate v0.1.1`)
- **Live Update Feed**:
  `[MANIFEST_LIVE=True, PACKAGE_LIVE=True, PACKAGE_HASH_VERIFIED=True]` (sha256 `b5bbdea2a7a2157a26389266aab07ab3602bb00b4612065c48defec9d6fe909c`)
- **UI Zone Isolation**: `0 files modified in UI area`
