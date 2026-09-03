# Отчёт независимого оркестратора: Release Gate ветки `codex/workflow-canvas` (A30)

## Дата проведения
2026-08-26

## Объект аудита
- **Ветка:** `codex/workflow-canvas`
- **Цель:** Независимая проверка реализации задания A30 («Главный экран "Обзор" — граф workflow, файлы агентов, LIVE»).

---

## 1. Сводка Git и состояние репозитория

- **`START_HEAD` (базовый коммит / merge-base с `main`):** `d6ec34d482a4e00a2017c7b53e934a82df0cc5ad`
- **`FINAL_HEAD` (коммит ветки A30):** `0c19738e29683c215352ea9de1b68a0a2e95b1f8` (`feat(web): add workflow canvas and live agent workspace`)
- **`origin/main`:** `c35bc4868d62cfa7abb7a1a4c1c17eca51eb6ce5`
- **Состояние рабочей директории (`git status`):**
  - Нестажированные изменения в бинарниках и установщике (`installer/HermesHubSetup.cs`, `launcher/HermesHub.exe`, `launcher/HermesHubWeb.exe`).
  - Нестажированный фикс CORS в `src/antigravity_provider/router/web/server.py` (перенесённый из `c35bc48` на `main`).
  - Неотслеживаемые задания в inbox (`agents/inbox/2026-08-25-A32-remove-desktop.md`, `agents/inbox/2026-08-26-antigravity-release-gate-a30.md`).

---

## 2. Результаты детерминированных проверок

### 2.1. Линтер `ruff check .`
- **Результат:** `All checks passed!` (0 ошибок, 0 предупреждений).

### 2.2. Полный регрессионный сьют `pytest tests/ -v`
- **Результат:** **458 passed, 2 skipped, 3 deselected, 1 failed** (всего 461 тест).
- **Время прогона:** 86.74 сек.

### 2.3. Скрипт `scripts/release_gate.py`
- **Результат:** `[RELEASE GATE: FAILED] One or more checks failed. Release blocked.`
- **Причина:** Падение теста обратной совместимости `tests/test_web_parity_a21.py::test_web_client_html_and_js_7_views_parity`.

---

## 3. Реестр найденных дефектов

| ID | Приоритет | Компонент | Описание дефекта и минимальное воспроизведение |
| :--- | :--- | :--- | :--- |
| **DEF-01** | **P1** | `tests/test_web_parity_a21.py:133` | **Устаревшая проверка селектора в тестах регрессии.** Тест проверяет наличие старого контейнера `overview-route-diagram` в `index.html`. В рамках A30 главный экран «Обзор» был полностью перестроен в Workflow Canvas (`workflow-canvas`, `workflow-main-layout`), и старый селектор был правомерно удалён из разметки, но тест не был обновлён под новый layout A30. <br>**Воспроизведение:** `pytest tests/test_web_parity_a21.py -k test_web_client_html_and_js_7_views_parity`. |
| **DEF-02** | **P2** | `server.py` / `git` | **Отставание ветки от `origin/main`.** Ветка `codex/workflow-canvas` ответвлена от `d6ec34d` и не включает коммит безопасности `c35bc48` (`fix(security): любой сайт во вкладке рядом мог управлять хабом`). Перед финальным слиянием в `main` требуется rebase / merge с актуальным `main`. |

---

## 4. Результаты проверки подсистем A30

### P0-1. Модель агента и Agent File
- **Статус:** **PASS**
- Сервис `WorkflowService` в [`workflow_service.py`](file:///c:/Users/Ochenstarik/Agent_projects/hermes-hub/src/antigravity_provider/router/workflow_service.py) реализует полное управление жизненным циклом агентов: `create_agent`, `update_agent`, `delete_agent`.
- Роли роутера автоматически мигрируют в сущности агентов.
- Файлы агентов создаются физически на диске в `agents/{role}.md` (например, `agents/orchestrator.md`, `agents/coder-primary.md`) и содержат реальный Markdown.
- Удаление агента, задействованного в ребрах графа, требует явного подтверждения (`confirmation_required: True`), предотвращая повреждение графа.
- Проверено тестами: `test_router_roles_migrate_to_agents_and_create_real_files`, `test_create_update_file_and_restart_persistence`, `test_delete_requires_explicit_confirmation_when_referenced`.

### P0-2. Граф workflow (Canvas, EDIT/LIVE, Циклы)
- **Статус:** **PASS**
- Граф реализован на чистом SVG + HTML5 (без npm, без react, без сторонних зависимостей сборки) в [`workflow.js`](file:///c:/Users/Ochenstarik/Agent_projects/hermes-hub/src/antigravity_provider/router/web/static/workflow.js) и [`workflow.css`](file:///c:/Users/Ochenstarik/Agent_projects/hermes-hub/src/antigravity_provider/router/web/static/workflow.css).
- **Режимы:** Чёткое переключение между `LIVE` (мониторинг исполнения) и `EDIT` (редактирование графа, соединение портов).
- **Редактор ребра:** Модальное окно позволяет задавать условия переходов (`SUCCESS`, `REVIEW_PASSED`, `REVIEW_FAILED`) и подписи.
- **Поддержка циклов:** Циклические маршруты (`Кодер 1 → Ревьюер → Кодер 1`) поддержаны и валидируются.
- **Защита от бесконечного зацикливания:** Параметр `max_iterations` отображается на экране (например, `Итерация: 2 / 5`), сохраняется в конфигурации и принудительно останавливает цикл с генерацией явного события `WORKFLOW_MAX_ITERATIONS`.
- **Элементы управления:** Мини-карта, масштабирование (`- 100% + ⛶`), легенда состояний узлов и рёбер.

### P0-3. LIVE-мониторинг, события и обработка ошибок
- **Статус:** **PASS**
- Поддержаны 5 состояний агента: `Ожидает` (серый), `Работает` (синий), `Проверяет` (жёлтый), `Ошибка` (красный), `Завершено` (зелёный).
- Тексты реальных ошибок провайдеров (например, `No authentication token found for Codex profile 'codex-orch'`) доходят до статуса запуска и списка событий.
- Прерванный перезапуском прогон корректно помечается статусом `interrupted` с записью события `WORKFLOW_INTERRUPTED`.
- Проверено тестами: `test_live_cycle_stops_with_explicit_iteration_limit_event`, `test_interrupted_run_is_reported_not_silently_completed`, `test_provider_error_text_reaches_run_and_events`.

### P0-4. Честность данных (Zero Fake / Zero Mock)
- **Статус:** **PASS**
- Поиск по кодовой базе показал полное отсутствие захардкоженных демонстрационных чисел из макета (`12`, `3.42 с`, `1.42M`, `94.2%`, `42`, `account-01...`).
- Все 5 оперативных KPI-показателей на экране «Обзор» берутся из реальных источников:
  1. *Активные задачи:* `workflow.run.status` (0 или 1).
  2. *Агенты онлайн:* `readiness.roles_ready_count / readiness.total_roles` из сервиса `readiness`.
  3. *Среднее время ответа:* `telemetry.global.latency_p50_ms` (при отсутствии вызовов: `Н/Д: за 24 часа нет измеренных вызовов`).
  4. *Использование токенов:* `telemetry.global.total_tokens` (при отсутствии: `Н/Д: провайдеры не вернули usage`).
  5. *Успешность задач:* отношение `successful_calls / total_calls` (при отсутствии: `Н/Д: за 24 часа нет завершённых вызовов`).
- Состояния загрузки (`workflow.is_loading`) явно отделены от отсутствия данных.

### P0-5. Неприкосновенность десктопного UI
- **Статус:** **PASS**
- Проверка `git diff --stat d6ec34d 0c19738 -- src/antigravity_provider/router/ui` подтвердила **0 изменений** в каталоге `router/ui/**`.

---

## 5. Проверка артефактов и скриншотов

Все 5 обязательных скриншотов присутствуют в каталоге `docs/screenshots/a30/` и проверены:
1. [`overview-live.png`](file:///c:/Users/Ochenstarik/Agent_projects/hermes-hub/docs/screenshots/a30/overview-live.png) — Главный экран в режиме LIVE с 6 агентами, честными статусами «Н/Д» и мини-картой.
2. [`overview-edit-inspector.png`](file:///c:/Users/Ochenstarik/Agent_projects/hermes-hub/docs/screenshots/a30/overview-edit-inspector.png) — Режим EDIT с выбранным узлом «Кодер 1», портами соединения и панелью инспектора (вкладки Основное, Модель, Инструкции, Инструменты, Память).
3. [`edge-editor.png`](file:///c:/Users/Ochenstarik/Agent_projects/hermes-hub/docs/screenshots/a30/edge-editor.png) — Модальное окно создания/редактирования ребра (`coder-primary` → `reviewer`, условие `SUCCESS`).
4. [`agent-file-editor.png`](file:///c:/Users/Ochenstarik/Agent_projects/hermes-hub/docs/screenshots/a30/agent-file-editor.png) — Редактор файла агента `agents/coder-primary.md` с реальным содержимым.
5. [`overview-live-provider-error.png`](file:///c:/Users/Ochenstarik/Agent_projects/hermes-hub/docs/screenshots/a30/overview-live-provider-error.png) — Отображение реальной ошибки провайдера в узле «Главный оркестратор» (красный статус) и в журнале событий LIVE.

---

## 6. Пропущенные проверки
- **Пропущенных проверок нет.** Все 10 пунктов регламента выполнены в полном объёме.

---

## 7. Итоговый вердикт Release Gate

> **ВЕРДИКТ: `BLOCKED` (Требуется исправление 1 теста и Rebase)**

**Обоснование:**
1. Функциональная реализация A30 (`WorkflowService`, Canvas, Agent Files, LIVE/EDIT, Cycle limits, Data honesty) выполнена качественно и полностью соответствует ТЗ.
2. Автоматический Release Gate заблокирован из-за дефекта **DEF-01** (устаревший ассерт `overview-route-diagram` в `tests/test_web_parity_a21.py:133`), дающего 1 падение из 461 теста.
3. Ветка требует rebase на актуальный `origin/main` (включение фикса безопасности CORS **DEF-02**) и обновления теста `test_web_parity_a21.py` на селектор `workflow-canvas`.
