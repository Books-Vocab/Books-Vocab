from __future__ import annotations

from pathlib import Path
import sys

import pytest

OPS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPS))

from delivery_control.adapters.errors import AdapterError  # noqa: E402
from delivery_control.application_build import _canonical_repo  # noqa: E402


class _Probe:
    def __init__(self, worktrees: tuple[object, ...]) -> None:
        self.worktrees = worktrees

    def list_worktrees(self) -> tuple[object, ...]:
        return self.worktrees


def _worktree(path: str, branch: str) -> object:
    return type("Worktree", (), {"path": Path(path), "branch": branch})()


def test_canonical_repo_selects_the_unique_main_worktree() -> None:
    main = Path("/repo")
    probe = _Probe(
        (
            _worktree("/owner", "debug/feature"),
            _worktree(str(main), "main"),
        )
    )

    assert _canonical_repo(main, probe=probe) == main


def test_canonical_repo_refuses_when_main_is_not_checked_out() -> None:
    probe = _Probe((_worktree("/owner", "debug/feature"),))

    with pytest.raises(AdapterError, match="main checkout is unavailable"):
        _canonical_repo(Path("/owner"), probe=probe)


def test_canonical_repo_refuses_ambiguous_main_checkouts() -> None:
    probe = _Probe(
        (
            _worktree("/main-a", "main"),
            _worktree("/main-b", "main"),
        )
    )

    with pytest.raises(AdapterError, match="main checkout is ambiguous"):
        _canonical_repo(Path("/owner"), probe=probe)


def test_canonical_repo_keeps_non_repository_composition_fallback() -> None:
    class FailingProbe:
        def list_worktrees(self) -> tuple[object, ...]:
            raise AdapterError("not a repository")

    source = Path("/composition-test")
    assert _canonical_repo(source, probe=FailingProbe()) == source
