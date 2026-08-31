#!/usr/bin/env python3
"""
Memory Freshness Checker (Task A47)
Validates that project memory (CURRENT_STATE.md) matches actual repository git state.

Usage:
    python scripts/check_memory_freshness.py [--strict] [--memory-path <path>] [--repo-path <path>]
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path


DEFAULT_MEMORY_ROOT = Path("/srv/projects/AI-Memory")
DEFAULT_PROJECT = "hermes-hub"


def get_git_commit(repo_path: Path, ref: str = "HEAD") -> str | None:
    """Retrieve full or short commit hash for a given git reference."""
    try:
        res = subprocess.run(
            ["git", "-C", str(repo_path), "rev-parse", ref],
            capture_output=True,
            text=True,
            check=True,
        )
        return res.stdout.strip()
    except (subprocess.SubprocessError, FileNotFoundError):
        return None


def get_git_branch(repo_path: Path) -> str | None:
    """Retrieve current branch name."""
    try:
        res = subprocess.run(
            ["git", "-C", str(repo_path), "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        return res.stdout.strip()
    except (subprocess.SubprocessError, FileNotFoundError):
        return None


def is_commit_in_history(repo_path: Path, commit_hash: str) -> bool:
    """Check if a commit exists in the repository object database."""
    try:
        subprocess.run(
            ["git", "-C", str(repo_path), "cat-file", "-e", f"{commit_hash}^{{commit}}"],
            capture_output=True,
            check=True,
        )
        return True
    except (subprocess.SubprocessError, FileNotFoundError):
        return False


def is_ancestor(repo_path: Path, ancestor: str, descendant: str = "HEAD") -> bool:
    """Check if ancestor commit is reachable from descendant commit."""
    try:
        res = subprocess.run(
            ["git", "-C", str(repo_path), "merge-base", "--is-ancestor", ancestor, descendant],
            capture_output=True,
        )
        return res.returncode == 0
    except (subprocess.SubprocessError, FileNotFoundError):
        return False


def extract_recorded_commit(content: str) -> str | None:
    """
    Extract the recorded commit hash from CURRENT_STATE.md text.
    Matches patterns like:
      - main = 80aab00
      - Canonical HEAD (main): `80aab00`
      - HEAD (main): `c35bc48`
      - commit `80aab00`
    """
    patterns = [
        r"main\s*=\s*`?([0-9a-fA-F]{7,40})`?",
        r"Canonical HEAD.*?:\s*`?([0-9a-fA-F]{7,40})`?",
        r"HEAD\s*\(main\):\s*`?([0-9a-fA-F]{7,40})`?",
        r"HEAD:\s*`?([0-9a-fA-F]{7,40})`?",
    ]
    for pattern in patterns:
        match = re.search(pattern, content, re.IGNORECASE)
        if match:
            return match.group(1).lower()
    return None


def check_memory_freshness(
    repo_path: Path | None = None,
    memory_file: Path | None = None,
    strict: bool = False,
) -> tuple[bool, str]:
    """
    Perform freshness verification. Returns (is_fresh, summary_message).
    """
    if repo_path is None:
        repo_path = Path(__file__).resolve().parent.parent

    if memory_file is None:
        env_path = os.getenv("AI_MEMORY_PATH")
        if env_path:
            memory_file = Path(env_path)
            if memory_file.is_dir():
                memory_file = memory_file / "01_PROJECTS" / DEFAULT_PROJECT / "CURRENT_STATE.md"
        else:
            memory_file = DEFAULT_MEMORY_ROOT / "01_PROJECTS" / DEFAULT_PROJECT / "CURRENT_STATE.md"

    if not memory_file.exists():
        msg = (
            f"[WARNING] Canonical memory file not found: {memory_file}\n"
            f"Note: AI-Memory is canonically hosted on server 192.168.1.81. "
            f"If executing in an isolated runner or off-server environment, this is expected."
        )
        return (False if strict else True, msg)

    try:
        content = memory_file.read_text(encoding="utf-8", errors="ignore")
    except Exception as e:
        return (False, f"[ERROR] Failed to read memory file {memory_file}: {e}")

    recorded_commit = extract_recorded_commit(content)
    if not recorded_commit:
        return (False, f"[ERROR] Could not extract recorded commit hash from {memory_file}")

    head_commit = get_git_commit(repo_path, "HEAD")
    main_commit = get_git_commit(repo_path, "origin/main") or get_git_commit(repo_path, "main")
    branch = get_git_branch(repo_path) or "unknown"

    if not head_commit:
        return (False, f"[ERROR] Failed to inspect git repository at {repo_path}")

    head_short = head_commit[: len(recorded_commit)]
    main_short = main_commit[: len(recorded_commit)] if main_commit else "N/A"

    recorded_in_history = is_commit_in_history(repo_path, recorded_commit)
    is_head_match = head_short.lower() == recorded_commit.lower()
    is_main_match = main_short.lower() == recorded_commit.lower() if main_commit else False

    report_lines = [
        "=== AI Memory Freshness Verification ===",
        f"Memory File:      {memory_file}",
        f"Recorded Commit:  {recorded_commit}",
        f"Current Branch:   {branch}",
        f"Current HEAD:     {head_commit[:10]}",
        f"Main Commit:      {main_commit[:10] if main_commit else 'N/A'}",
        f"In Git History:   {'YES' if recorded_in_history else 'NO'}",
    ]

    if is_head_match or is_main_match:
        report_lines.append("[STATUS] FRESH: Memory accurately matches canonical git repository state.")
        return (True, "\n".join(report_lines))

    # If we are on a feature branch descended from the recorded main commit
    if recorded_in_history and is_ancestor(repo_path, recorded_commit, "HEAD"):
        report_lines.append(
            f"[STATUS] FRESH (Active Branch): Working on '{branch}' based on recorded baseline {recorded_commit}."
        )
        return (True, "\n".join(report_lines))

    if recorded_in_history:
        report_lines.append(
            f"[STATUS] DIVERGED: Recorded commit {recorded_commit} exists in history but differs from current main/HEAD."
        )
        return (False if strict else True, "\n".join(report_lines))

    report_lines.append(
        f"[STATUS] STALE: Recorded commit {recorded_commit} does NOT exist in current repository history."
    )
    return (False, "\n".join(report_lines))


def main() -> int:
    parser = argparse.ArgumentParser(description="Check AI-Memory freshness against git repository.")
    parser.add_argument("--strict", action="store_true", help="Fail with exit code 1 on any discrepancy.")
    parser.add_argument("--memory-path", type=Path, help="Path to CURRENT_STATE.md or AI-Memory root.")
    parser.add_argument("--repo-path", type=Path, help="Path to git repository root.")
    args = parser.parse_args()

    mem_path = args.memory_path
    if mem_path and mem_path.is_dir():
        mem_path = mem_path / "01_PROJECTS" / DEFAULT_PROJECT / "CURRENT_STATE.md"

    is_fresh, summary = check_memory_freshness(
        repo_path=args.repo_path,
        memory_file=mem_path,
        strict=args.strict,
    )

    print(summary)
    return 0 if is_fresh else 1


if __name__ == "__main__":
    sys.exit(main())
