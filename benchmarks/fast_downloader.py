"""High-speed multi-connection HTTP range downloader."""
import concurrent.futures
import os
import sys
import time
import urllib.request

CHUNK_SIZE = 32 * 1024 * 1024  # 32MB chunks
NUM_WORKERS = 16


def get_file_info(url: str) -> tuple[str, int]:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        final_url = resp.geturl()
        length = int(resp.headers.get("Content-Length", 0))
        return final_url, length


def download_chunk(url: str, filepath: str, start_byte: int, end_byte: int, retries: int = 5) -> bool:
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Range": f"bytes={start_byte}-{end_byte}",
    }
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = resp.read()
                expected_len = end_byte - start_byte + 1
                if len(data) != expected_len:
                    raise IOError(f"Read {len(data)} bytes, expected {expected_len}")
                with open(filepath, "r+b") as f:
                    f.seek(start_byte)
                    f.write(data)
                return True
        except Exception as e:
            time.sleep(1 + attempt)
    return False


def parallel_download(url: str, output_path: str):
    print(f"[*] Resolving: {url}", flush=True)
    final_url, total_size = get_file_info(url)
    print(f"[*] Target file size: {total_size / (1024**3):.2f} GiB ({total_size} bytes)", flush=True)

    if not os.path.exists(output_path):
        with open(output_path, "wb") as f:
            f.truncate(total_size)
    else:
        current_size = os.path.getsize(output_path)
        if current_size != total_size:
            with open(output_path, "wb") as f:
                f.truncate(total_size)

    # Build chunk ranges
    chunks = []
    for start in range(0, total_size, CHUNK_SIZE):
        end = min(start + CHUNK_SIZE - 1, total_size - 1)
        chunks.append((start, end))

    print(f"[*] Total chunks to download: {len(chunks)} ({CHUNK_SIZE / (1024**2):.0f}MB each) with {NUM_WORKERS} workers", flush=True)
    t0 = time.time()
    completed = 0

    with concurrent.futures.ThreadPoolExecutor(max_workers=NUM_WORKERS) as executor:
        futures = {
            executor.submit(download_chunk, final_url, output_path, s, e): (s, e)
            for s, e in chunks
        }
        for future in concurrent.futures.as_completed(futures):
            ok = future.result()
            if not ok:
                print(f"[-] Chunk failed: {futures[future]}", flush=True)
                sys.exit(1)
            completed += 1
            elapsed = time.time() - t0
            downloaded_mb = completed * (CHUNK_SIZE / (1024**2))
            speed = downloaded_mb / elapsed if elapsed > 0 else 0
            percent = (completed / len(chunks)) * 100
            print(f"\r    [{percent:5.1f}%] {downloaded_mb:8.1f} MB downloaded | Avg Speed: {speed:6.1f} MB/s | Elapsed: {elapsed:5.1f}s", end="", flush=True)

    print(f"\n[+] Download completed successfully in {time.time() - t0:.1f}s!", flush=True)


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python fast_downloader.py <URL> <OUTPUT_PATH>")
        sys.exit(1)
    parallel_download(sys.argv[1], sys.argv[2])
