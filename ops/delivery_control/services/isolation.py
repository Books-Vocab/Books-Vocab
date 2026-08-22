"""Project explicit, evidence-bounded quarantine for legacy delivery residue."""

from __future__ import annotations

from ..domain.inventory import LaneInspection
from ..domain.isolation import IsolationSummary
from ..domain.observations import InventoryProblem
from ..domain.states import LaneState
from .inventory_sources import InspectionSources
from .pr_contract import pull_request_holds

_QUARANTINABLE_BLOCKED = frozenset({LaneState.BLOCKED_OWNER, LaneState.UNKNOWN})
_TERMINAL = frozenset({"merged", "abandoned"})


def _physical_matches(problem: InventoryProblem, sources: InspectionSources) -> bool:
    identity = problem.identity
    if identity in {str(item.path.resolve()) for item in sources.physical}:
        return True
    return any(item.branch == identity for item in sources.physical)


def _open_pr_matches(problem: InventoryProblem, sources: InspectionSources) -> bool:
    identity = problem.identity
    if identity.startswith("PR#"):
        try:
            number = int(identity.removeprefix("PR#"))
        except ValueError:
            return False
        return any(
            item.number == number and item.state == "OPEN"
            for item in sources.pull_requests
        )
    return any(
        item.branch == identity and item.state == "OPEN"
        for item in sources.pull_requests
    )


def _source_problem_is_quarantinable(
    problem: InventoryProblem, sources: InspectionSources
) -> bool:
    """Only isolate registry history with no physical or open-PR activity.

    A GitHub or runtime read failure stays actionable.  A registry record that
    cannot be parsed but has neither a physical worktree nor an open PR is a
    preserved source-history problem; it cannot be advanced by a Solver in
    the current cycle and must not be mistaken for active WIP.
    """

    return (
        problem.source == "registry"
        and not _physical_matches(problem, sources)
        and not _open_pr_matches(problem, sources)
    )


def _active_missing_worktree_is_quarantinable(
    lane: LaneInspection, sources: InspectionSources
) -> bool:
    if lane.registry is None or lane.registry.status != "active":
        return False
    if lane.physical is not None or lane.pull_requests:
        return False
    # A local/remote ref is deliberately not treated as permission to delete;
    # it remains preserved evidence while the owner-recovery lane is frozen.
    return lane.decision.state in _QUARANTINABLE_BLOCKED


def _terminal_residue_is_quarantinable(lane: LaneInspection) -> bool:
    return (
        lane.registry is not None
        and lane.registry.status in _TERMINAL
        and lane.decision.state is LaneState.TERMINAL_CLEANUP
        and lane.physical is None
    )


def _unmapped_pr_is_quarantinable(
    lane: LaneInspection, sources: InspectionSources
) -> bool:
    if lane.registry is not None or lane.physical is not None:
        return False
    open_prs = tuple(item for item in lane.pull_requests if item.state == "OPEN")
    if len(open_prs) != 1:
        return False
    pull_request = open_prs[0]
    if pull_request_holds(pull_request):
        return True
    historical_branch = any(
        record.branch == pull_request.branch for record in sources.records
    )
    active_branch = any(
        record.branch == pull_request.branch
        and record.status in {"active", "published", "cleanup_pending"}
        for record in sources.records
    )
    return historical_branch and not active_branch


def project_isolation(
    *,
    sources: InspectionSources,
    lanes: tuple[LaneInspection, ...],
) -> IsolationSummary:
    quarantined_source_problems = sum(
        _source_problem_is_quarantinable(problem, sources)
        for problem in sources.source_problems
    )
    quarantined_blocked_lanes = sum(
        _active_missing_worktree_is_quarantinable(lane, sources) for lane in lanes
    )
    quarantined_open_prs = sum(
        _unmapped_pr_is_quarantinable(lane, sources) for lane in lanes
    )
    quarantined_terminal_cleanup = sum(
        _terminal_residue_is_quarantinable(lane) for lane in lanes
    )
    return IsolationSummary(
        quarantined_source_problems=quarantined_source_problems,
        quarantined_blocked_lanes=quarantined_blocked_lanes,
        quarantined_open_prs=quarantined_open_prs,
        quarantined_terminal_cleanup=quarantined_terminal_cleanup,
    )


__all__ = ["project_isolation"]
