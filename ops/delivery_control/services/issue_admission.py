"""Read-only preflight for admitting one Issue into the candidate reservoir."""

from __future__ import annotations

from collections.abc import Callable, Iterable

from ..domain.demand_issues import DemandIssue
from ..domain.errors import DeliverySourceError, PolicyViolation
from ..domain.models import Scope
from ..domain.observations import PullRequestInventory, RegistryCollisionInventory


def assert_candidate_scope_available(
    *,
    scope: Scope,
    demand_issues: Iterable[DemandIssue],
    registry: RegistryCollisionInventory,
    pull_requests: PullRequestInventory,
    changed_paths: Callable[[int], tuple[str, ...]],
) -> None:
    """Fail closed when a candidate Scope is occupied or unreadable."""

    if registry.problems:
        reasons = "; ".join(problem.reason for problem in registry.problems)
        raise DeliverySourceError(
            f"registry Scope collision inventory is incomplete: {reasons}"
        )
    if pull_requests.problems:
        reasons = "; ".join(problem.reason for problem in pull_requests.problems)
        raise DeliverySourceError(
            f"GitHub PR inventory is incomplete during Issue admission: {reasons}"
        )
    paths = set(scope.paths)
    for claim in registry.records:
        overlap = paths.intersection(claim.scope.paths)
        if overlap:
            raise PolicyViolation(
                "candidate Scope overlaps active registry lane "
                f"{claim.lane_id}: {', '.join(sorted(overlap))}"
            )
    for issue in demand_issues:
        if issue.candidate_spec is None:
            continue
        overlap = paths.intersection(issue.candidate_spec.scope.paths)
        if overlap:
            raise PolicyViolation(
                f"candidate Scope overlaps typed candidate Issue #{issue.number}: "
                f"{', '.join(sorted(overlap))}"
            )
    for pull_request in pull_requests.records:
        try:
            observed_paths = changed_paths(pull_request.number)
        except DeliverySourceError as error:
            raise DeliverySourceError(
                f"cannot read changed paths for PR #{pull_request.number}"
            ) from error
        overlap = paths.intersection(observed_paths)
        if overlap:
            raise PolicyViolation(
                f"candidate Scope overlaps open PR #{pull_request.number}: "
                f"{', '.join(sorted(overlap))}"
            )


__all__ = ["assert_candidate_scope_available"]
