# Задание: расширить Hermes Hub — аккаунты, тарифы, квоты, Claude и Grok

## Цель

1. Показывать реальный email/identity подключенного аккаунта.
2. Показывать тариф аккаунта: FREE / PLUS / PRO / ULTRA / MAX / TEAM / BUSINESS (UNKNOWN если неизвестен, не выдумывать FREE).
3. Разделять квоты на QuotaSnapshot и QuotaBucket с процентами, абсолютными лимитами, reset times.
4. Разделить Claude и Gemini quota в Antigravity (исчерпание Claude не блокирует Gemini).
5. Поддержать same-account model fallback в Router.
6. Добавить Claude как полноценного провайдера (OAuth PKCE, API Key, identity, plan, session/weekly quota, router adapter).
7. Добавить Grok как полноценного провайдера (OAuth Device Code, API Key, identity, plan, weekly/chat/build/tasks quota buckets, router adapter).
8. Поддержать OpenCode Go и Codex многобакетный учет квот.
9. Обновить карточки аккаунтов, экран «Команда» и мастер подключения.
10. Фоновое автообновление квот вне UI mainloop.
