from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

OPS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPS))

from delivery_control.adapters.github_cli import GitHubCliAdapter
from delivery_control.adapters.github_parsing import parse_demand_issue_inventory
from delivery_control.cli import main
from delivery_control.domain.demand_issues import (
    DemandIssueInventory,
    IssueCloseReceipt,
    IssueDisposition,
    TerminalEvidenceKind,
)
from delivery_control.domain.errors import (
    CompareAndSwapConflict,
    DeliveryContractError,
    DeliverySourceError,
    PolicyViolation,
)
from delivery_control.domain.models import Scope
from delivery_control.domain.observations import (
    InventoryProblem,
    PullRequestSnapshot,
    RegistrySnapshot,
)
from delivery_control.ports.process import CommandResult
from delivery_control.services.demand_projection import project_demand_inventory
from delivery_control.services.issue_terminal_close import (
    TERMINAL_CLOSE_MARKER,
    IssueTerminalCloseService,
)

BASE = "a" * 40
HEAD = "b" * 40


def _payload(number: int, *, labels: tuple[str, ...] = ()) -> dict[str, object]:
    return {
        "id": f"I_{number}",
        "number": number,
        "url": f"https://github.com/owner/repo/issues/{number}",
        "title": f"Issue {number}",
        "body": f"Report {number}",
        "updatedAt": "2026-08-22T01:00:00Z",
        "labels": [{"name": label} for label in labels],
    }


def _pr(number: int, issue: int, state: str) -> PullRequestSnapshot:
    return PullRequestSnapshot(
        number=number,
        url=f"https://github.com/owner/repo/pull/{number}",
        branch=f"feat/issue-{issue}",
        base_sha=BASE,
        head_sha=HEAD,
        state=state,
        draft=False,
        mergeable=False,
        title=f"Fix #{issue}",
        merged_at=datetime(2026, 8, 22, tzinfo=UTC) if state == "MERGED" else None,
    )


def _lane(issue: int, status: str) -> RegistrySnapshot:
    return RegistrySnapshot(
        lane_id=f"DIRECT-DELIVERY-ISSUE-{issue}",
        branch=f"feat/issue-{issue}",
        path=Path(f"/tmp/issue-{issue}"),
        status=status,
        scope=Scope.from_paths(modify=(f"ops/i{issue}.py",)),
        base_sha=BASE,
        claim_generation=1,
        external_ids=(f"DIRECT-DELIVERY-ISSUE-{issue}",),
    )


def _inventory(*, complete: bool = True) -> DemandIssueInventory:
    raw = parse_demand_issue_inventory(
        [
            _payload(1),  # merged PR -> closable
            _payload(2),  # abandoned lane only -> not completion evidence
            _payload(3, labels=("duplicate",)),  # duplicate label -> closable
            _payload(4),  # closed-unmerged PR only -> not completion evidence
            _payload(5),  # untouched -> not terminal history
        ]
    )
    projected = project_demand_inventory(
        raw,
        registry_records=(_lane(2, "abandoned"),),
        pull_requests=(_pr(11, 1, "MERGED"), _pr(14, 4, "CLOSED")),
    )
    if complete:
        return projected
    return DemandIssueInventory(
        records=projected.records,
        raw_count=projected.raw_count,
        problems=(InventoryProblem("github", "open-prs", "partial"),),
        complete=False,
    )


class FakeIssues:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.fail: dict[int, Exception] = {}
        self.already_closed: set[int] = set()
        self.bad_readback: set[int] = set()

    def close_issue(self, **kwargs: object) -> IssueCloseReceipt:
        number = kwargs["issue_number"]
        assert isinstance(number, int)
        self.calls.append(kwargs)
        if number in self.fail:
            raise self.fail[number]
        if number in self.bad_readback:
            return IssueCloseReceipt(number, "OPEN", None)
        if number in self.already_closed:
            return IssueCloseReceipt(number, "CLOSED", "COMPLETED", already_closed=True)
        return IssueCloseReceipt(number, "CLOSED", "COMPLETED")


def _service(
    inventory: DemandIssueInventory, issues: FakeIssues | None = None
) -> tuple[IssueTerminalCloseService, FakeIssues]:
    issues = issues or FakeIssues()
    return IssueTerminalCloseService(inventory=lambda: inventory, issues=issues), issues


def test_projection_exposes_the_exact_terminal_facts_it_used() -> None:
    by_number = {item.number: item for item in _inventory().records}

    assert by_number[1].disposition is IssueDisposition.TERMINAL_HISTORY
    assert [
        (item.kind, item.ref, item.url) for item in by_number[1].terminal_evidence
    ] == [
        (
            TerminalEvidenceKind.PULL_REQUEST_MERGED,
            "#11",
            "https://github.com/owner/repo/pull/11",
        )
    ]
    assert [item.kind for item in by_number[2].terminal_evidence] == [
        TerminalEvidenceKind.REGISTRY_ABANDONED
    ]
    assert [item.kind for item in by_number[3].terminal_evidence] == [
        TerminalEvidenceKind.LABEL
    ]
    assert [item.kind for item in by_number[4].terminal_evidence] == [
        TerminalEvidenceKind.PULL_REQUEST_CLOSED
    ]
    assert by_number[5].terminal_evidence == ()
    assert not any(item.completes_issue for item in by_number[2].terminal_evidence)


def test_dry_run_lists_closable_and_skipped_with_evidence_and_never_mutates() -> None:
    service, issues = _service(_inventory())

    report = service.run(apply=False)

    assert report.mode == "dry-run"
    assert report.verdict == "dry-run"
    by_number = {item.number: item for item in report.items}
    assert set(by_number) == {1, 2, 3, 4}
    assert by_number[1].status == "would-close"
    assert by_number[3].status == "would-close"
    assert by_number[2].status == "skipped"
    assert by_number[4].status == "skipped"
    assert "pull/11" in by_number[1].comment
    assert TERMINAL_CLOSE_MARKER in by_number[1].comment
    assert by_number[1].evidence[0].ref == "#11"
    assert "merged" in by_number[2].reason or "completion" in by_number[2].reason
    assert report.counts == {
        "would-close": 2,
        "skipped": 2,
        "closed": 0,
        "already-closed": 0,
        "failed": 0,
    }
    assert issues.calls == []


def test_apply_closes_each_with_cas_fingerprint_and_evidence_comment() -> None:
    inventory = _inventory()
    service, issues = _service(inventory)

    report = service.run(apply=True, operator="im")

    assert report.verdict == "closed"
    assert [item.status for item in report.items if item.number in {1, 3}] == [
        "closed",
        "closed",
    ]
    assert [call["issue_number"] for call in issues.calls] == [1, 3]
    first = issues.calls[0]
    source = {item.number: item for item in inventory.records}[1]
    assert first["expected_updated_at"] == source.updated_at
    assert first["expected_body_sha256"] == source.body_sha256
    assert "pull/11" in first["comment"]  # type: ignore[operator]
    assert "im" in first["comment"]  # type: ignore[operator]
    assert report.counts["closed"] == 2


def test_single_failure_does_not_stop_others_and_is_reported() -> None:
    issues = FakeIssues()
    issues.fail[1] = CompareAndSwapConflict("Issue #1 changed")
    service, _ = _service(_inventory(), issues)

    report = service.run(apply=True, operator="im")

    assert report.verdict == "partial-failure"
    by_number = {item.number: item for item in report.items}
    assert by_number[1].status == "failed"
    assert "changed" in by_number[1].error
    assert by_number[3].status == "closed"
    assert [call["issue_number"] for call in issues.calls] == [1, 3]
    assert report.counts["failed"] == 1


def test_unverified_readback_is_a_failure_not_a_success() -> None:
    issues = FakeIssues()
    issues.bad_readback.add(1)
    service, _ = _service(_inventory(), issues)

    report = service.run(apply=True, operator="im")

    assert {item.number: item.status for item in report.items}[1] == "failed"
    assert report.verdict == "partial-failure"


def test_already_closed_issue_is_verified_not_recounted_as_closed() -> None:
    issues = FakeIssues()
    issues.already_closed.add(3)
    service, _ = _service(_inventory(), issues)

    report = service.run(apply=True, operator="im")

    assert {item.number: item.status for item in report.items}[3] == "already-closed"
    assert report.verdict == "closed"


def test_incomplete_inventory_blocks_apply_but_still_dry_runs() -> None:
    service, issues = _service(_inventory(complete=False))

    dry = service.run(apply=False)
    assert dry.verdict == "blocked"
    assert dry.complete is False
    with pytest.raises(PolicyViolation, match="incomplete"):
        service.run(apply=True, operator="im")
    assert issues.calls == []


def test_apply_requires_operator() -> None:
    service, issues = _service(_inventory())

    with pytest.raises(DeliveryContractError):
        service.run(apply=True)
    with pytest.raises(DeliveryContractError):
        service.run(apply=True, operator="  ")
    assert issues.calls == []


def test_issue_filter_limits_scope_and_flags_unknown_numbers() -> None:
    service, issues = _service(_inventory())

    report = service.run(apply=True, operator="im", issue_numbers=(3, 5, 99))

    by_number = {item.number: item for item in report.items}
    assert set(by_number) == {3, 5, 99}
    assert by_number[3].status == "closed"
    assert by_number[5].status == "skipped"
    assert by_number[99].status == "skipped"
    assert [call["issue_number"] for call in issues.calls] == [3]


def test_nothing_to_close_is_a_clean_verdict() -> None:
    inventory = project_demand_inventory(parse_demand_issue_inventory([_payload(5)]))
    service, issues = _service(inventory)

    report = service.run(apply=True, operator="im")

    assert report.verdict == "nothing-to-close"
    assert issues.calls == []


# --- adapter ---------------------------------------------------------------


class StaticRunner:
    def __init__(self, responses: list[CommandResult]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, ...]] = []

    def run(self, argv: tuple[str, ...], *, cwd: Path | None = None) -> CommandResult:
        self.calls.append(argv)
        if not self.responses:
            raise AssertionError(f"unexpected command: {argv!r}")
        return self.responses.pop(0)


def _ok(stdout: str = "") -> CommandResult:
    return CommandResult(argv=("gh",), exit_code=0, stdout=stdout, stderr="")


def _repo_name() -> CommandResult:
    return _ok(json.dumps({"nameWithOwner": "owner/repo"}))


def _read(
    *,
    state: str = "OPEN",
    reason: str | None = None,
    updated_at: str = "2026-08-22T01:00:00Z",
    body: str = "Report 1",
) -> CommandResult:
    issue = {
        **_payload(1),
        "body": body,
        "updatedAt": updated_at,
        "state": state,
        "stateReason": reason,
        "labels": {
            "nodes": [],
            "pageInfo": {"hasNextPage": False, "endCursor": None},
        },
    }
    return _ok(json.dumps({"data": {"repository": {"issue": issue}}}))


def _close_kwargs(**overrides: object) -> dict[str, object]:
    import hashlib

    kwargs: dict[str, object] = {
        "issue_number": 1,
        "expected_updated_at": datetime.fromisoformat("2026-08-22T01:00:00+00:00"),
        "expected_body_sha256": hashlib.sha256(b"Report 1").hexdigest(),
        "comment": f"{TERMINAL_CLOSE_MARKER}\nevidence",
    }
    kwargs.update(overrides)
    return kwargs


def test_adapter_closes_as_completed_with_comment_and_reads_back() -> None:
    runner = StaticRunner(
        [
            _repo_name(),
            _read(),
            _ok(),
            _repo_name(),
            _read(state="CLOSED", reason="COMPLETED"),
        ]
    )

    receipt = GitHubCliAdapter(runner=runner).close_issue(**_close_kwargs())

    assert receipt == IssueCloseReceipt(1, "CLOSED", "COMPLETED")
    close_call = next(
        call for call in runner.calls if call[:3] == ("gh", "issue", "close")
    )
    assert close_call[3] == "1"
    assert close_call[close_call.index("--reason") + 1] == "completed"
    assert TERMINAL_CLOSE_MARKER in close_call[close_call.index("--comment") + 1]


@pytest.mark.parametrize(
    "drift",
    [
        {"updated_at": "2026-08-22T02:00:00Z"},
        {"body": "Edited report"},
    ],
)
def test_adapter_refuses_to_close_an_issue_that_changed(drift: dict[str, str]) -> None:
    runner = StaticRunner([_repo_name(), _read(**drift)])

    with pytest.raises(CompareAndSwapConflict):
        GitHubCliAdapter(runner=runner).close_issue(**_close_kwargs())

    assert not any(call[:3] == ("gh", "issue", "close") for call in runner.calls)


def test_adapter_treats_a_closed_issue_as_verified_without_mutation() -> None:
    runner = StaticRunner([_repo_name(), _read(state="CLOSED", reason="COMPLETED")])

    receipt = GitHubCliAdapter(runner=runner).close_issue(**_close_kwargs())

    assert receipt.already_closed is True
    assert not any(call[:3] == ("gh", "issue", "close") for call in runner.calls)


def test_adapter_fails_closed_when_readback_is_not_completed() -> None:
    runner = StaticRunner(
        [
            _repo_name(),
            _read(),
            _ok(),
            _repo_name(),
            _read(state="CLOSED", reason="NOT_PLANNED"),
        ]
    )

    with pytest.raises(CompareAndSwapConflict):
        GitHubCliAdapter(runner=runner).close_issue(**_close_kwargs())


def test_adapter_does_not_retry_a_failed_close() -> None:
    runner = StaticRunner(
        [
            _repo_name(),
            _read(),
            CommandResult(argv=("gh",), exit_code=1, stdout="", stderr="boom"),
        ]
    )

    with pytest.raises(DeliverySourceError, match="boom"):
        GitHubCliAdapter(runner=runner).close_issue(**_close_kwargs())

    assert sum(call[:3] == ("gh", "issue", "close") for call in runner.calls) == 1


# --- CLI -------------------------------------------------------------------


class _CliApplication:
    def __init__(self, verdict: str) -> None:
        self.verdict = verdict
        self.calls: list[dict[str, object]] = []

    def close_terminal_issues(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        progress = kwargs.get("progress")
        if callable(progress):
            progress("closing #1")
        return {"verdict": self.verdict, "counts": {}}


def test_cli_defaults_to_dry_run_with_progress_on_stderr(capsys: object) -> None:
    application = _CliApplication("dry-run")

    code = main(["close-terminal-issues"], application_factory=lambda **_: application)

    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert code == 0
    assert application.calls[0]["apply"] is False
    assert application.calls[0]["issue_numbers"] == ()
    assert json.loads(captured.out)["verdict"] == "dry-run"
    assert "closing #1" in captured.err


def test_cli_apply_passes_operator_and_issue_filter(capsys: object) -> None:
    application = _CliApplication("closed")

    code = main(
        [
            "close-terminal-issues",
            "--apply",
            "--operator",
            "im",
            "--issue",
            "3",
            "--issue",
            "1",
        ],
        application_factory=lambda **_: application,
    )

    capsys.readouterr()  # type: ignore[attr-defined]
    assert code == 0
    assert application.calls[0]["apply"] is True
    assert application.calls[0]["operator"] == "im"
    assert application.calls[0]["issue_numbers"] == (1, 3)


@pytest.mark.parametrize(
    ("verdict", "code"),
    [("partial-failure", 1), ("blocked", 2), ("nothing-to-close", 0)],
)
def test_cli_exit_code_reflects_failures(
    capsys: object, verdict: str, code: int
) -> None:
    application = _CliApplication(verdict)

    observed = main(
        ["close-terminal-issues", "--apply", "--operator", "im"],
        application_factory=lambda **_: application,
    )

    payload = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert payload["verdict"] == verdict
    assert observed == code


# --- application wiring ------------------------------------------------------


def _bare_application(github: object) -> object:
    from delivery_control.application import DeliveryApplication

    return DeliveryApplication(
        repo=Path("/repo"),
        git=None,  # type: ignore[arg-type]
        github=github,  # type: ignore[arg-type]
        registry=None,  # type: ignore[arg-type]
        runtime=None,  # type: ignore[arg-type]
        telemetry=None,  # type: ignore[arg-type]
    )


def test_application_closes_from_the_shared_inspect_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    from delivery_control.application import DeliveryApplication

    issues = FakeIssues()
    inventory = _inventory()
    monkeypatch.setattr(
        DeliveryApplication,
        "inspect",
        lambda self, **_: SimpleNamespace(demand_issues=inventory),
    )

    report = _bare_application(issues).close_terminal_issues(  # type: ignore[attr-defined]
        apply=True, operator="im"
    )

    assert report.verdict == "closed"
    assert [call["issue_number"] for call in issues.calls] == [1, 3]


def test_application_without_close_capability_fails_closed() -> None:
    application = _bare_application(object())

    with pytest.raises(DeliverySourceError):
        application.close_terminal_issues(apply=False)  # type: ignore[attr-defined]
    with pytest.raises(DeliverySourceError):
        application.dispose_ownerless_claim(  # type: ignore[attr-defined]
            branch="x", apply=False
        )
