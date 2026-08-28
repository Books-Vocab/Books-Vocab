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
    InventoryProblem,
    PullRequestSnapshot,
    RegistrySnapshot,
)

_ISSUE_REF = re.compile(r"(?:#|/issues/)(?P<number>[1-9][0-9]*)\b", re.IGNORECASE)
_BARE_ISSUE_REF = re.compile(r"[1-9][0-9]*\Z")
_STRUCTURED_ISSUE_REF = re.compile(
    r"(?<![A-Z0-9])DIRECT-DELIVERY-(?:[A-Z0-9]+-)*ISSUE-"
    r"(?P<number>[1-9][0-9]*)(?=$|[^A-Z0-9])",
    re.IGNORECASE,
)
_HOLD_LABELS = {
    "delivery-hold:p0",
    "delivery-hold:p1",
    "delivery-hold:security",
    "security",
}
_HOLD_PHRASE = re.compile(
    r"\b(?:publish\s+only|security\s+hold|p0\s+hold|p1\s+hold)\b",
    re.IGNORECASE,
)
_HOLD_NEGATION = re.compile(
    r"\b(?:no|not|without|never|none|absent|missing)\b", re.IGNORECASE
)
_MALFORMED_LIVE_REGISTRY_STATUSES = frozenset({"active", "cleanup_pending"})


def _references_issue(value: str, number: int) -> bool:
    stripped = value.strip()
    if _BARE_ISSUE_REF.fullmatch(stripped):
        return int(stripped) == number
    return any(
        int(match.group("number")) == number
        for pattern in (_ISSUE_REF, _STRUCTURED_ISSUE_REF)
        for match in pattern.finditer(value)
    )


def _body_has_explicit_hold(body: str) -> bool:
    for match in _HOLD_PHRASE.finditer(body):
        line_start = body.rfind("\n", 0, match.start()) + 1
        context = body[line_start : match.start()]
        context = re.split(r"[.!?;:]\s*", context)[-1]
        if not _HOLD_NEGATION.search(context):
            return True
    return False


def _issue_is_held(issue: DemandIssue) -> bool:
    labels = {label.casefold() for label in issue.labels}
    body = issue.body.casefold()
    return (
        bool(labels & _HOLD_LABELS)
        or _body_has_explicit_hold(body)
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


def _malformed_active_registry_external_ids(
    issue: DemandIssue,
    problems: Iterable[InventoryProblem],
) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                external_id
                for problem in problems
                if problem.source == "registry"
                and problem.record_status in _MALFORMED_LIVE_REGISTRY_STATUSES
                for external_id in problem.record_external_ids
                if _references_issue(external_id, issue.number)
            }
        )
    )


def _source_problem_issue_numbers(inventory: DemandIssueInventory) -> frozenset[int]:
    """Return every Issue number implicated by a malformed raw entry.

    A duplicate raw entry is retained as ``source_entries`` while the first
    parsed record remains in ``records``.  Projection must quarantine both
    representations; otherwise the first copy could still be dispatched.
    """

    numbers = {
        entry.issue_number
        for entry in inventory.source_entries
        if entry.issue_number is not None
    }
    for problem in inventory.problems:
        identity = problem.identity
        if not identity.startswith("Issue#"):
            continue
        token = identity.removeprefix("Issue#").split("@", 1)[0]
        if token.isdigit() and int(token) > 0:
            numbers.add(int(token))
    return frozenset(numbers)


def project_demand_inventory(
    inventory: DemandIssueInventory,
    *,
    registry_records: tuple[RegistrySnapshot, ...] = (),
    pull_requests: tuple[PullRequestSnapshot, ...] = (),
    registry_problems: tuple[InventoryProblem, ...] = (),
) -> DemandIssueInventory:
    """Apply a stable precedence so every parsed Issue has one disposition."""

    source_problem_numbers = _source_problem_issue_numbers(inventory)
    projected: list[DemandIssue] = []
    for issue in inventory.records:
        mapped_records = _mapped_records(issue, registry_records)
        mapped_prs = _mapped_prs(issue, pull_requests)
        mapped_external_ids = tuple(
            external_id
            for record in mapped_records
            for external_id in (record.external_ids or (record.lane_id,))
        )
        mapped_pull_request_numbers = tuple(
            pull_request.number for pull_request in mapped_prs
        )
        malformed_active_registry_external_ids = (
            _malformed_active_registry_external_ids(issue, registry_problems)
        )
        if issue.number in source_problem_numbers:
            disposition = IssueDisposition.SOURCE_PROBLEM
            reason = "raw Issue or typed candidate payload is malformed"
        elif _issue_is_held(issue):
            disposition = IssueDisposition.SECURITY_HOLD
            reason = "Issue carries an explicit security/P0/P1 or PUBLISH ONLY hold"
        elif any(
            record.status in {"published", "cleanup_pending"}
            for record in mapped_records
        ):
            disposition = IssueDisposition.PUBLISHED_PR
            reason = "Issue is already mapped to a published delivery lane"
        elif any(
            record.status not in {"merged", "abandoned"} for record in mapped_records
        ) or any(pull_request.state == "OPEN" for pull_request in mapped_prs):
            disposition = IssueDisposition.OWNER_BOUND
            reason = "Issue is already mapped to an owner-bound registry or PR lane"
        elif (
            _issue_has_terminal_history(issue)
            or any(
                record.status in {"merged", "abandoned"} for record in mapped_records
            )
            or any(
                pull_request.state in {"MERGED", "CLOSED"}
                for pull_request in mapped_prs
            )
        ):
            disposition = IssueDisposition.TERMINAL_HISTORY
            reason = "Issue has verifiable duplicate, merged, or terminal history"
        elif issue.candidate_spec is not None and CANDIDATE_ISSUE_LABEL in issue.labels:
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
                mapped_pull_request_numbers=mapped_pull_request_numbers,
                malformed_active_registry_external_ids=(
                    malformed_active_registry_external_ids
                ),
            )
        )
    return DemandIssueInventory(
        records=tuple(projected),
        raw_count=inventory.raw_count,
        problems=inventory.problems,
        source_entries=inventory.source_entries,
        complete=inventory.complete,
    )
