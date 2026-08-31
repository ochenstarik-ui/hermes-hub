"""Validate supplied credentials before creating any profile or writing auth files."""
import json
import urllib.error
import urllib.request
from urllib.parse import urlsplit

DEFAULT_URLS = {
    "openrouter": "https://openrouter.ai/api/v1",
    "nvidia": "https://integrate.api.nvidia.com/v1",
    "local": "http://127.0.0.1:8081/v1", "vllm": "http://127.0.0.1:8081/v1",
    "ollama": "http://127.0.0.1:11434", "claude": "https://api.anthropic.com/v1",
    "opencode-go": "https://opencode.ai/zen/go/v1", "grok": "https://api.x.ai/v1",
    "openai-codex": "https://api.openai.com/v1",
}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("Перенаправление API запрещено: укажите конечный URL сервера")


def validate_connection(provider, token="", base_url="", preferred_model=""):
    provider = {"nvidia-nim": "nvidia", "local-llm": "local", "llama.cpp": "local"}.get(provider, provider)
    try:
        base_url = (base_url or DEFAULT_URLS.get(provider, "")).rstrip("/")
        parsed = urlsplit(base_url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username is not None or parsed.password is not None or parsed.query or parsed.fragment:
            raise ValueError("Укажите HTTP(S) URL сервера без пароля, параметров и фрагмента")
        if provider not in DEFAULT_URLS:
            raise ValueError("Для этого провайдера используйте вход через авторизацию")
        if provider not in ("local", "vllm", "ollama") and not token:
            raise ValueError("Не указан API-ключ")
        headers = {"Content-Type": "application/json"}
        if provider == "claude":
            headers.update({"x-api-key": token, "anthropic-version": "2023-06-01"})
        elif token:
            headers["Authorization"] = "Bearer " + token
        opener = urllib.request.build_opener(_NoRedirect())

        def request(path, body=None):
            req = urllib.request.Request(base_url + path, headers=headers,
                data=json.dumps(body).encode() if body is not None else None)
            with opener.open(req, timeout=20) as response:
                payload = json.load(response)
            if not isinstance(payload, dict) or payload.get("error"):
                raise ValueError("Провайдер вернул ошибку или неверный JSON")
            return payload

        if provider == "openrouter":
            # The catalog is public: its HTTP 200 is not proof of a valid key.
            request("/key")
        if provider == "ollama":
            base_url = base_url.removesuffix("/v1")
            payload, field, key = request("/api/tags"), "models", "name"
        else:
            payload, field, key = request("/models"), "data", "id"
        entries = payload.get(field)
        if not isinstance(entries, list):
            raise ValueError("Провайдер не вернул список моделей")
        models = sorted({m[key] for m in entries if isinstance(m, dict) and isinstance(m.get(key), str) and m[key]})
        if provider == "nvidia":
            if not models:
                raise ValueError("Каталог NVIDIA пуст: проверить ключ тестовым запросом невозможно")
            if preferred_model and preferred_model not in models:
                raise ValueError("Выбранной модели нет в каталоге NVIDIA")
            # NVIDIA also exposes a public catalog. Validate with a real request.
            chat_models = [model for model in models if any(word in model.lower() for word in ('instruct', 'chat')) and not any(word in model.lower() for word in ('embed', 'guard', 'reward'))]
            if not preferred_model and not chat_models:
                raise ValueError("Ключ пока не проверен: в каталоге NVIDIA не найдена чат-модель для теста")
            result = request("/chat/completions", {"model": preferred_model or chat_models[0],
                "messages": [{"role": "user", "content": "ping"}], "max_tokens": 1})
            if not isinstance(result.get("choices"), list) or not result["choices"]:
                raise ValueError("NVIDIA не вернула результат тестового запроса")
        message = f"Подключено и проверено. Получено моделей: {len(models)}" if models else "Сервер отвечает; моделей пока нет"
        return {"ok": True, "message": message, "data": {"models": models, "base_url": base_url}}
    except Exception as exc:
        if isinstance(exc, urllib.error.HTTPError):
            reason = exc.reason or 'провайдер отклонил запрос'
            try:
                body = json.loads(exc.read(4096).decode('utf-8', errors='replace'))
                detail = body.get('error') or body.get('detail')
                if isinstance(detail, dict):
                    detail = detail.get('message')
                if isinstance(detail, str) and detail.strip():
                    reason = detail[:500]
            except Exception:
                pass
            message = f"HTTP {exc.code}: {reason}"
        else:
            message = str(exc).strip() or type(exc).__name__
        if token:
            message = message.replace(token, "[скрыто]")
        return {"ok": False, "message": message, "data": {"models": []}}
