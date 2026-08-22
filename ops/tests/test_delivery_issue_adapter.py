from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

import pytest

OPS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPS))

from delivery_control.adapters.errors import AdapterCommandError, AdapterPayloadError
from delivery_control.adapters.github_cli import GitHubCliAdapter
from delivery_control.domain.candidate_issues import (
    CANDIDATE_ISSUE_LABEL,
    CandidateSeverity,
    CandidateSpec,
)
from delivery_control.domain.errors import (
    CompareAndSwapConflict,
    DeliverySourceError,
    PolicyViolation,
)
from delivery_control.domain.models import Scope
from delivery_control.ports.process import CommandResult
from delivery_control.services.candidate_contract import render_candidate_body


class StaticRunner:
    def __init__(self, responses: list[CommandResult]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, ...]] = []

    def run(self, argv: tuple[str, ...], *, cwd: Path | None = None) -> CommandResult:
        self.calls.append(argv)
        if not self.responses:
            raise AssertionError(f"unexpected command: {argv!r}")
        return self.responses.pop(0)


def _result(stdout: str = "", *, argv: tuple[str, ...] = ("gh",)) -> CommandResult:
    return CommandResult(argv=argv, exit_code=0, stdout=stdout, stderr="")


def _failure(stderr: str = "mutation failed") -> CommandResult:
    return CommandResult(argv=("gh",), exit_code=1, stdout="", stderr=stderr)


def _spec(number: int = 7) -> CandidateSpec:
    return CandidateSpec(
        severity=CandidateSeverity.P2,
        priority=number,
        scope=Scope.from_paths(modify=(f"ops/issue_{number}.py",)),
        acceptance=(f"Issue {number} is fixed.",),
    )


def _issue(
    number: int = 7,
    *,
    body: str = "Original report",
    labels: tuple[str, ...] = (),
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


def _graphql(issues: list[dict[str, object]], *, has_next: bool = False) -> str:
    return json.dumps(
        {
            "data": {
                "repository": {
                    "issues": {
                        "nodes": [
                            {
                                **issue,
                                "labels": {"nodes": issue["labels"]},
                            }
                            for issue in issues
                        ],
                        "pageInfo": {
                            "hasNextPage": has_next,
                            "endCursor": "cursor-1" if has_next else None,
                        },
                    }
                }
            }
        }
    )


def _repo_name() -> CommandResult:
    return _result(json.dumps({"nameWithOwner": "owner/repo"}))


def test_raw_issue_query_reads_all_pages_and_preserves_candidate_contract_errors() -> None:
    malformed = _issue(2, labels=(CANDIDATE_ISSUE_LABEL,), body="missing contract")
    runner = StaticRunner(
        [
            _repo_name(),
            _result(_graphql([_issue(1)], has_next=True)),
            _repo_name(),
            _result(_graphql([malformed])),
        ]
    )

    inventory = GitHubCliAdapter(runner=runner).list_open_issues()

    assert inventory.raw_open_issues == 2
    assert [item.number for item in inventory.records] == [1, 2]
    assert inventory.problems[0].identity == "Issue#2"
    assert len([call for call in runner.calls if call[:3] == ("gh", "api", "graphql")]) == 2
    assert "-F" in runner.calls[1]
    assert "cursor=null" in runner.calls[1]
    assert "cursor=cursor-1" in runner.calls[3]


def test_raw_issue_query_fails_closed_on_graphql_errors() -> None:
    runner = StaticRunner(
        [
            _repo_name(),
            _result(json.dumps({"errors": [{"message": "rate limited"}]})),
        ]
    )

    with pytest.raises(AdapterPayloadError, match="contains errors"):
        GitHubCliAdapter(runner=runner).list_open_issues()


def test_raw_issue_query_preserves_malformed_graphql_node_without_inventing_number() -> None:
    response = json.dumps(
        {
            "data": {
                "repository": {
                    "issues": {
                        "nodes": [
                            {
                                **_issue(1),
                                "labels": {"nodes": []},
                            },
                            None,
                        ],
                        "pageInfo": {"hasNextPage": False, "endCursor": None},
                    }
                }
            }
        }
    )
    runner = StaticRunner(
        [
            _repo_name(),
            _result(response),
        ]
    )

    inventory = GitHubCliAdapter(runner=runner).list_open_issues()

    assert inventory.raw_open_issues == 2
    assert [item.number for item in inventory.records] == [1]
    assert inventory.source_entries[0].identity == "entry[1]"
    assert inventory.source_entries[0].issue_number is None


def test_admission_preserves_original_body_and_requires_exact_readback() -> None:
    spec = _spec()
    original = "Original report with operator context"
    admitted_body = render_candidate_body(
        spec,
        original_body=original,
        triage_reason="bounded deterministic defect",
        operator="supervisor",
    )
    final_issue = _issue(
        body=admitted_body,
        labels=(CANDIDATE_ISSUE_LABEL,),
    )
    runner = StaticRunner(
        [
            _repo_name(),
            _result(_graphql([_issue(body=original)])),
            _result(json.dumps([{"name": CANDIDATE_ISSUE_LABEL}])),
            _result(),
            _repo_name(),
            _result(_graphql([_issue(body=admitted_body)])),
            _result(),
            _repo_name(),
            _result(_graphql([final_issue])),
        ]
    )

    result = GitHubCliAdapter(runner=runner).admit_candidate(
        issue_number=7,
        expected_updated_at=datetime.fromisoformat("2026-08-22T01:00:00+00:00"),
        expected_body_sha256=hashlib.sha256(original.encode("utf-8")).hexdigest(),
        spec=spec,
        triage_reason="bounded deterministic defect",
        operator="supervisor",
    )

    assert result.candidate_spec == spec
    assert result.body.startswith(original)
    assert result.body == admitted_body
    assert any(
        call[:3] == ("gh", "issue", "edit") and "--body" in call
        for call in runner.calls
    )
    assert any(
        call[:3] == ("gh", "issue", "edit") and "--add-label" in call
        for call in runner.calls
    )


def test_admission_stops_before_mutation_when_label_is_not_configured() -> None:
    original = "Original report"
    runner = StaticRunner(
        [
            _repo_name(),
            _result(_graphql([_issue(body=original)])),
            _result("[]"),
        ]
    )

    with pytest.raises(PolicyViolation, match="not configured"):
        GitHubCliAdapter(runner=runner).admit_candidate(
            issue_number=7,
            expected_updated_at=datetime.fromisoformat("2026-08-22T01:00:00+00:00"),
            expected_body_sha256=hashlib.sha256(original.encode("utf-8")).hexdigest(),
            spec=_spec(),
            triage_reason="bounded deterministic defect",
            operator="supervisor",
        )

    assert not any(call[:3] == ("gh", "issue", "edit") for call in runner.calls)


def test_admission_stops_before_mutation_when_raw_inventory_has_source_problem() -> None:
    original = "Malformed candidate payload"
    malformed = _issue(7, body=original, labels=(CANDIDATE_ISSUE_LABEL,))
    runner = StaticRunner(
        [
            _repo_name(),
            _result(_graphql([malformed])),
        ]
    )

    with pytest.raises(DeliverySourceError, match="source problems"):
        GitHubCliAdapter(runner=runner).admit_candidate(
            issue_number=7,
            expected_updated_at=datetime.fromisoformat("2026-08-22T01:00:00+00:00"),
            expected_body_sha256=hashlib.sha256(original.encode("utf-8")).hexdigest(),
            spec=_spec(),
            triage_reason="bounded deterministic defect",
            operator="supervisor",
        )

    assert not any(call[:3] == ("gh", "issue", "edit") for call in runner.calls)


def test_admission_stops_without_retry_when_body_mutation_fails() -> None:
    original = "Original report"
    runner = StaticRunner(
        [
            _repo_name(),
            _result(_graphql([_issue(body=original)])),
            _result(json.dumps([{"name": CANDIDATE_ISSUE_LABEL}])),
            _failure("body update failed"),
        ]
    )

    with pytest.raises(AdapterCommandError, match="body update failed"):
        GitHubCliAdapter(runner=runner).admit_candidate(
            issue_number=7,
            expected_updated_at=datetime.fromisoformat("2026-08-22T01:00:00+00:00"),
            expected_body_sha256=hashlib.sha256(original.encode("utf-8")).hexdigest(),
            spec=_spec(),
            triage_reason="bounded deterministic defect",
            operator="supervisor",
        )

    assert sum(call[:3] == ("gh", "issue", "edit") for call in runner.calls) == 1


def test_admission_stops_without_retry_when_label_mutation_fails() -> None:
    spec = _spec()
    original = "Original report"
    admitted_body = render_candidate_body(
        spec,
        original_body=original,
        triage_reason="bounded deterministic defect",
        operator="supervisor",
    )
    runner = StaticRunner(
        [
            _repo_name(),
            _result(_graphql([_issue(body=original)])),
            _result(json.dumps([{"name": CANDIDATE_ISSUE_LABEL}])),
            _result(),
            _repo_name(),
            _result(_graphql([_issue(body=admitted_body)])),
            _failure("label update failed"),
        ]
    )

    with pytest.raises(AdapterCommandError, match="label update failed"):
        GitHubCliAdapter(runner=runner).admit_candidate(
            issue_number=7,
            expected_updated_at=datetime.fromisoformat("2026-08-22T01:00:00+00:00"),
            expected_body_sha256=hashlib.sha256(original.encode("utf-8")).hexdigest(),
            spec=spec,
            triage_reason="bounded deterministic defect",
            operator="supervisor",
        )

    assert sum(call[:3] == ("gh", "issue", "edit") for call in runner.calls) == 2


def test_admission_body_readback_mismatch_fails_closed() -> None:
    spec = _spec()
    original = "Original report"
    admitted_body = render_candidate_body(
        spec,
        original_body=original,
        triage_reason="bounded deterministic defect",
        operator="supervisor",
    )
    runner = StaticRunner(
        [
            _repo_name(),
            _result(_graphql([_issue(body=original)])),
            _result(json.dumps([{"name": CANDIDATE_ISSUE_LABEL}])),
            _result(),
            _repo_name(),
            _result(_graphql([_issue(body=admitted_body + " drift")])),
        ]
    )

    with pytest.raises(CompareAndSwapConflict, match="did not read back"):
        GitHubCliAdapter(runner=runner).admit_candidate(
            issue_number=7,
            expected_updated_at=datetime.fromisoformat("2026-08-22T01:00:00+00:00"),
            expected_body_sha256=hashlib.sha256(original.encode("utf-8")).hexdigest(),
            spec=spec,
            triage_reason="bounded deterministic defect",
            operator="supervisor",
        )


def test_admission_is_idempotent_for_exact_existing_candidate() -> None:
    spec = _spec()
    admitted_body = render_candidate_body(spec, original_body="Original report")
    runner = StaticRunner(
        [
            _repo_name(),
            _result(
                _graphql(
                    [
                        _issue(
                            body=admitted_body,
                            labels=(CANDIDATE_ISSUE_LABEL,),
                        )
                    ]
                )
            ),
        ]
    )

    result = GitHubCliAdapter(runner=runner).admit_candidate(
        issue_number=7,
        expected_updated_at=datetime.fromisoformat("2020-01-01T00:00:00+00:00"),
        expected_body_sha256="0" * 64,
        spec=spec,
        triage_reason="ignored on idempotent replay",
        operator="supervisor",
    )

    assert result.candidate_spec == spec
    assert not any(call[:3] == ("gh", "issue", "edit") for call in runner.calls)


def test_admission_fails_closed_on_fingerprint_drift_without_retry() -> None:
    original = "Current report"
    runner = StaticRunner(
        [
            _repo_name(),
            _result(_graphql([_issue(body=original)])),
        ]
    )

    with pytest.raises(CompareAndSwapConflict, match="changed"):
        GitHubCliAdapter(runner=runner).admit_candidate(
            issue_number=7,
            expected_updated_at=datetime.fromisoformat("2026-08-21T01:00:00+00:00"),
            expected_body_sha256="0" * 64,
            spec=_spec(),
            triage_reason="bounded deterministic defect",
            operator="supervisor",
        )

    assert not any(call[:3] == ("gh", "issue", "edit") for call in runner.calls)
