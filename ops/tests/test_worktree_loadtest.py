"""Focused contracts for the throwaway worktree load-test harness."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "worktree_loadtest", ROOT / "ops" / "worktree_loadtest.py"
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    )
    return result.stdout.strip()


def test_loadtest_lane_commit_is_subject_only(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "test@example.test")
    _git(repo, "config", "user.name", "Test")
    (repo / "ops" / "loadtest_fixtures").mkdir(parents=True)

    steps = MODULE.make_lane_commit(repo, 1, "isolated")

    assert steps[-1]["rc"] == 0
    message = _git(repo, "show", "-s", "--format=%B", "HEAD")
    assert message.splitlines() == ["ops: load-test lane 1"]


def test_loadtest_handback_uses_typed_ordinary_child_receipt(tmp_path: Path) -> None:
    worktree = tmp_path / "worktree"
    outcomes = tmp_path / ".cache" / "handback-outcomes.json"
    command = MODULE.typed_child_handback_command(
        worktree, "feat/lt-00", outcomes
    )

    assert command == [
        str(worktree / "ops" / "worktree_registry.py"),
        "hand-back",
        "--branch", "feat/lt-00",
        "--path", str(worktree),
        "--role", "child",
        "--outcomes", str(outcomes),
        "--json",
    ]
