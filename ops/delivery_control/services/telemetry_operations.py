"""Derive duration evidence after successful delivery operations."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from ..domain.models import HandbackReceipt
from ..domain.observations import (
    MergeQueueEntrySnapshot,
    PullRequestSnapshot,
    RegistrySnapshot,
)
from ..domain.telemetry import (
    TelemetryMetric,
    TelemetryReadResult,
    TelemetryWarning,
    main_subject,
    publication_subject,
    pull_request_subject,
    queue_subject,
    sample_key_for,
)
from ..ports.git import GitQueryPort
from ..ports.github import GitHubQueryPort
from ..ports.telemetry import TelemetryStorePort
from .publish import PublicationOutcome, PublicationResult
from .queue import QueueResult
from .sync_main import MainSyncResult
from .telemetry import TelemetryService


class TelemetryGitHubPort(GitHubQueryPort, Protocol):
    def recent_merge_times(self, *, limit: int = 100) -> tuple[datetime, ...]: ...


@dataclass(frozen=True)
class OperationTelemetry:
    """Observe completed operations without owning their lifecycle truth."""

    store: TelemetryStorePort
    github: TelemetryGitHubPort
    git: GitQueryPort
    clock: Callable[[], datetime]

    @property
    def service(self) -> TelemetryService:
        return TelemetryService(self.store)

    def rolling(self, *, now: datetime) -> TelemetryReadResult:
        return self.service.read_window(now=now)

    def after_publish(
        self,
        *,
        receipt: HandbackReceipt,
        record: RegistrySnapshot,
        publication: PublicationResult,
    ) -> tuple[TelemetryWarning, ...]:
        if publication.outcome is PublicationOutcome.ALREADY_PUBLISHED:
            return ()
        completed_at = (
            publication.pull_request.created_at
            if publication.outcome is PublicationOutcome.CREATED
            and publication.pull_request.created_at is not None
            else self.clock()
        )
        warning = self.service.record(
            metric=TelemetryMetric.HANDBACK_TO_PR,
            subject=publication_subject(
                lane_id=receipt.lane_id,
                claim_generation=receipt.claim_generation,
                head_sha=receipt.head_sha,
                pr_number=publication.pull_request.number,
            ),
            started_at=record.handed_back_at,
            completed_at=completed_at,
        )
        return (warning,) if warning is not None else ()

    def after_enqueue(
        self,
        *,
        receipt: HandbackReceipt,
        record: RegistrySnapshot,
        result: QueueResult,
    ) -> tuple[TelemetryWarning, ...]:
        observed_at = self.clock()
        warnings: list[TelemetryWarning] = []
        entry, entry_warning = self._queue_entry(result.pull_request.node_id)
        if entry_warning is not None:
            warnings.append(entry_warning)
        publication_time = self._publication_time(
            receipt=receipt,
            record=record,
            pull_request=result.pull_request,
            observed_at=observed_at,
            warnings=warnings,
        )
        pr_subject = pull_request_subject(
            pr_number=result.pull_request.number,
            head_sha=receipt.head_sha,
        )
        observations = (
            (
                TelemetryMetric.PR_TO_REQUIRED_START,
                pr_subject,
                publication_time,
                result.required.started_at,
            ),
            (
                TelemetryMetric.REQUIRED_DURATION,
                pr_subject,
                result.required.started_at,
                result.required.completed_at,
            ),
            (
                TelemetryMetric.REQUIRED_SUCCESS_TO_ENQUEUE,
                queue_subject(
                    pr_number=result.pull_request.number,
                    head_sha=receipt.head_sha,
                    queue_entry_id=entry.entry_id if entry is not None else "missing",
                ),
                result.required.completed_at,
                entry.enqueued_at if entry is not None else None,
            ),
        )
        for metric, subject, started_at, completed_at in observations:
            warning = self.service.record(
                metric=metric,
                subject=subject,
                started_at=started_at,
                completed_at=completed_at,
            )
            if warning is not None:
                warnings.append(warning)
        return tuple(warnings)

    def after_cleanup(
        self,
        *,
        pull_request: PullRequestSnapshot,
        was_already_terminal: bool,
    ) -> tuple[TelemetryWarning, ...]:
        if was_already_terminal:
            return ()
        warning = self.service.record(
            metric=TelemetryMetric.MERGE_TO_CLEANUP,
            subject=pull_request_subject(
                pr_number=pull_request.number,
                head_sha=pull_request.head_sha,
            ),
            started_at=pull_request.merged_at,
            completed_at=self.clock(),
        )
        return (warning,) if warning is not None else ()

    def after_sync(self, result: MainSyncResult) -> tuple[TelemetryWarning, ...]:
        if not result.changed:
            return ()
        warnings: list[TelemetryWarning] = []
        merged_at = None
        try:
            merged = self.github.recent_merge_times(limit=1)
            merged_at = max(merged) if merged else None
            if self.git.origin_main_sha() != result.origin_sha:
                merged_at = None
                warnings.append(
                    TelemetryWarning(
                        code="telemetry_source_changed",
                        message="origin/main changed after synchronization",
                        metric=TelemetryMetric.MERGE_TO_SYNC,
                    )
                )
        except (OSError, RuntimeError, ValueError) as error:
            warnings.append(
                TelemetryWarning(
                    code="telemetry_source_read_failed",
                    message=str(error),
                    metric=TelemetryMetric.MERGE_TO_SYNC,
                )
            )
        warning = self.service.record(
            metric=TelemetryMetric.MERGE_TO_SYNC,
            subject=main_subject(origin_main_sha=result.origin_sha),
            started_at=merged_at,
            completed_at=self.clock(),
        )
        if warning is not None:
            warnings.append(warning)
        return tuple(warnings)

    def _publication_time(
        self,
        *,
        receipt: HandbackReceipt,
        record: RegistrySnapshot,
        pull_request: PullRequestSnapshot,
        observed_at: datetime,
        warnings: list[TelemetryWarning],
    ) -> datetime | None:
        if record.handed_back_at is None:
            warnings.append(
                TelemetryWarning(
                    code="telemetry_source_missing",
                    message="registry handback timestamp is unavailable",
                    metric=TelemetryMetric.PR_TO_REQUIRED_START,
                )
            )
            return None
        if (
            pull_request.created_at is not None
            and record.handed_back_at <= pull_request.created_at
        ):
            return pull_request.created_at
        subject = publication_subject(
            lane_id=receipt.lane_id,
            claim_generation=receipt.claim_generation,
            head_sha=receipt.head_sha,
            pr_number=pull_request.number,
        )
        sample, problems = self.service.find(
            sample_key=sample_key_for(TelemetryMetric.HANDBACK_TO_PR, subject),
            now=observed_at,
        )
        warnings.extend(
            TelemetryWarning(
                code="telemetry_read_problem",
                message=problem.reason,
                metric=TelemetryMetric.PR_TO_REQUIRED_START,
            )
            for problem in problems
        )
        return sample.completed_at if sample is not None else None

    def _queue_entry(
        self, pull_request_id: str
    ) -> tuple[MergeQueueEntrySnapshot | None, TelemetryWarning | None]:
        if not pull_request_id:
            return None, TelemetryWarning(
                code="telemetry_source_missing",
                message="PR node id is unavailable after enqueue",
                metric=TelemetryMetric.REQUIRED_SUCCESS_TO_ENQUEUE,
            )
        try:
            entry = self.github.merge_queue_entry_snapshot(pull_request_id)
        except (OSError, RuntimeError, ValueError) as error:
            return None, TelemetryWarning(
                code="telemetry_source_read_failed",
                message=str(error),
                metric=TelemetryMetric.REQUIRED_SUCCESS_TO_ENQUEUE,
            )
        if entry is None:
            return None, TelemetryWarning(
                code="telemetry_source_missing",
                message="merge queue readback has no entry",
                metric=TelemetryMetric.REQUIRED_SUCCESS_TO_ENQUEUE,
            )
        return entry, None
