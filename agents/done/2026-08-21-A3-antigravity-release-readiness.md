# Отчёт: Задание A3 — релиз, честность контракта, оставшиеся долги

Дата: 2026-08-21

## Идентификаторы и границы

- **START_HEAD (BASE_SHA)**: `9ffc815ed59f7fd364e176ffef20bf29d545bc46`
- **Ветка**: `antigravity/release-readiness`
- **origin/main**: `9ffc815ed59f7fd364e176ffef20bf29d545bc46`
- **Границы работ**: ни один файл зоны Codex (`src/antigravity_provider/router/ui/**`, `hermes_hub_app.py`, `tests/test_ui_*.py`) **НЕ изменялся** (`git diff --name-only` по этим путям пуст).
- **Тег `v0.1.1`**: **НЕ создавался** (в репозитории `hermes-hub`).

---

## 1. Честность контракта (P0-1)

В `docs/UI_STATE_CONTRACT.md` (версия 1.2) одновременно представлены **и** закрытые пробелы, **и** активные ограничения бэкенда:
- **Раздел 6 «Closed Gaps & Audit Status»**:
  - Gaps 1 & 2: изоляция multi-bucket квот (`claude`/`gemini`) и честный парсинг reset-таймстампов при 429 (`runtime_event`).
  - Gap 3: публичное поле `seq` в `HubSnapshot`.
  - Gap 5: политика `is_stale` (возвращает `True` для bootstrap-снимка и при превышении TTL возраста > 300 секунд).
  - Gap 6: происхождение тарифа (`plan_source`: `"provider_api"`, `"jwt_claim"`, `"provider_auth"`, `"inferred"`, `"unknown"`).
  - Gap 7: `AgentViewModel` расширен (`session_id`, `active_quota_status`, `active_quota_label`).
  - Gap 8: `PipelineNode` расширен (`account_identity`, `quota_status`, `failover_reason`).
  - Gap 9: канонические публикаторы для всех 11 объявленных событий.
  - Gaps 10 & 11: защита от гонок в планировщике и отбрасывание устаревших ответов (`seq < _latest_applied_seq`).
- **Раздел 7 «Active Limitations & Backend Constraints»**:
  - **Gap 4 (Shallow Immutability)**: `HubSnapshot` защищён `frozen=True` на уровне полей, но вложенные коллекции остаются мутабельными структурами Python. UI обязан обращаться со снимком как строго read-only.
  - **Gap 12 (Missing Metrics)**: задержки (latency), RPS, процент ошибок, финансовые затраты и SLA внешних провайдеров **не вычисляются бэкендом**. UI обязан показывать `Н/Д` либо скрывать эти карточки.

---

## 2. Релизная инфраструктура и манифест (P0-2)

- Собран дистрибутив `dist/hermes-hub-0.1.1.zip` и детерминированно обновлён `dist/checksums.txt`.
- Артефакты `hermes-hub-0.1.1.zip` и `HermesHubSetup.exe` загружены в GitHub Releases репозитория дистрибуции `ochenstarik-ui/hermes-hub-releases`.
- Манифест `update_manifest.json` в `ochenstarik-ui/hermes-hub-releases` обновлён с точным хешем sha256 (`29cfe190184934f2d26c981661652c40ce4c130043db679517e38014e287bb8c`).
- Проверка:
  - `curl -s https://raw.githubusercontent.com/ochenstarik-ui/hermes-hub-releases/main/update_manifest.json` → sha256 совпадает;
  - `curl -ILs https://github.com/ochenstarik-ui/hermes-hub-releases/releases/download/v0.1.1/hermes-hub-0.1.1.zip` → **HTTP 200 OK** (Redirect 302 → 200 OK).

---

## 3. Долги и фиксация архитектурных решений (P1-3)

1. **Комментарии `router_profiles.yaml`**: `save_router_config()` читает и сохраняет заголовочные комментарии и пустые строки перед первым ключом. Inline-комментарии внутри структур пересобираются каноническим YAML-дампером.
2. **`HKCU` в тестах установщика**: тесты установщика изолированы маркером `@pytest.mark.installer`, который исключён из стандартного прогона (`addopts = "-m 'not live and not network and not installer'"` в `pyproject.toml`).
3. **Сериализация Antigravity**: глобальный мьютекс `_AGY_INVOCATION_LOCK` обоснован и сохранён — он предотвращает гонки при переключении общего ключа `gemini:antigravity` в Windows Credential Manager между параллельными профилями.
4. **Зависимости `fastapi`/`uvicorn`**: вынесены в `[project.optional-dependencies] legacy` в `pyproject.toml` и не входят в основной список `dependencies`.

---

## 4. Подготовка к ручной проверке (P2-4)

1. **Диагностическая команда**:
   - `python -m antigravity_provider.router.cli_commands diag`
   - Печатает сводную таблицу по всем профилям: провайдер, маскированная идентичность, статус авторизации, статус квоты и источник данных.
2. **Журналирование переключений маршрутов**:
   - `RouterEngine.route_request()` при failover логирует предупреждения в логгер и записывает события в `EventLogService` (категория `routing`) с указанием роли, старого и нового профиля, а также причины переключения (`failover_reason`).

---

## 5. Проверки

- **Headless pytest** (3.8/default): `170 passed, 21 skipped, 3 deselected in 9.24s`
- **Full pytest** (Python 3.12 с `customtkinter`, `pillow`, `psutil`): `170 passed, 21 skipped, 3 deselected in 11.51s`
- **Ruff linter**: `All checks passed!`
- **Release Gate**: `7/7 PASSED` (`[RELEASE GATE: PASSED] All criteria verified. Ready for Candidate v0.1.1`)
- **UI Zone Isolation**: `0 files modified in UI area`
