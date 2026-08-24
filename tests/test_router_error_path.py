"""Путь обработки ошибок не должен падать сам.

Два дефекта, найденные проверкой всех шести ролей на живой машине:

1. antigravity_adapter.classify_error возвращал ErrorCategory.UNKNOWN —
   значения с таким именем не существует. Обращение к нему роняло сам
   классификатор, то есть отказ случался ровно там, где обрабатывался
   другой отказ, и маршрутизация обрывалась вместо перехода к резерву.

2. Уровень усилия не подставлялся, если у конкретного профиля не выполнен
   вход agy: карта усилий строится обнаружением через этот профиль. Уровни
   же — свойство модели, а не аккаунта, и берутся из сохранённого списка.
"""

from __future__ import annotations

from antigravity_provider.router.adapters import get_adapter
from antigravity_provider.router.adapters.base_adapter import ErrorCategory


def test_error_category_has_no_phantom_members():
    """Классификаторы обязаны ссылаться только на существующие категории."""
    valid = {m for m in dir(ErrorCategory) if not m.startswith("_")}
    assert "UNKNOWN" not in valid, (
        "если UNKNOWN добавили — обновите классификаторы, раньше его не было"
    )
    for name in ("AUTH_REQUIRED", "FATAL", "QUOTA_EXHAUSTED", "RATE_LIMITED", "TRANSIENT"):
        assert name in valid


def test_unclassified_error_does_not_crash_classifier():
    """Неразобранная ошибка должна классифицироваться, а не ронять обработчик."""
    for provider in ("antigravity", "openai-codex", "opencode-go", "grok", "claude"):
        adapter = get_adapter(provider)
        result = adapter.classify_error(Exception("нечто совершенно неразобранное"))
        assert result.category, f"{provider}: классификатор вернул пустую категорию"
        assert isinstance(result.category, str)


def test_effort_levels_derived_from_cached_model_ids(monkeypatch):
    """Уровни усилия берутся из склеенных идентификаторов, без обращения к профилю."""
    import antigravity_provider.agy_subprocess as agy
    from antigravity_provider.router import model_discovery

    monkeypatch.setattr(agy, "discover_models", lambda profile_id=None: {})
    monkeypatch.setattr(agy, "_AGY_EFFORT_MAP", {}, raising=False)

    class _Svc:
        @staticmethod
        def get():
            return _Svc()

        def get_models(self, provider):
            return ["gemini-3.7-flash-low", "gemini-3.7-flash-high", "claude-sonnet-4-6"]

    monkeypatch.setattr(model_discovery, "ModelDiscoveryService", _Svc)

    assert agy._model_supported_efforts("gemini-3.7-flash") == {"low", "high"}
    # У модели без суффиксов уровней быть не должно — подставлять нечего.
    assert agy._model_supported_efforts("claude-sonnet-4-6") == set()
