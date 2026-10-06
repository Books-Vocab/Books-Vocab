"""Close open Issues whose delivery history is verifiably terminal.

Eligibility is not re-derived here: an Issue is a candidate only when the
shared demand projection assigned ``terminal_history`` and attached the exact
facts it used.  Closing as completed additionally requires completion-grade
evidence (merged PR, merged lane, or a duplicate/terminal label); an abandoned
lane or an unmerged closed PR is history but not completion, so it is skipped
and reported instead of being closed with a false reason.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, runtime_checkable
from datetime import datetime

from ..domain.demand_issues import (
    DemandIssue,
    DemandIssueInventory,
    IssueCloseReceipt,
    IssueDisposition,
    TerminalEvidence,
)
from ..domain.errors import (
    DeliveryContractError,
    DeliverySourceError,
    PolicyViolation,
)

TERMINAL_CLOSE_MARKER = "<!-- kg.delivery.issue-terminal-close.v1 -->"
_COUNT_KEYS = ("would-close", "skipped", "closed", "already-closed", "failed")


@runtime_checkable
class IssueCloseCommandPort(Protocol):
    def close_issue(
        self,
        *,
        issue_number: int,
        expected_updated_at: datetime | None,
        expected_body_sha256: str,
        comment: str,
    ) -> IssueCloseReceipt: ...


@dataclass(frozen=True)
class TerminalCloseItem:
    number: int
    status: str
    reason: str
    url: str | None = None
    title: str | None = None
    evidence: tuple[TerminalEvidence, ...] = ()
    comment: str | None = None
    error: str | None = None
    state_reason: str | None = None


@dataclass(frozen=True)
class TerminalCloseReport:
    verdict: str
    mode: str
    complete: bool
    counts: dict[str, int]
    items: tuple[TerminalCloseItem, ...]
    source_problems: tuple[str, ...] = ()


def render_close_comment(issue: DemandIssue, *, operator: str) -> str:
    lines = [
        TERMINAL_CLOSE_MARKER,
        "Closing as completed: this Issue's delivery history is terminal.",
        "",
        "Evidence:",
    ]
    for item in issue.terminal_evidence:
        if not item.completes_issue:
            continue
        suffix = f": {item.url}" if item.url else ""
        lines.append(f"- {item.kind.value} {item.ref}{suffix}")
    lines.extend(
        [
            "",
            f"Closed by the delivery controller (operator: {operator}). "
            "Reopen this Issue if the evidence is wrong.",
        ]
    )
    return "\n".join(lines)


class IssueTerminalCloseService:
    def __init__(
        self,
        *,
        inventory: Callable[[], DemandIssueInventory],
        issues: IssueCloseCommandPort,
    ) -> None:
        self.inventory = inventory
        self.issues = issues

    @staticmethod
    def _skip_reason(issue: DemandIssue) -> str | None:
        if not any(item.completes_issue for item in issue.terminal_evidence):
            return (
                "terminal history has no merged PR, merged lane, or "
                "duplicate/terminal label (an abandoned lane or unmerged closed "
                "PR is not completion evidence)"
            )
        return None

    def run(
        self,
        *,
        apply: bool,
        issue_numbers: tuple[int, ...] = (),
        operator: str | None = None,
        progress: Callable[[str], None] | None = None,
    ) -> TerminalCloseReport:
        say = progress or (lambda _message: None)
        if apply and not (operator and operator.strip()):
            raise DeliveryContractError("--apply requires a non-empty --operator")
        say("reading open Issue inventory")
        inventory = self.inventory()
        if apply and not inventory.complete:
            raise PolicyViolation(
                "Issue inventory is incomplete; refusing to close Issues from "
                "a partial source"
            )
        label = (operator or "<operator>").strip()
        by_number = {item.number: item for item in inventory.records}
        wanted = tuple(sorted(set(issue_numbers)))
        if wanted:
            selected = wanted
        else:
            selected = tuple(
                item.number
                for item in inventory.records
                if item.disposition is IssueDisposition.TERMINAL_HISTORY
            )

        items: list[TerminalCloseItem] = []
        for number in selected:
            issue = by_number.get(number)
            if issue is None:
                items.append(TerminalCloseItem(number, "skipped", "not an open Issue"))
                continue
            if issue.disposition is not IssueDisposition.TERMINAL_HISTORY:
                items.append(
                    TerminalCloseItem(
                        number,
                        "skipped",
                        f"disposition is {issue.disposition.value}, "
                        "not terminal_history",
                        url=issue.url,
                        title=issue.title,
                    )
                )
                continue
            skip = self._skip_reason(issue)
            if skip is not None:
                items.append(
                    TerminalCloseItem(
                        number,
                        "skipped",
                        skip,
                        url=issue.url,
                        title=issue.title,
                        evidence=issue.terminal_evidence,
                    )
                )
                continue
            comment = render_close_comment(issue, operator=label)
            base = {
                "url": issue.url,
                "title": issue.title,
                "evidence": issue.terminal_evidence,
                "comment": comment,
            }
            if not apply:
                items.append(
                    TerminalCloseItem(
                        number,
                        "would-close",
                        issue.reason,
                        **base,  # type: ignore[arg-type]
                    )
                )
                continue
            say(f"closing Issue #{number}")
            try:
                receipt = self.issues.close_issue(
                    issue_number=number,
                    expected_updated_at=issue.updated_at,
                    expected_body_sha256=issue.body_sha256,
                    comment=comment,
                )
                if receipt.number != number or receipt.state != "CLOSED":
                    raise DeliverySourceError(
                        f"Issue #{number} did not read back as CLOSED"
                    )
            except (DeliverySourceError, OSError) as error:
                items.append(
                    TerminalCloseItem(
                        number,
                        "failed",
                        issue.reason,
                        error=str(error),
                        **base,  # type: ignore[arg-type]
                    )
                )
                continue
            items.append(
                TerminalCloseItem(
                    number,
                    "already-closed" if receipt.already_closed else "closed",
                    issue.reason,
                    state_reason=receipt.state_reason,
                    **base,  # type: ignore[arg-type]
                )
            )

        counts = dict.fromkeys(_COUNT_KEYS, 0)
        for item in items:
            counts[item.status] += 1
        if not inventory.complete:
            verdict = "blocked"
        elif not apply:
            verdict = "dry-run"
        elif counts["failed"]:
            verdict = "partial-failure"
        elif counts["closed"] + counts["already-closed"] == 0:
            verdict = "nothing-to-close"
        else:
            verdict = "closed"
        return TerminalCloseReport(
            verdict=verdict,
            mode="apply" if apply else "dry-run",
            complete=inventory.complete,
            counts=counts,
            items=tuple(items),
            source_problems=tuple(
                f"{problem.source}:{problem.identity}: {problem.reason}"
                for problem in inventory.problems
            ),
        )


__all__ = [
    "IssueCloseCommandPort",
    "IssueTerminalCloseService",
    "TERMINAL_CLOSE_MARKER",
    "TerminalCloseItem",
    "TerminalCloseReport",
    "render_close_comment",
]
