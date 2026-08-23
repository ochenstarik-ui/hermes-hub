"""Hermes Hub — Model Discovery Service.

Provides background discovery of available models across all providers with:
- Persistent disk caching (models_cache.json in HERMES_HOME)
- Strict non-blocking read access for UI and routers
- Strict timeout enforcement for background network / subprocess probes
- Honest empty/None returns when models have not been discovered yet (zero invented lists)
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("hermes.router.model_discovery")


class ModelDiscoveryService:
    """Thread-safe singleton service for discovering and caching provider models."""

    _instance: Optional["ModelDiscoveryService"] = None
    _lock = threading.Lock()

    def __init__(self, cache_path: Optional[Path] = None) -> None:
        if cache_path is None:
            hermes_home = Path(os.environ.get("HERMES_HOME", "~/.hermes")).expanduser()
            if os.name == "nt" and "HERMES_HOME" not in os.environ:
                local_app = os.environ.get("LOCALAPPDATA", "")
                if local_app and (Path(local_app) / "hermes").exists():
                    hermes_home = Path(local_app) / "hermes"
            cache_path = hermes_home / "models_cache.json"

        self._cache_path = cache_path
        self._cache_lock = threading.Lock()
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._ttl_seconds: int = 3600  # 1 hour
        self._load_cache_from_disk()

    @classmethod
    def get(cls) -> "ModelDiscoveryService":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    # ─────────────────────────────────────────────────────────────
    #  DISK PERSISTENCE
    # ─────────────────────────────────────────────────────────────

    def _load_cache_from_disk(self) -> None:
        with self._cache_lock:
            if not self._cache_path.is_file():
                self._cache = {}
                return
            try:
                data = json.loads(self._cache_path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    self._cache = data
            except Exception as exc:
                logger.warning("Could not read models cache from %s: %s", self._cache_path, exc)
                self._cache = {}

    def _save_cache_to_disk(self) -> None:
        try:
            self._cache_path.parent.mkdir(parents=True, exist_ok=True)
            temp_file = self._cache_path.with_name(f"{self._cache_path.name}.tmp")
            temp_file.write_text(json.dumps(self._cache, indent=2, ensure_ascii=False), encoding="utf-8")
            temp_file.replace(self._cache_path)
        except Exception as exc:
            logger.warning("Could not persist models cache to %s: %s", self._cache_path, exc)

    # ─────────────────────────────────────────────────────────────
    #  NON-BLOCKING READ API
    # ─────────────────────────────────────────────────────────────

    def get_models(self, provider: str) -> Optional[List[str]]:
        """Return cached models for provider immediately, or None if undiscovered."""
        meta = self.get_models_with_metadata(provider)
        if not meta or not meta.get("models"):
            return None
        return list(meta["models"])

    def get_models_with_metadata(self, provider: str) -> Dict[str, Any]:
        """Return cached models and freshness status without blocking."""
        with self._cache_lock:
            entry = self._cache.get(provider.lower())
            if not entry or "models" not in entry:
                return {
                    "provider": provider,
                    "models": None,
                    "discovered_at": None,
                    "is_stale": True,
                    "has_cache": False,
                }

            discovered_at = entry.get("discovered_at", 0)
            is_stale = (time.time() - discovered_at) > self._ttl_seconds
            return {
                "provider": provider,
                "models": list(entry["models"]),
                "discovered_at": discovered_at,
                "is_stale": is_stale,
                "has_cache": True,
            }

    def get_cached(self, provider: str) -> Dict[str, Any]:
        """Convenience alias for get_models_with_metadata."""
        return self.get_models_with_metadata(provider)

    def refresh_models(
        self,
        provider: str,
        on_complete: Optional[Callable[[Optional[List[str]]], None]] = None,
        timeout: float = 15.0,
    ) -> None:
        """Trigger background model discovery with strict timeout (alias)."""
        return self.refresh_models_async(provider, on_complete=on_complete, timeout=timeout)

    # ─────────────────────────────────────────────────────────────
    #  DISCOVERY PROBES WITH TIMEOUT
    # ─────────────────────────────────────────────────────────────

    def refresh_models_async(
        self,
        provider: str,
        on_complete: Optional[Callable[[Optional[List[str]]], None]] = None,
        timeout: float = 15.0,
    ) -> None:
        """Trigger background model discovery with strict timeout."""
        def _worker():
            res = self.discover_models_sync(provider, timeout=timeout)
            if on_complete:
                try:
                    on_complete(res)
                except Exception:
                    pass

        threading.Thread(target=_worker, daemon=True).start()

    def refresh_all_async(
        self,
        on_complete: Optional[Callable[[Dict[str, Optional[List[str]]]], None]] = None,
        timeout: float = 15.0,
    ) -> None:
        """Discover models for all 5 providers concurrently in background."""
        def _worker():
            providers = ["antigravity", "openai-codex", "opencode-go", "claude", "grok"]
            results: Dict[str, Optional[List[str]]] = {}
            threads = []

            def _probe(p):
                results[p] = self.discover_models_sync(p, timeout=timeout)

            for prov in providers:
                t = threading.Thread(target=_probe, args=(prov,), daemon=True)
                threads.append(t)
                t.start()

            for t in threads:
                t.join(timeout=timeout + 2.0)

            if on_complete:
                try:
                    on_complete(results)
                except Exception:
                    pass

        threading.Thread(target=_worker, daemon=True).start()

    def discover_models_sync(self, provider: str, timeout: float = 15.0) -> Optional[List[str]]:
        """Synchronously probe models with strict timeout without blocking indefinite hangs."""
        result_holder: List[Optional[List[str]]] = [None]
        error_holder: List[Optional[Exception]] = [None]

        def _do_probe():
            try:
                result_holder[0] = self._probe_provider(provider)
            except Exception as exc:
                error_holder[0] = exc

        worker = threading.Thread(target=_do_probe, daemon=True)
        worker.start()
        worker.join(timeout=timeout)

        if worker.is_alive():
            logger.warning("Model discovery for provider '%s' timed out (> %.1fs)", provider, timeout)
            # Timeout: retain existing cache if any
            with self._cache_lock:
                entry = self._cache.get(provider.lower())
                return list(entry["models"]) if entry and "models" in entry else None

        if error_holder[0]:
            logger.info("Model discovery probe for '%s' returned error: %s", provider, error_holder[0])
            with self._cache_lock:
                entry = self._cache.get(provider.lower())
                return list(entry["models"]) if entry and "models" in entry else None

        models = result_holder[0]
        if models is not None:
            with self._cache_lock:
                self._cache[provider.lower()] = {
                    "models": models,
                    "discovered_at": time.time(),
                }
                self._save_cache_to_disk()
            logger.info("Discovered %d models for provider '%s': %s", len(models), provider, models)
            return models

        return None

    def _probe_provider(self, provider: str) -> Optional[List[str]]:
        """Perform provider-specific model discovery."""
        prov = provider.lower()
        from antigravity_provider.router.profile_manager import ProfileAuthManager

        if prov == "antigravity":
            from antigravity_provider.agy_subprocess import discover_models
            res = discover_models()
            if res:
                return sorted(list(set(res.values())))
            return None

        elif prov in ("openai-codex", "codex"):
            for pid in ["codex-orch", "codex-worker-1", "codex-worker-2"]:
                auth = ProfileAuthManager.load_profile_auth("openai-codex", pid)
                if not auth:
                    continue
                tokens = auth.get("token") or auth.get("tokens") or auth
                access_token = (
                    tokens.get("access_token")
                    if isinstance(tokens, dict)
                    else auth.get("api_key") or auth.get("access_token")
                )
                if not access_token:
                    continue
                try:
                    req = urllib.request.Request(
                        "https://api.openai.com/v1/models",
                        headers={
                            "Authorization": f"Bearer {access_token}",
                            "Accept": "application/json",
                            "User-Agent": "hermes-hub/1.0",
                        },
                    )
                    with urllib.request.urlopen(req, timeout=10) as resp:
                        data = json.loads(resp.read().decode("utf-8") or "{}")
                        items = data.get("data", [])
                        if isinstance(items, list):
                            models = [str(m.get("id")) for m in items if isinstance(m, dict) and m.get("id")]
                            chat_models = [
                                m for m in models
                                if any(x in m for x in ("gpt-4", "gpt-3.5", "o1", "o3", "codex", "chatgpt"))
                            ]
                            return sorted(chat_models or models)
                except Exception as exc:
                    logger.debug("Codex model query failed on %s: %s", pid, exc)
            return None

        elif prov in ("opencode-go", "opencode"):
            for pid in ["opengo-1", "opengo-2", "opengo-3"]:
                auth = ProfileAuthManager.load_profile_auth("opencode-go", pid)
                if not auth:
                    continue
                api_key = auth.get("api_key")
                if not api_key:
                    continue
                try:
                    req = urllib.request.Request(
                        "https://opencode.ai/zen/go/v1/models",
                        headers={
                            "Authorization": f"Bearer {api_key}",
                            "Accept": "application/json",
                            "User-Agent": "hermes-hub/1.0",
                        },
                    )
                    with urllib.request.urlopen(req, timeout=10) as resp:
                        data = json.loads(resp.read().decode("utf-8") or "{}")
                        items = data.get("data") or data.get("models") or []
                        if isinstance(items, list):
                            models = [str(m.get("id") or m) for m in items if m]
                            return sorted(models)
                except Exception as exc:
                    logger.debug("OpenCode model query failed on %s: %s", pid, exc)
            return None

        return None
