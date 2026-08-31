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
            # Каталог NVIDIA общий для всех, а доступ к конкретной модели даётся
            # по аккаунту. Успешный список уже доказывает, что ключ рабочий:
            # сервер опознал аккаунт и ответил. Пробный запрос — уточнение, а не
            # условие. Раньше его отказ («Function ... Not found for account»)
            # объявлялся провалом подключения, хотя ключ был верным.
            chat_models = [model for model in models if any(word in model.lower() for word in ('instruct', 'chat')) and not any(word in model.lower() for word in ('embed', 'guard', 'reward'))]
            probe_target = preferred_model or (chat_models[0] if chat_models else None)
            if probe_target:
                try:
                    result = request("/chat/completions", {"model": probe_target,
                        "messages": [{"role": "user", "content": "ping"}], "max_tokens": 1})
                    if not isinstance(result.get("choices"), list) or not result["choices"]:
                        probe_note = f"модель {probe_target} не вернула результат"
                    else:
                        probe_note = ""
                except Exception as probe_exc:
                    # 401 и 403 — ключ отвергнут, это отказ подключения.
                    # 404 и прочее — ключ принят, но модель аккаунту не выдана:
                    # NVIDIA отвечает «Function ... Not found for account <id>»,
                    # то есть аккаунт опознан. Валить подключение из-за этого нельзя.
                    code = getattr(probe_exc, "code", None)
                    if code in (401, 403):
                        raise
                    probe_note = f"модель {probe_target} недоступна вашему аккаунту ({str(probe_exc)[:120]})"
            else:
                probe_note = "чат-модель для пробы не найдена"
            if probe_note:
                return {"ok": True, "data": {"models": models, "base_url": base_url},
                        "message": f"Ключ принят, моделей в каталоге: {len(models)}. Проба: {probe_note}. Выберите доступную модель."}
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
