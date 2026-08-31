import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from check_memory_freshness import (
    check_memory_freshness,
    extract_recorded_commit,
    get_git_commit,
)


def test_extract_recorded_commit_formats():
    assert extract_recorded_commit("Status: main = 80aab00\nDone") == "80aab00"
    assert extract_recorded_commit("Canonical HEAD (main): `80aab00`\nOther text") == "80aab00"
    assert extract_recorded_commit("- HEAD (main): c35bc48\n- Branch: main") == "c35bc48"
    assert extract_recorded_commit("Some random text with no commit") is None


def test_check_memory_freshness_real_repo():
    canonical_memory = Path("/srv/projects/AI-Memory/01_PROJECTS/hermes-hub/CURRENT_STATE.md")

    if canonical_memory.exists():
        is_fresh, summary = check_memory_freshness(
            repo_path=REPO_ROOT,
            memory_file=canonical_memory,
            strict=True,
        )
        assert is_fresh is True
        assert "FRESH" in summary
        assert "80aab00" in summary


def test_check_memory_freshness_missing_file_strict_vs_non_strict(tmp_path):
    missing_file = tmp_path / "NON_EXISTENT_CURRENT_STATE.md"

    # Non-strict mode should return True with warning for non-server runners
    is_fresh_non_strict, summary_non_strict = check_memory_freshness(
        repo_path=REPO_ROOT,
        memory_file=missing_file,
        strict=False,
    )
    assert is_fresh_non_strict is True
    assert "[WARNING]" in summary_non_strict

    # Strict mode should return False
    is_fresh_strict, summary_strict = check_memory_freshness(
        repo_path=REPO_ROOT,
        memory_file=missing_file,
        strict=True,
    )
    assert is_fresh_strict is False
    assert "[WARNING]" in summary_strict


def test_check_memory_freshness_stale_commit(tmp_path):
    fake_memory = tmp_path / "CURRENT_STATE.md"
    fake_memory.write_text("main = 0000000000000000000000000000000000000000\n", encoding="utf-8")

    is_fresh, summary = check_memory_freshness(
        repo_path=REPO_ROOT,
        memory_file=fake_memory,
        strict=True,
    )
    assert is_fresh is False
    assert "STALE" in summary


def test_check_memory_freshness_valid_synthetic_memory(tmp_path):
    head = get_git_commit(REPO_ROOT, "HEAD")
    assert head is not None

    synthetic_memory = tmp_path / "CURRENT_STATE.md"
    synthetic_memory.write_text(f"# Current State\n\nCanonical HEAD (main): `{head[:7]}`\n", encoding="utf-8")

    is_fresh, summary = check_memory_freshness(
        repo_path=REPO_ROOT,
        memory_file=synthetic_memory,
        strict=True,
    )
    assert is_fresh is True
    assert "FRESH" in summary


def test_cli_execution(tmp_path):
    script_path = REPO_ROOT / "scripts" / "check_memory_freshness.py"

    head = get_git_commit(REPO_ROOT, "HEAD")
    synthetic_memory = tmp_path / "CURRENT_STATE.md"
    synthetic_memory.write_text(f"main = {head[:7]}\n", encoding="utf-8")

    res = subprocess.run(
        [sys.executable, str(script_path), "--memory-path", str(synthetic_memory), "--strict"],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0
    assert "FRESH" in res.stdout
