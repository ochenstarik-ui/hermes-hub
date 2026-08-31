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
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("hermes.router.model_discovery")


class ModelDiscoveryService:
    """Thread-safe singleton service for discovering and caching provider models."""

    _instance: Optional["ModelDiscoveryService"] = None
    _lock = threading.Lock()

    def __init__(self, cache_path: Optional[Path] = None) -> None:
        if cache_path is None:
            from antigravity_provider.paths import get_hermes_home
            cache_path = get_hermes_home() / "models_cache.json"

        self._cache_path = cache_path
        self._cache_lock = threading.Lock()
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._probe_context = threading.local()
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

    def remember_models(self, provider: str, profile_id: str, models: list[str]) -> None:
        with self._cache_lock:
            self._cache[f"{provider.lower()}:{profile_id}"] = {
                "models": list(models), "discovered_at": time.time(), "error": None,
            }
            self._save_cache_to_disk()

    def get_models(self, provider: str) -> Optional[List[str]]:
        """Return cached models for provider immediately, or None if undiscovered."""
        meta = self.get_models_with_metadata(provider)
        if not meta or not meta.get("models"):
            return None
        return list(meta["models"])

    def get_models_with_metadata(self, provider: str, profile_id: Optional[str] = None) -> Dict[str, Any]:
        """Return cached models and freshness status without blocking."""
        with self._cache_lock:
            key = f"{provider.lower()}:{profile_id}" if profile_id else provider.lower()
            entry = self._cache.get(key)
            if not entry or "models" not in entry:
                return {
                    "provider": provider,
                    "models": None,
                    "discovered_at": None,
                    "is_stale": True,
                    "has_cache": False,
                    "error": entry.get("error") if entry else None,
                }

            discovered_at = entry.get("discovered_at")
            is_stale = (time.time() - float(discovered_at)) > self._ttl_seconds if discovered_at else True
            models = entry.get("models")
            return {
                "provider": provider,
                "models": list(models) if models is not None else None,
                "discovered_at": discovered_at,
                "is_stale": is_stale,
                "has_cache": models is not None,
                "error": entry.get("error"),
            }

    def get_error(self, provider: str) -> Optional[str]:
        """Return last discovery error message for provider if any."""
        with self._cache_lock:
            entry = self._cache.get(provider.lower())
            return entry.get("error") if entry else None

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
        """Discover models for all configured providers concurrently in background."""
        def _worker():
            providers = [
                "antigravity",
                "openai-codex",
                "opencode-go",
                "claude",
                "grok",
                "openrouter",
                "nvidia",
                "ollama",
                "local",
            ]
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

    def discover_models_sync(self, provider: str, timeout: float = 15.0, profile_id: Optional[str] = None) -> Optional[List[str]]:
        """Synchronously probe models with strict timeout without blocking indefinite hangs."""
        cache_key = f"{provider.lower()}:{profile_id}" if profile_id else provider.lower()
        result_holder: List[Optional[List[str]]] = [None]
        error_holder: List[Optional[str]] = [None]

        def _do_probe():
            try:
                self._probe_context.profile_id = profile_id
                models, err_msg = self._probe_provider(provider)
                result_holder[0] = models
                error_holder[0] = err_msg
            except Exception as exc:
                error_holder[0] = str(exc).strip() or type(exc).__name__

        worker = threading.Thread(target=_do_probe, daemon=True)
        worker.start()
        worker.join(timeout=timeout)

        if worker.is_alive():
            logger.warning("Model discovery for provider '%s' timed out (> %.1fs)", provider, timeout)
            timeout_msg = f"Превышено время ожидания ответа от сервера ({timeout:.1f}с)"
            with self._cache_lock:
                entry = self._cache.get(cache_key, {})
                existing_models = entry.get("models")
                self._cache[cache_key] = {
                    "models": existing_models,
                    "discovered_at": entry.get("discovered_at"),
                    "error": timeout_msg,
                }
                self._save_cache_to_disk()
                return list(existing_models) if existing_models else None

        models = result_holder[0]
        err_text = error_holder[0]

        if models is not None and not err_text:
            with self._cache_lock:
                self._cache[cache_key] = {
                    "models": models,
                    "discovered_at": time.time(),
                    "error": None,
                }
                self._save_cache_to_disk()
            logger.info("Discovered %d models for provider '%s': %s", len(models), provider, models)
            return models

        if err_text:
            logger.info("Model discovery probe for '%s' returned error: %s", provider, err_text)
            with self._cache_lock:
                entry = self._cache.get(cache_key, {})
                existing_models = entry.get("models")
                self._cache[cache_key] = {
                    "models": existing_models,
                    "discovered_at": entry.get("discovered_at"),
                    "error": err_text,
                }
                self._save_cache_to_disk()
            return list(existing_models) if existing_models else None

        with self._cache_lock:
            entry = self._cache.get(cache_key, {})
            existing_models = entry.get("models")
            self._cache[cache_key] = {
                "models": existing_models,
                "discovered_at": entry.get("discovered_at"),
                "error": entry.get("error") or "Модели не найдены",
            }
            self._save_cache_to_disk()
            return list(existing_models) if existing_models else None

    def discover_ollama_cloud(self) -> Dict[str, Any]:
        """Public catalog documented at https://docs.ollama.com/cloud#listing-models.

        Catalog presence is not proof of an account's inference entitlement.
        """
        key = "ollama-cloud-catalog"
        error = None
        models = None
        try:
            req = urllib.request.Request("https://ollama.com/api/tags", headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=10) as response:
                data = json.loads(response.read().decode("utf-8"))
            models = sorted({str(m.get("name") or m.get("model")) for m in data.get("models", []) if isinstance(m, dict) and (m.get("name") or m.get("model"))})
        except urllib.error.HTTPError as exc:
            error = self._extract_http_error(exc)
        except Exception as exc:
            error = str(exc)
        with self._cache_lock:
            previous = self._cache.get(key, {})
            self._cache[key] = {
                "models": models if models is not None else previous.get("models"),
                "discovered_at": time.time() if models is not None else previous.get("discovered_at"),
                "error": error,
            }
            self._save_cache_to_disk()
        return self.get_models_with_metadata(key)

    def _extract_http_error(self, http_err: urllib.error.HTTPError) -> str:
        raw_err = ""
        try:
            raw_err = http_err.read().decode("utf-8", errors="replace")[:2000]
            err_json = json.loads(raw_err)
            if isinstance(err_json, dict):
                if "error" in err_json:
                    err_obj = err_json["error"]
                    if isinstance(err_obj, dict):
                        msg = err_obj.get("message") or str(err_obj)
                    else:
                        msg = str(err_obj)
                elif "message" in err_json:
                    msg = str(err_json["message"])
                elif "detail" in err_json:
                    msg = str(err_json["detail"])
                else:
                    msg = raw_err
            else:
                msg = raw_err
            return f"HTTP {http_err.code}: {msg}"
        except Exception:
            return f"HTTP {http_err.code}: {raw_err or http_err.reason}"

    def _get_provider_candidate_profiles(self, prov: str) -> List[Tuple[str, Optional[Any]]]:
        from antigravity_provider.router.router_config import load_router_config
        cfg = load_router_config()
        p_lower = prov.lower()
        requested = getattr(self._probe_context, "profile_id", None)
        if requested:
            pcfg = cfg.get_profile(requested)
            return [(requested, pcfg)] if pcfg else []
        matched = [
            (pid, pcfg)
            for pid, pcfg in cfg.profiles.items()
            if pcfg.provider.lower() == p_lower
            or (p_lower in ("nvidia", "nvidia-nim") and pcfg.provider.lower() in ("nvidia", "nvidia-nim"))
            or (p_lower in ("openai-codex", "codex") and pcfg.provider.lower() in ("openai-codex", "codex"))
            or (p_lower in ("opencode-go", "opencode") and pcfg.provider.lower() in ("opencode-go", "opencode"))
            or (p_lower in ("claude", "anthropic") and pcfg.provider.lower() in ("claude", "anthropic"))
            or (p_lower in ("grok", "xai") and pcfg.provider.lower() in ("grok", "xai"))
            or (p_lower in ("local", "local-llm", "llama.cpp", "vllm") and pcfg.provider.lower() in ("local", "local-llm", "llama.cpp", "vllm"))
        ]
        if matched:
            return matched

        default_slots = {
            "openai-codex": ["codex-orch", "codex-worker-1", "codex-worker-2"],
            "codex": ["codex-orch", "codex-worker-1", "codex-worker-2"],
            "opencode-go": ["opengo-1", "opengo-2", "opengo-3"],
            "opencode": ["opengo-1", "opengo-2", "opengo-3"],
            "grok": ["grok-orch", "grok-worker-1", "grok-worker-2"],
            "xai": ["grok-orch", "grok-worker-1", "grok-worker-2"],
            "claude": ["claude-orch", "claude-worker-1", "claude-worker-2"],
            "anthropic": ["claude-orch", "claude-worker-1", "claude-worker-2"],
            "openrouter": ["openrouter-1", "openrouter-2"],
            "nvidia": ["nvidia-1", "nvidia-2"],
            "nvidia-nim": ["nvidia-nim-1", "nvidia-nim-2"],
            "ollama": ["ollama-1", "ollama-2"],
            "local": ["local-1", "local-2"],
            "local-llm": ["local-1", "local-2"],
            "llama.cpp": ["local-1", "local-2"],
            "vllm": ["local-1", "local-2"],
        }
        candidates = default_slots.get(p_lower, [f"{p_lower}-1", f"{p_lower}-2"])
        return [(pid, cfg.get_profile(pid)) for pid in candidates]

    def _probe_provider(self, provider: str) -> Tuple[Optional[List[str]], Optional[str]]:
        """Perform provider-specific model discovery returning (models_list, error_msg)."""
        prov = provider.lower()
        from antigravity_provider.router.profile_manager import ProfileAuthManager

        if prov in ("antigravity", "google-antigravity"):
            from antigravity_provider.agy_subprocess import discover_models
            from antigravity_provider.paths import get_hermes_home
            from antigravity_provider.router.router_config import load_router_config

            candidate_pids: List[str] = []
            req_p = getattr(self._probe_context, "profile_id", None)
            if req_p:
                candidate_pids.append(req_p)

            try:
                cfg = load_router_config()
                for pid, pcfg in cfg.profiles.items():
                    if pcfg.provider.lower() in ("antigravity", "google-antigravity") and pid not in candidate_pids:
                        candidate_pids.append(pid)
            except Exception:
                pass

            main_p = ProfileAuthManager.get_main_profile("antigravity")
            if main_p and main_p not in candidate_pids:
                candidate_pids.append(main_p)

            standard_slots = (
                ["ag-orch-primary", "ag-orch-fallback"]
                + [f"ag-{i}" for i in range(1, 21)]
                + [f"ag-w{i}" for i in range(1, 11)]
            )
            for s in standard_slots:
                if s not in candidate_pids:
                    candidate_pids.append(s)

            try:
                agy_dir = get_hermes_home() / "agy_profiles"
                if agy_dir.is_dir():
                    for sub in sorted(agy_dir.iterdir()):
                        if sub.is_dir() and sub.name not in candidate_pids:
                            candidate_pids.append(sub.name)
            except Exception:
                pass

            target_pid = None
            for cand in candidate_pids:
                st = ProfileAuthManager.get_profile_status("antigravity", cand)
                if st.get("authenticated") or ProfileAuthManager.load_profile_auth("antigravity", cand):
                    target_pid = cand
                    break

            if not target_pid:
                target_pid = candidate_pids[0] if candidate_pids else "ag-orch-fallback"

            try:
                res = discover_models(profile_id=target_pid)
                if res:
                    return sorted(list(set(res.values()))), None
                return None, "Модели Google Antigravity не обнаружены"
            except Exception as exc:
                return None, str(exc)

        elif prov in ("openai-codex", "codex"):
            profiles = self._get_provider_candidate_profiles("openai-codex")
            last_err = None
            for pid, pcfg in profiles:
                auth = ProfileAuthManager.load_profile_auth("openai-codex", pid) or {}
                tokens = auth.get("token") or auth.get("tokens") or auth
                access_token = (
                    tokens.get("access_token")
                    if isinstance(tokens, dict)
                    else auth.get("api_key") or auth.get("access_token")
                )
                if not access_token:
                    continue
                base_url = (pcfg.custom_base_url if pcfg else None) or auth.get("base_url") or "https://api.openai.com/v1"
                base_url = str(base_url).strip().rstrip("/")
                if not base_url.startswith(("http://", "https://")):
                    base_url = f"https://{base_url}"
                try:
                    req = urllib.request.Request(
                        f"{base_url}/models",
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
                            if chat_models or models:
                                return sorted(chat_models or models), None
                except urllib.error.HTTPError as http_err:
                    last_err = self._extract_http_error(http_err)
                    logger.debug("Codex model query HTTP error on %s: %s", pid, last_err)
                except Exception as exc:
                    last_err = str(exc).strip() or type(exc).__name__
                    logger.debug("Codex model query failed on %s: %s", pid, exc)
            return None, last_err or "Отсутствуют учетные данные для OpenAI Codex"

        elif prov in ("opencode-go", "opencode"):
            profiles = self._get_provider_candidate_profiles("opencode-go")
            last_err = None
            for pid, pcfg in profiles:
                auth = ProfileAuthManager.load_profile_auth("opencode-go", pid) or {}
                api_key = auth.get("api_key")
                if not api_key:
                    continue
                base_url = (pcfg.custom_base_url if pcfg else None) or auth.get("base_url") or "https://opencode.ai/zen/go/v1"
                base_url = str(base_url).strip().rstrip("/")
                if not base_url.startswith(("http://", "https://")):
                    base_url = f"https://{base_url}"
                try:
                    req = urllib.request.Request(
                        f"{base_url}/models",
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
                            if models:
                                return sorted(models), None
                except urllib.error.HTTPError as http_err:
                    last_err = self._extract_http_error(http_err)
                    logger.debug("OpenCode model query HTTP error on %s: %s", pid, last_err)
                except Exception as exc:
                    last_err = str(exc).strip() or type(exc).__name__
                    logger.debug("OpenCode model query failed on %s: %s", pid, exc)
            return None, last_err or "Отсутствуют учетные данные для OpenCode Go"

        elif prov in ("grok", "xai"):
            profiles = self._get_provider_candidate_profiles("grok")
            last_err = None
            for pid, pcfg in profiles:
                auth = ProfileAuthManager.load_profile_auth("grok", pid) or {}
                tokens = auth.get("token") or auth.get("tokens") or {}
                token = tokens.get("access_token") if isinstance(tokens, dict) else None
                token = token or auth.get("access_token") or auth.get("api_key")
                if not token:
                    continue
                base_url = (pcfg.custom_base_url if pcfg else None) or auth.get("base_url") or "https://api.x.ai/v1"
                base_url = str(base_url).strip().rstrip("/")
                if not base_url.startswith(("http://", "https://")):
                    base_url = f"https://{base_url}"
                try:
                    req = urllib.request.Request(
                        f"{base_url}/models",
                        headers={"Authorization": f"Bearer {token}", "Accept": "application/json", "User-Agent": "hermes-hub/1.0"},
                    )
                    with urllib.request.urlopen(req, timeout=15) as response:
                        payload = json.loads(response.read().decode("utf-8") or "{}")
                    models = [
                        str(item.get("id"))
                        for item in (payload.get("data") or [])
                        if isinstance(item, dict) and item.get("id")
                    ]
                    if models:
                        return sorted(set(models)), None
                except urllib.error.HTTPError as http_err:
                    last_err = self._extract_http_error(http_err)
                    logger.debug("Grok model discovery HTTP error for %s: %s", pid, last_err)
                except Exception as exc:
                    last_err = str(exc).strip() or type(exc).__name__
                    logger.debug("Grok model discovery failed for %s: %s", pid, exc)
            return None, last_err or "Отсутствуют учетные данные для Grok"

        elif prov in ("claude", "anthropic"):
            profiles = self._get_provider_candidate_profiles("claude")
            last_err = None
            for pid, pcfg in profiles:
                auth = ProfileAuthManager.load_profile_auth("claude", pid) or {}
                tokens = auth.get("token") or auth.get("tokens") or {}
                token = tokens.get("access_token") if isinstance(tokens, dict) else None
                token = token or auth.get("access_token") or auth.get("api_key") or os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("CLAUDE_API_KEY")
                if not token:
                    continue
                base_url = (pcfg.custom_base_url if pcfg else None) or auth.get("base_url") or "https://api.anthropic.com/v1"
                base_url = str(base_url).strip().rstrip("/")
                if not base_url.startswith(("http://", "https://")):
                    base_url = f"https://{base_url}"
                headers = {
                    "Accept": "application/json",
                    "anthropic-version": "2023-06-01",
                    "User-Agent": "hermes-hub/1.0",
                }
                if token.startswith("sk-ant-"):
                    headers["x-api-key"] = token
                else:
                    headers["Authorization"] = f"Bearer {token}"
                    headers["anthropic-beta"] = "oauth-2025-04-20"
                try:
                    req = urllib.request.Request(f"{base_url}/models", headers=headers)
                    with urllib.request.urlopen(req, timeout=10) as resp:
                        payload = json.loads(resp.read().decode("utf-8") or "{}")
                        items = payload.get("data") or payload.get("models") or []
                        models = [str(item.get("id") or item) for item in items if item]
                        if models:
                            return sorted(set(models)), None
                except urllib.error.HTTPError as http_err:
                    last_err = self._extract_http_error(http_err)
                except Exception as exc:
                    last_err = str(exc).strip() or type(exc).__name__
            return None, last_err or "Отсутствуют учетные данные для Claude"

        elif prov in ("openrouter",):
            profiles = self._get_provider_candidate_profiles("openrouter")
            last_err = None
            for pid, pcfg in profiles:
                auth = ProfileAuthManager.load_profile_auth("openrouter", pid) or {}
                api_key = auth.get("api_key") or auth.get("token") or os.environ.get("OPENROUTER_API_KEY")
                if not api_key:
                    continue
                base_url = (pcfg.custom_base_url if pcfg else None) or auth.get("base_url") or os.environ.get("OPENROUTER_BASE_URL") or "https://openrouter.ai/api/v1"
                base_url = str(base_url).strip().rstrip("/")
                if not base_url.startswith(("http://", "https://")):
                    base_url = f"https://{base_url}"

                referer = (
                    os.environ.get("OPENROUTER_HTTP_REFERER")
                    or os.environ.get("HERMES_REFERER")
                    or "https://github.com/ochenstarik-ui/hermes-hub"
                )
                title = (
                    os.environ.get("OPENROUTER_APP_TITLE")
                    or os.environ.get("OPENROUTER_TITLE")
                    or "Hermes Hub"
                )
                headers = {
                    "Authorization": f"Bearer {api_key}",
                    "HTTP-Referer": referer,
                    "X-OpenRouter-Title": title,
                    "X-Title": title,
                    "Accept": "application/json",
                    "User-Agent": "hermes-hub/1.0",
                }
                try:
                    req = urllib.request.Request(f"{base_url}/models", headers=headers)
                    with urllib.request.urlopen(req, timeout=15) as resp:
                        payload = json.loads(resp.read().decode("utf-8") or "{}")
                        items = payload.get("data") or payload.get("models") or []
                        models = []
                        if isinstance(items, list):
                            for item in items:
                                mid = item.get("id") if isinstance(item, dict) else str(item)
                                if mid:
                                    models.append(str(mid))
                        if models:
                            return sorted(set(models)), None
                except urllib.error.HTTPError as http_err:
                    last_err = self._extract_http_error(http_err)
                    logger.debug("OpenRouter model discovery HTTP error for %s: %s", pid, last_err)
                except Exception as exc:
                    last_err = str(exc).strip() or type(exc).__name__
                    logger.debug("OpenRouter model discovery failed for %s: %s", pid, exc)
            return None, last_err or "Отсутствуют учетные данные для OpenRouter"

        elif prov in ("nvidia", "nvidia-nim"):
            profiles = self._get_provider_candidate_profiles("nvidia")
            last_err = None
            for pid, pcfg in profiles:
                auth = ProfileAuthManager.load_profile_auth("nvidia", pid) or ProfileAuthManager.load_profile_auth("nvidia-nim", pid) or {}
                api_key = auth.get("api_key") or auth.get("token") or os.environ.get("NVIDIA_API_KEY") or os.environ.get("NV_API_KEY")
                if not api_key:
                    continue
                base_url = (pcfg.custom_base_url if pcfg else None) or auth.get("base_url") or os.environ.get("NVIDIA_BASE_URL") or "https://integrate.api.nvidia.com/v1"
                base_url = str(base_url).strip().rstrip("/")
                if not base_url.startswith(("http://", "https://")):
                    base_url = f"https://{base_url}"

                headers = {
                    "Authorization": f"Bearer {api_key}",
                    "Accept": "application/json",
                    "User-Agent": "hermes-hub/1.0",
                }
                try:
                    req = urllib.request.Request(f"{base_url}/models", headers=headers)
                    with urllib.request.urlopen(req, timeout=15) as resp:
                        payload = json.loads(resp.read().decode("utf-8") or "{}")
                        items = payload.get("data") or payload.get("models") or []
                        models = []
                        if isinstance(items, list):
                            for item in items:
                                mid = item.get("id") if isinstance(item, dict) else str(item)
                                if mid:
                                    models.append(str(mid))
                        if models:
                            return sorted(set(models)), None
                except urllib.error.HTTPError as http_err:
                    last_err = self._extract_http_error(http_err)
                    logger.debug("NVIDIA model discovery HTTP error for %s: %s", pid, last_err)
                except Exception as exc:
                    last_err = str(exc).strip() or type(exc).__name__
                    logger.debug("NVIDIA model discovery failed for %s: %s", pid, exc)
            return None, last_err or "Отсутствуют учетные данные для NVIDIA NIM"

        elif prov == "ollama":
            profiles = self._get_provider_candidate_profiles("ollama")
            last_err = None
            for pid, pcfg in profiles:
                auth = ProfileAuthManager.load_profile_auth("ollama", pid) or {}
                raw_url = (pcfg.custom_base_url if pcfg else None) or auth.get("base_url") or os.environ.get("OLLAMA_BASE_URL") or os.environ.get("OLLAMA_HOST") or "http://127.0.0.1:11434"
                raw_url = str(raw_url).strip().rstrip("/")
                if not raw_url.startswith(("http://", "https://")):
                    raw_url = f"http://{raw_url}"

                native_host = raw_url[:-3] if raw_url.endswith("/v1") else raw_url
                v1_url = raw_url if raw_url.endswith("/v1") else f"{raw_url}/v1"

                token = auth.get("api_key") or auth.get("token") or os.environ.get("OLLAMA_API_KEY")
                headers = {
                    "Accept": "application/json",
                    "User-Agent": "hermes-hub/1.0",
                }
                if token:
                    headers["Authorization"] = f"Bearer {token}"

                # 1. Try native Ollama endpoint /api/tags
                try:
                    req = urllib.request.Request(f"{native_host}/api/tags", headers=headers)
                    with urllib.request.urlopen(req, timeout=5) as resp:
                        data = json.loads(resp.read().decode("utf-8", errors="replace") or "{}")
                        items = data.get("models") or []
                        models = []
                        if isinstance(items, list):
                            for m in items:
                                name = m.get("name") or m.get("model") if isinstance(m, dict) else str(m)
                                if name:
                                    models.append(str(name))
                        return sorted(set(models)), None
                except urllib.error.HTTPError as http_err:
                    last_err = self._extract_http_error(http_err)
                    logger.debug("Ollama /api/tags HTTP error on %s: %s", pid, last_err)
                except Exception as exc:
                    last_err = str(exc).strip() or type(exc).__name__
                    logger.debug("Ollama /api/tags query failed on %s: %s", pid, exc)

                # 2. Try OpenAI-compatible endpoint /v1/models
                try:
                    req = urllib.request.Request(f"{v1_url}/models", headers=headers)
                    with urllib.request.urlopen(req, timeout=5) as resp:
                        data = json.loads(resp.read().decode("utf-8", errors="replace") or "{}")
                        items = data.get("data") or data.get("models") or []
                        models = []
                        if isinstance(items, list):
                            for m in items:
                                mid = m.get("id") or m.get("name") if isinstance(m, dict) else str(m)
                                if mid:
                                    models.append(str(mid))
                        return sorted(set(models)), None
                except urllib.error.HTTPError as http_err:
                    last_err = self._extract_http_error(http_err)
                    logger.debug("Ollama /v1/models HTTP error on %s: %s", pid, last_err)
                except Exception as exc:
                    last_err = str(exc).strip() or type(exc).__name__
                    logger.debug("Ollama /v1/models query failed on %s: %s", pid, exc)

            return None, last_err or "Не удалось подключиться к серверу Ollama"

        elif prov in ("local", "local-llm", "llama.cpp", "vllm"):
            profiles = self._get_provider_candidate_profiles("local")
            last_err = None
            for pid, pcfg in profiles:
                auth = ProfileAuthManager.load_profile_auth("local", pid) or {}
                base_url = (pcfg.custom_base_url if pcfg else None) or auth.get("base_url") or os.environ.get("LOCAL_LLM_BASE_URL") or "http://127.0.0.1:8081/v1"
                base_url = str(base_url).strip().rstrip("/")
                if not base_url.startswith(("http://", "https://")):
                    base_url = f"http://{base_url}"

                api_key = auth.get("api_key") or os.environ.get("LOCAL_LLM_API_KEY")
                headers = {
                    "Accept": "application/json",
                    "User-Agent": "hermes-hub/1.0",
                }
                if api_key:
                    headers["Authorization"] = f"Bearer {api_key}"
                try:
                    req = urllib.request.Request(f"{base_url}/models", headers=headers)
                    with urllib.request.urlopen(req, timeout=5) as resp:
                        data = json.loads(resp.read().decode("utf-8", errors="replace") or "{}")
                        items = data.get("data") or data.get("models") or []
                        if isinstance(items, list):
                            models = [
                                str(m.get("id") or m.get("name") if isinstance(m, dict) else m)
                                for m in items
                                if m
                            ]
                            return sorted(set(models)), None
                except urllib.error.HTTPError as http_err:
                    last_err = self._extract_http_error(http_err)
                    logger.debug("Local LLM model query HTTP error on %s (%s): %s", pid, base_url, last_err)
                except Exception as exc:
                    last_err = str(exc).strip() or type(exc).__name__
                    logger.debug("Local LLM model query failed on %s (%s): %s", pid, base_url, exc)
            return None, last_err or "Не удалось подключиться к локальному серверу LLM"

        return None, f"Неизвестный провайдер: {provider}"
