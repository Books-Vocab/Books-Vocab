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
from delivery_control.domain.demand_issues import (
    DemandIssue,
    ISSUE_INTAKE_SCHEMA,
    IssueDisposition,
    IssueIntakeRequest,
    issue_body_sha256,
)
from delivery_control.domain.errors import (
    CompareAndSwapConflict,
    DeliverySourceError,
    PolicyViolation,
)
from delivery_control.domain.models import Scope
from delivery_control.domain.observations import (
    PullRequestInventory,
    RegistryCollisionClaim,
    RegistryCollisionInventory,
)
from delivery_control.ports.process import CommandResult
from delivery_control.services.candidate_contract import render_candidate_body
from delivery_control.services.issue_admission import assert_issue_intake_available


class StaticRunner:
    def __init__(self, responses: list[CommandResult]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, ...]] = []

    def run(self, argv: tuple[str, ...], *, cwd: Path | None = None) -> CommandResult:
        self.calls.append(argv)
        if not self.responses:
            raise AssertionError(f"unexpected command: {argv!r}")
        return self.responses.pop(0)


_DEFAULT_LABEL_PAGE_INFO = object()


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


def _intake_payload(
    *, labels: list[str] | None = None, body: str = "A bounded report"
) -> dict[str, object]:
    return {
        "schema": ISSUE_INTAKE_SCHEMA,
        "title": "A bounded raw Issue",
        "body": body,
        "labels": labels or ["bug"],
        "source": "scout",
        "provenance": "fixture:issue-intake",
        "severity": "P2",
        "priority": 7,
        "acceptance": ["The raw Issue is read back exactly."],
        "scope": Scope.from_paths(modify=("ops/fixture.py",)).to_payload(),
        "operator": "supervisor",
    }


def _intake_repository() -> str:
    return json.dumps(
        {
            "data": {
                "repository": {
                    "id": "R_1",
                    "labels": {
                        "nodes": [
                            {"id": "L_bug", "name": "bug"},
                        ],
                        "pageInfo": {"hasNextPage": False, "endCursor": None},
                    },
                }
            }
        }
    )


def _intake_issue_graphql(
    *,
    number: int = 91,
    title: str = "A bounded raw Issue",
    body: str,
    labels: tuple[str, ...] = ("bug",),
    client_mutation_id: str | None = None,
    mutation: bool = False,
) -> str:
    issue = {
        "id": f"I_{number}",
        "number": number,
        "url": f"https://github.com/owner/repo/issues/{number}",
        "title": title,
        "body": body,
        "updatedAt": "2026-08-25T00:00:00Z",
        "state": "OPEN",
        "labels": {
            "nodes": [{"name": label} for label in labels],
            "pageInfo": {"hasNextPage": False, "endCursor": None},
        },
    }
    if mutation:
        return json.dumps(
            {
                "data": {
                    "createIssue": {
                        "clientMutationId": client_mutation_id,
                        "issue": issue,
                    }
                }
            }
        )
    return json.dumps({"data": {"repository": {"issue": issue}}})


def _graphql(
    issues: list[dict[str, object]],
    *,
    has_next: bool = False,
    label_page_info: object = _DEFAULT_LABEL_PAGE_INFO,
) -> str:
    if label_page_info is _DEFAULT_LABEL_PAGE_INFO:
        label_page_info = {"hasNextPage": False, "endCursor": None}
    return json.dumps(
        {
            "data": {
                "repository": {
                    "issues": {
                        "nodes": [
                            {
                                **issue,
                                "labels": {
                                    "nodes": issue["labels"],
                                    "pageInfo": label_page_info,
                                },
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


def test_raw_issue_query_reads_all_pages_and_preserves_candidate_contract_errors() -> (
    None
):
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
    graphql_calls = [
        call for call in runner.calls if call[:3] == ("gh", "api", "graphql")
    ]
    assert len(graphql_calls) == 2
    query = graphql_calls[0][graphql_calls[0].index("-f") + 1]
    assert "labels(first: 100)" in query
    assert "pageInfo { hasNextPage }" in query
    assert "-F" in runner.calls[1]
    assert "cursor=null" in runner.calls[1]
    assert "cursor=cursor-1" in runner.calls[3]


def test_raw_issue_query_rejects_incomplete_label_inventory() -> None:
    runner = StaticRunner(
        [
            _repo_name(),
            _result(
                _graphql(
                    [_issue(1, labels=(CANDIDATE_ISSUE_LABEL,))],
                    label_page_info={"hasNextPage": True, "endCursor": "labels-1"},
                )
            ),
        ]
    )

    with pytest.raises(DeliverySourceError, match="label inventory is incomplete"):
        GitHubCliAdapter(runner=runner).list_open_issues()


@pytest.mark.parametrize(
    "label_page_info",
    (
        None,
        {},
        {"hasNextPage": "yes"},
    ),
)
def test_raw_issue_query_rejects_malformed_label_page_info(
    label_page_info: object,
) -> None:
    runner = StaticRunner(
        [
            _repo_name(),
            _result(_graphql([_issue(1)], label_page_info=label_page_info)),
        ]
    )

    with pytest.raises(AdapterPayloadError, match="labels pageInfo is malformed"):
        GitHubCliAdapter(runner=runner).list_open_issues()


def test_raw_issue_query_fails_closed_on_graphql_errors() -> None:
    runner = StaticRunner(
        [
            _repo_name(),
            _result(json.dumps({"errors": [{"message": "rate limited"}]})),
        ]
    )

    with pytest.raises(AdapterPayloadError, match="contains errors"):
        GitHubCliAdapter(runner=runner).list_open_issues()


def test_raw_issue_query_rejects_repeated_pagination_cursor() -> None:
    runner = StaticRunner(
        [
            _repo_name(),
            _result(_graphql([_issue(1)], has_next=True)),
            _repo_name(),
            _result(_graphql([_issue(2)], has_next=True)),
        ]
    )

    with pytest.raises(DeliverySourceError, match="pagination cursor repeated"):
        GitHubCliAdapter(runner=runner).list_open_issues()


def test_raw_issue_query_preserves_malformed_graphql_node_without_inventing_number() -> (
    None
):
    response = json.dumps(
        {
            "data": {
                "repository": {
                    "issues": {
                        "nodes": [
                            {
                                **_issue(1),
                                "labels": {
                                    "nodes": [],
                                    "pageInfo": {
                                        "hasNextPage": False,
                                        "endCursor": None,
                                    },
                                },
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


def test_admission_stops_before_mutation_when_target_source_entry_is_malformed() -> (
    None
):
    original = "Malformed candidate payload"
    malformed = _issue(7, body=original, labels=(CANDIDATE_ISSUE_LABEL,))
    runner = StaticRunner(
        [
            _repo_name(),
            _result(_graphql([malformed])),
        ]
    )

    with pytest.raises(DeliverySourceError, match="raw source entry"):
        GitHubCliAdapter(runner=runner).admit_candidate(
            issue_number=7,
            expected_updated_at=datetime.fromisoformat("2026-08-22T01:00:00+00:00"),
            expected_body_sha256=hashlib.sha256(original.encode("utf-8")).hexdigest(),
            spec=_spec(),
            triage_reason="bounded deterministic defect",
            operator="supervisor",
        )

    assert not any(call[:3] == ("gh", "issue", "edit") for call in runner.calls)


def test_admission_ignores_unrelated_malformed_raw_issue_entry() -> None:
    spec = _spec()
    original = "Original report"
    admitted_body = render_candidate_body(
        spec,
        original_body=original,
        triage_reason="bounded deterministic defect",
        operator="supervisor",
    )
    malformed = {"number": 99, "labels": []}
    page_with_unrelated_malformed = _graphql([_issue(body=original), malformed])
    admitted_page_with_unrelated_malformed = _graphql(
        [
            _issue(body=admitted_body, labels=(CANDIDATE_ISSUE_LABEL,)),
            malformed,
        ]
    )
    runner = StaticRunner(
        [
            _repo_name(),
            _result(page_with_unrelated_malformed),
            _result(json.dumps([{"name": CANDIDATE_ISSUE_LABEL}])),
            _result(),
            _repo_name(),
            _result(admitted_page_with_unrelated_malformed),
            _result(),
            _repo_name(),
            _result(admitted_page_with_unrelated_malformed),
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

    assert result.number == 7
    assert result.candidate_spec == spec


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


def test_issue_intake_payload_is_explicit_and_object_only() -> None:
    valid = _intake_payload()
    request = IssueIntakeRequest.from_payload(valid)
    assert request.title == "A bounded raw Issue"
    assert request.scope.paths == ("ops/fixture.py",)

    with pytest.raises(ValueError, match="payload must be an object"):
        IssueIntakeRequest.from_payload([])  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="fields are not exact"):
        IssueIntakeRequest.from_payload({**valid, "unexpected": True})
    with pytest.raises(ValueError, match="labels"):
        IssueIntakeRequest.from_payload({**valid, "labels": []})


def test_issue_intake_adapter_creates_once_and_reads_back_exactly() -> None:
    request = IssueIntakeRequest.from_payload(_intake_payload())
    body = request.render_body()
    runner = StaticRunner(
        [
            _repo_name(),
            _result(_intake_repository()),
            _repo_name(),
            _result(
                _intake_issue_graphql(
                    body=body,
                    client_mutation_id=request.client_mutation_id,
                    mutation=True,
                )
            ),
            _repo_name(),
            _result(_intake_issue_graphql(body=body)),
        ]
    )

    receipt = GitHubCliAdapter(runner=runner).create_issue(request=request)

    assert receipt.issue.number == 91
    assert receipt.issue.title == request.title
    assert receipt.issue.body == body
    assert receipt.issue.labels == request.labels
    assert receipt.source_fingerprint == request.source_fingerprint
    assert CANDIDATE_ISSUE_LABEL not in receipt.issue.labels
    assert sum(call[:3] == ("gh", "api", "graphql") for call in runner.calls) == 3
    graphql_queries = [
        call[call.index("-f") + 1] for call in runner.calls if "-f" in call
    ]
    assert sum("createIssue" in query for query in graphql_queries) == 1


def test_issue_intake_adapter_stops_on_malformed_mutation_without_retry() -> None:
    request = IssueIntakeRequest.from_payload(_intake_payload())
    runner = StaticRunner(
        [
            _repo_name(),
            _result(_intake_repository()),
            _repo_name(),
            _result(json.dumps({"data": {"createIssue": None}})),
        ]
    )

    with pytest.raises(AdapterPayloadError, match="createIssue"):
        GitHubCliAdapter(runner=runner).create_issue(request=request)

    assert sum(call[:3] == ("gh", "api", "graphql") for call in runner.calls) == 2
    assert not any(
        "DeliveryReadIssue" in call[call.index("-f") + 1]
        for call in runner.calls
        if "-f" in call
    )


def test_issue_intake_adapter_fails_closed_on_readback_drift() -> None:
    request = IssueIntakeRequest.from_payload(_intake_payload())
    body = request.render_body()
    runner = StaticRunner(
        [
            _repo_name(),
            _result(_intake_repository()),
            _repo_name(),
            _result(
                _intake_issue_graphql(
                    body=body,
                    client_mutation_id=request.client_mutation_id,
                    mutation=True,
                )
            ),
            _repo_name(),
            _result(_intake_issue_graphql(body=body, title="drifted title")),
        ]
    )

    with pytest.raises(CompareAndSwapConflict, match="read back"):
        GitHubCliAdapter(runner=runner).create_issue(request=request)

    assert sum(call[:3] == ("gh", "api", "graphql") for call in runner.calls) == 3


def test_issue_intake_preflight_rejects_duplicate_security_and_scope_collisions() -> (
    None
):
    request = IssueIntakeRequest.from_payload(_intake_payload())
    duplicate = DemandIssue(
        number=91,
        url="https://github.com/owner/repo/issues/91",
        node_id="I_91",
        title=request.title,
        labels=request.labels,
        body=request.render_body(),
        updated_at=datetime.fromisoformat("2026-08-25T00:00:00+00:00"),
        body_sha256=issue_body_sha256(request.render_body()),
        disposition=IssueDisposition.TRIAGE_REQUIRED,
    )

    with pytest.raises(PolicyViolation, match="source fingerprint"):
        assert_issue_intake_available(
            request=request,
            demand_issues=(duplicate,),
            registry=RegistryCollisionInventory(records=()),
            pull_requests=PullRequestInventory(records=()),
            changed_paths=lambda _number: (),
        )

    with pytest.raises(PolicyViolation, match="security"):
        assert_issue_intake_available(
            request=IssueIntakeRequest.from_payload(
                _intake_payload(labels=["security"])
            ),
            demand_issues=(),
            registry=RegistryCollisionInventory(records=()),
            pull_requests=PullRequestInventory(records=()),
            changed_paths=lambda _number: (),
        )

    assert_issue_intake_available(
        request=IssueIntakeRequest.from_payload(
            _intake_payload(body="No P0/P1/security hold; no security impact.")
        ),
        demand_issues=(),
        registry=RegistryCollisionInventory(records=()),
        pull_requests=PullRequestInventory(records=()),
        changed_paths=lambda _number: (),
    )

    with pytest.raises(PolicyViolation, match="overlaps active registry"):
        assert_issue_intake_available(
            request=request,
            demand_issues=(),
            registry=RegistryCollisionInventory(
                records=(
                    RegistryCollisionClaim(
                        lane_id="DIRECT-OTHER",
                        branch="debug/other",
                        scope=request.scope,
                    ),
                )
            ),
            pull_requests=PullRequestInventory(records=()),
            changed_paths=lambda _number: (),
        )


def test_issue_intake_inventory_then_candidate_admission_is_separate() -> None:
    request = IssueIntakeRequest.from_payload(_intake_payload())
    raw_body = request.render_body()
    spec = CandidateSpec(
        severity=request.severity,
        priority=request.priority,
        scope=request.scope,
        acceptance=request.acceptance,
    )
    admitted_body = render_candidate_body(
        spec,
        original_body=raw_body,
        triage_reason="separate explicit admission",
        operator="supervisor",
    )
    runner = StaticRunner(
        [
            _repo_name(),
            _result(_intake_repository()),
            _repo_name(),
            _result(
                _intake_issue_graphql(
                    body=raw_body,
                    client_mutation_id=request.client_mutation_id,
                    mutation=True,
                )
            ),
            _repo_name(),
            _result(_intake_issue_graphql(body=raw_body)),
            _repo_name(),
            _result(_graphql([_issue(91, body=raw_body, labels=("bug",))])),
            _repo_name(),
            _result(_graphql([_issue(91, body=raw_body, labels=("bug",))])),
            _result(json.dumps([{"name": CANDIDATE_ISSUE_LABEL}])),
            _result(),
            _repo_name(),
            _result(_graphql([_issue(91, body=admitted_body, labels=("bug",))])),
            _result(),
            _repo_name(),
            _result(
                _graphql(
                    [
                        _issue(
                            91,
                            body=admitted_body,
                            labels=("bug", CANDIDATE_ISSUE_LABEL),
                        )
                    ]
                )
            ),
        ]
    )
    adapter = GitHubCliAdapter(runner=runner)

    created = adapter.create_issue(request=request)
    inventory = adapter.list_open_issues()
    assert inventory.records[0].candidate is None
    admitted = adapter.admit_candidate(
        issue_number=created.issue.number,
        expected_updated_at=datetime.fromisoformat("2026-08-22T01:00:00+00:00"),
        expected_body_sha256=created.issue.body_sha256,
        spec=spec,
        triage_reason="separate explicit admission",
        operator="supervisor",
    )

    assert admitted.candidate_spec == spec
    assert CANDIDATE_ISSUE_LABEL in admitted.labels
