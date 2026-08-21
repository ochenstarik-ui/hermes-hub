# Отчёт: Задание A6 — данные для нового дашборда

Дата: 2026-08-21

## Идентификаторы и границы

- **START_HEAD (BASE_SHA)**: `2407d47781079d34551aa74cb97e59c1181284d7`
- **Ветка**: `antigravity/dashboard-data`
- **origin/main**: `2407d47781079d34551aa74cb97e59c1181284d7`
- **Граница зоны Codex**: ни один файл в `src/antigravity_provider/router/ui/**`, `hermes_hub_app.py`, `tests/test_ui_*.py` **НЕ изменялся** (`git diff --name-only` по этим путям пуст).
- **Тег `v0.1.1`**: **НЕ создавался** (в репозитории `hermes-hub`).

---

## 1. Вывод телеметрии в снапшот (P0-1)

В `HubSnapshot.metrics["telemetry"]` выставлен полный структурированный срез агрегатов за окно (по умолчанию 24h / 86400s), генерируемый `TelemetryService.get().get_breakdown(...)`:
- `global`: общие агрегаты (латентность `latency_p50_ms`, `latency_p95_ms`, `latency_max_ms`, токены `total_prompt_tokens`, `total_completion_tokens`, `total_tokens`, `error_rate`, `total_calls`, `successful_calls`, `failed_calls`, `total_cost_usd`, `source: "own_measurement"`);
- `by_provider`: словарь `{provider_name: TelemetryAggregates}` с метриками по каждому провайдеру (`call_share`, `latency_p50_ms`, `total_calls` для правой панели «Статус в реальном времени»);
- `by_role`: словарь `{role_name: TelemetryAggregates}` с метриками по каждой роли (`total_calls`, `latency_p50_ms`, `total_tokens` для счётчиков на схеме маршрутизации).
- При отсутствии вызовов в окне возвращается `has_data=False`, а все числовые поля строго равны `None` (без выдуманных нулей).

---

## 2. Доля вызовов по провайдеру (P0-2)

- В `TelemetryAggregates` и выборку `get_aggregates(...)` / `get_breakdown(...)` добавлено поле `call_share: Optional[float]`:
  - Рассчитывается как отношение вызовов выбранного фильтра к общему числу вызовов за окно: `call_share = round(filtered_calls / total_window_calls, 4)` (например, 0.45, 0.35, 0.20);
  - Если за окно не было ни одного вызова (`total_window_calls == 0`), `call_share` строго равен `None` (не «0%» и не равномерное распределение);
  - Проверено тестом `test_provider_call_share_calculation` с точным распределением 45/35/20.

---

## 3. Показатели хоста через `psutil` (P1-3)

- Создан модуль `src/antigravity_provider/router/host_metrics.py` со службой `HostMetricsService`:
  - Собирает аппаратные показатели хост-машины без блокировки: `cpu_percent` (%), `memory_percent` (%), `memory_used_mb`, `memory_total_mb`, `disk_percent` (%), `disk_used_gb`, `disk_total_gb`, `net_bytes_sent`, `net_bytes_recv`;
  - Источник данных: `source: "host_measurement"`;
  - Интегрирован в общий цикл построения снапшота `HubStateStore._build_snapshot()` в `HubSnapshot.metrics["host"]`;
  - При отсутствии `psutil` или ошибке сбора — возвращает `has_data=False` и `None` для всех показателей;
  - Проверено тестом `test_host_metrics_service_psutil`.

---

## 4. Активные вызовы и лизы (P1-4)

- В `LeaseManager` (`session_affinity.py`) добавлены методы агрегации:
  - `total_active_count() -> int` (общее число занятых лизов по всем профилям);
  - `all_active_counts() -> dict[str, int]` (активные лизы по каждому профилю).
- `LeaseManager` переведен на потокобезопасный синглтон `LeaseManager.get()`, используемый совместно в `RouterEngine`, `HealthTracker`, `UnifiedHealthService` и `HubStateStore`.
- В `HubSnapshot.metrics` выставлены:
  - `"active_calls_total"`: общее число активных вызовов;
  - `"active_calls_by_profile"`: распределение активных лизов по профилям.
- В `ProfileViewModel` и `ProfileHealthRecord` поле `active_leases` теперь отражает реальное число активных лизов из `LeaseManager`.
- Очереди по приоритетам и окна обслуживания **не изобретались**.

---

## 5. Обновление контракта и статус долга (P1-5, P2-6)

- В `docs/UI_STATE_CONTRACT.md`:
  - Gap 13 переведен в **Closed (Self-Measured)**: показатели хоста (`source: "host_measurement"`).
  - Заведен **Gap 14** в «Active Limitations»: в нем зафиксированы истинно недоступные показатели — серверный RPS провайдера, внешний SLA uptime %, подсистемы очередей приоритетов и окна обслуживания (отсутствуют в архитектуре Hermes Hub).
  - Раздел 8 расширен подразделами 8.1 (Call Telemetry & Routing Distribution), 8.2 (Host System Metrics), 8.3 (Active Calls Telemetry).
- **Статус долга по комментариям YAML (P2-6)**:
  - Статус зафиксирован как **«частично»**: сохраняются все заголовочные комментарии и пустые строки (`existing_comments`) перед первым ключом. Внутренние inline-комментарии внутри словарей нормализуются стандартным `safe_dump`.

---

## 6. Результаты проверок

- **Headless pytest** (Python 3.8):
  `pytest -v` → **189 passed, 22 skipped, 3 deselected in 10.39s**
- **Full pytest** (Python 3.12 с `customtkinter`, `pillow`, `psutil`):
  `& "C:\Users\trush\AppData\Local\Programs\Python\Python312\python.exe" -m pytest -v` → **189 passed, 22 skipped, 3 deselected in 27.21s**
- **Ruff linter**:
  `ruff check .` → **All checks passed!**
- **Release Gate**:
  `python scripts/release_gate.py` → **7/7 PASSED** (`[RELEASE GATE: PASSED] All criteria verified. Ready for Candidate v0.1.1`)
- **Live Update Feed**:
  `[MANIFEST_LIVE=True, PACKAGE_LIVE=True, PACKAGE_HASH_VERIFIED=True]` (sha256 `b5bbdea2a7a2157a26389266aab07ab3602bb00b4612065c48defec9d6fe909c`)
- **UI Zone Isolation**: `0 files modified in UI area`
