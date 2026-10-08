from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

OPS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPS))

from delivery_control.adapters.github_parsing import (
    parse_demand_issue_inventory,
)
from delivery_control.domain.candidate_issues import (
    CANDIDATE_ISSUE_LABEL,
    CandidateSeverity,
    CandidateSpec,
)
from delivery_control.domain.demand_issues import IssueDisposition
from delivery_control.domain.models import HandbackReceipt, Scope
from delivery_control.domain.observations import PullRequestSnapshot
from delivery_control.services.candidate_contract import (
    render_candidate_body,
)
from delivery_control.services.demand_projection import (
    project_demand_inventory,
    terminal_history_evidence,
)
from delivery_control.services.pr_contract import (
    IssueLinks,
    render_pull_request_body,
)


def _payload(
    number: int, *, body: str, labels: tuple[str, ...] = ()
) -> dict[str, object]:
    return {
        "id": f"I_{number}",
        "number": number,
        "url": f"https://github.com/owner/repo/issues/{number}",
        "title": f"Issue {number}",
        "body": body,
        "updatedAt": "2026-08-22T01:00:00Z",
        "labels": [{"name": label} for label in labels],
    }


def _candidate_body(number: int) -> str:
    return render_candidate_body(
        CandidateSpec(
            severity=CandidateSeverity.P2,
            priority=number,
            scope=Scope.from_paths(modify=(f"ops/issue_{number}.py",)),
            acceptance=(f"Issue {number} is fixed.",),
        )
    )


def test_duplicate_raw_issue_number_quarantines_the_parsed_copy() -> None:
    raw = parse_demand_issue_inventory(
        [
            _payload(
                7,
                body=_candidate_body(7),
                labels=(CANDIDATE_ISSUE_LABEL,),
            ),
            _payload(7, body="duplicate raw entry"),
        ]
    )

    projected = project_demand_inventory(raw)

    assert projected.records[0].disposition is IssueDisposition.SOURCE_PROBLEM
    assert projected.dispatchable_candidate_issues == ()
    assert projected.disposition_counts[IssueDisposition.SOURCE_PROBLEM.value] == 2
    assert projected.unadmitted_open_issues == 2


def _receipt() -> HandbackReceipt:
    return HandbackReceipt(
        lane_id="LANE-A",
        owner_thread_id="thread-1",
        claim_generation=1,
        branch="feat/a",
        worktree_path="/tmp/a",
        base_sha="a" * 40,
        parent_sha="a" * 40,
        head_sha="b" * 40,
        origin_main_sha="d" * 40,
        content_digest="e" * 64,
        scope=Scope.from_paths(modify=("ops/a.py",)),
    )


def _delivery_pr(state: str, links: IssueLinks) -> PullRequestSnapshot:
    return PullRequestSnapshot(
        number=500,
        url="https://github.com/owner/repo/pull/500",
        branch="feat/a",
        base_sha="a" * 40,
        head_sha="b" * 40,
        state=state,
        draft=False,
        mergeable=False,
        title="feat(ops): integration",
        body=render_pull_request_body(_receipt(), issues=links),
        merged_at=datetime(2026, 8, 22, tzinfo=UTC) if state == "MERGED" else None,
    )


def _project(numbers: tuple[int, ...], pr: PullRequestSnapshot):
    raw = parse_demand_issue_inventory(
        [_payload(n, body="needs triage") for n in numbers]
    )
    return {
        record.number: record
        for record in project_demand_inventory(raw, pull_requests=(pr,)).records
    }


def test_merged_pr_refs_never_yield_completion_evidence_but_closes_does() -> None:
    pr = _delivery_pr("MERGED", IssueLinks(closes=(2026,), refs=(2027,)))

    records = _project((2026, 2027), pr)

    assert records[2026].disposition is IssueDisposition.TERMINAL_HISTORY
    assert [e.completes_issue for e in records[2026].terminal_evidence] == [True]
    assert records[2027].disposition is IssueDisposition.TRIAGE_REQUIRED
    assert records[2027].mapped_pull_request_numbers == ()
    assert records[2027].terminal_evidence == ()


def test_open_pr_refs_still_owner_bind_the_issue() -> None:
    pr = _delivery_pr("OPEN", IssueLinks(closes=(2026,), refs=(2027,)))

    records = _project((2026, 2027), pr)

    assert records[2026].disposition is IssueDisposition.OWNER_BOUND
    assert records[2027].disposition is IssueDisposition.OWNER_BOUND
    assert records[2027].mapped_pull_request_numbers == (500,)


def test_wide_integration_pr_closes_only_its_closes_set() -> None:
    closes = tuple(range(2050, 2065))
    pr = _delivery_pr("MERGED", IssueLinks(closes=closes, refs=(2026, 2045)))

    records = _project(closes + (2026, 2045), pr)

    assert {n for n, r in records.items() if r.terminal_evidence} == set(closes)
    assert terminal_history_evidence(records[2026], (), ()) == ()
