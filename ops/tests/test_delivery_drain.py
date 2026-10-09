"""`delivery.py drain`: one process pumps gate-green PRs to merged and cleaned (#2646)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

OPS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPS))

from delivery_control import cli
from delivery_control.domain.errors import DeliverySourceError, PolicyViolation
from delivery_control.domain.inventory import DeliveryInventory, LaneInspection
from delivery_control.domain.observations import PullRequestSnapshot
from delivery_control.domain.states import LaneDecision, LaneState, NextAction
from delivery_control.services.drain import (
    MAX_ATTEMPTS,
    DrainKind,
    DrainService,
    DrainStatus,
    plan_actions,
)

# PR status -> (lane state, next action, GitHub PR state)
_SHAPES = {
    "green": (LaneState.READY_TO_QUEUE, NextAction.ENQUEUE, "OPEN"),
    "red": (LaneState.REQUIRED_FAILED, NextAction.REPAIR_REQUIRED, "OPEN"),
    "pending": (LaneState.PR_WAITING_REQUIRED, NextAction.WAIT_REQUIRED, "OPEN"),
    "queued": (LaneState.PR_QUEUED, NextAction.WAIT_MERGE, "OPEN"),
    "merged": (LaneState.TERMINAL_CLEANUP, NextAction.CLEANUP, "MERGED"),
    "released": (LaneState.PUBLISHED_LOCAL_CLEANUP, NextAction.CLEANUP_LOCAL, "OPEN"),
    "done": (LaneState.DONE, NextAction.NONE, "MERGED"),
    "active": (LaneState.ACTIVE_DEVELOPMENT, NextAction.CONTINUE_WORK, "OPEN"),
}


def _lane(number: int, status: str) -> LaneInspection:
    state, action, pr_state = _SHAPES[status]
    pull_requests = (
        ()
        if status == "active"
        else (
            PullRequestSnapshot(
                number=number,
                url=f"https://example.test/pull/{number}",
                branch=f"debug/issue-{number}-x",
                base_sha="a" * 40,
                head_sha="b" * 40,
                state=pr_state,
                draft=False,
                mergeable=True,
            ),
        )
    )
    return LaneInspection(
        key=f"LANE-{number}",
        registry=None,
        physical=None,
        snapshot=None,
        pull_requests=pull_requests,
        decision=LaneDecision(state, action, f"{status} lane"),
    )


class FakeFleet:
    """Applies queue and merge transitions the way GitHub would between cycles."""

    def __init__(self, statuses: dict[int, str]) -> None:
        self.status = dict(statuses)
        self.calls: list[tuple[str, int]] = []
        self.in_flight = 0
        self.max_in_flight = 0
        self.failures: dict[tuple[str, int], list[Exception]] = {}

    def inspect(self) -> DeliveryInventory:
        for number, status in list(self.status.items()):
            if status == "queued":  # the native queue merges after one cycle
                self.status[number] = "merged"
        return DeliveryInventory(
            lanes=tuple(_lane(n, s) for n, s in sorted(self.status.items()))
        )

    def _call(self, name: str, number: int, after: str) -> None:
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            self.calls.append((name, number))
            queued_failures = self.failures.get((name, number))
            if queued_failures:
                raise queued_failures.pop(0)
            self.status[number] = after
        finally:
            self.in_flight -= 1

    def enqueue(self, *, pull_request_number: int) -> object:
        self._call("enqueue", pull_request_number, "queued")
        return {}

    def cleanup_merged(self, number: int, *, operation_lease: object = None) -> object:
        self._call("cleanup-merged", number, "done")
        return {}

    def release_published(
        self, number: int, *, operation_lease: object = None
    ) -> object:
        self._call("release-published", number, "pending")
        return {}


def _service(fleet: FakeFleet, **kwargs: object) -> tuple[DrainService, list[float]]:
    sleeps: list[float] = []
    clock = {"now": 0.0}

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        clock["now"] += seconds

    service = DrainService(
        application=fleet,  # type: ignore[arg-type]
        sleep=sleep,
        clock=lambda: clock["now"],
        **kwargs,  # type: ignore[arg-type]
    )
    return service, sleeps


def test_twenty_simulated_prs_drain_in_one_process_without_a_red_enqueue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("drain must not spawn a delivery.py process")

    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    statuses = {n: "green" for n in range(1, 15)}
    statuses.update({n: "red" for n in range(15, 18)})
    statuses.update({n: "pending" for n in range(18, 21)})
    fleet = FakeFleet(statuses)
    service, _ = _service(fleet)

    report = service.run(timeout=100)

    enqueued = {n for name, n in fleet.calls if name == "enqueue"}
    cleaned = {n for name, n in fleet.calls if name == "cleanup-merged"}
    assert enqueued == set(range(1, 15))  # green only: never red, never pending
    assert cleaned == enqueued  # cleanup follows every merge in the same drain
    assert fleet.max_in_flight == 1  # strictly sequential, one process
    assert report.stopped == "timeout"  # pending/red lanes keep the pump waiting
    assert {a.pull_request for a in report.waiting} == set(range(18, 21))


def test_drain_settles_when_nothing_is_left_to_wait_for() -> None:
    fleet = FakeFleet({1: "green", 2: "merged", 3: "done"})
    service, sleeps = _service(fleet)

    report = service.run()

    assert report.stopped == "settled"
    assert fleet.calls == [("cleanup-merged", 2), ("enqueue", 1), ("cleanup-merged", 1)]
    assert fleet.status == {1: "done", 2: "done", 3: "done"}
    assert sleeps  # it paused between cycles while PR #1 sat in the queue


def test_once_runs_a_single_cycle_and_dry_run_executes_nothing() -> None:
    fleet = FakeFleet({1: "green", 2: "merged"})
    service, sleeps = _service(fleet)

    once = service.run(once=True)
    assert once.stopped == "once" and once.cycles == 1 and not sleeps
    assert fleet.calls == [("cleanup-merged", 2), ("enqueue", 1)]

    fleet = FakeFleet({1: "green", 2: "merged"})
    service, _ = _service(fleet)
    dry = service.run(dry_run=True)
    assert dry.stopped == "dry-run" and fleet.calls == []
    assert {o.status for o in dry.outcomes} == {DrainStatus.PLANNED}
    assert [o.action.kind for o in dry.outcomes] == [
        DrainKind.CLEANUP_MERGED,
        DrainKind.ENQUEUE,
    ]


def test_waits_while_a_scope_owner_is_still_active() -> None:
    fleet = FakeFleet({1: "active", 2: "pending"})
    service, sleeps = _service(fleet)

    report = service.run(timeout=90, interval=30)

    assert report.stopped == "timeout"
    assert fleet.calls == [] and sleeps == [30, 30, 30]
    assert {a.lane for a in report.waiting} == {"LANE-1", "LANE-2"}


def test_lock_and_rate_limit_backoff_do_not_spend_attempts() -> None:
    fleet = FakeFleet({1: "green"})
    busy = DeliverySourceError("delivery mutation already in progress; command=x")
    limited = DeliverySourceError("GraphQL: API rate limit exceeded")
    fleet.failures[("enqueue", 1)] = [busy, limited] * (MAX_ATTEMPTS + 2)
    service, _ = _service(fleet)

    report = service.run(timeout=10_000)

    statuses = [o.status for o in report.outcomes]
    assert statuses.count(DrainStatus.BACKOFF) == 2 * (MAX_ATTEMPTS + 2)
    assert DrainStatus.FAILED not in statuses
    assert fleet.status[1] == "done"  # still drained after more backoffs than attempts


def test_a_real_refusal_exhausts_attempts_and_reports_stuck() -> None:
    fleet = FakeFleet({1: "green", 2: "green"})
    fleet.failures[("enqueue", 1)] = [PolicyViolation("head moved")] * 10
    service, _ = _service(fleet)

    report = service.run(timeout=10_000)

    assert report.stopped == "stuck"
    assert [c for c in fleet.calls if c == ("enqueue", 1)] == [
        ("enqueue", 1)
    ] * MAX_ATTEMPTS
    assert fleet.status[2] == "done"  # one bad PR does not block the others
    failed = [o for o in report.outcomes if o.status is DrainStatus.FAILED]
    assert len(failed) == MAX_ATTEMPTS


def test_plan_ignores_a_lane_without_an_addressable_pull_request() -> None:
    lane = _lane(5, "merged")
    lane = LaneInspection(**{**lane.__dict__, "pull_requests": ()})
    assert plan_actions(DeliveryInventory(lanes=(lane,))) == ()


def test_released_lane_releases_local_assets() -> None:
    fleet = FakeFleet({4: "released"})
    service, _ = _service(fleet)
    service.run(once=True)
    assert fleet.calls == [("release-published", 4)]


def test_drain_is_a_scoped_lease_command_with_distinct_exit_codes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert "drain" in cli.SCOPED_LEASE_COMMANDS
    assert "drain" in cli.MUTATING_COMMANDS
    args = cli._parser().parse_args(["drain", "--once", "--dry-run", "--interval", "5"])
    assert (args.once, args.dry_run, args.interval) == (True, True, 5.0)

    class Stuck:
        stopped = "stuck"

    assert cli._result_exit_code("drain", Stuck()) == 1
    assert cli._result_exit_code("drain", {"stopped": "timeout"}) == 2
    assert cli._result_exit_code("drain", {"stopped": "settled"}) == 0
    assert cli._command_verdict("drain", {"stopped": "settled"}) == "settled"

    class App:
        repo = tmp_path

        def drain(self, **kwargs: object) -> object:
            assert kwargs["once"] is True and kwargs["dry_run"] is True
            assert callable(kwargs["operation_lease"])
            return {"stopped": "dry-run", "cycles": 1}

    code = cli.main(
        ["--repo", str(tmp_path), "drain", "--once", "--dry-run"],
        application_factory=lambda **_: App(),
    )
    assert code == 0
    assert json.loads(capsys.readouterr().out)["verdict"] == "dry-run"
