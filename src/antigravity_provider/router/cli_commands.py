"""CLI diagnostic and management commands for Hermes Multi-Provider Account Router."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from antigravity_provider.router.router_config import RouterConfig, RouterProfileConfig, load_router_config
from antigravity_provider.router.health_tracker import HealthTracker
from antigravity_provider.router.router_engine import RouterEngine, get_router_engine
from antigravity_provider.router.adapters import get_adapter
from antigravity_provider.router.profile_manager import ProfileAuthManager, mask_email, mask_id


def print_router_status() -> int:
    """Print pool and health status of all profiles and role chains."""
    engine = get_router_engine()
    config = engine.config

    print("=" * 80)
    print("HERMES MULTI-PROVIDER ACCOUNT ROUTER: POOL & HEALTH STATUS")
    print("=" * 80)
    print(f"{'LOGICAL ROLE':<16} {'PROFILE':<18} {'PROVIDER':<15} {'STATE':<18} {'RESET IN':<10}")
    print("-" * 80)

    for rname, rpolicy in sorted(config.roles.items()):
        for idx, pid in enumerate(rpolicy.preferred_chain):
            pconfig = config.get_profile(pid)
            if not pconfig:
                continue
            role_label = rname if idx == 0 else f"  -> fallback {idx}"
            precord = engine.health.get_or_create(pid)

            state_display = precord.overall_state
            reset_display = "-"
            if precord.overall_state != "healthy":
                cooldown_remaining = max([int(f.reset_at - time.time()) for f in precord.families.values() if f.reset_at and f.reset_at > time.time()] or [0])
                if cooldown_remaining > 0:
                    reset_display = f"{cooldown_remaining}s"
                else:
                    state_display = "cooldown (ready)"

            if not pconfig.enabled:
                state_display = "disabled (cold)"

            print(f"{role_label:<16} {pid:<18} {pconfig.provider:<15} {state_display:<18} {reset_display:<10}")

    print("-" * 80)
    return 0


def print_routing_policy() -> int:
    """Print the configured routing policies and fallback chains."""
    config = load_router_config()
    print("=" * 70)
    print("HERMES ROUTING POLICIES")
    print("=" * 70)

    for rname, rpolicy in sorted(config.roles.items()):
        chain_str = " -> ".join(rpolicy.preferred_chain)
        print(f"Role: {rname}")
        print(f"  Preferred Chain: {chain_str}")
        print(f"  Max Failover:    {rpolicy.max_failover_attempts}")
        print(f"  Session Affinity: {'Enabled' if rpolicy.session_affinity_enabled else 'Disabled'}")
        if rpolicy.default_model:
            print(f"  Default Model:   {rpolicy.default_model}")
        print()
    return 0


def profile_status_cli(profile_id: Optional[str] = None) -> int:
    """Print detailed auth and credential status for profiles."""
    config = load_router_config()
    main_ag_pid = ProfileAuthManager.get_main_profile("antigravity")
    main_codex_pid = ProfileAuthManager.get_main_profile("openai-codex")

    print("=" * 85)
    print("HERMES ROUTER PROFILE AUTHENTICATION STATUS (* = Main/Default Account)")
    print("=" * 85)
    print(f"{'PROFILE':<19} | {'PROVIDER':<13} | {'AUTH STATUS':<19} | {'ACCOUNT / EMAIL':<25} | {'STORAGE'}")
    print("-" * 105)

    profiles = [profile_id] if profile_id else sorted(config.profiles.keys())
    for pid in profiles:
        pcfg = config.get_profile(pid)
        if not pcfg:
            print(f"Profile '{pid}' not found.")
            continue
        if not pcfg.enabled:
            print(f"{pid:<19} | {pcfg.provider:<13} | {'DISABLED':<19} | {'(cold spare)':<25} | -")
            continue

        is_main = (pid == main_ag_pid and pcfg.provider == "antigravity") or (pid == main_codex_pid and pcfg.provider == "openai-codex")
        pid_display = f"{pid} *" if is_main else pid

        status = ProfileAuthManager.get_profile_status(pcfg.provider, pid)
        if status.get("authenticated"):
            auth_tag = "[PASS] AUTH (MAIN)" if is_main else "[PASS] AUTH"
        else:
            auth_tag = "[FAIL] NO AUTH"

        account = status.get("email_masked") or status.get("account_id_masked") or status.get("error") or "-"
        if len(account) > 24:
            account = account[:23] + "..."
        storage = status.get("storage") or "-"
        print(f"{pid_display:<19} | {pcfg.provider:<13} | {auth_tag:<19} | {account:<25} | {storage}")

    print("-" * 105)
    return 0


def profile_set_main_cli(profile_id: str) -> int:
    """Set a specific profile as the active main account for Hermes."""
    config = load_router_config()
    pcfg = config.get_profile(profile_id)
    if not pcfg:
        print(f"[ERROR] Profile '{profile_id}' not found in configuration.")
        return 1

    ok, msg = ProfileAuthManager.set_main_profile(pcfg.provider, profile_id)
    if ok:
        print(f"[OK] {msg}")
        ver = ProfileAuthManager.get_profile_status(pcfg.provider, profile_id)
        print(f"Active Account: {ver.get('email_masked') or ver.get('account_id_masked')} (Provider: {pcfg.provider})")
        return 0
    else:
        print(f"[FAIL] {msg}")
        return 1


def profile_import_cli(profile_id: str, from_current_cm: bool = False) -> int:
    """Import active credentials into a profile."""
    config = load_router_config()
    pcfg = config.get_profile(profile_id)
    if not pcfg:
        print(f"[ERROR] Profile '{profile_id}' not found in configuration.")
        return 1

    if pcfg.provider == "antigravity":
        if from_current_cm:
            cm_data = ProfileAuthManager.read_windows_credential("gemini:antigravity")
            if not cm_data:
                print("[ERROR] No 'gemini:antigravity' credential found in Windows Credential Manager.")
                return 1
            saved_p = ProfileAuthManager.save_profile_auth("antigravity", profile_id, cm_data)
            print(f"[OK] Successfully imported Windows Credential into profile '{profile_id}' -> {saved_p}")
            ver = ProfileAuthManager.verify_antigravity_profile(profile_id)
            print(f"Verified identity: {ver.get('email_masked', '')} (sub={ver.get('account_id_masked', '')})")
            return 0

    elif pcfg.provider == "openai-codex":
        if from_current_cm:
            codex_file = Path.home() / ".codex" / "auth.json"
            if not codex_file.is_file():
                print("[ERROR] ~/.codex/auth.json not found.")
                return 1
            d = json.loads(codex_file.read_text(encoding="utf-8"))
            saved_p = ProfileAuthManager.save_profile_auth("openai-codex", profile_id, d)
            print(f"[OK] Successfully imported Codex credentials into profile '{profile_id}' -> {saved_p}")
            ver = ProfileAuthManager.verify_codex_profile(profile_id)
            print(f"Verified identity: {ver.get('email_masked', '')} (account={ver.get('account_id_masked', '')})")
            return 0

    print(f"[ERROR] Import method not supported for provider '{pcfg.provider}'.")
    return 1


def profile_set_key_cli(profile_id: str, api_key: str) -> int:
    """Set an API key for an OpenCode Go profile."""
    config = load_router_config()
    pcfg = config.get_profile(profile_id)
    if not pcfg:
        print(f"[ERROR] Profile '{profile_id}' not found.")
        return 1

    saved = ProfileAuthManager.save_profile_auth(pcfg.provider, profile_id, {"api_key": api_key, "auth_mode": "api_key"})
    print(f"[OK] API key saved for profile '{profile_id}' -> {saved}")
    status = ProfileAuthManager.get_profile_status(pcfg.provider, profile_id)
    print(f"Status: {status}")
    return 0


def test_profile_cli(profile_id: str) -> int:
    """Test a live prompt execution on a specific profile."""
    config = load_router_config()
    pconfig = config.get_profile(profile_id)
    if not pconfig:
        print(f"[ERROR] Profile '{profile_id}' not found.")
        return 1

    print(f"Testing profile '{profile_id}' (Provider: {pconfig.provider})...")
    adapter = get_adapter(pconfig.provider)

    test_request = {
        "model": pconfig.preferred_models[0] if pconfig.preferred_models else "default",
        "messages": [{"role": "user", "content": "respond only with: router_test_ok"}],
        "temperature": 0.1,
    }

    try:
        resp = adapter.invoke(pconfig, test_request)
        content = resp.get("choices", [{}])[0].get("message", {}).get("content", "")
        print(f"[PASS] Response from {profile_id}: {content.strip()[:100]}")
        return 0
    except Exception as e:
        print(f"[FAIL] Error from {profile_id}: {e}")
        return 1


def simulate_quota_cli(profile_id: str, model_family: Optional[str] = None, duration: int = 600) -> int:
    """Simulate quota exhaustion on a profile for testing."""
    engine = get_router_engine()
    pconfig = engine.config.get_profile(profile_id)
    if not pconfig:
        print(f"[ERROR] Profile '{profile_id}' not found.")
        return 1

    engine.health.simulate_quota(profile_id, model_family=model_family, duration=duration)
    print(f"[OK] Simulated quota exhaustion activated for profile '{profile_id}' for {duration} seconds.")
    print("Use `hermes router clear-cooldown` to restore normal state.")
    return 0


def clear_cooldown_cli(profile_id: Optional[str] = None) -> int:
    """Clear cooldowns and quota simulations."""
    engine = get_router_engine()
    engine.health.clear_cooldown(profile_id)
    if profile_id:
        print(f"[OK] Cooldowns and simulated quota cleared for profile '{profile_id}'.")
    else:
        print("[OK] All profile cooldowns and simulated quotas cleared.")
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="hermes router", description="Hermes Multi-Provider Account Router CLI")
    subparsers = parser.add_subparsers(dest="subcommand", help="Router subcommands")

    # status
    subparsers.add_parser("status", help="Show pool and health status of all provider profiles")

    # policy
    subparsers.add_parser("policy", help="Show role fallback chains and policies")

    # profile
    prof_parser = subparsers.add_parser("profile", help="Manage profile authentication and provisioning")
    prof_sub = prof_parser.add_subparsers(dest="prof_action", help="Profile action")

    # profile status
    pstat = prof_sub.add_parser("status", help="Show authentication status for profiles")
    pstat.add_argument("profile_id", nargs="?", default=None, help="Optional profile ID")

    # profile set-main
    psetm = prof_sub.add_parser("set-main", help="Set profile as the active default for Hermes")
    psetm.add_argument("profile_id", help="Profile ID to make main (e.g. ag-w1, ag-orch-fallback)")

    # profile import
    pimp = prof_sub.add_parser("import", help="Import credentials into profile")
    pimp.add_argument("profile_id", help="Target profile ID")
    pimp.add_argument("--from-current-cm", action="store_true", help="Import from current Windows Credential Manager or ~/.codex/auth.json")

    # profile set-key
    psetk = prof_sub.add_parser("set-key", help="Set API key for an OpenCode Go / API profile")
    psetk.add_argument("profile_id", help="Target profile ID")
    psetk.add_argument("api_key", help="API Key value")

    # test
    test_parser = subparsers.add_parser("test", help="Test specific profile invocation")
    test_parser.add_argument("profile_id", help="Profile ID to test")

    # simulate
    sim_parser = subparsers.add_parser("simulate", help="Simulate quota exhaustion for testing")
    sim_sub = sim_parser.add_subparsers(dest="sim_type", help="Simulation type")
    sim_quota = sim_sub.add_parser("quota", help="Simulate quota exhaustion on a profile")
    sim_quota.add_argument("profile_id", help="Profile ID to mark exhausted")
    sim_quota.add_argument("--model-family", default=None, help="Specific model family to mark exhausted")
    sim_quota.add_argument("--duration", type=int, default=600, help="Duration in seconds (default 600)")

    # clear-cooldown
    cc_parser = subparsers.add_parser("clear-cooldown", help="Clear cooldowns and quota simulations")
    cc_parser.add_argument("profile_id", nargs="?", default=None, help="Optional profile ID")

    # hub / cockpit / gui
    hub_parser = subparsers.add_parser("hub", aliases=["cockpit", "gui"], help="Launch Hermes Hub GUI")
    hub_parser.add_argument("--port", type=int, default=8765, help="Port to bind server (default 8765)")
    hub_parser.add_argument("--no-browser", action="store_true", help="Do not automatically open browser")

    args = parser.parse_args(argv)

    if args.subcommand in ("hub", "cockpit", "gui"):
        from antigravity_provider.router.hermes_hub_app import launch_hub
        launch_hub()
        return 0
    elif args.subcommand == "status":
        return print_router_status()
    elif args.subcommand == "policy":
        return print_routing_policy()
    elif args.subcommand == "profile":
        if args.prof_action == "status":
            return profile_status_cli(args.profile_id)
        elif args.prof_action == "set-main":
            return profile_set_main_cli(args.profile_id)
        elif args.prof_action == "import":
            return profile_import_cli(args.profile_id, from_current_cm=args.from_current_cm)
        elif args.prof_action == "set-key":
            return profile_set_key_cli(args.profile_id, args.api_key)
        else:
            prof_parser.print_help()
            return 1
    elif args.subcommand == "test":
        return test_profile_cli(args.profile_id)
    elif args.subcommand == "simulate":
        if args.sim_type == "quota":
            return simulate_quota_cli(args.profile_id, model_family=args.model_family, duration=args.duration)
        else:
            sim_parser.print_help()
            return 1
    elif args.subcommand == "clear-cooldown":
        return clear_cooldown_cli(args.profile_id)
    else:
        parser.print_help()
        return 0


if __name__ == "__main__":
    sys.exit(main())
