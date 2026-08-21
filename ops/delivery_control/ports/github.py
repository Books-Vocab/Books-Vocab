from __future__ import annotations

from typing import Protocol, runtime_checkable

from delivery_control.domain.models import PullRequestSnapshot


@runtime_checkable
class GitHubQueryPort(Protocol):
    def find_open_pull_request(self, branch: str) -> PullRequestSnapshot | None: ...

    def get_pull_request(self, number: int) -> PullRequestSnapshot: ...


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

    def enqueue(self, number: int) -> None: ...
