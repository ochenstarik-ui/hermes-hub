# Отчёт: Задание A5 — настоящая телеметрия вызовов и закрытие долгов

Дата: 2026-08-21

## Идентификаторы и границы

- **START_HEAD (BASE_SHA)**: `f5d002c918c5e6383ee302636d1b28daae820ec4`
- **Ветка**: `antigravity/telemetry`
- **origin/main**: `f5d002c918c5e6383ee302636d1b28daae820ec4`
- **Граница зоны Codex**: ни один файл в `src/antigravity_provider/router/ui/**`, `hermes_hub_app.py`, `tests/test_ui_*.py` **НЕ изменялся** (`git diff --name-only` по этим путям пуст).
- **Тег `v0.1.1`**: **НЕ создавался** (в репозитории `hermes-hub`).

---

## 1. Сохранение телеметрии собственных вызовов (P0-1)

Реализован сервис `TelemetryService` в `src/antigravity_provider/router/telemetry_service.py`:
- По одной записи `TelemetryRecord` на каждую попытку вызова роутера:
  - `timestamp` (float epoch) и `iso_time` (UTC ISO-8601);
  - `role`, `profile_id`, `provider`, `model`;
  - `outcome` (`"success"`, `"failover"`, `"error"`, `"quota_exhausted"`, `"rate_limited"`, `"auth_required"`);
  - `latency_seconds` (замеренная длительность выполнения);
  - `prompt_tokens`, `completion_tokens`, `total_tokens` (извлекаются **строго из метаданных `usage`**, возвращенных провайдером; если провайдер не вернул `usage`, поля остаются `None` без эвристических догадок);
  - `cost_usd` (рассчитывается только при наличии пользовательского прайса);
  - `failover_count`, `error_category`;
  - `source`: `"own_measurement"`.
- Ограниченный размер и надежность:
  - Кольцевой буфер в памяти (`maxlen=10000`);
  - Ротация файла лога `telemetry.jsonl` при достижении 5 МБ с сохранением до 3 архивов (`telemetry.jsonl.1`..);
  - Никаких секретов, токенов, авторизационных заголовков или содержимого запросов/ответов;
  - Сохранение истории между перезапусками (чтение последних записей с диска при инициализации).

---

## 2. Эмпирические агрегаты (P0-2)

- В `TelemetryService.get_aggregates(...)` реализован расчет метрик за произвольное окно времени по провайдеру, профилю, модели и роли:
  - Латентность: P50 (медиана), P95, Max, общее число вызовов (`total_calls`);
  - Токены: `total_prompt_tokens`, `total_completion_tokens`, `total_tokens` (суммируются только сообщенные провайдером токены);
  - Переключения: `failovers_count`, `failover_reasons` (гистограмма причин переключения);
  - Доля ошибок: `error_rate = failed_calls / total_calls`;
  - Источник данных: `source = "own_measurement"`.
- **Честное поведение при отсутствии вызовов**: если вызовов в окне не было, возвращаются `None` для латентностей, токенов и доли ошибок, а флаг `has_data=False` (никаких фальшивых нулей).

---

## 3. Стоимость только при наличии прайса (P1-3)

- В `RouterConfig` и схему `router_profiles.yaml` добавлена опциональная секция `pricing`:
  ```yaml
  pricing:
    gemini-2.5-pro:
      input_cost_per_m: 1.25
      output_cost_per_m: 5.00
    gpt-4o:
      input_cost_per_m: 2.50
      output_cost_per_m: 10.00
  ```
- Если прайс для модели задан — рассчитывается реальная стоимость `cost_usd = (prompt_tokens * input_rate + completion_tokens * output_rate) / 1_000_000`.
- Если прайс не задан — `cost_usd = None`. Цены в код не зашиваются. Пример прайса добавлен в `config/router_profiles.example.yaml`.

---

## 4. Обновление контракта (P1-4)

- В `docs/UI_STATE_CONTRACT.md`:
  - Gap 12 переведен в **Closed (Self-Measured)**: собственная эмпирическая телеметрия роутера (`source: "own_measurement"`).
  - Описан раздел **8. Telemetry & Empirical Metrics Contract** со спецификацией полей и поведения при отсутствии данных.
  - В **Active Limitations (Gap 13)** оставлены истинно неизмеримые внешние показатели (RPS серверов провайдера, SLA uptime %, CPU/RAM/Disk/Network хоста), для которых UI обязан отображать `Н/Д` либо опускать карточки.

---

## 5. Закрытие трёх долгов (P1-5)

1. **`Registry.CurrentUser` в `HermesHubSetup.cs` (Закрыт)**:
   - В `HermesHubSetup.cs` регистрация в HKCU изолирована проверкой переменной окружения `HERMES_HUB_NO_REGISTRY == "1"`.
   - В боевом установщике запись в `HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall` необходима для корректного отображения в панели «Установка и удаление программ» Windows для пользователя без прав администратора. В тестовых прогонах реестр изолирован.
2. **`fastapi` / `uvicorn` в обязательных зависимостях (Закрыт)**:
   - `fastapi` и `uvicorn` полностью отсутствуют в секции `dependencies` файла `pyproject.toml` и вынесены в `[project.optional-dependencies] legacy`.
3. **Комментарии в `router_profiles.yaml` (Закрыт)**:
   - Функция `save_router_config` в `router_config.py` считывает существующие заголовочные комментарии и пустые строки (`existing_comments`) перед первым ключом и сохраняет их verbatim. Проверено юнит-тестом `test_yaml_comments_preservation_and_debts_closure`.

---

## 6. Результаты проверок

- **Headless pytest** (Python 3.8):
  `pytest -v` → **185 passed, 22 skipped, 3 deselected in 9.76s**
- **Full pytest** (Python 3.12 с `customtkinter`, `pillow`, `psutil`):
  `py -3.12 -m pytest -v` → **185 passed, 22 skipped, 3 deselected in 13.50s**
- **Ruff linter**:
  `ruff check .` → **All checks passed!**
- **Release Gate**:
  `python scripts/release_gate.py` → **7/7 PASSED** (`[RELEASE GATE: PASSED] All criteria verified. Ready for Candidate v0.1.1`)
- **Live Update Feed**:
  `[MANIFEST_LIVE=True, PACKAGE_LIVE=True, PACKAGE_HASH_VERIFIED=True]` (sha256 `b5bbdea2a7a2157a26389266aab07ab3602bb00b4612065c48defec9d6fe909c`)
- **UI Zone Isolation**: `0 files modified in UI area`
