# Ревью, раунд 5: `0d9005f…0c511cd` (OAuth, мастер, тарифы, квоты, Claude/Grok, Plan A)

**База:** `8314d46` → **проверено:** `0c511cd` (5 коммитов, +6970 / −665)
**Состояние:** тесты 91 passed / 7 skipped / 3 deselected, релизный гейт зелёный.

**Вердикт: ⛔ два блокирующих дефекта — фабрикация данных о квотах и поддельный код авторизации. Оба относятся к классу «пользователь видит правдоподобное, но выдуманное».**

---

## 1. ⛔ Блокер A: сборщик квот выдаёт захардкоженные числа под видом данных провайдера

`src/antigravity_provider/router/quota_collector.py` (561 строка) **не делает ни одного сетевого вызова**:

```
urlopen вызовов: 0
```

При этом каждый сборщик возвращает фиксированные константы и помечает их источником провайдерского API:

```python
# _collect_antigravity_quota, строки 320–346
QuotaBucket(id="antigravity.gemini.5h",     used_percent=9.0,  remaining_percent=91.0, status="healthy")
QuotaBucket(id="antigravity.gemini.weekly", used_percent=1.0,  remaining_percent=99.0, status="healthy")
...
return QuotaSnapshot(..., source="antigravity_api")
```

Всего **17 литеральных `used_percent`** по пяти провайдерам, с источниками:
`antigravity_api`, `codex_usage_api`, `opencode_api`, `claude_oauth_usage_api`, `xai_task_usage_api`.

Эти значения доходят до пользователя: `ui/views/accounts_view.py:168`

```python
snap = quota_snap or p.quota_snapshot or AccountQuotaService.get().get_snapshot(p.provider, p.profile_id)
```

и рисуются в `quota_box` карточки аккаунта. То есть на экране «Аккаунты» показывается «Gemini 5h — использовано 9%, осталось 91%» независимо от реального состояния квоты. Ровно та задача, ради которой существует продукт — понимать, где кончилась квота, — решается вымышленными числами.

**Тесты фикцию не закрепляют** (`test_accounts_tariffs_quotas.py` проверяет арифметику `used/remaining` на собственных значениях), поэтому дефект не виден по зелёному прогону.

**Требуется одно из двух:**
- реализовать реальный сбор (запрос к провайдеру) — тогда источники честные;
- либо пометить снапшоты как `source="baseline"`/`"estimated"` и явно показать в UI, что это оценка, а не данные провайдера. Значение `"baseline"` в коде уже есть (строка 525) — значит, различие осознавалось.

---

## 2. ⛔ Блокер B: тихий фолбэк на поддельный код авторизации

`codex_oauth.py:103–112`:

```python
try:
    resp = _post_json(CODEX_OAUTH_USER_CODE_URL, {"client_id": CODEX_OAUTH_CLIENT_ID})
    self.user_code = resp.get("user_code")
    self.device_auth_id = resp.get("device_auth_id")
except Exception as e:
    logger.warning("Could not reach OpenAI deviceauth endpoint directly: %s. Using local session.", e)
    self.user_code = f"CDX-{secrets.token_hex(3).upper()}"
    self.device_auth_id = secrets.token_urlsafe(16)
```

То же в `grok_oauth.py:91–94` (`GRK-XXXXXX` + локальный `device_code`).

По RFC 8628 `user_code` и `device_code` выдаёт **сервер авторизации**. Сгенерированные локально, они серверу неизвестны. Последствие: при любой недоступности эндпоинта (сетевой сбой, смена API, гео-блокировка) мастер показывает пользователю правдоподобный код вида `CDX-A1B2C3`, предлагает ввести его на странице провайдера, затем поллит `device_auth_id`, которого не существует, — и через 15 минут выдаёт таймаут. Отличить подделку от настоящего кода пользователь не может; в логах остаётся только `warning`.

Комментарий в коде говорит «for offline or simulated/mocked environment» — то есть режим предназначен для тестов, но срабатывает в продакшене по любому исключению.

**Требуется:** при неудаче запроса кода показывать ошибку немедленно, а фолбэк включать только под явным флагом (`HERMES_HUB_DEV_MODE=1`), по образцу уже сделанного в `update_manager.is_allowed_update_host`.

---

## 3. Существенные замечания

**S1. Три новых заимствованных OAuth-клиента без документирования.**
```
codex_oauth.py:31  CODEX_OAUTH_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"   (OpenAI Codex CLI)
grok_oauth.py:30   XAI_OAUTH_CLIENT_ID   = "b1a00492-073a-47ea-816f-4c329264a828"
claude_oauth.py    клиент Claude
```
Для Google было принято решение и оформлено `docs/OAUTH_CLIENT.md` с моделью угроз по RFC 8252. Три новых клиента появились без такого же разбора. Политику нужно распространить на них — иначе документ описывает одну треть реальной картины.

**S2. `gui_server.py` вырос на 112 строк и по-прежнему ничем не запускается.** Проверено: ни один `.py`, `.bat`, `.ps1`, `.cs` не вызывает `run_gui_server`. В мёртвый параллельный стек вкладываются усилия; `fastapi`/`uvicorn` остаются обязательными зависимостями.

**S3. `health_tracker`: атомарность есть, межпроцессной блокировки нет.** Запись через `tempfile.mkstemp` + `os.replace` (строки 136–145) — риск порванного файла закрыт. Но GUI-процесс и процесс Hermes по-прежнему перетирают состояние друг друга целиком (last-writer-wins).

---

## 4. Закрыто в этих коммитах (подтверждаю)

| Замечание прошлых раундов | Статус |
|---|---|
| Session affinity без TTL и вытеснения | ✅ `ttl_seconds=1800`, `max_entries=1000`, `prune_expired()` |
| `_restore_status` блокирует UI сетевым сканом | ✅ читает готовый снапшот из `HubStateStore`, сети в UI-потоке нет |
| Новые модули оказываются мёртвым кодом | ✅ не повторилось: `quota_collector` (9 импортёров), `state_store` (8), `account_identity` (5), `scheduler` (5), `event_bus` (4), `model_registry` (2) — всё подключено |
| Новые адаптеры не регистрируются | ✅ `claude` и `grok` есть в `_ADAPTERS` |
| Наложение периодических задач | ✅ `HermesRefreshScheduler` с overlap-skip и счётчиком `tasks_skipped_overlap` |
| Утечка секретов в логи | ✅ не найдено: в `add_account_wizard.py`, `codex_oauth.py`, `grok_oauth.py`, `claude_oauth.py` токены и ключи не логируются; в мастере поле с `show="*"` и маскирование идентичности |

Отдельно отмечу качество: капабилити-роутинг в `router_engine` со скорингом моделей и фолбэком в пределах аккаунта сделан аккуратно, `state_store` с дельта-обновлениями — правильное архитектурное решение против прежних полных пересканов.

---

## 5. Остаётся открытым с прошлых раундов

- `capability_matrix`, `lifecycle_supervisor`, `skill_registry`, `deepseek_adapter` — по-прежнему не подключены ни к одному кодовому пути.
- Комментарии в `router_profiles.yaml` стираются при сохранении.
- `model_timeout_seconds`, `monitoring_interval_seconds`, `auto_monitoring` сохраняются, но не читаются.
- `tests/test_installer.py` при запуске с `-m installer` пишет в Start Menu и `HKCU`.
- `_CM_LOCK` удерживается на всё время subprocess `agy`; глобальная запись `gemini:antigravity` перезаписывается без восстановления.

---

## 6. Условия приёмки

**Блокирующие:**
1. Блокер A — либо реальный сбор квот, либо честная маркировка `estimated`/`baseline` в источнике и в UI.
2. Блокер B — фолбэк на локальный код только под `HERMES_HUB_DEV_MODE=1`, иначе немедленная ошибка.

**До релиза:**
3. Распространить решение по OAuth-клиентам на OpenAI, xAI и Claude в `docs/OAUTH_CLIENT.md`.
4. Определиться с `gui_server.py`: удалить, вынести в `legacy/` или подключить.

После закрытия 1 и 2 препятствий к тегу со стороны кода не вижу — остаются организационные пункты из раунда 4 (опубликовать ассет релиза и `HermesHubSetup.exe`, обновить `checksums.txt`).
