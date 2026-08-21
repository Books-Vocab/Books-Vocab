"""Application facade that composes deterministic delivery services."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from .adapters.git_cli import GitCliAdapter
from .adapters.github_cli import GitHubCliAdapter
from .adapters.registry import RegistryCliAdapter
from .adapters.runtime import RuntimeStatusMap
from .controller.capacity import decide_capacity
from .controller.dogfood import assess_dogfood_readiness
from .controller.metrics import measure_merge_cadence, measure_pipeline
from .domain.errors import PolicyViolation
from .domain.models import HandbackReceipt
from .domain.states import HoldKind
from .ports.git import GitCommandPort, GitQueryPort
from .ports.github import GitHubCommandPort, GitHubQueryPort
from .ports.registry import RegistryCommandPort, RegistryQueryPort
from .ports.runtime import AgentRuntimePort
from .services.cleanup import CleanupService
from .services.inspect import InspectService
from .services.publish import (
    PublishService,
    parse_pull_request_body,
    receipt_from_active_claim,
)
from .services.publish_preflight import PublishPreflightService
from .services.queue import QueueService
from .services.sync_main import MainSyncService

CONTROL_PLANE_OPS = Path(__file__).resolve().parents[1]


class DeliveryGitPort(GitQueryPort, GitCommandPort, Protocol):
    pass


class DeliveryGitHubPort(GitHubQueryPort, GitHubCommandPort, Protocol):
    def recent_merge_times(self, *, limit: int = 100) -> tuple[datetime, ...]: ...


class DeliveryRegistryPort(RegistryQueryPort, RegistryCommandPort, Protocol):
    pass


@dataclass(frozen=True)
class DeliveryApplication:
    repo: Path
    git: DeliveryGitPort
    github: DeliveryGitHubPort
    registry: DeliveryRegistryPort
    runtime: AgentRuntimePort

    def inspect(self) -> object:
        return InspectService(
            registry=self.registry,
            git=self.git,
            github=self.github,
            runtime=self.runtime,
        ).inspect()

    def metrics(self) -> object:
        return measure_pipeline(self.inspect())

    def plan(self, *, now: datetime | None = None) -> object:
        observed_at = now or datetime.now(tz=UTC)
        metrics = self.metrics()
        cadence = measure_merge_cadence(
            self.github.recent_merge_times(), now=observed_at
        )
        return {
            "metrics": metrics,
            "cadence": cadence,
            "decision": decide_capacity(metrics, cadence),
        }

    def dogfood_preflight(self, *, now: datetime | None = None) -> object:
        observed_at = now or datetime.now(tz=UTC)
        checkout = self.git.canonical_checkout()
        origin_main_sha = self.git.origin_main_sha()
        physical_worktrees = self.git.list_worktrees()
        metrics = self.metrics()
        cadence = measure_merge_cadence(
            self.github.recent_merge_times(), now=observed_at
        )
        return assess_dogfood_readiness(
            local_main_sha=self.git.local_main_sha(),
            origin_main_sha=origin_main_sha,
            canonical_branch=checkout.branch,
            canonical_clean=checkout.clean,
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
        record = self.registry.get(lane_id)
        if record is None:
            raise PolicyViolation(f"no unique active registry record for {lane_id}")
        snapshot = self.git.inspect_worktree(record.path, record.base_sha)
        return receipt_from_active_claim(record, snapshot)

    def publish(self, *, lane_id: str, title: str) -> object:
        receipt = self.receipt(lane_id)
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
        release = self._cleanup().release_after_publish(
            receipt=receipt,
            pull_request_number=publication.pull_request.number,
        )
        return {
            "receipt": receipt,
            "publication": publication,
            "release": release,
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
        return QueueService(
            registry=self.registry,
            git=self.git,
            github_query=self.github,
            github_command=self.github,
        ).enqueue(
            receipt=receipt,
            pull_request_number=pull_request_number,
            holds=holds,
        )

    def cleanup_merged(self, pull_request_number: int) -> object:
        receipt = self._receipt_from_pr(pull_request_number)
        return self._cleanup().finalize_merged(
            receipt=receipt, pull_request_number=pull_request_number
        )

    def sync_main(self) -> object:
        return MainSyncService(
            canonical_path=self.repo,
            query=self.git,
            command=self.git,
        ).sync()

    def _receipt_from_pr(self, number: int) -> HandbackReceipt:
        return parse_pull_request_body(self.github.get_pull_request(number).body)

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
    return DeliveryApplication(
        repo=resolved,
        git=GitCliAdapter(repo=resolved),
        github=GitHubCliAdapter(repo=resolved),
        registry=RegistryCliAdapter(
            script_path=CONTROL_PLANE_OPS / "worktree_registry.py"
        ),
        runtime=RuntimeStatusMap.from_file(runtime_status_file),
    )
