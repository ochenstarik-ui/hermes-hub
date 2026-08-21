# Hermes Hub — редизайн по утверждённому макету B5

Дата: 2026-08-21

Ветка: `codex/mockup-redesign`

BASE_SHA: `69cbefcab6d566929d99b7ad7dc1b6b9824bfb2b` (`origin/main`, обновлён перед финальной интеграцией)

FINAL_SHA: `git rev-parse codex/mockup-redesign` в момент handoff. Точный SHA указан в итоговом сообщении, поскольку commit не может содержать собственный SHA.

## Реализовано

- Один утверждённый layout для трёх схем: `dark`, `hybrid`, `light`.
- Все палитры находятся в `theme.py`, имеют одинаковый набор токенов и меняют всё окно после сохранения настройки.
- Выбор темы сохраняется в `hub_settings.json`; приложение применяет его при следующем запуске.
- Общий каркас соответствует макету: брендовая левая панель, прокручиваемая навигация, пользователь и версия снизу, глобальная верхняя строка с состоянием, `Ctrl + K`, добавлением аккаунта и служебными действиями.
- Dashboard: пять компактных KPI, провайдеры → оркестратор → роли, правая панель состояния, реальные события снизу.
- После обновления контракта подключены реальные доли/число вызовов и P50 по провайдерам, вызовы по ролям, active calls и локальные CPU/RAM/disk/network.
- Добавлены отдельные вкладки «Квоты и лимиты» и «Аналитика» на данных `HubSnapshot`/`TelemetryService`.
- Журнал получает реальные события через action layer приложения, поддерживает поиск и фильтр уровня.
- На «Аккаунты» возвращены `test`, `set_main`, `set_orchestrator`, `assign_role`; механический и фактический UI-тесты проверяют все четыре триггера.
- Сохранена keyed-дельта карточек и квотных корзин.
- Цветовые литералы вне `theme.py` удалены; отдельный тест запрещает их повторное появление.

## Изменённые файлы

- `src/antigravity_provider/router/hermes_hub_app.py`
- `src/antigravity_provider/router/ui/theme.py`
- `src/antigravity_provider/router/ui/components.py`
- `src/antigravity_provider/router/ui/assets.py`
- `src/antigravity_provider/router/ui/add_account_wizard.py`
- `src/antigravity_provider/router/ui/views/dashboard_view.py`
- `src/antigravity_provider/router/ui/views/logs_view.py`
- `src/antigravity_provider/router/ui/views/settings_view.py`
- `src/antigravity_provider/router/ui/views/team_view.py`
- `src/antigravity_provider/router/ui/views/analytics_view.py`
- `src/antigravity_provider/router/ui/views/quotas_view.py`
- `tests/test_ui_mockup_redesign.py`
- `tests/test_ui_screenshot_harness.py`
- `artifacts/mockup-redesign/*.png`
- `CODEX_MOCKUP_REDESIGN_REPORT.md`

Backend/state/adapters, installer, scripts, config, legacy и чужие тесты не изменялись.

## Проверка размеров и scaling

Проверены `1280×720`, `1366×768`, `1920×1080`. На наименьшем размере дополнительно проверены 100%, 125% и 150% widget scaling. Правая граница поиска и кнопки добавления оставалась внутри верхней строки:

```text
scale 1.00: search_right=539, add_right=1074, header_width=1090
scale 1.25: search_right=661, add_right=1023, header_width=1043
scale 1.50: search_right=781, add_right=971,  header_width=995
```

Навигация помещена в прокручиваемую область, поэтому нижние разделы доступны при 150%.

## Скриншоты — все вкладки и темы

| Вкладка | Тёмная | Гибрид | Светлая |
|---|---|---|---|
| Обзор | [dark](artifacts/mockup-redesign/overview-dark.png) | [hybrid](artifacts/mockup-redesign/overview-hybrid.png) | [light](artifacts/mockup-redesign/overview-light.png) |
| Команда | [dark](artifacts/mockup-redesign/team-dark.png) | [hybrid](artifacts/mockup-redesign/team-hybrid.png) | [light](artifacts/mockup-redesign/team-light.png) |
| Аккаунты | [dark](artifacts/mockup-redesign/accounts-dark.png) | [hybrid](artifacts/mockup-redesign/accounts-hybrid.png) | [light](artifacts/mockup-redesign/accounts-light.png) |
| Маршрутизация | [dark](artifacts/mockup-redesign/routing-dark.png) | [hybrid](artifacts/mockup-redesign/routing-hybrid.png) | [light](artifacts/mockup-redesign/routing-light.png) |
| Провайдеры | [dark](artifacts/mockup-redesign/providers-dark.png) | [hybrid](artifacts/mockup-redesign/providers-hybrid.png) | [light](artifacts/mockup-redesign/providers-light.png) |
| Квоты | [dark](artifacts/mockup-redesign/quotas-dark.png) | [hybrid](artifacts/mockup-redesign/quotas-hybrid.png) | [light](artifacts/mockup-redesign/quotas-light.png) |
| Аналитика | [dark](artifacts/mockup-redesign/analytics-dark.png) | [hybrid](artifacts/mockup-redesign/analytics-hybrid.png) | [light](artifacts/mockup-redesign/analytics-light.png) |
| Состояние | [dark](artifacts/mockup-redesign/health-dark.png) | [hybrid](artifacts/mockup-redesign/health-hybrid.png) | [light](artifacts/mockup-redesign/health-light.png) |
| Журнал | [dark](artifacts/mockup-redesign/logs-dark.png) | [hybrid](artifacts/mockup-redesign/logs-hybrid.png) | [light](artifacts/mockup-redesign/logs-light.png) |
| Настройки | [dark](artifacts/mockup-redesign/settings-dark.png) | [hybrid](artifacts/mockup-redesign/settings-hybrid.png) | [light](artifacts/mockup-redesign/settings-light.png) |
| О программе | [dark](artifacts/mockup-redesign/about-dark.png) | [hybrid](artifacts/mockup-redesign/about-hybrid.png) | [light](artifacts/mockup-redesign/about-light.png) |

## Расхождения с макетом

| Элемент макета | Реализация и причина |
|---|---|
| «Квота сегодня 78%» | Показано `Н/Д`, пока нет хотя бы одной реально измеренной корзины. Baseline `None` не превращается в процент. |
| «Активные задачи 24» | Заменено на реальные вызовы роутера из telemetry. Подсистемы задач/очередей нет. |
| «Окно обслуживания 09:00–21:00» | Заменено количеством реальных failover-переключений. Понятия окна обслуживания нет. |
| Доли провайдеров 45/35/20% и 128/74/56 запросов по ролям | Показываются только из реального `metrics.telemetry.by_provider/by_role`; без вызовов отображаются online/`Н/Д`, а не цифры макета. |
| Латентность каждого провайдера | Показывается реальный P50 из `by_provider`; без измерений значение скрыто. |
| CPU, память, диск, сеть | Показываются реальные локальные измерения `psutil`; при недоступном `psutil` — `Н/Д`. |
| Очереди задач | Блок исключён: подсистемы очередей в продукте нет. |
| Раздел «Инциденты» | Не создан: вместо него используется реальный журнал с фильтром ошибок. |
| Кривые соединения | В native CustomTkinter используются адаптивные направленные связи между тремя колонками; данные и порядок цепочки сохранены без canvas-зависимости. |
| Версия `2.8.1` на макете | Показывается реальная версия пакета `0.1.1`. |

## Проверки

### Headless без UI-зависимостей

```powershell
uv run --isolated --no-project --with pytest --with pyyaml --with pydantic --with requests --with httpx --with psutil python -m pytest -q
```

Результат: `193 passed, 26 skipped, 3 deselected in 14.32s`.

### UI-enabled

Из-за известной повторной инициализации Tcl/Tk набор выполнен в трёх свежих процессах:

```powershell
uv run --extra dev python -m pytest -q --ignore=tests/test_ui_phase2_6.py --deselect=tests/test_oauth_lifecycle.py::test_f_copy_before_open_browser
uv run --extra dev python -m pytest -q tests/test_ui_phase2_6.py
uv run --extra dev python -m pytest -q tests/test_oauth_lifecycle.py::test_f_copy_before_open_browser
```

Результаты: `243 passed, 2 skipped, 4 deselected`; `4 passed`; `1 passed`. Итог уникального набора: `248 passed, 2 skipped, 3 deselected`, ошибок нет.

### Статика и release gate

```powershell
uv run ruff check .
uv run --extra dev python scripts/release_gate.py
```

Результат: Ruff — `All checks passed!`; release gate — `PASSED`, публичный package и hash подтверждены.

## Backend gaps

1. Внешние provider RPS/SLA, task queues и maintenance windows отсутствуют в продукте; UI их не синтезирует.
2. Baseline-квоты остаются `None`; реальное число появляется только из provider claim/runtime event.
3. `HubSnapshot` не содержит журнал событий; app action layer передаёт в views безопасные presentation-объекты из `EventLogService`, сами views backend не читают.
4. Network contract содержит накопительные bytes с момента загрузки ОС, а не мгновенную скорость; UI показывает объём, не выдуманный Мбит/с.
5. Тег `v0.1.1`, release и manifest не создавались и не изменялись.
