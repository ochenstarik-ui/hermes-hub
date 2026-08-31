"""Local LLM OpenAI-compatible provider adapter for llama.cpp / vLLM / Ollama."""
from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

from ..router_config import RouterProfileConfig
from .base_adapter import BaseProviderAdapter, ErrorCategory, ErrorClassification, extract_api_error_message

logger = logging.getLogger("hermes.router.adapter.local")

DEFAULT_LOCAL_BASE_URL = "http://127.0.0.1:8081/v1"
DEFAULT_LOCAL_MODELS = ["default"]


class LocalLLMAdapter(BaseProviderAdapter):
    """Adapter for local OpenAI-compatible chat completion servers (llama.cpp, Ollama, vLLM)."""

    def _resolve_base_url(self, profile: RouterProfileConfig) -> str:
        """Resolve base_url from profile custom_base_url, auth_config, or environment."""
        url = (
            profile.custom_base_url
            or profile.auth_config.get("base_url")
            or os.environ.get("LOCAL_LLM_BASE_URL")
            or DEFAULT_LOCAL_BASE_URL
        )
        url_str = str(url).strip().rstrip("/")
        if not url_str.startswith(("http://", "https://")):
            url_str = f"http://{url_str}"
        return url_str

    def _resolve_api_key(self, profile: RouterProfileConfig) -> Optional[str]:
        """Resolve optional API key from profile auth_config or environment."""
        key = profile.auth_config.get("api_key") or profile.auth_config.get("token")
        if key:
            return str(key).strip()

        suffix = profile.profile_id.upper().replace("-", "_")
        for candidate in (f"LOCAL_LLM_API_KEY_{suffix}", "LOCAL_LLM_API_KEY", "LOCAL_API_KEY"):
            val = os.environ.get(candidate, "").strip()
            if val:
                return val
        return None

    _context_window_cache: Dict[str, int] = {}

    def get_context_window(
        self,
        profile: RouterProfileConfig,
        model: Optional[str] = None,
        query_remote: bool = False,
    ) -> Optional[int]:
        """Fetch actual context_window / max_context_length from profile config or /models endpoint.
        
        Never invents or hardcodes defaults. Returns None if unknown.
        """
        # 1. Profile auth_config / custom settings
        for key in ("context_window", "context_length", "max_context_length", "max_tokens_limit", "n_ctx"):
            if key in profile.auth_config and profile.auth_config[key]:
                try:
                    return int(profile.auth_config[key])
                except (ValueError, TypeError):
                    pass

        # 2. In-memory cache from previous model discovery
        cache_key = f"{profile.profile_id}:{model or 'default'}"
        if cache_key in self._context_window_cache:
            return self._context_window_cache[cache_key]
        if f"{profile.profile_id}:all" in self._context_window_cache:
            return self._context_window_cache[f"{profile.profile_id}:all"]

        if not query_remote:
            return None

        # 3. Query /props endpoint (llama.cpp native)
        base_url = self._resolve_base_url(profile)
        # Strip trailing /v1 for props endpoint if needed
        root_url = base_url[:-3] if base_url.endswith("/v1") else base_url
        try:
            req_props = urllib.request.Request(f"{root_url}/props", headers={"User-Agent": "hermes-router/1.0"}, method="GET")
            with urllib.request.urlopen(req_props, timeout=2) as resp:
                p_data = json.loads(resp.read().decode("utf-8", errors="replace"))
                n_ctx = p_data.get("default_generation_settings", {}).get("n_ctx") or p_data.get("n_ctx")
                if n_ctx:
                    ctx_val = int(n_ctx)
                    self._context_window_cache[f"{profile.profile_id}:all"] = ctx_val
                    return ctx_val
        except Exception:
            pass

        # 4. Query /models endpoint
        api_key = self._resolve_api_key(profile)
        headers = {"Accept": "application/json", "User-Agent": "hermes-router/1.0"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        req = urllib.request.Request(f"{base_url}/models", headers=headers, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=3) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="replace"))
                items = data.get("data") or data.get("models") or []
                if isinstance(items, list):
                    for m in items:
                        if isinstance(m, dict):
                            m_id = str(m.get("id") or m.get("name") or "")
                            for ck in ("context_window", "context_length", "max_model_len", "max_context_length", "n_ctx"):
                                if ck in m and m[ck]:
                                    try:
                                        ctx_val = int(m[ck])
                                        self._context_window_cache[f"{profile.profile_id}:{m_id}"] = ctx_val
                                        self._context_window_cache[f"{profile.profile_id}:all"] = ctx_val
                                        if not model or m_id == model or model in m_id or m_id in model or len(items) == 1:
                                            return ctx_val
                                    except (ValueError, TypeError):
                                        pass
                            meta = m.get("meta") or {}
                            if isinstance(meta, dict):
                                for ck in ("n_ctx", "context_length", "max_context_length"):
                                    if ck in meta and meta[ck]:
                                        try:
                                            ctx_val = int(meta[ck])
                                            self._context_window_cache[f"{profile.profile_id}:{m_id}"] = ctx_val
                                            self._context_window_cache[f"{profile.profile_id}:all"] = ctx_val
                                            if not model or m_id == model or model in m_id or m_id in model or len(items) == 1:
                                                return ctx_val
                                        except (ValueError, TypeError):
                                            pass
        except Exception as exc:
            logger.debug("Failed to query context window from server for %s: %s", profile.profile_id, exc)

        return None

    def invoke(self, profile: RouterProfileConfig, request: Dict[str, Any]) -> Dict[str, Any]:
        base_url = self._resolve_base_url(profile)
        api_key = self._resolve_api_key(profile)

        model = request.get("model", "")
        if not model or model == "default":
            model = profile.preferred_models[0] if profile.preferred_models else "default"

        messages = list(request.get("messages", []))

        # Context Compression & Truncation Guard
        context_window = self.get_context_window(profile, model, query_remote=False)
        if context_window is not None and context_window > 0 and len(messages) > 1:
            from antigravity_provider.router.settings_service import get_hub_settings
            from antigravity_provider.router.local_supervisor import LocalSupervisor
            from antigravity_provider.router.router_config import load_router_config

            hub_settings = get_hub_settings()
            threshold_pct = float(hub_settings.get("compression_threshold_percent", 75.0))
            keep_recent = int(hub_settings.get("compression_keep_recent_messages", 3))
            compressor_pid = hub_settings.get("compressor_profile_id")

            compressor_pconfig = None
            if compressor_pid:
                try:
                    rcfg = load_router_config()
                    compressor_pconfig = rcfg.get_profile(compressor_pid)
                except Exception:
                    pass

            supervisor = LocalSupervisor(base_url=base_url)
            messages, outcome = supervisor.compress_context_if_needed(
                messages=messages,
                target_context_limit=context_window,
                compressor_profile=compressor_pconfig,
                threshold_percent=threshold_pct,
                keep_recent_messages=keep_recent,
            )

            # Secondary Safety Guard: if still exceeding token budget (e.g. huge single message or compressor disabled/failed)
            max_tok = int(request.get("max_tokens", 0) or 0)
            token_budget = context_window - max_tok - 64
            if token_budget > 100:
                def _est_tok(msgs: list) -> int:
                    total_chars = sum(len(str(m.get("content", ""))) for m in msgs if isinstance(m, dict))
                    return int(total_chars / 3.5) + len(msgs) * 4

                if _est_tok(messages) > token_budget:
                    logger.warning(
                        "Context safety boundary active for %s: prompt exceeds token budget (%d). Truncating middle messages.",
                        profile.profile_id,
                        context_window,
                    )
                    system_msg = [messages[0]] if messages and messages[0].get("role") == "system" else []
                    last_msg = messages[-1]
                    middle = messages[1:-1] if system_msg else messages[:-1]

                    while middle and _est_tok(system_msg + middle + [last_msg]) > token_budget:
                        middle.pop(0)

                    if _est_tok(system_msg + middle + [last_msg]) > token_budget:
                        avail_chars = max(100, int(token_budget * 3.0))
                        last_copy = dict(last_msg)
                        last_copy["content"] = str(last_copy.get("content", ""))[-avail_chars:]
                        messages = system_msg + middle + [last_copy]
                    else:
                        messages = system_msg + middle + [last_msg]


        payload: Dict[str, Any] = {
            "model": model,
            "messages": messages,
        }
        if "temperature" in request:
            payload["temperature"] = request["temperature"]
        elif isinstance(profile.request_options, dict) and "temperature" in profile.request_options:
            payload["temperature"] = profile.request_options["temperature"]
        else:
            payload["temperature"] = request.get("temperature", 0.7)

        if "tools" in request and request["tools"]:
            payload["tools"] = request["tools"]
        if "tool_choice" in request:
            payload["tool_choice"] = request["tool_choice"]
        if "response_format" in request:
            payload["response_format"] = request["response_format"]
        if "max_tokens" in request:
            payload["max_tokens"] = request["max_tokens"]
        if "stream" in request:
            payload["stream"] = request["stream"]
        if "stop" in request:
            payload["stop"] = request["stop"]

        # Mix in request_options from profile (generic, supports any arbitrary keys & nested structures)
        req_options = profile.request_options if isinstance(profile.request_options, dict) else {}
        for opt_key, opt_val in req_options.items():
            if opt_key == "temperature":
                if "temperature" in request and request["temperature"] != opt_val:
                    logger.warning(
                        "Profile %s request_option '%s' (%r) ignored: request specified explicit value (%r)",
                        profile.profile_id,
                        opt_key,
                        opt_val,
                        request["temperature"],
                    )
                continue

            if opt_key in request:
                req_val = request[opt_key]
                if req_val != opt_val:
                    logger.warning(
                        "Profile %s request_option '%s' (%r) ignored: request specified explicit value (%r)",
                        profile.profile_id,
                        opt_key,
                        opt_val,
                        req_val,
                    )
            elif opt_key in payload:
                if payload[opt_key] != opt_val:
                    logger.warning(
                        "Profile %s request_option '%s' (%r) ignored: payload contains (%r)",
                        profile.profile_id,
                        opt_key,
                        opt_val,
                        payload[opt_key],
                    )
            else:
                payload[opt_key] = opt_val

        headers: Dict[str, str] = {
            "Content-Type": "application/json",
            "User-Agent": "hermes-router/1.0",
        }
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        req = urllib.request.Request(
            f"{base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="replace"))
        except urllib.error.HTTPError as http_err:
            raw_err = http_err.read().decode("utf-8", errors="replace")
            try:
                err_msg = extract_api_error_message(raw_err)
            except Exception:
                err_msg = raw_err
            raise RuntimeError(f"Local LLM API Error ({http_err.code}): {err_msg}") from http_err
        except Exception as exc:
            raise RuntimeError(f"Local LLM Transport Error: {exc}") from exc

        # Проверка ПОСЛЕ блока перехвата: иначе отказ по пустому ответу
        # оборачивался в «Transport Error», хотя транспорт отработал штатно.
        self._reject_empty_answer(data)
        return data



    @staticmethod
    def _reject_empty_answer(data: Dict[str, Any]) -> None:
        """Пустой ответ — это отказ, а не успех.

        Сервер владельца поднят с ``--reasoning on --reasoning-budget 4096``.
        При скромном ``max_tokens`` весь бюджет уходит на рассуждения: модель
        возвращает 200, заполняет ``reasoning_content`` и оставляет ``content``
        пустым. Проверено на живой модели: с max_tokens=40 ответа нет, с 200 —
        приходит «ОК».

        Если отдать такой ответ дальше как успешный, роутер засчитает вызов, а
        пользователь не получит ничего и не узнает почему. Поэтому отказываем
        явно — тогда сработает переключение на следующий профиль.
        """
        choices = data.get("choices") or []
        if not choices:
            raise RuntimeError("Local LLM вернул ответ без choices")

        message = choices[0].get("message") or {}
        content = (message.get("content") or "").strip()
        if content:
            return

        finish = choices[0].get("finish_reason")
        if message.get("reasoning_content"):
            raise RuntimeError(
                "Local LLM израсходовал лимит токенов на рассуждения и не выдал ответ "
                f"(finish_reason={finish}). Увеличьте max_tokens или уменьшите "
                "--reasoning-budget на сервере."
            )
        raise RuntimeError(f"Local LLM вернул пустой ответ (finish_reason={finish})")

    def discover_models(self, profile: RouterProfileConfig) -> List[str]:
        """Request GET {base_url}/models with short timeout (5s) and return list of model IDs."""
        base_url = self._resolve_base_url(profile)
        api_key = self._resolve_api_key(profile)

        headers: Dict[str, str] = {
            "Accept": "application/json",
            "User-Agent": "hermes-router/1.0",
        }
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        req = urllib.request.Request(
            f"{base_url}/models",
            headers=headers,
            method="GET",
        )

        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="replace"))
                items = data.get("data") or data.get("models") or []
                if isinstance(items, list):
                    models = [
                        str(m.get("id") or m.get("name") if isinstance(m, dict) else m)
                        for m in items
                        if m
                    ]
                    if models:
                        return sorted(models)
        except Exception as exc:
            logger.debug("Failed to discover models for local profile %s: %s", profile.profile_id, exc)

        return list(profile.preferred_models or DEFAULT_LOCAL_MODELS)

    def health_check(self, profile: RouterProfileConfig) -> bool:
        """Fast GET {base_url}/models probe (2-3s). Returns True on success, False on error."""
        base_url = self._resolve_base_url(profile)
        api_key = self._resolve_api_key(profile)

        headers: Dict[str, str] = {
            "Accept": "application/json",
            "User-Agent": "hermes-router/1.0",
        }
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        req = urllib.request.Request(
            f"{base_url}/models",
            headers=headers,
            method="GET",
        )

        try:
            with urllib.request.urlopen(req, timeout=3) as resp:
                return resp.status in (200, 204)
        except Exception:
            return False

    def classify_error(
        self,
        exc: Exception,
        response_data: Optional[Dict[str, Any]] = None,
    ) -> ErrorClassification:
        """Classify execution failure into structured error category."""
        err_msg = str(exc)
        err_lower = err_msg.lower()

        # 429 Rate limited
        if "429" in err_lower or "rate limit" in err_lower or "too many requests" in err_lower:
            return ErrorClassification(
                category=ErrorCategory.RATE_LIMITED,
                message=err_msg,
                retry_delay_seconds=30,
            )

        # 401 / 403 Auth required
        if any(k in err_lower for k in ("401", "403", "unauthorized", "forbidden", "invalid api key", "authentication")):
            return ErrorClassification(
                category=ErrorCategory.AUTH_REQUIRED,
                message=err_msg,
            )

        # 400 / Bad request / Invalid parameter / Unknown parameter
        if any(k in err_lower for k in ("400", "invalid_request", "bad request", "unknown parameter", "invalid parameter", "unknown field", "unrecognized field")):
            return ErrorClassification(
                category=ErrorCategory.INVALID_REQUEST,
                message=err_msg,
                retry_delay_seconds=300,
            )

        # Quota exhausted
        if any(k in err_lower for k in ("quota", "insufficient balance", "insufficient_quota")):
            return ErrorClassification(
                category=ErrorCategory.QUOTA_EXHAUSTED,
                message=err_msg,
                reset_duration_seconds=1800,
            )

        # Network failures / Connection refused / Timeout / 502, 503, 504 / Transport error
        # Classified as TRANSIENT with short retry delay (2s) for instant failover
        if any(k in err_lower for k in (
            "connection refused", "connection error", "connect", "refused",
            "timeout", "timed out", "502", "503", "504", "gateway",
            "econnrefused", "econnreset", "transport error", "urlerror",
            "winerror 10061", "nodename nor servname provided",
        )):
            return ErrorClassification(
                category=ErrorCategory.TRANSIENT,
                message=err_msg,
                retry_delay_seconds=2,
            )

        return ErrorClassification(category=ErrorCategory.TRANSIENT, message=err_msg, retry_delay_seconds=2)
