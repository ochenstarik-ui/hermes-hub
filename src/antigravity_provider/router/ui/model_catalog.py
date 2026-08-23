"""Non-blocking UI adapter for the backend model-discovery cache.

The UI never discovers models synchronously and never invents model IDs.  The
adapter deliberately tolerates the small naming differences used by backend
revisions so the presentation layer can be merged independently from A9.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional


@dataclass(frozen=True)
class CachedModels:
    provider: str
    models: tuple[str, ...] = ()
    fetched_at: str = ""
    is_stale: bool = True
    unavailable_reason: str = "Список моделей ещё не получен"


def _service() -> Any:
    try:
        from antigravity_provider.router.model_discovery import ModelDiscoveryService

        getter = getattr(ModelDiscoveryService, "get", None)
        return getter() if callable(getter) else ModelDiscoveryService()
    except (ImportError, AttributeError, TypeError):
        return None


def _normalise(provider: str, raw: Any) -> CachedModels:
    if raw is None:
        return CachedModels(provider=provider)
    if isinstance(raw, dict):
        models = raw.get("models") or raw.get("discovered_models") or []
        fetched_at = raw.get("fetched_at") or raw.get("discovered_at") or raw.get("updated_at") or raw.get("last_refresh_at") or ""
        stale = raw.get("is_stale", raw.get("stale", False))
        reason = raw.get("unavailable_reason") or raw.get("error") or ""
    else:
        models = getattr(raw, "models", None) or getattr(raw, "discovered_models", None) or []
        fetched_at = (
            getattr(raw, "fetched_at", None)
            or getattr(raw, "updated_at", None)
            or getattr(raw, "last_refresh_at", None)
            or ""
        )
        stale = getattr(raw, "is_stale", getattr(raw, "stale", False))
        reason = getattr(raw, "unavailable_reason", None) or getattr(raw, "error", None) or ""
    clean = tuple(dict.fromkeys(str(model).strip() for model in models if str(model).strip()))
    return CachedModels(
        provider=provider,
        models=clean,
        fetched_at=str(fetched_at),
        is_stale=bool(stale),
        unavailable_reason=str(reason or ("" if clean else "Список моделей ещё не получен")),
    )


def get_cached_models(provider: str) -> CachedModels:
    """Return cached models immediately; never performs provider I/O."""
    service = _service()
    if service is None:
        return CachedModels(provider=provider, unavailable_reason="Служба обнаружения моделей ещё не подключена")
    for name in ("get_cached", "get_cached_models", "get_snapshot", "get_provider_models"):
        method = getattr(service, name, None)
        if not callable(method):
            continue
        try:
            return _normalise(provider, method(provider))
        except Exception as exc:
            return CachedModels(provider=provider, unavailable_reason=f"Кэш моделей недоступен: {exc}")
    return CachedModels(provider=provider, unavailable_reason="Служба не предоставляет чтение кэша моделей")


def refresh_models_async(provider: str, on_complete: Callable[[CachedModels], None]) -> bool:
    """Request a backend background refresh without blocking the Tk thread."""
    service = _service()
    if service is None:
        on_complete(get_cached_models(provider))
        return False
    for name in ("refresh_provider_async", "refresh_async", "discover_async"):
        method = getattr(service, name, None)
        if not callable(method):
            continue
        try:
            result: Optional[Any] = method(provider, on_complete=lambda *_args: on_complete(get_cached_models(provider)))
            return result is not False
        except TypeError:
            try:
                result = method(provider)
                return result is not False
            except Exception:
                break
        except Exception:
            break
    on_complete(get_cached_models(provider))
    return False
