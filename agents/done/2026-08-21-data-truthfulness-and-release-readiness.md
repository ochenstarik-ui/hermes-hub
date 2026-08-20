# Отчёт: Правдивость данных и готовность к релизу v0.1.1

**Дата:** 2026-08-21  
**Исполнитель:** Antigravity  
**Статус:** Выполнено (100% PASS, Release Gate 7/7)  

---

## 1. Контекст и Выполненные Работы

Устранены дефекты показа недостоверных данных и тихого создания фиктивных кодов авторизации.

### 1.1 P0-1. Честный сбор и маркировка квот (quota_collector.py, account_identity.py, accounts_view.py)
- **Исключены выдуманные проценты:** Удалены захардкоженные `used_percent` (12%, 9%, 1%, 2%, 5%, 10%, 6%, 9%, 14%, 13%, 1%). При отсутствии сетевого API провайдера для измерения точного расхода `used_percent` и `remaining_percent` устанавливаются в `None`.
- **Честный источник:** Источники квот маркируются как `"baseline"` (или `"estimated"` / `"runtime_event"`), а не фиктивными `*_api`.
- **Визуальный признак в UI:** В `AccountCardWidget` для оценочных/базовых данных отображается явная подпись `(оценка)` и бейдж `• оценка` во времени обновления.
- **Честная формулировка доступности:** `QuotaBucket.formatted_remaining()` возвращает `"Доступна"`, а при runtime-исчерпании квоты (429) — `"Исчерпана (Сброс через ...)"`.

### 1.2 P0-2. Устранение тихого фолбэка на поддельный код авторизации (codex_oauth.py, grok_oauth.py, claude_oauth.py)
- **Fail-Closed при сетевой ошибке:** При недоступности эндпоинта провайдера в `CodexOAuthSession` и `GrokOAuthSession`:
  - `start()` немедленно переходит в статус `status = "failed"` с возвратом ошибки.
  - Поток поллинга `poll_thread` **не запускается**.
  - Фиктивные коды `CDX-...` и `GRK-...` **не генерируются**.
- **Строгий DEV_MODE:** Фолбэк на локальную сессию разрешён **только** при явном флаге `HERMES_HUB_DEV_MODE=1` с визуальным предупреждением в мастере `⚠️ ТЕСТОВЫЙ РЕЖИМ (HERMES_HUB_DEV_MODE)`.
- **Claude OAuth:** В `handle_auth_code()` при сбое обмена кода возвращается ошибка; прямой приём строки допускается только для явных ключей `sk-ant-` или в `HERMES_HUB_DEV_MODE=1`.

### 1.3 P1-3. Документация OAuth-клиентов (docs/OAUTH_CLIENT.md)
- Документированы 4 публичных клиента (Google Antigravity, OpenAI Codex `app_EMoamEEZ73f0CkXaXp7hrann`, xAI Grok `b1a00492-073a-47ea-816f-4c329264a828`, Anthropic Claude `9d1c250a-e61b-44d9-88ed-5944d1962f5e`).
- Описаны модели угроз и обоснования по RFC 8252 (Native Apps), RFC 7636 (PKCE) и RFC 8628 (Device Authorization Grant).

### 1.4 P1-4. Очистка неиспользуемого gui_server.py
- Неиспользуемые файлы `gui_server.py` и `gui_cockpit.html` вынесены из `src/` в `legacy/`.
- Зависимости `fastapi` и `uvicorn` изолированы в секцию `[project.optional-dependencies] legacy`.

---

## 2. Результаты Тестирования и Release Gate

1. **Новый набор тестов (`tests/test_data_truthfulness_and_oauth_security.py`):**
   - Проверка честной маркировки источников квот `source != '*_api'` и `is_estimated=True`.
   - Проверка немедленного `failed` статуса и отсутствия поллинга в Codex и Grok при сетевых сбоях.
   - Проверка работы mock-сессий строго под `HERMES_HUB_DEV_MODE=1`.
   - Проверка отклонения невалидных кодов в Claude.

2. **Полный прогон Pytest:**
   - Команда: `pytest -v`
   - Результат: **98 passed, 7 skipped, 3 deselected in 9.63s (100% PASS)**.

3. **Release Gate Verification (`scripts/release_gate.py`):**
   - Результат: **7/7 PASSED**.
