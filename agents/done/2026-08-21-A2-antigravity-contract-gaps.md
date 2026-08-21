# Отчёт: Задание A2 — закрытие пробелов контракта и релизная инфраструктура

Дата: 2026-08-21

## Идентификаторы и границы

- Base SHA: `e8a404be035fa04b5f76e3e572c6539fba0e83e4` (актуальный `origin/main` на старте).
- Ветка: `antigravity/contract-gaps`.
- Контракт: `docs/UI_STATE_CONTRACT.md` обновлён до версии **1.1** первым шагом.
- Тег `v0.1.1` **НЕ создавался**.
- Файлы UI (`src/antigravity_provider/router/ui/**`, `hermes_hub_app.py`, `tests/test_ui_*.py`) **НЕ изменялись** (`git diff --name-only` по этим путям полностью пуст).

## Реализовано и закрыто

### 1. Канонические публикаторы событий (Gap 9, P0-1)
- Для каждого объявленного события реализован канонический метод/вызов в `HubStateStore`:
  - `EVENT_ACCOUNT_UPDATED`: `apply_delta_account_updated` публикует payload `{profile_id, profile, generation, seq}`.
  - `EVENT_ACCOUNT_ADDED`: `apply_delta_account_added` публикует payload `{provider, profile_id, profile, generation, seq}`.
  - `EVENT_ACCOUNT_REMOVED`: `apply_delta_account_removed` публикует payload `{provider, profile_id, generation, seq}`.
  - `EVENT_ACCOUNT_AUTH_CHANGED`: `publish_auth_changed` публикует payload `{provider, profile_id, auth_state, profile, generation, seq}`.
  - `EVENT_QUOTA_UPDATED`: `apply_delta_quota_updated` публикует payload `{provider, profile_id, snapshot, quota_snapshot, generation, seq}`.
  - `EVENT_ROUTING_UPDATED`: `apply_delta_route_changed` публикует payload `{role_id, active_profile_id, pipeline, failover_reason, generation, seq}`.
  - `EVENT_AGENT_UPDATED`: `apply_delta_route_changed` / `apply_delta_agent_updated` публикует payload `{role_id, agent, generation, seq}`.
  - `EVENT_SYSTEM_READINESS_CHANGED`: `refresh` публикует payload `readiness`.
  - `EVENT_REFRESH_STARTED` / `EVENT_REFRESH_COMPLETED` / `EVENT_REFRESH_FAILED`: планировщик и state store публикуют с монотонными `seq` и `generation`.
- Неиспользуемые мёртвые константы (`EVENT_QUOTA_STALE`, `EVENT_PROVIDER_HEALTH_CHANGED`, `EVENT_ROUTING_SLOT_UPDATED`) удалены из `event_bus.py`.

### 2. Происхождение тарифа в `ProfileViewModel` (Gap 6, P0-2)
- В `ProfileViewModel` добавлено поле `plan_source: str = "unknown"` (`"provider_api"`, `"jwt_claim"`, `"provider_auth"`, `"inferred"`, `"unknown"`).
- `UnifiedHealthService` заполняет `plan_source` из `ident.plan.source`. UI может достоверно отображать `PlanBadge`, проверяя `plan_source != "unknown"`.

### 3. Расширение `AgentViewModel` и `PipelineNode` (Gaps 7, 8, P0-3)
- `AgentViewModel`:
  - `session_id: Optional[str] = None`
  - `active_quota_status: str = "healthy"` (`"healthy"`, `"warning"`, `"exhausted"`)
  - `active_quota_label: str = ""` (например `"Осталось 85%"` или `"Исчерпана (429)"`)
- `PipelineNode`:
  - `account_identity: str = ""`
  - `quota_status: str = "healthy"`
  - `failover_reason: Optional[str] = None` (содержит реальную причину переключения: `"Исчерпана квота (429)"`, `"Требуется авторизация"` и т.д., либо `None` для активного узла / резерва).

### 4. Измерение и изоляция квот (Gaps 1, 2, P1-4)
- Структурное разделение model-family buckets (`claude`, `gemini`, `gpt`, `grok`, `opencode`) с честными неизвестными значениями (`None`, `is_estimated=True`).
- Runtime 429 парсит ответ провайдера, сбрасывает квоту до 0% и выставляет `source="runtime_event"`, `is_estimated=False`.

### 5. Свежесть данных и защита от устаревших ответов (Gaps 3, 10, 11, P1-5)
- `HubSnapshot` содержит публичное поле `seq: int`.
- Планировщик завершает сбор квот до перестроения снимка.
- `HubStateStore.refresh` проверяет `request_seq < self._latest_applied_seq` и гарантированно отбрасывает устаревшие ответы без повреждения монотонности снимков.
- Доказано юнит- и интеграционными тестами с асинхронными задержками.

### 6. Релизная инфраструктура (P1-6)
- Пакет дистрибутива собран детерминированно: `dist/hermes-hub-0.1.1.zip`.
- Хеши обновлены в `dist/checksums.txt`.
- Тег `v0.1.1` **НЕ создавался**.

## Проверки

1. **Pytest (headless)**: `167 passed, 22 skipped, 3 deselected in 15.87s`.
2. **Ruff linter**: `All checks passed!`.
3. **Release Gate**: `7/7 PASSED`.
4. **UI Zone Isolation**: `0 files modified in UI area`.
