from __future__ import annotations

import sys
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

OPS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPS))

from delivery_control.domain.models import CheckStatus, HandbackReceipt, Scope
from delivery_control.domain.observations import (
    CheckSnapshot,
    FileChange,
    FileOperation,
    InventoryProblem,
    PhysicalWorktree,
    PullRequestInventory,
    PullRequestSnapshot,
    RegistryInventory,
    RegistrySnapshot,
    WorktreeSnapshot,
)
from delivery_control.domain.states import LaneState
from delivery_control.services.inspect import InspectService
from delivery_control.services.publish import render_pull_request_body


class FakeRegistry:
    def __init__(
        self,
        records: tuple[RegistrySnapshot, ...],
        *,
        problems: tuple[InventoryProblem, ...] = (),
    ) -> None:
        self.inventory = RegistryInventory(records=records, problems=problems)

    def list_records(self) -> RegistryInventory:
        return self.inventory

    def get(self, lane_id: str) -> RegistrySnapshot | None:
        return next(
            (item for item in self.inventory.records if item.lane_id == lane_id), None
        )


class FakeGit:
    def __init__(
        self,
        physical: tuple[PhysicalWorktree, ...],
        snapshots: dict[Path, WorktreeSnapshot],
        local_branches: dict[str, str] | None = None,
    ) -> None:
        self.physical = physical
        self.snapshots = snapshots
        self.local_branches = local_branches or {}

    def list_worktrees(self) -> tuple[PhysicalWorktree, ...]:
        return self.physical

    def inspect_worktree(self, path: Path, base_sha: str) -> WorktreeSnapshot:
        return self.snapshots[path]

    def remote_branch_sha(self, branch: str) -> str | None:
        return None

    def local_branch_sha(self, branch: str) -> str | None:
        return self.local_branches.get(branch)

    def local_main_sha(self) -> str:
        return "a" * 40

    def origin_main_sha(self) -> str:
        return "a" * 40


class FakeGitHub:
    def __init__(
        self,
        pull_requests: tuple[PullRequestSnapshot, ...],
        *,
        problems: tuple[InventoryProblem, ...] = (),
        queued_numbers: frozenset[int] = frozenset(),
    ) -> None:
        self.pull_requests = pull_requests
        self.problems = problems
        self.queued_numbers = queued_numbers

    def list_open_pull_requests(self) -> PullRequestInventory:
        return PullRequestInventory(
            tuple(item for item in self.pull_requests if item.state == "OPEN"),
            self.problems,
        )

    def list_pull_requests_for_branch(self, branch: str) -> PullRequestInventory:
        return PullRequestInventory(
            tuple(item for item in self.pull_requests if item.branch == branch)
        )

    def find_open_pull_request(self, branch: str) -> PullRequestSnapshot | None:
        return next(
            (item for item in self.pull_requests if item.branch == branch), None
        )

    def get_pull_request(self, number: int) -> PullRequestSnapshot:
        return next(item for item in self.pull_requests if item.number == number)

    def required_check_snapshot(self, number: int) -> CheckSnapshot:
        pull_request = self.get_pull_request(number)
        return CheckSnapshot(
            CheckStatus.SUCCESS,
            pull_request.head_sha,
            datetime(2026, 8, 21, tzinfo=UTC),
            ("required",),
        )

    def changed_paths(self, number: int) -> tuple[str, ...]:
        return ("ops/a.py",)

    def branch_is_protected(self, branch: str) -> bool:
        return False

    def merge_queue_entry_id(self, pull_request_id: str) -> str | None:
        number = int(pull_request_id.removeprefix("PR_"))
        return f"MQE_{number}" if number in self.queued_numbers else None


class FakeRuntime:
    def owner_status(self, thread_id: str) -> str:
        return "running"

    def dispatch(self, thread_id: str, instruction: str) -> None:
        return None


def _record(path: Path, *, status: str = "active") -> RegistrySnapshot:
    receipt = _receipt(path)
    return RegistrySnapshot(
        lane_id=receipt.lane_id,
        branch=receipt.branch,
        path=path,
        status=status,
        scope=receipt.scope,
        base_sha=receipt.base_sha,
        claim_generation=receipt.claim_generation,
        owner_thread_id=receipt.owner_thread_id,
        handed_back_sha=receipt.head_sha,
        handback_claim_generation=receipt.claim_generation,
        handback_valid=True,
        handback_digest=receipt.content_digest,
        handback_origin_main_sha=receipt.origin_main_sha,
    )


def _receipt(path: Path) -> HandbackReceipt:
    return HandbackReceipt(
        lane_id="#1",
        owner_thread_id="thread-1",
        claim_generation=3,
        branch="feat/one",
        worktree_path=str(path),
        base_sha="a" * 40,
        parent_sha="a" * 40,
        head_sha="b" * 40,
        origin_main_sha="a" * 40,
        content_digest="c" * 64,
        scope=Scope.from_paths(modify=("ops/a.py",)),
    )


def _snapshot(
    path: Path, *, clean: bool = True, head: str = "b" * 40
) -> WorktreeSnapshot:
    return WorktreeSnapshot(
        path=path,
        branch="feat/one",
        base_sha="a" * 40,
        head_sha=head,
        parent_sha="a" * 40,
        clean=clean,
        changes=(FileChange(FileOperation.MODIFY, "ops/a.py"),),
    )


def _pull_request(
    path: Path, *, head: str = "b" * 40, state: str = "OPEN"
) -> PullRequestSnapshot:
    receipt = _receipt(path)
    return PullRequestSnapshot(
        number=1,
        url="https://example.test/pull/1",
        branch="feat/one",
        base_sha="a" * 40,
        head_sha=head,
        state=state,
        draft=False,
        mergeable=True,
        title="fix: one",
        body=render_pull_request_body(receipt),
        node_id="PR_1",
    )


def test_inspect_service_requires_exact_registry_physical_pr_and_check_tuple(
    tmp_path: Path,
) -> None:
    path = tmp_path / "lane"
    physical = PhysicalWorktree(path=path, head_sha="b" * 40, branch="feat/one")
    service = InspectService(
        registry=FakeRegistry((_record(path),)),
        git=FakeGit((physical,), {path: _snapshot(path)}),
        github=FakeGitHub((_pull_request(path),)),
        runtime=FakeRuntime(),
    )
    inventory = service.inspect()
    active = next(item for item in inventory.lanes if item.key == "#1")
    assert active.decision.state is LaneState.PUBLISHED_LOCAL_CLEANUP
    assert not active.problems


def test_inspect_service_excludes_clean_canonical_main_from_lane_inventory(
    tmp_path: Path,
) -> None:
    main = PhysicalWorktree(path=tmp_path / "repo", head_sha="a" * 40, branch="main")
    service = InspectService(
        registry=FakeRegistry(()),
        git=FakeGit((main,), {}),
        github=FakeGitHub(()),
        runtime=FakeRuntime(),
    )

    assert service.inspect().lanes == ()


def test_inspect_service_never_marks_dirty_or_head_drift_ready(tmp_path: Path) -> None:
    path = tmp_path / "lane"
    physical = PhysicalWorktree(path=path, head_sha="c" * 40, branch="feat/one")
    service = InspectService(
        registry=FakeRegistry((_record(path),)),
        git=FakeGit((physical,), {path: _snapshot(path, clean=False, head="c" * 40)}),
        github=FakeGitHub((_pull_request(path),)),
        runtime=FakeRuntime(),
    )
    active = next(item for item in service.inspect().lanes if item.key == "#1")
    assert active.decision.state is LaneState.BLOCKED_DIRTY
    assert any("HEAD differs" in problem.reason for problem in active.problems)


def test_published_lane_is_remote_queue_not_orphaned_local_work(tmp_path: Path) -> None:
    path = tmp_path / "lane"
    published = _record(path, status="published")
    service = InspectService(
        registry=FakeRegistry((published,)),
        git=FakeGit((), {}),
        github=FakeGitHub((_pull_request(path),)),
        runtime=FakeRuntime(),
    )

    lane = next(
        item for item in service.inspect().lanes if item.key.startswith("published:")
    )

    assert lane.decision.state is LaneState.READY_TO_QUEUE
    assert lane.physical is None


def test_queued_pr_keeps_exact_receipt_when_main_base_advances(tmp_path: Path) -> None:
    path = tmp_path / "lane"
    published = _record(path, status="published")
    advanced = replace(_pull_request(path), base_sha="d" * 40)
    service = InspectService(
        registry=FakeRegistry((published,)),
        git=FakeGit((), {}),
        github=FakeGitHub((advanced,), queued_numbers=frozenset({1})),
        runtime=FakeRuntime(),
    )

    lane = next(
        item for item in service.inspect().lanes if item.key.startswith("published:")
    )

    assert lane.decision.state is LaneState.PR_QUEUED
    assert not lane.problems


def test_published_lane_with_local_branch_is_classified_for_cleanup(
    tmp_path: Path,
) -> None:
    path = tmp_path / "lane"
    published = _record(path, status="published")
    service = InspectService(
        registry=FakeRegistry((published,)),
        git=FakeGit((), {}, {"feat/one": "b" * 40}),
        github=FakeGitHub((_pull_request(path),)),
        runtime=FakeRuntime(),
    )

    lane = next(
        item for item in service.inspect().lanes if item.key.startswith("published:")
    )

    assert lane.decision.state is LaneState.PUBLISHED_LOCAL_CLEANUP


def test_interrupted_cleanup_lease_remains_visible_for_retry(tmp_path: Path) -> None:
    path = tmp_path / "lane"
    leased = _record(path, status="cleanup_pending")
    service = InspectService(
        registry=FakeRegistry((leased,)),
        git=FakeGit((), {}, {"feat/one": "b" * 40}),
        github=FakeGitHub((_pull_request(path),)),
        runtime=FakeRuntime(),
    )

    lane = next(
        item for item in service.inspect().lanes if item.key.startswith("published:")
    )

    assert lane.decision.state is LaneState.PUBLISHED_LOCAL_CLEANUP


def test_merged_pr_remains_visible_for_terminal_cleanup(tmp_path: Path) -> None:
    path = tmp_path / "lane"
    published = _record(path, status="published")
    service = InspectService(
        registry=FakeRegistry((published,)),
        git=FakeGit((), {}),
        github=FakeGitHub((_pull_request(path, state="MERGED"),)),
        runtime=FakeRuntime(),
    )

    lane = next(
        item for item in service.inspect().lanes if item.key.startswith("published:")
    )

    assert lane.decision.state is LaneState.TERMINAL_CLEANUP
    assert lane.pull_requests[0].state == "MERGED"


def test_published_lane_requires_exact_machine_receipt_before_queue(
    tmp_path: Path,
) -> None:
    path = tmp_path / "lane"
    published = _record(path, status="published")
    malformed = _pull_request(path)
    malformed = replace(
        malformed,
        body="## Scope\n- ops/a.py\n\n## Validation\n- required",
    )
    service = InspectService(
        registry=FakeRegistry((published,)),
        git=FakeGit((), {}),
        github=FakeGitHub((malformed,)),
        runtime=FakeRuntime(),
    )

    lane = next(
        item for item in service.inspect().lanes if item.key.startswith("published:")
    )

    assert lane.decision.state is LaneState.REQUIRED_FAILED
    assert any("typed delivery receipt" in problem.reason for problem in lane.problems)


def test_terminal_registry_history_does_not_claim_physical_worktree(
    tmp_path: Path,
) -> None:
    path = tmp_path / "lane"
    physical = PhysicalWorktree(path=path, head_sha="b" * 40, branch="feat/one")
    service = InspectService(
        registry=FakeRegistry((_record(path, status="abandoned"),)),
        git=FakeGit((physical,), {path: _snapshot(path)}),
        github=FakeGitHub(()),
        runtime=FakeRuntime(),
    )
    inventory = service.inspect()
    assert any(item.key == str(path.resolve()) for item in inventory.lanes)
    orphan = next(item for item in inventory.lanes if item.key == str(path.resolve()))
    assert orphan.decision.state is LaneState.BLOCKED_OWNER


def test_absent_abandoned_history_is_terminal_not_blocked(tmp_path: Path) -> None:
    path = tmp_path / "retired"
    service = InspectService(
        registry=FakeRegistry((_record(path, status="abandoned"),)),
        git=FakeGit((), {}),
        github=FakeGitHub(()),
        runtime=FakeRuntime(),
    )

    history = next(
        item for item in service.inspect().lanes if item.key.startswith("history:")
    )

    assert history.decision.state is LaneState.DONE


def test_inspect_surfaces_github_inventory_problems(tmp_path: Path) -> None:
    problem = InventoryProblem("github", "entry[0]", "malformed")
    service = InspectService(
        registry=FakeRegistry(()),
        git=FakeGit((), {}),
        github=FakeGitHub((), problems=(problem,)),
        runtime=FakeRuntime(),
    )
    assert problem in service.inspect().source_problems


def test_inspect_surfaces_registry_inventory_problems(tmp_path: Path) -> None:
    problem = InventoryProblem("registry", "record[0]", "malformed")
    service = InspectService(
        registry=FakeRegistry((), problems=(problem,)),
        git=FakeGit((), {}),
        github=FakeGitHub(()),
        runtime=FakeRuntime(),
    )

    assert problem in service.inspect().source_problems


def test_inspect_turns_unknown_registry_status_into_source_problem(
    tmp_path: Path,
) -> None:
    unknown = _record(tmp_path / "lane", status="legacy-migrating")
    service = InspectService(
        registry=FakeRegistry((unknown,)),
        git=FakeGit((), {}),
        github=FakeGitHub(()),
        runtime=FakeRuntime(),
    )

    inventory = service.inspect()

    assert inventory.lanes == ()
    assert inventory.source_problems == (
        InventoryProblem(
            "registry",
            "#1",
            "unsupported registry status: 'legacy-migrating'",
        ),
    )
