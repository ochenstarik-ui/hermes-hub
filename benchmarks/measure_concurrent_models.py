"""Script to perform live, honest VRAM measurements of solo and concurrent model deployments."""
import json
import os
import subprocess
import time
import urllib.request
from typing import Dict, List, Tuple


def get_gpu_compute_apps() -> List[Dict[str, str]]:
    """Query nvidia-smi for all active compute processes on GPU."""
    try:
        res = subprocess.run(
            ["nvidia-smi", "--query-compute-apps=pid,process_name,used_memory", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        apps = []
        for line in res.stdout.strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 3:
                apps.append({
                    "pid": int(parts[0]),
                    "process_name": parts[1],
                    "used_memory_mib": int(parts[2]),
                })
        return apps
    except Exception as e:
        print(f"Error querying nvidia-smi: {e}")
        return []


def get_total_vram_used() -> int:
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


def ping_health(port: int, timeout: int = 40) -> bool:
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            req = urllib.request.Request(f"http://127.0.0.1:{port}/health")
            with urllib.request.urlopen(req, timeout=2) as resp:
                data = json.loads(resp.read().decode())
                if data.get("status") == "ok":
                    return True
        except Exception:
            pass
        time.sleep(1)
    return False


def test_completion(port: int, model_path: str) -> Tuple[bool, float, str]:
    req_body = {
        "model": model_path,
        "messages": [{"role": "user", "content": "Respond exact word 'PONG'"}],
        "max_tokens": 10,
        "temperature": 0.1,
    }
    t0 = time.monotonic()
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/chat/completions",
            data=json.dumps(req_body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            elapsed = time.monotonic() - t0
            raw = json.loads(resp.read().decode())
            content = raw["choices"][0]["message"]["content"]
            return True, elapsed, content.strip()
    except Exception as e:
        return False, time.monotonic() - t0, str(e)


def run_solo_measurement(name: str, model_path: str, ctx: int, port: int = 8089) -> Dict[str, any]:
    print(f"\n[*] Measuring Solo: {name} (ctx={ctx})...", flush=True)
    cmd = [
        "/home/ochenstarik/llama.cpp/build/bin/llama-server",
        "-m", model_path,
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
    p = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        ok = ping_health(port, timeout=45)
        if not ok:
            print(f"[-] Failed to start {name} on port {port}", flush=True)
            return {"name": name, "model_path": model_path, "ctx": ctx, "status": "START_FAILED"}
        
        # Warmup
        comp_ok, comp_time, comp_resp = test_completion(port, model_path)
        
        apps = get_gpu_compute_apps()
        proc_vram = next((a["used_memory_mib"] for a in apps if a["pid"] == p.pid), 0)
        total_vram = get_total_vram_used()
        
        print(f"[+] {name} (ctx={ctx}): Process VRAM = {proc_vram} MiB | Total GPU = {total_vram} MiB | Ping = {comp_time:.2f}s ('{comp_resp}')", flush=True)
        return {
            "name": name,
            "model_path": model_path,
            "ctx": ctx,
            "process_vram_mib": proc_vram,
            "total_gpu_mib": total_vram,
            "status": "OK",
        }
    finally:
        p.terminate()
        try:
            p.wait(timeout=5)
        except Exception:
            p.kill()
        time.sleep(1)


def main():
    print("===================================================================", flush=True)
    print(" LIVE VRAM & CONCURRENCY BENCHMARK ON TESLA V100 32GB", flush=True)
    print("===================================================================", flush=True)
    
    models = [
        ("Qwen3.8-27B", "/srv/ai/models/qwen3.8-27b/Qwen3.8-27B-Q4_K_M.gguf", 32768),
        ("Qwen3.8-27B (192k ctx)", "/srv/ai/models/qwen3.8-27b/Qwen3.8-27B-Q4_K_M.gguf", 196608),
        ("Qwen2.5-Coder-32B", "/srv/ai/models/qwen2.5-coder-32b/Qwen2.5-Coder-32B-Instruct-Q4_K_M.gguf", 32768),
        ("Qwen2.5-Coder-14B", "/srv/ai/models/qwen2.5-coder-14b/qwen2.5-coder-14b-instruct-q4_k_m.gguf", 32768),
        ("Qwen2.5-Coder-14B (64k ctx)", "/srv/ai/models/qwen2.5-coder-14b/qwen2.5-coder-14b-instruct-q4_k_m.gguf", 65536),
        ("Phi-4-14B", "/srv/ai/models/phi-4-14b/phi-4-Q4_K_M.gguf", 16384),
        ("DeepSeek-Coder-V2-Lite", "/srv/ai/models/deepseek-coder-v2-lite/DeepSeek-Coder-V2-Lite-Instruct-Q4_K_M.gguf", 32768),
        ("DeepSeek-Coder-V2-Lite (64k ctx)", "/srv/ai/models/deepseek-coder-v2-lite/DeepSeek-Coder-V2-Lite-Instruct-Q4_K_M.gguf", 65536),
        ("Granite-4.2-8B", "/srv/ai/models/granite-4.2-8b/granite-4.2-8b-Q4_K_M.gguf", 32768),
        ("Granite-4.2-8B (64k ctx)", "/srv/ai/models/granite-4.2-8b/granite-4.2-8b-Q4_K_M.gguf", 65536),
        ("Granite-3.2-8B-Preview", "/srv/ai/models/granite-3.2-8b/granite-3.2-8b-instruct-preview.Q4_K_M.gguf", 32768),
        ("Qwen3-4B-Compressor", "/srv/ai/models/qwen3-4b-compressor/Qwen_Qwen3-4B-Instruct-2507-Q4_K_M.gguf", 32768),
        ("LFM2.5-2.6B", "/srv/ai/models/lfm2.5-2.6b/LFM2.5-2.6B-Q4_K_M.gguf", 16384),
    ]

    solo_results = []
    for name, path, ctx in models:
        res = run_solo_measurement(name, path, ctx, port=8089)
        solo_results.append(res)
    
    with open("benchmarks/solo_vram_results.json", "w", encoding="utf-8") as f:
        json.dump(solo_results, f, indent=2)

    # -------------------------------------------------------------
    # CONCURRENCY TEST: 3 Models simultaneously
    # (Qwen2.5-Coder-14B + Granite-4.2-8B + Qwen3-4B-Compressor)
    # -------------------------------------------------------------
    print("\n=======================================================", flush=True)
    print(" [*] TEST SCENARIO A: 3 Models Simultaneously on GPU", flush=True)
    print("     1. Qwen2.5-Coder-14B (32k)")
    print("     2. Granite-4.2-8B (32k)")
    print("     3. Qwen3-4B-Compressor (32k)")
    print("=======================================================", flush=True)

    procs = []
    configs_3 = [
        ("qwen2.5-coder-14b", "/srv/ai/models/qwen2.5-coder-14b/qwen2.5-coder-14b-instruct-q4_k_m.gguf", 32768, 8083),
        ("granite-4.2-8b", "/srv/ai/models/granite-4.2-8b/granite-4.2-8b-Q4_K_M.gguf", 32768, 8084),
        ("qwen3-4b-compressor", "/srv/ai/models/qwen3-4b-compressor/Qwen_Qwen3-4B-Instruct-2507-Q4_K_M.gguf", 32768, 8085),
    ]

    try:
        for name, path, ctx, port in configs_3:
            cmd = [
                "/home/ochenstarik/llama.cpp/build/bin/llama-server",
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
                "--port", str(port),
            ]
            p = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            procs.append((name, p, port, path))
            ok = ping_health(port, timeout=45)
            print(f"    - {name} on port {port}: {'STARTED' if ok else 'FAILED'}", flush=True)

        time.sleep(2)
        apps = get_gpu_compute_apps()
        total_vram = get_total_vram_used()
        print(f"\n[+] 3-MODEL CONCURRENT RESULT (Total GPU VRAM = {total_vram} MiB / 32768 MiB):", flush=True)
        for name, p, port, path in procs:
            proc_mem = next((a["used_memory_mib"] for a in apps if a["pid"] == p.pid), 0)
            comp_ok, comp_time, comp_resp = test_completion(port, path)
            print(f"    - {name:22s} (PID {p.pid:7d}): {proc_mem:5d} MiB | Req = {'OK' if comp_ok else 'ERR'} ({comp_time:.2f}s)", flush=True)
    finally:
        for name, p, port, path in procs:
            p.terminate()
            try:
                p.wait(timeout=5)
            except Exception:
                p.kill()
        time.sleep(2)

    # -------------------------------------------------------------
    # CONCURRENCY TEST: 4 Models simultaneously
    # (+ DeepSeek-Coder-V2-Lite)
    # -------------------------------------------------------------
    print("\n=======================================================", flush=True)
    print(" [*] TEST SCENARIO B: 4 Models Simultaneously on GPU (ctx=32k)", flush=True)
    print("     1. Qwen2.5-Coder-14B (32k)")
    print("     2. DeepSeek-Coder-V2-Lite (32k)")
    print("     3. Granite-4.2-8B (32k)")
    print("     4. Qwen3-4B-Compressor (32k)")
    print("=======================================================", flush=True)

    procs_4 = []
    configs_4 = [
        ("qwen2.5-coder-14b", "/srv/ai/models/qwen2.5-coder-14b/qwen2.5-coder-14b-instruct-q4_k_m.gguf", 32768, 8083),
        ("deepseek-coder-v2-lite", "/srv/ai/models/deepseek-coder-v2-lite/DeepSeek-Coder-V2-Lite-Instruct-Q4_K_M.gguf", 32768, 8086),
        ("granite-4.2-8b", "/srv/ai/models/granite-4.2-8b/granite-4.2-8b-Q4_K_M.gguf", 32768, 8084),
        ("qwen3-4b-compressor", "/srv/ai/models/qwen3-4b-compressor/Qwen_Qwen3-4B-Instruct-2507-Q4_K_M.gguf", 32768, 8085),
    ]

    try:
        for name, path, ctx, port in configs_4:
            cmd = [
                "/home/ochenstarik/llama.cpp/build/bin/llama-server",
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
                "--port", str(port),
            ]
            p = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            procs_4.append((name, p, port, path))
            ok = ping_health(port, timeout=45)
            print(f"    - {name} on port {port}: {'STARTED' if ok else 'FAILED'}", flush=True)

        time.sleep(2)
        apps = get_gpu_compute_apps()
        total_vram = get_total_vram_used()
        print(f"\n[+] 4-MODEL CONCURRENT RESULT (Total GPU VRAM = {total_vram} MiB / 32768 MiB):", flush=True)
        for name, p, port, path in procs_4:
            proc_mem = next((a["used_memory_mib"] for a in apps if a["pid"] == p.pid), 0)
            comp_ok, comp_time, comp_resp = test_completion(port, path)
            print(f"    - {name:24s} (PID {p.pid:7d}): {proc_mem:5d} MiB | Req = {'OK' if comp_ok else 'ERR'} ({comp_time:.2f}s)", flush=True)
    finally:
        for name, p, port, path in procs_4:
            p.terminate()
            try:
                p.wait(timeout=5)
            except Exception:
                p.kill()
        time.sleep(2)


if __name__ == "__main__":
    main()
