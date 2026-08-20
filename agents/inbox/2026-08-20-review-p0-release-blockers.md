# Ревью: `2a97e80` + `7926de9` (закрытие P0 и релизный конвейер)

**Ревьюер:** Claude (роль «Ревьюер»)
**База:** `5ccfd48` → **проверено:** `7926de9`
**Метод:** построчный разбор диффа + исполняемая проверка каждого утверждения в изолированном `HERMES_HOME`

**Вердикт: ⚠️ Принять нельзя — 4 блокирующих замечания.** Из 9 P0 фактически закрыто 8; один закрыт с регрессией. Дополнительно найдено 4 дефекта в новом коде.

---

## 1. Подтверждено закрытым (проверено исполнением)

| P0 | Проверка | Итог |
|---|---|---|
| №2 `get_profile_dir` | `hasattr(ProfileAuthManager,'get_profile_dir')` → `True`, поддержаны обе сигнатуры | ✅ |
| №3 `json` в мастере | импорт присутствует, `_save_key` отрабатывает | ✅ |
| №4 `auto_assign_all` | метод существует, выполняется | ✅ (см. B2) |
| №6 статусы OAuth | `("error","failed","cancelled")` + `"timeout"` — `add_account_wizard.py:265` | ✅ |
| №7 `assign_role` | обработчик + модалка `hermes_hub_app.py:408,419` | ✅ |
| №8 роль из шага 4 | вызывается `assign_profile_to_role` | ✅ (см. B2) |
| №9 валидация ключа | реальные `verify_codex_token` / `verify_opencode_token`, честная метка «НЕ ПРОВЕРЕН» | ✅ |
| №1 зависимости UI | `HermesHubSetup.py:52` ставит пакеты в venv Hermes + проверка импорта. Пины `customtkinter>=6.0.0`, `pillow>=12.3.0` сверены с PyPI — версии существуют | ✅ |

**Сверх P0 — зачтено:** единая версия `0.1.1` (`version.py` → pyproject → compatibility.json → About); `paths.py` вместо пяти реализаций резолвинга и захардкоженного `E:/Agent projects`; сброс `overall_state` по истечении cooldown (проверено: `overall=healthy` при `family=quota-exhausted`, после истечения — оба healthy); типизированные исключения вместо угадывания по подстрокам на уровне роутера; `conftest.py` с изоляцией `HERMES_HOME` (проверено — работает); маркеры pytest и `addopts` с отключением `installer/live/network`; CI и `release_gate.py`.

**Тесты:** `41 passed, 1 failed, 3 deselected`. Единственный failed — `test_p0_1_installer_dependencies`, потому что в venv Hermes на этой машине `customtkinter` ещё не установлен (установщик не запускался). Регрессионный тест на failover `test_p0_5_antigravity_failover_on_quota` присутствует и проходит.

---

## 2. Блокирующие замечания

### B1. Регрессия: не-роутерный путь падает с `IndexError`

`agy_subprocess.py:584` теперь возвращает `{"error": {...}}` без `choices`. Для роутера это правильно, но `_error_completion` обслуживает **два** пути, а `hermes_plugin.py` не менялся.

Путь 2 (`hermes_plugin.antigravity_llm_execution`, когда роутер отключён `config.enabled=false` или выбросил исключение):
```
completion = agy_generate(request)          # -> {"error": {...}}
return openai_completion_object(completion) # -> choices = []
```

Проверено исполнением:
```
после openai_completion_object: choices = []
обращение Hermes к choices[0]: IndexError: list index out of range
```

Было: пользователь видел текст ошибки как ответ ассистента. Стало: падение транспорта Hermes.

**Требуется:** обработать `{"error": …}` в `antigravity_llm_execution` — либо конвертировать в completion с текстом ошибки, либо пробрасывать типизированное исключение. Тест на путь с `enabled=false` обязателен.

---

### B2. `assign_profile_to_role` создаёт фиктивные роли и не меняет реальные

`auto_assigner.py:assign_profile_to_role` вызывает `config.get_role_policy(role_name)`, а тот для неизвестной роли возвращает **generic-политику с `preferred_chain = list(self.profiles.keys())`** — все 16 профилей. Результат сохраняется в конфиг.

При этом `auto_assign_all` раздаёт роли из списка `["orchestrator","coder","reviewer","researcher","tester","general"]`, а мастер — `coder/researcher/general/spare`. Реальные роли роутера: `orchestrator`, `coder-primary`, `coder-secondary`, `reviewer`, `research`, `fast`. Совпадают только `orchestrator` и `reviewer`.

Проверено в изолированном окружении:
```
роли ДО   : [coder-primary, coder-secondary, fast, orchestrator, research, reviewer]
роли ПОСЛЕ: [coder, coder-primary, coder-secondary, fast, orchestrator, research, reviewer]

длина цепочки роли coder : 16
цепочка coder            : [ag-w1, codex-orch, ..., ag-cold-1, ag-cold-2, ag-cold-3, opengo-1, ...]
цепочка coder-primary    : [codex-worker-1, ag-w1, opengo-3]   <- НЕ ИЗМЕНИЛАСЬ
```

Итог: назначение роли не влияет на маршрутизацию, а конфиг засоряется мусорными ролями с цепочками из 16 профилей, включая отключённые холодные резервы.

`test_p0_4` и `test_p0_7` этого не ловят, потому что проверяют механику («выполнилось без `AttributeError`», «цепочка изменилась и сохранилась»), а не семантику — что имя роли маршрутизируемое.

**Требуется:** маппинг человекочитаемых имён на реальные (`coder` → `coder-primary`, `researcher` → `research`, `tester`/`general` → `fast` или отдельная роль), отказ при неизвестной роли, и запрет на persist generic-политики со всеми профилями. В тесты — проверка, что `role_name in config.roles` **до** назначения.

---

### B3. Каждое назначение роли уничтожает пользовательский YAML

`save_router_config` пишет схему, отличную от шаблона. Раньше это срабатывало редко, теперь — при **каждом** подключении аккаунта через мастер и при каждом `auto_assign_all`.

Проверено на копии `config/router_profiles.example.yaml`:
```
шаблон:                        5 строк комментариев, блок router: 1
после одного назначения роли:  0 строк комментариев, блок router: 0
```

Блок `router:` (`max_failover_attempts`, `cooldown_base_seconds`, `cooldown_max_seconds`, `session_affinity_ttl_seconds`) загрузчиком и так игнорируется — но пользователь, отредактировавший его, молча теряет правки.

**Требуется:** либо привести `load/save` к одной схеме и покрыть тестом round-trip (`load → save → load` без потерь), либо перейти на редактирование с сохранением структуры.

---

### B4. Rate limit классифицируется как исчерпание квоты — 30 минут вместо 60 секунд

`antigravity_adapter.py:invoke` — первая ветка ловит `("quota","resource_exhausted","429","limit","exhausted")`, ветка `"rate"` идёт **после** и для реального 429 недостижима: сообщение «429 Too Many Requests: rate limit exceeded» содержит и `429`, и `limit`.

Проверено исполнением:
```
вход : Antigravity error: agy error: 429 Too Many Requests: rate limit exceeded
итог : QuotaExceededError -> category=quota-exhausted cooldown=1800s
```

Профиль паркуется на 30 минут вместо 60 секунд. При цепочке из трёх профилей серия временных 429 выводит роль в «Failover Exhausted».

**Требуется:** проверять `rate`/`too many requests`/`429` **до** квотной ветки, либо различать по коду ответа, а не по подстроке.

---

## 3. Существенные замечания (не блокируют, но лучше в этом же заходе)

**S1. Потеряно время сброса квоты.** Типизированные исключения обрабатываются в начале `classify_error` и используют `exc.reset_in_sec or 1800`, но `reset_in_sec` при выбросе в `invoke` не заполняется. Regex-разбор («resets in 2h» → 7200 s) остался ниже и для типизированных исключений недостижим. Проверено: «individual quota reached, resets in 2h» → `cooldown=1800s`. Раньше было 7200. Прокидывайте распарсенную длительность в конструктор исключения.

**S2. Встроенный апдейтер нерабочий.** `update_manager.py:82` тянет манифест с `raw.githubusercontent.com/ochenstarik-ui/hermes-hub/main/dist/update_manifest.json`. Файл не отслеживается git (`dist/` в `.gitignore`), репозиторий приватный. Проверено: `HTTP 404`. Проверка обновлений всегда будет падать. Нужен публичный канал (GitHub Releases API) или отдельная ветка/репозиторий манифестов.

**S3. Апдейтер проверяет целостность, но не подлинность.** SHA-256 берётся из того же манифеста, что и `package_url`, — при подмене манифеста хеш подменяется вместе с пакетом. Плюс `HERMES_HUB_UPDATE_URL` переопределяется переменной окружения, а `package_url` скачивается без allowlist хостов. Для механизма, который распаковывает код в рабочий каталог и затем исполняется, нужна подпись пакета либо жёсткая привязка к домену релизов. (`extractall` от Zip Slip защищён — CPython нормализует пути, здесь претензий нет.)

**S4. `release_gate.check_security_zero_secrets` даёт ложное «0 секретов».** Проверка ищет отслеживаемые **файлы**-секреты и не видит `CLIENT_SECRET` в `oauth.py:28`, склеенный из фрагментов строк специально для обхода сканеров. Гейт будет зелёным при наличии секрета в коде.

**S5. `py_compile` по `dest.rglob("*.py")`** (`update_manager.py:194`) пройдёт по `.venv`, если апдейт применяется к каталогу разработки, — это тысячи файлов и вероятные ложные сбои с откатом. Ограничьте обход каталогом `src`.

**S6. Настройки по-прежнему не сохраняются.** Ни один `CTkSwitch`/`CTkOptionMenu` в `settings_view.py` (строки 78, 87, 96, 116, 124) не имеет `command=`/`variable=`, `_save_settings()` пишет неизменённый словарь дефолтов. Кнопка «💾 Сохранить» ничего не сохраняет. В отчёте это заявлено как «интерактивные переключатели» — расхождение.

**S7. `test_installer` всё ещё меняет систему.** Песочница через `LOCALAPPDATA`/`HERMES_HOME` в env закрывает файловое дерево, но `CreateStartMenuShortcut` пишет в `%APPDATA%\...\Start Menu`, а `RegisterInWindowsUninstall` — в `HKCU`. Ни то, ни другое не перенаправляется. Смягчено маркером `installer` и `addopts`, но при `-m installer` система снова будет изменена.

**S8. Отсутствие UI-зависимости роняет весь прогон.** `test_ui_refinement.py:11` импортирует `hermes_hub_app` на уровне модуля → `ModuleNotFoundError: customtkinter` прерывает сбор всей сессии («Interrupted: 1 error during collection»), а не пропускает один модуль. Нужен `pytest.importorskip("customtkinter")`.

**S9. Мастер не останавливает опрос при закрытии окна.** `_polling_active` сбрасывается только при переходе на шаг 3 (`add_account_wizard.py:279`). Закрытие модалки во время OAuth оставляет поток жить до 120 с, и он вызовет `self.after(0, …)` на уничтоженном виджете. Нужен `destroy()`/`WM_DELETE_WINDOW` со сбросом флага.

---

## 4. Осталось открытым из аудита (вне scope этого коммита)

Не претензия к коммиту — фиксирую, что эти пункты не затронуты:

- `_CM_LOCK` по-прежнему удерживается на всё время subprocess `agy` (`antigravity_adapter.py:invoke`) → профили Antigravity сериализуются.
- Глобальная запись `gemini:antigravity` перезаписывается без восстановления → «основной аккаунт Hermes» меняется как побочный эффект маршрутизации.
- Session affinity без TTL; `router_state.json` без межпроцессной блокировки.
- `hermes_plugin` перехватывает все вызовы `llm_execution` и не вызывает `next_call`.
- 5 экранов пересоздают виджеты через `destroy()`; нет периодического автообновления.
- Roadmap-модули (`supervisor`, `capability`, `skills`, `scheduler`, `deepseek_adapter`) по-прежнему не подключены; `DeepSeekResponsesAdapter` не зарегистрирован в `_ADAPTERS`.
- Веб-стек `gui_server.py` + `gui_cockpit.html` и прямой API-путь остаются мёртвыми; `fastapi`/`uvicorn` — в обязательных зависимостях.

---

## 5. Резюме для исполнителя

Порядок правок: **B1** (регрессия, ломает работающий сценарий) → **B4** (однострочная перестановка веток) → **B2** + **B3** (связаны: маппинг ролей и сохранение конфига) → S1, S8, S9 (дёшево) → S2–S5 (апдейтер, до объявления релиза).

Релизным гейтом это пропускать нельзя: `check_p0_release_gate` рапортует «9/9 P0 verified», хотя P0-5 закрыт с регрессией, а P0-4/P0-7 проходят на фиктивных ролях.
