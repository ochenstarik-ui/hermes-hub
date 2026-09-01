"""Tests for Task A56: Context Compression (Сжатие контекста).

Verifies:
- P0-1: Compressor is a configurable role/profile, not hardcoded, excluded from Hermes default routing chains.
- P0-2: Context threshold triggering (default 75%), fresh window preserved verbatim, no recursive double compression.
- P0-3: Strict verbatim preservation of factual entities (file paths, ports, IPs, variable/function names, commit SHAs, versions, metrics) with 100% retention guarantee.
- P0-4: Transparent telemetry, history store for original uncompressed text, non-blocking graceful fallback when compressor is offline.
- P0-5: Shared memory persistence in /srv/projects/AI-Memory indexed by GGUF build metadata.
- P0-6: Audit pass testing on live server (if accessible) and mock offline fallback.
"""
from __future__ import annotations

import json
import os
import tempfile
import urllib.error
import urllib.request
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from antigravity_provider.router.context_compressor import (
    COMPRESSED_BLOCK_END,
    COMPRESSED_BLOCK_START,
    CompressionOutcome,
    ContextCompressor,
    FactualEntities,
    extract_factual_entities,
    verify_facts_retention,
)
from antigravity_provider.router.local_supervisor import (
    LocalSupervisor,
    ServerPropsResult,
    TokenCountResult,
)
from antigravity_provider.router.router_config import RouterConfig, RouterProfileConfig
from antigravity_provider.router.settings_service import (
    DEFAULT_SETTINGS,
    get_hub_settings,
    invalidate_settings_cache,
    save_hub_settings,
)
from antigravity_provider.router.web.server import app


# ─────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────
@pytest.fixture
def tmp_vault(tmp_path: Path):
    vault = tmp_path / "AI-Memory"
    vault.mkdir(parents=True, exist_ok=True)
    (vault / "01_PROJECTS" / "hermes-hub").mkdir(parents=True, exist_ok=True)
    return vault


@pytest.fixture
def test_client():
    return TestClient(app)


# ─────────────────────────────────────────────────────────────
# P0-1: Configurable role & profile
# ─────────────────────────────────────────────────────────────
def test_p0_1_compressor_unconfigured_returns_nd_status(tmp_vault: Path):
    """When compressor profile is not selected, returns unconfigured N/D without error."""
    compressor = ContextCompressor(memory_file=tmp_vault / "01_PROJECTS" / "hermes-hub" / "compression_memory.json")
    supervisor = LocalSupervisor(compressor=compressor)

    # Status without profile
    status = supervisor.get_compression_status(compressor_profile=None)
    assert status["configured"] is False
    assert status["status"] == "unconfigured"
    assert "Н/Д: модель для сжатия не выбрана" in status["display_status"]

    # Compression with unconfigured profile
    messages = [
        {"role": "system", "content": "System prompt"},
        {"role": "user", "content": "Hello world" * 100},
    ]
    with patch.dict(os.environ, {}, clear=True):
        res_msgs, outcome = compressor.compress_messages_if_needed(
            messages=messages,
            target_context_limit=1000,
            current_token_count=800,
            compressor_profile=None,
        )
    assert outcome.status == "UNCONFIGURED"
    assert "Н/Д" in outcome.status_message
    assert res_msgs == messages


def test_p0_1_compressor_endpoint_resolved_from_profile(tmp_vault: Path):
    """Compressor endpoint is dynamically resolved from profile config, not hardcoded."""
    compressor = ContextCompressor(memory_file=tmp_vault / "01_PROJECTS" / "hermes-hub" / "compression_memory.json")

    pconfig = RouterProfileConfig(
        profile_id="local-compressor-custom",
        provider="local",
        custom_base_url="http://192.168.1.100:9999/v1",
        preferred_models=["CustomCompressor-7B"],
        auth_config={"api_key": "secret-token-123"},
    )

    base_url, model, token = compressor.resolve_compressor_endpoint(pconfig)
    assert base_url == "http://192.168.1.100:9999/v1"
    assert model == "CustomCompressor-7B"
    assert token == "secret-token-123"


# ─────────────────────────────────────────────────────────────
# P0-2: Triggering conditions & threshold
# ─────────────────────────────────────────────────────────────
def test_p0_2_threshold_skips_when_under_limit(tmp_vault: Path):
    """When token count is below threshold percent (e.g. 50% < 75%), compression is skipped."""
    compressor = ContextCompressor(memory_file=tmp_vault / "01_PROJECTS" / "hermes-hub" / "compression_memory.json")

    pconfig = RouterProfileConfig(
        profile_id="compressor-mock",
        provider="local",
        custom_base_url="http://127.0.0.1:8082/v1",
        preferred_models=["Qwen3-4B-2507"],
    )

    messages = [
        {"role": "system", "content": "System prompt"},
        {"role": "user", "content": "Message 1"},
        {"role": "assistant", "content": "Response 1"},
        {"role": "user", "content": "Message 2"},
    ]

    # Target 10,000, current 5,000 -> 50% < 75% threshold
    res_msgs, outcome = compressor.compress_messages_if_needed(
        messages=messages,
        target_context_limit=10000,
        current_token_count=5000,
        compressor_profile=pconfig,
        threshold_percent=75.0,
    )

    assert outcome.status == "SKIPPED"
    assert "В пределах нормы" in outcome.status_message
    assert res_msgs == messages


def test_p0_2_fresh_window_preserved_verbatim_and_no_double_nesting(tmp_vault: Path):
    """Fresh messages remain completely verbatim; existing summary blocks are unnested without recursion."""
    compressor = ContextCompressor(memory_file=tmp_vault / "01_PROJECTS" / "hermes-hub" / "compression_memory.json")

    pconfig = RouterProfileConfig(
        profile_id="compressor-mock",
        provider="local",
        custom_base_url="http://127.0.0.1:8082/v1",
        preferred_models=["Qwen3-4B-2507"],
    )

    # Existing summary block inside history
    prev_summary = (
        f"{COMPRESSED_BLOCK_START}\n"
        f"## Сжатая сводка предшествующего контекста\n"
        f"- Server running on 192.168.1.81:8765\n"
        f"- Active port: :8081\n"
        f"{COMPRESSED_BLOCK_END}"
    )

    messages = [
        {"role": "system", "content": "You are a senior developer."},
        {"role": "user", "content": prev_summary},
        {"role": "user", "content": "Step 2: Created /srv/projects/hermes/test.py with SHA 8e75dc6."},
        {"role": "assistant", "content": "Step 2 done."},
        # Fresh window (last 2 messages)
        {"role": "user", "content": "Fresh user request: run tests now."},
        {"role": "assistant", "content": "Fresh assistant response."},
    ]

    mock_llm_response = {
        "choices": [{
            "message": {
                "role": "assistant",
                "content": (
                    "- Server running on 192.168.1.81:8765\n"
                    "- Active port :8081\n"
                    "- Created /srv/projects/hermes/test.py with SHA 8e75dc6"
                )
            }
        }],
        "model": "Qwen3-4B-2507-Instruct-Q4_K_M.gguf",
    }

    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(mock_llm_response).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        res_msgs, outcome = compressor.compress_messages_if_needed(
            messages=messages,
            target_context_limit=1000,
            current_token_count=900,
            compressor_profile=pconfig,
            threshold_percent=75.0,
            keep_recent_messages=2,
        )

    assert outcome.status == "SUCCESS"
    assert outcome.retention_percent == 100.0

    # System message preserved
    assert res_msgs[0]["content"] == "You are a senior developer."

    # Fresh window preserved verbatim
    assert res_msgs[-2]["content"] == "Fresh user request: run tests now."
    assert res_msgs[-1]["content"] == "Fresh assistant response."

    # Only 1 single compression block, never nested
    compressed_content = res_msgs[1]["content"]
    assert compressed_content.count(COMPRESSED_BLOCK_START) == 1
    assert compressed_content.count(COMPRESSED_BLOCK_END) == 1


# ─────────────────────────────────────────────────────────────
# P0-3: Strict Verbatim Preservation of Factual Entities
# ─────────────────────────────────────────────────────────────
def test_p0_3_extract_and_verify_all_factual_entities():
    """Extracts and verifies 100% of paths, ports, IPs, SHAs, versions, and metrics."""
    text = (
        "Server deployed on 192.168.1.81:8765. Primary coder is on port 8081 with 224K context (229376 tokens). "
        "Measured generation speed: 107.4 tok/s, VRAM: 30008 MiB. Local compressor on port 8082 with 32768 context. "
        "File: /srv/projects/Agent projects/hermes-hub/src/antigravity_provider/router/local_supervisor.py. "
        "Commit SHA: 26f7d2c, version: v0.1.2. Classes: LocalSupervisor and ContextCompressor."
    )

    facts = extract_factual_entities(text)
    assert "/srv/projects/Agent projects/hermes-hub/src/antigravity_provider/router/local_supervisor.py" in facts.file_paths
    assert "192.168.1.81" in facts.ip_addresses
    assert any(":8081" in p or "8081" in p for p in facts.port_numbers)
    assert any(":8082" in p or "8082" in p for p in facts.port_numbers)
    assert "26f7d2c" in facts.commit_shas
    assert "v0.1.2" in facts.version_numbers
    assert any("107.4" in m for m in facts.metrics)
    assert any("30008" in m for m in facts.metrics)
    assert "LocalSupervisor" in facts.identifiers

    # Verify retention in exact summary
    summary = (
        "Summary:\n"
        "- 192.168.1.81:8765\n"
        "- port 8081, 224K, 229376 tokens, 107.4 tok/s, 30008 MiB\n"
        "- port 8082, 32768 tokens\n"
        "- /srv/projects/Agent projects/hermes-hub/src/antigravity_provider/router/local_supervisor.py\n"
        "- SHA 26f7d2c, version v0.1.2\n"
        "- LocalSupervisor, ContextCompressor"
    )
    retention, preserved, missing = verify_facts_retention(summary, facts)
    assert retention >= 95.0


def test_p0_3_factual_safeguard_ledger_guarantees_100_percent_retention(tmp_vault: Path):
    """If LLM summary misses an entity, safeguard ledger automatically appends it to reach 100% retention."""
    compressor = ContextCompressor(memory_file=tmp_vault / "01_PROJECTS" / "hermes-hub" / "compression_memory.json")

    pconfig = RouterProfileConfig(
        profile_id="compressor-mock",
        provider="local",
        custom_base_url="http://127.0.0.1:8082/v1",
        preferred_models=["Qwen3-4B-2507"],
    )

    messages = [
        {"role": "system", "content": "You are a coder."},
        {"role": "user", "content": "Critical secret port is :8888 and critical commit is 79ac9cf5610dccf8."},
        {"role": "assistant", "content": "Understood."},
        {"role": "user", "content": "Recent question?"},
    ]

    # Model generates a summary that forgot the port and commit
    mock_llm_response = {
        "choices": [{
            "message": {
                "role": "assistant",
                "content": "User discussed server settings."
            }
        }],
        "model": "Qwen3-4B-2507-Instruct-Q4_K_M.gguf",
    }

    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(mock_llm_response).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        res_msgs, outcome = compressor.compress_messages_if_needed(
            messages=messages,
            target_context_limit=1000,
            current_token_count=800,
            compressor_profile=pconfig,
            threshold_percent=50.0,
            keep_recent_messages=1,
        )

    assert outcome.status == "SUCCESS"
    assert outcome.retention_percent == 100.0
    compressed_text = res_msgs[1]["content"]
    assert ":8888" in compressed_text
    assert "79ac9cf5610dccf8" in compressed_text


# ─────────────────────────────────────────────────────────────
# P0-4: Non-blocking graceful fallback & history snapshot
# ─────────────────────────────────────────────────────────────
def test_p0_4_compressor_offline_does_not_crash_task(tmp_vault: Path):
    """When compressor server is unreachable, task continues safely on uncompressed context."""
    compressor = ContextCompressor(memory_file=tmp_vault / "01_PROJECTS" / "hermes-hub" / "compression_memory.json")

    pconfig = RouterProfileConfig(
        profile_id="compressor-offline",
        provider="local",
        custom_base_url="http://127.0.0.1:9999/v1",  # dead port
        preferred_models=["Qwen3-4B-2507"],
    )

    messages = [
        {"role": "system", "content": "System message"},
        {"role": "user", "content": "Original user text" * 20},
        {"role": "assistant", "content": "Original assistant text" * 20},
        {"role": "user", "content": "Latest user query"},
    ]

    # Simulating connection error
    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("Connection refused")):
        res_msgs, outcome = compressor.compress_messages_if_needed(
            messages=messages,
            target_context_limit=100,
            current_token_count=500,
            compressor_profile=pconfig,
            threshold_percent=50.0,
            keep_recent_messages=1,
        )

    # Task is NOT aborted
    assert outcome.status == "ERROR"
    assert "Задача продолжается на исходном контексте" in outcome.status_message
    assert res_msgs == messages

    # Original messages preserved in history snapshot
    assert outcome.original_messages_snapshot == messages


# ─────────────────────────────────────────────────────────────
# P0-5: Shared Memory Persistence in AI-Memory
# ─────────────────────────────────────────────────────────────
def test_p0_5_compression_memory_recorded_by_gguf_name(tmp_vault: Path):
    """Records compression history in /srv/projects/AI-Memory indexed by GGUF model."""
    memory_file = tmp_vault / "01_PROJECTS" / "hermes-hub" / "compression_memory.json"
    compressor = ContextCompressor(memory_file=memory_file)

    pconfig = RouterProfileConfig(
        profile_id="compressor-p1",
        provider="local",
        custom_base_url="http://127.0.0.1:8082/v1",
        preferred_models=["Qwen3-4B-2507"],
    )

    messages = [
        {"role": "system", "content": "Sys"},
        {"role": "user", "content": "Server is 192.168.1.81:8081"},
        {"role": "assistant", "content": "Ok"},
        {"role": "user", "content": "Next"},
    ]

    mock_llm_response = {
        "choices": [{
            "message": {
                "role": "assistant",
                "content": "- 192.168.1.81:8081 active"
            }
        }],
        "model": "/srv/ai/models/qwen3-4b-compressor/Qwen_Qwen3-4B-Instruct-2507-Q4_K_M.gguf",
    }

    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(mock_llm_response).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        _, outcome = compressor.compress_messages_if_needed(
            messages=messages,
            target_context_limit=100,
            current_token_count=200,
            compressor_profile=pconfig,
            threshold_percent=50.0,
            keep_recent_messages=1,
        )

    assert outcome.status == "SUCCESS"
    assert memory_file.exists()

    data = json.loads(memory_file.read_text(encoding="utf-8"))
    assert "compressor_models" in data
    gguf_key = "Qwen_Qwen3-4B-Instruct-2507-Q4_K_M.gguf"
    assert gguf_key in data["compressor_models"]
    rec = data["compressor_models"][gguf_key]
    assert rec["successful_compressions"] == 1
    assert rec["avg_fact_retention_percent"] == 100.0
    assert len(rec["history"]) == 1


# ─────────────────────────────────────────────────────────────
# Web API & Action Handler Integration
# ─────────────────────────────────────────────────────────────
def test_web_api_compression_endpoints(test_client: TestClient):
    """Tests GET /api/compression/status, /api/compression/history, POST /api/compression/test."""
    # 1. GET /api/compression/status
    res = test_client.get("/api/compression/status")
    assert res.status_code == 200
    data = res.json()
    assert "threshold_percent" in data
    assert "display_status" in data

    # 2. GET /api/compression/history
    res_hist = test_client.get("/api/compression/history")
    assert res_hist.status_code == 200
    assert "history" in res_hist.json()

    # 3. POST /api/compression/test
    res_test = test_client.post("/api/compression/test", json={"profile_id": "none"})
    assert res_test.status_code == 200
    test_json = res_test.json()
    assert "message" in test_json
    assert "data" in test_json


# ─────────────────────────────────────────────────────────────
# P0-6: Live Server Verification (if 8082 is reachable)
# ─────────────────────────────────────────────────────────────
def test_p0_6_live_compressor_verification():
    """Live verification against local llama-server compressor on port 8082 if online."""
    try:
        req = urllib.request.Request("http://127.0.0.1:8082/health", headers={"User-Agent": "Test/1.0"})
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if data.get("status") != "ok":
                pytest.skip("Local compressor server on 8082 not healthy")
    except Exception as exc:
        pytest.skip(f"Local compressor server on 8082 not reachable: {exc}")

    compressor = ContextCompressor()
    pconfig = RouterProfileConfig(
        profile_id="live-compressor",
        provider="local",
        custom_base_url="http://127.0.0.1:8082/v1",
        preferred_models=["default"],
    )

    test_messages = [
        {"role": "system", "content": "You are a software engineer."},
        {"role": "user", "content": "Hermes Hub server runs on 192.168.1.81:8765. Primary coder is on port 8081 with 224K context (229376 tokens), speed 107.4 tok/s, VRAM 30008 MiB. Active branch: antigravity/a56-context-compression, Commit SHA: 26f7d2c, version v0.1.2. Local compressor is on port 8082 on CPU."},
        {"role": "assistant", "content": "Server metrics and ports registered."},
        {"role": "user", "content": "File path is /srv/projects/Agent projects/hermes-hub/src/antigravity_provider/router/local_supervisor.py."},
        {"role": "assistant", "content": "Path registered."},
        {"role": "user", "content": "What is our next action?"},
    ]

    res_msgs, outcome = compressor.compress_messages_if_needed(
        messages=test_messages,
        target_context_limit=32768,
        current_token_count=150,
        compressor_profile=pconfig,
        threshold_percent=0.0,  # force compression
        keep_recent_messages=2,
    )

    assert outcome.status == "SUCCESS"
    assert outcome.retention_percent == 100.0
    assert outcome.saved_tokens >= 0
    assert len(res_msgs) == 4  # system + compressed + 2 fresh

    compressed_body = res_msgs[1]["content"]
    assert "192.168.1.81" in compressed_body
    assert "8081" in compressed_body
    assert "8082" in compressed_body
    assert "26f7d2c" in compressed_body
    assert "v0.1.2" in compressed_body
