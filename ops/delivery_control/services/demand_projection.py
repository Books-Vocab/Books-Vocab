"""Classify raw open Issues without creating a second lifecycle database."""

from __future__ import annotations

import re
from collections.abc import Iterable

from ..domain.candidate_issues import CANDIDATE_ISSUE_LABEL
from ..domain.demand_issues import (
    DemandIssue,
    DemandIssueInventory,
    IssueDisposition,
)
from ..domain.observations import (
    PullRequestSnapshot,
    RegistrySnapshot,
)

_ISSUE_REF = re.compile(r"(?:#|/issues/)(?P<number>[1-9][0-9]*)\b", re.IGNORECASE)
_HOLD_LABELS = {
    "delivery-hold:p0",
    "delivery-hold:p1",
    "delivery-hold:security",
    "security",
}


def _references_issue(value: str, number: int) -> bool:
    return any(int(match.group("number")) == number for match in _ISSUE_REF.finditer(value))


def _issue_is_held(issue: DemandIssue) -> bool:
    labels = {label.casefold() for label in issue.labels}
    body = issue.body.casefold()
    return (
        bool(labels & _HOLD_LABELS)
        or "publish only" in body
        or "security hold" in body
        or "p0 hold" in body
        or "p1 hold" in body
        or (
            issue.candidate_spec is not None
            and bool(issue.candidate_spec.initial_holds)
        )
    )


def _issue_has_terminal_history(issue: DemandIssue) -> bool:
    labels = {label.casefold() for label in issue.labels}
    return bool(
        labels
        & {
            "duplicate",
            "duplicate-of",
            "delivery:terminal",
            "terminal",
            "merged",
        }
    )


def _mapped_records(
    issue: DemandIssue,
    records: Iterable[RegistrySnapshot],
) -> tuple[RegistrySnapshot, ...]:
    matches: list[RegistrySnapshot] = []
    for record in records:
        references = record.external_ids or (record.lane_id,)
        if any(_references_issue(reference, issue.number) for reference in references):
            matches.append(record)
    return tuple(matches)


def _mapped_prs(
    issue: DemandIssue,
    pull_requests: Iterable[PullRequestSnapshot],
) -> tuple[PullRequestSnapshot, ...]:
    return tuple(
        pull_request
        for pull_request in pull_requests
        if _references_issue(pull_request.title, issue.number)
        or _references_issue(pull_request.body, issue.number)
    )


def project_demand_inventory(
    inventory: DemandIssueInventory,
    *,
    registry_records: tuple[RegistrySnapshot, ...] = (),
    pull_requests: tuple[PullRequestSnapshot, ...] = (),
) -> DemandIssueInventory:
    """Apply a stable precedence so every parsed Issue has one disposition."""

    source_problem_ids = {problem.identity for problem in inventory.problems}
    projected: list[DemandIssue] = []
    for issue in inventory.records:
        mapped_records = _mapped_records(issue, registry_records)
        mapped_prs = _mapped_prs(issue, pull_requests)
        mapped_external_ids = tuple(
            external_id
            for record in mapped_records
            for external_id in (record.external_ids or (record.lane_id,))
        )
        identity = f"Issue#{issue.number}"
        if identity in source_problem_ids:
            disposition = IssueDisposition.SOURCE_PROBLEM
            reason = "raw Issue or typed candidate payload is malformed"
        elif _issue_is_held(issue):
            disposition = IssueDisposition.SECURITY_HOLD
            reason = "Issue carries an explicit security/P0/P1 or PUBLISH ONLY hold"
        elif any(record.status in {"published", "cleanup_pending"} for record in mapped_records):
            disposition = IssueDisposition.PUBLISHED_PR
            reason = "Issue is already mapped to a published delivery lane"
        elif any(record.status not in {"merged", "abandoned"} for record in mapped_records) or any(
            pull_request.state == "OPEN" for pull_request in mapped_prs
        ):
            disposition = IssueDisposition.OWNER_BOUND
            reason = "Issue is already mapped to an owner-bound registry or PR lane"
        elif _issue_has_terminal_history(issue) or any(
            record.status in {"merged", "abandoned"} for record in mapped_records
        ) or any(
            pull_request.state in {"MERGED", "CLOSED"} for pull_request in mapped_prs
        ):
            disposition = IssueDisposition.TERMINAL_HISTORY
            reason = "Issue has verifiable duplicate, merged, or terminal history"
        elif (
            issue.candidate_spec is not None
            and CANDIDATE_ISSUE_LABEL in issue.labels
        ):
            disposition = IssueDisposition.DISPATCHABLE_CANDIDATE
            reason = "Issue has an exact typed candidate contract and no active mapping"
        else:
            labels = {label.casefold() for label in issue.labels}
            if "blocked" in labels or "macos-capacity" in labels:
                disposition = IssueDisposition.BLOCKED
                reason = "Issue is explicitly blocked or capacity constrained"
            elif "legacy-ticket" in labels:
                disposition = IssueDisposition.LEGACY_UNMAPPED
                reason = "legacy Issue needs explicit migration evidence"
            else:
                disposition = IssueDisposition.TRIAGE_REQUIRED
                reason = "Issue has no exact candidate contract or owner mapping"
        projected.append(
            DemandIssue(
                number=issue.number,
                url=issue.url,
                node_id=issue.node_id,
                title=issue.title,
                labels=issue.labels,
                body=issue.body,
                updated_at=issue.updated_at,
                body_sha256=issue.body_sha256,
                disposition=disposition,
                reason=reason,
                candidate_spec=issue.candidate_spec,
                mapped_external_ids=mapped_external_ids,
            )
        )
    return DemandIssueInventory(
        records=tuple(projected),
        raw_count=inventory.raw_count,
        problems=inventory.problems,
        source_entries=inventory.source_entries,
        complete=inventory.complete,
    )
