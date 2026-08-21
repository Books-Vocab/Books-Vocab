from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..domain.observations import (
    CheckSnapshot,
    PullRequestInventory,
    PullRequestSnapshot,
)


@runtime_checkable
class GitHubQueryPort(Protocol):
    def list_open_pull_requests(self) -> PullRequestInventory: ...

    def find_open_pull_request(self, branch: str) -> PullRequestSnapshot | None: ...

    def get_pull_request(self, number: int) -> PullRequestSnapshot: ...

    def required_check_snapshot(self, number: int) -> CheckSnapshot: ...

    def changed_paths(self, number: int) -> tuple[str, ...]: ...

    def branch_is_protected(self, branch: str) -> bool: ...


@runtime_checkable
class GitHubCommandPort(Protocol):
    def create_pull_request(
        self,
        *,
        branch: str,
        title: str,
        body: str,
    ) -> PullRequestSnapshot: ...

    def update_pull_request(
        self,
        *,
        number: int,
        title: str,
        body: str,
    ) -> PullRequestSnapshot: ...

    def mark_ready(self, number: int) -> PullRequestSnapshot: ...

    def enqueue(
        self, *, number: int, expected_base_sha: str, expected_head_sha: str
    ) -> None: ...
