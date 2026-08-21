from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from delivery_control.adapters.errors import AdapterError
from delivery_control.domain.models import (
    InventoryProblem,
    PhysicalWorktree,
    PullRequestSnapshot,
    RegistrySnapshot,
    WorktreeSnapshot,
)
from delivery_control.domain.states import (
    CheckStatus,
    LaneDecision,
    LaneFacts,
    derive_lane_decision,
)
from delivery_control.ports.git import GitQueryPort
from delivery_control.ports.github import GitHubQueryPort
from delivery_control.ports.registry import RegistryQueryPort


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
    ) -> None:
        self.registry = registry
        self.git = git
        self.github = github

    @staticmethod
    def _colliding_lane_ids(records: tuple[RegistrySnapshot, ...]) -> set[str]:
        active = [item for item in records if item.status == "active"]
        collisions: set[str] = set()
        for index, left in enumerate(active):
            left_paths = set(left.scope.paths)
            for right in active[index + 1 :]:
                if left_paths.intersection(right.scope.paths):
                    collisions.update((left.lane_id, right.lane_id))
        return collisions

    def inspect(self) -> DeliveryInventory:
        registry_inventory = self.registry.list_records()
        records = registry_inventory.records
        physical = self.git.list_worktrees()
        pull_requests = self.github.list_open_pull_requests()
        physical_by_path = {item.path.resolve(): item for item in physical}
        prs_by_branch: dict[str, list[PullRequestSnapshot]] = {}
        for pull_request in pull_requests:
            prs_by_branch.setdefault(pull_request.branch, []).append(pull_request)
        collisions = self._colliding_lane_ids(records)
        lanes: list[LaneInspection] = []
        claimed_paths: set[Path] = set()
        claimed_prs: set[int] = set()

        for record in records:
            path = record.path.resolve()
            claimed_paths.add(path)
            physical_ref = physical_by_path.get(path)
            snapshot: WorktreeSnapshot | None = None
            problems: list[InventoryProblem] = []
            if physical_ref is not None:
                try:
                    snapshot = self.git.inspect_worktree(path, record.base_sha)
                except (AdapterError, RuntimeError) as error:
                    problems.append(InventoryProblem("git", str(path), str(error)))
            elif record.status == "active":
                problems.append(
                    InventoryProblem("git", str(path), "registered worktree is missing")
                )

            branch_prs = tuple(prs_by_branch.get(record.branch, ()))
            claimed_prs.update(item.number for item in branch_prs)
            required_status = CheckStatus.ABSENT
            if len(branch_prs) == 1:
                try:
                    required_status = self.github.required_check_status(
                        branch_prs[0].number
                    )
                except (AdapterError, RuntimeError) as error:
                    problems.append(
                        InventoryProblem(
                            "github", f"PR#{branch_prs[0].number}", str(error)
                        )
                    )
            pull_request = branch_prs[0] if len(branch_prs) == 1 else None
            merged = record.status == "merged"
            facts = LaneFacts(
                has_worktree=physical_ref is not None,
                owner_known=record.owner_thread_id is not None,
                owner_reachable=record.owner_thread_id is not None,
                dirty=(snapshot is not None and not snapshot.clean),
                has_committed_diff=(bool(snapshot.changed_paths) if snapshot else None),
                handback_valid=(record.handback_valid and snapshot is not None),
                duplicate_pr=len(branch_prs) > 1,
                scope_collision=record.lane_id in collisions,
                pr_open=pull_request is not None,
                pr_draft=(pull_request.draft if pull_request else False),
                required_status=required_status,
                mergeable=(pull_request.mergeable if pull_request else False),
                merged=merged,
                cleanup_complete=merged and physical_ref is None,
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

        for physical_ref in physical:
            path = physical_ref.path.resolve()
            if path in claimed_paths:
                continue
            branch_prs = tuple(prs_by_branch.get(physical_ref.branch or "", ()))
            claimed_prs.update(item.number for item in branch_prs)
            lanes.append(
                LaneInspection(
                    key=str(path),
                    registry=None,
                    physical=physical_ref,
                    snapshot=None,
                    pull_requests=branch_prs,
                    decision=derive_lane_decision(
                        LaneFacts(
                            has_worktree=True,
                            owner_known=False,
                            duplicate_pr=len(branch_prs) > 1,
                            pr_open=len(branch_prs) == 1,
                            pr_draft=branch_prs[0].draft
                            if len(branch_prs) == 1
                            else False,
                        )
                    ),
                    problems=(
                        InventoryProblem(
                            "registry", str(path), "physical worktree is unregistered"
                        ),
                    ),
                )
            )

        for pull_request in pull_requests:
            if pull_request.number in claimed_prs:
                continue
            try:
                required_status = self.github.required_check_status(pull_request.number)
            except (AdapterError, RuntimeError):
                required_status = CheckStatus.ABSENT
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
                            required_status=required_status,
                            mergeable=pull_request.mergeable,
                        )
                    ),
                    problems=(
                        InventoryProblem(
                            "registry",
                            f"PR#{pull_request.number}",
                            "open PR has no local registry mapping",
                        ),
                    ),
                )
            )

        return DeliveryInventory(
            lanes=tuple(sorted(lanes, key=lambda item: item.key)),
            source_problems=registry_inventory.problems,
        )
