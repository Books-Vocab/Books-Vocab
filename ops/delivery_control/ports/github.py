from __future__ import annotations

from typing import Protocol, runtime_checkable

from delivery_control.domain.models import PullRequestSnapshot
from delivery_control.domain.states import CheckStatus


@runtime_checkable
class GitHubQueryPort(Protocol):
    def list_open_pull_requests(self) -> tuple[PullRequestSnapshot, ...]: ...

    def find_open_pull_request(self, branch: str) -> PullRequestSnapshot | None: ...

    def get_pull_request(self, number: int) -> PullRequestSnapshot: ...

    def required_check_status(self, number: int) -> CheckStatus: ...


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
