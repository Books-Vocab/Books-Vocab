from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

OPS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPS))

from delivery_control.domain.models import (
    PullRequestSnapshot,
    RegistrySnapshot,
    WorktreeSnapshot,
)
from delivery_control.ports.clock import ClockPort
from delivery_control.ports.git import GitCommandPort, GitQueryPort
from delivery_control.ports.github import GitHubCommandPort, GitHubQueryPort
from delivery_control.ports.registry import RegistryCommandPort, RegistryQueryPort
from delivery_control.ports.runtime import AgentRuntimePort


def test_ports_are_small_runtime_checkable_capability_contracts() -> None:
    class FakeClock:
        def now(self) -> datetime:
            return datetime(2026, 8, 21, tzinfo=UTC)

    class FakeGitQuery:
        def inspect_worktree(self, path: Path) -> WorktreeSnapshot:
            raise NotImplementedError

        def remote_branch_sha(self, branch: str) -> str | None:
            return None

        def local_main_sha(self) -> str:
            return "a" * 40

        def origin_main_sha(self) -> str:
            return "a" * 40

    class FakeGitCommand:
        def push_branch(
            self,
            *,
            worktree: Path,
            branch: str,
            expected_remote_sha: str | None = None,
        ) -> str:
            return "b" * 40

        def remove_worktree(self, path: Path) -> None:
            return None

        def delete_local_branch(self, branch: str) -> None:
            return None

        def fast_forward_main(self, expected_origin_sha: str) -> str:
            return expected_origin_sha

    class FakeGitHubQuery:
        def find_open_pull_request(self, branch: str) -> PullRequestSnapshot | None:
            return None

        def get_pull_request(self, number: int) -> PullRequestSnapshot:
            raise NotImplementedError

    class FakeGitHubCommand:
        def create_pull_request(
            self, *, branch: str, title: str, body: str
        ) -> PullRequestSnapshot:
            raise NotImplementedError

        def update_pull_request(
            self, *, number: int, title: str, body: str
        ) -> PullRequestSnapshot:
            raise NotImplementedError

        def mark_ready(self, number: int) -> PullRequestSnapshot:
            raise NotImplementedError

        def enqueue(self, number: int) -> None:
            return None

    class FakeRegistryQuery:
        def list_active(self) -> tuple[RegistrySnapshot, ...]:
            return ()

        def get(self, lane_id: str) -> RegistrySnapshot | None:
            return None

    class FakeRegistryCommand:
        def persist_handback(self, lane_id: str, payload: dict[str, object]) -> None:
            return None

        def resolve(self, lane_id: str, disposition: str) -> None:
            return None

    class FakeRuntime:
        def owner_status(self, thread_id: str) -> str:
            return "running"

        def dispatch(self, thread_id: str, instruction: str) -> None:
            return None

    assert isinstance(FakeClock(), ClockPort)
    assert isinstance(FakeGitQuery(), GitQueryPort)
    assert isinstance(FakeGitCommand(), GitCommandPort)
    assert isinstance(FakeGitHubQuery(), GitHubQueryPort)
    assert isinstance(FakeGitHubCommand(), GitHubCommandPort)
    assert isinstance(FakeRegistryQuery(), RegistryQueryPort)
    assert isinstance(FakeRegistryCommand(), RegistryCommandPort)
    assert isinstance(FakeRuntime(), AgentRuntimePort)
