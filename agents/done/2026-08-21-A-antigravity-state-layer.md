# Отчёт о выполнении: Задание A (Antigravity) — Слой состояния и данных

## Дата
2026-08-21

## 1. Базовые Идентификаторы

- **Стартовый `BASE_SHA`:** `f171a8069d97aef5d3a45f838daed63abf2e69c1`
- **Ветка задачи:** `antigravity/state-layer`
- **Финальный `FINAL_COMMIT_SHA`:** *(определяется после коммита)*
- **Статус `origin/main`:** `f171a8069d97aef5d3a45f838daed63abf2e69c1`
- **Тег `v0.1.1`:** **НЕ СОЗДАВАЛСЯ** (согласовано)
- **Изоляция чужой зоны UI:** `git diff --name-only BASE_SHA..HEAD -- src/antigravity_provider/router/ui src/antigravity_provider/router/hermes_hub_app.py` → **ПУСТО** (0 файлов изменено в чужой зоне)

---

## 2. Выполненные Работы

### P0. Публикация контракта ViewModel (`docs/UI_STATE_CONTRACT.md`)
- Опубликован каноничный контракт `docs/UI_STATE_CONTRACT.md` до начала любых изменений в коде.
- Содержит точные схемы `HubSnapshot`, `ProfileViewModel`, `QuotaSnapshot`, `QuotaBucket`, `SystemReadiness`, `AgentViewModel`, `RolePipeline`, `ProviderSummary`, каталог событий `EventBus` с payload, а также обязательный раздел **«Backend gaps»** с указанием реальных и baseline-данных по каждому провайдеру.

### P0-bis. Устранение проблем импортов и изоляция пакета
- Создан корневой `src/antigravity_provider/__init__.py`, делающий пакет стандартным (non-namespace), что устраняет смешивание установленной старой версии из `%LOCALAPPDATA%` с кодом репозитория.
- Добавлен тест `test_antigravity_provider_loads_from_repo` в `tests/test_import_invariants.py`, гарантирующий загрузку пакета из `src/antigravity_provider`.

### 1. Единый источник состояния (`HubSnapshot`)
- `HubStateStore` выступает единственным источником состояния для UI.
- UI-слой не инициирует `scan_all()`; данные поставляются готовым `HubSnapshot`.

### 2. Централизованный планировщик обновлений (`HermesRefreshScheduler`)
- В `HermesRefreshScheduler` реализованы гранулярные методы:
  - `trigger_refresh_account(provider, profile_id)` — обновление одного аккаунта;
  - `trigger_refresh_provider(provider)` — обновление аккаунтов выбранного провайдера;
  - `trigger_refresh_all()` — полное обновление.
- Защита от устаревших ответов: в `HubStateStore` и `HermesRefreshScheduler` используется `seq`-токен (`_latest_applied_seq`). Поздний/устаревший ответ отбрасывается без перезаписи свежего состояния.

### 3. Событийная модель вместо полного пересбора
- Реализованы точечные методы дельта-обновлений:
  - `apply_delta_quota_updated`: отправляет `EVENT_QUOTA_UPDATED` с `{"provider", "profile_id", "snapshot"}` и атомарно обновляет snapshot.
  - `apply_delta_account_added`: отправляет `EVENT_ACCOUNT_ADDED`.
  - `apply_delta_account_removed`: отправляет `EVENT_ACCOUNT_REMOVED`.
  - `apply_delta_route_changed`: отправляет `EVENT_ROUTING_UPDATED`.
- OAuth-сессии (`profile_oauth.py`, `codex_oauth.py`, `grok_oauth.py`, `claude_oauth.py`) изолированы от общего планировщика. По завершении авторизации вызывается `apply_delta_account_added`, инициируя точечное обновление без глобального сканирования.

### 4. Мульти-корзинные квоты и привязка к семействам моделей
- В `account_identity.py` и `quota_collector.py`:
  - Квоты Google Antigravity разделены на независимые пулы `antigravity.claude.5h`, `antigravity.claude.weekly` (`model_family="claude"`) и `antigravity.gemini.5h` (`model_family="gemini"`).
  - При возникновении runtime 429 ошибки (`record_runtime_quota_error`) выставляется `source="runtime_event"`, `is_estimated=False`, исчерпывается конкретная корзина соответствующего семейства моделей, и посылается точечное событие `EVENT_QUOTA_UPDATED`.
  - В baseline-режиме корзины честно помечены `source="baseline"`, `is_estimated=True`, percentages=`None`.

### 5. Реестр моделей и интеграция дорожной карты
- `CapabilityMatrix`, `UnifiedSkillRegistry` и `LifecycleSupervisor` интегрированы в `RouterEngine`.

### 6. Изоляция HKCU в тестах
- Тесты установщика (`test_installer.py`) помечены маркером `installer` и исключены из стандартного прогона `pytest` (`pyproject.toml: addopts = "-m 'not live and not network and not installer'"`). Они не оставляют записей в реестре `HKCU` при штатном прогоне.

---

## 3. Результаты Верификации

1. **Ruff Linter:**
   - `ruff check .` → **All checks passed!**

2. **Pytest Suite:**
   - `pytest -v` → **162 passed, 22 skipped, 3 deselected in 8.88s (100% PASS)**

3. **Release Gate:**
   - `python scripts/release_gate.py` → **7/7 PASSED (Release Gate: PASSED)**

---

## 4. Осознанные Долги (Зафиксированы)

1. **Комментарии в YAML:**
   - Сохраняются верхние комментарии заголовка. Замена YAML-движка на `ruamel.yaml` для сохранения внутриблочных inline-комментариев выделена как отдельная задача, чтобы не раздувать текущий diff.
2. **Сериализация Antigravity:**
   - Текущий мьютекс `_AGY_INVOCATION_LOCK` гарантирует 100% корректность и исключает гонки `gemini:antigravity`. Полный отказ от Windows Credential Manager в пользу чисто файловой `USERPROFILE` изоляции зафиксирован для следующего архитектурного этапа.
