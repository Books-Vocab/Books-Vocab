from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from ..domain.errors import DeliverySourceError
from ..domain.inventory import DeliveryInventory, LaneInspection
from ..domain.observations import InventoryProblem, WorktreeSnapshot
from ..domain.states import LaneFacts, derive_lane_decision
from ..ports.git import GitQueryPort
from ..ports.github import GitHubQueryPort
from ..ports.registry import RegistryQueryPort
from ..ports.runtime import AgentRuntimePort
from .correlation import collision_keys, delivery_collision_path_sets
from .inventory_sources import InspectionSources, collect_inventory_sources
from .isolation import project_isolation
from .lane_projection import project_active_lane, project_published_lane

_TERMINAL = {"merged", "abandoned"}


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

    def inspect(
        self, *, supervision_worktree_paths: tuple[Path, ...] = ()
    ) -> DeliveryInventory:
        sources = collect_inventory_sources(
            registry=self.registry,
            git=self.git,
            github=self.github,
        )
        if supervision_worktree_paths:
            sources = self._apply_supervision_boundary(
                sources, supervision_worktree_paths
            )
        records = sources.records
        active_records = sources.active_records
        published_records = sources.published_records
        physical = sources.physical
        live_main_sha = sources.live_main_sha
        local_main_sha = sources.local_main_sha
        physical_by_path = sources.physical_by_path
        prs_by_branch = sources.prs_by_branch
        collisions = sources.collisions

        lanes: list[LaneInspection] = []
        claimed_paths: set[Path] = set()
        claimed_prs: set[int] = set()
        for record in active_records:
            path = record.path.resolve()
            claimed_paths.add(path)
            lane = project_active_lane(
                sources=sources,
                record=record,
                github=self.github,
                runtime=self.runtime,
            )
            claimed_prs.update(item.number for item in lane.pull_requests)
            lanes.append(lane)

        for record in published_records:
            path = record.path.resolve()
            if physical_by_path.get(path) is not None:
                claimed_paths.add(path)
            lane = project_published_lane(
                sources=sources,
                record=record,
                git=self.git,
                github=self.github,
            )
            claimed_prs.update(item.number for item in lane.pull_requests)
            lanes.append(lane)

        for record in records:
            if record.status not in _TERMINAL:
                continue
            physical_ref = physical_by_path.get(record.path.resolve())
            newer_records = tuple(
                candidate
                for candidate in records
                if candidate.claim_generation > record.claim_generation
            )
            branch_reclaimed = any(
                candidate.branch == record.branch for candidate in newer_records
            )
            path_reclaimed = any(
                candidate.path.resolve() == record.path.resolve()
                for candidate in newer_records
            )
            has_local_branch = (
                not branch_reclaimed
                and record.branch in sources.branch_inventory.local_by_name
            )
            has_remote_branch = (
                not branch_reclaimed
                and record.branch in sources.branch_inventory.remote_by_name
            )
            terminal_assets_present = (
                (physical_ref is not None and not path_reclaimed)
                or has_local_branch
                or has_remote_branch
            )
            terminal_problems: tuple[InventoryProblem, ...] = ()
            if (
                physical_ref is not None
                and not path_reclaimed
                and record.path.resolve() not in claimed_paths
            ):
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
                            abandoned=record.status == "abandoned",
                            cleanup_policy_passed=terminal_assets_present,
                            cleanup_complete=not terminal_assets_present,
                        )
                    ),
                    problems=terminal_problems,
                )
            )

        for physical_ref in physical:
            if (
                physical_ref.branch == "main"
                and physical_ref.head_sha == local_main_sha
            ):
                continue
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

        for pull_request in sources.pull_requests:
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
                            scope_collision=f"pr:{pull_request.number}" in collisions,
                        )
                    ),
                    problems=problems,
                )
            )

        inventory = DeliveryInventory(
            lanes=tuple(sorted(lanes, key=lambda item: item.key)),
            source_problems=sources.source_problems,
            candidate_issues=sources.candidate_issues,
            dispatchable_candidate_issues=sources.dispatchable_candidate_issues,
            demand_issues=sources.demand_issues,
        )
        return DeliveryInventory(
            lanes=inventory.lanes,
            source_problems=inventory.source_problems,
            candidate_issues=inventory.candidate_issues,
            dispatchable_candidate_issues=inventory.dispatchable_candidate_issues,
            demand_issues=inventory.demand_issues,
            isolation=project_isolation(sources=sources, lanes=inventory.lanes),
        )

    def _apply_supervision_boundary(
        self,
        sources: InspectionSources,
        supervision_worktree_paths: tuple[Path, ...],
    ) -> InspectionSources:
        excluded_paths = frozenset(
            path.expanduser().resolve() for path in supervision_worktree_paths
        )
        physical = tuple(
            item
            for item in sources.physical
            if item.path.resolve() not in excluded_paths
        )
        working_paths = {
            item.path.resolve()
            for item in (*sources.active_records, *sources.published_records)
        }
        unregistered_snapshots: dict[Path, WorktreeSnapshot | None] = {}
        for physical_ref in physical:
            path = physical_ref.path.resolve()
            if path in working_paths:
                continue
            if (
                physical_ref.branch == "main"
                and physical_ref.head_sha == sources.local_main_sha
            ):
                continue
            try:
                unregistered_snapshots[path] = self.git.inspect_worktree(
                    path, sources.live_main_sha
                )
            except DeliverySourceError:
                unregistered_snapshots[path] = None
        path_sets = delivery_collision_path_sets(
            active_records=sources.active_records,
            published_records=sources.published_records,
            physical=physical,
            snapshots=sources.snapshots,
            prs_by_branch=sources.prs_by_branch,
            pr_paths=sources.pr_paths,
            local_main_sha=sources.local_main_sha,
            excluded_physical_paths=excluded_paths,
            unregistered_snapshots=unregistered_snapshots,
        )
        return replace(
            sources,
            physical=physical,
            collisions=frozenset(collision_keys(path_sets)),
        )
