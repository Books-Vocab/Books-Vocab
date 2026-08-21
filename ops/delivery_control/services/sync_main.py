"""Fail-closed synchronization of canonical local main."""

from __future__ import annotations

from dataclasses import dataclass

from ..ports.git import GitCommandPort, GitQueryPort


@dataclass(frozen=True)
class MainSyncResult:
    before_sha: str
    origin_sha: str
    after_sha: str
    changed: bool


class MainSyncService:
    def __init__(self, *, query: GitQueryPort, command: GitCommandPort) -> None:
        self.query = query
        self.command = command

    def sync(self) -> MainSyncResult:
        before = self.query.local_main_sha()
        origin = self.query.origin_main_sha()
        if before == origin:
            return MainSyncResult(before, origin, before, False)
        after = self.command.fast_forward_main(
            expected_local_sha=before,
            expected_origin_sha=origin,
        )
        return MainSyncResult(before, origin, after, True)
