# Отчёт: Задание A4 — изоляция учётных данных и последние долги

Дата: 2026-08-21

## Идентификаторы и границы

- **START_HEAD (BASE_SHA)**: `33b99988ff59345e69e719602058e573a7c6407d`
- **Ветка**: `antigravity/credential-isolation`
- **origin/main**: `33b99988ff59345e69e719602058e573a7c6407d`
- **Граница зоны Codex**: ни один файл в `src/antigravity_provider/router/ui/**`, `hermes_hub_app.py`, `tests/test_ui_*.py` **НЕ изменялся** (`git diff --name-only` по этим путям пуст).
- **Тег `v0.1.1`**: **НЕ создавался** (в репозитории `hermes-hub`).

---

## 1. Изоляция учётных данных в subprocess (P0-1)

- Реализована функция `build_safe_subprocess_env()` в `src/antigravity_provider/agy_subprocess.py`:
  - Окружение дочернего процесса формируется **явно** на основе строгого allowlist системных переменных (`PATH`, `SYSTEMROOT`, `TEMP`, `USERPROFILE`, `LOCALAPPDATA` и др.).
  - Все ключи и токены внешних провайдеров (`OPENAI_API_KEY`, `CODEX_TOKEN_*`, `ANTHROPIC_API_KEY`, `DEEPSEEK_API_KEY`, `OPENCODE_GO_API_KEY`, `XAI_API_KEY`, `HERMES_API_SECRET`, `MY_AUTH_TOKEN` и др.) гарантированно удаляются по шаблонам безопасности `BLOCKED_SECRET_PATTERNS`.
  - Профильная изоляция (`USERPROFILE`, `HOME`, `HOMEPATH`) передается через явные `overrides`.
- Все вызовы дочерних процессов (`agy_generate`, `discover_models`, `AntigravityAdapter.invoke`) переведены на использование `build_safe_subprocess_env()`.
- Добавлен статический AST-тест `test_no_unfiltered_environ_copy_in_src`, запрещающий использование сырых копий `dict(os.environ)` или `os.environ.copy()` в `src/` без безопасной фильтрации.
- Добавлен юнит-тест `test_antigravity_adapter_subprocess_env_isolation`, доказывающий отсутствие ключей сторонних провайдеров в окружении дочернего процесса.

---

## 2. Разбор и фиксация оставшихся долгов (P1-2)

| Долг | Решение / Статус | Обоснование |
|---|---|---|
| **Комментарии `router_profiles.yaml`** | **Закрыт / Зафиксирован** | Функция `save_router_config` в `router_config.py` читает существующие заголовочные комментарии и пустые строки (`existing_comments`) перед первым ключом и сохраняет их verbatim. Inline-комментарии внутри структур пересобираются каноническим safe_dump. |
| **`Registry.CurrentUser` в установщике** | **Закрыт** | В `installer/HermesHubSetup.cs` добавлена проверка переменной окружения `HERMES_HUB_NO_REGISTRY == "1"`, отключающая запись в HKCU при тестовых и изолированных запусках. В `tests/test_installer.py` переменная передается по умолчанию, исключая загрязнение live-реестра. |
| **`fastapi` / `uvicorn`** | **Закрыт** | Зависимости `fastapi` и `uvicorn` вынесены в `[project.optional-dependencies] legacy` в `pyproject.toml` и отсутствуют в обязательных `dependencies`. |
| **Сериализация Antigravity (`_AGY_INVOCATION_LOCK`)** | **Осознанный долг / Зафиксирован** | Windows Credential Manager хранит учётные данные глобально для текущего пользователя под единым ключом `gemini:antigravity`. При одновременном запуске нескольких Antigravity-профилей с разными Google-аккаунтами мьютекс `_AGY_INVOCATION_LOCK` предотвращает состояние гонки при подмене токена в WCM. Для профилей без собственной авторизации блокировка не накладывается. |

---

## 3. Объяснение выбора провайдера (P1-3)

- В `RouterEngine.route_request()` реализована матрица оценки кандидатов `evaluation_matrix`, отслеживающая каждый профиль из `candidate_profiles`:
  - Статус кандидата: `selected`, `skipped`, `rejected`, `failed`.
  - Честная причина отсева/выбора (отключен в конфигурации, исчерпана квота / cooldown всех моделей, достигнут лимит параллелизма `max_concurrency`, сбой выполнения с ошибкой 429/401/timeout, выбран для выполнения с баллом оценки).
- Полный след выбора `selection_trace` (включая `required_capabilities`, `candidates_evaluated`, `selected_profile_id`, `selected_model`, `decision_rationale`, `evaluation_matrix`) сохраняется:
  1. В метаданных успешного ответа: `response["router_metadata"]["selection_trace"]`;
  2. В ответе при исчерпании всех маршрутов: `response["selection_trace"]`;
  3. В записях `EventLogService` (категория `routing`).

---

## 4. Результаты проверок

- **Headless pytest** (3.8): `175 passed, 22 skipped, 3 deselected in 9.79s`
- **Full pytest** (Python 3.12 с `customtkinter`, `pillow`, `psutil`): `175 passed, 22 skipped, 3 deselected in 9.49s`
- **Ruff linter**: `All checks passed!`
- **Release Gate**: `7/7 PASSED` (`[RELEASE GATE: PASSED] All criteria verified. Ready for Candidate v0.1.1`)
- **Live Update Feed**: `[MANIFEST_LIVE=True, PACKAGE_LIVE=True, PACKAGE_HASH_VERIFIED=True]` (sha256 `f2e565619209b0746182ae0e4612b021e50c739af04ca1e455bd48a4d42385f1`)
- **UI Zone Isolation**: `0 files modified in UI area`
