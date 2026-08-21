"""Application facade that composes deterministic delivery services."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

import worktree_registry

from .adapters.git_cli import GitCliAdapter
from .adapters.github_cli import GitHubCliAdapter
from .adapters.module_runner import ModuleCommandRunner
from .adapters.registry import RegistryCliAdapter
from .adapters.runtime import RuntimeStatusMap
from .adapters.telemetry_ndjson import TelemetryNdjsonAdapter
from .controller.capacity import decide_capacity
from .controller.dogfood import assess_dogfood_readiness
from .controller.metrics import measure_merge_cadence, measure_pipeline
from .domain.errors import PolicyViolation
from .domain.models import HandbackReceipt
from .domain.observations import RegistrySnapshot
from .domain.states import HoldKind
from .ports.git import GitCommandPort, GitQueryPort
from .ports.github import GitHubCommandPort, GitHubQueryPort
from .ports.registry import (
    RegistryCleanupQueryPort,
    RegistryCommandPort,
    RegistryPublicationQueryPort,
    RegistryQueryPort,
)
from .ports.runtime import AgentRuntimePort
from .ports.telemetry import TelemetryStorePort
from .services.cleanup import CleanupService
from .services.holds import HoldService
from .services.inspect import InspectService
from .services.metadata import MetadataRepairService
from .services.pr_contract import parse_pull_request_body
from .services.publish import PublishService, receipt_from_active_claim
from .services.publish_preflight import PublishPreflightService
from .services.queue import QueueService
from .services.sync_main import MainSyncService
from .services.telemetry_operations import OperationTelemetry

CONTROL_PLANE_OPS = Path(__file__).resolve().parents[1]


def _utc_now() -> datetime:
    return datetime.now(tz=UTC)


class DeliveryGitPort(GitQueryPort, GitCommandPort, Protocol):
    pass


class DeliveryGitHubPort(GitHubQueryPort, GitHubCommandPort, Protocol):
    def recent_merge_times(self, *, limit: int = 100) -> tuple[datetime, ...]: ...


class DeliveryRegistryPort(
    RegistryQueryPort,
    RegistryPublicationQueryPort,
    RegistryCleanupQueryPort,
    RegistryCommandPort,
    Protocol,
):
    pass


@dataclass(frozen=True)
class DeliveryApplication:
    repo: Path
    git: DeliveryGitPort
    github: DeliveryGitHubPort
    registry: DeliveryRegistryPort
    runtime: AgentRuntimePort
    telemetry: TelemetryStorePort
    clock: Callable[[], datetime] = _utc_now

    def inspect(self) -> object:
        return InspectService(
            registry=self.registry,
            git=self.git,
            github=self.github,
            runtime=self.runtime,
        ).inspect()

    def metrics(self, *, now: datetime | None = None) -> object:
        observed_at = now or self.clock()
        telemetry = self._operation_telemetry().rolling(now=observed_at)
        return measure_pipeline(self.inspect(), telemetry=telemetry, now=observed_at)

    def plan(self, *, now: datetime | None = None) -> object:
        observed_at = now or self.clock()
        metrics = self.metrics(now=observed_at)
        cadence = measure_merge_cadence(
            self.github.recent_merge_times(), now=observed_at
        )
        return {
            "metrics": metrics,
            "cadence": cadence,
            "decision": decide_capacity(metrics, cadence),
        }

    def dogfood_preflight(self, *, now: datetime | None = None) -> object:
        observed_at = now or self.clock()
        checkout = self.git.canonical_checkout()
        origin_main_sha = self.git.origin_main_sha()
        physical_worktrees = self.git.list_worktrees()
        main_protected = self.github.branch_is_protected("main")
        required_status_contexts = (
            self.github.required_status_contexts("main") if main_protected else ()
        )
        metrics = self.metrics(now=observed_at)
        cadence = measure_merge_cadence(
            self.github.recent_merge_times(), now=observed_at
        )
        return assess_dogfood_readiness(
            local_main_sha=self.git.local_main_sha(),
            origin_main_sha=origin_main_sha,
            canonical_branch=checkout.branch,
            canonical_clean=checkout.clean,
            main_protected=main_protected,
            required_status_contexts=required_status_contexts,
            merge_queue_enabled=self.github.merge_queue_enabled("main"),
            physical_worktree_count=len(physical_worktrees),
            canonical_worktree_present=(
                sum(
                    item.path.resolve() == self.repo.resolve()
                    for item in physical_worktrees
                )
                == 1
            ),
            metrics=metrics,
            cadence=cadence,
        )

    def receipt(self, lane_id: str) -> HandbackReceipt:
        receipt, _ = self._receipt_and_record(lane_id)
        return receipt

    def _receipt_and_record(
        self, lane_id: str
    ) -> tuple[HandbackReceipt, RegistrySnapshot]:
        record = self.registry.get(lane_id)
        if record is None:
            raise PolicyViolation(f"no unique active registry record for {lane_id}")
        snapshot = self.git.inspect_worktree(record.path, record.base_sha)
        return receipt_from_active_claim(record, snapshot), record

    def publish(self, *, lane_id: str, title: str) -> object:
        receipt, record = self._receipt_and_record(lane_id)
        publication = PublishService(
            preflight=PublishPreflightService(
                registry=self.registry,
                git=self.git,
                github=self.github,
            ),
            git=self.git,
            github_query=self.github,
            github_command=self.github,
        ).publish(receipt=receipt, title=title)
        warnings = self._operation_telemetry().after_publish(
            receipt=receipt,
            record=record,
            publication=publication,
        )
        release = self._cleanup().release_after_publish(
            receipt=receipt,
            pull_request_number=publication.pull_request.number,
        )
        return {
            "receipt": receipt,
            "publication": publication,
            "release": release,
            "telemetry_warnings": warnings,
        }

    def release_published(self, pull_request_number: int) -> object:
        receipt = self._receipt_from_pr(pull_request_number)
        return self._cleanup().release_after_publish(
            receipt=receipt, pull_request_number=pull_request_number
        )

    def enqueue(
        self,
        *,
        pull_request_number: int,
        holds: frozenset[HoldKind] = frozenset(),
    ) -> object:
        receipt = self._receipt_from_pr(pull_request_number)
        record = self._record_for_receipt(receipt)
        result = QueueService(
            registry=self.registry,
            git=self.git,
            github_query=self.github,
            github_command=self.github,
        ).enqueue(
            receipt=receipt,
            pull_request_number=pull_request_number,
            holds=holds,
        )
        warnings = self._operation_telemetry().after_enqueue(
            receipt=receipt,
            record=record,
            result=result,
        )
        return {"queue": result, "telemetry_warnings": warnings}

    def reconcile_holds(
        self,
        *,
        pull_request_number: int,
        holds: frozenset[HoldKind],
        clear_all: bool,
    ) -> object:
        return HoldService(query=self.github, command=self.github).reconcile(
            number=pull_request_number,
            holds=holds,
            clear_all=clear_all,
        )

    def repair_metadata(self, pull_request_number: int) -> object:
        return MetadataRepairService(
            registry=self.registry,
            query=self.github,
            command=self.github,
        ).repair(pull_request_number)

    def cleanup_merged(self, pull_request_number: int) -> object:
        pull_request = self.github.get_pull_request(pull_request_number)
        receipt = parse_pull_request_body(pull_request.body)
        record = self._record_for_receipt(receipt)
        result = self._cleanup().finalize_merged(
            receipt=receipt, pull_request_number=pull_request_number
        )
        warnings = self._operation_telemetry().after_cleanup(
            pull_request=pull_request,
            was_already_terminal=record.status == "merged",
        )
        return {"cleanup": result, "telemetry_warnings": warnings}

    def sync_main(self) -> object:
        result = MainSyncService(
            canonical_path=self.repo,
            query=self.git,
            command=self.git,
        ).sync()
        warnings = self._operation_telemetry().after_sync(result)
        return {"sync": result, "telemetry_warnings": warnings}

    def _receipt_from_pr(self, number: int) -> HandbackReceipt:
        return parse_pull_request_body(self.github.get_pull_request(number).body)

    def _record_for_receipt(self, receipt: HandbackReceipt) -> RegistrySnapshot:
        record = self.registry.find_exact_claim(
            lane_id=receipt.lane_id,
            branch=receipt.branch,
            path=Path(receipt.worktree_path),
            claim_generation=receipt.claim_generation,
        )
        if record is None:
            raise PolicyViolation("typed receipt has no exact registry claim")
        return record

    def _operation_telemetry(self) -> OperationTelemetry:
        return OperationTelemetry(
            store=self.telemetry,
            github=self.github,
            git=self.git,
            clock=self.clock,
        )

    def _cleanup(self) -> CleanupService:
        return CleanupService(
            registry_query=self.registry,
            registry_command=self.registry,
            git_query=self.git,
            git_command=self.git,
            github=self.github,
        )


def build_application(
    *, repo: Path, runtime_status_file: Path | None = None
) -> DeliveryApplication:
    resolved = repo.expanduser().resolve()
    registry_script = CONTROL_PLANE_OPS / "worktree_registry.py"
    return DeliveryApplication(
        repo=resolved,
        git=GitCliAdapter(repo=resolved),
        github=GitHubCliAdapter(repo=resolved),
        registry=RegistryCliAdapter(
            script_path=registry_script,
            state_path=resolved / ".cache" / "worktree_registry.json",
            runner=ModuleCommandRunner(
                executable=registry_script,
                main=worktree_registry.main,
            ),
        ),
        runtime=RuntimeStatusMap.from_file(runtime_status_file),
        telemetry=TelemetryNdjsonAdapter(
            resolved / ".cache" / "delivery_telemetry.ndjson"
        ),
    )
