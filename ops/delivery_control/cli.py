"""Thin command surface for the deterministic delivery services."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, is_dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any, Protocol

from .adapters.git_cli import GitCliAdapter
from .adapters.github_cli import GitHubCliAdapter
from .adapters.registry import RegistryCliAdapter
from .controller.capacity import decide_capacity
from .controller.metrics import measure_merge_cadence, measure_pipeline
from .domain.errors import DeliveryContractError, DeliverySourceError, PolicyViolation
from .domain.models import HandbackReceipt
from .domain.states import HoldKind
from .ports.git import GitCommandPort, GitQueryPort
from .ports.github import GitHubCommandPort, GitHubQueryPort
from .ports.registry import RegistryCommandPort, RegistryQueryPort
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

COMMAND_SCHEMA = "kg.delivery.command.v1"


class DeliveryGitPort(GitQueryPort, GitCommandPort, Protocol):
    pass


class DeliveryGitHubPort(GitHubQueryPort, GitHubCommandPort, Protocol):
    def recent_merge_times(self, *, limit: int = 100) -> tuple[datetime, ...]: ...


class DeliveryRegistryPort(RegistryQueryPort, RegistryCommandPort, Protocol):
    pass


class RuntimeStatusMap:
    """Read-only owner status input; absent evidence stays unknown."""

    def __init__(self, statuses: Mapping[str, str] | None = None) -> None:
        self.statuses = dict(statuses or {})

    @classmethod
    def from_file(cls, path: Path | None) -> RuntimeStatusMap:
        if path is None:
            return cls()
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise PolicyViolation(f"runtime status file is unreadable: {path}") from error
        if not isinstance(payload, Mapping) or any(
            type(key) is not str or type(value) is not str
            for key, value in payload.items()
        ):
            raise PolicyViolation("runtime status file must map thread IDs to states")
        return cls(payload)

    def owner_status(self, thread_id: str) -> str:
        return self.statuses.get(thread_id, "unknown")

    def dispatch(self, thread_id: str, instruction: str) -> None:
        raise PolicyViolation("the deterministic CLI never dispatches agents")


@dataclass(frozen=True)
class DeliveryApplication:
    repo: Path
    git: DeliveryGitPort
    github: DeliveryGitHubPort
    registry: DeliveryRegistryPort
    runtime: RuntimeStatusMap

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

    def receipt(self, lane_id: str) -> HandbackReceipt:
        record = self.registry.get(lane_id)
        if record is None:
            raise PolicyViolation(f"no unique active registry record for {lane_id}")
        snapshot = self.git.inspect_worktree(record.path, record.base_sha)
        return receipt_from_active_claim(record, snapshot)

    def publish(self, *, lane_id: str, title: str) -> object:
        receipt = self.receipt(lane_id)
        preflight = PublishPreflightService(
            registry=self.registry,
            git=self.git,
            github=self.github,
        )
        publication = PublishService(
            preflight=preflight,
            git=self.git,
            github_query=self.github,
            github_command=self.github,
        ).publish(receipt=receipt, title=title)
        release = self._cleanup().release_after_publish(
            receipt=receipt,
            pull_request_number=publication.pull_request.number,
        )
        return {"receipt": receipt, "publication": publication, "release": release}

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
            script_path=resolved / "ops" / "worktree_registry.py"
        ),
        runtime=RuntimeStatusMap.from_file(runtime_status_file),
    )


def _jsonable(value: object) -> object:
    if is_dataclass(value):
        return _jsonable(asdict(value))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, set, frozenset)):
        return [_jsonable(item) for item in value]
    return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Deterministic KG delivery control plane"
    )
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--runtime-status-file", type=Path)
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("inspect", help="classify every known delivery lane")
    commands.add_parser("metrics", help="measure current queue reservoirs")
    commands.add_parser("plan", help="derive the next capacity actions")

    receipt = commands.add_parser("receipt", help="normalize one active handback")
    receipt.add_argument("--lane", required=True)

    publish = commands.add_parser("publish", help="publish and release one handback")
    publish.add_argument("--lane", required=True)
    publish.add_argument("--title", required=True)

    release = commands.add_parser(
        "release-published", help="retry local release after durable PR publication"
    )
    release.add_argument("--pr", type=int, required=True)

    queue = commands.add_parser("queue", help="admit one exact PR to merge queue")
    queue.add_argument("--pr", type=int, required=True)
    queue.add_argument(
        "--hold", action="append", choices=tuple(item.value for item in HoldKind)
    )

    cleanup = commands.add_parser(
        "cleanup-merged", help="remove exact merged branch residue"
    )
    cleanup.add_argument("--pr", type=int, required=True)
    commands.add_parser("sync-main", help="ff-only synchronize canonical main")
    return parser


def run_command(args: argparse.Namespace, application: DeliveryApplication) -> object:
    if args.command == "inspect":
        return application.inspect()
    if args.command == "metrics":
        return application.metrics()
    if args.command == "plan":
        return application.plan()
    if args.command == "receipt":
        return application.receipt(args.lane)
    if args.command == "publish":
        return application.publish(lane_id=args.lane, title=args.title)
    if args.command == "release-published":
        return application.release_published(args.pr)
    if args.command == "queue":
        return application.enqueue(
            pull_request_number=args.pr,
            holds=frozenset(HoldKind(item) for item in args.hold or ()),
        )
    if args.command == "cleanup-merged":
        return application.cleanup_merged(args.pr)
    if args.command == "sync-main":
        return application.sync_main()
    raise AssertionError(f"unhandled command: {args.command}")


def main(
    argv: Sequence[str] | None = None,
    *,
    application_factory: Any = build_application,
) -> int:
    args = _parser().parse_args(argv)
    try:
        application = application_factory(
            repo=args.repo,
            runtime_status_file=args.runtime_status_file,
        )
        result = run_command(args, application)
    except (DeliveryContractError, DeliverySourceError, OSError) as error:
        print(
            json.dumps(
                {
                    "schema": COMMAND_SCHEMA,
                    "command": args.command,
                    "ok": False,
                    "error": str(error),
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1
    print(
        json.dumps(
            {
                "schema": COMMAND_SCHEMA,
                "command": args.command,
                "ok": True,
                "result": _jsonable(result),
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


__all__ = [
    "COMMAND_SCHEMA",
    "DeliveryApplication",
    "RuntimeStatusMap",
    "build_application",
    "main",
    "run_command",
]
