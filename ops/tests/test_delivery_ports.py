from __future__ import annotations

import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

OPS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPS))

from delivery_control.domain.branch_refs import BranchInventory
from delivery_control.domain.candidate_issues import CandidateIssueInventory
from delivery_control.domain.models import (
    HandbackReceipt,
)
from delivery_control.domain.observations import (
    CheckSnapshot,
    MainLandingSnapshot,
    MergeQueueEntrySnapshot,
    PhysicalWorktree,
    PullRequestInventory,
    PullRequestSnapshot,
    RegistryCollisionInventory,
    RegistryInventory,
    RegistrySnapshot,
    WorktreeSnapshot,
)
from delivery_control.ports.clock import ClockPort
from delivery_control.ports.git import GitCommandPort, GitQueryPort
from delivery_control.ports.github import GitHubCommandPort, GitHubQueryPort
from delivery_control.ports.registry import (
    RegistryCleanupQueryPort,
    RegistryCommandPort,
    RegistryPublicationQueryPort,
    RegistryQueryPort,
)
from delivery_control.ports.runtime import AgentRuntimePort


def test_ports_are_small_runtime_checkable_capability_contracts() -> None:
    class FakeClock:
        def now(self) -> datetime:
            return datetime(2026, 8, 21, tzinfo=UTC)

    class FakeGitQuery:
        def list_worktrees(self) -> tuple[PhysicalWorktree, ...]:
            return ()

        def branch_inventory(self) -> BranchInventory:
            return BranchInventory()

        def canonical_checkout(self) -> object:
            raise NotImplementedError

        def inspect_worktree(self, path: Path, base_sha: str) -> WorktreeSnapshot:
            raise NotImplementedError

        def remote_branch_sha(self, branch: str) -> str | None:
            return None

        def local_branch_sha(self, branch: str) -> str | None:
            return None

        def local_main_sha(self) -> str:
            return "a" * 40

        def origin_main_sha(self) -> str:
            return "a" * 40

        def first_parent_landings(
            self, *, before_sha: str, after_sha: str
        ) -> tuple[MainLandingSnapshot, ...]:
            return ()

    class FakeGitCommand:
        def push_branch(
            self,
            *,
            worktree: Path,
            branch: str,
            expected_local_sha: str,
            expected_remote_sha: str | None = None,
        ) -> str:
            return "b" * 40

        def remove_worktree(self, path: Path, *, expected_head_sha: str) -> None:
            return None

        def delete_local_branch(self, branch: str, *, expected_head_sha: str) -> None:
            return None

        def delete_remote_branch(self, branch: str, *, expected_head_sha: str) -> None:
            return None

        def fast_forward_main(
            self, *, expected_local_sha: str, expected_origin_sha: str
        ) -> str:
            return expected_origin_sha

    class FakeGitHubQuery:
        def list_open_candidate_issues(self) -> CandidateIssueInventory:
            return CandidateIssueInventory(records=())

        def list_open_pull_requests(self) -> PullRequestInventory:
            return PullRequestInventory(records=())

        def list_pull_requests_for_branch(self, branch: str) -> PullRequestInventory:
            return PullRequestInventory(records=())

        def find_open_pull_request(self, branch: str) -> PullRequestSnapshot | None:
            return None

        def get_pull_request(self, number: int) -> PullRequestSnapshot:
            raise NotImplementedError

        def required_check_snapshot(self, number: int) -> CheckSnapshot:
            raise NotImplementedError

        def changed_paths(self, number: int) -> tuple[str, ...]:
            return ()

        def branch_is_protected(self, branch: str) -> bool:
            return False

        def required_status_contexts(self, branch: str) -> tuple[str, ...]:
            return ("required",)

        def merge_queue_enabled(self, branch: str) -> bool:
            return True

        def merge_queue_entry_id(self, pull_request_id: str) -> str | None:
            return None

        def merge_queue_entry_snapshot(
            self, pull_request_id: str
        ) -> MergeQueueEntrySnapshot | None:
            return None

    class FakeGitHubCommand:
        def create_pull_request(
            self, *, branch: str, title: str, body: str
        ) -> PullRequestSnapshot:
            raise NotImplementedError

        def update_pull_request(
            self,
            *,
            number: int,
            title: str,
            body: str,
            expected_head_sha: str,
        ) -> PullRequestSnapshot:
            raise NotImplementedError

        def mark_ready(self, number: int) -> PullRequestSnapshot:
            raise NotImplementedError

        def close_pull_request(
            self,
            *,
            number: int,
            expected_base_sha: str,
            expected_head_sha: str,
            expected_body: str,
        ) -> PullRequestSnapshot:
            raise NotImplementedError

        def reopen_pull_request(
            self,
            *,
            number: int,
            expected_base_sha: str,
            expected_head_sha: str,
            expected_body: str,
        ) -> PullRequestSnapshot:
            raise NotImplementedError

        def enqueue(
            self,
            *,
            number: int,
            expected_base_sha: str,
            expected_head_sha: str,
            expected_body: str,
        ) -> None:
            return None

    class FakeRegistryQuery:
        def list_records(self) -> RegistryInventory:
            return RegistryInventory(records=())

        def get(self, lane_id: str) -> RegistrySnapshot | None:
            return None

    class FakeRegistryCommand:
        def persist_handback(
            self, receipt: HandbackReceipt, *, expected_claim_generation: int
        ) -> None:
            return None

        def resolve(
            self,
            lane_id: str,
            disposition: str,
            *,
            expected_claim_generation: int,
            expected_branch: str,
            expected_path: str,
            expected_head_sha: str,
            terminal_proof=None,
        ) -> None:
            return None

    class FakeRegistryPublicationQuery:
        def get(self, lane_id: str) -> RegistrySnapshot | None:
            return None

        def list_collision_claims(self) -> RegistryCollisionInventory:
            return RegistryCollisionInventory(records=())

    class FakeRegistryCleanupQuery:
        def find_exact_claim(
            self,
            *,
            lane_id: str,
            branch: str,
            path: Path,
            claim_generation: int,
        ) -> RegistrySnapshot | None:
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
    assert isinstance(FakeRegistryPublicationQuery(), RegistryPublicationQueryPort)
    assert isinstance(FakeRegistryCleanupQuery(), RegistryCleanupQueryPort)
    assert isinstance(FakeRegistryCommand(), RegistryCommandPort)
    assert isinstance(FakeRuntime(), AgentRuntimePort)


def test_package_imports_work_from_repository_root_without_sys_path_patch() -> None:
    script = (
        "from ops.delivery_control.ports.git import GitQueryPort; "
        "assert GitQueryPort.__name__ == 'GitQueryPort'"
    )
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            script,
        ],
        cwd=OPS.parent,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
