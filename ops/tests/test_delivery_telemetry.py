from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

OPS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPS))

from delivery_control.adapters.telemetry_ndjson import TelemetryNdjsonAdapter
from delivery_control.controller.metrics import measure_pipeline
from delivery_control.domain.errors import CompareAndSwapConflict, DeliverySourceError
from delivery_control.domain.inventory import DeliveryInventory, LaneInspection
from delivery_control.domain.models import CheckStatus, HandbackReceipt, Scope
from delivery_control.domain.observations import (
    CheckSnapshot,
    MainLandingSnapshot,
    PullRequestSnapshot,
    RegistrySnapshot,
)
from delivery_control.domain.states import LaneDecision, LaneState, NextAction
from delivery_control.domain.telemetry import (
    DurationSample,
    TelemetryMetric,
    TelemetryReadResult,
    main_subject,
    publication_subject,
)
from delivery_control.services.publish import PublicationOutcome, PublicationResult
from delivery_control.services.sync_main import MainSyncResult
from delivery_control.services.telemetry import TelemetryService
from delivery_control.services.telemetry_operations import OperationTelemetry


def _sample(
    *,
    metric: TelemetryMetric = TelemetryMetric.MERGE_TO_SYNC,
    subject: str | None = None,
    start: datetime | None = None,
    seconds: int = 10,
) -> DurationSample:
    started_at = start or datetime(2026, 8, 21, tzinfo=UTC)
    return DurationSample(
        metric,
        subject or main_subject(origin_main_sha="a" * 40),
        started_at,
        started_at + timedelta(seconds=seconds),
    )


def test_ndjson_append_is_idempotent_and_conflicting_key_fails_cas(
    tmp_path: Path,
) -> None:
    path = tmp_path / "telemetry.ndjson"
    store = TelemetryNdjsonAdapter(path)
    sample = _sample()

    assert store.append(sample) is True
    assert store.append(sample) is False
    assert len(path.read_text(encoding="utf-8").splitlines()) == 1

    conflict = DurationSample(
        sample.metric,
        sample.subject,
        sample.started_at,
        sample.completed_at + timedelta(seconds=1),
    )
    with pytest.raises(CompareAndSwapConflict, match="sample_key conflict"):
        store.append(conflict)


def test_malformed_rows_are_visible_to_readers_and_block_unsafe_append(
    tmp_path: Path,
) -> None:
    path = tmp_path / "telemetry.ndjson"
    good = _sample()
    path.write_text(
        json.dumps(good.to_payload(), sort_keys=True) + "\nnot-json\n",
        encoding="utf-8",
    )
    store = TelemetryNdjsonAdapter(path)

    result = store.read_since(good.started_at - timedelta(seconds=1))

    assert result.samples == (good,)
    assert len(result.problems) == 1
    assert result.problems[0].identity == "line:2"
    with pytest.raises(DeliverySourceError, match="journal malformed"):
        store.append(
            _sample(
                subject=main_subject(origin_main_sha="b" * 40),
            )
        )


def test_rolling_window_keeps_terminal_lane_samples_and_surfaces_bad_journal(
    tmp_path: Path,
) -> None:
    now = datetime(2026, 8, 21, 12, tzinfo=UTC)
    path = tmp_path / "telemetry.ndjson"
    store = TelemetryNdjsonAdapter(path)
    recent = _sample(start=now - timedelta(minutes=10), seconds=20)
    old = _sample(
        subject=main_subject(origin_main_sha="b" * 40),
        start=now - timedelta(hours=2),
        seconds=30,
    )
    store.append(old)
    store.append(recent)
    with path.open("a", encoding="utf-8") as stream:
        stream.write("{}\n")

    rolling = TelemetryService(store).read_window(now=now)
    metrics = measure_pipeline(DeliveryInventory(()), telemetry=rolling, now=now)

    assert rolling.samples == (recent,)
    assert metrics.timings.merge_to_sync_samples == 1
    assert metrics.timings.merge_to_sync_p95_seconds == 20.0
    assert metrics.source_problems == 1


def test_reanchor_uses_journal_readback_instead_of_original_pr_creation() -> None:
    now = datetime(2026, 8, 21, 12, tzinfo=UTC)
    handed_back_at = now - timedelta(seconds=50)
    publication = DurationSample(
        TelemetryMetric.HANDBACK_TO_PR,
        publication_subject(
            lane_id="ISSUE-1",
            claim_generation=3,
            head_sha="b" * 40,
            pr_number=9,
        ),
        handed_back_at,
        now - timedelta(seconds=30),
    )
    record = RegistrySnapshot(
        lane_id="ISSUE-1",
        branch="feat/one",
        path=Path("/tmp/one"),
        status="published",
        scope=Scope.from_paths(modify=("ops/a.py",)),
        base_sha="a" * 40,
        claim_generation=3,
        handed_back_at=handed_back_at,
    )
    pull_request = PullRequestSnapshot(
        number=9,
        url="https://example.test/pull/9",
        branch="feat/one",
        base_sha="a" * 40,
        head_sha="b" * 40,
        state="OPEN",
        draft=False,
        mergeable=True,
        created_at=now - timedelta(days=1),
    )
    check = CheckSnapshot(
        status=CheckStatus.SUCCESS,
        head_sha="b" * 40,
        observed_at=now,
        names=("required",),
        started_at=now - timedelta(seconds=20),
        completed_at=now - timedelta(seconds=10),
    )
    inventory = DeliveryInventory(
        (
            LaneInspection(
                key="ISSUE-1",
                registry=record,
                physical=None,
                snapshot=None,
                pull_requests=(pull_request,),
                decision=LaneDecision(
                    LaneState.READY_TO_QUEUE,
                    NextAction.ENQUEUE,
                    "ready",
                ),
                required_check=check,
            ),
        )
    )

    metrics = measure_pipeline(
        inventory,
        telemetry=TelemetryReadResult((publication,)),
        now=now,
    )

    assert metrics.timings.handback_to_pr_p95_seconds == 20.0
    assert metrics.timings.pr_to_required_start_p95_seconds == 10.0
    assert metrics.source_problems == 0


def test_updated_pr_records_current_reanchor_readback_not_old_creation(
    tmp_path: Path,
) -> None:
    now = datetime(2026, 8, 21, 12, tzinfo=UTC)
    handed_back_at = now - timedelta(seconds=25)
    store = TelemetryNdjsonAdapter(tmp_path / "telemetry.ndjson")
    receipt = HandbackReceipt(
        lane_id="ISSUE-9",
        owner_thread_id="thread-9",
        claim_generation=4,
        branch="feat/nine",
        worktree_path="/tmp/nine",
        base_sha="a" * 40,
        parent_sha="a" * 40,
        head_sha="b" * 40,
        origin_main_sha="a" * 40,
        content_digest="c" * 64,
        scope=Scope.from_paths(modify=("ops/a.py",)),
    )
    record = RegistrySnapshot(
        lane_id=receipt.lane_id,
        branch=receipt.branch,
        path=Path(receipt.worktree_path),
        status="active",
        scope=receipt.scope,
        base_sha=receipt.base_sha,
        claim_generation=receipt.claim_generation,
        handed_back_at=handed_back_at,
    )
    pull_request = PullRequestSnapshot(
        number=9,
        url="https://example.test/pull/9",
        branch=receipt.branch,
        base_sha=receipt.base_sha,
        head_sha=receipt.head_sha,
        state="OPEN",
        draft=False,
        mergeable=True,
        created_at=now - timedelta(days=1),
    )
    operations = OperationTelemetry(
        store=store,
        github=object(),  # type: ignore[arg-type]
        git=object(),  # type: ignore[arg-type]
        clock=lambda: now,
    )

    warnings = operations.after_publish(
        receipt=receipt,
        record=record,
        publication=PublicationResult(PublicationOutcome.UPDATED, pull_request),
    )
    result = store.read_since(now - timedelta(hours=1))

    assert warnings == ()
    assert len(result.samples) == 1
    assert result.samples[0].started_at == handed_back_at
    assert result.samples[0].completed_at == now
    assert result.samples[0].duration_seconds == 25.0


class _LandingGit:
    def __init__(self, *, origin_sha: str, history: str) -> None:
        self.origin_sha = origin_sha
        self.history = history
        self.calls: list[tuple[str, ...]] = []

    def origin_main_sha(self) -> str:
        return self.origin_sha

    def first_parent_landings(
        self, *, before_sha: str, after_sha: str
    ) -> tuple[MainLandingSnapshot, ...]:
        self.calls.append(
            (
                "log",
                "--first-parent",
                "--reverse",
                "--format=%H%x09%cI",
                f"{before_sha}..{after_sha}",
            )
        )
        return tuple(
            MainLandingSnapshot(
                sha=sha,
                landed_at=datetime.fromisoformat(timestamp),
            )
            for sha, timestamp in (
                line.split("\t", 1) for line in self.history.splitlines()
            )
        )


def test_sync_records_every_first_parent_landing_by_exact_merge_sha(
    tmp_path: Path,
) -> None:
    now = datetime(2026, 8, 21, 12, tzinfo=UTC)
    first = "b" * 40
    second = "c" * 40
    git = _LandingGit(
        origin_sha=second,
        history=(
            f"{first}\t2026-08-21T11:59:20+00:00\n"
            f"{second}\t2026-08-21T11:59:50+00:00"
        ),
    )
    store = TelemetryNdjsonAdapter(tmp_path / "telemetry.ndjson")
    operations = OperationTelemetry(
        store=store,
        github=object(),  # type: ignore[arg-type]
        git=git,  # type: ignore[arg-type]
        clock=lambda: now,
    )

    warnings = operations.after_sync(
        MainSyncResult("a" * 40, second, second, True)
    )
    result = store.read_since(now - timedelta(hours=1))

    assert warnings == ()
    assert {
        sample.subject: sample.duration_seconds for sample in result.samples
    } == {
        main_subject(origin_main_sha=first): 40.0,
        main_subject(origin_main_sha=second): 10.0,
    }
    assert git.calls == [
        (
            "log",
            "--first-parent",
            "--reverse",
            "--format=%H%x09%cI",
            f"{'a' * 40}..{second}",
        )
    ]


def test_sync_surfaces_incomplete_landing_history_instead_of_dropping_samples(
    tmp_path: Path,
) -> None:
    now = datetime(2026, 8, 21, 12, tzinfo=UTC)
    origin = "c" * 40
    store = TelemetryNdjsonAdapter(tmp_path / "telemetry.ndjson")
    operations = OperationTelemetry(
        store=store,
        github=object(),  # type: ignore[arg-type]
        git=_LandingGit(origin_sha=origin, history=""),  # type: ignore[arg-type]
        clock=lambda: now,
    )

    warnings = operations.after_sync(
        MainSyncResult("a" * 40, origin, origin, True)
    )

    assert [warning.code for warning in warnings] == [
        "telemetry_merge_history_incomplete"
    ]
    assert store.read_since(now - timedelta(hours=1)).samples == ()


class _NoHistoryGit:
    def __init__(self, origin_sha: str) -> None:
        self.origin_sha = origin_sha

    def origin_main_sha(self) -> str:
        return self.origin_sha

    def first_parent_landings(
        self, *, before_sha: str, after_sha: str
    ) -> tuple[MainLandingSnapshot, ...]:
        raise ValueError("landing history adapter unavailable")


def test_sync_without_git_history_never_silently_collapses_multiple_landings(
    tmp_path: Path,
) -> None:
    now = datetime(2026, 8, 21, 12, tzinfo=UTC)
    origin = "c" * 40
    store = TelemetryNdjsonAdapter(tmp_path / "telemetry.ndjson")
    operations = OperationTelemetry(
        store=store,
        github=object(),  # type: ignore[arg-type]
        git=_NoHistoryGit(origin),  # type: ignore[arg-type]
        clock=lambda: now,
    )

    warnings = operations.after_sync(
        MainSyncResult("a" * 40, origin, origin, True)
    )

    assert [warning.code for warning in warnings] == [
        "telemetry_source_read_failed"
    ]
    assert store.read_since(now - timedelta(hours=1)).samples == ()
