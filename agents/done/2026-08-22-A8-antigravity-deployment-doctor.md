# Отчёт: Задание A8 — запуск, развёртывание, самопроверка

Дата: 2026-08-22

## Идентификаторы и границы

- **START_HEAD (BASE_SHA)**: `20078f5ae2ee38525b6da383e20e54d314811a2f` (`origin/main`)
- **Ветка**: `antigravity/deployment-doctor`
- **origin/main**: `20078f5ae2ee38525b6da383e20e54d314811a2f`
- **Граница зоны Codex**: ни один файл в `src/antigravity_provider/router/ui/**`, `tests/test_ui_*.py` **НЕ изменялся** (`git diff --name-only` по этим путям пуст).
- **Тег `v0.1.1`**: **НЕ создавался** (в репозитории `hermes-hub`).

---

## 1. Самолечение и видимая диагностика сбоев при запуске (P0-1)

- **Создан модуль самовосстановления и ранней диагностики** [`src/antigravity_provider/router/launcher_bootstrap.py`](file:///E:/Agent%20projects/hermes-hub/src/antigravity_provider/router/launcher_bootstrap.py):
  - `check_missing_dependencies()`: проверяет наличие `customtkinter`, `PIL`, `psutil`, `yaml`.
  - `self_heal_dependencies()`: если пакеты снесены кнопкой «Repair install» в Hermes, выполняет автоматическую тихую доустановку в активный venv (`sys.executable -m pip install`).
  - `log_startup()`: фиксирует все этапы запуска и полный трейсбек исключений в `logs/startup.log` **до** инициализации графической оболочки.
  - `show_native_error()`: в случае фатального падения до создания окна вызывает нативный диалог `MessageBoxW` с текстом ошибки и путем к логу запуска.
- **Обновлен лаунчер `launcher/HermesHub.cs`** и скомпилирован `launcher/HermesHub.exe`: генерируемый входной скрипт запускает приложение через `bootstrap_and_launch()`.
- **Оценка перехода на собственный venv**:
  - *Обоснование*: Оставлено единое окружение Hermes venv с механизмом самолечения (`launcher_bootstrap.py`), так как собственный venv потребовал бы дублирования 300+ МБ рантайма Python и усложнил интеграцию с CLI Hermes. Самолечение устраняет риск сноса пакетов при пересборке venv агентом.

---

## 2. Профили Claude и Grok во встроенной конфигурации и исправление мастера (P0-2)

- **Добавлены профили Claude и Grok**:
  - В [`src/antigravity_provider/router/router_config.py`](file:///E:/Agent%20projects/hermes-hub/src/antigravity_provider/router/router_config.py) и [`config/router_profiles.example.yaml`](file:///E:/Agent%20projects/hermes-hub/config/router_profiles.example.yaml) добавлены по 3 профиля: `claude-orch`, `claude-worker-1`, `claude-worker-2` и `grok-orch`, `grok-worker-1`, `grok-worker-2` (всего 22 профиля).
- **Исправление `AutoAssigner.find_free_slot`**:
  - Кандидаты строго фильтруются по наличию в `config.profiles`.
  - Если для провайдера нет свободных/неавторизованных слотов, метод возвращает `None` (а не несуществующий или занятый `candidates[0]`).
  - `AutoAssigner.recommend_assignment` при отсутствии слотов корректно возвращает пустой слот со статусом «Нет свободных слотов».
  - **Тест**: `test_auto_assigner_find_free_slot_for_all_five_providers` проверяет все 5 провайдеров.

---

## 3. Блокировка интерактивного входа при нажатии «Тест» (P0-3)

- **В `do_test_profile`** в `hermes_hub_app.py`: добавлена предварительная проверка `status.get("expired")`, которая сразу возвращает ошибку «Авторизация истекла, требуется повторный вход» без вызова адаптера.
- **В `AntigravityAdapter.invoke`**: добавлена проверка времени жизни токена (`tokens.get("expiry_date")`) перед запуском подпроцесса `agy`. При просрочке немедленно выбрасывается `AuthExpiredError`.
- **В окружение `agy_subprocess`**: добавлены флаги `BROWSER=none` и `CI=1`, исключающие интерактивный запуск браузера дочерними процессами.
- **Тесты**: `test_adapter_no_browser_on_expired_token` и `test_do_test_profile_no_browser_on_expired_token`.

---

## 4. Зеркальное развёртывание инсталлятора и манифест (P0-4)

- **В `installer/HermesHubSetup.cs`**:
  - Функция `CopyDirectoryRecursive` переведена на `MirrorDirectoryRecursive`: рекурсивно зеркалирует источник, удаляя устаревшие или мертвые файлы/каталоги в целевой папке (`pluginDst`), игнорируя `__pycache__` и `.pyc`.
  - При установке создается `deployment_manifest.json` с полями `version`, `deployed_at`, `git_commit`.
  - Скомпилирован `dist/HermesHubSetup.exe` и обновлен `dist/checksums.txt`.
- **В `installer/HermesHubSetup.py`**: также добавлено зеркальное копирование и запись `deployment_manifest.json`.
- **Тест**: `test_mirror_deployment_removes_deleted_files` подтверждает удаление исчезнувших из источника файлов.

---

## 5. Команда самопроверки `hermes router diag` (P0-5)

- В [`src/antigravity_provider/router/cli_commands.py`](file:///E:/Agent%20projects/hermes-hub/src/antigravity_provider/router/cli_commands.py) расширена команда `print_diagnostics_cli()`:
  1. Проверка зависимостей venv (`customtkinter`, `Pillow`, `psutil`, `pyyaml`).
  2. Проверка свежести развёрнутого плагина против версии приложения по `deployment_manifest.json`.
  3. Проверка валидности `router_profiles.yaml` (число профилей и ролей).
  4. Диагностическая матрица по всем профилям с маскированием идентичностей и источниками квот.
  5. Реальный тестовый вызов по одному профилю на каждого авторизованного провайдера.
  6. Однострочный вердикт: `[ВЕРДИКТ: ГОТОВ / ЧАСТИЧНО ГОТОВ / НЕ ГОТОВ]` с явным списком причин.
  7. Все секреты маскируются (`sk-...abcd`, `och***@domain`).
- **Тест**: `test_print_diagnostics_cli_output` проверяет структуру вывода и вердикта.

---

## 6. Результаты проверок

- **Headless pytest** (Python 3.8):
  `pytest -v` → **201 passed, 27 skipped, 3 deselected in 10.70s**
- **Full pytest** (Python 3.12):
  `& "C:\Users\trush\AppData\Local\Programs\Python\Python312\python.exe" -m pytest -v` → **201 passed, 27 skipped, 3 deselected in 10.54s**
- **Ruff linter**:
  `ruff check .` → **All checks passed!**
- **Release Gate**:
  `python scripts/release_gate.py` → **7/7 PASSED** (`[RELEASE GATE: PASSED] All criteria verified. Ready for Candidate v0.1.1`)
- **Live Update Feed**:
  `[MANIFEST_LIVE=True, PACKAGE_LIVE=True, PACKAGE_HASH_VERIFIED=True]` (sha256 `b5bbdea2a7a2157a26389266aab07ab3602bb00b4612065c48defec9d6fe909c`)
