# Hermes Hub — подключение UI-контракта v1.1

Дата: 2026-08-21

Ветка: `codex/contract-v11`

BASE_SHA: `9ffc815ed59f7fd364e176ffef20bf29d545bc46`

FINAL_SHA: `git rev-parse codex/contract-v11` в момент handoff. Точный SHA указан в итоговом сообщении, поскольку commit не может содержать собственный SHA.

## Изменённые файлы

- `src/antigravity_provider/router/hermes_hub_app.py`
- `src/antigravity_provider/router/ui/components.py`
- `src/antigravity_provider/router/ui/views/dashboard_view.py`
- `src/antigravity_provider/router/ui/views/routing_view.py`
- `src/antigravity_provider/router/ui/views/team_view.py`
- `tests/test_ui_contract_v11.py`
- `CODEX_CONTRACT_V11_REPORT.md`

Файлы backend/state/adapters, installer, scripts, config, legacy и чужие тесты не изменялись.

## Что подключено

- `ProfileViewModel.plan_code` и `plan_source`: подтверждённый провайдером тариф показан акцентным `PlanBadge`; `inferred` явно помечен как «выведено»; `unknown` скрыт.
- `QuotaSnapshot.unavailable_reason` и совместимый fallback на `QuotaBucket.unavailable_reason`: причина отсутствия данных показана под корзиной.
- `QuotaBar` и `QuotaBucketWidget`: `None` показан как «Н/Д» нейтральным цветом, реальный `0%` — как исчерпанная квота красным цветом.
- `AgentViewModel.active_quota_status`, `active_quota_label` и `session_id`: активная квота и сессия видны в карточке агента.
- `PipelineNode.quota_status`, `failover_reason` и `account_identity`: состояние квоты и реальная причина показаны у узла, с которого ушёл трафик.
- `HubSnapshot.seq` и `is_stale`: номер snapshot и предупреждение об устаревших данных показаны на Dashboard и в общей строке состояния.
- Устранено обращение Dashboard/маршрутизации к отсутствующему `PipelineNode.provider_display_name`; используется контрактное поле `provider`.

## Проверки

### Без UI-зависимостей

```powershell
uv run --isolated --no-project --with pytest --with pyyaml --with pydantic --with requests --with httpx python -m pytest -q
```

Результат: `169 passed, 22 skipped, 3 deselected in 8.87s`. `customtkinter`, Pillow и psutil намеренно отсутствуют, UI-тесты пропущены.

### С UI-зависимостями

```powershell
uv run --extra dev python -m pytest -q
```

Результат: `216 passed, 2 skipped, 3 deselected in 24.22s`, включая `5 passed` в `tests/test_ui_contract_v11.py`.

### Ruff и release gate

```powershell
uv run ruff check .
uv run --extra dev python scripts/release_gate.py
```

Результат: Ruff — `All checks passed!`; release gate — `PASSED`. Публичный manifest доступен, package URL по-прежнему имеет статус pending upload/404, как и до B3.

## Что осталось

- Все поля, перечисленные в задании B3, подключены. Сбор данных в UI не добавлялся.
- Тег `v0.1.1`, release и manifest не создавались и не изменялись.

## Backend gaps

1. В фактической модели v1.1 `unavailable_reason` находится на `QuotaSnapshot`, а не на `QuotaBucket`, хотя таблица задания называет `QuotaBucket`. UI поддерживает оба расположения без собственного сбора данных.
2. Baseline-корзины провайдеров не содержат числовых лимитов: до provider claim/runtime event UI честно показывает «Н/Д», а не синтетический процент.
3. Live release package остаётся внешней задачей: release gate сообщает `PACKAGE_LIVE=False (Pending Upload 404)`.
