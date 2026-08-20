# Задание: Hermes Hub — Plan A Stabilization, Refresh-архитектура, Delta UI и Smart Capability/Cost Model Routing

## Цели
1. Аудит текущего Git HEAD (`2b8b709`).
2. Ввести единый `HubSnapshot` и `HubStateStore`.
3. Убрать destroy/recreate из `AccountsView` и `RoutingView` (перевести на стабильные reused виджеты по `profile_id`/`role_id`).
4. Убрать любые вызовы `scan_all()` / сетевые / файловые I/O из UI Views и `_restore_status()`.
5. Обновлять только активную вкладку; при скрытых вкладках сохранять generation и выполнять lazy update при открытии.
6. Разработать централизованный `HermesRefreshScheduler` (tick каждые 5с, `max_concurrent_refresh=1`, stable initial delays, running guard, overlap policy).
7. Поддержать single-account refresh, refresh-all (только configured), request deduplication и stale response sequence protection.
8. Разработать типизированный thread-safe `EventBus` с delta событиями.
9. Проверить и исправить Win32 single instance mutex lifetime, thread-safe singletons и SessionAffinityTracker TTL + LRU capacity.
10. Разработать динамический `ModelRegistry` и `CapabilityPolicy` (без жесткой привязки к номерам версий моделей: Fast/Dispatcher, Researcher, Core Coder, Routine Coder, Reviewer), scoring по capability, quality, reasoning, latency, cost, diversity, quota buckets, same-account fallback и формированием объяснимого trace.
11. Расширить `gui_server.py` и WebSocket/event contracts для будущего перехода на Tauri без изменения бизнес-логики.
12. Разработать и запустить бенчмарки и тесты (reuse, performance, dedup, stale, scheduler, mutex, session TTL, routing, capability, cost).
13. Пройти полный pytest suite и `release_gate.py`.
14. Закоммитить и запушить в `main` без создания релизного тега v0.1.1.
