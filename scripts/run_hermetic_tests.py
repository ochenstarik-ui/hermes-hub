#!/usr/bin/env python3
"""Hard wall-clock wrapper for the hermetic pytest suite.

A hanging suite is terminated. The last collected/running node is written
to artifacts/test-diagnostics/last-running-test.txt when possible.
"""
from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LIMIT = 480  # 8 minutes: enough for ~500 hermetic tests, not 15 hours


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help="Wall-clock seconds")
    parser.add_argument("pytest_args", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    pytest_args = list(args.pytest_args)
    if pytest_args and pytest_args[0] == "--":
        pytest_args = pytest_args[1:]
    out_dir = ROOT / "artifacts" / "test-diagnostics"
    out_dir.mkdir(parents=True, exist_ok=True)
    last_path = out_dir / "last-running-test.txt"
    cmd = [
        args.python,
        "-X",
        "faulthandler",
        "-m",
        "pytest",
        "-vv",
        "--tb=short",
        *pytest_args,
    ]
    env = os.environ.copy()
    env["PYTHONFAULTHANDLER"] = "1"
    start = time.monotonic()
    proc = subprocess.Popen(
        cmd,
        cwd=str(ROOT),
        env=env,
        start_new_session=True,
    )
    try:
        return_code = proc.wait(timeout=args.limit)
        last_path.write_text(
            f"completed rc={return_code} duration={time.monotonic() - start:.1f}s\n",
            encoding="utf-8",
        )
        return return_code
    except subprocess.TimeoutExpired:
        last_path.write_text(
            f"TIMEOUT after {args.limit}s pid={proc.pid}\ncmd={' '.join(cmd)}\n",
            encoding="utf-8",
        )
        try:
            os.killpg(proc.pid, signal.SIGABRT)
            time.sleep(0.5)
        except (ProcessLookupError, PermissionError, OSError):
            pass
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            proc.kill()
        print(
            f"HERMETIC SUITE WALL CLOCK EXCEEDED ({args.limit}s). Killed pid={proc.pid}. "
            f"See {last_path}",
            file=sys.stderr,
        )
        return 124


if __name__ == "__main__":
    raise SystemExit(main())
