from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

OPS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPS))

from delivery_control.adapters.git_cli import GitCliAdapter
from delivery_control.domain.errors import CompareAndSwapConflict
from delivery_control.domain.observations import (
    FileChange,
    FileOperation,
)
from delivery_control.ports.process import CommandResult


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def test_git_adapter_computes_operation_aware_exact_base_diff(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "base.txt").write_text("base\n", encoding="utf-8")
    _git(repo, "add", "base.txt")
    _git(repo, "commit", "-qm", "base")
    base_sha = _git(repo, "rev-parse", "HEAD")
    _git(repo, "switch", "-qc", "feat/example")
    (repo / "base.txt").write_text("changed\n", encoding="utf-8")
    (repo / "ops").mkdir()
    (repo / "ops" / "change.py").write_text("value = 1\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "change")

    snapshot = GitCliAdapter(repo=repo).inspect_worktree(repo, base_sha)

    assert snapshot.clean
    assert snapshot.changes == (
        FileChange(FileOperation.MODIFY, "base.txt"),
        FileChange(FileOperation.ADD, "ops/change.py"),
    )


def test_git_new_remote_branch_push_uses_absent_ref_lease(tmp_path: Path) -> None:
    head = "b" * 40
    runner = StaticRunner(
        [
            CommandResult(("git",), 0, "feat/one\n", ""),
            CommandResult(("git",), 0, f"{head}\n", ""),
            CommandResult(("git",), 0, "", ""),
            CommandResult(("git",), 0, "", ""),
            CommandResult(("git",), 0, "", ""),
            CommandResult(("git",), 0, f"{head}\trefs/heads/feat/one\n", ""),
        ]
    )
    adapter = GitCliAdapter(repo=tmp_path, runner=runner)

    adapter.push_branch(
        worktree=tmp_path,
        branch="feat/one",
        expected_local_sha=head,
        expected_remote_sha=None,
    )

    push = next(call for call in runner.calls if "push" in call)
    assert "--force-with-lease=refs/heads/feat/one:" in push


def test_git_local_branch_delete_uses_atomic_expected_old_sha(tmp_path: Path) -> None:
    head = "b" * 40
    runner = StaticRunner(
        [
            CommandResult(("git",), 0, f"{head}\n", ""),
            CommandResult(("git",), 0, "", ""),
            CommandResult(("git",), 128, "", "unknown revision"),
        ]
    )
    adapter = GitCliAdapter(repo=tmp_path, runner=runner)

    adapter.delete_local_branch("feat/one", expected_head_sha=head)

    assert any(
        call[-4:] == ("update-ref", "-d", "refs/heads/feat/one", head)
        for call in runner.calls
    )


def test_git_remote_branch_delete_uses_exact_lease(tmp_path: Path) -> None:
    head = "b" * 40
    runner = StaticRunner(
        [
            CommandResult(
                ("git",), 0, f"{head}\trefs/heads/feat/one\n", ""
            ),
            CommandResult(("git",), 0, "", ""),
            CommandResult(("git",), 0, "", ""),
        ]
    )
    adapter = GitCliAdapter(repo=tmp_path, runner=runner)

    adapter.delete_remote_branch("feat/one", expected_head_sha=head)

    push = next(call for call in runner.calls if "push" in call)
    assert f"--force-with-lease=refs/heads/feat/one:{head}" in push
    assert ":refs/heads/feat/one" in push


def test_git_push_lease_failure_is_a_compare_and_swap_conflict(tmp_path: Path) -> None:
    head = "b" * 40
    runner = StaticRunner(
        [
            CommandResult(("git",), 0, "feat/one\n", ""),
            CommandResult(("git",), 0, f"{head}\n", ""),
            CommandResult(("git",), 0, "", ""),
            CommandResult(("git",), 0, "", ""),
            CommandResult(("git",), 1, "", "stale info"),
        ]
    )
    adapter = GitCliAdapter(repo=tmp_path, runner=runner)

    with pytest.raises(CompareAndSwapConflict, match="lease"):
        adapter.push_branch(
            worktree=tmp_path,
            branch="feat/one",
            expected_local_sha=head,
            expected_remote_sha=None,
        )


def test_git_cleanup_refuses_canonical_checkout_and_main(tmp_path: Path) -> None:
    adapter = GitCliAdapter(repo=tmp_path, runner=StaticRunner([]))

    with pytest.raises(CompareAndSwapConflict, match="canonical"):
        adapter.remove_worktree(tmp_path, expected_head_sha="b" * 40)
    with pytest.raises(CompareAndSwapConflict, match="local main"):
        adapter.delete_local_branch("main", expected_head_sha="b" * 40)
    with pytest.raises(CompareAndSwapConflict, match="remote main"):
        adapter.delete_remote_branch("main", expected_head_sha="b" * 40)


class StaticRunner:
    def __init__(self, responses: list[CommandResult]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, ...]] = []

    def run(self, argv: tuple[str, ...], *, cwd: Path | None = None) -> CommandResult:
        self.calls.append(argv)
        return self.responses.pop(0)
