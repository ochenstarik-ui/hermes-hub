"""Clean, verified measurement of exact live VRAM, prompt/gen speeds, and task accuracy for A45 candidates."""
import json
import os
import subprocess
import time
import urllib.request
from typing import Any, Dict, List

from benchmarks.benchmark_suite import BENCHMARK_TASKS, _compile_and_get

LLAMA_SERVER_BIN = "/home/ochenstarik/llama.cpp/build/bin/llama-server.bin"


def get_vram() -> int:
    try:
        res = subprocess.run(
            ["nvidia-smi", "--query-compute-apps=pid,used_memory", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
        )
        for line in res.stdout.strip().split("\n"):
            line = line.strip()
            if line:
                parts = line.split(",")
                if len(parts) >= 2:
                    return int(parts[1].strip())
    except Exception:
        pass
    return 0


def cleanup_8089():
    subprocess.run(["pkill", "-9", "-f", "port 8089"], capture_output=True)
    time.sleep(2)


def ping_and_wait(port=8089, timeout=120) -> bool:
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            req = urllib.request.Request(f"http://127.0.0.1:{port}/health")
            with urllib.request.urlopen(req, timeout=2) as r:
                data = json.loads(r.read().decode())
                if data.get("status") == "ok":
                    return True
        except Exception:
            pass
        time.sleep(2)
    return False


def request_chat(port: int, model_path: str, messages: List[Dict[str, str]], max_tokens: int = 1024, temperature: float = 0.2) -> Dict[str, Any]:
    req_body = {
        "model": model_path,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": False,
    }
    t0 = time.monotonic()
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/v1/chat/completions",
        data=json.dumps(req_body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=180) as resp:
        elapsed = time.monotonic() - t0
        raw = json.loads(resp.read().decode())
        raw["client_wall_time_sec"] = round(elapsed, 3)
        return raw


def test_long_context(port: int, model_path: str) -> List[Dict[str, Any]]:
    results = []
    base_filler = "In high performance distributed systems, memory consistency models and lease management require careful synchronization. " * 80
    for n_tokens in [2000, 8000, 16000, 32000, 48000]:
        multiplier = max(1, n_tokens // 1000)
        prompt = f"Background context:\n{base_filler * multiplier}\n\nTask: Output exact word 'READY'."
        try:
            res = request_chat(port, model_path, [{"role": "user", "content": prompt}], max_tokens=10, temperature=0.0)
            timings = res.get("timings", {})
            prompt_tps = timings.get("prompt_per_second", 0.0)
            gen_tps = timings.get("predicted_per_second", 0.0)
            results.append({
                "target_tokens": n_tokens,
                "prompt_tokens_per_sec": round(prompt_tps, 2),
                "gen_tokens_per_sec": round(gen_tps, 2),
                "wall_time_sec": res.get("client_wall_time_sec", 0.0),
                "status": "OK",
            })
            print(f"      [Degradation {n_tokens:5d} tok]: Prompt {prompt_tps:6.1f} t/s | Gen {gen_tps:5.1f} t/s | Wall {res.get('client_wall_time_sec', 0):.2f}s", flush=True)
        except Exception as e:
            results.append({
                "target_tokens": n_tokens,
                "error": str(e),
                "status": "FAILED_OR_TIMEOUT",
            })
            print(f"      [Degradation {n_tokens:5d} tok]: FAILED ({e})", flush=True)
    return results


def run_single_model_ctx(name: str, path: str, ctx: int) -> Dict[str, Any]:
    cleanup_8089()
    cmd = [
        LLAMA_SERVER_BIN,
        "-m", path,
        "-ngl", "99",
        "-c", str(ctx),
        "--parallel", "1",
        "--flash-attn", "on",
        "--cache-type-k", "q8_0",
        "--cache-type-v", "q8_0",
        "--reasoning", "off",
        "--temp", "0.2",
        "--host", "127.0.0.1",
        "--port", "8089",
    ]
    t_start = time.time()
    p = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        ok = ping_and_wait(8089, timeout=120)
        cold_sec = round(time.time() - t_start, 2)
        if not ok:
            print(f"[-] {name} (ctx={ctx}): Start failed / OOM")
            return {
                "context_size": ctx,
                "status": "START_FAILED_OR_OOM",
                "cold_start_sec": cold_sec,
            }
        
        vram = get_vram()
        print(f"\n[+] {name} (ctx={ctx}) READY in {cold_sec}s | VRAM: {vram} MiB", flush=True)

        # Measure baseline speed
        prompt = "Write a complete python implementation of a high-throughput async ring buffer queue with circular buffer memory management."
        res = request_chat(8089, path, [{"role": "user", "content": prompt}], max_tokens=128, temperature=0.1)
        timings = res.get("timings", {})
        gen_tps = round(timings.get("predicted_per_second", 0.0), 2)
        prompt_tps = round(timings.get("prompt_per_second", 0.0), 2)
        print(f"    - Baseline: Gen = {gen_tps} tok/s | Prompt = {prompt_tps} tok/s", flush=True)

        # 12 benchmark tasks
        passed = 0
        task_res = []
        for t in BENCHMARK_TASKS:
            try:
                r = request_chat(8089, path, [{"role": "user", "content": t.prompt}], max_tokens=1024, temperature=0.2)
                cnt = r["choices"][0]["message"]["content"]
                fn, err = _compile_and_get(cnt, t.expected_function_name)
                if err:
                    ok_task, msg = False, err
                else:
                    ok_task, msg = t.test_function(fn)
                if ok_task:
                    passed += 1
                task_res.append({
                    "task_id": t.task_id,
                    "passed": ok_task,
                    "message": msg,
                    "duration_sec": r.get("client_wall_time_sec", 0.0),
                    "timings": r.get("timings", {}),
                })
                print(f"    - [{ 'PASS' if ok_task else 'FAIL' }] {t.task_id}: {msg} ({r.get('client_wall_time_sec', 0.0):.2f}s)")
            except Exception as e:
                task_res.append({"task_id": t.task_id, "passed": False, "message": str(e), "duration_sec": 0.0})
                print(f"    - [FAIL] {t.task_id}: {e}")

        degradation = None
        if ctx == 65536:
            degradation = test_long_context(8089, path)

        return {
            "context_size": ctx,
            "status": "COMPLETED",
            "cold_start_sec": cold_sec,
            "process_vram_mib": vram,
            "generation_speed_tps": gen_tps,
            "prompt_speed_tps": prompt_tps,
            "tasks_passed": passed,
            "tasks_total": len(BENCHMARK_TASKS),
            "tasks_pass_rate_pct": round((passed / len(BENCHMARK_TASKS)) * 100, 1),
            "task_evaluations": task_res,
            "long_context_degradation": degradation,
        }
    finally:
        p.terminate()
        try:
            p.wait(timeout=5)
        except Exception:
            p.kill()
        cleanup_8089()


def get_stats(path: str) -> Dict[str, Any]:
    import hashlib
    st = os.stat(path)
    h = hashlib.sha256()
    with open(path, "rb") as f:
        h.update(f.read(64 * 1024 * 1024))
    from benchmarks.run_moe_benchmark import get_gguf_metadata
    meta = get_gguf_metadata(path)
    return {
        "filepath": path,
        "size_bytes": st.st_size,
        "size_gib": round(st.st_size / (1024**3), 2),
        "sha256_64mb": h.hexdigest(),
        "general_name": meta.get("general.name", os.path.basename(path)),
        "architecture": meta.get("general.architecture", "unknown"),
    }


def main():
    models = [
        ("Qwen3-Coder-30B-A3B-Instruct", "/srv/ai/models/qwen3-coder-30b-a3b/Qwen3-Coder-30B-A3B-Instruct-Q4_K_M.gguf"),
        ("Qwen2.5-Coder-32B-Instruct", "/srv/ai/models/qwen2.5-coder-32b/Qwen2.5-Coder-32B-Instruct-Q4_K_M.gguf"),
        ("Tiel-Coder-35B-A3B-UD-Q4_K_S", "/srv/ai/models/tiel-coder-35b-a3b/Tiel-Coder-35B-A3B-UD-Q4_K_S.gguf"),
    ]

    results = {}
    for name, path in models:
        print(f"\n===================================================================", flush=True)
        print(f" EVALUATING: {name}", flush=True)
        print(f"===================================================================", flush=True)
        stats = get_stats(path)
        ctx_map = {}
        for ctx in [65536, 32768]:
            res = run_single_model_ctx(name, path, ctx)
            ctx_map[str(ctx)] = res
        results[name] = {
            "name": name,
            "file_stats": stats,
            "contexts": ctx_map,
            "status": "COMPLETED",
        }
        with open("benchmarks/benchmark_moe_results.json", "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)

    print("\n[+] Done! Saved clean results to benchmarks/benchmark_moe_results.json")


if __name__ == "__main__":
    main()
