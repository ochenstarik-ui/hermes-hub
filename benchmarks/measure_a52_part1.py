"""Automated benchmark and verification suite for Task A52 (Part 1).

Measures:
1. P0-1: Live qwen-coder service with Qwen3-Coder-30B-A3B @ 64K (-c 65536) on port 8081
2. P0-2: Compressor quality & performance: LFM2.5-2.6B vs Qwen3-4B-2507 on GPU and CPU (-ngl 0) on port 8082
3. P0-3: Process VRAM @ 64K for Phi-4-14B, Qwen2.5-Coder-14B, Qwen3-4B-2507, Granite-4.2-8B
4. Multi-model coexistence tests (pairs in 32GB VRAM)
5. Memory bandwidth contention test: single generation vs concurrent dual generation
"""
import concurrent.futures
import hashlib
import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

LLAMA_SERVER_REAL = "/home/ochenstarik/llama.cpp/build/bin/llama-server.real"
HOLD_FILE = "/home/ochenstarik/.hermes/benchmark_hold"


def get_proc_gpu_vram(pid: Optional[int] = None) -> int:
    try:
        res = subprocess.run(
            ["nvidia-smi", "--query-compute-apps=pid,used_memory", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        total_or_proc = 0
        for line in res.stdout.strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 2:
                p_id = int(parts[0])
                vram = int(parts[1])
                if pid is not None and p_id == pid:
                    return vram
                total_or_proc += vram
        return total_or_proc
    except Exception as e:
        print(f"Error reading GPU VRAM: {e}")
    return 0


def cleanup_port(port: int):
    subprocess.run(["pkill", "-9", "-f", f"port {port}"], capture_output=True)
    time.sleep(1.5)


def ping_health(port: int, timeout: int = 120) -> bool:
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
        time.sleep(1.5)
    return False


def request_chat(port: int, model_path: str, messages: List[Dict[str, str]], max_tokens: int = 128, temperature: float = 0.2) -> Dict[str, Any]:
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
    with urllib.request.urlopen(req, timeout=120) as resp:
        elapsed = time.monotonic() - t0
        raw = json.loads(resp.read().decode())
        raw["client_wall_time_sec"] = round(elapsed, 3)
        return raw


# -------------------------------------------------------------
# 1. P0-1: Live Coder Benchmark on Port 8081
# -------------------------------------------------------------
def measure_live_coder(port: int = 8081) -> Dict[str, Any]:
    print(f"\n===================================================================", flush=True)
    print(f" [P0-1] MEASURING LIVE CODER ON PORT {port}", flush=True)
    print(f"===================================================================", flush=True)

    # 1. Check /props
    props_url = f"http://127.0.0.1:{port}/props"
    with urllib.request.urlopen(urllib.request.Request(props_url), timeout=5) as r:
        props = json.loads(r.read().decode())
    
    n_ctx = props.get("default_generation_settings", {}).get("n_ctx", 0)
    total_slots = props.get("total_slots", 0)
    print(f"[+] Server Props: n_ctx = {n_ctx}, total_slots = {total_slots}")

    # 2. Check /tokenize
    tok_url = f"http://127.0.0.1:{port}/tokenize"
    sample_text = "def add(a, b): return a + b"
    tok_body = json.dumps({"content": sample_text}).encode("utf-8")
    req = urllib.request.Request(tok_url, data=tok_body, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=5) as r:
        tok_data = json.loads(r.read().decode())
    tokens_count = len(tok_data.get("tokens", []))
    print(f"[+] Server Tokenize '{sample_text}': {tokens_count} tokens")

    # 3. Measure speed and VRAM
    res = request_chat(port, "qwen3-coder", [{"role": "user", "content": "Write a python implementation of a thread-safe LeaseManager."}], max_tokens=128, temperature=0.1)
    timings = res.get("timings", {})
    gen_tps = round(timings.get("predicted_per_second", 0.0), 2)
    prompt_tps = round(timings.get("prompt_per_second", 0.0), 2)
    
    # Process VRAM
    vram = get_proc_gpu_vram()
    print(f"[+] Live Coder Performance: Gen = {gen_tps} tok/s | Prompt = {prompt_tps} tok/s | Total VRAM = {vram} MiB")
    return {
        "port": port,
        "n_ctx": n_ctx,
        "total_slots": total_slots,
        "tokenize_sample_tokens": tokens_count,
        "total_vram_mib": vram,
        "generation_speed_tps": gen_tps,
        "prompt_speed_tps": prompt_tps,
        "timings": timings,
    }


# -------------------------------------------------------------
# 2. P0-2: Compressor Evaluation
# -------------------------------------------------------------
COMPRESSION_TEST_PROMPTS = [
    {
        "id": "C01_code_repo_summary",
        "system": "You are a concise code compressor. Extract key architecture facts, ports, and invariants without dropping numbers.",
        "text": """
Project: Hermes Hub Router
Architecture: FastAPI web server listening on port 8765. Multi-provider routing between Ollama (port 11434), Local llama.cpp (coder on port 8081, compressor on port 8082), OpenRouter, Anthropic Claude, and xAI Grok.
Invariants:
1. All local models are limited to max concurrency 1 via LeaseManager.
2. Credentials stored in ~/.hermes/ are never deleted by reset.
3. When local coder exceeds 64K tokens, LocalSupervisor splits the payload.
4. ErrorCategory.TRANSIENT triggers exponential backoff (retry_delay_seconds=2).
Task: Provide a dense 3-sentence summary retaining all ports, error categories, and invariants.
"""
    },
    {
        "id": "C02_security_audit_log",
        "system": "You are a context compressor. Extract key security audit facts, IPs, hashes, and actions.",
        "text": """
Security Event Log:
2026-08-31 10:15:02 UTC - ALERT: Unauthorized access attempt from IP 192.168.1.105 on /v1/chat/completions.
2026-08-31 10:15:05 UTC - BLOCKED: CIDR whitelist violation for subnet 192.168.1.0/24. Token hash sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855.
2026-08-31 10:15:10 UTC - ACTION: IP 192.168.1.105 blacklisted for 3600 seconds. Router fallback engaged to secondary provider.
Task: Summarize security incident keeping IP, hash, and blacklist duration exact.
"""
    }
]


def evaluate_compressor(name: str, path: str, ngl: int, port: int = 8085) -> Dict[str, Any]:
    cleanup_port(port)
    device = "GPU" if ngl > 0 else "CPU"
    print(f"\n[*] Evaluating Compressor: {name} on {device} (ngl={ngl})...", flush=True)

    cmd = [
        LLAMA_SERVER_REAL,
        "-m", path,
        "-ngl", str(ngl),
        "-c", "32768",
        "--parallel", "1",
        "--flash-attn", "on" if ngl > 0 else "off",
        "--reasoning", "off",
        "--temp", "0.2",
        "--host", "127.0.0.1",
        "--port", str(port),
    ]
    if ngl == 0:
        cmd.extend(["-t", "32"])  # 32 CPU threads

    t0 = time.time()
    p = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        ok = ping_health(port, timeout=90)
        cold_sec = round(time.time() - t0, 2)
        if not ok:
            print(f"[-] {name} on {device}: Failed to start")
            return {"name": name, "device": device, "status": "FAILED"}

        vram = get_proc_gpu_vram(p.pid)
        print(f"[+] {name} ({device}) Ready in {cold_sec}s | Process VRAM: {vram} MiB")

        results = []
        gen_speeds = []
        prompt_speeds = []

        for item in COMPRESSION_TEST_PROMPTS:
            msgs = [
                {"role": "system", "content": item["system"]},
                {"role": "user", "content": item["text"]},
            ]
            res = request_chat(port, path, msgs, max_tokens=150, temperature=0.1)
            content = res["choices"][0]["message"]["content"]
            timings = res.get("timings", {})
            g_tps = timings.get("predicted_per_second", 0.0)
            p_tps = timings.get("prompt_per_second", 0.0)
            gen_speeds.append(g_tps)
            prompt_speeds.append(p_tps)

            results.append({
                "prompt_id": item["id"],
                "content_preview": content[:140].replace("\n", " "),
                "gen_tps": round(g_tps, 2),
                "prompt_tps": round(p_tps, 2),
            })
            print(f"    - {item['id']}: Gen {g_tps:.2f} t/s | Prompt {p_tps:.2f} t/s")

        avg_gen = round(sum(gen_speeds) / len(gen_speeds), 2) if gen_speeds else 0.0
        avg_prompt = round(sum(prompt_speeds) / len(prompt_speeds), 2) if prompt_speeds else 0.0

        return {
            "name": name,
            "device": device,
            "ngl": ngl,
            "cold_start_sec": cold_sec,
            "process_vram_mib": vram,
            "avg_generation_tps": avg_gen,
            "avg_prompt_tps": avg_prompt,
            "evaluations": results,
            "status": "OK",
        }
    finally:
        p.terminate()
        try:
            p.wait(timeout=5)
        except Exception:
            p.kill()
        cleanup_port(port)


# -------------------------------------------------------------
# 3. P0-3: Measure 64K VRAM for Candidates & Bandwidth Test
# -------------------------------------------------------------
CANDIDATES_64K = [
    ("Phi-4-14B", "/srv/ai/models/phi-4-14b/phi-4-Q4_K_M.gguf"),
    ("Qwen2.5-Coder-14B", "/srv/ai/models/qwen2.5-coder-14b/qwen2.5-coder-14b-instruct-q4_k_m.gguf"),
    ("Granite-4.2-8B", "/srv/ai/models/granite-4.2-8b/granite-4.2-8b-Q4_K_M.gguf"),
    ("Qwen3-4B-2507", "/srv/ai/models/qwen3-4b-compressor/Qwen_Qwen3-4B-Instruct-2507-Q4_K_M.gguf"),
    ("Qwen3-Coder-30B-A3B", "/srv/ai/models/qwen3-coder-30b-a3b/Qwen3-Coder-30B-A3B-Instruct-Q4_K_M.gguf"),
]


def measure_model_vram_at_64k(name: str, path: str, port: int = 8085) -> Dict[str, Any]:
    cleanup_port(port)
    print(f"\n[*] Measuring {name} at 64K (-c 65536)...", flush=True)

    cmd = [
        LLAMA_SERVER_REAL,
        "-m", path,
        "-ngl", "99",
        "-c", "65536",
        "--parallel", "1",
        "--flash-attn", "on",
        "--cache-type-k", "q8_0",
        "--cache-type-v", "q8_0",
        "--reasoning", "off",
        "--temp", "0.2",
        "--host", "127.0.0.1",
        "--port", str(port),
    ]
    t0 = time.time()
    p = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        ok = ping_health(port, timeout=90)
        cold_sec = round(time.time() - t0, 2)
        if not ok:
            print(f"[-] {name} failed to start at 64K")
            return {"name": name, "status": "FAILED_OR_OOM", "cold_sec": cold_sec}

        vram = get_proc_gpu_vram(p.pid)
        res = request_chat(port, path, [{"role": "user", "content": "Write quick python binary search function."}], max_tokens=64, temperature=0.1)
        timings = res.get("timings", {})
        gen_tps = round(timings.get("predicted_per_second", 0.0), 2)
        prompt_tps = round(timings.get("prompt_per_second", 0.0), 2)
        print(f"[+] {name} (64K): Process VRAM = {vram} MiB | Gen = {gen_tps} tok/s | Prompt = {prompt_tps} tok/s")
        return {
            "name": name,
            "status": "OK",
            "cold_start_sec": cold_sec,
            "process_vram_mib": vram,
            "generation_tps": gen_tps,
            "prompt_tps": prompt_tps,
        }
    finally:
        p.terminate()
        try:
            p.wait(timeout=5)
        except Exception:
            p.kill()
        cleanup_port(port)


def test_coexistence_and_bandwidth(
    name_a: str, path_a: str, port_a: int, ctx_a: int,
    name_b: str, path_b: str, port_b: int, ctx_b: int,
) -> Dict[str, Any]:
    cleanup_port(port_a)
    cleanup_port(port_b)
    print(f"\n===================================================================", flush=True)
    print(f" TESTING COEXISTENCE & BANDWIDTH: {name_a} (:{port_a}) + {name_b} (:{port_b})", flush=True)
    print(f"===================================================================", flush=True)

    cmd_a = [
        LLAMA_SERVER_REAL, "-m", path_a, "-ngl", "99", "-c", str(ctx_a),
        "--parallel", "1", "--flash-attn", "on", "--cache-type-k", "q8_0", "--cache-type-v", "q8_0",
        "--reasoning", "off", "--temp", "0.2", "--host", "127.0.0.1", "--port", str(port_a),
    ]
    cmd_b = [
        LLAMA_SERVER_REAL, "-m", path_b, "-ngl", "99", "-c", str(ctx_b),
        "--parallel", "1", "--flash-attn", "on", "--cache-type-k", "q8_0", "--cache-type-v", "q8_0",
        "--reasoning", "off", "--temp", "0.2", "--host", "127.0.0.1", "--port", str(port_b),
    ]

    p_a = subprocess.Popen(cmd_a, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    p_b = subprocess.Popen(cmd_b, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    try:
        ok_a = ping_health(port_a, timeout=90)
        ok_b = ping_health(port_b, timeout=90)

        if not (ok_a and ok_b):
            print(f"[-] Coexistence failed: {name_a} ok={ok_a}, {name_b} ok={ok_b}")
            return {"status": "COEXISTENCE_FAILED", "name_a": name_a, "name_b": name_b}

        vram_a = get_proc_gpu_vram(p_a.pid)
        vram_b = get_proc_gpu_vram(p_b.pid)
        total_vram = get_proc_gpu_vram()
        print(f"[+] BOTH MODELS LOADED SUCCESSFULLY IN VRAM!")
        print(f"    - {name_a} VRAM: {vram_a} MiB")
        print(f"    - {name_b} VRAM: {vram_b} MiB")
        print(f"    - Total Combined GPU VRAM: {total_vram} MiB / 32768 MiB (Free: {32768 - total_vram} MiB)")

        # 1. Solo speed A
        res_a_solo = request_chat(port_a, path_a, [{"role": "user", "content": "Write a python merge sort implementation with tests."}], max_tokens=150, temperature=0.1)
        solo_a_tps = res_a_solo.get("timings", {}).get("predicted_per_second", 0.0)
        print(f"[+] {name_a} Solo Generation: {solo_a_tps:.2f} tok/s")

        # 2. Solo speed B
        res_b_solo = request_chat(port_b, path_b, [{"role": "user", "content": "Write a python quick sort implementation with tests."}], max_tokens=150, temperature=0.1)
        solo_b_tps = res_b_solo.get("timings", {}).get("predicted_per_second", 0.0)
        print(f"[+] {name_b} Solo Generation: {solo_b_tps:.2f} tok/s")

        # 3. Concurrent generation
        print("[*] Launching simultaneous concurrent generation on both models...")
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            f_a = executor.submit(request_chat, port_a, path_a, [{"role": "user", "content": "Write a python merge sort implementation with tests."}], 150, 0.1)
            f_b = executor.submit(request_chat, port_b, path_b, [{"role": "user", "content": "Write a python quick sort implementation with tests."}], 150, 0.1)
            res_a_conc = f_a.result()
            res_b_conc = f_b.result()

        conc_a_tps = res_a_conc.get("timings", {}).get("predicted_per_second", 0.0)
        conc_b_tps = res_b_conc.get("timings", {}).get("predicted_per_second", 0.0)
        total_conc_tps = conc_a_tps + conc_b_tps

        print(f"[+] Concurrent {name_a}: {conc_a_tps:.2f} tok/s (Solo was {solo_a_tps:.2f} tok/s)")
        print(f"[+] Concurrent {name_b}: {conc_b_tps:.2f} tok/s (Solo was {solo_b_tps:.2f} tok/s)")
        print(f"[+] Combined Concurrent Throughput: {total_conc_tps:.2f} tok/s")
        print(f"[+] Memory Bandwidth Sharing Ratio: {total_conc_tps / max(solo_a_tps, 1.0):.2f}x")

        return {
            "status": "SUCCESS",
            "name_a": name_a,
            "name_b": name_b,
            "vram_a_mib": vram_a,
            "vram_b_mib": vram_b,
            "total_vram_mib": total_vram,
            "solo_a_tps": round(solo_a_tps, 2),
            "solo_b_tps": round(solo_b_tps, 2),
            "conc_a_tps": round(conc_a_tps, 2),
            "conc_b_tps": round(conc_b_tps, 2),
            "total_conc_tps": round(total_conc_tps, 2),
            "ratio_vs_solo_a": round(total_conc_tps / max(solo_a_tps, 1.0), 2),
        }
    finally:
        p_a.terminate()
        p_b.terminate()
        try:
            p_a.wait(timeout=5)
            p_b.wait(timeout=5)
        except Exception:
            p_a.kill()
            p_b.kill()
        cleanup_port(port_a)
        cleanup_port(port_b)


def main():
    report_data = {}

    # 1. P0-1: Measure live coder
    report_data["live_coder_8081"] = measure_live_coder(8081)

    # 2. Pause background services to acquire full 32GB VRAM for benchmarks
    print("\n[*] Pausing background services for isolated benchmarks...", flush=True)
    with open(HOLD_FILE, "w") as f:
        f.write("hold\n")
    subprocess.run(["pkill", "-9", "-f", "llama-server.real"], capture_output=True)
    time.sleep(3)

    try:
        # 3. P0-2: Compressors on GPU & CPU
        compressors = [
            ("Qwen3-4B-2507", "/srv/ai/models/qwen3-4b-compressor/Qwen_Qwen3-4B-Instruct-2507-Q4_K_M.gguf"),
            ("LFM2.5-2.6B", "/srv/ai/models/lfm2.5-2.6b/LFM2.5-2.6B-Q4_K_M.gguf"),
        ]
        comp_results = {}
        for name, path in compressors:
            comp_results[f"{name}_GPU"] = evaluate_compressor(name, path, ngl=99, port=8085)
            comp_results[f"{name}_CPU"] = evaluate_compressor(name, path, ngl=0, port=8085)
        report_data["compressor_evaluation"] = comp_results

        # 4. P0-3: 64K VRAM for candidate models
        vram_64k_results = {}
        for name, path in CANDIDATES_64K:
            vram_64k_results[name] = measure_model_vram_at_64k(name, path, port=8085)
        report_data["candidates_64k_vram"] = vram_64k_results

        # 5. Test multi-model pairs in VRAM & Bandwidth contention
        # Pair 1: Qwen3-Coder-30B-A3B (64K) + Qwen3-4B-2507 (32K compressor)
        pair1 = test_coexistence_and_bandwidth(
            "Qwen3-Coder-30B-A3B", "/srv/ai/models/qwen3-coder-30b-a3b/Qwen3-Coder-30B-A3B-Instruct-Q4_K_M.gguf", 8085, 65536,
            "Qwen3-4B-2507", "/srv/ai/models/qwen3-4b-compressor/Qwen_Qwen3-4B-Instruct-2507-Q4_K_M.gguf", 8086, 32768,
        )
        report_data["pair_coder_and_compressor"] = pair1

        # Pair 2: Phi-4-14B (64K) + Qwen2.5-Coder-14B (64K)
        pair2 = test_coexistence_and_bandwidth(
            "Phi-4-14B", "/srv/ai/models/phi-4-14b/phi-4-Q4_K_M.gguf", 8085, 65536,
            "Qwen2.5-Coder-14B", "/srv/ai/models/qwen2.5-coder-14b/qwen2.5-coder-14b-instruct-q4_k_m.gguf", 8086, 65536,
        )
        report_data["pair_phi4_and_qwen25_14b"] = pair2

        # Pair 3: Qwen3-Coder-30B-A3B (32K) + Granite-4.2-8B (32K)
        pair3 = test_coexistence_and_bandwidth(
            "Qwen3-Coder-30B-A3B", "/srv/ai/models/qwen3-coder-30b-a3b/Qwen3-Coder-30B-A3B-Instruct-Q4_K_M.gguf", 8085, 32768,
            "Granite-4.2-8B", "/srv/ai/models/granite-4.2-8b/granite-4.2-8b-Q4_K_M.gguf", 8086, 32768,
        )
        report_data["pair_qwen3moe_and_granite"] = pair3

    finally:
        # 6. Unpause background services
        print("\n[*] Unpausing background services...", flush=True)
        if os.path.exists(HOLD_FILE):
            os.remove(HOLD_FILE)
        subprocess.run(["pkill", "-9", "-f", "sleep 3600"], capture_output=True)
        subprocess.run(["pkill", "-9", "-f", "llama-server"], capture_output=True)

    with open("benchmarks/a52_part1_measurements.json", "w", encoding="utf-8") as f:
        json.dump(report_data, f, indent=2, ensure_ascii=False)
    print("\n[+] Benchmark suite completed! Results saved to benchmarks/a52_part1_measurements.json")


if __name__ == "__main__":
    main()
