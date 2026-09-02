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
from fastapi import FastAPI, Request, HTTPException, Depends, Header, Response
from pathlib import Path

from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.encoders import jsonable_encoder
from starlette.concurrency import run_in_threadpool

from antigravity_provider.router.state_store import HubStateStore
from antigravity_provider.router.action_handler import ActionExecutor
from antigravity_provider.router.router_config import load_router_config

from antigravity_provider.updater.update_manager import get_installed_commit, get_installed_build_time, UpdateManager

logger = logging.getLogger("hermes.router.web")

def _bootstrap_settings() -> Dict[str, Any]:
    """Настройки, нужные до объявления _web_settings (список источников CORS)."""
    try:
        from antigravity_provider.router.settings_service import get_hub_settings

        return get_hub_settings() or {}
    except Exception:
        return {}


app = FastAPI(title="Hermes Hub Web API", version="1.0.0")

# Межсайтовые запросы запрещены по умолчанию.
#
# Стояло allow_origins=["*"] вместе с allow_credentials=True. FastAPI в таком
# сочетании отражает любой присланный Origin обратно, поэтому проверено
# запросом: страница с https://evil.example.com получала
#   access-control-allow-origin: https://evil.example.com
#   access-control-allow-credentials: true
# на 200 от /api/snapshot.
#
# Опаснее всего это на localhost: там токен не требуется вовсе (см.
# get_auth_token), а значит ЛЮБОЙ сайт, открытый во вкладке рядом, мог читать
# снапшот со всеми аккаунтами и почтами и вызывать /api/action — удалять
# учётные данные, менять маршрутизацию, запускать входы OAuth.
#
# Собственному интерфейсу CORS не нужен: он отдаётся тем же сервером. Список
# разрешённых источников оставлен настройкой — он понадобится, когда одна
# панель будет смотреть на несколько хабов.
_raw_cors = str(_bootstrap_settings().get("web_api_allowed_origins", "")).split(",")
_cors_origins = [
    o.strip()
    for o in _raw_cors
    if o.strip() and o.strip() != "*"
]
if _cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["X-Hub-Token", "Content-Type", "X-Hub-Actor"],
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

# Коммит и время запуска СНИМАЮТСЯ ОДИН РАЗ, при старте процесса.
#
# get_installed_commit() читает манифест с диска при каждом вызове, поэтому
# переживший обновление процесс бодро рапортует свежий коммит: владелец видит
# новый номер и старое поведение. Отличить сборки по такому полю нельзя.
#
# Снятое при старте значение отвечает на настоящий вопрос: какой код сейчас
# в памяти. Вместе со временем запуска этого достаточно, чтобы понять, дошло
# ли обновление до работы, а не только до файлов.
RUNNING_COMMIT: str = get_installed_commit()
PROCESS_STARTED_AT: float = time.time()


@app.get("/api/health")
def health_check():
    from ..account_probe_service import AccountProbeService
    return {
        "pid": os.getpid(),
        "account_probe": AccountProbeService.get().status(),
        "ok": True,
        "version": __version__,
        "commit": get_installed_commit(),
        "running_commit": RUNNING_COMMIT,
        "started_at": PROCESS_STARTED_AT,
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
                "reason": "terminal-or-redirect",
                "hint": "Вход через agy в терминале (основной) или по ссылке в браузере (запасной)",
            },
            "claude": {
                "supported": True,
                "reason": "code-paste",
                "hint": "Откройте ссылку в любом браузере и верните показанный код",
            },
        }
    }

def sanitize_snapshot(snap_dict: Any, email_masking_mode: Optional[str] = None) -> Any:
    import re
    if email_masking_mode is None:
        try:
            from antigravity_provider.router.settings_service import get_hub_settings
            email_masking_mode = get_hub_settings().get("email_masking_mode", "none")
        except Exception:
            email_masking_mode = "none"

    mode = str(email_masking_mode or "none").strip().lower()

    secret_patterns = [
        re.compile(r'((?:access_token|refresh_token|api_key|token|password|secret|key)=)([^\s&,"]+)', re.IGNORECASE),
        re.compile(r'(sk-[a-zA-Z0-9_\-]{8,})'),
        re.compile(r'(gho_[a-zA-Z0-9_\-]{8,})'),
        re.compile(r'(Bearer\s+)([a-zA-Z0-9_\-\.]{8,})', re.IGNORECASE),
    ]

    email_pattern = re.compile(r'\b([A-Za-z0-9._%+-]+)@([A-Za-z0-9.-]+\.[A-Za-z]{2,})\b')

    def _mask_email_match(match: re.Match) -> str:
        local_part = match.group(1)
        domain_part = match.group(2)
        if mode == "full":
            return "***@***.***"
        elif mode == "partial":
            if len(local_part) > 2:
                masked = f"{local_part[0]}***{local_part[-1]}"
            elif local_part:
                masked = f"{local_part[0]}***"
            else:
                masked = "***"
            return f"{masked}@{domain_part}"
        return match.group(0)

    def _mask_str(val: str) -> str:
        res = val
        for pat in secret_patterns:
            if pat.groups == 2:
                res = pat.sub(r'\g<1>***', res)
            elif pat.groups == 1:
                res = pat.sub(r'***', res)
        if mode in ("partial", "full"):
            res = email_pattern.sub(_mask_email_match, res)
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
    from ..account_probe_service import AccountProbeService
    from ..model_discovery_service import ModelDiscoveryService
    probe, discovery = AccountProbeService.get(), ModelDiscoveryService.get()
    snap_dict["account_probe"] = probe.status()
    for profile in snap_dict.get("all_profiles", {}).values():
        pid, provider = profile["profile_id"], profile["provider"]
        check = probe.state(pid)
        profile["connection_check"] = check
        if profile.get("auth_state") == "AUTHENTICATED" and profile.get("enabled", True) and not check.get("models_only"):
            if check.get("state") == "working":
                profile["health_state"], profile["health_label_ru"] = "healthy", "Проверен: работает"
            elif check.get("state") == "failed":
                profile["health_state"], profile["health_label_ru"] = "unhealthy", "Проверен: не работает — " + check["message"]
            elif check.get("state") == "checking":
                profile["health_state"], profile["health_label_ru"] = "checking", "Проверяется…"
        profile["model_discovery"] = discovery.get_models_with_metadata(provider, pid)
        if provider == "ollama":
            profile["model_discovery"]["cloud"] = discovery.get_models_with_metadata("ollama-cloud-catalog")
    snap_dict["profiles_by_provider"] = {
        provider: [snap_dict["all_profiles"].get(p["profile_id"], p) for p in profiles]
        for provider, profiles in snap_dict.get("profiles_by_provider", {}).items()
    }
    snap_dict = sanitize_snapshot(snap_dict)
    
    server_host = _web_settings().get("web_api_host", "127.0.0.1")
    is_external = (server_host != "127.0.0.1" and server_host != "localhost")
    snap_dict["network_security"] = {
        "is_external_bind": is_external,
        "is_tls": False,
        "host": server_host,
        "warning": (
            f"Внимание: Web API привязан к внешнему сетевому интерфейсу ({server_host}) поверх открытого HTTP. Токен авторизации и почты аккаунтов передаются по сети в открытом виде. Рекомендуется использовать HTTPS, VPN или SSH-туннель."
            if is_external
            else None
        ),
    }
    
    snap_dict["version"] = __version__
    snap_dict["commit"] = get_installed_commit()
    snap_dict["running_commit"] = RUNNING_COMMIT
    snap_dict["started_at"] = PROCESS_STARTED_AT
    snap_dict["system_paths"] = {
        "hermes_home": str(paths.get_hermes_home()),
        "config_dir": str(paths.get_config_dir()),
        "log_file": str(paths.get_log_file()),
    }
    try:
        from antigravity_provider.router.agy_eligibility_service import AgyEligibilityService
        snap_dict["agy_eligibility"] = AgyEligibilityService.get().check_eligibility_state(force=False)
    except Exception as exc:
        snap_dict["agy_eligibility"] = {
            "status": "unknown",
            "status_label_ru": f"Н/Д: {exc}",
            "detail_ru": str(exc),
            "version": "Н/Д",
            "binary_path": "",
            "binary_sha256": "",
            "binary_size_bytes": 0,
            "checked_at": time.time(),
            "patch_script_path": "",
        }
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
        
    actor = request.headers.get("X-Hub-Actor") or (f"web:{request.client.host}" if request.client else "user:web")
    try:
        result = await run_in_threadpool(ActionExecutor.execute, action, data.get("data", {}), async_runner=_async_runner, actor=actor)
    except Exception as exc:
        result = {"ok": False, "message": f"Действие {action} завершилось ошибкой {type(exc).__name__}"}

    if result.get("unknown"):
        raise HTTPException(status_code=404, detail="Неизвестное действие")
        
    return {
        "ok": result.get("ok", False),
        "message": result.get("message") or ("Действие выполнено" if result.get("ok") else f"Действие {action} не выполнено: обработчик не сообщил причину"),
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


@app.get("/api/quotas/export")
def export_quotas_endpoint(
    format: str = "json",
    authorized: bool = Depends(get_auth_token),
):
    """Export full quotas and limits report across all providers and profiles."""
    from antigravity_provider.router.action_handler import generate_quotas_export
    fmt = format.lower().strip()
    if fmt == "csv":
        csv_data = generate_quotas_export(format="csv")
        return Response(
            content=csv_data,
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": "attachment; filename=hermes_quotas_export.csv"},
        )
    else:
        json_data = generate_quotas_export(format="json")
        sanitized = sanitize_snapshot(json_data)
        return JSONResponse(
            content=jsonable_encoder(sanitized),
            headers={"Content-Disposition": "attachment; filename=hermes_quotas_export.json"},
        )


@app.get("/api/skills")
def get_skills_endpoint(authorized: bool = Depends(get_auth_token)):
    """Return all discovered skills with metadata, assigned agents, and validation status."""
    from antigravity_provider.router.skills_service import SkillsService
    skills = SkillsService.get().discover_skills()
    skills_dicts = [s.to_dict() for s in skills]
    return JSONResponse(content=jsonable_encoder({"skills": skills_dicts}))


@app.post("/api/skills/assign")
async def assign_skill_endpoint(request: Request, authorized: bool = Depends(get_auth_token)):
    """Assign a skill to a specific subagent."""
    from antigravity_provider.router.skills_service import SkillsService
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    skill_name = str(data.get("skill_name") or data.get("name") or "").strip()
    agent_id = str(data.get("agent_id") or data.get("id") or "").strip()
    if not skill_name or not agent_id:
        raise HTTPException(status_code=400, detail="Укажите 'skill_name' и 'agent_id'")

    try:
        res = SkillsService.get().assign_skill(skill_name, agent_id)
        return JSONResponse(content=jsonable_encoder(res))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/skills/unassign")
async def unassign_skill_endpoint(request: Request, authorized: bool = Depends(get_auth_token)):
    """Remove an assigned skill from a subagent."""
    from antigravity_provider.router.skills_service import SkillsService
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    skill_name = str(data.get("skill_name") or data.get("name") or "").strip()
    agent_id = str(data.get("agent_id") or data.get("id") or "").strip()
    if not skill_name or not agent_id:
        raise HTTPException(status_code=400, detail="Укажите 'skill_name' и 'agent_id'")

    try:
        res = SkillsService.get().unassign_skill(skill_name, agent_id)
        return JSONResponse(content=jsonable_encoder(res))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/skills/usage")
def get_skills_usage_endpoint(authorized: bool = Depends(get_auth_token)):
    """Return truthful skill invocation statistics."""
    from antigravity_provider.router.skills_service import SkillsService
    usage = SkillsService.get().get_skills_usage()
    return JSONResponse(content=jsonable_encoder(usage))


@app.post("/api/skills/diagnose")
async def diagnose_skill_endpoint(request: Request, authorized: bool = Depends(get_auth_token)):
    """Run SkillDoctor diagnostics on a skill by name, filepath, or raw content."""
    from antigravity_provider.router.skills_service import SkillsService
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    skill_name = data.get("skill_name") or data.get("name")
    filepath = data.get("path") or data.get("filepath")
    content = data.get("content")

    try:
        diag = SkillsService.get().diagnose_skill(skill_name=skill_name, filepath=filepath, content=content)
        return JSONResponse(content=jsonable_encoder({"ok": True, "diagnosis": diag.to_dict()}))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/compression/status")
def get_compression_status_endpoint(authorized: bool = Depends(get_auth_token)):
    """Return real-time diagnostic status of context compressor."""
    from antigravity_provider.router.settings_service import get_hub_settings
    from antigravity_provider.router.local_supervisor import LocalSupervisor

    hub_settings = get_hub_settings()
    c_pid = hub_settings.get("compressor_profile_id")
    c_pcfg = None
    if c_pid:
        try:
            c_pcfg = load_router_config().get_profile(c_pid)
        except Exception:
            pass
    supervisor = LocalSupervisor()
    status_data = supervisor.get_compression_status(c_pcfg)
    status_data["threshold_percent"] = hub_settings.get("compression_threshold_percent", 75.0)
    status_data["keep_recent_messages"] = hub_settings.get("compression_keep_recent_messages", 3)
    status_data["compression_enabled"] = hub_settings.get("compression_enabled", True)
    return JSONResponse(content=jsonable_encoder(status_data))


@app.get("/api/compression/history")
def get_compression_history_endpoint(limit: int = 20, authorized: bool = Depends(get_auth_token)):
    """Return historical record of recent context compressions."""
    from antigravity_provider.router.context_compressor import ContextCompressor
    history = ContextCompressor().get_compression_history(limit=limit)
    return JSONResponse(content=jsonable_encoder({"history": history}))


@app.post("/api/compression/test")
async def test_compression_endpoint(request: Request, authorized: bool = Depends(get_auth_token)):
    """Execute test context compression on synthetic benchmark prompt."""
    from antigravity_provider.router.settings_service import get_hub_settings
    from antigravity_provider.router.local_supervisor import LocalSupervisor
    from dataclasses import asdict

    try:
        data = await request.json()
    except Exception:
        data = {}

    hub_settings = get_hub_settings()
    c_pid = data.get("profile_id") or hub_settings.get("compressor_profile_id")
    c_pcfg = None
    if c_pid and c_pid != "none":
        try:
            c_pcfg = load_router_config().get_profile(c_pid)
        except Exception:
            pass

    test_messages = [
        {"role": "system", "content": "You are a software engineer."},
        {"role": "user", "content": "Hermes Hub server runs on 192.168.1.81:8765. The primary coder is on port 8081 with 224K context (229376 tokens), generating at 107.4 tok/s. VRAM usage: 30008 MiB. Active branch: antigravity/a56-context-compression, Commit SHA: 26f7d2c, version v0.1.2. Local compressor is on port 8082."},
        {"role": "assistant", "content": "Acknowledged. All server metrics and ports are noted."},
        {"role": "user", "content": "Now run preflight diagnostics for LocalSupervisor and ContextCompressor in src/antigravity_provider/router/local_supervisor.py."},
        {"role": "assistant", "content": "Diagnostics completed successfully. Memory vault is at /srv/projects/AI-Memory."},
        {"role": "user", "content": "What is our current task?"},
    ]

    supervisor = LocalSupervisor()
    new_msgs, outcome = supervisor.compress_context_if_needed(
        messages=test_messages,
        target_context_limit=32768,
        compressor_profile=c_pcfg,
        threshold_percent=0.0,  # force compression
        keep_recent_messages=2,
    )
    return JSONResponse(content=jsonable_encoder({
        "ok": outcome.status == "SUCCESS",
        "message": outcome.status_message,
        "data": {
            "outcome": asdict(outcome) if hasattr(outcome, "__dataclass_fields__") else outcome.__dict__,
            "messages_before_count": len(test_messages),
            "messages_after_count": len(new_msgs),
        }
    }))


@app.get("/api/settings")
def get_settings(authorized: bool = Depends(get_auth_token)):
    """Return current server and hub settings without exposing raw auth tokens."""
    raw = _web_settings()
    has_token = bool(raw.get("web_api_token"))
    last_check = UpdateManager.get_last_check_result()
    server_host = raw.get("web_api_host", "127.0.0.1")
    is_external = (server_host != "127.0.0.1" and server_host != "localhost")
    system_paths = {
        "hermes_home": str(paths.get_hermes_home()),
        "config_dir": str(paths.get_config_dir()),
        "log_file": str(paths.get_log_file()),
    }
    settings_out: Dict[str, Any] = {
        "system_paths": system_paths,
        "web_api_host": server_host,
        "web_api_port": raw.get("web_api_port", 5800),
        "web_api_token_configured": has_token,
        "theme": raw.get("theme", "system"),
        "quota_refresh_interval_sec": raw.get("quota_refresh_interval_sec", raw.get("account_check_interval_seconds", 300)),
        "hermes_home": system_paths["hermes_home"],
        "config_dir": system_paths["config_dir"],
        "log_file": system_paths["log_file"],
        "installed_commit": get_installed_commit(),
        # Версия между сборками не меняется намеренно, а коммит — строка из
        # шестнадцатеричных цифр, по которой трудно на глаз отличить старую
        # сборку от новой. Время установки отвечает на этот вопрос сразу.
        "installed_at": get_installed_build_time(),
        "version": __version__,
        "last_update_check": last_check.to_dict() if last_check else None,
        "network_security": {
            "is_external_bind": is_external,
            "is_tls": False,
            "host": server_host,
            "warning": (
                f"Внимание: Web API привязан к внешнему сетевому интерфейсу ({server_host}) поверх открытого HTTP. Токен авторизации и почты аккаунтов передаются по сети в открытом виде. Рекомендуется использовать HTTPS, VPN или SSH-туннель."
                if is_external
                else None
            ),
        },
    }
    try:
        from antigravity_provider.router.agy_eligibility_service import AgyEligibilityService
        settings_out["agy_eligibility"] = AgyEligibilityService.get().check_eligibility_state(force=False)
    except Exception as exc:
        settings_out["agy_eligibility"] = {
            "status": "unknown",
            "status_label_ru": f"Н/Д: {exc}",
            "detail_ru": str(exc),
            "version": "Н/Д",
            "binary_path": "",
            "binary_sha256": "",
            "binary_size_bytes": 0,
            "checked_at": time.time(),
            "patch_script_path": "",
        }
    for k, v in raw.items():
        if k not in settings_out and not any(secret in k.lower() for secret in ['token', 'secret', 'key', 'password', 'jwt']):
            settings_out[k] = v
    return JSONResponse(content=jsonable_encoder(settings_out))

def run_web_server(host: Optional[str] = None, port: Optional[int] = None, open_browser: bool = False) -> None:
    import uvicorn
    import webbrowser
    settings = _web_settings()
    host = host or settings.get('web_api_host', '127.0.0.1')
    port = port or int(settings.get('web_api_port', 5800))
    token = settings.get('web_api_token', '')
    
    if host != '127.0.0.1' and not token:
        logger.error("Cannot bind Web API externally without web_api_token")
        sys.exit(1)
        
    url = f"http://{host}:{port}"
    logger.info(f"Starting Hermes Hub Web on {url}")
    print(f"Hermes Hub running at {url}")

    if open_browser:
        def _open():
            time.sleep(0.5)
            try:
                webbrowser.open(url)
            except Exception:
                pass
        threading.Thread(target=_open, daemon=True).start()

    uvicorn.run(app, host=host, port=port, log_level="warning")


def start_web_server_background(host: Optional[str] = None, port: Optional[int] = None) -> threading.Thread:
    """Start web server in a daemon thread."""
    t = threading.Thread(target=run_web_server, kwargs={"host": host, "port": port, "open_browser": False}, daemon=True)
    t.start()
    return t


def run_server() -> None:
    run_web_server(open_browser=False)



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

    # A48 и A49 добавили новые файлы клиента, а заголовки кэширования им не
    # прописали: браузер держал их сколько угодно. Владелец обновлял сборку и
    # видел прежний интерфейс — ровно та поломка, ради которой запрет кэша
    # вводился для app.js. Перечисление сделано общим, чтобы следующий
    # добавленный файл не оказался снова без заголовков.
    for _client_script in ("workspace.js", "workflow.js", "workflow.css"):

        def _make_route(name: str):
            media = "text/css" if name.endswith(".css") else "application/javascript"

            def _serve():
                return FileResponse(str(_STATIC_DIR / name), media_type=media, headers=_NO_CACHE)

            return _serve

        app.get("/" + _client_script)(_make_route(_client_script))

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
_background_stop = threading.Event()


def _background_refresh_loop() -> None:
    from antigravity_provider.router.quota_collector import AccountQuotaService
    from antigravity_provider.router.account_probe_service import AccountProbeService
    AccountProbeService.get().enabled = True
    AccountProbeService.get().tick()

    try:
        AccountQuotaService.get().fetch_all_configured(force=True)
        logger.info("Quota cache warmed on startup")
    except Exception as exc:
        logger.warning("Quota warm-up failed: %s", exc)

    # Initial quiet update check in background
    try:
        UpdateManager().check_for_updates()
        logger.info("Initial update check completed in background")
    except Exception as exc:
        logger.debug("Initial background update check skipped: %s", exc)

    while not _background_stop.is_set():
        try:
            AccountProbeService.get().tick()
            HubStateStore.get().refresh(force_scan=False)
        except Exception as exc:
            logger.warning("Snapshot refresh failed: %s", exc)
        _background_stop.wait(_SNAPSHOT_REFRESH_SEC)


@app.on_event("startup")
def _start_background_refresh() -> None:
    _background_stop.clear()
    # В фоне: опрос ходит по сети к нескольким провайдерам, держать на нём
    # старт сервера нельзя.
    threading.Thread(target=_background_refresh_loop, daemon=True, name="hub-web-refresh").start()

    from antigravity_provider.router.quota_collector import AccountQuotaService

    try:
        AccountQuotaService.get().start_background_scheduler()
    except Exception as exc:
        logger.warning("Could not start quota scheduler: %s", exc)


@app.on_event("shutdown")
def _stop_background_refresh() -> None:
    from ..account_probe_service import AccountProbeService
    from ..quota_collector import AccountQuotaService
    _background_stop.set()
    AccountProbeService.get().shutdown()
    AccountQuotaService.get().stop_background_scheduler()
