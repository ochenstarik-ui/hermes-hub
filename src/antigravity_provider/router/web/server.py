import os
import sys
import threading
import dataclasses
import logging
from typing import Dict, Any

from fastapi import FastAPI, Request, HTTPException, Depends, Header
from fastapi.responses import JSONResponse
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

def get_auth_token(x_hub_token: str = Header(None)) -> bool:
    config = load_router_config()
    server_host = config.hub.get('web_api_host', '127.0.0.1')
    
    if server_host != '127.0.0.1':
        required_token = config.hub.get('web_api_token', '')
        if not required_token:
            raise HTTPException(status_code=500, detail="Server misconfigured: external bind requires a token")
        if x_hub_token != required_token:
            raise HTTPException(status_code=401, detail="Invalid X-Hub-Token")
    return True

@app.get("/api/health")
def health_check():
    return {
        "ok": True,
        "version": "1.0.0",
        "auth_flows": {
            "openai-codex": {"supported": True, "reason": "device-code"},
            "grok": {"supported": True, "reason": "device-code"},
            "opencode-go": {"supported": True, "reason": "token"},
            "antigravity": {"supported": False, "reason": "Требует redirect на localhost; используйте десктоп или проброс портов"},
            "claude": {"supported": False, "reason": "Требует redirect на localhost; используйте десктоп или проброс портов"}
        }
    }

def sanitize_snapshot(snap_dict: Dict[str, Any]) -> Dict[str, Any]:
    def _sanitize(node):
        if isinstance(node, dict):
            return {
                k: _sanitize(v) for k, v in node.items()
                if not any(secret in k.lower() for secret in ['access_token', 'refresh_token', 'api_key', 'jwt'])
            }
        elif isinstance(node, list):
            return [_sanitize(x) for x in node]
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

def run_server():
    import uvicorn
    config = load_router_config()
    host = config.hub.get('web_api_host', '127.0.0.1')
    port = int(config.hub.get('web_api_port', 5800))
    token = config.hub.get('web_api_token', '')
    
    if host != '127.0.0.1' and not token:
        logger.error("Cannot bind Web API externally without web_api_token")
        sys.exit(1)
        
    logger.info(f"Starting Hermes Hub Web API on {host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="warning")
