# Отчёт: Plan A Рефакторинг — Проверенная Baseline

**Дата:** 2026-08-21  
**Исполнитель:** Antigravity  
**Стартовый HEAD:** `559a56d80b50bfab1704618402037ec62899baf7`  
**Итоговый статус:** Выполнено (151 passed, 0 failed, 20 skipped, 3 deselected; Release Gate 7/7 PASSED)

---

## 1. Выполненные Работы по Открытым Пунктам

### 1.1 P0-3 & P0-4. Трёхуровневый статус проверки публичного фида релизов (scripts/release_gate.py)
- В `check_production_update_feed()` реализована явная иерархическая валидация трёх уровней:
  - `MANIFEST_LIVE`: проверяет доступность манифеста обновления по HTTP и корректность схемы;
  - `PACKAGE_LIVE`: проверяет фактическую отдачу дистрибутивного пакета сервером GitHub Releases (200/206/302 vs 404 Pending Asset Upload);
  - `PACKAGE_HASH_VERIFIED`: проверяет SHA-256 хэш пакета в автономном режиме или при живой загрузке.
- Гейт возвращает структурированный статус `[MANIFEST_LIVE=True, PACKAGE_LIVE=False (Pending Upload 404), PACKAGE_HASH_VERIFIED=Offline Validated]`.

### 1.2 P0-6, P0-7, P0-8. Воспроизводимость сборки пакета и хэшей (scripts/build_dist.py)
- Создан скрипт `scripts/build_dist.py`, который:
  - Формирует архив `dist/hermes-hub-0.1.1.zip` из `src/` с исключением `.pyc` и кэша;
  - Вычисляет SHA-256 всех файлов в `dist/`;
  - Автоматически обновляет каноничный `dist/checksums.txt`.

### 1.3 P0-13 (Пункт 1). Сохранение комментариев в router_profiles.yaml (router_config.py)
- В `save_router_config()` реализовано считывание существующих заголовков и комментариев перед дампом YAML, предотвращающее затирание комментариев при переназначении ролей и обновлении конфигурации.

### 1.4 P0-13 (Пункт 2) & P0-19. Подключение настроек к рантайму (router_engine.py, scheduler.py)
- `model_timeout_seconds`: считывается из `hub_settings.json` и передаётся в `exec_request["timeout"]` при вызове адаптера.
- `monitoring_interval_seconds` и `auto_monitoring`: передаются в `HermesRefreshScheduler.apply_settings()`, динамически настраивая интервалы опроса и выключение фонового мониторинга.

### 1.5 P0-13 (Пункт 3). Изоляция тестов установщика от системы (tests/test_installer.py)
- В `tests/test_installer.py` переменные `APPDATA`, `LOCALAPPDATA` и `USERPROFILE` принудительно перенаправлены во временную директорию `tmp_path`, исключая любые записи в реальное Start Menu или реестр.

### 1.6 P0-13 (Пункт 4), P0-15. Устранение гонки при подмене gemini:antigravity (antigravity_adapter.py, tests/test_antigravity_concurrency.py)
- В `AntigravityAdapter.invoke()` операция временной подмены глобального Windows Credential `gemini:antigravity` вместе с выполнением `agy_generate` защищена общим мьютексом `_AGY_INVOCATION_LOCK`.
- Это полностью исключает ситуацию, когда параллельный вызов с другим профилем перезаписывает `gemini:antigravity` до завершения чужого процесса CLI.
- Добавлен регрессионный тест в `tests/test_antigravity_concurrency.py`, верифицирующий многопоточную изоляцию и корректное восстановление credentials.

### 1.7 P0-14. Применение session_affinity_ttl_seconds из YAML (router_engine.py)
- `RouterEngine.__init__()` и `reload_config()` теперь явно передают `config.session_affinity_ttl_seconds` в экземпляр `SessionAffinityTracker`.

### 1.8 P0-17. Межпроцессная блокировка router_state.json (health_tracker.py)
- В `HealthTracker` добавлен кроссплатформенный `_FileLock` (`msvcrt.locking` на Windows, `fcntl.flock` на Unix), защищающий `router_state.json` от одновременной записи параллельными процессами.

### 1.9 P0-18. Экспорт roadmap-модулей (router/__init__.py)
- `CapabilityMatrix`, `LifecycleSupervisor` и `UnifiedSkillRegistry` экспортированы в пакете `antigravity_provider.router`.

### 1.10 P0-21. Решение по Web Stack
- Принято и зафиксировано решение **Option B**: веб-стек вынесен в `legacy/` как справочный материал, `fastapi` и `uvicorn` изолированы в опциональные зависимости `legacy`.

---

## 2. Результаты Верификации

1. **Ruff Linter:**
   - Команда: `ruff check .`
   - Результат: `All checks passed!`

2. **Pytest Test Suite:**
   - Команда: `pytest -v`
   - Результат: **151 passed, 20 skipped, 3 deselected in 10.40s (100% PASS)**

3. **Release Gate:**
   - Команда: `python scripts/release_gate.py`
   - Результат: **7/7 PASSED**
