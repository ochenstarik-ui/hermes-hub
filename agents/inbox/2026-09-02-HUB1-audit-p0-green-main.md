# Задание HUB-1: зелёный main и P0 из аудита Hermes Hub

## Для кого
**Серверная сессия Claude (пользователь `ochenstarik`), не для agy.** Это работа
исполнителя-Claude: правка кода, прогон, пуш. Ревьюер (сессия на ПК) принимает.

## Дата
2026-09-02.

## База
`origin/main` (`144f6a5`).

```
git fetch origin --prune
git checkout -b hub/audit-p0-green-main origin/main
```

В `main` напрямую не пушить. **Координация:** над `main` работают две сессии.
Перед пушем — `git fetch` и `git log --oneline origin/main`; при расхождении
перенести правки поверх, как это уже делалось.

## Зачем

По решению о слиянии (`docs/research/kagent-merge-decision.md`) шаг 1 —
**Hermes довести до зелёного и стабильного**, потому что он служит эталоном
переноса, а сломанный эталон портировать нельзя. Сейчас `main` красный. Полный
аудит — на рабочем столе владельца (`HERMES_HUB_FULL_AUDIT_2026-09-02.md`);
здесь только то, что подтверждено исполнением.

---

## Что ревьюер уже проверил — заново не выяснять

### CI на main красный. Причина — два дефекта, оба видны в логе последнего прогона

**1. Security-инвариант A37 не держится на Windows.**
`tests/test_a37_isolation_guards.py:394` падает:

```
AssertionError: команда со стильдой прошла мимо защиты: rm -rf $HOME/.hermes (OK)
assert not True
```

WorkspaceBoundaryGuard пропускает разрушительную команду с `$HOME`, потому что
раскрытие переменных и нормализация путей на Windows и Linux различаются. Это
не косметика — это граница вокруг агентских shell-действий. Пока она работает
по-разному на поддерживаемых системах, sandbox нельзя считать доказанным.

**2. Windows UTF-8 роняет verification-скрипт.**
`scripts/verify_multi_provider_router.py:63`:

```
UnicodeEncodeError: 'charmap' codec can't encode characters ...
```

Скрипт печатает русский текст (`[PASS] Чистая конфигурация...`), а консоль
Windows в CI — cp1252. Падает `print`, не логика.

Красные джобы: `Headless Run (no GUI dependencies)` и
`Clean Windows Runner Test`.

### Баг pricing fallback (P2, но реальный)

`src/antigravity_provider/router/telemetry_service.py:164`:

```python
data = yaml.safe_dump(p.read_text(encoding="utf-8"))
if isinstance(data, dict) and "pricing" in data:  # всегда False
```

`safe_dump` вместо `safe_load` — таблица цен из `pricing.yaml` не грузится
никогда, и `except: pass` это глушит. Должно быть `safe_load`.

---

## P0-1. Зелёный main (это первично)

1. **Исправить UTF-8 в verification-скрипте**: принудительный UTF-8 вывода
   (`PYTHONUTF8`, `PYTHONIOENCODING=utf-8`, реконфигурация `sys.stdout`, либо
   безопасное кодирование). Кросс-платформенно, проверяемо на обеих системах.
2. **Исправить WorkspaceBoundaryGuard** единым конвейером: классификация
   диалекта shell → раскрытие только распознанных переменных → нормализация
   разделителей → разрешение `$HOME`/`%USERPROFILE%` → канонизация пути →
   сравнение с защищёнными корнями → **fail closed**. Одинаковый тест-набор для
   Windows и Linux; `test_a37_isolation_guards` должен ловить `rm -rf $HOME/...`
   на обеих системах.
3. **Проверка — по зелёному CI**, а не локально: локальный прогон на Linux эти
   две джобы не воспроизводит. Довести оба Windows-джоба до зелёного.

## P0-2. Остальные P0 аудита — подтвердить исполнением ПЕРЕД правкой

Ревьюер их не проверял. По каждому: сначала воспроизвести, потом чинить. Не
чинить со слов аудита.

1. **Release Gate заявляет проверку хеша, которой не было** — частичный HTTP
   Range, но `PACKAGE_HASH_VERIFIED=True` без полного SHA-256. Прочитать
   `scripts/release_gate.py`, подтвердить, затем считать полный хеш или брать
   достоверный digest из release API.
2. **Publication gate fail-open** — 404/сеть/отсутствие пакета возвращаются как
   PASS. Разделить Offline Gate (тесты, updater, статика, сборка) и Publication
   Gate (релиз есть, ассеты есть, digest сверен, скачивание прошло).
3. **localhost `/api/action` без CSRF/Origin** — на loopback токен не требуется,
   а действие меняет состояние. Проверить, затем: bootstrap-токен, проверка
   `Origin`/`Sec-Fetch-Site`, авторизация небезопасных методов.

## P1. После зелёного main

1. **Zip-slip в updater**: распаковка обязана проверять каждый путь
   (`resolved.is_relative_to(staging)`), запрет абсолютных путей, `..`, symlink,
   device.
2. **pricing fallback**: `safe_load` вместо `safe_dump` (см. выше).
3. **CI-матрица Windows + Linux**: сейчас Linux-джоба нет, а проект на Linux и
   активно получает Linux-фиксы.
4. Прочее из аудита (failover error policy, `uv sync --frozen`, лишний `web`
   extra, secret-scan шире) — отдельными заданиями, не в этом.

---

## Ограничения

- Правки ревьюера из `main` не откатывать.
- Фронтенд без npm/сборки/фреймворков — `docs/web-api/CONTRACT.md` §1.
- Проверку SHA-256 и список разрешённых адресов обновления не ослаблять.
- Учётные данные и `~/.hermes/agy_profiles/` не трогать.
- Версию `0.1.3` не понижать.
- Правило честности: неизмеренное — `Н/Д` с причиной.

## Критерии приёмки

1. Ветка в `origin`, `git status` чист.
2. **Оба Windows-джоба CI зелёные** — ссылка на зелёный прогон в отчёте.
3. `test_a37_isolation_guards` ловит `rm -rf $HOME/...` на Windows и Linux;
   guard fail-closed.
4. verification-скрипт не падает на cp1252.
5. Остальные P0 либо исправлены с доказательством, либо явно помечены как
   отложенные с причиной.
6. `ruff check .` чисто; локальный прогон Linux зелёный; число тестов не меньше
   текущего.
7. Отчёт: `START_HEAD`, `FINAL_HEAD`, `origin/main`, `git status`,
   `X passed / Y skipped / Z failed`, ссылка на зелёный CI.

## Главное

Первично — зелёный main, и обе причины уже найдены: security-guard на Windows и
UTF-8 в verification. Остальные P0 аудита — только после подтверждения
исполнением. Это фундамент под слияние: пока Hermes красный и его sandbox-guard
дырявый на одной из систем, переносить его поведение в KAgent нельзя.

## Порядок сдачи
Передать точный `FINAL_COMMIT_SHA` и ссылку на зелёный прогон CI.
