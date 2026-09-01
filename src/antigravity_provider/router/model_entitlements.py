"""Определение моделей, доступных конкретному аккаунту.

Каталог NVIDIA публичный: `GET /v1/models` отдаётся вообще без ключа и
возвращает один и тот же список всем. Полей о доступности в нём нет — только
`id`, `object`, `created`, `owned_by`. Проверено запросом.

Значит узнать, чем может пользоваться конкретный аккаунт, из каталога нельзя.
Единственный достоверный способ — спросить у самой модели. Недоступная
отвечает до генерации:

    404  Function ... Not found for account '<id>'

то есть проверка недоступной модели не стоит ничего, а доступной — один токен
при `max_tokens=1`.

Опрос запускается ТОЛЬКО по явному действию владельца и результат сохраняется:
83 запроса подряд упираются в ограничения провайдера, и делать это молча при
каждом подключении неправильно.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from antigravity_provider import paths

logger = logging.getLogger("hermes.router.entitlements")

# Опрашиваем небольшими пачками: провайдеры ограничивают частоту, а выигрыш от
# большего числа потоков всё равно съедается их лимитом.
DEFAULT_WORKERS = 8
DEFAULT_TIMEOUT_SEC = 20.0


@dataclass
class EntitlementResult:
    """Итог опроса одного аккаунта."""

    provider: str
    profile_id: str
    checked_at: float
    available: List[str] = field(default_factory=list)
    unavailable: List[str] = field(default_factory=list)
    undetermined: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "provider": self.provider,
            "profile_id": self.profile_id,
            "checked_at": self.checked_at,
            "available": list(self.available),
            "unavailable": list(self.unavailable),
            "undetermined": dict(self.undetermined),
            "total": len(self.available) + len(self.unavailable) + len(self.undetermined),
        }


def _store_path() -> Any:
    return paths.get_hermes_home() / "model_entitlements.json"


def load_entitlements(provider: str, profile_id: str) -> Optional[Dict[str, Any]]:
    """Ранее определённая доступность или None, если опрос не проводился."""
    try:
        path = _store_path()
        if not path.is_file():
            return None
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        return data.get(f"{provider}:{profile_id}")
    except Exception as exc:
        logger.debug("Не удалось прочитать сохранённую доступность: %s", exc)
        return None


def save_entitlements(result: EntitlementResult) -> None:
    path = _store_path()
    try:
        data: Dict[str, Any] = {}
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8-sig"))
            except Exception:
                data = {}
        data[f"{result.provider}:{result.profile_id}"] = result.to_dict()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:
        logger.warning("Не удалось сохранить доступность моделей: %s", exc)


def _probe_one(base_url: str, token: str, model: str, timeout: float) -> tuple:
    """Вернуть (model, state, note): state — available | unavailable | undetermined."""
    body = json.dumps(
        {"model": model, "messages": [{"role": "user", "content": "ping"}], "max_tokens": 1}
    ).encode()
    req = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions",
        data=body,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            payload = json.load(response)
        if isinstance(payload.get("choices"), list):
            return (model, "available", "")
        return (model, "undetermined", "провайдер вернул ответ без choices")
    except urllib.error.HTTPError as exc:
        # 404 — модель аккаунту не выдана. Это ответ провайдера, а не сбой.
        if exc.code == 404:
            return (model, "unavailable", "не выдана аккаунту")
        # 401/403 — отвергнут сам ключ: дальше опрашивать бессмысленно.
        if exc.code in (401, 403):
            return (model, "undetermined", f"ключ отвергнут (HTTP {exc.code})")
        if exc.code == 429:
            return (model, "undetermined", "превышена частота запросов")
        return (model, "undetermined", f"HTTP {exc.code}")
    except Exception as exc:
        return (model, "undetermined", str(exc)[:80])


def probe_account_models(
    provider: str,
    profile_id: str,
    token: str,
    base_url: str,
    models: List[str],
    workers: int = DEFAULT_WORKERS,
    timeout: float = DEFAULT_TIMEOUT_SEC,
    progress: Optional[Callable[[int, int], None]] = None,
) -> EntitlementResult:
    """Опросить каталог и разложить модели по доступности.

    Модель, про которую ответ неоднозначен, попадает в `undetermined` с
    причиной — выдавать её за доступную или недоступную нельзя.
    """
    result = EntitlementResult(
        provider=provider, profile_id=profile_id, checked_at=time.time()
    )
    if not models:
        return result
    if not token:
        result.undetermined = {m: "ключ не задан" for m in models}
        return result

    done = 0
    lock = threading.Lock()

    def _run(model: str):
        nonlocal done
        outcome = _probe_one(base_url, token, model, timeout)
        with lock:
            done += 1
            if progress:
                try:
                    progress(done, len(models))
                except Exception:
                    pass
        return outcome

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        for model, state, note in pool.map(_run, models):
            if state == "available":
                result.available.append(model)
            elif state == "unavailable":
                result.unavailable.append(model)
            else:
                result.undetermined[model] = note

    result.available.sort()
    result.unavailable.sort()
    save_entitlements(result)
    return result
