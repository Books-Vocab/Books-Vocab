"""One in-process pump that carries published lanes from green to cleaned (#2646).

Each cycle reads GitHub and registry state once (``inspect``) and executes the
action the lane state machine already derived: enqueue a PR whose merge policy
passed on its exact head, run ``cleanup-merged`` right after a merge, release
local assets of a durable PR, and wait on everything else (required checks,
the native merge queue, still-active Scope owners).  It never chooses a PR by
session or branch prefix, and it never spawns ``delivery.py``: every action
is an in-process application call, so a drain cannot create lock contention
with itself.

A lock-busy or rate-limit refusal is backoff, not an attempt; only a real
refusal counts toward ``MAX_ATTEMPTS`` for that (action, PR).
"""

from __future__ import annotations

import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from ..domain.errors import DeliveryContractError, DeliverySourceError
from ..domain.inventory import DeliveryInventory, LaneInspection
from ..domain.observations import PullRequestSnapshot
from ..domain.states import NextAction
from .cleanup import OperationLease

MAX_ATTEMPTS = 3
DEFAULT_INTERVAL_SECONDS = 30.0
DEFAULT_TIMEOUT_SECONDS = 3600.0
# Message fragments of refusals that say "try again later", never "this PR is bad".
_BACKOFF_MARKERS = ("already in progress", "rate limit", "secondary rate")

_WAITING = frozenset(
    {
        NextAction.WAIT_REQUIRED,
        NextAction.WAIT_MERGE,
        NextAction.FINALIZE_PR,
        NextAction.CONTINUE_WORK,
        NextAction.REANCHOR,
        NextAction.PUBLISH,
    }
)


class DrainKind(StrEnum):
    ENQUEUE = "enqueue"
    CLEANUP_MERGED = "cleanup-merged"
    RELEASE_PUBLISHED = "release-published"
    WAIT = "wait"


class DrainStatus(StrEnum):
    DONE = "done"
    PLANNED = "planned"
    BACKOFF = "backoff"
    FAILED = "failed"
    EXHAUSTED = "exhausted"


@dataclass(frozen=True)
class DrainAction:
    kind: DrainKind
    lane: str
    reason: str
    pull_request: int | None = None


@dataclass(frozen=True)
class DrainOutcome:
    action: DrainAction
    status: DrainStatus
    detail: str = ""


@dataclass(frozen=True)
class DrainReport:
    cycles: int
    stopped: str
    outcomes: tuple[DrainOutcome, ...]
    waiting: tuple[DrainAction, ...]


class DrainApplication(Protocol):
    def inspect(self) -> DeliveryInventory: ...

    def enqueue(self, *, pull_request_number: int) -> object: ...

    def cleanup_merged(
        self, pull_request_number: int, *, operation_lease: OperationLease | None = None
    ) -> object: ...

    def release_published(
        self, pull_request_number: int, *, operation_lease: OperationLease | None = None
    ) -> object: ...


def _pull_request(lane: LaneInspection, state: str) -> PullRequestSnapshot | None:
    matching = [item for item in lane.pull_requests if item.state == state]
    return max(matching, key=lambda item: item.number) if matching else None


def plan_actions(inventory: DeliveryInventory) -> tuple[DrainAction, ...]:
    """Map every lane's derived next action to a drain action, in PR order."""

    actions: list[DrainAction] = []
    for lane in inventory.lanes:
        decision = lane.decision
        wanted = {
            NextAction.ENQUEUE: (DrainKind.ENQUEUE, "OPEN"),
            NextAction.CLEANUP: (DrainKind.CLEANUP_MERGED, "MERGED"),
            NextAction.CLEANUP_LOCAL: (DrainKind.RELEASE_PUBLISHED, "OPEN"),
        }.get(decision.next_action)
        if wanted is not None:
            kind, state = wanted
            pull_request = _pull_request(lane, state)
            if pull_request is not None:
                actions.append(
                    DrainAction(kind, lane.key, decision.reason, pull_request.number)
                )
            continue  # no addressable PR: the lane is left to inspect/doctor
        if decision.next_action in _WAITING:
            pull_request = next(iter(lane.pull_requests), None)
            actions.append(
                DrainAction(
                    DrainKind.WAIT,
                    lane.key,
                    f"{decision.next_action.value}: {decision.reason}",
                    pull_request.number if pull_request else None,
                )
            )
    # Cleanup frees Scope for the next lane, so it runs before any enqueue.
    cleanup_first = {DrainKind.ENQUEUE: 1}
    return tuple(
        sorted(
            actions,
            key=lambda item: (
                cleanup_first.get(item.kind, 0),
                item.pull_request or 0,
                item.lane,
            ),
        )
    )


def is_backoff(error: BaseException) -> bool:
    text = str(error).lower()
    return any(marker in text for marker in _BACKOFF_MARKERS)


class DrainService:
    def __init__(
        self,
        *,
        application: DrainApplication,
        operation_lease: OperationLease | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.application = application
        self.operation_lease = operation_lease
        self.sleep = sleep
        self.clock = clock

    def _execute(self, action: DrainAction) -> None:
        number = action.pull_request
        if number is None:
            raise DeliveryContractError("drain action has no pull request")
        if action.kind is DrainKind.ENQUEUE:
            self.application.enqueue(pull_request_number=number)
        elif action.kind is DrainKind.CLEANUP_MERGED:
            self.application.cleanup_merged(
                number, operation_lease=self.operation_lease
            )
        else:
            self.application.release_published(
                number, operation_lease=self.operation_lease
            )

    def run(
        self,
        *,
        once: bool = False,
        dry_run: bool = False,
        interval: float = DEFAULT_INTERVAL_SECONDS,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> DrainReport:
        attempts: Counter[tuple[DrainKind, int | None]] = Counter()
        outcomes: list[DrainOutcome] = []
        started = self.clock()
        cycles = 0
        while True:
            cycles += 1
            actions = plan_actions(self.application.inspect())
            progressing = False
            stuck = False
            waiting: list[DrainAction] = []
            for action in actions:
                if action.kind is DrainKind.WAIT:
                    waiting.append(action)
                    continue
                key = (action.kind, action.pull_request)
                if dry_run:
                    outcomes.append(DrainOutcome(action, DrainStatus.PLANNED))
                    continue
                if attempts[key] >= MAX_ATTEMPTS:
                    outcomes.append(DrainOutcome(action, DrainStatus.EXHAUSTED))
                    stuck = True
                    continue
                try:
                    self._execute(action)
                except (DeliveryContractError, DeliverySourceError) as error:
                    if is_backoff(error):
                        outcomes.append(
                            DrainOutcome(action, DrainStatus.BACKOFF, str(error))
                        )
                        progressing = True  # retried next cycle, attempt not spent
                    else:
                        attempts[key] += 1
                        outcomes.append(
                            DrainOutcome(action, DrainStatus.FAILED, str(error))
                        )
                        if attempts[key] < MAX_ATTEMPTS:
                            progressing = True
                        else:
                            stuck = True
                else:
                    outcomes.append(DrainOutcome(action, DrainStatus.DONE))
                    progressing = True
            if once or dry_run:
                stopped = "dry-run" if dry_run else "once"
                break
            if not progressing and not waiting:
                stopped = "stuck" if stuck else "settled"
                break
            if self.clock() - started >= timeout:
                stopped = "timeout"
                break
            self.sleep(interval)
        return DrainReport(cycles, stopped, tuple(outcomes), tuple(waiting))


__all__ = [
    "DrainAction",
    "DrainKind",
    "DrainOutcome",
    "DrainReport",
    "DrainService",
    "DrainStatus",
    "is_backoff",
    "plan_actions",
]
