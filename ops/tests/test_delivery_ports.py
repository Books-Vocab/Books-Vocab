from __future__ import annotations

import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

OPS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPS))
# ruff: noqa: E402

from delivery_control.adapters.errors import AdapterCommandError
from delivery_control.adapters.git_commands import GitCommands
from delivery_control.domain.branch_refs import BranchInventory
from delivery_control.domain.candidate_issues import CandidateIssueInventory
from delivery_control.domain.errors import CompareAndSwapConflict
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
from delivery_control.domain.unreachable_commits import UnreachableCommitInventory
from delivery_control.ports.clock import ClockPort
from delivery_control.ports.git import GitCommandPort, GitQueryPort
from delivery_control.ports.github import GitHubCommandPort, GitHubQueryPort
from delivery_control.ports.process import CommandResult
from delivery_control.ports.registry import (
    RegistryCleanupQueryPort,
    RegistryCommandPort,
    RegistryDiscardCommandPort,
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

        def unreachable_commit_inventory(self) -> UnreachableCommitInventory:
            return UnreachableCommitInventory()

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

        def is_ancestor(self, ancestor_sha: str, descendant_sha: str) -> bool:
            return True

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

        def park_main_to_origin(
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
        def record_published_base(
            self,
            *,
            lane_id: str,
            expected_claim_generation: int,
            expected_branch: str,
            expected_path: str,
            expected_head_sha: str,
            expected_handback_base_sha: str,
            published_base_sha: str,
        ) -> None:
            return None

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

    class FakeRegistryDiscardCommand:
        def discard(
            self,
            *,
            lane_id: str,
            expected_claim_generation: int,
            expected_branch: str,
            expected_path: str,
            expected_head_sha: str,
            operator: str,
            reason: str,
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
    assert not isinstance(FakeRegistryCommand(), RegistryDiscardCommandPort)
    assert isinstance(FakeRegistryDiscardCommand(), RegistryDiscardCommandPort)
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


def test_git_commands_park_main_uses_cas_without_reset_rebase_delete_or_merge() -> None:
    base = "a" * 40
    local = "b" * 40

    class Query:
        def __init__(self) -> None:
            self.local = local
            self.origin = base

        def local_main_sha(self) -> str:
            return self.local

        def origin_main_sha(self) -> str:
            return self.origin

    class Client:
        def __init__(self, query: Query) -> None:
            self.query = query
            self.branch = "main"
            self.calls: list[tuple[str, ...]] = []

        def run(self, *args: str, cwd: Path | None = None) -> str:
            del cwd
            self.calls.append(args)
            if args == ("branch", "--show-current"):
                return self.branch
            if args == ("status", "--porcelain=v1", "--untracked-files=all"):
                return ""
            if args[:2] == ("checkout", "--detach"):
                self.branch = ""
                return ""
            if args[:1] == ("update-ref",):
                self.query.local = base
                return ""
            if args == ("switch", "main"):
                self.branch = "main"
                return ""
            raise AssertionError(args)

    query = Query()
    client = Client(query)
    result = GitCommands(
        repo=Path("/repo"), client=client, query=query
    ).park_main_to_origin(expected_local_sha=local, expected_origin_sha=base)

    assert result == base
    assert query.local == base
    assert client.branch == "main"
    assert ("update-ref", "refs/heads/main", base, local) in client.calls
    assert not {
        command
        for call in client.calls
        for command in call
        if command in {"reset", "rebase", "delete", "merge"}
    }


def test_git_commands_park_main_compensates_detach_when_cas_mutation_fails() -> None:
    base = "a" * 40
    local = "b" * 40

    class Query:
        def local_main_sha(self) -> str:
            return local

        def origin_main_sha(self) -> str:
            return base

    class Client:
        def __init__(self) -> None:
            self.branch = "main"
            self.calls: list[tuple[str, ...]] = []

        def run(self, *args: str, cwd: Path | None = None) -> str:
            del cwd
            self.calls.append(args)
            if args == ("branch", "--show-current"):
                return self.branch
            if args == ("status", "--porcelain=v1", "--untracked-files=all"):
                return ""
            if args[:2] == ("checkout", "--detach"):
                self.branch = ""
                return ""
            if args[:1] == ("update-ref",):
                raise AdapterCommandError(CommandResult(args, 1, "", "CAS race", False))
            if args == ("switch", "main"):
                self.branch = "main"
                return ""
            raise AssertionError(args)

    query = Query()
    client = Client()
    with pytest.raises(CompareAndSwapConflict, match="canonical main park failed"):
        GitCommands(repo=Path("/repo"), client=client, query=query).park_main_to_origin(
            expected_local_sha=local, expected_origin_sha=base
        )

    assert client.branch == "main"
    assert client.calls[-1] == ("switch", "main")
