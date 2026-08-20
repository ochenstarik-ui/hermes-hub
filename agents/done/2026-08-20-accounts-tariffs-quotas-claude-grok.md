# Отчет о выполнении: расширение Hermes Hub — аккаунты, тарифы, квоты, Claude и Grok

## 1. Выполненные задачи

- **Унифицированная модель Identity & Plans** (`src/antigravity_provider/router/account_identity.py`):
  - Приоритет разрешения идентичности: `email -> display_name -> account_id -> profile_id`.
  - Безопасное маскирование персональных данных.
  - Тарифы: `SubscriptionPlan` с кодами FREE, PLUS, PRO, ULTRA, MAX, TEAM, BUSINESS, SUPERGROK, GROK PRO. При отсутствии данных отображается «Тариф: неизвестен» (без ложного FREE).

- **Многобакетная система квот** (`QuotaBucket`, `QuotaSnapshot`, `AccountQuotaService`):
  - Точные проценты «Осталось X%» vs «Использовано Y%».
  - Поддержка абсолютных лимитов (напр. задачи Grok `0/10`, `0/30`).
  - Форматирование времени сброса (`Сброс через Xч Yмин`).
  - Полная изоляция квот Claude и Gemini в Antigravity: исчерпание квоты Claude не блокирует запросы Gemini на том же профиле.
  - Мгновенная фиксация runtime quota ошибок (429/overloaded).

- **Same-Account Model Fallback в RouterEngine**:
  - При исчерпании выбранной модели на профиле роутер пробует переключиться на альтернативную совместимую модель того же аккаунта (например, с Claude на Gemini) до прыжка на другой профиль.

- **Интеграция Claude (Anthropic)**:
  - OAuth 2.0 PKCE менеджер (`claude_oauth.py`) с ручным вводом кода/токена.
  - Claude Messages API адаптер (`claude_adapter.py`) с поддержкой OAuth Bearer и API Key (`sk-ant-...`).
  - Квоты: сессионная (5h), недельная, Opus/Sonnet.

- **Интеграция Grok (xAI)**:
  - Device Code OAuth менеджер (`grok_oauth.py`) с ручным вводом токена.
  - Grok Chat Completions API адаптер (`grok_adapter.py`) с поддержкой OAuth Bearer и API Key (`xai-...`).
  - Квоты: weekly, chat, build, частые задачи (10), обычные задачи (30).

- **Обновление UI**:
  - 5 вкладок в «Аккаунты» (Antigravity, OpenAI Codex, OpenCode Go, Claude, xAI Grok).
  - Бейджи тарифов, карточки многобакетных квот с прогресс-барами и временем сброса.
  - Кнопки одиночного обновления `[↻]` и полного обновления `[↻ Обновить все]`.
  - Настройка интервала фонового автообновления квот (Выкл, 1м, 5м, 10м, 30м) в Настройках, работающая в фоновом потоке без блокировки mainloop.
  - Обновленный экран «Команда» и мастер «Добавить аккаунт» для всех 5 провайдеров.

## 2. Результаты тестирования

- **Pytest**: 86 passed, 4 skipped, 3 deselected (100% прохождение всех unit и integration тестов, включая 16 новых тестов в `test_accounts_tariffs_quotas.py`).
- **Release Gate**: Все 7 критериев успешно пройдены (`[RELEASE GATE: PASSED]`).
