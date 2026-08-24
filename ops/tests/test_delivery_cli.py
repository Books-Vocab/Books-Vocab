from __future__ import annotations

import json
import sys
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

OPS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPS))

from delivery_control.cli import (
    DeliveryApplication,
    RuntimeStatusMap,
    _parser,
    main,
)
from delivery_control.domain.branch_lifecycle import (
    BranchAsset,
    BranchCleanupAction,
    BranchDisposition,
    BranchRegistryEvidence,
    BranchSide,
)
from delivery_control.domain.candidate_issues import (
    CandidateSeverity,
    CandidateSpec,
)
from delivery_control.domain.errors import CompareAndSwapConflict, PolicyViolation
from delivery_control.domain.models import CheckStatus, Scope
from delivery_control.domain.observations import (
    CanonicalCheckoutSnapshot,
    CheckSnapshot,
    FileChange,
    FileOperation,
    InventoryProblem,
    MainLandingSnapshot,
    MergeQueueEntrySnapshot,
    PhysicalWorktree,
    PullRequestInventory,
    PullRequestSnapshot,
    RegistryCollisionClaim,
    RegistryCollisionInventory,
    RegistryInventory,
    RegistrySnapshot,
    WorktreeSnapshot,
)
from delivery_control.domain.states import HoldKind
from delivery_control.domain.telemetry import (
    DurationSample,
    TelemetryReadResult,
)
from delivery_control.services.pr_contract import render_pull_request_body

BASE = "a" * 40
HEAD = "b" * 40
DIGEST = "c" * 64
BRANCH = "feat/cli"
WORKTREE = Path("/tmp/cli-worktree").resolve()
EVENT_START = datetime(2026, 8, 21, tzinfo=UTC)


def _record() -> RegistrySnapshot:
    return RegistrySnapshot(
        lane_id="DIRECT-CLI",
        branch=BRANCH,
        path=WORKTREE,
        status="active",
        scope=Scope.from_paths(modify=("ops/a.py",)),
        base_sha=BASE,
        claim_generation=2,
        owner_thread_id="thread-cli",
        handed_back_sha=HEAD,
        handback_claim_generation=2,
        handback_valid=True,
        handback_digest=DIGEST,
        handback_origin_main_sha=BASE,
        handed_back_at=EVENT_START,
    )


def _snapshot() -> WorktreeSnapshot:
    return WorktreeSnapshot(
        path=WORKTREE,
        branch=BRANCH,
        base_sha=BASE,
        parent_sha=BASE,
        head_sha=HEAD,
        clean=True,
        changes=(FileChange(FileOperation.MODIFY, "ops/a.py"),),
    )


class FakeRegistry:
    def __init__(self) -> None:
        self.record = _record()
        self.fail_resolve_once = False

    def get(self, lane_id: str) -> RegistrySnapshot | None:
        return self.record if lane_id == self.record.lane_id else None

    def list_records(self) -> RegistryInventory:
        return RegistryInventory((self.record,))

    def list_collision_claims(self) -> RegistryCollisionInventory:
        return RegistryCollisionInventory(
            (
                RegistryCollisionClaim(
                    self.record.lane_id,
                    self.record.branch,
                    self.record.scope,
                ),
            )
        )

    def find_exact_claim(
        self,
        *,
        lane_id: str,
        branch: str,
        path: Path,
        claim_generation: int,
    ) -> RegistrySnapshot | None:
        if (
            self.record.lane_id == lane_id
            and self.record.branch == branch
            and self.record.path == path
            and self.record.claim_generation == claim_generation
        ):
            return self.record
        return None

    def resolve(
        self,
        lane_id: str,
        disposition: str,
        *,
        expected_claim_generation: int,
        expected_branch: str,
        expected_path: str,
        expected_head_sha: str,
        terminal_proof=None,
    ) -> None:
        if self.fail_resolve_once:
            self.fail_resolve_once = False
            raise CompareAndSwapConflict("injected registry CAS failure")
        assert lane_id == self.record.lane_id
        assert expected_claim_generation == self.record.claim_generation
        assert expected_branch == self.record.branch
        assert Path(expected_path) == self.record.path
        assert expected_head_sha == self.record.handed_back_sha
        self.record = replace(self.record, status=disposition)

    def persist_handback(
        self, receipt: object, *, expected_claim_generation: int
    ) -> None:
        raise AssertionError("CLI must consume, not create, handbacks")

    def record_published_base(
        self,
        *,
        lane_id: str,
        expected_claim_generation: int,
        expected_branch: str,
        expected_path: str,
        expected_head_sha: str,
        expected_handback_base_sha: str,
        published_base_sha: str,
    ) -> None:
        assert lane_id == self.record.lane_id
        assert expected_claim_generation == self.record.claim_generation
        assert expected_branch == self.record.branch
        assert Path(expected_path) == self.record.path
        assert expected_head_sha == self.record.handed_back_sha
        assert expected_handback_base_sha == self.record.base_sha
        self.record = replace(self.record, published_base_sha=published_base_sha)


class FakeGit:
    def __init__(self) -> None:
        self.snapshot = _snapshot()
        self.remote: str | None = None
        self.local: str | None = HEAD
        self.worktrees = (PhysicalWorktree(WORKTREE, HEAD, BRANCH),)
        self.fail_remove_once = False
        self.main_local = BASE
        self.main_origin = BASE

    def inspect_worktree(self, path: Path, base_sha: str) -> WorktreeSnapshot:
        if path == Path("/repo"):
            assert base_sha == self.main_local
            return WorktreeSnapshot(
                path=path,
                branch="main",
                base_sha=base_sha,
                parent_sha=base_sha,
                head_sha=self.main_local,
                clean=True,
                changes=(),
            )
        assert path == WORKTREE and base_sha == BASE
        return self.snapshot

    def canonical_checkout(self) -> CanonicalCheckoutSnapshot:
        return CanonicalCheckoutSnapshot(Path("/repo"), "main", self.main_local, True)

    def list_worktrees(self) -> tuple[PhysicalWorktree, ...]:
        return self.worktrees

    def remote_branch_sha(self, branch: str) -> str | None:
        return self.remote

    def local_branch_sha(self, branch: str) -> str | None:
        return self.local

    def push_branch(
        self,
        *,
        worktree: Path,
        branch: str,
        expected_local_sha: str,
        expected_remote_sha: str | None = None,
    ) -> str:
        assert worktree == WORKTREE and branch == BRANCH
        assert expected_local_sha == HEAD and expected_remote_sha == self.remote
        self.remote = HEAD
        return HEAD

    def remove_worktree(self, path: Path, *, expected_head_sha: str) -> None:
        assert path == WORKTREE and expected_head_sha == HEAD
        if self.fail_remove_once:
            self.fail_remove_once = False
            raise CompareAndSwapConflict("injected worktree removal failure")
        self.worktrees = ()

    def delete_local_branch(self, branch: str, *, expected_head_sha: str) -> None:
        assert branch == BRANCH and expected_head_sha == HEAD
        self.local = None

    def delete_remote_branch(self, branch: str, *, expected_head_sha: str) -> None:
        self.remote = None

    def local_main_sha(self) -> str:
        return self.main_local

    def origin_main_sha(self) -> str:
        return self.main_origin

    def first_parent_landings(
        self, *, before_sha: str, after_sha: str
    ) -> tuple[MainLandingSnapshot, ...]:
        assert before_sha == BASE
        assert after_sha == HEAD
        return (
            MainLandingSnapshot(
                sha=HEAD,
                landed_at=EVENT_START.replace(minute=2),
            ),
        )

    def fast_forward_main(
        self, *, expected_local_sha: str, expected_origin_sha: str
    ) -> str:
        assert expected_local_sha == self.main_local
        assert expected_origin_sha == self.main_origin
        self.main_local = expected_origin_sha
        return expected_origin_sha


class FakeGitHub:
    def __init__(self) -> None:
        self.pull_request: PullRequestSnapshot | None = None
        self.branch_history: tuple[PullRequestSnapshot, ...] = ()
        self.branch_inventory_problems: tuple[InventoryProblem, ...] = ()
        self.publish_base = BASE
        self.queue_entry: MergeQueueEntrySnapshot | None = None
        self.recent_merges: tuple[datetime, ...] = ()
        self.readiness_dispatches: list[tuple[int, str, str]] = []

    def list_open_pull_requests(self) -> PullRequestInventory:
        return PullRequestInventory(
            () if self.pull_request is None else (self.pull_request,)
        )

    def find_open_pull_request(self, branch: str) -> PullRequestSnapshot | None:
        return self.pull_request

    def list_pull_requests_for_branch(self, branch: str) -> PullRequestInventory:
        if self.pull_request is None or self.pull_request.branch != branch:
            return PullRequestInventory(())
        return PullRequestInventory(
            self.branch_history + (self.pull_request,),
            self.branch_inventory_problems,
        )

    def trigger_readiness(
        self, *, number: int, branch: str, head_sha: str
    ) -> tuple[str, ...]:
        self.readiness_dispatches.append((number, branch, head_sha))
        return ("gh", "workflow", "run", "pr-readiness.yml")

    def create_pull_request(
        self, *, branch: str, title: str, body: str
    ) -> PullRequestSnapshot:
        self.pull_request = PullRequestSnapshot(
            number=41,
            url="https://example.test/pull/41",
            branch=branch,
            base_sha=self.publish_base,
            head_sha=HEAD,
            state="OPEN",
            draft=False,
            mergeable=True,
            title=title,
            body=body,
            node_id="PR_41",
            created_at=EVENT_START.replace(second=30),
        )
        return self.pull_request

    def update_pull_request(
        self,
        *,
        number: int,
        title: str,
        body: str,
        expected_head_sha: str,
    ) -> PullRequestSnapshot:
        raise AssertionError("new publication must not update")

    def get_pull_request(self, number: int) -> PullRequestSnapshot:
        assert self.pull_request is not None and number == 41
        return self.pull_request

    def changed_paths(self, number: int) -> tuple[str, ...]:
        return ("ops/a.py",)

    def branch_is_protected(self, branch: str) -> bool:
        return False

    def required_status_contexts(self, branch: str) -> tuple[str, ...]:
        return ("required",)

    def merge_queue_entry_id(self, pull_request_id: str) -> str | None:
        return None

    def merge_queue_entry_snapshot(
        self, pull_request_id: str
    ) -> MergeQueueEntrySnapshot | None:
        assert pull_request_id == "PR_41"
        return self.queue_entry

    def merge_queue_enabled(self, branch: str) -> bool:
        return True

    def required_check_snapshot(self, number: int) -> CheckSnapshot:
        return CheckSnapshot(
            status=CheckStatus.SUCCESS,
            head_sha=HEAD,
            observed_at=datetime(2026, 8, 21, tzinfo=UTC),
            names=("required",),
            started_at=EVENT_START.replace(second=40),
            completed_at=EVENT_START.replace(second=50),
        )

    def mark_ready(self, number: int) -> PullRequestSnapshot:
        return self.get_pull_request(number)

    def enqueue(
        self,
        *,
        number: int,
        expected_base_sha: str,
        expected_head_sha: str,
        expected_body: str,
    ) -> None:
        self.queue_entry = MergeQueueEntrySnapshot(
            "MQE_41", EVENT_START.replace(second=55)
        )

    def recent_merge_times(self, *, limit: int = 100) -> tuple[datetime, ...]:
        return self.recent_merges[:limit]


class MemoryTelemetry:
    def __init__(self) -> None:
        self.samples: dict[str, DurationSample] = {}

    def append(self, sample: DurationSample) -> bool:
        existing = self.samples.get(sample.sample_key)
        if existing == sample:
            return False
        if existing is not None:
            raise CompareAndSwapConflict("telemetry sample conflict")
        self.samples[sample.sample_key] = sample
        return True

    def read_since(self, since: datetime) -> TelemetryReadResult:
        return TelemetryReadResult(
            tuple(
                sample
                for sample in self.samples.values()
                if sample.completed_at >= since
            )
        )


class FailingTelemetry(MemoryTelemetry):
    def append(self, sample: DurationSample) -> bool:
        raise OSError("telemetry disk unavailable")


def _historical_pull_request(
    *, number: int = 40, state: str = "MERGED"
) -> PullRequestSnapshot:
    return PullRequestSnapshot(
        number=number,
        url=f"https://example.test/pull/{number}",
        branch=BRANCH,
        base_sha=BASE,
        head_sha="d" * 40,
        state=state,
        draft=False,
        mergeable=True,
        title="historical delivery",
        body="historical delivery body",
        node_id=f"PR_{number}",
        created_at=EVENT_START.replace(second=10),
        merged_at=EVENT_START.replace(second=20) if state == "MERGED" else None,
    )


def _application(
    registry: FakeRegistry, git: FakeGit, github: FakeGitHub
) -> DeliveryApplication:
    return DeliveryApplication(
        repo=Path("/repo"),
        git=git,
        github=github,
        registry=registry,
        runtime=RuntimeStatusMap({"thread-cli": "running"}),
        telemetry=MemoryTelemetry(),
    )


def test_publish_ignores_merged_branch_history_for_published_base() -> None:
    registry = FakeRegistry()
    git = FakeGit()
    github = FakeGitHub()
    github.branch_history = (_historical_pull_request(),)

    _application(registry, git, github).publish(
        lane_id="DIRECT-CLI", title="fix: exact delivery"
    )

    assert registry.record.published_base_sha == BASE


def test_publish_rejects_multiple_current_open_branch_prs() -> None:
    registry = FakeRegistry()
    git = FakeGit()
    github = FakeGitHub()
    github.branch_history = (_historical_pull_request(state="OPEN"),)

    with pytest.raises(
        PolicyViolation, match="published branch does not map to one unique PR"
    ):
        _application(registry, git, github).publish(
            lane_id="DIRECT-CLI", title="fix: exact delivery"
        )


def test_publish_rejects_branch_history_inventory_problems() -> None:
    registry = FakeRegistry()
    git = FakeGit()
    github = FakeGitHub()
    github.branch_inventory_problems = (
        InventoryProblem("github", BRANCH, "history page unavailable"),
    )

    with pytest.raises(
        PolicyViolation, match="published branch does not map to one unique PR"
    ):
        _application(registry, git, github).publish(
            lane_id="DIRECT-CLI", title="fix: exact delivery"
        )


def test_publish_command_makes_github_durable_then_releases_local_assets() -> None:
    registry = FakeRegistry()
    git = FakeGit()
    github = FakeGitHub()
    app = DeliveryApplication(
        repo=Path("/repo"),
        git=git,
        github=github,
        registry=registry,
        runtime=RuntimeStatusMap({"thread-cli": "running"}),
        telemetry=MemoryTelemetry(),
    )

    result = app.publish(lane_id="DIRECT-CLI", title="fix: exact delivery")

    assert result["publication"].pull_request.number == 41
    assert registry.record.published_base_sha == BASE
    assert registry.record.status == "published"
    assert git.worktrees == ()
    assert git.local is None
    assert git.remote == HEAD


def test_publish_records_github_advanced_base_without_rewriting_handback() -> None:
    registry = FakeRegistry()
    git = FakeGit()
    github = FakeGitHub()
    github.publish_base = "d" * 40
    app = DeliveryApplication(
        repo=Path("/repo"),
        git=git,
        github=github,
        registry=registry,
        runtime=RuntimeStatusMap({"thread-cli": "running"}),
        telemetry=MemoryTelemetry(),
    )

    app.publish(lane_id="DIRECT-CLI", title="fix: exact delivery")

    assert registry.record.base_sha == BASE
    assert registry.record.published_base_sha == "d" * 40


def test_publish_and_enqueue_record_exact_duration_samples() -> None:
    registry = FakeRegistry()
    git = FakeGit()
    github = FakeGitHub()
    telemetry = MemoryTelemetry()
    app = DeliveryApplication(
        repo=Path("/repo"),
        git=git,
        github=github,
        registry=registry,
        runtime=RuntimeStatusMap({"thread-cli": "running"}),
        telemetry=telemetry,
        clock=lambda: EVENT_START.replace(minute=1),
    )

    published = app.publish(lane_id="DIRECT-CLI", title="fix: exact delivery")
    queued = app.enqueue(pull_request_number=41)

    assert published["telemetry_warnings"] == ()
    assert queued["telemetry_warnings"] == ()
    assert sorted(sample.metric.value for sample in telemetry.samples.values()) == [
        "handback_to_pr",
        "pr_to_required_start",
        "required_duration",
        "required_success_to_enqueue",
    ]


def test_telemetry_failure_does_not_block_durable_publication_or_cleanup() -> None:
    registry = FakeRegistry()
    git = FakeGit()
    app = DeliveryApplication(
        repo=Path("/repo"),
        git=git,
        github=FakeGitHub(),
        registry=registry,
        runtime=RuntimeStatusMap({"thread-cli": "running"}),
        telemetry=FailingTelemetry(),
    )

    result = app.publish(lane_id="DIRECT-CLI", title="fix: exact delivery")

    assert registry.record.status == "published"
    assert git.worktrees == ()
    assert result["telemetry_warnings"][0].code == "telemetry_append_failed"


def test_telemetry_failure_does_not_block_cleanup_or_main_sync() -> None:
    registry = FakeRegistry()
    git = FakeGit()
    github = FakeGitHub()
    publisher = DeliveryApplication(
        repo=Path("/repo"),
        git=git,
        github=github,
        registry=registry,
        runtime=RuntimeStatusMap({"thread-cli": "running"}),
        telemetry=MemoryTelemetry(),
    )
    publisher.publish(lane_id="DIRECT-CLI", title="fix: exact delivery")
    assert github.pull_request is not None
    github.pull_request = replace(
        github.pull_request,
        state="MERGED",
        merged_at=EVENT_START.replace(minute=2),
    )
    github.recent_merges = (EVENT_START.replace(minute=2),)
    app = DeliveryApplication(
        repo=Path("/repo"),
        git=git,
        github=github,
        registry=registry,
        runtime=RuntimeStatusMap({"thread-cli": "running"}),
        telemetry=FailingTelemetry(),
        clock=lambda: EVENT_START.replace(minute=3),
    )

    cleaned = app.cleanup_merged(41)
    git.main_origin = HEAD
    synced = app.sync_main()

    assert registry.record.status == "merged"
    assert git.remote is None
    assert git.main_local == HEAD
    assert cleaned["telemetry_warnings"][0].code == "telemetry_append_failed"
    assert synced["telemetry_warnings"][0].code == "telemetry_append_failed"


def test_cleanup_and_main_sync_record_post_merge_durations() -> None:
    registry = FakeRegistry()
    git = FakeGit()
    github = FakeGitHub()
    telemetry = MemoryTelemetry()
    app = DeliveryApplication(
        repo=Path("/repo"),
        git=git,
        github=github,
        registry=registry,
        runtime=RuntimeStatusMap({"thread-cli": "running"}),
        telemetry=telemetry,
        clock=lambda: EVENT_START.replace(minute=3),
    )
    app.publish(lane_id="DIRECT-CLI", title="fix: exact delivery")
    assert github.pull_request is not None
    github.pull_request = replace(
        github.pull_request,
        state="MERGED",
        merged_at=EVENT_START.replace(minute=2),
    )
    github.recent_merges = (EVENT_START.replace(minute=2),)

    cleaned = app.cleanup_merged(41)
    git.main_origin = HEAD
    synced = app.sync_main()

    assert cleaned["cleanup"].disposition == "merged"
    assert cleaned["telemetry_warnings"] == ()
    assert synced["sync"].after_sha == HEAD
    assert synced["telemetry_warnings"] == ()
    assert {
        sample.metric.value: sample.duration_seconds
        for sample in telemetry.samples.values()
        if sample.metric.value.startswith("merge_to_")
    } == {"merge_to_cleanup": 60.0, "merge_to_sync": 60.0}


def test_publish_retry_recovers_after_pr_creation_then_registry_cas_failure() -> None:
    registry = FakeRegistry()
    registry.fail_resolve_once = True
    git = FakeGit()
    github = FakeGitHub()
    app = DeliveryApplication(
        repo=Path("/repo"),
        git=git,
        github=github,
        registry=registry,
        runtime=RuntimeStatusMap({"thread-cli": "running"}),
        telemetry=MemoryTelemetry(),
    )

    with pytest.raises(CompareAndSwapConflict, match="injected registry"):
        app.publish(lane_id="DIRECT-CLI", title="fix: exact delivery")
    assert github.pull_request is not None
    assert git.remote == HEAD
    assert registry.record.status == "active"

    app.publish(lane_id="DIRECT-CLI", title="fix: exact delivery")

    assert registry.record.status == "published"
    assert git.worktrees == ()
    assert git.local is None


def test_release_retry_recovers_after_registry_publish_then_cleanup_failure() -> None:
    registry = FakeRegistry()
    git = FakeGit()
    git.fail_remove_once = True
    github = FakeGitHub()
    app = DeliveryApplication(
        repo=Path("/repo"),
        git=git,
        github=github,
        registry=registry,
        runtime=RuntimeStatusMap({"thread-cli": "running"}),
        telemetry=MemoryTelemetry(),
    )

    with pytest.raises(CompareAndSwapConflict, match="removal"):
        app.publish(lane_id="DIRECT-CLI", title="fix: exact delivery")
    assert registry.record.status == "cleanup_pending"
    assert git.worktrees

    app.release_published(41)

    assert registry.record.status == "published"
    assert git.worktrees == ()
    assert git.local is None


def test_cli_queue_preserves_explicit_hold_as_typed_input(capsys: object) -> None:
    class FakeApplication:
        def __init__(self) -> None:
            self.calls: list[object] = []

        def enqueue(
            self, *, pull_request_number: int, holds: frozenset[object]
        ) -> object:
            self.calls.append((pull_request_number, holds))
            return {"queued": False}

    application = FakeApplication()

    assert (
        main(
            ["queue", "--pr", "41", "--hold", "security"],
            application_factory=lambda **_: application,
        )
        == 0
    )

    captured = capsys.readouterr()  # type: ignore[attr-defined]
    payload = json.loads(captured.out)
    assert payload["ok"] is True
    assert application.calls[0][0] == 41
    assert {item.value for item in application.calls[0][1]} == {"security"}


def test_cli_requires_an_explicit_hold_or_clearance_action(capsys: object) -> None:
    class FakeApplication:
        def __init__(self) -> None:
            self.calls: list[object] = []

        def reconcile_holds(
            self,
            *,
            pull_request_number: int,
            holds: frozenset[object],
            clear_all: bool,
        ) -> object:
            self.calls.append((pull_request_number, holds, clear_all))
            return {"updated": True}

    application = FakeApplication()

    assert (
        main(
            ["reconcile-holds", "--pr", "41", "--clear-all"],
            application_factory=lambda **_: application,
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert payload["ok"] is True
    assert application.calls == [(41, frozenset(), True)]


def test_application_reconcile_holds_preserves_keyword_compatibility(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from delivery_control import application_services

    calls: list[object] = []

    class StubHoldService:
        def __init__(self, *, query: object, command: object) -> None:
            calls.append((query, command))

        def reconcile(
            self,
            *,
            number: int,
            holds: frozenset[object],
            clear_all: bool,
        ) -> object:
            calls.append((number, holds, clear_all))
            return {"updated": True}

    monkeypatch.setattr(
        application_services.hold_services,
        "HoldService",
        StubHoldService,
    )
    github = FakeGitHub()
    application = DeliveryApplication(
        repo=Path("/repo"),
        git=FakeGit(),
        github=github,
        registry=FakeRegistry(),
        runtime=RuntimeStatusMap({}),
        telemetry=MemoryTelemetry(),
    )

    result = application.reconcile_holds(
        pull_request_number=41,
        holds=frozenset({HoldKind.SECURITY}),
        clear_all=False,
    )

    assert result == {"updated": True}
    assert calls == [
        (github, github),
        (41, frozenset({HoldKind.SECURITY}), False),
    ]


def test_cli_routes_exact_post_publication_abandonment(capsys: object) -> None:
    class FakeApplication:
        def __init__(self) -> None:
            self.calls: list[int] = []

        def abandon_pr(self, pull_request_number: int) -> object:
            self.calls.append(pull_request_number)
            return {"registry_status": "abandoned"}

    application = FakeApplication()

    assert (
        main(
            ["abandon-pr", "--pr", "41"],
            application_factory=lambda **_: application,
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert payload["ok"] is True
    assert application.calls == [41]


def test_cli_routes_legacy_abandoned_branch_cleanup(capsys: object) -> None:
    class FakeApplication:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def cleanup_abandoned(self, branch: str) -> object:
            self.calls.append(branch)
            return {"disposition": "abandoned"}

    application = FakeApplication()

    assert (
        main(
            ["cleanup-abandoned", "--branch", "debug/no-pr"],
            application_factory=lambda **_: application,
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert payload["ok"] is True
    assert application.calls == ["debug/no-pr"]


def test_cli_routes_explicit_abandoned_handback_discard(capsys: object) -> None:
    class FakeApplication:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str, str, str]] = []

        def discard_abandoned_handback(
            self,
            *,
            branch: str,
            expected_head_sha: str,
            operator: str,
            reason: str,
        ) -> object:
            self.calls.append((branch, expected_head_sha, operator, reason))
            return {"disposition": "abandoned_handback_discarded"}

    application = FakeApplication()
    head = "b" * 40

    assert (
        main(
            [
                "discard-abandoned-handback",
                "--branch",
                "debug/orphan",
                "--expected-head-sha",
                head,
                "--operator",
                "supervisor",
                "--reason",
                "ownerless clean handback explicitly discarded",
            ],
            application_factory=lambda **_: application,
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert payload["result"]["disposition"] == "abandoned_handback_discarded"
    assert application.calls == [
        (
            "debug/orphan",
            head,
            "supervisor",
            "ownerless clean handback explicitly discarded",
        )
    ]


def test_cli_routes_unregistered_orphan_branch_discard(capsys: object) -> None:
    class FakeApplication:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str, str, str]] = []

        def discard_orphan_branch(
            self,
            *,
            branch: str,
            expected_head_sha: str,
            operator: str,
            reason: str,
        ) -> object:
            self.calls.append((branch, expected_head_sha, operator, reason))
            return {"disposition": "orphan_local_discarded"}

    application = FakeApplication()
    head = "b" * 40

    assert (
        main(
            [
                "discard-orphan-branch",
                "--branch",
                "feat/orphan",
                "--expected-head-sha",
                head,
                "--operator",
                "supervisor",
                "--reason",
                "ancestor branch has no unmerged changes",
            ],
            application_factory=lambda **_: application,
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert payload["result"]["disposition"] == "orphan_local_discarded"
    assert application.calls == [
        (
            "feat/orphan",
            head,
            "supervisor",
            "ancestor branch has no unmerged changes",
        )
    ]


def test_cli_exposes_dogfood_preflight_as_read_only_json(capsys: object) -> None:
    class FakeApplication:
        def dogfood_preflight(
            self, *, supervision_worktree_paths: tuple[Path, ...]
        ) -> object:
            assert supervision_worktree_paths == (Path("/supervision"),)
            return {"ready": False, "blockers": ["source inventory"]}

    assert (
        main(
            ["dogfood-preflight", "--supervision-worktree", "/supervision"],
            application_factory=lambda **_: FakeApplication(),
        )
        == 2
    )

    payload = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert payload["command"] == "dogfood-preflight"
    assert payload["result"]["ready"] is False


def test_cli_exposes_branch_audit_and_forwards_supervision_paths(
    capsys: object,
) -> None:
    class FakeApplication:
        def branch_audit(
            self, *, supervision_worktree_paths: tuple[Path, ...]
        ) -> object:
            assert supervision_worktree_paths == (Path("/supervision"),)
            return {"schema": "kg.delivery.branch-audit.v1", "complete": True}

    assert (
        main(
            [
                "branch-audit",
                "--supervision-worktree",
                "/supervision",
            ],
            application_factory=lambda **_: FakeApplication(),
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert payload["command"] == "branch-audit"
    assert payload["verdict"] == "complete"
    assert payload["result"]["schema"] == "kg.delivery.branch-audit.v1"


def test_cli_serializes_bounded_unreachable_commit_evidence(capsys: object) -> None:
    commit_sha = "a" * 40
    evidence = {
        "schema": "kg.delivery.unreachable-commit.v1",
        "commit_sha": commit_sha,
        "parent_shas": ["b" * 40],
        "subject": "preserve object",
        "unreachable": True,
        "changed_paths": ["ops/example.py"],
        "changed_path_count": 1,
        "changed_paths_truncated": False,
        "change_fingerprint": "c" * 64,
        "disposition": "preserve_for_owner_correlation",
        "source_problem_scope": None,
        "next_step": "correlate with an owner, Issue, or PR before any lifecycle action",
        "complete": True,
        "error": None,
    }

    class FakeApplication:
        def branch_audit(
            self, *, supervision_worktree_paths: tuple[Path, ...]
        ) -> object:
            return {
                "schema": "kg.delivery.branch-audit.v1",
                "complete": True,
                "unreachable_commit_count": 3998,
                "unreachable_commit_sample": [commit_sha],
                "unreachable_commit_evidence": [evidence],
            }

    assert (
        main(
            ["branch-audit"],
            application_factory=lambda **_: FakeApplication(),
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    result = payload["result"]
    assert result["unreachable_commit_count"] == 3998
    assert result["unreachable_commit_sample"] == [commit_sha]
    assert result["unreachable_commit_evidence"][0]["commit_sha"] == commit_sha
    assert result["unreachable_commit_evidence"][0]["changed_paths"] == [
        "ops/example.py"
    ]


def test_cli_serializes_additive_branch_registry_evidence(capsys: object) -> None:
    evidence = BranchRegistryEvidence(
        lane_id="LANE-CLI-EVIDENCE",
        branch="feat/cli-evidence",
        path="/tmp/cli-evidence",
        status="published",
        claim_generation=4,
        base_sha=BASE,
        published_base_sha=HEAD,
        handed_back_sha=HEAD,
        handback_digest=DIGEST,
        owner_thread_id=None,
        scope_paths=("ops/a.py",),
        external_ids=(),
    )
    asset = BranchAsset(
        branch="feat/cli-evidence",
        side=BranchSide.REMOTE,
        sha=HEAD,
        disposition=BranchDisposition.ACTIVE_OR_PUBLISHED_LANE,
        cleanup_action=BranchCleanupAction.FOLLOW_OWNER_LANE,
        reason="owned lane",
        registry_evidence=(evidence,),
        paired_ref_side=BranchSide.LOCAL,
        paired_ref_sha=BASE,
    )

    class FakeApplication:
        def branch_audit(
            self, *, supervision_worktree_paths: tuple[Path, ...]
        ) -> object:
            return {
                "schema": "kg.delivery.branch-audit.v1",
                "complete": True,
                "assets": (asset,),
            }

    assert (
        main(
            ["branch-audit"],
            application_factory=lambda **_: FakeApplication(),
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    serialized = payload["result"]["assets"][0]["registry_evidence"][0]
    assert serialized["lane_id"] == "LANE-CLI-EVIDENCE"
    assert serialized["published_base_sha"] == HEAD
    assert serialized["owner_thread_id"] is None
    assert serialized["external_ids"] == []
    asset_serialized = payload["result"]["assets"][0]
    assert asset_serialized["paired_ref_side"] == "local"
    assert asset_serialized["paired_ref_sha"] == BASE


def test_cli_marks_incomplete_branch_audit_as_observation_without_transport_error(
    capsys: object,
) -> None:
    class FakeApplication:
        def branch_audit(
            self, *, supervision_worktree_paths: tuple[Path, ...]
        ) -> object:
            return {
                "schema": "kg.delivery.branch-audit.v1",
                "complete": False,
                "source_problem_actions": [{"category": "registry_source_problem"}],
            }

    assert (
        main(
            ["branch-audit"],
            application_factory=lambda **_: FakeApplication(),
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert payload["ok"] is True
    assert payload["verdict"] == "incomplete"
    assert payload["result"]["source_problem_actions"]


def test_cli_routes_branch_content_inspection(capsys: object) -> None:
    class FakeApplication:
        def branch_inspect(
            self, *, branch: str, expected_head_sha: str | None
        ) -> object:
            assert branch == "feat/unlanded"
            assert expected_head_sha == "b" * 40
            return {
                "schema": "kg.delivery.branch-content.v1",
                "complete": True,
                "base_is_ancestor": False,
            }

    assert (
        main(
            [
                "branch-inspect",
                "--branch",
                "feat/unlanded",
                "--expected-head-sha",
                "b" * 40,
            ],
            application_factory=lambda **_: FakeApplication(),
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["result"]["base_is_ancestor"] is False


def test_cli_routes_unreachable_commit_inspection(capsys: object) -> None:
    class FakeApplication:
        def unreachable_commit_inspect(
            self, *, commit_sha: str, max_paths: int
        ) -> object:
            assert commit_sha == "a" * 40
            assert max_paths == 17
            return {
                "schema": "kg.delivery.unreachable-commit.v1",
                "complete": True,
                "unreachable": True,
                "disposition": "preserve_for_owner_correlation",
            }

    assert (
        main(
            [
                "unreachable-commit-inspect",
                "--commit",
                "a" * 40,
                "--max-paths",
                "17",
            ],
            application_factory=lambda **_: FakeApplication(),
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["command"] == "unreachable-commit-inspect"
    assert payload["result"]["disposition"] == "preserve_for_owner_correlation"


def test_cli_keeps_incomplete_unreachable_observation_transport_success(
    capsys: object,
) -> None:
    class FakeApplication:
        def unreachable_commit_inspect(
            self, *, commit_sha: str, max_paths: int
        ) -> object:
            assert commit_sha == "a" * 40
            assert max_paths == 17
            return {
                "schema": "kg.delivery.unreachable-commit.v1",
                "complete": False,
                "source_problem_scope": "git_objects",
                "disposition": "preserve_with_source_problem",
            }

    assert (
        main(
            [
                "unreachable-commit-inspect",
                "--commit",
                "a" * 40,
                "--max-paths",
                "17",
            ],
            application_factory=lambda **_: FakeApplication(),
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["verdict"] == "incomplete"
    assert payload["result"]["source_problem_scope"] == "git_objects"


def test_cli_routes_paged_branch_review_plan_as_observation(capsys: object) -> None:
    class FakeApplication:
        def branch_review_plan(self, *, offset: int, limit: int) -> object:
            assert offset == 5
            assert limit == 3
            return {
                "schema": "kg.delivery.branch-content-review-plan.v1",
                "complete": False,
                "remaining_count": 7,
            }

    assert (
        main(
            ["branch-review-plan", "--offset", "5", "--limit", "3"],
            application_factory=lambda **_: FakeApplication(),
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["command"] == "branch-review-plan"
    assert payload["result"]["remaining_count"] == 7


def test_cli_routes_explicit_unregistered_branch_discard(capsys: object) -> None:
    class FakeApplication:
        def discard_unregistered_branch(
            self,
            *,
            branch: str,
            expected_head_sha: str,
            expected_content_fingerprint: str,
            operator: str,
            reason: str,
            confirm_unmerged: bool,
        ) -> object:
            assert branch == "feat/unlanded"
            assert expected_head_sha == "b" * 40
            assert expected_content_fingerprint == "c" * 64
            assert operator == "supervisor"
            assert reason == "explicitly reviewed"
            assert confirm_unmerged
            return {"disposition": "unregistered_local_branch_discarded"}

    assert (
        main(
            [
                "discard-unregistered-branch",
                "--branch",
                "feat/unlanded",
                "--expected-head-sha",
                "b" * 40,
                "--expected-content-fingerprint",
                "c" * 64,
                "--operator",
                "supervisor",
                "--reason",
                "explicitly reviewed",
                "--confirm-unmerged",
            ],
            application_factory=lambda **_: FakeApplication(),
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["result"]["disposition"] == "unregistered_local_branch_discarded"


@pytest.mark.parametrize("command", ["inspect", "metrics", "plan"])
def test_cli_forwards_supervision_worktrees_for_observation_commands(
    command: str,
    capsys: object,
) -> None:
    class FakeApplication:
        def inspect(self, *, supervision_worktree_paths: tuple[Path, ...]) -> object:
            assert supervision_worktree_paths == (Path("/supervision"),)
            return {"lanes": []}

        def metrics(self, *, supervision_worktree_paths: tuple[Path, ...]) -> object:
            assert supervision_worktree_paths == (Path("/supervision"),)
            return {"physical_worktrees": 0}

        def plan(self, *, supervision_worktree_paths: tuple[Path, ...]) -> object:
            assert supervision_worktree_paths == (Path("/supervision"),)
            return {"decision": {"actions": []}}

    assert (
        main(
            [command, "--supervision-worktree", "/supervision"],
            application_factory=lambda **_: FakeApplication(),
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert payload["command"] == command


def test_cli_exposes_watchdog_without_dispatching(capsys: object) -> None:
    class FakeApplication:
        def watchdog(
            self,
            *,
            supervisor_thread_id: str,
            stale_after_seconds: int,
        ) -> object:
            assert supervisor_thread_id == "supervisor-thread"
            assert stale_after_seconds == 300
            return {"action": "noop", "reason": "lease is valid"}

    assert (
        main(
            [
                "--runtime-status-file",
                "/runtime/supervisor.json",
                "watchdog",
                "--supervisor-thread",
                "supervisor-thread",
            ],
            application_factory=lambda **_: FakeApplication(),
        )
        == 2
    )

    payload = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert payload["command"] == "watchdog"
    assert payload["result"]["action"] == "noop"
    assert payload["verdict"] == "observation"
    assert payload["dispatch_authorized"] is False


@pytest.mark.parametrize("command", ["watchdog", "watchdog-claim"])
def test_watchdog_help_documents_required_global_runtime_receipt(
    command: str, capsys: object
) -> None:
    with pytest.raises(SystemExit) as caught:
        _parser().parse_args([command, "--help"])

    assert caught.value.code == 0
    help_text = capsys.readouterr().out  # type: ignore[attr-defined]
    normalized_help = " ".join(help_text.split())
    assert "--runtime-status-file PATH" in normalized_help
    assert f"before the {command} subcommand" in normalized_help


@pytest.mark.parametrize(
    ("command", "required_phrases"),
    [
        (
            "watchdog",
            (
                "read-only observation",
                "verdict=observation, dispatch_authorized=false, exit 2",
                "must not retry or wake",
            ),
        ),
        (
            "watchdog-claim",
            (
                "only verdict=wake-authorized, action=wake, wake_claimed=true, dispatch_authorized=true may exit 0",
                "noop/escalate/wake_claimed=false/claim conflict are valid no-wake observations",
                "ok=true, verdict=no-wake, exit 2",
                "must not retry or wake",
            ),
        ),
    ],
)
def test_watchdog_help_documents_dispatch_boundary(
    command: str, required_phrases: tuple[str, ...], capsys: object
) -> None:
    with pytest.raises(SystemExit) as caught:
        _parser().parse_args([command, "--help"])

    assert caught.value.code == 0
    normalized_help = " ".join(capsys.readouterr().out.split())  # type: ignore[attr-defined]
    for phrase in required_phrases:
        assert phrase in normalized_help


def test_cli_preserves_command_exit_when_stdout_pipe_closes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from delivery_control import cli

    class FakeApplication:
        def inspect(self, *, supervision_worktree_paths: tuple[Path, ...]) -> object:
            assert supervision_worktree_paths == ()
            return {"lanes": []}

    def broken_print(*args: object, **kwargs: object) -> None:
        raise BrokenPipeError("pipe closed")

    monkeypatch.setattr(cli, "print", broken_print, raising=False)

    assert (
        main(
            ["inspect"],
            application_factory=lambda **_: FakeApplication(),
        )
        == 0
    )


@pytest.mark.parametrize("command", ["watchdog", "watchdog-claim"])
def test_cli_rejects_watchdog_commands_without_runtime_status_file(
    command: str, capsys: object
) -> None:
    class FakeApplication:
        def watchdog(
            self,
            *,
            supervisor_thread_id: str,
            stale_after_seconds: int,
        ) -> object:
            raise AssertionError("watchdog must not run without a receipt path")

        def watchdog_claim(
            self,
            *,
            supervisor_thread_id: str,
            stale_after_seconds: int,
        ) -> object:
            raise AssertionError("watchdog-claim must not run without a receipt path")

    assert (
        main(
            [command, "--supervisor-thread", "supervisor-thread"],
            application_factory=lambda **_: FakeApplication(),
        )
        == 1
    )

    payload = json.loads(capsys.readouterr().err)  # type: ignore[attr-defined]
    assert payload["ok"] is False
    assert payload["error"] == f"{command} requires --runtime-status-file"


def test_cli_exposes_watchdog_claim_before_external_dispatch(capsys: object) -> None:
    class FakeApplication:
        def watchdog_claim(
            self,
            *,
            supervisor_thread_id: str,
            stale_after_seconds: int,
        ) -> object:
            assert supervisor_thread_id == "supervisor-thread"
            assert stale_after_seconds == 300
            return {
                "action": "wake",
                "wake_id": "wake-1",
                "wake_claimed": True,
            }

    assert (
        main(
            [
                "--runtime-status-file",
                "/runtime/supervisor.json",
                "watchdog-claim",
                "--supervisor-thread",
                "supervisor-thread",
            ],
            application_factory=lambda **_: FakeApplication(),
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert payload["command"] == "watchdog-claim"
    assert payload["result"]["wake_claimed"] is True
    assert payload["dispatch_authorized"] is True
    assert payload["verdict"] == "wake-authorized"


@pytest.mark.parametrize(
    ("result", "expected_exit", "expected_verdict"),
    [
        (
            {"action": "noop", "reason": "lease is valid", "wake_claimed": False},
            2,
            "no-wake",
        ),
        (
            {
                "action": "escalate",
                "reason": "wake already issued for current stale receipt",
                "wake_claimed": False,
            },
            2,
            "no-wake",
        ),
        (
            {"action": "wake", "wake_id": "wake-1", "wake_claimed": False},
            2,
            "no-wake",
        ),
    ],
)
def test_watchdog_claim_no_wake_is_not_a_dispatch_success(
    result: dict[str, object],
    expected_exit: int,
    expected_verdict: str,
    capsys: object,
) -> None:
    class FakeApplication:
        def watchdog_claim(
            self,
            *,
            supervisor_thread_id: str,
            stale_after_seconds: int,
        ) -> object:
            assert supervisor_thread_id == "supervisor-thread"
            assert stale_after_seconds == 300
            return result

    assert (
        main(
            [
                "--runtime-status-file",
                "/runtime/supervisor.json",
                "watchdog-claim",
                "--supervisor-thread",
                "supervisor-thread",
            ],
            application_factory=lambda **_: FakeApplication(),
        )
        == expected_exit
    )

    payload = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert payload["ok"] is True
    assert payload["command"] == "watchdog-claim"
    assert payload["verdict"] == expected_verdict
    assert payload["dispatch_authorized"] is False
    assert payload["result"] == result


@pytest.mark.parametrize(
    "result",
    [
        {"action": "noop", "reason": "runtime is frozen", "wake_claimed": False},
        {
            "action": "wake",
            "reason": "stale runtime is eligible",
            "wake_id": "wake-1",
            "wake_claimed": False,
        },
        {
            "action": "escalate",
            "reason": "runtime receipt is missing",
            "wake_claimed": False,
        },
        {
            "action": "escalate",
            "reason": "runtime timestamp is in the future",
            "wake_claimed": False,
        },
    ],
)
def test_watchdog_read_only_observation_is_never_dispatch_authorized(
    result: dict[str, object], capsys: object
) -> None:
    class FakeApplication:
        def watchdog(
            self,
            *,
            supervisor_thread_id: str,
            stale_after_seconds: int,
        ) -> object:
            assert supervisor_thread_id == "supervisor-thread"
            assert stale_after_seconds == 300
            return result

    assert (
        main(
            [
                "--runtime-status-file",
                "/runtime/supervisor.json",
                "watchdog",
                "--supervisor-thread",
                "supervisor-thread",
            ],
            application_factory=lambda **_: FakeApplication(),
        )
        == 2
    )

    payload = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert payload["command"] == "watchdog"
    assert payload["ok"] is True
    assert payload["verdict"] == "observation"
    assert payload["dispatch_authorized"] is False
    assert payload["result"] == result


def test_cli_publishes_atomic_runtime_receipt(tmp_path: Path, capsys: object) -> None:
    status_path = tmp_path / "runtime" / "supervisor.json"

    assert (
        main(
            [
                "--repo",
                str(tmp_path),
                "--runtime-status-file",
                str(status_path),
                "runtime-receipt",
                "--thread-id",
                "supervisor-thread",
                "--state",
                "running",
                "--cycle-id",
                "cycle-1",
                "--lease-seconds",
                "600",
                "--clear-last-action",
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert payload["command"] == "runtime-receipt"
    assert payload["result"]["thread_id"] == "supervisor-thread"
    assert payload["result"]["state"] == "running"
    assert status_path.exists()


def test_runtime_status_file_fails_closed_for_unlisted_owner(tmp_path: Path) -> None:
    path = tmp_path / "runtime.json"
    path.write_text(json.dumps({"thread-1": "running"}), encoding="utf-8")

    runtime = RuntimeStatusMap.from_file(path)

    assert runtime.owner_status("thread-1") == "running"
    assert runtime.owner_status("thread-unknown") == "unknown"


def test_cli_validate_pr_body_uses_machine_receipt_not_workflow_regex(
    tmp_path: Path, capsys: object
) -> None:
    record = _record()
    receipt = DeliveryApplication(
        repo=Path("/repo"),
        git=FakeGit(),
        github=FakeGitHub(),
        registry=FakeRegistry(),
        runtime=RuntimeStatusMap(),
        telemetry=MemoryTelemetry(),
    ).receipt(record.lane_id)
    body_path = tmp_path / "body.md"
    body_path.write_text(render_pull_request_body(receipt), encoding="utf-8")

    assert (
        main(
            [
                "validate-pr-body",
                "--head-sha",
                receipt.head_sha,
                "--body-file",
                str(body_path),
            ],
            application_factory=lambda **_: object(),
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert payload["result"]["head_sha"] == receipt.head_sha


def test_cli_renders_and_validates_candidate_contract(
    tmp_path: Path, capsys: object
) -> None:
    spec = CandidateSpec(
        CandidateSeverity.P2,
        20,
        Scope.from_paths(modify=("ops/example.py",)),
        ("Focused proof is green.",),
    )
    payload_path = tmp_path / "candidate.json"
    payload_path.write_text(json.dumps(spec.to_payload()), encoding="utf-8")

    assert (
        main(
            ["render-candidate-body", "--payload-file", str(payload_path)],
            application_factory=lambda **_: object(),
        )
        == 0
    )
    rendered = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    body_path = tmp_path / "candidate.md"
    body_path.write_text(rendered["result"]["body"], encoding="utf-8")

    assert (
        main(
            ["validate-candidate-body", "--body-file", str(body_path)],
            application_factory=lambda **_: object(),
        )
        == 0
    )
    validated = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert validated["result"]["scope"]["files"][0]["path"] == "ops/example.py"


def test_cli_exposes_exact_required_trigger(capsys: object) -> None:
    class FakeApplication:
        def __init__(self) -> None:
            self.calls: list[int] = []

        def trigger_required(self, pull_request_number: int) -> object:
            self.calls.append(pull_request_number)
            return {"dispatched": True, "merge_eligibility_assessed": False}

    application = FakeApplication()

    assert (
        main(
            ["trigger-required", "--pr", "41"],
            application_factory=lambda **_: application,
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert payload["command"] == "trigger-required"
    assert payload["result"]["merge_eligibility_assessed"] is False
    assert application.calls == [41]
