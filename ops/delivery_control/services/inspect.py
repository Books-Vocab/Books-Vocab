from __future__ import annotations

from pathlib import Path

from ..domain.errors import DeliverySourceError
from ..domain.inventory import DeliveryInventory, LaneInspection
from ..domain.observations import InventoryProblem
from ..domain.states import LaneFacts, derive_lane_decision
from ..ports.git import GitQueryPort
from ..ports.github import GitHubQueryPort
from ..ports.registry import RegistryQueryPort
from ..ports.runtime import AgentRuntimePort
from .inventory_sources import collect_inventory_sources
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

    def inspect(self) -> DeliveryInventory:
        sources = collect_inventory_sources(
            registry=self.registry,
            git=self.git,
            github=self.github,
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
            if physical_ref.branch == "main" and physical_ref.head_sha == local_main_sha:
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

        return DeliveryInventory(
            lanes=tuple(sorted(lanes, key=lambda item: item.key)),
            source_problems=sources.source_problems,
        )
