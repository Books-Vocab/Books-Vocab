"""Fail-closed synchronization of canonical local main."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..domain.errors import PolicyViolation
from ..ports.git import GitCommandPort, GitQueryPort


@dataclass(frozen=True)
class MainSyncResult:
    before_sha: str
    origin_sha: str
    after_sha: str
    changed: bool


class MainSyncService:
    def __init__(
        self,
        *,
        canonical_path: Path,
        query: GitQueryPort,
        command: GitCommandPort,
    ) -> None:
        self.canonical_path = canonical_path.resolve()
        self.query = query
        self.command = command

    def _validate_checkout(self, *, expected_head_sha: str) -> None:
        snapshot = self.query.inspect_worktree(
            self.canonical_path, expected_head_sha
        )
        if (
            snapshot.path.resolve() != self.canonical_path
            or snapshot.branch != "main"
            or not snapshot.clean
            or snapshot.head_sha != expected_head_sha
        ):
            raise PolicyViolation(
                "canonical checkout must be clean, on main, and match local main"
            )

    def sync(self) -> MainSyncResult:
        origin = self.query.origin_main_sha()
        before = self.query.local_main_sha()
        self._validate_checkout(expected_head_sha=before)
        if before == origin:
            return MainSyncResult(before, origin, before, False)
        after = self.command.fast_forward_main(
            expected_local_sha=before,
            expected_origin_sha=origin,
        )
        if after != origin or self.query.local_main_sha() != origin:
            raise PolicyViolation("canonical main fast-forward did not reach origin/main")
        self._validate_checkout(expected_head_sha=origin)
        return MainSyncResult(before, origin, after, True)
