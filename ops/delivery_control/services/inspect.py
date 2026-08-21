from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..domain.errors import DeliverySourceError
from ..domain.models import CheckStatus
from ..domain.observations import (
    InventoryProblem,
    PhysicalWorktree,
    PullRequestSnapshot,
    RegistrySnapshot,
    WorktreeSnapshot,
)
from ..domain.states import LaneDecision, LaneFacts, derive_lane_decision
from ..ports.git import GitQueryPort
from ..ports.github import GitHubQueryPort
from ..ports.registry import RegistryQueryPort
from ..ports.runtime import AgentRuntimePort
from .correlation import (
    collision_keys,
    has_explicit_hold,
    inspect_registered,
    owner_reachable,
    scope_matches_snapshot,
)

_ACTIVE = "active"
_TERMINAL = {"merged", "abandoned"}


@dataclass(frozen=True)
class LaneInspection:
    key: str
    registry: RegistrySnapshot | None
    physical: PhysicalWorktree | None
    snapshot: WorktreeSnapshot | None
    pull_requests: tuple[PullRequestSnapshot, ...]
    decision: LaneDecision
    problems: tuple[InventoryProblem, ...] = ()


@dataclass(frozen=True)
class DeliveryInventory:
    lanes: tuple[LaneInspection, ...]
    source_problems: tuple[InventoryProblem, ...] = ()


class InspectService:
    def __init__(
        self,
        *,
        registry: RegistryQueryPort,
        git: GitQueryPort,
        github: GitHubQueryPort,
        runtime: AgentRuntimePort,
    ) -> None:
        self.registry = registry
        self.git = git
        self.github = github
        self.runtime = runtime

    def inspect(self) -> DeliveryInventory:
        registry_inventory = self.registry.list_records()
        physical = self.git.list_worktrees()
        github_inventory = self.github.list_open_pull_requests()
        live_main_sha = self.git.origin_main_sha()
        records = registry_inventory.records
        active_records = tuple(item for item in records if item.status == _ACTIVE)
        physical_by_path = {item.path.resolve(): item for item in physical}
        prs_by_branch: dict[str, list[PullRequestSnapshot]] = {}
        for pull_request in github_inventory.records:
            prs_by_branch.setdefault(pull_request.branch, []).append(pull_request)

        snapshots: dict[str, WorktreeSnapshot | None] = {}
        lane_problems: dict[str, list[InventoryProblem]] = {
            item.lane_id: [] for item in active_records
        }
        pr_paths: dict[int, tuple[str, ...]] = {}
        github_problems = list(github_inventory.problems)
        for record in active_records:
            snapshots[record.lane_id] = inspect_registered(
                self.git,
                record,
                physical_by_path.get(record.path.resolve()),
                lane_problems[record.lane_id],
            )
        for pull_request in github_inventory.records:
            try:
                pr_paths[pull_request.number] = self.github.changed_paths(
                    pull_request.number
                )
            except DeliverySourceError as error:
                pr_paths[pull_request.number] = ()
                github_problems.append(
                    InventoryProblem("github", f"PR#{pull_request.number}", str(error))
                )

        path_sets: dict[str, set[str]] = {}
        for record in active_records:
            observed = set(record.scope.paths)
            snapshot = snapshots[record.lane_id]
            if snapshot is not None:
                observed.update(snapshot.changed_paths)
            for pull_request in prs_by_branch.get(record.branch, ()):
                observed.update(pr_paths.get(pull_request.number, ()))
            path_sets[f"lane:{record.lane_id}"] = observed
        active_branches = {item.branch for item in active_records}
        active_paths = {item.path.resolve() for item in active_records}
        for pull_request in github_inventory.records:
            if pull_request.branch not in active_branches:
                path_sets[f"pr:{pull_request.number}"] = set(
                    pr_paths.get(pull_request.number, ())
                )
        for physical_ref in physical:
            path = physical_ref.path.resolve()
            if path not in active_paths:
                try:
                    snapshot = self.git.inspect_worktree(path, live_main_sha)
                except DeliverySourceError:
                    continue
                path_sets[f"worktree:{path}"] = set(snapshot.changed_paths)
        collisions = collision_keys(path_sets)

        lanes: list[LaneInspection] = []
        claimed_paths: set[Path] = set()
        claimed_prs: set[int] = set()
        for record in active_records:
            path = record.path.resolve()
            claimed_paths.add(path)
            physical_ref = physical_by_path.get(path)
            snapshot = snapshots[record.lane_id]
            problems = lane_problems[record.lane_id]
            branch_prs = tuple(prs_by_branch.get(record.branch, ()))
            claimed_prs.update(item.number for item in branch_prs)
            pull_request = branch_prs[0] if len(branch_prs) == 1 else None
            is_owner_reachable = owner_reachable(self.runtime, record, problems)
            check = None
            if pull_request is not None:
                try:
                    check = self.github.required_check_snapshot(pull_request.number)
                except DeliverySourceError as error:
                    problems.append(
                        InventoryProblem(
                            "github", f"PR#{pull_request.number}", str(error)
                        )
                    )
            lane_collision = f"lane:{record.lane_id}" in collisions
            scope_exact = snapshot is not None and scope_matches_snapshot(
                record, snapshot
            )
            if snapshot is not None and not scope_exact:
                problems.append(
                    InventoryProblem(
                        "git",
                        str(path),
                        "physical operations or paths differ from Scope",
                    )
                )
            if pull_request is not None:
                if pull_request.base_sha != record.base_sha:
                    problems.append(
                        InventoryProblem(
                            "github",
                            f"PR#{pull_request.number}",
                            "PR base differs from registry base",
                        )
                    )
                if snapshot is None or pull_request.head_sha != snapshot.head_sha:
                    problems.append(
                        InventoryProblem(
                            "github",
                            f"PR#{pull_request.number}",
                            "PR HEAD differs from physical HEAD",
                        )
                    )
                if record.handed_back_sha != pull_request.head_sha:
                    problems.append(
                        InventoryProblem(
                            "github",
                            f"PR#{pull_request.number}",
                            "PR HEAD differs from registry handback",
                        )
                    )
            transport_exact = (
                not problems
                and not lane_collision
                and len(branch_prs) <= 1
                and is_owner_reachable
                and snapshot is not None
                and snapshot.clean
                and snapshot.path.resolve() == path
                and snapshot.branch == record.branch
                and snapshot.base_sha == record.base_sha
                and scope_exact
                and record.handback_valid
                and record.handed_back_sha == snapshot.head_sha
                and record.handback_claim_generation == record.claim_generation
            )
            merge_exact = (
                transport_exact
                and pull_request is not None
                and pull_request.state == "OPEN"
                and not pull_request.draft
                and pull_request.mergeable
                and pull_request.base_sha == live_main_sha == record.base_sha
                and pull_request.head_sha == snapshot.head_sha
                and check is not None
                and check.head_sha == pull_request.head_sha
                and check.status is CheckStatus.SUCCESS
                and not has_explicit_hold(pull_request)
            )
            facts = LaneFacts(
                has_worktree=physical_ref is not None,
                owner_known=record.owner_thread_id is not None,
                owner_reachable=is_owner_reachable,
                dirty=snapshot is not None and not snapshot.clean,
                has_committed_diff=bool(snapshot.changes) if snapshot else None,
                handback_valid=record.handback_valid,
                transport_policy_passed=transport_exact and pull_request is None,
                merge_policy_passed=merge_exact,
                abandonment_policy_passed=(
                    not problems
                    and snapshot is not None
                    and snapshot.clean
                    and not snapshot.changes
                    and is_owner_reachable
                    and not branch_prs
                ),
                duplicate_pr=len(branch_prs) > 1,
                scope_collision=lane_collision,
                pr_open=pull_request is not None,
                pr_draft=pull_request.draft if pull_request else False,
                required_status=check.status if check else CheckStatus.ABSENT,
                mergeable=pull_request.mergeable if pull_request else False,
                holds=frozenset(),
            )
            lanes.append(
                LaneInspection(
                    key=record.lane_id,
                    registry=record,
                    physical=physical_ref,
                    snapshot=snapshot,
                    pull_requests=branch_prs,
                    decision=derive_lane_decision(facts),
                    problems=tuple(problems),
                )
            )

        for record in records:
            if record.status not in _TERMINAL:
                continue
            physical_ref = physical_by_path.get(record.path.resolve())
            terminal_problems: tuple[InventoryProblem, ...] = ()
            if physical_ref is not None and record.path.resolve() not in claimed_paths:
                terminal_problems = (
                    InventoryProblem(
                        "registry",
                        str(record.path),
                        "terminal history cannot claim a physical worktree",
                    ),
                )
            lanes.append(
                LaneInspection(
                    key=f"history:{record.lane_id}:{record.claim_generation}",
                    registry=record,
                    physical=None,
                    snapshot=None,
                    pull_requests=(),
                    decision=derive_lane_decision(
                        LaneFacts(
                            merged=record.status == "merged",
                            cleanup_complete=physical_ref is None,
                        )
                    ),
                    problems=terminal_problems,
                )
            )

        for physical_ref in physical:
            path = physical_ref.path.resolve()
            if path in claimed_paths:
                continue
            branch_prs = tuple(prs_by_branch.get(physical_ref.branch or "", ()))
            claimed_prs.update(item.number for item in branch_prs)
            problems = [
                InventoryProblem(
                    "registry", str(path), "physical worktree is unregistered"
                )
            ]
            snapshot = None
            try:
                snapshot = self.git.inspect_worktree(path, live_main_sha)
            except DeliverySourceError as error:
                problems.append(InventoryProblem("git", str(path), str(error)))
            lanes.append(
                LaneInspection(
                    key=str(path),
                    registry=None,
                    physical=physical_ref,
                    snapshot=snapshot,
                    pull_requests=branch_prs,
                    decision=derive_lane_decision(
                        LaneFacts(
                            has_worktree=True,
                            owner_known=False,
                            dirty=snapshot is not None and not snapshot.clean,
                            duplicate_pr=len(branch_prs) > 1,
                            scope_collision=f"worktree:{path}" in collisions,
                            pr_open=len(branch_prs) == 1,
                            pr_draft=branch_prs[0].draft
                            if len(branch_prs) == 1
                            else False,
                        )
                    ),
                    problems=tuple(problems),
                )
            )

        for pull_request in github_inventory.records:
            if pull_request.number in claimed_prs:
                continue
            problems = (
                InventoryProblem(
                    "registry",
                    f"PR#{pull_request.number}",
                    "open PR has no active local registry mapping",
                ),
            )
            lanes.append(
                LaneInspection(
                    key=f"PR#{pull_request.number}",
                    registry=None,
                    physical=None,
                    snapshot=None,
                    pull_requests=(pull_request,),
                    decision=derive_lane_decision(
                        LaneFacts(
                            pr_open=True,
                            pr_draft=pull_request.draft,
                            scope_collision=f"pr:{pull_request.number}" in collisions,
                        )
                    ),
                    problems=problems,
                )
            )

        return DeliveryInventory(
            lanes=tuple(sorted(lanes, key=lambda item: item.key)),
            source_problems=registry_inventory.problems + tuple(github_problems),
        )
