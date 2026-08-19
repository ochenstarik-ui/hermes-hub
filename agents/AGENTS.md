# Правила работы агентов — Hermes Hub

Документ описывает правила разработки и поддержки самостоятельного репозитория `hermes-hub`.

## 1. Границы задачи
Hermes Hub является автономным проектом (Source of Truth). Изменения логики маршрутизации, UI, адаптеров провайдеров и лаунчера производятся исключительно здесь.

## 2. Безопасность учетных данных (Security Invariants)
В репозиторий запрещено коммитить реальные учетные данные пользователей (`auth.json`, токены, API-ключи, Credential Manager экспорты, персональные пути). Для шаблонов конфигурации используется `config/router_profiles.example.yaml`.

## 3. Разделение Source и Runtime
- **Source of Truth:** `E:\Agent projects\hermes-hub`
- **Installed App:** `%LOCALAPPDATA%\Programs\HermesHub\`
- **Hermes Plugin:** `%LOCALAPPDATA%\hermes\plugins\antigravity-provider\`
- **User Data:** `%LOCALAPPDATA%\hermes\` (сохраняется при обновлениях и обычном удалении).

## 4. Проверка и верификация
Любые изменения валидируются через детерминированные тесты:
- `pytest tests/test_multi_provider_router.py`
- `python scripts/verify_multi_provider_router.py`
- `HermesHubSetup.exe /silent` (проверка кодов возврата 0, 10, 11, 12).
