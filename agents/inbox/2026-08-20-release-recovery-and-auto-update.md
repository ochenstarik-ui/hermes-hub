# Задание: Hermes Hub — Release Recovery + GitHub Auto Update

## Дата поступления
2026-08-20

## Область задачи (Scope)
1. **Independent Audit & Remediation Tracker**:
   - Сохранение `docs/audits/2026-08-20-independent-audit.md`.
   - Ведение `docs/audits/2026-08-20-remediation-tracker.md` со всеми ID, приоритетами, статусами и тестами.
2. **Unified Version Source (v0.1.1)**:
   - Создание единого источника истины версии `version.py`.
   - Синхронизация `pyproject.toml`, `compatibility.json`, GUI About, CLI, Installer, Updater, Diagnostics.
3. **P0 Blockers Resolution (9/9 VERIFIED)**:
   - P0-1: `customtkinter` / `Pillow` чистая установка в venv Hermes + проверка импортов.
   - P0-2: Унификация `ProfileAuthManager.get_profile_dir(profile_id)`.
   - P0-3: `json` импорт в `add_account_wizard.py` + тест сохранения API key.
   - P0-4: Реализация `AutoAssigner.auto_assign_all()`.
   - P0-5: Antigravity failover & typed exceptions (ошибки провайдера не возвращаются как успешный ответ).
   - P0-6: Унификация статусов OAuth (`pending`, `success`, `failed`, `cancelled`, `timeout`).
   - P0-7: Реальный обработчик кнопки `assign_role`.
   - P0-8: Применение выбранной роли из Wizard в конфигурацию.
   - P0-9: Удаление фейковой валидации API ключей (реальная проверка или `NOT_VERIFIED`).
4. **P0 Release Test & Isolation**:
   - `tests/test_p0_release_gate.py`.
   - Изоляция тестов через `HERMES_HOME` (tmp_path), запрет модификации реальных файлов пользователя.
   - Pytest маркеры (`unit`, `integration`, `network`, `installer`, `live`).
5. **Router, Health & Performance Fixes**:
   - Background snapshot updates, устранение фризов `_restore_status()`, bounded parallelism в `scan_all`.
   - In-place UI update без мерцания.
   - Cooldown recovery & разделение здоровья профиля и семейств моделей.
   - Session affinity TTL и inter-process lock для `router_state.json`.
   - Безопасное окружение subprocess (whitelist env vars).
   - Error taxonomy и round-trip конфигурации.
6. **Security & Cleanup**:
   - Единый `paths.py`.
   - Санитизация логов (маскирование токенов/ключей).
   - Вывод устаревшего веб-стека (`gui_server.py`, `gui_cockpit.html` -> legacy) и удаление FastAPI/uvicorn из runtime.
7. **Packaging, Installer & Single Instance**:
   - Канонический инсталлятор с pre-flight проверкой версии Hermes и зависимостей UI.
   - Single Instance mutex.
   - Запись `startup.log` до инициализации UI.
8. **CI/CD & Built-in Auto Updates**:
   - GitHub Actions CI на чистом Windows runner.
   - Релизный пайплайн `v0.1.1`.
   - Встроенный механизм проверки и установки обновлений через `HermesHubUpdater` с защитой от поврежденных файлов (SHA-256) и rollback.
   - E2E dogfood update test v0.1.1 -> v0.1.2.
   - `scripts/release_gate.py`.
9. **Документация и Финальный Отчёт**:
   - Обновление всей документации (`README.md`, `ARCHITECTURE.md`, `AUTH.md`, `SECURITY.md`, `INSTALLATION.md`, `UPDATES.md`, `DEVELOPMENT.md`, `ROUTER.md`).
   - Итоговый аудит `docs/audits/2026-08-20-release-recovery-results.md`.
