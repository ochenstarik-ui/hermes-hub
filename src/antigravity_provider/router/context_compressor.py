"""Hermes Hub Context Compression Engine (Сжатие контекста).

Implements Task A56 requirements:
- P0-1: Configurable compressor role/profile (not hardcoded to port 8082), excluded from Hermes default routing chains.
- P0-2: Context-fill threshold (measured via /props and /tokenize, default 75%), fresh window preserved verbatim, no recursive double-compression.
- P0-3: Strict verbatim preservation of factual entities (file paths, ports, IPs, variable/function names, commit SHAs, version numbers, benchmark metrics) with 100% retention guarantee.
- P0-4: Transparent telemetry, history store for original uncompressed text, non-blocking graceful fallback if compressor is offline/unconfigured.
- P0-5: Shared memory persistence in /srv/projects/AI-Memory indexed by GGUF build metadata.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger("hermes.router.compression")

SHARED_MEMORY_VAULT = Path("/srv/projects/AI-Memory")
COMPRESSION_MEMORY_FILE = SHARED_MEMORY_VAULT / "01_PROJECTS" / "hermes-hub" / "compression_memory.json"

COMPRESSED_BLOCK_START = "<!-- HERMES_CONTEXT_COMPRESSION_START -->"
COMPRESSED_BLOCK_END = "<!-- HERMES_CONTEXT_COMPRESSION_END -->"


@dataclass
class FactualEntities:
    file_paths: List[str] = field(default_factory=list)
    ip_addresses: List[str] = field(default_factory=list)
    port_numbers: List[str] = field(default_factory=list)
    commit_shas: List[str] = field(default_factory=list)
    version_numbers: List[str] = field(default_factory=list)
    identifiers: List[str] = field(default_factory=list)
    metrics: List[str] = field(default_factory=list)

    @property
    def total_count(self) -> int:
        return (
            len(self.file_paths)
            + len(self.ip_addresses)
            + len(self.port_numbers)
            + len(self.commit_shas)
            + len(self.version_numbers)
            + len(self.identifiers)
            + len(self.metrics)
        )

    def all_unique_facts(self) -> Set[str]:
        items: Set[str] = set()
        items.update(self.file_paths)
        items.update(self.ip_addresses)
        items.update(self.port_numbers)
        items.update(self.commit_shas)
        items.update(self.version_numbers)
        items.update(self.identifiers)
        items.update(self.metrics)
        return items


@dataclass
class CompressionOutcome:
    status: str  # "SUCCESS", "SKIPPED", "UNCONFIGURED", "ERROR"
    status_message: str
    tokens_before: int = 0
    tokens_after: int = 0
    compression_ratio: float = 1.0
    saved_tokens: int = 0
    duration_sec: float = 0.0
    facts_total: int = 0
    facts_retained: int = 0
    retention_percent: float = 100.0
    retained_facts: List[str] = field(default_factory=list)
    missing_facts: List[str] = field(default_factory=list)
    model_name: str = ""
    gguf_name: str = ""
    endpoint: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    original_messages_snapshot: List[Dict[str, Any]] = field(default_factory=list)


def extract_factual_entities(text: str) -> FactualEntities:
    """Extract factual technical entities from text using strict regex patterns."""
    if not text:
        return FactualEntities()

    # 1. Absolute and relative file paths (e.g. /srv/projects/Agent projects/..., ./src/..., benchmarks/foo.md)
    path_pattern = re.compile(
        r"(?:/[a-zA-Z0-9._ -]+)+/[a-zA-Z0-9._-]+\.[a-zA-Z0-9]+|(?:/[a-zA-Z0-9._-]+)+[a-zA-Z0-9._-]+\.[a-zA-Z0-9]+|(?:[a-zA-Z0-9._-]+/)+[a-zA-Z0-9._-]+\.[a-zA-Z0-9]+"
    )
    raw_paths = path_pattern.findall(text)
    file_paths = sorted(set(p.strip() for p in raw_paths if p.strip()))

    # 2. IP addresses (e.g. 192.168.1.81, 127.0.0.1)
    ip_pattern = re.compile(r"\b(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\b")
    ip_addresses = sorted(set(ip_pattern.findall(text)))

    # 3. Ports (e.g. :8081, :8082, :8765, port 8081)
    port_pattern = re.compile(r"(?::|\bport\s+)([0-9]{4,5})\b", re.IGNORECASE)
    port_matches = port_pattern.findall(text)
    port_numbers = sorted(set(f":{p}" if not p.startswith(":") else p for p in port_matches))

    # 4. Commit SHAs and hex tokens (7-64 hex chars)
    sha_pattern = re.compile(r"\b[0-9a-fA-F]{7,64}\b")
    raw_shas = sha_pattern.findall(text)
    # Filter out pure decimal numbers or common words
    commit_shas = sorted(set(
        s for s in raw_shas
        if any(c in "abcdefABCDEF" for c in s) and 7 <= len(s) <= 64
    ))

    # 5. Version numbers (e.g. v0.1.2, 0.1.1, v0.1.2-b2)
    ver_pattern = re.compile(r"\bv?[0-9]+\.[0-9]+(?:\.[0-9]+)?(?:-[a-zA-Z0-9.]+)?\b")
    version_numbers = sorted(set(v for v in ver_pattern.findall(text) if v not in ip_addresses))

    # 6. Specific benchmark and hardware numbers (e.g. 107.4 tok/s, 30008 MiB, 229376 tokens, 224K, 64K)
    metric_pattern = re.compile(r"\b[0-9]+(?:\.[0-9]+)?\s*(?:tok/s|t/s|MiB|GiB|MB|GB|tokens|tok|K|k)\b")
    metrics = sorted(set(metric_pattern.findall(text)))

    # 7. Key Python / System Identifiers
    id_pattern = re.compile(r"\b(?:LocalSupervisor|DualCoderPipeline|ContextCompressor|Qwen3-Coder|Qwen3-4B|Phi-4|Granite|llama-server|systemd)\b")
    identifiers = sorted(set(id_pattern.findall(text)))

    return FactualEntities(
        file_paths=file_paths,
        ip_addresses=ip_addresses,
        port_numbers=port_numbers,
        commit_shas=commit_shas,
        version_numbers=version_numbers,
        identifiers=identifiers,
        metrics=metrics,
    )


def verify_facts_retention(summary: str, expected_facts: FactualEntities) -> Tuple[float, List[str], List[str]]:
    """Check how many expected facts are present verbatim in the summary."""
    all_facts = expected_facts.all_unique_facts()
    if not all_facts:
        return 100.0, [], []

    preserved: List[str] = []
    missing: List[str] = []

    for fact in all_facts:
        # Check direct substring match
        if fact in summary or (fact.startswith(":") and fact[1:] in summary):
            preserved.append(fact)
        else:
            missing.append(fact)

    retention_percent = (len(preserved) / len(all_facts)) * 100.0
    return retention_percent, preserved, missing


class ContextCompressor:
    """Orchestrates high-fidelity LLM context compression."""

    DEFAULT_THRESHOLD_PERCENT: float = 75.0
    DEFAULT_KEEP_RECENT: int = 3

    def __init__(
        self,
        memory_file: Optional[Path] = None,
    ):
        self.memory_file = memory_file or COMPRESSION_MEMORY_FILE
        self._history_snapshots: List[CompressionOutcome] = []

    def get_compression_history(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Return in-memory history of recent compressions."""
        return [asdict(o) for o in reversed(self._history_snapshots[-limit:])]

    def resolve_compressor_endpoint(
        self,
        profile_config: Optional[Any] = None,
        custom_base_url: Optional[str] = None,
    ) -> Tuple[str, str, str]:
        """Resolve base_url, model_name, and auth token for compressor."""
        if custom_base_url:
            return custom_base_url.rstrip("/"), "default", ""

        if profile_config is not None:
            base_url = (
                getattr(profile_config, "custom_base_url", None)
                or (profile_config.auth_config.get("base_url") if hasattr(profile_config, "auth_config") and isinstance(profile_config.auth_config, dict) else None)
                or os.environ.get("LOCAL_COMPRESSOR_BASE_URL")
                or "http://127.0.0.1:8082/v1"
            )
            model_name = profile_config.preferred_models[0] if getattr(profile_config, "preferred_models", None) else "default"
            token = profile_config.auth_config.get("api_key") or profile_config.auth_config.get("token") if hasattr(profile_config, "auth_config") and isinstance(profile_config.auth_config, dict) else ""
            return str(base_url).rstrip("/"), str(model_name), str(token or "")

        # Fallback to environment or standard compressor port
        env_url = os.environ.get("LOCAL_COMPRESSOR_BASE_URL", "http://127.0.0.1:8082/v1")
        return env_url.rstrip("/"), "default", ""

    def compress_messages_if_needed(
        self,
        messages: List[Dict[str, Any]],
        target_context_limit: int,
        current_token_count: int,
        compressor_profile: Optional[Any] = None,
        threshold_percent: float = DEFAULT_THRESHOLD_PERCENT,
        keep_recent_messages: int = DEFAULT_KEEP_RECENT,
        timeout_sec: float = 60.0,
    ) -> Tuple[List[Dict[str, Any]], CompressionOutcome]:
        """Compress conversation history if current_token_count exceeds threshold.
        
        Preserves system prompt and last `keep_recent_messages` untouched.
        Never nests compressed summaries recursively.
        Guarantees 100% factual retention.
        """
        # P0-1: If compressor profile is not configured
        if not compressor_profile and not os.environ.get("LOCAL_COMPRESSOR_BASE_URL"):
            outcome = CompressionOutcome(
                status="UNCONFIGURED",
                status_message="Н/Д: модель для сжатия не выбрана",
                tokens_before=current_token_count,
                tokens_after=current_token_count,
                compression_ratio=1.0,
            )
            return messages, outcome

        # P0-2: When to compress — check threshold
        threshold_tokens = int(target_context_limit * (threshold_percent / 100.0))
        if current_token_count < threshold_tokens:
            outcome = CompressionOutcome(
                status="SKIPPED",
                status_message=f"В пределах нормы ({current_token_count}/{threshold_tokens} токенов, {threshold_percent}%)",
                tokens_before=current_token_count,
                tokens_after=current_token_count,
                compression_ratio=1.0,
            )
            return messages, outcome

        # Not enough messages to compress (e.g. only system + 1 user prompt)
        system_msg: List[Dict[str, Any]] = []
        conversation: List[Dict[str, Any]] = list(messages)
        if conversation and conversation[0].get("role") == "system":
            system_msg = [conversation[0]]
            conversation = conversation[1:]

        if len(conversation) <= keep_recent_messages:
            outcome = CompressionOutcome(
                status="SKIPPED",
                status_message=f"Слишком мало сообщений для разделения ({len(conversation)} <= {keep_recent_messages})",
                tokens_before=current_token_count,
                tokens_after=current_token_count,
                compression_ratio=1.0,
            )
            return messages, outcome

        # Partition into old history to compress and fresh window to keep verbatim
        old_history = conversation[:-keep_recent_messages]
        fresh_window = conversation[-keep_recent_messages:]

        # P0-2 & P0-3: Extract existing summary block if present to prevent recursive double compression
        extracted_facts: List[FactualEntities] = []
        text_segments_to_compress: List[str] = []

        for msg in old_history:
            content = str(msg.get("content", ""))
            # Extract facts before stripping tags
            extracted_facts.append(extract_factual_entities(content))

            if COMPRESSED_BLOCK_START in content and COMPRESSED_BLOCK_END in content:
                # Extract the inner text of previously compressed context
                match = re.search(
                    rf"{re.escape(COMPRESSED_BLOCK_START)}\s*(.*?)\s*{re.escape(COMPRESSED_BLOCK_END)}",
                    content,
                    re.DOTALL,
                )
                if match:
                    prev_summary = match.group(1).strip()
                    text_segments_to_compress.append(f"[РАНЕЕ СОХРАНЁННЫЙ КОНТЕКСТ]:\n{prev_summary}")
                else:
                    text_segments_to_compress.append(content)
            else:
                role_label = msg.get("role", "user").upper()
                text_segments_to_compress.append(f"[{role_label}]:\n{content}")

        combined_history_text = "\n\n".join(text_segments_to_compress)

        # Merge all expected facts
        all_expected_facts = FactualEntities()
        for ef in extracted_facts:
            all_expected_facts.file_paths.extend(ef.file_paths)
            all_expected_facts.ip_addresses.extend(ef.ip_addresses)
            all_expected_facts.port_numbers.extend(ef.port_numbers)
            all_expected_facts.commit_shas.extend(ef.commit_shas)
            all_expected_facts.version_numbers.extend(ef.version_numbers)
            all_expected_facts.identifiers.extend(ef.identifiers)
            all_expected_facts.metrics.extend(ef.metrics)

        all_expected_facts.file_paths = sorted(set(all_expected_facts.file_paths))
        all_expected_facts.ip_addresses = sorted(set(all_expected_facts.ip_addresses))
        all_expected_facts.port_numbers = sorted(set(all_expected_facts.port_numbers))
        all_expected_facts.commit_shas = sorted(set(all_expected_facts.commit_shas))
        all_expected_facts.version_numbers = sorted(set(all_expected_facts.version_numbers))
        all_expected_facts.identifiers = sorted(set(all_expected_facts.identifiers))
        all_expected_facts.metrics = sorted(set(all_expected_facts.metrics))

        # P0-4: Execute compression against the resolved compressor model
        base_url, model_name, token = self.resolve_compressor_endpoint(compressor_profile)
        api_url = f"{base_url}/chat/completions" if not base_url.endswith("/chat/completions") else base_url

        system_instruction = (
            "You are a precise technical context compression engine.\n"
            "Summarize the technical history concisely into clear structured bullet points.\n"
            "CRITICAL REQUIREMENT: Strictly preserve ALL factual entities VERBATIM:\n"
            "- Exact file paths and directory names (e.g. /path/to/file.py)\n"
            "- IP addresses and hostnames (e.g. 192.168.1.81)\n"
            "- Port numbers (e.g. :8081, :8082, :8765)\n"
            "- Commit SHAs and cryptographic hashes (e.g. 26f7d2c, 8e75dc6)\n"
            "- Version numbers (e.g. v0.1.2)\n"
            "- Exact benchmark metrics and quantities (e.g. 107.4 tok/s, 30008 MiB, 224K)\n"
            "Never generalize, invent, or omit technical identifiers."
        )

        compression_request_payload = {
            "model": model_name or "default",
            "messages": [
                {"role": "system", "content": system_instruction},
                {
                    "role": "user",
                    "content": f"Please summarize the following execution history while retaining 100% of technical facts:\n\n{combined_history_text}",
                },
            ],
            "temperature": 0.1,
            "max_tokens": 1024,
        }

        t0 = time.time()
        try:
            req_headers = {"Content-Type": "application/json", "User-Agent": "Hermes-ContextCompressor/1.0"}
            if token:
                req_headers["Authorization"] = f"Bearer {token}"

            req_data = json.dumps(compression_request_payload).encode("utf-8")
            req = urllib.request.Request(api_url, data=req_data, headers=req_headers, method="POST")

            with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
                resp_data = json.loads(resp.read().decode("utf-8"))

            elapsed = time.time() - t0
            choices = resp_data.get("choices", [])
            if not choices:
                raise RuntimeError("Compressor returned empty choices")

            raw_summary = choices[0].get("message", {}).get("content", "").strip()
            if not raw_summary:
                raise RuntimeError("Compressor returned empty content")

            # Extract model GGUF build metadata if available
            gguf_model = str(resp_data.get("model", model_name or "compressor"))

            # P0-3: Verify facts retention
            retention_rate, preserved, missing = verify_facts_retention(raw_summary, all_expected_facts)

            # P0-3 Safeguard: If any critical technical entities were omitted by model, append explicit factual ledger
            if missing:
                logger.info("Context compressor missed %d facts. Appending verbatim factual safeguard ledger.", len(missing))
                facts_ledger = "\n### Ключевые сохранённые факты:\n" + "\n".join(f"- `{f}`" for f in missing)
                final_summary = f"{raw_summary}\n{facts_ledger}"
                # Re-verify -> guaranteed 100% retention
                retention_rate, preserved, missing = verify_facts_retention(final_summary, all_expected_facts)
            else:
                final_summary = raw_summary

            # Format the compressed block with clear delimiter
            formatted_compressed_content = (
                f"{COMPRESSED_BLOCK_START}\n"
                f"## Сжатая сводка предшествующего контекста\n"
                f"{final_summary}\n"
                f"{COMPRESSED_BLOCK_END}"
            )

            compressed_message = {
                "role": "user",
                "content": formatted_compressed_content,
            }

            new_messages = system_msg + [compressed_message] + fresh_window

            # Approximate/count new tokens
            est_before = current_token_count
            est_summary_tokens = max(1, int(len(formatted_compressed_content) / 3.5))
            est_fresh_tokens = sum(max(1, int(len(str(m.get("content", ""))) / 3.5)) for m in fresh_window)
            est_system_tokens = sum(max(1, int(len(str(m.get("content", ""))) / 3.5)) for m in system_msg)
            est_after = est_system_tokens + est_summary_tokens + est_fresh_tokens

            ratio = round(est_after / max(1, est_before), 2)
            saved = max(0, est_before - est_after)

            outcome = CompressionOutcome(
                status="SUCCESS",
                status_message=f"Контекст успешно сжат: {est_before} → {est_after} токенов ({ratio}x, экономия {saved} токенов) за {elapsed:.2f}с. Сохранено фактов: {len(preserved)}/{all_expected_facts.total_count} (100%).",
                tokens_before=est_before,
                tokens_after=est_after,
                compression_ratio=ratio,
                saved_tokens=saved,
                duration_sec=round(elapsed, 2),
                facts_total=all_expected_facts.total_count,
                facts_retained=len(preserved),
                retention_percent=retention_rate,
                retained_facts=preserved,
                missing_facts=missing,
                model_name=model_name,
                gguf_name=gguf_model,
                endpoint=base_url,
                original_messages_snapshot=messages,
            )

            # Store in in-memory snapshot history
            self._history_snapshots.append(outcome)

            # P0-5: Record to AI-Memory
            self._record_to_shared_memory(outcome)

            logger.info(
                "Context compression successful: %d -> %d tokens (%.2fx) in %.2fs. Model: %s",
                est_before,
                est_after,
                ratio,
                elapsed,
                gguf_model,
            )
            return new_messages, outcome

        except Exception as err:
            elapsed = time.time() - t0
            logger.warning("Context compression failed (%s). Continuing with uncompressed context: %s", base_url, err)

            # P0-4: Failure does NOT crash task. Proceed with original uncompressed messages
            outcome = CompressionOutcome(
                status="ERROR",
                status_message=f"Ошибка сжатия ({err}). Задача продолжается на исходном контексте.",
                tokens_before=current_token_count,
                tokens_after=current_token_count,
                compression_ratio=1.0,
                duration_sec=round(elapsed, 2),
                model_name=model_name,
                endpoint=base_url,
                original_messages_snapshot=messages,
            )
            self._history_snapshots.append(outcome)
            return messages, outcome

    def _record_to_shared_memory(self, outcome: CompressionOutcome) -> None:
        """Persist compression history in /srv/projects/AI-Memory indexed by GGUF model."""
        try:
            self.memory_file.parent.mkdir(parents=True, exist_ok=True)
            existing_data: Dict[str, Any] = {}
            if self.memory_file.exists():
                try:
                    existing_data = json.loads(self.memory_file.read_text(encoding="utf-8"))
                except Exception:
                    existing_data = {}

            models_map = existing_data.setdefault("compressor_models", {})
            model_key = Path(outcome.gguf_name).name if outcome.gguf_name else "default_compressor"

            rec = models_map.setdefault(model_key, {
                "gguf_name": outcome.gguf_name,
                "total_compressions": 0,
                "successful_compressions": 0,
                "avg_compression_ratio": 1.0,
                "avg_duration_sec": 0.0,
                "avg_fact_retention_percent": 100.0,
                "last_used": "",
                "history": [],
            })

            rec["total_compressions"] += 1
            if outcome.status == "SUCCESS":
                rec["successful_compressions"] += 1
                n = rec["successful_compressions"]
                rec["avg_compression_ratio"] = round(((rec["avg_compression_ratio"] * (n - 1)) + outcome.compression_ratio) / n, 3)
                rec["avg_duration_sec"] = round(((rec["avg_duration_sec"] * (n - 1)) + outcome.duration_sec) / n, 2)
                rec["avg_fact_retention_percent"] = round(((rec["avg_fact_retention_percent"] * (n - 1)) + outcome.retention_percent) / n, 1)

            rec["last_used"] = outcome.timestamp
            rec["history"].append({
                "timestamp": outcome.timestamp,
                "tokens_before": outcome.tokens_before,
                "tokens_after": outcome.tokens_after,
                "ratio": outcome.compression_ratio,
                "duration_sec": outcome.duration_sec,
                "retention_percent": outcome.retention_percent,
                "facts_total": outcome.facts_total,
                "status": outcome.status,
            })
            # Keep history limited to last 50 entries
            rec["history"] = rec["history"][-50:]

            self.memory_file.write_text(json.dumps(existing_data, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as exc:
            logger.debug("Failed to record compression memory to %s: %s", self.memory_file, exc)
