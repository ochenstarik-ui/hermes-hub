#!/usr/bin/env python3
"""Per-file and per-node pytest hang diagnostic runner.

Each file (or node) is a separate subprocess with a hard timeout.
One hang never blocks the rest of the suite.
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "artifacts" / "test-diagnostics"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def list_test_files() -> list[Path]:
    tests_dir = ROOT / "tests"
    return sorted(p for p in tests_dir.glob("test_*.py") if p.is_file())


def collect_node_ids(python: str, test_file: Path, collect_timeout: int) -> list[str]:
    cmd = [
        python,
        "-m",
        "pytest",
        str(test_file),
        "--collect-only",
        "-q",
        "--no-header",
    ]
    proc = subprocess.run(
        cmd,
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=collect_timeout,
        env=os.environ.copy(),
    )
    nodes: list[str] = []
    for line in (proc.stdout or "").splitlines():
        line = line.strip()
        if line.startswith(str(test_file).replace("\\", "/")) or line.startswith("tests/"):
            if "::" in line and not line.startswith("="):
                nodes.append(line.split()[0])
        elif "::" in line and not line.startswith("=") and "error" not in line.lower():
            if line.startswith("test_") or "/test_" in line or line.startswith("tests"):
                nodes.append(line.split()[0])
    # Fallback: pytest -q collect prints node ids as first token.
    if not nodes:
        for line in (proc.stdout or "").splitlines():
            stripped = line.strip()
            if "::" in stripped and not stripped.startswith("="):
                nodes.append(stripped.split()[0])
    return nodes


def _kill_tree(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            proc.kill()
        except Exception:
            pass
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass


def run_guarded(
    python: str,
    target: str,
    timeout_s: int,
    log_dir: Path,
    extra_args: list[str] | None = None,
) -> dict:
    safe_name = target.replace("/", "_").replace("::", "__").replace("[", "_").replace("]", "_")
    stdout_path = log_dir / f"{safe_name}.stdout.txt"
    stderr_path = log_dir / f"{safe_name}.stderr.txt"
    dump_path = log_dir / f"{safe_name}.faulthandler.txt"
    cmd = [
        python,
        "-X",
        "faulthandler",
        "-m",
        "pytest",
        target,
        "-vv",
        "--tb=short",
        "-p",
        "no:cacheprovider",
    ]
    if extra_args:
        cmd.extend(extra_args)
    env = os.environ.copy()
    env["PYTHONFAULTHANDLER"] = "1"
    start = time.monotonic()
    start_iso = utc_now()
    status = "UNKNOWN"
    return_code: int | None = None
    timed_out = False
    dump = ""
    stdout_text = ""
    stderr_text = ""
    try:
        with open(stdout_path, "w", encoding="utf-8") as out_f, open(
            stderr_path, "w", encoding="utf-8"
        ) as err_f:
            proc = subprocess.Popen(
                cmd,
                cwd=str(ROOT),
                stdout=out_f,
                stderr=err_f,
                text=True,
                start_new_session=True,
                env=env,
            )
            try:
                return_code = proc.wait(timeout=timeout_s)
            except subprocess.TimeoutExpired:
                timed_out = True
                try:
                    os.killpg(proc.pid, signal.SIGABRT)
                    time.sleep(0.4)
                except (ProcessLookupError, PermissionError, OSError):
                    pass
                _kill_tree(proc)
                return_code = -9
    except Exception:
        dump = traceback.format_exc()
        status = "ERROR"
        return_code = -1
    duration = round(time.monotonic() - start, 3)
    try:
        stdout_text = stdout_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        stdout_text = ""
    try:
        stderr_text = stderr_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        stderr_text = ""
    if timed_out:
        status = "TIMEOUT"
        dump_parts = [dump, "=== STDERR TAIL ===\n" + stderr_text[-8000:], "=== STDOUT TAIL ===\n" + stdout_text[-8000:]]
        dump = "\n".join(p for p in dump_parts if p)
        dump_path.write_text(dump, encoding="utf-8")
    elif return_code == 0:
        status = "PASS"
    else:
        status = "FAIL"
        dump_path.write_text(
            (stderr_text[-8000:] + "\n" + stdout_text[-8000:]),
            encoding="utf-8",
        )
    return {
        "target": target,
        "start_time": start_iso,
        "duration": duration,
        "return_code": return_code,
        "status": status,
        "stdout_path": str(stdout_path),
        "stderr_path": str(stderr_path),
        "dump_path": str(dump_path) if dump_path.exists() else None,
        "timed_out": timed_out,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--file-timeout", type=int, default=90)
    parser.add_argument("--node-timeout", type=int, default=30)
    parser.add_argument("--collect-timeout", type=int, default=30)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--mode", choices=["files", "nodes"], default="files")
    parser.add_argument("--file", action="append", default=[])
    args = parser.parse_args()
    out_dir = args.out
    logs = out_dir / ("file-logs" if args.mode == "files" else "node-logs")
    logs.mkdir(parents=True, exist_ok=True)
    if args.file:
        files = [Path(f) if Path(f).is_absolute() else ROOT / f for f in args.file]
    else:
        files = list_test_files()
    results: list[dict] = []
    if args.mode == "files":
        for path in files:
            rel = str(path.relative_to(ROOT)) if path.is_absolute() else str(path)
            print(f"[RUN FILE] {rel}", flush=True)
            rec = run_guarded(args.python, rel, args.file_timeout, logs)
            rec["file"] = rel
            results.append(rec)
            print(f"  -> {rec['status']} {rec['duration']}s rc={rec['return_code']}", flush=True)
        payload = {
            "generated_at": utc_now(),
            "mode": "files",
            "file_timeout": args.file_timeout,
            "results": results,
            "summary": {
                "total": len(results),
                "pass": sum(1 for r in results if r["status"] == "PASS"),
                "fail": sum(1 for r in results if r["status"] == "FAIL"),
                "timeout": sum(1 for r in results if r["status"] == "TIMEOUT"),
            },
        }
        out_path = out_dir / "file-results.json"
    else:
        for path in files:
            rel = str(path.relative_to(ROOT)) if path.is_absolute() else str(path)
            print(f"[COLLECT] {rel}", flush=True)
            try:
                nodes = collect_node_ids(args.python, Path(rel), args.collect_timeout)
            except subprocess.TimeoutExpired:
                results.append(
                    {
                        "file": rel,
                        "target": rel,
                        "status": "COLLECT_TIMEOUT",
                        "start_time": utc_now(),
                        "duration": args.collect_timeout,
                        "return_code": -9,
                        "timed_out": True,
                    }
                )
                continue
            if not nodes:
                print(f"  no nodes collected for {rel}", flush=True)
                continue
            for node in nodes:
                print(f"[RUN NODE] {node}", flush=True)
                rec = run_guarded(args.python, node, args.node_timeout, logs)
                rec["file"] = rel
                rec["node_id"] = node
                results.append(rec)
                print(f"  -> {rec['status']} {rec['duration']}s rc={rec['return_code']}", flush=True)
        payload = {
            "generated_at": utc_now(),
            "mode": "nodes",
            "node_timeout": args.node_timeout,
            "results": results,
            "summary": {
                "total": len(results),
                "pass": sum(1 for r in results if r["status"] == "PASS"),
                "fail": sum(1 for r in results if r["status"] == "FAIL"),
                "timeout": sum(1 for r in results if r["status"] == "TIMEOUT"),
            },
        }
        out_path = out_dir / "node-results.json"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload["summary"], indent=2), flush=True)
    print(f"wrote {out_path}", flush=True)
    return 0 if payload["summary"]["timeout"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
