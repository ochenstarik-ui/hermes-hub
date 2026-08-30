"""Поиск локальных серверов моделей, уже запущенных на машине.

Раньше адрес локального сервера вводился руками: владелец должен был помнить,
на каком порту у него llama.cpp, Ollama или LM Studio. Здесь опрашиваются
известные порты на петле, и наружу отдаётся только то, что **ответило**.

Правило честности действует и тут: ни одного порта, который не ответил, в
результат не попадает, и ни одна модель не выдумывается — список берётся у
самого сервера.
"""

from __future__ import annotations

import concurrent.futures
import json
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("hermes.router.local_discovery")

# Порты, на которых эти серверы работают из коробки. Список — умолчание, а не
# исчерпывающая истина: владелец всегда может ввести адрес сам.
WELL_KNOWN_ENDPOINTS: List[Dict[str, Any]] = [
    {"name": "Ollama", "port": 11434, "base_path": "/v1"},
    {"name": "LM Studio", "port": 1234, "base_path": "/v1"},
    {"name": "llama.cpp", "port": 8080, "base_path": "/v1"},
    {"name": "llama.cpp", "port": 8081, "base_path": "/v1"},
    {"name": "llama.cpp", "port": 8082, "base_path": "/v1"},
    {"name": "vLLM", "port": 8000, "base_path": "/v1"},
    {"name": "Jan", "port": 1337, "base_path": "/v1"},
    {"name": "GPT4All", "port": 4891, "base_path": "/v1"},
    {"name": "Text Generation WebUI", "port": 5000, "base_path": "/v1"},
]

DEFAULT_HOST = "127.0.0.1"
PROBE_TIMEOUT_SEC = 1.5


@dataclass
class LocalServer:
    """Обнаруженный локальный сервер моделей."""

    name: str
    base_url: str
    models: List[str] = field(default_factory=list)
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "base_url": self.base_url,
            "models": list(self.models),
            "model_count": len(self.models),
            "error": self.error,
        }


def _fetch_models(base_url: str, timeout: float) -> List[str]:
    """Спросить у сервера список моделей по OpenAI-совместимому /models."""
    url = base_url.rstrip("/") + "/models"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        if resp.status != 200:
            raise ValueError(f"HTTP {resp.status}")
        payload = json.loads(resp.read().decode("utf-8", errors="replace"))

    models: List[str] = []
    for item in payload.get("data") or []:
        if isinstance(item, dict) and item.get("id"):
            models.append(str(item["id"]))
        elif isinstance(item, str):
            models.append(item)
    return models


def probe_endpoint(host: str, port: int, base_path: str, name: str,
                   timeout: float = PROBE_TIMEOUT_SEC) -> Optional[LocalServer]:
    """Опросить один адрес. Не ответил — вернуть None, а не пустую заглушку."""
    base_url = f"http://{host}:{port}{base_path}"
    try:
        models = _fetch_models(base_url, timeout)
    except (urllib.error.URLError, OSError, TimeoutError):
        # Порт закрыт или сервер не отвечает — это не находка и не ошибка.
        return None
    except (ValueError, json.JSONDecodeError) as exc:
        # Порт занят чем-то, что говорит не на том языке. Показываем как
        # найденный, но с причиной: иначе владелец будет гадать, почему
        # заведомо работающий сервер не виден.
        logger.debug("Порт %s занят не тем сервисом: %s", port, exc)
        return LocalServer(name=f"{name} (порт {port})", base_url=base_url,
                           error="Сервер на этом порту ответил не по OpenAI-совместимому протоколу")
    return LocalServer(name=f"{name} (порт {port})", base_url=base_url, models=models)


def discover_local_servers(host: str = DEFAULT_HOST,
                           endpoints: Optional[List[Dict[str, Any]]] = None,
                           timeout: float = PROBE_TIMEOUT_SEC) -> List[LocalServer]:
    """Опросить известные порты параллельно и вернуть только ответившие.

    Опрос идёт параллельно: последовательно девять закрытых портов дали бы
    заметную паузу в интерфейсе.
    """
    targets = endpoints if endpoints is not None else WELL_KNOWN_ENDPOINTS
    found: List[LocalServer] = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=min(10, len(targets) or 1)) as pool:
        futures = {
            pool.submit(probe_endpoint, host, t["port"], t.get("base_path", "/v1"), t["name"], timeout): t
            for t in targets
        }
        for fut in concurrent.futures.as_completed(futures):
            try:
                result = fut.result()
            except Exception as exc:  # опрос не должен ронять вызывающего
                logger.warning("Ошибка опроса локального сервера: %s", exc)
                continue
            if result is not None:
                found.append(result)

    found.sort(key=lambda s: (s.error is not None, -len(s.models), s.base_url))
    return found
