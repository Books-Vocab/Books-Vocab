from __future__ import annotations

import sys
from pathlib import Path

OPS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPS))

from delivery_control.adapters.github_parsing import parse_demand_issue_inventory
from delivery_control.domain.candidate_issues import (
    CANDIDATE_ISSUE_LABEL,
    CandidateSeverity,
    CandidateSpec,
)
from delivery_control.domain.demand_issues import IssueDisposition
from delivery_control.domain.models import Scope
from delivery_control.services.candidate_contract import render_candidate_body
from delivery_control.services.demand_projection import project_demand_inventory


def _payload(number: int, *, body: str, labels: tuple[str, ...] = ()) -> dict[str, object]:
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
