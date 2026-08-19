# Руководство по установке Hermes Hub

## 1. Системные требования
- **ОС:** Windows 10/11 x64 (или Linux/macOS с CLI запуском).
- **Hermes Agent:** Установлен и настроен (проверенная версия: `0.20.4`, минимальная: `0.20.0`).
- **Python:** 3.10 – 3.12 в составе виртуального окружения Hermes Agent.
- **Браузер:** Microsoft Edge (для Windows App Mode) или любой современный браузер.

---

## 2. Установка через Windows Setup (`HermesHubSetup.exe`)

1. Скачайте `HermesHubSetup.exe` из раздела релизов или соберите с помощью `installer/build_installer.ps1`.
2. Запустите `HermesHubSetup.exe`.
3. Установщик автоматически:
   - Проверит наличие Hermes Agent (`%LOCALAPPDATA%\hermes`).
   - Проверит версию Hermes по `compatibility.json`.
   - Установит приложение в `%LOCALAPPDATA%\Programs\HermesHub\`.
   - Интегрирует плагин в `%LOCALAPPDATA%\hermes\plugins\antigravity-provider\`.
   - Создаст ярлык `Hermes Hub` в меню «Пуск».
   - Зарегистрирует запись для удаления в «Установка и удаление программ».
4. Нажмите «Запустить Hermes Hub».

### Автоматическая (тихая) установка (Unattended Mode)

Для скриптов автоматизации и процедур восстановления доступен тихий режим:

```powershell
.\HermesHubSetup.exe /silent
```

#### Коды возврата установщика:
- `0` — Успешная установка.
- `10` — Hermes Agent не найден на целевой машине.
- `11` — Несовместимая версия Hermes Agent.
- `12` — Ошибка пост-установочной верификации файлов.

---

## 3. Установка через PowerShell-скрипты

```powershell
# Установка / развертывание
.\scripts\install.ps1

# Обновление без сброса учетных данных
.\scripts\update.ps1

# Удаление (с сохранением пользовательских профилей)
.\scripts\uninstall.ps1

# Полное удаление с очисткой данных
.\scripts\uninstall.ps1 -PurgeUserData
```
