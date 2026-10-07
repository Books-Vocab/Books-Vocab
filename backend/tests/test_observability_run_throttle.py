"""Tests for kg.observability_alerts.throttled_run_slot — the request-path gate (#2087).

`/api/system/info` is unauthenticated and rate-limit exempt, so the threshold
checks it piggybacks are gated per process. The endpoint-level contract lives in
test_system_info.py; these tests pin the gate's own semantics. Throttle state is
reset between tests by the autouse fixture in conftest.py.
"""

from __future__ import annotations

import threading

import pytest

from kg import observability_alerts


@pytest.fixture()
def clock(monkeypatch):
    now = [500.0]
    monkeypatch.setattr(observability_alerts, "_monotonic", lambda: now[0])
    return now


def test_first_slot_granted_then_refused_within_interval(clock):
    with observability_alerts.throttled_run_slot(interval_s=60) as granted:
        assert granted is True
    clock[0] += 59.9
    with observability_alerts.throttled_run_slot(interval_s=60) as granted:
        assert granted is False
    clock[0] += 0.1
    with observability_alerts.throttled_run_slot(interval_s=60) as granted:
        assert granted is True


def test_open_slot_blocks_overlap_even_after_interval(clock):
    # A run slower than the interval must not let a second run start beside
    # it: at most one thread ever holds the log-DB locks on our behalf.
    with observability_alerts.throttled_run_slot(interval_s=60) as first:
        assert first is True
        clock[0] += 3600
        with observability_alerts.throttled_run_slot(interval_s=60) as second:
            assert second is False
    with observability_alerts.throttled_run_slot(interval_s=60) as after:
        assert after is True


def test_default_interval_is_module_constant_resolved_at_call_time(clock, monkeypatch):
    monkeypatch.setattr(observability_alerts, "CHECK_INTERVAL_S", 5.0)
    with observability_alerts.throttled_run_slot() as granted:
        assert granted is True
    clock[0] += 4.9
    with observability_alerts.throttled_run_slot() as granted:
        assert granted is False
    clock[0] += 0.1
    with observability_alerts.throttled_run_slot() as granted:
        assert granted is True


def test_failed_run_releases_slot_but_keeps_interval(clock):
    with pytest.raises(RuntimeError, match="run blew up"):
        with observability_alerts.throttled_run_slot(interval_s=60) as granted:
            assert granted is True
            raise RuntimeError("run blew up")
    # Not retried immediately, so a failing check cannot become a retry storm ...
    with observability_alerts.throttled_run_slot(interval_s=60) as granted:
        assert granted is False
    # ... but the slot was released, so the next interval runs again.
    clock[0] += 60
    with observability_alerts.throttled_run_slot(interval_s=60) as granted:
        assert granted is True


def test_concurrent_threads_get_exactly_one_slot():
    n = 20
    barrier = threading.Barrier(n)
    all_decided = threading.Event()
    grants: list[bool] = []
    grants_lock = threading.Lock()

    def contender() -> None:
        barrier.wait()
        with observability_alerts.throttled_run_slot(interval_s=60) as granted:
            with grants_lock:
                grants.append(granted)
                if len(grants) == n:
                    all_decided.set()
            if granted:
                # Hold the slot open until every contender has been decided.
                all_decided.wait(timeout=5)

    threads = [threading.Thread(target=contender) for _ in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)
    assert sorted(grants) == [False] * (n - 1) + [True]


def test_reset_forgets_the_last_run(clock):
    with observability_alerts.throttled_run_slot(interval_s=60) as granted:
        assert granted is True
    observability_alerts._reset_run_throttle()
    with observability_alerts.throttled_run_slot(interval_s=60) as granted:
        assert granted is True
