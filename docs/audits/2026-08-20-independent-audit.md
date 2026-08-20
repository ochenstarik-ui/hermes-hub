# Независимый аудит релиза Hermes Hub

**Дата**: 2026-08-20  
**Репозиторий**: `https://github.com/ochenstarik-ui/hermes-hub`  
**Проверенная ревизия**: `origin/main @ 5ccfd48`  
**Текущая заявленная версия**: 0.1.0  
**Целевая версия релиза**: 0.1.1  

---

## 1. Сводка результатов аудита

Независимый аудит выявил ряд критических архитектурных и прикладных несоответствий, требующих обязательного исправления (Release Gate Blockers):

### P0 (Блокеры релиза — 9 пунктов)
1. **P0-1 (customtkinter / Pillow imports)**: На чистой системе без установленных в venv пакетов `customtkinter` / `Pillow` приложение аварийно завершается без внятного сообщения.
2. **P0-2 (ProfileAuthManager.get_profile_dir signature)**: Несогласованность сигнатуры метода `get_profile_dir` (`provider, profile_id` vs `profile_id`).
3. **P0-3 (Missing `import json` in wizard)**: В `add_account_wizard.py` отсутствует `import json`, что приводит к падению при попытке сохранить API-ключ для Codex / OpenCode Go.
4. **P0-4 (AutoAssigner.auto_assign_all)**: UI вызывает несуществующий метод `AutoAssigner.auto_assign_all()`, вызывая ошибку `AttributeError`.
5. **P0-5 (Antigravity failover & error handling)**: `agy_generate` возвращает текст ошибки провайдера как обычный успешный ответ модели (`choices[0].message.content`), из-за чего RouterEngine не распознаёт ошибку квоты и не выполняет failover.
6. **P0-6 (OAuth session status handling)**: Неунифицированные статусы OAuth сессий приводят к зависанию визарда на 120 секунд вместо немедленной реакции на ошибку.
7. **P0-7 (assign_role button handler)**: Кнопка «Назначить» не имела реального диалога и обработчика назначения роли с сохранением в конфигурацию.
8. **P0-8 (Wizard role application)**: Выбранная на 4 шаге визарда роль не применялась к реальной конфигурации роутера.
9. **P0-9 (Fake API validation)**: В визарде присутствовала заглушка «успешно проверено» без реальной валидации ключа и обнаружения моделей.

---

## 2. Категории P1 / P2 / P3

- **P1 (Архитектурная корректность)**: Изоляция тестов через `HERMES_HOME` (tmp_path), офлайн pytest по умолчанию, background health snapshot, in-place UI обновления, разделение здоровья профиля и моделей, TTL сессионной привязки, блокировка `router_state.json`, изоляция переменных окружения subprocess, санитизация логов, удаление мертвого FastAPI веб-стека.
- **P2 (Дистрибуция и надежность)**: Канонический инсталлятор, проверка совместимости версий Hermes (`compatibility.json`), ресурсная иконка в .exe, Single Instance mutex, `startup.log`.
- **P3 (Автообновления и CI/CD)**: GitHub Actions CI, встроенный `HermesHubUpdater` с верификацией SHA-256, поддержка отката (rollback), E2E dogfood update test `v0.1.1 -> v0.1.2`, скрипт `scripts/release_gate.py`.
