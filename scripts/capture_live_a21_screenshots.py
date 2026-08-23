"""
Hermes Hub — Task A21 Screenshot Capture Script
Captures high-resolution (1440x920) screenshots for all 4 new screens:
1. Analytics (Аналитика)
2. Health / Readiness (Состояние)
3. Logs (Журнал событий)
4. Settings (Настройки)
"""

from __future__ import annotations

import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

import uvicorn
from antigravity_provider.router.web.server import app
from antigravity_provider.router.unified_health import EventLogService

ARTIFACTS_DIR = REPO_ROOT / "artifacts" / "a21-screenshots"
ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)

CHROME_PATHS = [
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]


def get_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def seed_event_logs():
    svc = EventLogService.get()
    svc.log("system", "Hermes Hub запущен в нативном режиме Windows.", level="info")
    svc.log("account", "Обновлены квоты для 22 аккаунтов (Antigravity, Codex, Grok, Claude, OpenCode).", level="info")
    svc.log("routing", "Основной маршрут 'coder-primary' переключен на ag-w1.", level="info")
    svc.log("quota", "Превышен лимит запросов для резервного профиля codex-2.", level="warning", details="HTTP 429 Too Many Requests от OpenAI API")
    svc.log("system", "Фоновая синхронизация конфигурации завершена успешно.", level="info")
    svc.log("routing", "Автоматический failover: 'reviewer' переведён на claude-main.", level="warning", details="Таймаут первичного узла grok-fast")


def main():
    seed_event_logs()

    port = get_free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)

    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    time.sleep(1.0)

    chrome_exe = None
    for p in CHROME_PATHS:
        if os.path.isfile(p):
            chrome_exe = p
            break
    if not chrome_exe:
        raise RuntimeError("No Chrome/Edge executable found")

    temp_profile = REPO_ROOT / "artifacts" / "temp_chrome_profile_a21"
    temp_profile.mkdir(parents=True, exist_ok=True)

    scenarios = [
        ("01_analytics_view.png", f"http://127.0.0.1:{port}/index.html?view=analytics"),
        ("02_health_view.png", f"http://127.0.0.1:{port}/index.html?view=health"),
        ("03_logs_view.png", f"http://127.0.0.1:{port}/index.html?view=logs"),
        ("04_settings_view.png", f"http://127.0.0.1:{port}/index.html?view=settings"),
    ]

    captured = 0
    for filename, url in scenarios:
        out_file = ARTIFACTS_DIR / filename
        cmd = [
            chrome_exe,
            "--headless=new",
            "--disable-gpu",
            "--no-sandbox",
            "--hide-scrollbars",
            "--virtual-time-budget=2500",
            f"--user-data-dir={temp_profile}",
            "--window-size=1440,920",
            f"--screenshot={out_file}",
            url,
        ]
        print(f"Capturing: {filename}...")
        subprocess.run(cmd, capture_output=True, timeout=15)
        if out_file.is_file() and out_file.stat().st_size > 1000:
            print(f"  [OK] Saved {out_file.name} ({out_file.stat().st_size // 1024} KB)")
            captured += 1
        else:
            print(f"  [FAIL] Could not generate {out_file.name}")

    server.should_exit = True
    print(f"\nCaptured {captured}/{len(scenarios)} screenshots in {ARTIFACTS_DIR}")


if __name__ == "__main__":
    main()
