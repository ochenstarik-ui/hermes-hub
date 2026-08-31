"""Automated Benchmark Runner for MoE Candidates on Tesla V100 32GB (Task A45).

Measures:
- Cold load time
- Per-process VRAM via `nvidia-smi --query-compute-apps=pid,used_memory`
- Prompt processing & token generation speeds at both 32k and 64k context
- 12 code generation and evaluation tasks from `benchmarks.benchmark_suite`
- Long context degradation analysis (MoE attention scaling)
"""
import hashlib
import json
import os
import re
import struct
import subprocess
import sys
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

from benchmarks.benchmark_suite import BENCHMARK_TASKS, _compile_and_get

LLAMA_SERVER_BIN = "/home/ochenstarik/llama.cpp/build/bin/llama-server"


def get_gguf_metadata(filepath: str) -> Dict[str, Any]:
    """Parse basic GGUF metadata to extract general.name and architecture."""
    meta: Dict[str, Any] = {"general.name": "Unknown", "architecture": "Unknown"}
    try:
        with open(filepath, "rb") as f:
            magic = f.read(4)
            if magic != b"GGUF":
                return meta
            version = struct.unpack("<I", f.read(4))[0]
            tensor_count = struct.unpack("<Q", f.read(8))[0]
            kv_count = struct.unpack("<Q", f.read(8))[0]

            for _ in range(min(kv_count, 100)):
                key_len = struct.unpack("<Q", f.read(8))[0]
                if key_len > 256 or key_len <= 0:
                    break
                key = f.read(key_len).decode("utf-8", errors="ignore")
                val_type = struct.unpack("<I", f.read(4))[0]

                # string type = 8
                if val_type == 8:
                    str_len = struct.unpack("<Q", f.read(8))[0]
                    if str_len > 1024 or str_len <= 0:
                        continue
                    val = f.read(str_len).decode("utf-8", errors="ignore")
                    if key in ("general.name", "general.architecture", "general.type"):
                        meta[key] = val
                    if "general.name" in meta and "general.architecture" in meta and meta["general.name"] != "Unknown" and meta["general.architecture"] != "Unknown":
                        break
                elif val_type in (0, 1, 2, 3, 4, 5, 6, 7):
                    sizes = {0: 1, 1: 1, 2: 2, 3: 2, 4: 4, 5: 4, 6: 4, 7: 1, 9: 8, 10: 8, 11: 8}
                    f.seek(sizes.get(val_type, 4), 1)
                else:
                    break
    except Exception as e:
        print(f"Metadata read error: {e}")
    return meta


def get_file_stats(filepath: str) -> Dict[str, Any]:
    st = os.stat(filepath)
    size_bytes = st.st_size
    size_gib = size_bytes / (1024**3)

    hasher = hashlib.sha256()
    with open(filepath, "rb") as f:
        chunk = f.read(64 * 1024 * 1024)
        hasher.update(chunk)
    sha256_first64mb = hasher.hexdigest()

    meta = get_gguf_metadata(filepath)
    return {
        "filepath": filepath,
        "size_bytes": size_bytes,
        "size_gib": round(size_gib, 2),
        "sha256_64mb": sha256_first64mb,
        "general_name": meta.get("general.name", os.path.basename(filepath)),
        "architecture": meta.get("general.architecture", "unknown"),
    }


def get_proc_gpu_vram(pid: int) -> int:
    try:
        res = subprocess.run(
            ["nvidia-smi", "--query-compute-apps=pid,used_memory", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        for line in res.stdout.strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 2 and int(parts[0]) == pid:
                return int(parts[1])
    except Exception as e:
        print(f"Error reading GPU VRAM for PID {pid}: {e}")
    return 0


def cleanup_port(port: int):
    """Ensure no process is lingering on port."""
    subprocess.run(["pkill", "-9", "-f", f"port {port}"], capture_output=True)
    time.sleep(2)


def ping_health(port: int, timeout: int = 180) -> bool:
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            req = urllib.request.Request(f"http://127.0.0.1:{port}/health")
            with urllib.request.urlopen(req, timeout=2) as resp:
                data = json.loads(resp.read().decode())
                if data.get("status") == "ok":
                    return True
        except urllib.error.HTTPError:
            pass  # HTTP 503 means model is still loading
        except Exception:
            pass
        time.sleep(2)
    return False


def request_chat_completion(port: int, model_path: str, messages: List[Dict[str, str]], max_tokens: int = 1024, temperature: float = 0.2) -> Dict[str, Any]:
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


def test_speed_synthetic(port: int, model_path: str, num_gen_tokens: int = 128) -> Tuple[float, float, Dict[str, Any]]:
    """Measure raw prompt processing and token generation speeds."""
    prompt = "Write a complete python implementation of a high-throughput async ring buffer queue with circular buffer memory management and lock-free atomic pointers."
    res = request_chat_completion(port, model_path, [{"role": "user", "content": prompt}], max_tokens=num_gen_tokens, temperature=0.1)
    timings = res.get("timings", {})
    gen_tps = timings.get("predicted_per_second", 0.0)
    prompt_tps = timings.get("prompt_per_second", 0.0)
    return gen_tps, prompt_tps, res


def test_long_context_degradation(port: int, model_path: str) -> List[Dict[str, Any]]:
    """Test response throughput across increasing context sizes (2k, 8k, 16k, 32k, 48k tokens)."""
    results = []
    base_filler = "In Python distributed systems, memory consistency models and lease management require careful synchronization. " * 80

    target_tokens = [2000, 8000, 16000, 32000, 48000]
    for n_tokens in target_tokens:
        multiplier = max(1, n_tokens // 1000)
        filler = base_filler * multiplier
        prompt = f"Background context:\n{filler}\n\nTask: Output exact word 'READY'."
        try:
            res = request_chat_completion(port, model_path, [{"role": "user", "content": prompt}], max_tokens=10, temperature=0.0)
            timings = res.get("timings", {})
            prompt_ms = timings.get("prompt_ms", 0.0)
            prompt_n = timings.get("prompt_n", 0)
            prompt_tps = timings.get("prompt_per_second", 0.0)
            gen_tps = timings.get("predicted_per_second", 0.0)
            results.append({
                "target_tokens": n_tokens,
                "actual_prompt_tokens": prompt_n,
                "prompt_ms": round(prompt_ms, 1),
                "prompt_tokens_per_sec": round(prompt_tps, 2),
                "gen_tokens_per_sec": round(gen_tps, 2),
                "wall_time_sec": res.get("client_wall_time_sec", 0.0),
                "status": "OK",
            })
            print(f"      [Context {n_tokens:5d} tok]: Prompt {prompt_tps:6.1f} t/s | Gen {gen_tps:5.1f} t/s | Wall {res.get('client_wall_time_sec', 0):.2f}s", flush=True)
        except Exception as e:
            results.append({
                "target_tokens": n_tokens,
                "error": str(e),
                "status": "FAILED_OR_TIMEOUT",
            })
            print(f"      [Context {n_tokens:5d} tok]: FAILED ({e})", flush=True)
    return results


def run_benchmark_for_model(
    name: str,
    filepath: str,
    contexts: List[int] = [65536, 32768],
    port: int = 8089,
) -> Dict[str, Any]:
    print(f"\n===================================================================", flush=True)
    print(f" BENCHMARKING CANDIDATE: {name}", flush=True)
    print(f" File: {filepath}", flush=True)
    print(f"===================================================================", flush=True)

    if not os.path.exists(filepath):
        print(f"[-] File not found: {filepath}")
        return {
            "name": name,
            "filepath": filepath,
            "status": "FILE_NOT_FOUND",
            "reason": "Model file not present on server disk",
        }

    stats = get_file_stats(filepath)
    print(f"[+] File Size: {stats['size_gib']} GiB ({stats['size_bytes']} bytes)")
    print(f"[+] SHA256 (64MB): {stats['sha256_64mb']}")
    print(f"[+] GGUF Name: {stats['general_name']}, Arch: {stats['architecture']}")

    context_results = {}

    for ctx in contexts:
        cleanup_port(port)
        print(f"\n[*] Launching llama-server with Context Size = {ctx} (-c {ctx})...", flush=True)
        cmd = [
            LLAMA_SERVER_BIN,
            "-m", filepath,
            "-ngl", "99",
            "-c", str(ctx),
            "--parallel", "1",
            "--flash-attn", "on",
            "--cache-type-k", "q8_0",
            "--cache-type-v", "q8_0",
            "--reasoning", "off",
            "--temp", "0.2",
            "--host", "127.0.0.1",
            "--port", str(port),
        ]
        
        t_start = time.time()
        p = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        try:
            ok = ping_health(port, timeout=180)
            cold_start_sec = round(time.time() - t_start, 2)
            if not ok:
                print(f"[-] Failed to start llama-server within 180s for -c {ctx} (OOM or crash)")
                context_results[str(ctx)] = {
                    "context_size": ctx,
                    "status": "START_FAILED_OR_OOM",
                    "reason": "CUDA out of memory or context allocation failure on 32GB VRAM",
                    "cold_start_sec": cold_start_sec,
                }
                continue

            vram_mib = get_proc_gpu_vram(p.pid)
            print(f"[+] Cold start time: {cold_start_sec}s | Process VRAM: {vram_mib} MiB")

            # 1. Measure raw speeds
            print(f"[*] Measuring Generation & Prompt Speed at -c {ctx}...", flush=True)
            try:
                gen_tps, prompt_tps, speed_raw = test_speed_synthetic(port, filepath, num_gen_tokens=128)
                print(f"    - Generation Speed: {gen_tps:.2f} tok/s")
                print(f"    - Prompt Speed:     {prompt_tps:.2f} tok/s")
            except Exception as e:
                print(f"    - Generation Speed Test Failed: {e}")
                gen_tps, prompt_tps, speed_raw = 0.0, 0.0, {"error": str(e)}

            # 2. Run 12 Benchmark Tasks
            print(f"[*] Running 12 Hermes Codebase Benchmark Tasks at -c {ctx}...", flush=True)
            task_results = []
            passed_count = 0

            for t in BENCHMARK_TASKS:
                try:
                    res = request_chat_completion(port, filepath, [{"role": "user", "content": t.prompt}], max_tokens=1024, temperature=0.2)
                    content = res["choices"][0]["message"]["content"]
                    timings = res.get("timings", {})
                    fn, err = _compile_and_get(content, t.expected_function_name)
                    if err:
                        success = False
                        msg = err
                    else:
                        success, msg = t.test_function(fn)
                    
                    if success:
                        passed_count += 1
                    
                    task_results.append({
                        "task_id": t.task_id,
                        "title": t.title,
                        "category": t.category,
                        "passed": success,
                        "message": msg,
                        "duration_sec": res.get("client_wall_time_sec", 0.0),
                        "timings": timings,
                        "response_preview": content[:150],
                    })
                    print(f"    - [{ 'PASS' if success else 'FAIL' }] {t.task_id}: {msg} ({res.get('client_wall_time_sec', 0.0):.2f}s)")
                except Exception as e:
                    task_results.append({
                        "task_id": t.task_id,
                        "title": t.title,
                        "category": t.category,
                        "passed": False,
                        "message": f"Exception: {e}",
                        "duration_sec": 0.0,
                    })
                    print(f"    - [FAIL] {t.task_id}: Exception {e}")

            # 3. Long Context Degradation (only on 64k)
            long_context_degradation = None
            if ctx == 65536:
                print(f"[*] Running Long Context Degradation Profile...", flush=True)
                long_context_degradation = test_long_context_degradation(port, filepath)

            context_results[str(ctx)] = {
                "context_size": ctx,
                "status": "COMPLETED",
                "cold_start_sec": cold_start_sec,
                "process_vram_mib": vram_mib,
                "generation_speed_tps": round(gen_tps, 2),
                "prompt_speed_tps": round(prompt_tps, 2),
                "tasks_passed": passed_count,
                "tasks_total": len(BENCHMARK_TASKS),
                "tasks_pass_rate_pct": round((passed_count / len(BENCHMARK_TASKS)) * 100, 1),
                "speed_timings_raw": speed_raw.get("timings", {}),
                "task_evaluations": task_results,
                "long_context_degradation": long_context_degradation,
            }
        finally:
            p.terminate()
            try:
                p.wait(timeout=5)
            except Exception:
                p.kill()
            cleanup_port(port)

    return {
        "name": name,
        "file_stats": stats,
        "contexts": context_results,
        "status": "COMPLETED",
    }


def main():
    models_to_test = [
        ("Qwen3-Coder-30B-A3B-Instruct", "/srv/ai/models/qwen3-coder-30b-a3b/Qwen3-Coder-30B-A3B-Instruct-Q4_K_M.gguf"),
        ("Qwen2.5-Coder-32B-Instruct", "/srv/ai/models/qwen2.5-coder-32b/Qwen2.5-Coder-32B-Instruct-Q4_K_M.gguf"),
        ("Tiel-Coder-35B-A3B-UD-Q4_K_S", "/srv/ai/models/tiel-coder-35b-a3b/Tiel-Coder-35B-A3B-UD-Q4_K_S.gguf"),
    ]

    all_results = {}
    if os.path.exists("benchmarks/benchmark_moe_results.json"):
        try:
            with open("benchmarks/benchmark_moe_results.json", "r", encoding="utf-8") as f:
                all_results = json.load(f)
        except Exception:
            all_results = {}

    for name, path in models_to_test:
        if name in all_results and all_results[name].get("status") == "COMPLETED":
            print(f"[+] Skipping already completed candidate: {name}")
            continue
        res = run_benchmark_for_model(name, path, contexts=[65536, 32768], port=8089)
        all_results[name] = res
        with open("benchmarks/benchmark_moe_results.json", "w", encoding="utf-8") as f:
            json.dump(all_results, f, indent=2, ensure_ascii=False)

    print("\n[+] Benchmark complete! Saved to benchmarks/benchmark_moe_results.json", flush=True)


if __name__ == "__main__":
    main()
