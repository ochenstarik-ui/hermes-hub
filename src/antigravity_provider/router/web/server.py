import json
import secrets
import os
import sys
import threading
import time
import dataclasses
import logging
from typing import Any, Dict, List, Optional

from antigravity_provider import paths
from antigravity_provider.version import __version__
from fastapi import FastAPI, Request, HTTPException, Depends, Header
from pathlib import Path

from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.encoders import jsonable_encoder

from antigravity_provider.router.state_store import HubStateStore
from antigravity_provider.router.action_handler import ActionExecutor
from antigravity_provider.router.router_config import load_router_config

logger = logging.getLogger("hermes.router.web")

app = FastAPI(title="Hermes Hub Web API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _web_settings() -> Dict[str, Any]:
    """Настройки веб-API живут в hub_settings.json, а не в RouterConfig."""
    from antigravity_provider.router.settings_service import get_hub_settings
    return get_hub_settings()


def get_auth_token(x_hub_token: str = Header(None)) -> bool:
    settings = _web_settings()
    server_host = settings.get('web_api_host', '127.0.0.1')
    
    if server_host != '127.0.0.1':
        required_token = settings.get('web_api_token', '')
        if not required_token:
            raise HTTPException(status_code=500, detail="Server misconfigured: external bind requires a token")
        # Сравнение постоянного времени — требование раздела 3 контракта,
        # которое до сих пор не было выполнено: стояло обычное !=, дающее
        # утечку по времени посимвольного сравнения. Заголовок может быть
        # None, поэтому приводим к строке до сравнения.
        # Сравниваем в байтах: compare_digest со строками запрещает не-ASCII
        # и падает TypeError, то есть токен с кириллицей давал бы 500 вместо
        # честного отказа.
        _given = str(x_hub_token or '').encode('utf-8')
        _needed = str(required_token).encode('utf-8')
        if not secrets.compare_digest(_given, _needed):
            raise HTTPException(status_code=401, detail="Invalid X-Hub-Token")
    return True

@app.get("/api/health")
def health_check():
    return {
        "ok": True,
        "version": __version__,
        # Antigravity и Claude раньше стояли здесь как supported: False с
        # советом идти в десктоп или пробрасывать порты. Это было неверно:
        # ProfileOAuthSession.handle_manual_callback_url и
        # ClaudeOAuthSession.handle_auth_code принимают вставленное вручную
        # значение, поэтому браузер нужен где угодно, а не на машине с Hub.
        "auth_flows": {
            "openai-codex": {"supported": True, "reason": "device-code"},
            "grok": {"supported": True, "reason": "device-code"},
            "opencode-go": {"supported": True, "reason": "token"},
            "antigravity": {
                "supported": True,
                "reason": "redirect-url-paste",
                "hint": "Откройте ссылку в любом браузере и верните адрес из адресной строки",
            },
            "claude": {
                "supported": True,
                "reason": "code-paste",
                "hint": "Откройте ссылку в любом браузере и верните показанный код",
            },
        }
    }

def sanitize_snapshot(snap_dict: Any) -> Any:
    import re
    secret_patterns = [
        re.compile(r'((?:access_token|refresh_token|api_key|token|password|secret|key)=)([^\s&,"]+)', re.IGNORECASE),
        re.compile(r'(sk-[a-zA-Z0-9_\-]{8,})'),
        re.compile(r'(gho_[a-zA-Z0-9_\-]{8,})'),
        re.compile(r'(Bearer\s+)([a-zA-Z0-9_\-\.]{8,})', re.IGNORECASE),
    ]

    def _mask_str(val: str) -> str:
        res = val
        for pat in secret_patterns:
            if pat.groups == 2:
                res = pat.sub(r'\g<1>***', res)
            elif pat.groups == 1:
                res = pat.sub(r'***', res)
        return res

    def _sanitize(node):
        if isinstance(node, dict):
            return {
                k: _sanitize(v) for k, v in node.items()
                if not any(secret in k.lower() for secret in ['access_token', 'refresh_token', 'api_key', 'jwt', 'client_secret'])
            }
        elif isinstance(node, list):
            return [_sanitize(x) for x in node]
        elif isinstance(node, str):
            return _mask_str(node)
        return node
    return _sanitize(snap_dict)

@app.get("/api/snapshot")
def get_snapshot(authorized: bool = Depends(get_auth_token)):
    snapshot = HubStateStore.get().get_snapshot()
    if not snapshot:
        raise HTTPException(status_code=503, detail="Snapshot not ready")
    
    snap_dict = dataclasses.asdict(snapshot)
    snap_dict = sanitize_snapshot(snap_dict)
    
    return JSONResponse(content=jsonable_encoder(snap_dict))

@app.post("/api/action")
async def handle_action(request: Request, authorized: bool = Depends(get_auth_token)):
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")
        
    action = data.get("action")
    if not action:
        raise HTTPException(status_code=400, detail="Missing 'action'")
        
    def _async_runner(func, name):
        threading.Thread(target=func, name=name, daemon=True).start()
        
    result = ActionExecutor.execute(action, data.get("data", {}), async_runner=_async_runner)
    if result.get("unknown"):
        raise HTTPException(status_code=404, detail="Неизвестное действие")
        
    return {
        "ok": result.get("ok", False),
        "message": result.get("message", ""),
        "data": result.get("data", {})
    }


@app.get("/api/events")
def get_events(limit: int = 100, category: Optional[str] = None, authorized: bool = Depends(get_auth_token)):
    """Return recent events log in reverse chronological order without secrets."""
    from antigravity_provider.router.unified_health import EventLogService
    events = EventLogService.get().get_events(limit=limit, category=category)
    event_dicts = [dataclasses.asdict(e) for e in events]
    sanitized = sanitize_snapshot(event_dicts)
    return JSONResponse(content=jsonable_encoder({"events": sanitized}))


@app.get("/api/settings")
def get_settings(authorized: bool = Depends(get_auth_token)):
    """Return current server and hub settings without exposing raw auth tokens."""
    raw = _web_settings()
    has_token = bool(raw.get("web_api_token"))
    settings_out: Dict[str, Any] = {
        "web_api_host": raw.get("web_api_host", "127.0.0.1"),
        "web_api_port": raw.get("web_api_port", 5800),
        "web_api_token_configured": has_token,
        "theme": raw.get("theme", "system"),
        "quota_refresh_interval_sec": raw.get("quota_refresh_interval_sec", 300),
        "hermes_home": str(paths.get_hermes_home()),
        "config_dir": str(paths.get_config_dir()),
        "log_file": str(paths.get_log_file()),
    }
    for k, v in raw.items():
        if k not in settings_out and not any(secret in k.lower() for secret in ['token', 'secret', 'key', 'password', 'jwt']):
            settings_out[k] = v
    return JSONResponse(content=jsonable_encoder(settings_out))

def run_server():
    import uvicorn
    settings = _web_settings()
    host = settings.get('web_api_host', '127.0.0.1')
    port = int(settings.get('web_api_port', 5800))
    token = settings.get('web_api_token', '')
    
    if host != '127.0.0.1' and not token:
        logger.error("Cannot bind Web API externally without web_api_token")
        sys.exit(1)
        
    logger.info(f"Starting Hermes Hub Web API on {host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="warning")


# ─────────────────────────────────────────────────────────────
#  Статика: сервер обязан отдавать сам интерфейс, а не только API.
#  Контракт описывал каталог static/, но не назвал, кто его монтирует,
#  поэтому серверная и клиентская стороны сошлись в пустоту: API
#  отвечал, файлы лежали в репозитории, а в браузере был 404.
# ─────────────────────────────────────────────────────────────

_STATIC_DIR = Path(__file__).resolve().parent / "static"

if _STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    # Ассеты обязаны перепроверяться при каждой загрузке.
    # Без Cache-Control браузер применяет эвристическое кэширование и может
    # неделями отдавать старый app.js: интерфейс выглядит обновлённым (index.html
    # перепроверяется при навигации), а поведение остаётся от прошлой сборки.
    _NO_CACHE = {"Cache-Control": "no-cache, must-revalidate"}

    @app.get("/")
    @app.get("/index.html")
    def index():
        return FileResponse(str(_STATIC_DIR / "index.html"), headers=_NO_CACHE)

    @app.get("/app.js")
    def _app_js():
        return FileResponse(
            str(_STATIC_DIR / "app.js"),
            media_type="application/javascript",
            headers=_NO_CACHE,
        )

    @app.get("/style.css")
    def _style_css():
        return FileResponse(
            str(_STATIC_DIR / "style.css"),
            media_type="text/css",
            headers=_NO_CACHE,
        )

    @app.get("/snapshot.example.json")
    def _fixture():
        return FileResponse(str(_STATIC_DIR / "snapshot.example.json"), media_type="application/json")


# ─────────────────────────────────────────────────────────────
#  Фоновое обновление: прогрев квот и пересбор снапшота.
#
#  Две причины, по которым /api/snapshot отдавал пустые квоты навсегда:
#
#  1. state_store наполняет квоты через quota_service.get_snapshot, который
#     читает кэш и при промахе отдаёт пустую заглушку, живой опрос НЕ
#     запуская. В десктопе кэш грел _refresh_quotas_on_startup; в вебе
#     такого не было. Штатный планировщик службы сам по себе не спасает:
#     его цикл сначала спит интервал (по умолчанию 300 с) и только потом
#     опрашивает.
#
#  2. HubStateStore.get_snapshot() возвращает КЭШИРОВАННЫЙ снапшот и
#     пересобирает его лишь при самом первом вызове. Даже после прогрева
#     квот ответ оставался прежним. В десктопе пересбор делал _refresh_data.
# ─────────────────────────────────────────────────────────────

_SNAPSHOT_REFRESH_SEC = 30


def _background_refresh_loop() -> None:
    from antigravity_provider.router.quota_collector import AccountQuotaService

    try:
        AccountQuotaService.get().fetch_all_configured(force=True)
        logger.info("Quota cache warmed on startup")
    except Exception as exc:
        logger.warning("Quota warm-up failed: %s", exc)

    while True:
        try:
            HubStateStore.get().refresh(force_scan=False)
        except Exception as exc:
            logger.warning("Snapshot refresh failed: %s", exc)
        time.sleep(_SNAPSHOT_REFRESH_SEC)


@app.on_event("startup")
def _start_background_refresh() -> None:
    # В фоне: опрос ходит по сети к нескольким провайдерам, держать на нём
    # старт сервера нельзя.
    threading.Thread(target=_background_refresh_loop, daemon=True, name="hub-web-refresh").start()

    from antigravity_provider.router.quota_collector import AccountQuotaService

    try:
        AccountQuotaService.get().start_background_scheduler()
    except Exception as exc:
        logger.warning("Could not start quota scheduler: %s", exc)
