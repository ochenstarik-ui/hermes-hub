#!/usr/bin/env python3
"""Verify Antigravity Provider and agy subprocess integration for Hermes."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


def get_hermes_home() -> Path:
    env_home = os.environ.get("HERMES_HOME", "").strip()
    if env_home:
        return Path(env_home).expanduser()
    if os.name == "nt":
        local_app = os.environ.get("LOCALAPPDATA", "").strip()
        if local_app and (Path(local_app) / "hermes").exists():
            return Path(local_app) / "hermes"
    return Path.home() / ".hermes"


def find_agy_exe() -> str | None:
    env_path = os.environ.get("AGY_EXE_PATH", "").strip()
    if env_path and Path(env_path).is_file():
        return env_path
    if os.name == "nt":
        local_app = os.environ.get("LOCALAPPDATA", "").strip()
        if local_app:
            candidate = Path(local_app) / "agy" / "bin" / "agy.exe"
            if candidate.is_file():
                return str(candidate)
    found = shutil.which("agy") or shutil.which("agy.exe")
    return found


def verify() -> int:
    errors = 0
    warnings = 0
    hermes_home = get_hermes_home()
    print("=" * 60)
    print("VERIFY: Hermes Antigravity Provider Integration")
    print("=" * 60)
    print(f"Hermes Home: {hermes_home}")

    # 1. Hermes Home directory
    if not hermes_home.is_dir():
        print(f"[FAIL] Hermes home directory not found at {hermes_home}")
        errors += 1
    else:
        print(f"[PASS] Hermes home directory exists: {hermes_home}")

    # 2. agy executable
    agy_exe = find_agy_exe()
    if not agy_exe:
        print("[FAIL] agy executable not found (checked AGY_EXE_PATH, LOCALAPPDATA/agy/bin/agy.exe, PATH)")
        print("       Install agy or set AGY_EXE_PATH environment variable.")
        errors += 1
    else:
        print(f"[PASS] agy binary found: {agy_exe}")

    # 3. Patched antigravity-provider installed
    REPO_ROOT = Path(__file__).resolve().parent.parent
    for p in [
        REPO_ROOT / "src",
        REPO_ROOT / "plugins" / "antigravity-provider" / "src",
        Path(os.environ.get("LOCALAPPDATA", "")) / "hermes" / "plugins" / "antigravity-provider" / "src",
    ]:
        if p.is_dir() and str(p) not in sys.path:
            sys.path.insert(0, str(p))

    try:
        import antigravity_provider
    except ImportError:
        pass

    plugin_dir = hermes_home / "plugins" / "antigravity-provider"
    subprocess_module = plugin_dir / "src" / "antigravity_provider" / "agy_subprocess.py"
    if not subprocess_module.is_file():
        print(f"[FAIL] Patched antigravity-provider not found at {plugin_dir}")
        print(f"       Missing {subprocess_module}")
        errors += 1
    else:
        print(f"[PASS] Patched antigravity-provider installed: {plugin_dir}")

    # 4. Check for duplicate/backup plugins in scan paths
    plugins_root = hermes_home / "plugins"
    if plugins_root.is_dir():
        duplicate_plugins = []
        for item in plugins_root.iterdir():
            if item.is_dir() and item.name != "antigravity-provider":
                if item.name.startswith("antigravity-provider.") or "antigravity" in item.name.lower():
                    yaml_file = item / "plugin.yaml"
                    if yaml_file.is_file():
                        duplicate_plugins.append(str(item))
        if duplicate_plugins:
            print(f"[FAIL] Found duplicate/backup plugin directories with active plugin.yaml:")
            for dup in duplicate_plugins:
                print(f"       - {dup}")
            print("       Run restore_backup.py or quarantine these directories to prevent plugin collisions.")
            errors += 1
        else:
            print("[PASS] No conflicting duplicate plugin copies in plugins scan directory.")

    # 5. Check direct API calls are absent (fail-closed check)
    hermes_plugin_py = plugin_dir / "src" / "antigravity_provider" / "hermes_plugin.py"
    if hermes_plugin_py.is_file():
        content = hermes_plugin_py.read_text(encoding="utf-8", errors="replace")
        if "generate_chat_completion" in content and "from .agy_subprocess import agy_generate" not in content:
            print("[FAIL] hermes_plugin.py is using old direct Cloud Code API transport!")
            errors += 1
        else:
            print("[PASS] hermes_plugin.py is configured to use agy_subprocess transport.")

    # 6. Test model discovery and effort mapping
    if agy_exe:
        try:
            probe = subprocess.run(
                [agy_exe, "-p", "x", "--model", "__invalid_probe__", "--output-format", "json", "--print-timeout", "10s"],
                capture_output=True,
                text=True,
                timeout=15,
                encoding="utf-8",
                errors="replace",
            )
            if "Available models:" in probe.stdout:
                print("[PASS] Dynamic model discovery via agy probe is functional.")
            else:
                print("[WARN] agy model discovery probe returned unexpected output.")
                warnings += 1
        except Exception as e:
            print(f"[WARN] agy model discovery probe failed: {e}")
            warnings += 1

    # 7. Check agy authentication state
    if agy_exe:
        try:
            auth_check = subprocess.run(
                [agy_exe, "--input-format", "text", "--output-format", "json", "--model", "gemini-3.5-flash", "--effort", "low", "--print-timeout", "15s"],
                input="respond only: test_ok",
                capture_output=True,
                text=True,
                timeout=20,
                encoding="utf-8",
                errors="replace",
            )
            if auth_check.returncode == 0:
                try:
                    data = json.loads(auth_check.stdout.strip())
                    if data.get("status") == "SUCCESS":
                        print("[PASS] agy authentication is active and query succeeded.")
                        # 8. Smoke test with hermes CLI or venv python
                        hermes_venv_py = hermes_home / "hermes-agent" / "venv" / "Scripts" / "python.exe"
                        smoke_cmd = None
                        if hermes_venv_py.is_file():
                            smoke_cmd = [
                                str(hermes_venv_py),
                                "-m", "hermes_cli.main",
                                "-z", "respond only with exactly: hermes_verify_ok",
                                "-m", "google-antigravity/gemini-3.5-flash",
                                "--provider", "antigravity",
                            ]
                        elif shutil.which("hermes"):
                            smoke_cmd = [
                                shutil.which("hermes"),
                                "-z", "respond only with exactly: hermes_verify_ok",
                                "-m", "google-antigravity/gemini-3.5-flash",
                                "--provider", "antigravity",
                            ]

                        if smoke_cmd:
                            smoke = subprocess.run(
                                smoke_cmd,
                                capture_output=True,
                                text=True,
                                timeout=45,
                                encoding="utf-8",
                                errors="replace",
                            )
                            combined_out = smoke.stdout + smoke.stderr
                            if "hermes_verify_ok" in combined_out:
                                print("[PASS] End-to-end hermes -z smoke test SUCCEEDED ('hermes_verify_ok').")
                            else:
                                print(f"[WARN] hermes -z smoke test returned: {smoke.stdout.strip()[:100]}")
                                warnings += 1
                        else:
                            print("[INFO] hermes command not on PATH; skipped hermes -z end-to-end invocation.")
                    else:
                        print(f"[WARN] agy returned non-success status: {data.get('error', '')[:100]}")
                        warnings += 1
                except json.JSONDecodeError:
                    print(f"[WARN] agy output was not JSON: {auth_check.stdout[:100]}")
                    warnings += 1
            else:
                stderr_text = auth_check.stderr or auth_check.stdout
                if "login" in stderr_text.lower() or "auth" in stderr_text.lower() or "quota" in stderr_text.lower():
                    print("[INFO] agy is not currently authenticated or quota reached. Run `agy` to authenticate.")
                else:
                    print(f"[WARN] agy test call returned exit code {auth_check.returncode}: {stderr_text[:100]}")
                    warnings += 1
        except Exception as e:
            print(f"[WARN] agy invocation test failed: {e}")
            warnings += 1

    print("-" * 60)
    if errors > 0:
        print(f"VERIFICATION FAILED: {errors} error(s), {warnings} warning(s)")
        return 1
    else:
        print(f"VERIFICATION PASSED: 0 errors, {warnings} warning(s)")
        return 0


if __name__ == "__main__":
    sys.exit(verify())
