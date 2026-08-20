# Hermes Hub

**Multi-Agent & Multi-Provider Control Hub for Hermes Agent**

Hermes Hub — централизованная панель управления и отказоустойчивый маршрутизатор запросов (Multi-Provider Router) для [Hermes Agent](https://hermes-agent.org/). Объединяет учетные записи различных провайдеров (**Google Antigravity**, **OpenAI Codex**, **OpenCode Go**, **DeepSeek**) в единую согласованную команду с автоматическим переключением при исчерпании квот (failover) и поддержкой сессионной привязки (Session Affinity).

---

## 🌟 Ключевые возможности

- 🖥️ **Нативное приложение Windows (CustomTkinter & Brandbook)**:
  - Фирменная дизайн-система **Obsidian Forest** (`#0F1510`, `#1A2A1F`, `#2F4A36`, `#F7F1E3`, `#CDAA64`).
  - Мгновенное переключение вкладок (**P95 < 200 ms**, в среднем ~30 ms).
  - Полноценная интеграция с панелью задач Windows через `AppUserModelID` (`HermesHub.Desktop`) и multi-resolution `.ico`.
- 👥 **Команда агентов (Team View)**:
  - 6 логических ролей («Главный оркестратор», «Кодер», «Ревьюер», «Исследователь», «Тестировщик», «Агент общего назначения»).
  - Реальные логотипы провайдеров с динамическим кэшированием.
  - Четкое разделение флагов **MAIN Hermes Account** и **Primary Orchestrator**.
- 🔀 **Многоуровневый Failover & Маршрутизация**:
  - Визуальные пайплайны маршрутизации со статусами узлов в реальном времени.
  - Автоматический failover цепочки `Codex -> Antigravity -> OpenCode Go` при квотных ограничениях (HTTP 429 / Quota Exceeded).
- 🛡️ **Строгий Status Resolver & Unified Health**:
  - Неподключенные слоты отображаются как `NOT_CONFIGURED` («Аккаунт не добавлен») и никогда не показывают ложных `QUOTA_EXHAUSTED` или `HEALTHY`.
  - Автоматическая очистка устаревших квотных записей при удалении credentials.
- 💼 **Cockpit Tools Accounts View**:
  - Верхний тулбар: Поиск, фильтры (Подключенные, Требуется вход, Квота), сортировка.
  - Компактный блок свободных слотов без визуального шума.
  - 4-шаговый мастер добавления аккаунтов (Wizard).
- ⚙️ **Архитектурные модули (Roadmap P0, P1, P2)**:
  - `LifecycleSupervisor`: Реестр процессов с контролем владения по UUID и PID, исключающий использование `killall` / `taskkill`.
  - `PolicyEnforcer`: `WebPolicy` (ограничение исходящих доменов, блокировка метаданных) и `ToolPolicy` (валидация команд).
  - `UnifiedSkillRegistry`: Межпровайдерный реестр навыков.
  - `CapabilityMatrix`: Ранжирование моделей по контексту, рассуждениям и инструментам.
  - `ScheduledTaskSafetyCoordinator`: Защита периодических задач (`overlap_policy: skip`).
- 📦 **Windows Installer (`HermesHubSetup.exe`)**:
  - Обязательная pre-flight проверка наличия установленного Hermes Agent.
  - Автоматическое создание ярлыков на Рабочем столе и в Главном меню с `AppUserModelID`.

---

## 🚀 Быстрый старт

### Запуск из исходного кода
```powershell
# Установка зависимостей
uv sync

# Запуск приложения Hermes Hub
uv run python -m antigravity_provider.router.hermes_hub_app
```

### Запуск тестов и верификации
```powershell
# Полный набор автоматических тестов (35 тестов)
uv run pytest -v tests/

# Комплексная проверка роутера (10 проверок)
python scripts/verify_multi_provider_router.py
```

---

## 🏗️ Структура проекта

| Каталог | Назначение |
|---|---|
| `src/antigravity_provider/router/` | Ядро Multi-Provider Router и Native GUI |
| `src/antigravity_provider/router/ui/` | Дизайн-система, компоненты и экраны (Views) |
| `src/antigravity_provider/router/supervisor/` | Lifecycle Supervisor и политики безопасности (WebPolicy/ToolPolicy) |
| `src/antigravity_provider/router/skills/` | Унифицированный реестр навыков |
| `src/antigravity_provider/router/capability/` | Матрица возможностей моделей и DeepSeek адаптер |
| `src/antigravity_provider/router/scheduler/` | Координатор безопасности запланированных задач |
| `assets/` | Фирменные логотипы, иконки провайдеров и .ico |
| `installer/` | Инсталлятор `HermesHubSetup.py` с проверкой Hermes Agent |
| `tests/` | Автоматизированные тесты pytest |
| `docs/` | Архитектура, гайдлайны бренда, безопасность и производительность |

---

## 📄 Лицензия
MIT License. Hermes Hub is an open-source component of the Hermes Agent ecosystem.
