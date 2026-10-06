from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

OPS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPS))

from delivery_control.adapters.runtime import RuntimeStatusMap
from delivery_control.adapters.runtime_receipt import RuntimeReceiptFile
from delivery_control.application import build_application
from delivery_control.controller.runtime_watchdog import (
    evaluate_runtime_watchdog,
)
from delivery_control.domain.errors import (
    CompareAndSwapConflict,
    PolicyViolation,
)
from delivery_control.domain.runtime_models import (
    RUNTIME_SCHEMA,
    RuntimeReceipt,
    RuntimeState,
    WatchdogAction,
)

NOW = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)
THREAD = "supervisor-thread"


def _receipt(**changes: object) -> RuntimeReceipt:
    values: dict[str, object] = {
        "thread_id": THREAD,
        "state": RuntimeState.RUNNING,
        "last_progress_at": NOW - timedelta(seconds=30),
        "observed_at": NOW,
        "lease_until": NOW + timedelta(minutes=2),
        "cycle_id": "cycle-1",
    }
    values.update(changes)
    return RuntimeReceipt(**values)


def test_valid_running_lease_is_a_noop() -> None:
    decision = evaluate_runtime_watchdog(_receipt(), now=NOW)

    assert decision.action is WatchdogAction.NOOP
    assert decision.reason == "lease is valid"
    assert decision.wake_id is None


def test_waiting_for_future_event_is_a_noop_even_without_lease() -> None:
    decision = evaluate_runtime_watchdog(
        _receipt(
            state=RuntimeState.WAITING,
            lease_until=None,
            expected_next_event_at=NOW + timedelta(minutes=2),
        ),
        now=NOW,
    )

    assert decision.action is WatchdogAction.NOOP
    assert decision.reason == "waiting for expected event"


def test_stale_progress_returns_idempotent_wake_decision() -> None:
    receipt = _receipt(
        state=RuntimeState.IDLE,
        lease_until=None,
        last_progress_at=NOW - timedelta(minutes=11),
    )

    first = evaluate_runtime_watchdog(receipt, now=NOW)
    second = evaluate_runtime_watchdog(receipt, now=NOW + timedelta(seconds=1))

    assert first.action is WatchdogAction.WAKE
    assert first.reason == "progress is stale"
    assert first.wake_id == second.wake_id


def test_default_watchdog_tick_is_five_minutes() -> None:
    decision = evaluate_runtime_watchdog(
        _receipt(
            state=RuntimeState.IDLE,
            lease_until=None,
            last_progress_at=NOW - timedelta(minutes=5),
        ),
        now=NOW,
    )

    assert decision.action is WatchdogAction.WAKE


@pytest.mark.parametrize(
    "changes",
    (
        {"last_progress_at": NOW + timedelta(minutes=1)},
        {"observed_at": NOW + timedelta(minutes=1)},
        {
            "last_progress_at": NOW - timedelta(seconds=1),
            "observed_at": NOW - timedelta(seconds=2),
        },
    ),
)
def test_incoherent_runtime_timestamps_escalate_fail_closed(
    changes: dict[str, datetime],
) -> None:
    decision = evaluate_runtime_watchdog(
        _receipt(lease_until=None, **changes),
        now=NOW,
    )

    assert decision.action is WatchdogAction.ESCALATE
    assert decision.reason == (
        "runtime receipt timestamps are incoherent; external clock audit required"
    )
    assert decision.wake_id is None


@pytest.mark.parametrize("state", (RuntimeState.FROZEN, RuntimeState.ARCHIVED))
def test_incoherent_frozen_or_archived_runtime_stays_noop(
    state: RuntimeState,
) -> None:
    decision = evaluate_runtime_watchdog(
        _receipt(
            state=state,
            last_progress_at=NOW + timedelta(minutes=1),
            observed_at=NOW + timedelta(minutes=1),
        ),
        now=NOW,
    )

    assert decision.action is WatchdogAction.NOOP
    assert decision.reason == f"runtime is {state.value}"
    assert decision.wake_id is None


def test_expired_lease_wakes_even_when_last_progress_is_recent() -> None:
    decision = evaluate_runtime_watchdog(
        _receipt(
            state=RuntimeState.IDLE,
            lease_until=NOW - timedelta(seconds=1),
        ),
        now=NOW,
    )

    assert decision.action is WatchdogAction.WAKE
    assert decision.reason == "lease expired"


def test_stale_running_runtime_escalates_instead_of_starting_a_second_turn() -> None:
    decision = evaluate_runtime_watchdog(
        _receipt(lease_until=None, last_progress_at=NOW - timedelta(minutes=11)),
        now=NOW,
    )

    assert decision.action is WatchdogAction.ESCALATE
    assert decision.reason == (
        "running runtime progress is stale; external status check required"
    )
    assert decision.wake_id is None


def test_already_recorded_wake_is_not_reissued() -> None:
    stale = _receipt(
        state=RuntimeState.IDLE,
        lease_until=None,
        last_progress_at=NOW - timedelta(minutes=11),
    )
    first = evaluate_runtime_watchdog(stale, now=NOW)
    recorded = _receipt(
        state=RuntimeState.IDLE,
        lease_until=None,
        last_progress_at=stale.last_progress_at,
        last_action_id=first.wake_id,
    )

    second = evaluate_runtime_watchdog(recorded, now=NOW + timedelta(seconds=1))

    assert first.action is WatchdogAction.WAKE
    assert second.action is WatchdogAction.ESCALATE
    assert second.reason == "wake already issued for current stale receipt"


def test_due_waiting_event_can_wake_once() -> None:
    decision = evaluate_runtime_watchdog(
        _receipt(
            state=RuntimeState.WAITING,
            lease_until=None,
            expected_next_event_at=NOW - timedelta(seconds=1),
        ),
        now=NOW,
    )

    assert decision.action is WatchdogAction.WAKE
    assert decision.reason == "expected event is due"


def test_frozen_and_archived_runtimes_are_not_woken() -> None:
    for state in (RuntimeState.FROZEN, RuntimeState.ARCHIVED):
        decision = evaluate_runtime_watchdog(_receipt(state=state), now=NOW)
        assert decision.action is WatchdogAction.NOOP
        assert decision.reason == f"runtime is {state.value}"


def test_missing_receipt_escalates_instead_of_guessing() -> None:
    decision = evaluate_runtime_watchdog(None, now=NOW)

    assert decision.action is WatchdogAction.ESCALATE
    assert decision.reason == "runtime receipt is missing"


def test_runtime_receipt_round_trips_through_status_file(tmp_path: Path) -> None:
    receipt = _receipt(expected_next_event_at=NOW + timedelta(minutes=1))
    path = tmp_path / "runtime.json"
    path.write_text(json.dumps(receipt.to_payload()), encoding="utf-8")

    runtime = RuntimeStatusMap.from_file(path)

    assert runtime.owner_status(THREAD) == "running"
    assert runtime.runtime_receipt(THREAD) == receipt


def test_missing_runtime_status_file_is_unknown_for_watchdog(tmp_path: Path) -> None:
    runtime = RuntimeStatusMap.from_file(tmp_path / "missing.json")

    assert runtime.owner_status(THREAD) == "unknown"
    assert runtime.runtime_receipt(THREAD) is None


def test_runtime_receipt_file_is_atomic_monotonic_and_cas_protected(
    tmp_path: Path,
) -> None:
    path = tmp_path / "runtime" / "supervisor.json"
    store = RuntimeReceiptFile(path)
    first = _receipt(state=RuntimeState.IDLE, lease_until=None)

    assert store.write(first) == first
    newer = _receipt(
        state=RuntimeState.RUNNING,
        observed_at=NOW + timedelta(seconds=1),
        last_progress_at=NOW + timedelta(seconds=1),
        cycle_id="cycle-2",
    )
    assert store.write(newer, expected_cycle_id="cycle-1") == newer
    assert store.read() == newer

    with pytest.raises(CompareAndSwapConflict, match="cycle changed"):
        store.write(
            _receipt(
                state=RuntimeState.IDLE,
                observed_at=NOW + timedelta(seconds=2),
                last_progress_at=NOW + timedelta(seconds=2),
                cycle_id="cycle-3",
            ),
            expected_cycle_id="cycle-1",
        )

    with pytest.raises(CompareAndSwapConflict, match="moved backwards"):
        store.write(
            _receipt(
                state=RuntimeState.IDLE,
                observed_at=NOW,
                last_progress_at=NOW,
                cycle_id="cycle-4",
            )
        )

    with pytest.raises(CompareAndSwapConflict, match="thread changed"):
        store.write(
            _receipt(
                thread_id="another-supervisor",
                observed_at=NOW + timedelta(seconds=2),
                last_progress_at=NOW + timedelta(seconds=2),
                cycle_id="cycle-5",
            )
        )


def test_runtime_receipt_wake_claim_is_single_consumer(tmp_path: Path) -> None:
    path = tmp_path / "runtime" / "supervisor.json"
    store = RuntimeReceiptFile(path)
    stale = _receipt(
        state=RuntimeState.IDLE,
        lease_until=None,
        last_progress_at=NOW - timedelta(minutes=11),
    )
    assert store.write(stale) == stale

    first = evaluate_runtime_watchdog(stale, now=NOW)
    assert first.action is WatchdogAction.WAKE
    assert first.wake_id is not None
    claimed = store.write(
        _receipt(
            state=stale.state,
            lease_until=None,
            last_progress_at=stale.last_progress_at,
            last_action_id=first.wake_id,
        ),
        expected_cycle_id=stale.cycle_id,
        expected_last_action_id=None,
    )
    assert claimed.last_action_id == first.wake_id

    with pytest.raises(CompareAndSwapConflict, match="wake action changed"):
        store.write(
            _receipt(
                state=stale.state,
                lease_until=None,
                last_progress_at=stale.last_progress_at,
                last_action_id=first.wake_id,
            ),
            expected_cycle_id=stale.cycle_id,
            expected_last_action_id=None,
        )


def test_runtime_receipt_new_cycle_can_clear_consumed_wake(tmp_path: Path) -> None:
    path = tmp_path / "runtime" / "supervisor.json"
    store = RuntimeReceiptFile(path)
    stale = _receipt(
        state=RuntimeState.IDLE,
        lease_until=None,
        last_progress_at=NOW - timedelta(minutes=11),
    )
    wake_id = evaluate_runtime_watchdog(stale, now=NOW).wake_id
    assert wake_id is not None
    claimed = _receipt(
        state=stale.state,
        lease_until=None,
        last_progress_at=stale.last_progress_at,
        last_action_id=wake_id,
    )
    assert store.write(claimed, expected_last_action_id=None) == claimed

    next_cycle = _receipt(
        state=RuntimeState.RUNNING,
        observed_at=NOW + timedelta(seconds=1),
        last_progress_at=NOW + timedelta(seconds=1),
        cycle_id="cycle-2",
        last_action_id=None,
        lease_until=NOW + timedelta(minutes=2),
    )
    assert store.write(next_cycle, expected_cycle_id="cycle-1") == next_cycle


def test_runtime_status_map_keeps_legacy_owner_status_support(tmp_path: Path) -> None:
    path = tmp_path / "runtime.json"
    path.write_text(json.dumps({THREAD: "running"}), encoding="utf-8")

    runtime = RuntimeStatusMap.from_file(path)

    assert runtime.owner_status(THREAD) == "running"
    assert runtime.runtime_receipt(THREAD) is None


def test_malformed_runtime_receipt_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "runtime.json"
    path.write_text(
        json.dumps({"schema": RUNTIME_SCHEMA, "thread_id": THREAD}),
        encoding="utf-8",
    )

    with pytest.raises(PolicyViolation, match="runtime receipt is malformed"):
        RuntimeStatusMap.from_file(path)


@pytest.mark.parametrize("payload", (["not", "an", "object"], "not an object", None))
def test_runtime_receipt_file_rejects_non_object_json_payloads(
    tmp_path: Path,
    payload: object,
) -> None:
    path = tmp_path / "runtime.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(PolicyViolation, match="runtime receipt is unreadable"):
        RuntimeReceiptFile(path).read()


def test_invalid_stale_threshold_is_rejected() -> None:
    with pytest.raises(ValueError, match="positive integer"):
        evaluate_runtime_watchdog(_receipt(), now=NOW, stale_after_seconds=0)


def test_application_watchdog_is_read_only_and_returns_decision(tmp_path: Path) -> None:
    receipt = _receipt(
        state=RuntimeState.IDLE,
        lease_until=None,
        last_progress_at=NOW - timedelta(minutes=11),
    )
    path = tmp_path / "runtime.json"
    path.write_text(json.dumps(receipt.to_payload()), encoding="utf-8")

    application = build_application(repo=tmp_path, runtime_status_file=path)
    decision = application.watchdog(supervisor_thread_id=THREAD, now=NOW)

    assert decision.action is WatchdogAction.WAKE
    assert decision.wake_id is not None
    assert decision.wake_claimed is False


def test_application_watchdog_claim_persists_before_external_dispatch(
    tmp_path: Path,
) -> None:
    receipt = _receipt(
        state=RuntimeState.IDLE,
        lease_until=None,
        last_progress_at=NOW - timedelta(minutes=11),
    )
    path = tmp_path / "runtime.json"
    path.write_text(json.dumps(receipt.to_payload()), encoding="utf-8")

    first_application = build_application(repo=tmp_path, runtime_status_file=path)
    first = first_application.watchdog_claim(supervisor_thread_id=THREAD, now=NOW)

    assert first.action is WatchdogAction.WAKE
    assert first.wake_claimed is True
    assert first.wake_id is not None

    second_application = build_application(repo=tmp_path, runtime_status_file=path)
    second = second_application.watchdog_claim(
        supervisor_thread_id=THREAD,
        now=NOW + timedelta(seconds=1),
    )

    assert second.action is WatchdogAction.ESCALATE
    assert second.reason == "wake already issued for current stale receipt"
