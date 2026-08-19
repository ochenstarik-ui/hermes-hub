# Hermes Hub

**Multi-Agent & Multi-Provider Control Hub for Hermes Agent**

Hermes Hub — централизованная панель управления и отказоустойчивый маршрутизатор запросов (Multi-Provider Router) для [Hermes Agent](https://hermes-agent.org/). Позволяет объединить учетные записи различных провайдеров (**OpenAI Codex**, **Google Antigravity**, **OpenCode Go**) в единую отказоустойчивую команду с автоматическим переключением при исчерпании квот (failover) и поддержкой диалогового контекста (Session Affinity).

---

## 🌟 Ключевые возможности

- 👥 **Визуальная панель «Команда Hermes»**: Управление ролями агентов («Главный оркестратор», «Кодер 1», «Кодер 2», «Ревьюер», «Исследователь», «Быстрый агент», «Резерв»).
- 🔀 **Многоуровневый Failover**: Бесшовное переключение цепочки провайдеров `Codex -> Antigravity -> OpenCode Go` при квотных ограничениях (HTTP 429 / Quota Exceeded).
- 🧠 **Auto Assignment Engine**: Автоматический подбор свободных слотов при подключении новых аккаунтов и защита от дубликатов.
- ⚡ **Session Affinity**: Сохранение используемого профиля и модели на протяжении диалоговой сессии без случайных скачков контекста.
- 🔐 **Безопасная изоляция профилей**: Раздельные профили окружения и хранилища учетных данных (`auth.json`), маскирование email и API-ключей.
- 💻 **Нативный лаунчер (`HermesHub.exe`)**: Windows App Mode на базе Microsoft Edge с проверкой готовности бэкенда (HTTP 200 health check gate).
- 📦 **Полноценный Windows Installer (`HermesHubSetup.exe`)**: Мастер установки с pre-flight проверкой Hermes 0.20.4+, тихим режимом `/silent`, поддержкой обновления и безопасного удаления.

---

## 🚀 Быстрый старт

### Вариант 1: Установка через Windows Installer
Скачайте и запустите `HermesHubSetup.exe`:
```powershell
# Интерактивный графический мастер:
.\HermesHubSetup.exe

# Автоматический тихий режим:
.\HermesHubSetup.exe /silent
```

### Вариант 2: Установка через PowerShell
```powershell
.\scripts\install.ps1
```

После установки ярлык **Hermes Hub** появится в меню «Пуск».

---

## 🏗️ Архитектура системы

| Компонент | Расположение | Назначение |
|---|---|---|
| **Source of Truth** | `E:\Agent projects\hermes-hub` | Репозиторий исходного кода |
| **Installed Application** | `%LOCALAPPDATA%\Programs\HermesHub\` | Исполняемые файлы (`HermesHub.exe`, скрипты) |
| **Plugin Integration** | `%LOCALAPPDATA%\hermes\plugins\antigravity-provider\` | Пакет роутера и адаптеров провайдеров |
| **User Runtime & Auth** | `%LOCALAPPDATA%\hermes\` | Пользовательские авторизации и настройки |

---

## 🧪 Тестирование и верификация

```powershell
# Запуск полного набора unit/integration тестов
uv run pytest tests/test_multi_provider_router.py -v

# Запуск скрипта автоматической верификации роутера
python scripts/verify_multi_provider_router.py
```

---

## 📄 Лицензия

Проект распространяется под лицензией [MIT](LICENSE).
