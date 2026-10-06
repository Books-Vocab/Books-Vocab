from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path

import pytest

OPS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPS))

from delivery_control.adapters.disposition_receipts import (
    DispositionReceiptNdjsonAdapter,
)
from delivery_control.cli import main
from delivery_control.domain.errors import (
    CompareAndSwapConflict,
    DeliveryContractError,
)
from delivery_control.domain.models import Scope
from delivery_control.domain.observations import (
    CanonicalCheckoutSnapshot,
    InventoryProblem,
    PhysicalWorktree,
    PullRequestInventory,
    PullRequestSnapshot,
    RegistryInventory,
    RegistrySnapshot,
)
from delivery_control.services.ownerless_claim import (
    OwnerlessClaimDisposalService,
)

BASE = "a" * 40
LOCAL = "b" * 40
OTHER = "c" * 40
BRANCH = "feat/ownerless"
PATH = Path("/tmp/kg-ownerless-claim-absent").resolve()
SCOPE = Scope.from_paths(modify=("ops/example.py",))


def _record(**overrides: object) -> RegistrySnapshot:
    fields: dict[str, object] = {
        "lane_id": "DIRECT-OWNERLESS",
        "branch": BRANCH,
        "path": PATH,
        "status": "active",
        "scope": SCOPE,
        "base_sha": BASE,
        "claim_generation": 3,
        "owner_thread_id": None,
    }
    fields.update(overrides)
    return RegistrySnapshot(**fields)  # type: ignore[arg-type]


class FakeRegistry:
    def __init__(self, *records: RegistrySnapshot) -> None:
        self.records = list(records)
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.journal: list[str] = []
        self.fail_resolve: Exception | None = None
        self.skip_status_change = False

    def list_records(self) -> RegistryInventory:
        return RegistryInventory(tuple(self.records))

    def find_exact_claim(
        self, *, lane_id: str, branch: str, path: Path, claim_generation: int
    ) -> RegistrySnapshot | None:
        for record in self.records:
            if (
                record.lane_id == lane_id
                and record.branch == branch
                and record.path == path
                and record.claim_generation == claim_generation
            ):
                return record
        return None

    def resolve(self, lane_id: str, disposition: str, **kwargs: object) -> None:
        self.journal.append("resolve")
        self.calls.append((disposition, {"lane_id": lane_id, **kwargs}))
        if self.fail_resolve is not None:
            raise self.fail_resolve
        if self.skip_status_change:
            return
        self.records = [
            replace(item, status=disposition) if item.lane_id == lane_id else item
            for item in self.records
        ]


class FakeGit:
    def __init__(
        self,
        *,
        local: str | None = None,
        remote: str | None = None,
        physical: tuple[PhysicalWorktree, ...] = (),
        canonical_branch: str = "main",
        canonical_clean: bool = True,
    ) -> None:
        self.local = local
        self.remote = remote
        self.physical = physical
        self.canonical_branch = canonical_branch
        self.canonical_clean = canonical_clean

    def canonical_checkout(self) -> CanonicalCheckoutSnapshot:
        return CanonicalCheckoutSnapshot(
            path=Path("/repo"),
            branch=self.canonical_branch,
            head_sha=BASE,
            clean=self.canonical_clean,
        )

    def list_worktrees(self) -> tuple[PhysicalWorktree, ...]:
        return self.physical

    def local_branch_sha(self, branch: str) -> str | None:
        return self.local

    def remote_branch_sha(self, branch: str) -> str | None:
        return self.remote


class FakeGitHub:
    def __init__(self, inventory: PullRequestInventory | None = None) -> None:
        self.inventory = inventory or PullRequestInventory(())

    def list_pull_requests_for_branch(self, branch: str) -> PullRequestInventory:
        return self.inventory


class FakeReceipts:
    def __init__(self, registry: FakeRegistry) -> None:
        self.registry = registry
        self.rows: list[dict[str, object]] = []

    def append(self, receipt: dict[str, object]) -> None:
        self.registry.journal.append(f"receipt:{receipt['phase']}")
        self.rows.append(receipt)


def _pr(state: str = "CLOSED") -> PullRequestSnapshot:
    return PullRequestSnapshot(
        number=9,
        url="https://github.com/o/r/pull/9",
        branch=BRANCH,
        base_sha=BASE,
        head_sha=LOCAL,
        state=state,
        draft=False,
        mergeable=False,
    )


def _service(
    registry: FakeRegistry,
    git: FakeGit | None = None,
    github: FakeGitHub | None = None,
) -> tuple[OwnerlessClaimDisposalService, FakeReceipts]:
    receipts = FakeReceipts(registry)
    return (
        OwnerlessClaimDisposalService(
            registry=registry,
            registry_command=registry,
            git_query=git or FakeGit(),
            github=github or FakeGitHub(),
            receipts=receipts,
        ),
        receipts,
    )


def _check(report: object, check_id: str) -> object:
    return next(item for item in report.checks if item.id == check_id)  # type: ignore[attr-defined]


def test_dry_run_reports_eligibility_and_never_mutates() -> None:
    registry = FakeRegistry(_record())
    service, receipts = _service(registry)

    report = service.dispose(branch=BRANCH, apply=False)

    assert report.eligible is True
    assert report.applied is False
    assert report.verdict == "eligible"
    assert report.claim_generation == 3
    assert report.head_sha == BASE
    assert all(item.ok for item in report.checks)
    assert registry.calls == []
    assert receipts.rows == []


def test_apply_writes_ahead_receipt_then_cas_resolves_then_commits() -> None:
    registry = FakeRegistry(_record())
    service, receipts = _service(registry)

    report = service.dispose(
        branch=BRANCH,
        apply=True,
        expected_claim_generation=3,
        expected_head_sha=BASE,
        operator="im",
        reason="ownerless claim has no worktree, PR, or handback",
    )

    assert report.applied is True
    assert report.verdict == "applied"
    assert registry.journal == [
        "receipt:intent",
        "resolve",
        "receipt:committed",
    ]
    disposition, kwargs = registry.calls[0]
    assert disposition == "abandoned"
    assert kwargs == {
        "lane_id": "DIRECT-OWNERLESS",
        "expected_claim_generation": 3,
        "expected_branch": BRANCH,
        "expected_path": str(PATH),
        "expected_head_sha": BASE,
    }
    intent, committed = receipts.rows
    assert intent["operator"] == "im"
    assert intent["reason"].startswith("ownerless claim")
    assert intent["branch"] == BRANCH
    assert intent["claim_generation"] == 3
    assert {item["id"] for item in intent["checks"]} >= {
        "owner_absent",
        "no_physical_worktree",
        "no_pr_history",
        "no_valid_handback",
        "no_remote_drift",
        "no_hold",
    }
    assert committed["registry_status"] == "abandoned"
    assert committed["phase"] == "committed"
    assert intent["phase"] == "intent"


def test_apply_uses_the_exact_local_tip_as_cas_head() -> None:
    registry = FakeRegistry(_record())
    service, _ = _service(registry, FakeGit(local=LOCAL))

    report = service.dispose(
        branch=BRANCH,
        apply=True,
        expected_claim_generation=3,
        expected_head_sha=LOCAL,
        operator="im",
        reason="ownerless",
    )

    assert report.applied is True
    assert registry.calls[0][1]["expected_head_sha"] == LOCAL


@pytest.mark.parametrize(
    ("check_id", "record", "git", "github"),
    [
        ("owner_absent", _record(owner_thread_id="thread-1"), None, None),
        (
            "no_physical_worktree",
            _record(),
            FakeGit(physical=(PhysicalWorktree(PATH, LOCAL, BRANCH),)),
            None,
        ),
        (
            "no_physical_worktree",
            _record(),
            FakeGit(physical=(PhysicalWorktree(Path("/elsewhere"), LOCAL, BRANCH),)),
            None,
        ),
        (
            "no_pr_history",
            _record(),
            None,
            FakeGitHub(PullRequestInventory((_pr("CLOSED"),))),
        ),
        (
            "no_pr_history",
            _record(),
            None,
            FakeGitHub(PullRequestInventory((_pr("MERGED"),))),
        ),
        (
            "no_pr_history",
            _record(),
            None,
            FakeGitHub(PullRequestInventory((_pr("OPEN"),))),
        ),
        (
            "no_pr_history",
            _record(),
            None,
            FakeGitHub(
                PullRequestInventory(
                    (), problems=(InventoryProblem("github", BRANCH, "partial"),)
                )
            ),
        ),
        (
            "no_valid_handback",
            _record(handed_back_sha=LOCAL, handback_valid=True, handback_digest="d" * 64),
            None,
            None,
        ),
        ("no_remote_drift", _record(), FakeGit(remote=OTHER), None),
        ("no_remote_drift", _record(), FakeGit(local=LOCAL, remote=OTHER), None),
        ("no_hold", _record(handback_initial_holds=("security",)), None, None),
        ("canonical_main_clean", _record(), FakeGit(canonical_clean=False), None),
        ("canonical_main_clean", _record(), FakeGit(canonical_branch="feat/x"), None),
        ("claim_active", _record(status="published"), None, None),
    ],
)
def test_each_unmet_precondition_refuses_without_mutation(
    check_id: str,
    record: RegistrySnapshot,
    git: FakeGit | None,
    github: FakeGitHub | None,
) -> None:
    registry = FakeRegistry(record)
    service, receipts = _service(registry, git, github)

    report = service.dispose(
        branch=BRANCH,
        apply=True,
        expected_claim_generation=3,
        expected_head_sha=BASE,
        operator="im",
        reason="ownerless",
    )

    assert report.eligible is False
    assert report.applied is False
    assert report.verdict == "refused"
    assert _check(report, check_id).ok is False
    assert registry.calls == []
    assert receipts.rows == []


def test_refusal_lists_every_failed_precondition() -> None:
    registry = FakeRegistry(
        _record(owner_thread_id="thread-1", handback_initial_holds=("p0",))
    )
    service, _ = _service(
        registry,
        FakeGit(physical=(PhysicalWorktree(PATH, LOCAL, BRANCH),), remote=OTHER),
        FakeGitHub(PullRequestInventory((_pr(),))),
    )

    report = service.dispose(branch=BRANCH, apply=False)

    failed = {item.id for item in report.checks if item.ok is False}
    assert failed == {
        "owner_absent",
        "no_physical_worktree",
        "no_pr_history",
        "no_remote_drift",
        "no_hold",
    }
    assert all(item.detail for item in report.checks if item.ok is False)


def test_missing_or_ambiguous_claim_is_refused_not_guessed() -> None:
    empty = FakeRegistry()
    service, _ = _service(empty)
    assert service.dispose(branch=BRANCH, apply=False).verdict == "refused"

    twin = FakeRegistry(_record(), _record(lane_id="DIRECT-TWIN", claim_generation=4))
    service, _ = _service(twin)
    report = service.dispose(branch=BRANCH, apply=False)
    assert report.verdict == "refused"
    assert _check(report, "claim_unique").ok is False


def test_apply_requires_cas_pins_to_match_the_observed_claim() -> None:
    registry = FakeRegistry(_record())
    service, receipts = _service(registry)

    stale_generation = service.dispose(
        branch=BRANCH,
        apply=True,
        expected_claim_generation=2,
        expected_head_sha=BASE,
        operator="im",
        reason="ownerless",
    )
    stale_head = service.dispose(
        branch=BRANCH,
        apply=True,
        expected_claim_generation=3,
        expected_head_sha=OTHER,
        operator="im",
        reason="ownerless",
    )

    assert _check(stale_generation, "expected_claim_generation").ok is False
    assert _check(stale_head, "expected_head_sha").ok is False
    assert registry.calls == []
    assert receipts.rows == []


@pytest.mark.parametrize(
    "kwargs",
    [
        {},
        {"expected_claim_generation": 3, "expected_head_sha": BASE},
        {
            "expected_claim_generation": 3,
            "expected_head_sha": BASE,
            "operator": " ",
            "reason": "x",
        },
        {
            "expected_claim_generation": 3,
            "expected_head_sha": BASE,
            "operator": "im",
            "reason": "",
        },
        {"operator": "im", "reason": "x"},
    ],
)
def test_apply_demands_operator_reason_and_pins(kwargs: dict[str, object]) -> None:
    registry = FakeRegistry(_record())
    service, _ = _service(registry)

    with pytest.raises(DeliveryContractError):
        service.dispose(branch=BRANCH, apply=True, **kwargs)  # type: ignore[arg-type]

    assert registry.calls == []


def test_registry_cas_conflict_leaves_a_failed_receipt_and_raises() -> None:
    registry = FakeRegistry(_record())
    registry.fail_resolve = CompareAndSwapConflict("claim moved")
    service, receipts = _service(registry)

    with pytest.raises(CompareAndSwapConflict):
        service.dispose(
            branch=BRANCH,
            apply=True,
            expected_claim_generation=3,
            expected_head_sha=BASE,
            operator="im",
            reason="ownerless",
        )

    assert [row["phase"] for row in receipts.rows] == ["intent", "failed"]
    assert "claim moved" in str(receipts.rows[1]["error"])


def test_unverified_readback_fails_closed_and_is_not_committed() -> None:
    registry = FakeRegistry(_record())
    registry.skip_status_change = True
    service, receipts = _service(registry)

    with pytest.raises(CompareAndSwapConflict):
        service.dispose(
            branch=BRANCH,
            apply=True,
            expected_claim_generation=3,
            expected_head_sha=BASE,
            operator="im",
            reason="ownerless",
        )

    assert [row["phase"] for row in receipts.rows] == ["intent", "failed"]


def test_receipt_adapter_is_append_only_fsynced_ndjson(tmp_path: Path) -> None:
    path = tmp_path / ".cache" / "delivery_dispositions.ndjson"
    adapter = DispositionReceiptNdjsonAdapter(path)

    adapter.append({"phase": "intent", "branch": "a"})
    adapter.append({"phase": "committed", "branch": "a"})

    rows = [json.loads(line) for line in path.read_text().splitlines()]
    assert [row["phase"] for row in rows] == ["intent", "committed"]
    assert all(len(row["digest"]) == 64 for row in rows)
    assert rows[0]["digest"] != rows[1]["digest"]


def test_receipt_adapter_refuses_a_malformed_journal(tmp_path: Path) -> None:
    path = tmp_path / "journal.ndjson"
    path.write_text("not json\n")

    with pytest.raises(Exception, match="malformed"):
        DispositionReceiptNdjsonAdapter(path).append({"phase": "intent"})
    assert path.read_text() == "not json\n"


class _CliApplication:
    def __init__(self, verdict: str) -> None:
        self.verdict = verdict
        self.calls: list[dict[str, object]] = []

    def dispose_ownerless_claim(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        progress = kwargs.get("progress")
        if callable(progress):
            progress("checking claim")
        return {"verdict": self.verdict, "eligible": self.verdict != "refused"}


def test_cli_defaults_to_dry_run_and_keeps_progress_on_stderr(capsys: object) -> None:
    application = _CliApplication("eligible")

    code = main(
        ["dispose-ownerless-claim", "--branch", BRANCH],
        application_factory=lambda **_: application,
    )

    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert code == 0
    assert application.calls[0]["apply"] is False
    assert application.calls[0]["branch"] == BRANCH
    assert json.loads(captured.out)["verdict"] == "eligible"
    assert "checking claim" in captured.err
    assert "checking claim" not in captured.out


def test_cli_apply_passes_pins_and_refusal_exits_two(capsys: object) -> None:
    application = _CliApplication("refused")

    code = main(
        [
            "dispose-ownerless-claim",
            "--branch",
            BRANCH,
            "--apply",
            "--expected-claim-generation",
            "3",
            "--expected-head-sha",
            BASE,
            "--operator",
            "im",
            "--reason",
            "ownerless",
        ],
        application_factory=lambda **_: application,
    )

    payload = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert code == 2
    assert payload["verdict"] == "refused"
    assert application.calls[0] == {
        "branch": BRANCH,
        "apply": True,
        "expected_claim_generation": 3,
        "expected_head_sha": BASE,
        "operator": "im",
        "reason": "ownerless",
        "progress": application.calls[0]["progress"],
    }


def test_cli_apply_is_serialized_but_dry_run_is_not() -> None:
    from delivery_control import cli

    assert "dispose-ownerless-claim" in cli.APPLY_COMMANDS
    assert "close-terminal-issues" in cli.APPLY_COMMANDS
    assert "dispose-ownerless-claim" not in cli.MUTATING_COMMANDS


def test_service_terminalizes_through_the_real_registry_cas(tmp_path: Path) -> None:
    """Contract: the unchanged registry CLI accepts this exact active->abandoned CAS."""

    import worktree_registry as registry_module
    from delivery_control.adapters.module_runner import ModuleCommandRunner
    from delivery_control.adapters.registry import RegistryCliAdapter

    path = tmp_path / "ghost-worktree"
    state_path = tmp_path / "registry.json"
    registry_module.save_state(
        state_path,
        {
            "schema": registry_module.SCHEMA,
            "records": [
                {
                    "branch": BRANCH,
                    "path": str(path),
                    "status": "active",
                    "external_ids": ["DIRECT-GHOST"],
                    "base": BASE,
                    "scope": {
                        "schema": "kg.worktree.scope.v1",
                        "files": [{"operation": "modify", "path": "ops/a.py"}],
                    },
                    "claim_generation": 5,
                }
            ],
        },
    )
    script = OPS / "worktree_registry.py"
    adapter = RegistryCliAdapter(
        script_path=script,
        state_path=state_path,
        runner=ModuleCommandRunner(executable=script, main=registry_module.main),
    )
    receipts = FakeReceipts(FakeRegistry())
    service = OwnerlessClaimDisposalService(
        registry=adapter,
        registry_command=adapter,
        git_query=FakeGit(),
        github=FakeGitHub(),
        receipts=receipts,
    )

    report = service.dispose(
        branch=BRANCH,
        apply=True,
        expected_claim_generation=5,
        expected_head_sha=BASE,
        operator="im",
        reason="ghost claim",
    )

    assert report.applied is True
    persisted = registry_module.load_state(state_path)["records"][0]
    assert persisted["status"] == "abandoned"
    assert [row["phase"] for row in receipts.rows] == ["intent", "committed"]
