"""Benchmark runner for evaluating local LLMs on Tesla V100 hardware according to A40 rules."""
from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import urllib.request
import urllib.error
import gguf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from benchmarks.benchmark_suite import BENCHMARK_TASKS, BenchmarkTask, _compile_and_get


def get_vram_usage_mib() -> int:
    """Query current GPU VRAM usage in MiB via nvidia-smi."""
    try:
        res = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return int(res.stdout.strip().split()[0])
    except Exception:
        return 0


def get_gguf_metadata(file_path: str) -> Dict[str, Any]:
    """Extract general.name, general.architecture, file size in bytes, and sha256 of first 64MB."""
    p = Path(file_path)
    if not p.is_file():
        return {
            "exists": False,
            "error": f"File not found: {file_path}",
        }

    st = p.stat()
    size_bytes = st.st_size

    # SHA256 of first 64MB
    with open(p, "rb") as f:
        head_bytes = f.read(64 * 1024 * 1024)
        sha256_head = hashlib.sha256(head_bytes).hexdigest()

    general_name = "unknown"
    general_arch = "unknown"
    try:
        reader = gguf.GGUFReader(file_path)
        for field in reader.fields.values():
            if field.name == "general.name":
                general_name = bytes(field.parts[field.data[0]]).decode("utf-8", "ignore")
            elif field.name == "general.architecture":
                general_arch = bytes(field.parts[field.data[0]]).decode("utf-8", "ignore")
    except Exception as e:
        general_name = f"Error reading GGUF: {e}"

    return {
        "exists": True,
        "file_path": str(p.resolve()),
        "file_size_bytes": size_bytes,
        "file_size_gib": round(size_bytes / (1024**3), 2),
        "sha256_64mb": sha256_head,
        "general_name": general_name,
        "general_arch": general_arch,
    }


def call_model_api(
    endpoint_url: str,
    model_id: str,
    prompt: str,
    system_prompt: str = "You are an expert Python software engineer. Write clean, robust, working Python code without extra conversational filler.",
    max_tokens: int = 2048,
    temperature: float = 0.2,
    timeout: int = 180,
) -> Tuple[Optional[str], float, Dict[str, Any], Dict[str, Any], Optional[str]]:
    """Send chat completion request to OpenAI-compatible endpoint.

    Returns: (generated_text, elapsed_seconds, usage_dict, timings_dict, error_string)
    """
    req_body = {
        "model": model_id,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    data_bytes = json.dumps(req_body).encode("utf-8")
    req = urllib.request.Request(
        endpoint_url,
        data=data_bytes,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            elapsed = time.monotonic() - t0
            parsed = json.loads(raw)
            choices = parsed.get("choices") or []
            if not choices:
                return None, elapsed, {}, {}, "No choices returned from model"
            content = choices[0].get("message", {}).get("content", "")
            usage = parsed.get("usage") or {}
            timings = parsed.get("timings") or {}
            return content, elapsed, usage, timings, None
    except Exception as e:
        elapsed = time.monotonic() - t0
        return None, elapsed, {}, {}, f"{type(e).__name__}: {e}"


def run_model_benchmark(
    endpoint_url: str,
    model_id: str,
    display_name: str,
    model_file_path: str,
) -> Dict[str, Any]:
    print(f"\n=======================================================", flush=True)
    print(f"[*] Benchmarking Model: {display_name} ({model_id})", flush=True)
    print(f"    Endpoint: {endpoint_url}", flush=True)
    print(f"    File:     {model_file_path}", flush=True)
    print(f"=======================================================", flush=True)

    meta = get_gguf_metadata(model_file_path)
    if not meta.get("exists"):
        print(f"[!] ERROR: Model file does not exist on disk: {model_file_path}", flush=True)
        return {
            "model_id": model_id,
            "display_name": display_name,
            "status": "FILE_NOT_FOUND",
            "error": f"File does not exist: {model_file_path}",
        }

    print(f"[*] GGUF General Name: {meta['general_name']}", flush=True)
    print(f"[*] GGUF Architecture: {meta['general_arch']}", flush=True)
    print(f"[*] File Size:         {meta['file_size_bytes']} bytes ({meta['file_size_gib']} GiB)", flush=True)
    print(f"[*] SHA256 (first 64M): {meta['sha256_64mb']}", flush=True)

    # 1. Warm-up / Cold-load measurement
    print(f"[*] Measuring initial warmup...", flush=True)
    vram_before = get_vram_usage_mib()
    warmup_text, warmup_elapsed, warmup_usage, warmup_timings, warmup_err = call_model_api(
        endpoint_url, model_id, "Output exact string 'OK'", max_tokens=10, timeout=240
    )
    cold_load_sec = round(warmup_elapsed, 2)
    vram_active = get_vram_usage_mib()

    if warmup_err:
        print(f"[!] Warmup/Load Error: {warmup_err}", flush=True)
        return {
            "model_id": model_id,
            "display_name": display_name,
            "meta": meta,
            "status": "LOAD_ERROR",
            "error": warmup_err,
            "cold_load_sec": cold_load_sec,
            "vram_active_mib": vram_active,
        }

    print(f"[+] Warmup time: {cold_load_sec}s | VRAM active: {vram_active} MiB", flush=True)

    # 2. Run 12 Tasks
    task_results = []
    total_prompt_tokens = 0
    total_completion_tokens = 0
    total_eval_time = 0.0
    passed_count = 0
    raw_timings_samples = []

    for idx, task in enumerate(BENCHMARK_TASKS, 1):
        print(f"\n  [{idx}/12] Running {task.task_id}: {task.title}...", flush=True)
        prompt_text = task.prompt
        if task.is_long_context:
            filler = "# System architecture table and routes\n" + ("# Context: router lease table lease_id metadata status\n" * 800)
            prompt_text = f"{filler}\n\n{task.prompt}"

        content, elapsed, usage, timings, err = call_model_api(
            endpoint_url, model_id, prompt_text, max_tokens=2048, timeout=180
        )

        p_tokens = usage.get("prompt_tokens", len(prompt_text) // 4)
        c_tokens = usage.get("completion_tokens", len(content or "") // 4)
        total_prompt_tokens += p_tokens
        total_completion_tokens += c_tokens
        total_eval_time += elapsed

        if timings:
            raw_timings_samples.append(timings)

        if err:
            print(f"      [-] Execution Error: {err}", flush=True)
            task_results.append({
                "task_id": task.task_id,
                "title": task.title,
                "passed": False,
                "error": err,
                "elapsed": round(elapsed, 2),
                "tokens": c_tokens,
                "timings": timings,
            })
            continue

        target_fn, compile_err = _compile_and_get(content or "", task.expected_function_name)
        if compile_err:
            print(f"      [-] Compilation/Load Error: {compile_err}", flush=True)
            task_results.append({
                "task_id": task.task_id,
                "title": task.title,
                "passed": False,
                "error": compile_err,
                "elapsed": round(elapsed, 2),
                "tokens": c_tokens,
                "timings": timings,
                "code_snippet": (content or "")[:200],
            })
            continue

        # Execute test function with a 5-second timeout protection
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(task.test_function, target_fn)
                ok, test_msg = future.result(timeout=5.0)
        except concurrent.futures.TimeoutError:
            ok, test_msg = False, "Test function timed out (>5.0s, possible blocking acquire/sleep)"
        except Exception as test_exc:
            ok, test_msg = False, f"Exception executing test function: {test_exc}"

        if ok:
            passed_count += 1
            print(f"      [+] PASSED: {test_msg} ({c_tokens} tokens in {elapsed:.2f}s)", flush=True)
        else:
            print(f"      [-] FAILED: {test_msg}", flush=True)

        task_results.append({
            "task_id": task.task_id,
            "title": task.title,
            "passed": ok,
            "message": test_msg,
            "elapsed": round(elapsed, 2),
            "tokens": c_tokens,
            "timings": timings,
        })

    # Speed metrics from raw timings or fallback
    pred_speeds = [t.get("predicted_per_second") for t in raw_timings_samples if t.get("predicted_per_second")]
    prompt_speeds = [t.get("prompt_per_second") for t in raw_timings_samples if t.get("prompt_per_second")]

    avg_gen_speed = round(sum(pred_speeds) / len(pred_speeds), 2) if pred_speeds else round(total_completion_tokens / max(total_eval_time, 0.001), 2)
    avg_prompt_speed = round(sum(prompt_speeds) / len(prompt_speeds), 2) if prompt_speeds else 0.0

    pass_rate_pct = round((passed_count / len(BENCHMARK_TASKS)) * 100, 1)

    print(f"\n[+] Results for {display_name}:", flush=True)
    print(f"    - General Name:        {meta['general_name']}", flush=True)
    print(f"    - Pass Rate:           {passed_count}/{len(BENCHMARK_TASKS)} ({pass_rate_pct}%)", flush=True)
    print(f"    - Avg Gen Speed:       {avg_gen_speed} tok/s (raw timings)", flush=True)
    print(f"    - Avg Prompt Speed:    {avg_prompt_speed} tok/s (raw timings)", flush=True)
    print(f"    - VRAM Active:         {vram_active} MiB", flush=True)
    print(f"    - Warmup Time:         {cold_load_sec}s", flush=True)

    return {
        "model_id": model_id,
        "display_name": display_name,
        "meta": meta,
        "status": "COMPLETED",
        "passed_tasks": passed_count,
        "total_tasks": len(BENCHMARK_TASKS),
        "pass_rate_pct": pass_rate_pct,
        "gen_tokens_per_sec": avg_gen_speed,
        "prompt_tokens_per_sec": avg_prompt_speed,
        "cold_load_sec": cold_load_sec,
        "vram_active_mib": vram_active,
        "raw_timings_sample": raw_timings_samples[0] if raw_timings_samples else {},
        "tasks": task_results,
    }


def main():
    parser = argparse.ArgumentParser(description="Run LLM benchmark suite according to A40 rules")
    parser.add_argument("--endpoint", default="http://127.0.0.1:8089/v1/chat/completions", help="Endpoint URL")
    parser.add_argument("--model-id", default=None, required=True, help="Model ID")
    parser.add_argument("--model-name", default=None, help="Display Name")
    parser.add_argument("--model-path", default=None, required=True, help="Model File Path on Disk")
    parser.add_argument("--output", default="benchmarks/benchmark_results.json", help="Output JSON path")
    args = parser.parse_args()

    res = run_model_benchmark(
        endpoint_url=args.endpoint,
        model_id=args.model_id,
        display_name=args.model_name or args.model_id,
        model_file_path=args.model_path,
    )

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    existing = []
    if out_path.is_file():
        try:
            existing = json.loads(out_path.read_text(encoding="utf-8"))
        except Exception:
            existing = []

    existing = [item for item in existing if item.get("meta", {}).get("file_path") != res.get("meta", {}).get("file_path")]
    existing.append(res)
    out_path.write_text(json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n[+] Results saved to {out_path}", flush=True)


if __name__ == "__main__":
    main()
