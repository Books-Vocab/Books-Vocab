"""Read-only preflight for admitting one Issue into the candidate reservoir."""

from __future__ import annotations

from collections.abc import Callable, Iterable

from lib.worktree_scope import overlap_paths

from ..domain.demand_issues import (
    DemandIssue,
    IssueDisposition,
    IssueIntakeRequest,
    issue_intake_fingerprint,
)
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
        overlap = overlap_paths(paths, claim.scope.paths)
        if overlap:
            raise PolicyViolation(
                "candidate Scope overlaps active registry lane "
                f"{claim.lane_id}: {', '.join(sorted(overlap))}"
            )
    for issue in demand_issues:
        if (
            issue.candidate_spec is None
            or issue.disposition is IssueDisposition.TERMINAL_HISTORY
        ):
            continue
        overlap = overlap_paths(paths, issue.candidate_spec.scope.paths)
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
        overlap = overlap_paths(paths, observed_paths)
        if overlap:
            raise PolicyViolation(
                f"candidate Scope overlaps open PR #{pull_request.number}: "
                f"{', '.join(sorted(overlap))}"
            )


def _title_key(title: str) -> str:
    return " ".join(title.split()).casefold()


def assert_issue_intake_available(
    *,
    request: IssueIntakeRequest,
    demand_issues: tuple[DemandIssue, ...],
    registry: RegistryCollisionInventory,
    pull_requests: PullRequestInventory,
    changed_paths: Callable[[int], tuple[str, ...]],
) -> None:
    """Authorize one raw Issue create without admitting a candidate."""

    if request.has_security_hold:
        raise PolicyViolation(
            "raw Issue intake is held by an explicit security/PUBLISH ONLY signal"
        )
    if registry.problems:
        reasons = "; ".join(problem.reason for problem in registry.problems)
        raise DeliverySourceError(
            f"registry Scope collision inventory is incomplete: {reasons}"
        )
    if pull_requests.problems:
        reasons = "; ".join(problem.reason for problem in pull_requests.problems)
        raise DeliverySourceError(
            f"GitHub PR inventory is incomplete during Issue intake: {reasons}"
        )

    for issue in demand_issues:
        if issue_intake_fingerprint(issue.body) == request.source_fingerprint:
            raise PolicyViolation(
                f"raw Issue intake source fingerprint already exists at Issue #{issue.number}"
            )

    # A twin with a different body would otherwise slip past the fingerprint,
    # and a fix could then close only one of the two issues (#2654).
    title = _title_key(request.title)
    for issue in demand_issues:
        if _title_key(issue.title) == title:
            raise PolicyViolation(
                f"raw Issue intake title duplicates open Issue #{issue.number}; "
                "update that Issue instead of filing a twin"
            )

    paths = set(request.scope.paths)
    for claim in registry.records:
        if request.provenance in {claim.lane_id, claim.branch}:
            raise PolicyViolation(
                "raw Issue intake provenance collides with active registry lane "
                f"{claim.lane_id}"
            )
        overlap = overlap_paths(paths, claim.scope.paths)
        if overlap:
            raise PolicyViolation(
                "raw Issue intake Scope overlaps active registry lane "
                f"{claim.lane_id}: {', '.join(sorted(overlap))}"
            )

    for issue in demand_issues:
        if issue.candidate_spec is None:
            continue
        overlap = overlap_paths(paths, issue.candidate_spec.scope.paths)
        if overlap:
            raise PolicyViolation(
                f"raw Issue intake Scope overlaps typed candidate Issue #{issue.number}: "
                f"{', '.join(sorted(overlap))}"
            )

    for pull_request in pull_requests.records:
        if request.provenance == pull_request.branch:
            raise PolicyViolation(
                "raw Issue intake provenance collides with open PR "
                f"#{pull_request.number}"
            )
        try:
            observed_paths = changed_paths(pull_request.number)
        except DeliverySourceError as error:
            raise DeliverySourceError(
                f"cannot read changed paths for PR #{pull_request.number} during Issue intake"
            ) from error
        overlap = overlap_paths(paths, observed_paths)
        if overlap:
            raise PolicyViolation(
                f"raw Issue intake Scope overlaps open PR #{pull_request.number}: "
                f"{', '.join(sorted(overlap))}"
            )


__all__ = ["assert_candidate_scope_available", "assert_issue_intake_available"]
