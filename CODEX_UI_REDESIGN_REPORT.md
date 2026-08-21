# Hermes Hub UI redesign — фазы 2–6

Дата: 2026-08-21

Ветка: `codex/ui-redesign`

INITIAL_BASE_SHA: `c6876e96b274b598ada964a6639b6c3ad038aebf`

BASE_SHA после финального обязательного rebase на `origin/main`: `e8a404be035fa04b5f76e3e572c6539fba0e83e4`. Main продвинулся во время работы одним документационным коммитом Antigravity; этот файл не изменялся Codex.

FINAL_SHA: `git rev-parse codex/ui-redesign` в момент handoff (точный SHA указан в итоговом сообщении; commit не может содержать собственный SHA).

## Изменённые файлы

- `src/antigravity_provider/router/hermes_hub_app.py`
- `src/antigravity_provider/router/ui/components.py`
- `src/antigravity_provider/router/ui/views/accounts_view.py`
- `src/antigravity_provider/router/ui/views/dashboard_view.py`
- `src/antigravity_provider/router/ui/views/health_view.py`
- `src/antigravity_provider/router/ui/views/logs_view.py`
- `src/antigravity_provider/router/ui/views/providers_view.py`
- `src/antigravity_provider/router/ui/views/routing_view.py`
- `src/antigravity_provider/router/ui/views/settings_view.py`
- `src/antigravity_provider/router/ui/views/team_view.py`
- `tests/test_ui_phase2_6.py`
- `CODEX_UI_REDESIGN_REPORT.md`

Файлы state/data/router, adapters, installer, scripts, config, legacy и чужие тесты не изменялись.

## Переработанные экраны

### Аккаунты и квоты

- Одна карточка соответствует одному `profile_id` и переиспользуется между поколениями snapshot.
- `QuotaBucketWidget` хранится по стабильному `QuotaBucket.id`; существующая корзина обновляется на месте.
- Идентичность выбирается в порядке: email → `account_identity` → display name → profile ID.
- `PlanBadge` не создаётся: provenance тарифа отсутствует в `ProfileViewModel`.
- Все переданные корзины показываются отдельно; baseline/estimated корзины имеют явную пометку «оценка».
- Неизвестный остаток и время сброса показываются как `Н/Д`.
- Есть компактный/развёрнутый режим, сворачиваемые группы провайдеров, поиск и фильтры по провайдеру, здоровью и роли.
- Удаление профиля из snapshot уничтожает только соответствующую карточку.

### Обзор

- Экран добавлен в основную навигацию.
- Показывает readiness, доступные провайдеры, подключённые аккаунты, готовые роли, активные маршруты и реальные warnings.
- Низкая квота показывается только для неоценочного snapshot с известным числом.
- Истёкшая авторизация показывается из `auth_state`.
- Выдуманные throughput/SLA/cost метрики отсутствуют.

### Команда

- Иерархия разделена на «Оркестратор» и «Роли и агенты».
- Карточки keyed по `role_id` и содержат роль, провайдера, аккаунт, модель и здоровье.
- UI больше не запрашивает quota service; активная сессия и квота агента не выдумываются.

### Маршрутизация

- Роли keyed по `role_id`, узлы цепочки — по `profile_id`.
- Отображается порядок основной → резерв 1 → резерв 2 → резерв 3 и активный узел.
- Показываются только доступные provider/model/status поля.
- Причина переключения честно обозначена как `Н/Д`.
- Редактирование остаётся кнопочным; drag-and-drop не добавлялся.

### Второстепенные экраны

- Providers и Health используют keyed cards/rows.
- Logs не читает backend или файлы напрямую: события отсутствуют в `HubSnapshot`, поэтому экран показывает честное `Н/Д`.
- Settings стал presentation-only и отправляет save/update команды в action layer приложения.
- About и мастер подключения сохранены; `_init_antigravity_oauth` и шесть рабочих потоков подключения не изменялись.

## Замер производительности: 50 аккаунтов

Тест: `test_fifty_accounts_update_one_quota_without_rebuilding_other_cards`.

| Состояние | Карточек создано | Карточек уничтожено | Quota widgets создано | Quota widgets уничтожено |
|---|---:|---:|---:|---:|
| Первичная отрисовка | 50 | 0 | 50 | 0 |
| После изменения квоты аккаунта A | 50 | 0 | 50 | 0 |
| Дельта операции | **0** | **0** | **0** | **0** |

Object identity всех 50 карточек до и после обновления совпадает. Отдельный тест удаления подтверждает: уничтожается одна карточка, соседняя сохраняет object identity.

## Проверки

### Без UI-зависимостей

```powershell
uv run --isolated --no-project --with pytest --with pytest-asyncio --with anyio --with pyyaml --with pydantic --with requests --with httpx pytest -q
```

Результат: `160 passed, 28 skipped, 3 deselected in 9.55s`.

### С UI-зависимостями

Полный набор успешно проходил одной командой (`202 passed, 9 skipped, 3 deselected`). Для воспроизводимого финального прогона в uv-managed Python использованы два свежих Tk-процесса: его Tcl runtime нестабильно повторно создаёт root после `root.destroy()` в соседнем OAuth-тесте.

```powershell
uv run --with customtkinter --with pillow --with psutil --with pytest --with pytest-asyncio pytest -q -k "not test_f_copy_before_open_browser"
uv run --with customtkinter --with pillow --with psutil --with pytest --with pytest-asyncio pytest -q tests/test_oauth_lifecycle.py::test_f_copy_before_open_browser
```

Результаты: `201 passed, 9 skipped, 4 deselected in 26.42s` и `1 passed in 2.86s`. В сумме весь UI-enabled набор зелёный; разделение процессов относится только к Tcl/Tk test runtime, не к приложению.

### Статика и release gate

```powershell
uv run --with ruff ruff check .
uv run python scripts/release_gate.py
```

Результат: Ruff — `All checks passed`; release gate — `PASSED`. Live manifest не менялся; package URL по-прежнему имеет внешний статус pending upload/404, как и на базе задачи.

## Backend gaps

1. Ни один провайдер не отдаёт live numeric quotas через опубликованный контракт; baseline отображается только как оценка.
2. Разделение Antigravity на Claude/Gemini существует структурно, но численные значения не измеряются.
3. Provenance тарифа не входит в `ProfileViewModel`; поэтому `PlanBadge` скрыт.
4. В `AgentViewModel` нет активной сессии и квоты.
5. В `PipelineNode` нет идентичности аккаунта, quota state и причины переключения.
6. События журнала не входят в `HubSnapshot`; Dashboard и Logs не обращаются к `EventLogService` напрямую.
7. Латентность, RPS, error rate, стоимость и удалённые SLA отсутствуют.
8. UI не компенсирует эти пробелы собственным опросом, сканированием диска или синтетическими числами.

## Известные ограничения

- В текущем контракте журнал нельзя показать без расширения `HubSnapshot`.
- Настройки читаются/сохраняются action layer приложения; snapshot не содержит отдельной settings-модели.
- Live release package остаётся внешней задачей. По B2 тег, релиз и manifest не создавались и не изменялись.
