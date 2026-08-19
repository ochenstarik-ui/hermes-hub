"""Hermes Account Manager: Local Cockpit GUI Server (FastAPI + Embedded Reactive Dashboard)."""
from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
import webbrowser
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from antigravity_provider.router.router_config import RouterConfig, load_router_config
from antigravity_provider.router.profile_manager import ProfileAuthManager, mask_email, mask_id
from antigravity_provider.router.profile_oauth import start_profile_oauth, get_oauth_session
from antigravity_provider.router.auto_assigner import AutoAssigner
from antigravity_provider.router.router_engine import get_router_engine
from antigravity_provider.router.adapters import get_adapter
from antigravity_provider.router.adapters.antigravity_adapter import AntigravityAdapter

logger = logging.getLogger("hermes.router.gui")

app = FastAPI(title="Hermes Hub", description="Multi-Agent & Multi-Provider Control Hub", version="1.3.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class SetMainRequest(BaseModel):
    provider: str
    profile_id: str


class SetOrchestratorRequest(BaseModel):
    profile_id: str


class TestProfileRequest(BaseModel):
    provider: str
    profile_id: str


class DeleteProfileRequest(BaseModel):
    provider: str
    profile_id: str


class StartOAuthRequest(BaseModel):
    profile_id: Optional[str] = None
    requested_role: Optional[str] = "auto"


class SetKeyRequest(BaseModel):
    profile_id: Optional[str] = None
    api_key: str
    requested_role: Optional[str] = "auto"


@app.get("/api/team")
def get_team_view() -> Dict[str, Any]:
    """Return the structured Hermes Team view with human-readable roles and cards."""
    return AutoAssigner.build_team_hierarchy()


@app.get("/api/status")
def get_all_status() -> Dict[str, Any]:
    config = load_router_config()
    engine = get_router_engine()

    main_ag = ProfileAuthManager.get_main_profile("antigravity")
    main_codex = ProfileAuthManager.get_main_profile("openai-codex")

    result = {
        "providers": {
            "antigravity": [],
            "openai-codex": [],
            "opencode-go": [],
        },
        "main_profiles": {
            "antigravity": main_ag,
            "openai-codex": main_codex,
        },
        "stats": {
            "total_profiles": len(config.profiles),
            "authenticated_profiles": 0,
        }
    }

    # Discover logical role assigned to each profile
    role_assignments = {}
    for rname, rpol in config.roles.items():
        for idx, pid in enumerate(rpol.preferred_chain):
            tag = f"{rname} (primary)" if idx == 0 else f"{rname} (fallback {idx})"
            role_assignments.setdefault(pid, []).append(tag)

    for pid, pcfg in sorted(config.profiles.items()):
        prov = pcfg.provider
        if prov not in result["providers"]:
            result["providers"][prov] = []

        precord = engine.health.get_or_create(pid)
        is_main = (pid == main_ag and prov == "antigravity") or (pid == main_codex and prov == "openai-codex")

        # Live credential verification
        auth_status = ProfileAuthManager.get_profile_status(prov, pid)
        is_auth = auth_status.get("authenticated", False)
        if is_auth and pcfg.enabled:
            result["stats"]["authenticated_profiles"] += 1

        identity = auth_status.get("email_masked") or auth_status.get("account_id_masked") or auth_status.get("error") or "Не авторизован"
        display_name, log_role, tier = AutoAssigner.get_display_name_and_role(pid)

        # Quota and cooldown
        cooldown_remaining = max([int(f.reset_at - time.time()) for f in precord.families.values() if f.reset_at and f.reset_at > time.time()] or [0])

        card = {
            "profile_id": pid,
            "display_name": display_name,
            "provider": prov,
            "enabled": pcfg.enabled,
            "is_main": is_main,
            "account_id": pcfg.account_id,
            "identity": identity,
            "authenticated": is_auth,
            "health_state": precord.overall_state,
            "cooldown_remaining_sec": cooldown_remaining,
            "preferred_models": pcfg.preferred_models,
            "discovered_models": pcfg.preferred_models or ["gemini-3.7-flash"],
            "capabilities": pcfg.capabilities,
            "assigned_roles": role_assignments.get(pid, [log_role]),
            "storage_path": auth_status.get("storage", "-"),
        }
        result["providers"][prov].append(card)

    return result


@app.post("/api/profile/set-main")
def set_main_profile(req: SetMainRequest) -> Dict[str, Any]:
    ok, msg = ProfileAuthManager.set_main_profile(req.provider, req.profile_id)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"success": True, "message": msg}


@app.post("/api/profile/set-orchestrator")
def set_orchestrator(req: SetOrchestratorRequest) -> Dict[str, Any]:
    ok, msg = AutoAssigner.set_primary_orchestrator(req.profile_id)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"success": True, "message": msg}


@app.post("/api/profile/test")
def test_profile(req: TestProfileRequest) -> Dict[str, Any]:
    """Test a profile using existing credentials. NEVER triggers login or OAuth flow."""
    config = load_router_config()
    pcfg = config.get_profile(req.profile_id)
    if not pcfg:
        raise HTTPException(status_code=404, detail=f"Profile '{req.profile_id}' not found")

    status = ProfileAuthManager.get_profile_status(pcfg.provider, req.profile_id)
    if not status.get("authenticated"):
        return {
            "success": False,
            "profile_id": req.profile_id,
            "auth_status": "AUTH REQUIRED",
            "error": "Профиль не авторизован. Нажмите 'Подключить аккаунт'.",
        }

    adapter = get_adapter(pcfg.provider)
    model = pcfg.preferred_models[0] if pcfg.preferred_models else "default"

    t0 = time.time()
    try:
        resp = adapter.invoke(pcfg, {
            "model": model,
            "messages": [{"role": "user", "content": f"Respond strictly with: TEST_OK_FOR_{req.profile_id}"}],
            "temperature": 0.1,
        })
        el = round(time.time() - t0, 2)
        content = resp.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
        return {
            "success": True,
            "profile_id": req.profile_id,
            "identity": status.get("email_masked") or status.get("account_id_masked"),
            "model": model,
            "duration_sec": el,
            "response": content[:120],
        }
    except Exception as e:
        el = round(time.time() - t0, 2)
        return {
            "success": False,
            "profile_id": req.profile_id,
            "identity": status.get("email_masked") or status.get("account_id_masked"),
            "model": model,
            "duration_sec": el,
            "error": str(e),
        }


@app.post("/api/profile/delete")
def delete_profile(req: DeleteProfileRequest) -> Dict[str, Any]:
    auth_p = ProfileAuthManager.get_profile_dir(req.provider, req.profile_id) / "auth.json"
    if auth_p.is_file():
        try:
            auth_p.unlink()
            return {"success": True, "message": f"Учетные данные для '{req.profile_id}' очищены"}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to delete {auth_p}: {e}")
    return {"success": True, "message": f"Учетные данные для '{req.profile_id}' отсутствовали"}


@app.post("/api/antigravity/oauth/start")
def start_oauth(req: StartOAuthRequest) -> Dict[str, Any]:
    profile_id = req.profile_id
    if not profile_id:
        profile_id = AutoAssigner.find_free_slot("antigravity", req.requested_role or "auto")

    if not profile_id:
        raise HTTPException(status_code=400, detail="Нет свободных слотов для Antigravity аккаунтов")

    try:
        session_id, auth_url = start_profile_oauth(profile_id)
        display_name, _, _ = AutoAssigner.get_display_name_and_role(profile_id)
        return {
            "success": True,
            "session_id": session_id,
            "auth_url": auth_url,
            "profile_id": profile_id,
            "display_name": display_name,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to start OAuth session: {e}")


@app.get("/api/antigravity/oauth/poll/{session_id}")
def poll_oauth(session_id: str) -> Dict[str, Any]:
    session = get_oauth_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="OAuth session not found")

    duplicate_warning = None
    if session.status == "completed" and session.completed_profile_info:
        raw_email = session.completed_profile_info.get("email") or session.completed_profile_info.get("email_masked")
        dup_pid = AutoAssigner.check_duplicate_identity("antigravity", raw_email, exclude_profile_id=session.profile_id)
        if dup_pid:
            dup_name, _, _ = AutoAssigner.get_display_name_and_role(dup_pid)
            duplicate_warning = f"Этот аккаунт уже привязан к '{dup_name}' ({dup_pid})."

    return {
        "status": session.status,
        "error_msg": session.error_msg,
        "profile_id": session.profile_id,
        "completed_info": session.completed_profile_info,
        "duplicate_warning": duplicate_warning,
    }


@app.post("/api/antigravity/oauth/cancel/{session_id}")
def cancel_oauth(session_id: str) -> Dict[str, Any]:
    session = get_oauth_session(session_id)
    if session:
        session.cancel()
    return {"success": True}


@app.get("/api/routing")
def get_routing_config() -> Dict[str, Any]:
    config = load_router_config()
    roles = {}
    for rname, rpol in config.roles.items():
        chain_cards = []
        for pid in rpol.preferred_chain:
            dname, _, _ = AutoAssigner.get_display_name_and_role(pid)
            chain_cards.append({"profile_id": pid, "display_name": dname})
        roles[rname] = {
            "chain": rpol.preferred_chain,
            "chain_cards": chain_cards,
            "default_model": rpol.default_model,
            "max_failover": rpol.max_failover_attempts,
            "session_affinity": rpol.session_affinity_enabled,
        }
    return {"roles": roles}


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    html_path = Path(__file__).resolve().parent / "gui_cockpit.html"
    if html_path.is_file():
        return html_path.read_text(encoding="utf-8")
    return "<h1>Hermes Hub UI Not Found</h1>"


def run_gui_server(host: str = "127.0.0.1", port: int = 8765, open_browser: bool = True) -> None:
    """Launch the GUI server and open in default browser."""
    import uvicorn

    url = f"http://{host}:{port}"
    print(f"\n" + "=" * 70)
    print(f"  HERMES HUB (MULTI-AGENT & MULTI-PROVIDER CONTROL HUB)")
    print(f"  URL: {url}")
    print("=" * 70 + "\n")

    if open_browser:
        def _open():
            time.sleep(1.0)
            webbrowser.open(url)
        threading.Thread(target=_open, daemon=True).start()

    uvicorn.run(app, host=host, port=port, log_level="warning")


if __name__ == "__main__":
    run_gui_server()
