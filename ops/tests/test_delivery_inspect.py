from __future__ import annotations

import sys
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

OPS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPS))

from delivery_control.adapters.errors import AdapterPayloadError
from delivery_control.domain.branch_refs import BranchInventory
from delivery_control.domain.candidate_issues import (
    CANDIDATE_ISSUE_LABEL,
    CandidateIssue,
    CandidateIssueInventory,
    CandidateSeverity,
    CandidateSpec,
)
from delivery_control.domain.models import CheckStatus, HandbackReceipt, Scope
from delivery_control.domain.observations import (
    CheckSnapshot,
    FileChange,
    FileOperation,
    InventoryProblem,
    MergeQueueEntrySnapshot,
    PhysicalWorktree,
    PullRequestInventory,
    PullRequestSnapshot,
    RegistryInventory,
    RegistrySnapshot,
    WorktreeSnapshot,
)
from delivery_control.domain.states import LaneState
from delivery_control.services.active_lane_projection import (
    project_active_lane as project_active_lane_implementation,
)
from delivery_control.services.inspect import InspectService
from delivery_control.services.lane_projection import (
    project_active_lane,
    project_published_lane,
)
from delivery_control.services.pr_contract import render_pull_request_body
from delivery_control.services.published_lane_projection import (
    project_published_lane as project_published_lane_implementation,
)


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
        remote_branches: dict[str, str] | None = None,
        main_sha: str = "a" * 40,
    ) -> None:
        self.physical = physical
        self.snapshots = snapshots
        self.local_branches = local_branches or {}
        self.remote_branches = remote_branches or {}
        self.main_sha = main_sha

    def list_worktrees(self) -> tuple[PhysicalWorktree, ...]:
        return self.physical

    def inspect_worktree(self, path: Path, base_sha: str) -> WorktreeSnapshot:
        return self.snapshots[path]

    def branch_inventory(self) -> BranchInventory:
        return BranchInventory(
            local=tuple(sorted(self.local_branches.items())),
            remote=tuple(sorted(self.remote_branches.items())),
        )

    def remote_branch_sha(self, branch: str) -> str | None:
        return self.remote_branches.get(branch)

    def local_branch_sha(self, branch: str) -> str | None:
        return self.local_branches.get(branch)

    def local_main_sha(self) -> str:
        return self.main_sha

    def origin_main_sha(self) -> str:
        return self.main_sha


class FakeGitHub:
    def __init__(
        self,
        pull_requests: tuple[PullRequestSnapshot, ...],
        *,
        problems: tuple[InventoryProblem, ...] = (),
        queued_numbers: frozenset[int] = frozenset(),
        candidates: tuple[CandidateIssue, ...] = (),
        candidate_problems: tuple[InventoryProblem, ...] = (),
    ) -> None:
        self.pull_requests = pull_requests
        self.problems = problems
        self.queued_numbers = queued_numbers
        self.candidates = candidates
        self.candidate_problems = candidate_problems

    def list_open_candidate_issues(self) -> CandidateIssueInventory:
        return CandidateIssueInventory(self.candidates, self.candidate_problems)

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

    def merge_queue_entry_snapshot(
        self, pull_request_id: str
    ) -> MergeQueueEntrySnapshot | None:
        entry_id = self.merge_queue_entry_id(pull_request_id)
        if entry_id is None:
            return None
        return MergeQueueEntrySnapshot(
            entry_id,
            datetime(2026, 8, 21, tzinfo=UTC),
        )


class FakeRuntime:
    def __init__(self, status: str = "running") -> None:
        self.status = status

    def owner_status(self, thread_id: str) -> str:
        return self.status

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


def _candidate(number: int) -> CandidateIssue:
    return CandidateIssue(
        number,
        f"https://github.com/owner/repo/issues/{number}",
        CandidateSpec(
            CandidateSeverity.P2,
            number,
            Scope.from_paths(modify=(f"ops/issue_{number}.py",)),
            (f"Issue {number} is fixed.",),
        ),
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


def test_lane_projection_facade_preserves_public_imports() -> None:
    assert project_active_lane is project_active_lane_implementation
    assert project_published_lane is project_published_lane_implementation


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


def test_sealed_handback_is_publishable_when_owner_session_is_unreachable(
    tmp_path: Path,
) -> None:
    path = tmp_path / "lane"
    physical = PhysicalWorktree(path=path, head_sha="b" * 40, branch="feat/one")
    service = InspectService(
        registry=FakeRegistry((_record(path),)),
        git=FakeGit((physical,), {path: _snapshot(path)}),
        github=FakeGitHub(()),
        runtime=FakeRuntime("archived"),
    )

    active = next(item for item in service.inspect().lanes if item.key == "#1")

    assert active.decision.state is LaneState.HANDBACK_PUBLISHABLE


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


def test_inspect_service_excludes_explicit_supervision_checkout_from_delivery_collisions(
    tmp_path: Path,
) -> None:
    lane_path = tmp_path / "lane"
    supervision_path = tmp_path / "supervision"
    lane_physical = PhysicalWorktree(
        path=lane_path, head_sha="b" * 40, branch="feat/one"
    )
    supervision_physical = PhysicalWorktree(
        path=supervision_path, head_sha="b" * 40, branch=None
    )
    snapshots = {
        lane_path: _snapshot(lane_path),
        supervision_path: _snapshot(supervision_path),
    }
    service = InspectService(
        registry=FakeRegistry((_record(lane_path),)),
        git=FakeGit((lane_physical, supervision_physical), snapshots),
        github=FakeGitHub((_pull_request(lane_path),)),
        runtime=FakeRuntime(),
    )

    default_inventory = service.inspect()
    default_lane = next(item for item in default_inventory.lanes if item.key == "#1")
    assert default_lane.decision.state is LaneState.BLOCKED_COLLISION
    assert str(supervision_path.resolve()) in {
        item.key for item in default_inventory.lanes
    }

    bounded_inventory = service.inspect(supervision_worktree_paths=(supervision_path,))
    bounded_lane = next(item for item in bounded_inventory.lanes if item.key == "#1")
    assert bounded_lane.decision.state is LaneState.PUBLISHED_LOCAL_CLEANUP
    assert str(supervision_path.resolve()) not in {
        item.key for item in bounded_inventory.lanes
    }


def test_candidate_reservoir_excludes_only_nonterminal_registry_issue_refs(
    tmp_path: Path,
) -> None:
    active = replace(_record(tmp_path / "seven"), lane_id="#7", branch="feat/seven")
    published = replace(
        _record(tmp_path / "eight", status="published"),
        lane_id="https://github.com/owner/repo/issues/8",
        branch="feat/eight",
    )
    terminal = replace(
        _record(tmp_path / "nine", status="merged"),
        lane_id="Issue-9",
        branch="feat/nine",
    )
    candidates = tuple(_candidate(number) for number in range(7, 11))

    inventory = InspectService(
        registry=FakeRegistry((active, published, terminal)),
        git=FakeGit((), {}),
        github=FakeGitHub((), candidates=candidates),
        runtime=FakeRuntime(),
    ).inspect()

    assert [item.number for item in inventory.candidate_issues] == [9, 10]


def test_candidate_reservoir_checks_every_registry_external_id(
    tmp_path: Path,
) -> None:
    active = replace(
        _record(tmp_path / "seven"),
        lane_id="DIRECT-UNRELATED",
        external_ids=(
            "DIRECT-UNRELATED",
            "https://github.com/owner/repo/issues/7",
        ),
    )
    candidates = (
        _candidate(7),
        _candidate(8),
    )

    inventory = InspectService(
        registry=FakeRegistry((active,)),
        git=FakeGit((), {}),
        github=FakeGitHub((), candidates=candidates),
        runtime=FakeRuntime(),
    ).inspect()

    assert [item.number for item in inventory.candidate_issues] == [8]


def test_candidate_query_failure_is_a_source_problem(tmp_path: Path) -> None:
    class BrokenCandidateGitHub(FakeGitHub):
        def list_open_candidate_issues(self) -> CandidateIssueInventory:
            raise AdapterPayloadError("candidate payload is malformed")

    inventory = InspectService(
        registry=FakeRegistry(()),
        git=FakeGit((), {}),
        github=BrokenCandidateGitHub(()),
        runtime=FakeRuntime(),
    ).inspect()

    assert (
        InventoryProblem(
            "github", CANDIDATE_ISSUE_LABEL, "candidate payload is malformed"
        )
        in inventory.source_problems
    )
    assert inventory.candidate_issues == ()


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


def test_exact_stale_required_green_pr_is_the_only_reanchor_classification(
    tmp_path: Path,
) -> None:
    path = tmp_path / "lane"
    published = _record(path, status="published")
    service = InspectService(
        registry=FakeRegistry((published,)),
        git=FakeGit((), {}, main_sha="d" * 40),
        github=FakeGitHub((_pull_request(path),)),
        runtime=FakeRuntime(),
    )

    lane = next(
        item for item in service.inspect().lanes if item.key.startswith("published:")
    )

    assert lane.decision.state is LaneState.REANCHOR
    assert not lane.problems


def test_published_lane_uses_observed_pr_base_without_rewriting_handback_base(
    tmp_path: Path,
) -> None:
    path = tmp_path / "lane"
    published = replace(
        _record(path, status="published"),
        published_base_sha="d" * 40,
    )
    advanced = replace(_pull_request(path), base_sha="d" * 40)
    service = InspectService(
        registry=FakeRegistry((published,)),
        git=FakeGit((), {}, main_sha="e" * 40),
        github=FakeGitHub((advanced,)),
        runtime=FakeRuntime(),
    )

    lane = next(
        item for item in service.inspect().lanes if item.key.startswith("published:")
    )

    assert lane.registry is not None
    assert lane.registry.base_sha == "a" * 40
    assert lane.registry.published_base_sha == "d" * 40
    assert lane.decision.state is LaneState.REANCHOR
    assert not lane.problems


def test_scope_drift_is_not_misclassified_as_safe_reanchor(tmp_path: Path) -> None:
    class PathDriftGitHub(FakeGitHub):
        def changed_paths(self, number: int) -> tuple[str, ...]:
            return ("ops/other.py",)

    path = tmp_path / "lane"
    published = _record(path, status="published")
    service = InspectService(
        registry=FakeRegistry((published,)),
        git=FakeGit((), {}, main_sha="d" * 40),
        github=PathDriftGitHub((_pull_request(path),)),
        runtime=FakeRuntime(),
    )

    lane = next(
        item for item in service.inspect().lanes if item.key.startswith("published:")
    )

    assert lane.decision.state is LaneState.UNKNOWN
    assert any("paths differ" in problem.reason for problem in lane.problems)


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

    assert lane.decision.state is LaneState.PR_CONTRACT_FAILED
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


def test_merged_history_with_local_branch_residue_requires_terminal_cleanup(
    tmp_path: Path,
) -> None:
    path = tmp_path / "merged"
    service = InspectService(
        registry=FakeRegistry((_record(path, status="merged"),)),
        git=FakeGit((), {}, {"feat/one": "b" * 40}),
        github=FakeGitHub(()),
        runtime=FakeRuntime(),
    )

    history = next(
        item for item in service.inspect().lanes if item.key.startswith("history:")
    )

    assert history.decision.state is LaneState.TERMINAL_CLEANUP


def test_superseded_terminal_generation_does_not_claim_newer_lane_assets(
    tmp_path: Path,
) -> None:
    old_path = tmp_path / "published-old"
    new_path = tmp_path / "reanchored"
    old = replace(_record(old_path, status="abandoned"), claim_generation=3)
    current = replace(
        _record(new_path),
        claim_generation=4,
        handback_claim_generation=4,
    )
    physical = PhysicalWorktree(
        path=new_path,
        head_sha="b" * 40,
        branch="feat/one",
    )
    service = InspectService(
        registry=FakeRegistry((old, current)),
        git=FakeGit(
            (physical,),
            {new_path: _snapshot(new_path)},
            {"feat/one": "b" * 40},
            {"feat/one": "b" * 40},
        ),
        github=FakeGitHub(()),
        runtime=FakeRuntime(),
    )

    history = next(
        item for item in service.inspect().lanes if item.key == "history:#1:3"
    )

    assert history.decision.state is LaneState.DONE
    assert not history.problems


def test_merged_history_with_remote_branch_residue_requires_terminal_cleanup(
    tmp_path: Path,
) -> None:
    path = tmp_path / "merged"
    service = InspectService(
        registry=FakeRegistry((_record(path, status="merged"),)),
        git=FakeGit((), {}, remote_branches={"feat/one": "b" * 40}),
        github=FakeGitHub(()),
        runtime=FakeRuntime(),
    )

    history = next(
        item for item in service.inspect().lanes if item.key.startswith("history:")
    )

    assert history.decision.state is LaneState.TERMINAL_CLEANUP


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
