# Задание: Hermes Hub — Product Stabilization + Native Windows UX v3 + GitHub + Architecture Roadmap

## Дата поступления
2026-08-20

## Область задачи (Scope)
1. **GitHub & Security Baseline**:
   - Инициализация git-репозитория `E:\Agent projects\hermes-hub`.
   - Настройка строгого `.gitignore` (исключение токенов, `auth.json`, ключей, логов, кэшей).
   - Repository-wide Security Audit.
   - Создание приватного репозитория `hermes-hub` на GitHub и первый push.
2. **Product Stabilization & Performance**:
   - Ликвидация задержек при переключении вкладок (P95 < 200 ms, без I/O, без сетевых запросов).
   - Устранение дерганий при движении/resize окна (кэширование иконок, дебаунс).
   - Строгий Status Resolver: неподключенный аккаунт -> `NOT_CONFIGURED` («Аккаунт не добавлен»), очистка устаревших квот, отсутствие `QUOTA_EXHAUSTED` / `HEALTHY` на пустых слотах.
   - Человекочитаемые подписи статусов на русском языке.
3. **Windows App Identity & Taskbar Integration**:
   - Установка стабильного `AppUserModelID` (`HermesHub.Desktop`).
   - Использование фирменного multi-resolution `.ico` для taskbar, title bar, Alt+Tab, Start Menu.
   - Исключение появления иконки Python при закреплении на панели задач.
4. **Provider Icons & Visual System**:
   - Интеграция официальных иконок провайдеров (Google Antigravity, OpenAI Codex, OpenCode Go) из предоставленных ассетов в `assets/providers/`.
   - Увеличенная читаемая типографика (14-16px body, 18-20px titles).
   - Качественный Sidebar с однородными иконками и аккуратный Header.
5. **Accounts View (Уровень Cockpit Tools)**:
   - Верхний Toolbar: Поиск, фильтры (Все, Подключенные, Требуется вход, Квоты, Провайдеры), сортировка, добавление.
   - Компактные информативные карточки подключенных аккаунтов.
   - Сводный блок свободных слотов без визуального шума.
6. **Team View & Routing & Health & Settings**:
   - 6 логических ролей в Team View, разделение флагов MAIN Hermes Account и Primary Orchestrator.
   - Визуальный пайплайн failover в Routing View.
   - Компактная диагностика в Health View (пустые слоты никогда не здоровы).
   - Интерактивные переключатели и сворачиваемый Advanced раздел в Settings View.
7. **Graceful Shutdown**:
   - Координатор остановки процессов, таймеров и воркеров без зомби-процессов.
8. **Архитектурный Roadmap (P0 -> P1 -> P2)**:
   - P0: Lifecycle Supervisor с Process Registry (владение процессами без `killall`), Lease/TTL, Heartbeat, WebPolicy, ToolPolicy, аудит.
   - P1: Unified Skill Registry, Provider Capability Matrix, DeepSeek Responses API адаптер.
   - P2: Scheduled Task Safety (overlap_policy: skip).
9. **Installer**:
   - Инсталлятор `HermesHubSetup.exe` с обязательной проверкой наличия установленного Hermes Agent.
10. **Тестирование, Документация и Отчётность**:
    - Unit, Integration, Performance и Windows тесты.
    - Обновление всей документации.
    - Атомарные коммиты в GitHub.
    - Итоговый подробный отчет в `agents/done/`.
