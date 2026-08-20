# Отчёт: Задание A — слой состояния и данных

Дата: 2026-08-21

## Идентификаторы и границы

- Base: `f171a8069d97aef5d3a45f838daed63abf2e69c1` (актуальный `origin/main` на старте).
- Ветка: `antigravity/state-layer`.
- Контракт опубликован первым отдельным коммитом в удалённой ветке: `35881c4`.
- Тег `v0.1.1` не создавался.
- Файлы UI и `hermes_hub_app.py` не изменялись.

## Реализовано

1. `HubStateStore` и `HubSnapshot`
   - snapshot имеет монотонные `generation` и `seq`;
   - медленные сканирования выполняются вне блокировки store;
   - поздний результат с меньшим `seq` не может перезаписать более свежий;
   - дельты применяются copy-on-write, без изменения вложенных словарей frozen snapshot на месте;
   - account/quota события содержат `provider`, `profile_id`, `generation` и `seq`.

2. Планировщик
   - refresh одного аккаунта и одного провайдера дедуплицируется;
   - quota fetch завершается до публикации account delta;
   - OAuth/account events запускают обновление только соответствующего аккаунта;
   - `UnifiedHealthService.refresh_profile()` пересчитывает один ViewModel без глобального scan.

3. OAuth и хранение auth
   - запись `auth.json` атомарна (`temp` + `os.replace`);
   - `ProfileAuthManager` публикует единое secret-free событие жизненного цикла;
   - дублирующие OAuth-события и скрывающие ошибки `except: pass` удалены;
   - listener, PKCE, callback и ручной fallback остаются отдельными от scheduler.

4. Квоты и routing
   - baseline содержит отдельные model-family buckets и честные неизвестные значения (`None`, `status=unknown`, UI: `Н/Д`);
   - runtime 429 обновляет только соответствующий аккаунт/семейство и немедленно публикует quota delta;
   - `ModelRegistry` учитывает capability, cost priority и известный остаток квоты;
   - exhausted pool отклоняется, неизвестная квота оценивается нейтрально.

5. Импорты и технический долг
   - корневой `antigravity_provider/__init__.py` запрещает смешивание namespace package с установленной старой копией;
   - добавлен runtime-тест происхождения импортов;
   - неиспользуемые дубликаты `CapabilityMatrix`, `SkillRegistry` и `LifecycleSupervisor` удалены после проверки отсутствия consumers; действующие механизмы остаются в `ModelRegistry`, router policy и lease/session слоях.

## Осознанные решения

- YAML: текущий PyYAML round-trip сохраняет заголовочные комментарии, но не гарантирует inline-комментарии. Миграция на `ruamel.yaml` не включена: это отдельное изменение формата/зависимостей, не требуемое для state API.
- Antigravity: глобальный `_AGY_INVOCATION_LOCK` сохранён. Несмотря на раздельные `USERPROFILE/HOME`, CLI всё ещё использует общий Windows Credential Manager key `gemini:antigravity`; lock защищает полный swap/invoke/restore и подтверждён concurrency-тестами.
- Installer: реальные installer-тесты имеют marker `installer` и исключены из штатного pytest; HKCU не затрагивается обычным прогоном.

## Проверки

- Целевой state/data/import/routing набор: `112 passed`.
- Полный набор при установленных UI-зависимостях: `201 passed, 4 skipped, 3 deselected, 2 failed`.
- Ruff: `All checks passed`.
- Release gate: заблокирован.

Два оставшихся падения находятся в запрещённой для Task A UI-зоне:

- `test_e_repeated_open_browser_invariance`: у `AddAccountWizard` не устанавливается `oauth_port`;
- `test_f_copy_before_open_browser`: wizard распаковывает backend-результат из трёх значений как два, поэтому `oauth_url` остаётся `None`.

Backend возвращает контракт `(session_id, auth_url, port)` корректно. Исправление требуется в Task B (`router/ui/add_account_wizard.py`). До зелёного полного gate release asset не публиковался. Live manifest доступен, но package URL сейчас отвечает 404; публикация заведомо не прошедшего gate пакета сознательно не выполнялась.
