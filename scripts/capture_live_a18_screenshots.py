"""
Live screenshot capture for Hermes Hub Web Client (A18).
Captures model selection flow (before, selection modal, account details, and after) via Headless Chrome CLI.
"""

from __future__ import annotations

import http.server
import os
from pathlib import Path
import socket
import subprocess
import threading
import time

REPO_ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = REPO_ROOT / "src" / "antigravity_provider" / "router" / "web" / "static"
ARTIFACTS_DIR = REPO_ROOT / "artifacts" / "a18-screenshots"
ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)

CHROME_PATHS = [
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]


class StaticServer(threading.Thread):
    def __init__(self, port: int):
        super().__init__(daemon=True)
        self.port = port
        self.httpd = None

    def run(self):
        class Handler(http.server.SimpleHTTPRequestHandler):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, directory=str(STATIC_DIR), **kwargs)

            def log_message(self, *args):
                pass

        self.httpd = http.server.HTTPServer(("127.0.0.1", self.port), Handler)
        self.httpd.serve_forever()

    def stop(self):
        if self.httpd:
            self.httpd.shutdown()


def get_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main():
    port = get_free_port()
    server = StaticServer(port)
    server.start()
    print(f"Static HTTP Server running on http://127.0.0.1:{port}")
    time.sleep(0.3)

    chrome_exe = None
    for p in CHROME_PATHS:
        if os.path.isfile(p):
            chrome_exe = p
            break
    if not chrome_exe:
        raise RuntimeError("No Chrome/Edge executable found")

    temp_profile = REPO_ROOT / "artifacts" / "temp_chrome_profile"
    temp_profile.mkdir(parents=True, exist_ok=True)

    scenarios = [
        ("01_model_choice_team_before.png", f"http://127.0.0.1:{port}/index.html?view=team"),
        ("02_model_choice_modal.png", f"http://127.0.0.1:{port}/index.html?modal=agent_model&role=coder-primary"),
        ("03_model_choice_account_details.png", f"http://127.0.0.1:{port}/index.html?modal=account_details&profile=ag-w1"),
        ("04_web_accounts_view.png", f"http://127.0.0.1:{port}/index.html?view=accounts"),
        ("05_web_providers_discovered_models.png", f"http://127.0.0.1:{port}/index.html?view=providers"),
    ]

    captured_count = 0
    for filename, url in scenarios:
        out_file = ARTIFACTS_DIR / filename
        cmd = [
            chrome_exe,
            "--headless=new",
            "--disable-gpu",
            "--no-sandbox",
            "--hide-scrollbars",
            "--virtual-time-budget=2000",
            f"--user-data-dir={temp_profile}",
            "--window-size=1440,920",
            f"--screenshot={out_file}",
            url,
        ]
        res = subprocess.run(cmd, capture_output=True, timeout=20)
        if res.returncode == 0 and out_file.exists():
            size = out_file.stat().st_size
            print(f"Captured: {filename} ({size} bytes)")
            captured_count += 1
        else:
            print(f"FAILED to capture {filename}: returncode {res.returncode}")

    server.stop()
    print(f"\nTotal screenshots captured: {captured_count}/{len(scenarios)}")


if __name__ == "__main__":
    main()
