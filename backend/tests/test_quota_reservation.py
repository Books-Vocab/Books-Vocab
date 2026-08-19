"""In-flight quota reservation — defends the gap between pre-flight check
and post-call `record()`.

Root cause: `check_quota` reads `used` from already-recorded token usage,
but quota is checked BEFORE the LLM call and tokens are recorded AFTER it.
Concurrent same-user requests (multi-tab translate, or a single pipeline
run fanning out 5-way enrich batches via ThreadPoolExecutor) all pass the
gate before the first `record()` lands → unbounded over-spend.

Fix: an in-memory per-user reservation registry. A caller optimistically
reserves an estimated cost before the call; the gate counts reservations
on top of recorded usage; the reservation is released once the real cost
is recorded.

DB isolation mirrors test_quota_service.py: patch `_get_conn`/`_lock`.
"""

from __future__ import annotations

import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import pytest

import kg.quota_service as qs


@pytest.fixture
def mock_db(tmp_path, monkeypatch):
    import kg.llm_error_log as llm_error_log
    import kg.token_tracker as token_tracker

    monkeypatch.setattr(token_tracker, "DATA_DIR", tmp_path)
    monkeypatch.setattr(token_tracker, "DB_PATH", tmp_path / "token_usage.db")
    monkeypatch.setattr(llm_error_log, "DATA_DIR", tmp_path)
    monkeypatch.setattr(llm_error_log, "DB_PATH", tmp_path / "llm_errors.db")
    token_tracker.reset()
    llm_error_log.reset()

    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.execute(
        """
        CREATE TABLE token_usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            call_type TEXT NOT NULL,
            input_tokens INTEGER NOT NULL DEFAULT 0,
            output_tokens INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            provider TEXT,
            model TEXT
        )
        """
    )
    conn.commit()
    lock = threading.Lock()
    with patch("kg.quota_service._get_conn", return_value=conn), \
         patch("kg.quota_service._lock", lock):
        yield conn

    token_tracker.reset()
    llm_error_log.reset()
    conn.close()

    assert token_tracker._conn is None, "token tracker connection leaked past fixture"
    assert llm_error_log._conn is None, "LLM error connection leaked past fixture"


@pytest.fixture(autouse=True)
def _stable_limits_and_clean_reservations():
    qs.configure_limits(pro=0.30, free=0.03)
    qs.clear_reservations()
    yield
    qs.clear_reservations()
    qs.configure_limits(pro=0.30, free=0.03)


# ── reservation primitive ─────────────────────────────────────────


def test_reservation_counts_against_quota(mock_db):
    """A reservation alone (no recorded usage) makes the gate see usage."""
    # Free limit $0.03. Reserve $0.02 → still under, not exceeded.
    with qs.reserve("u1", 0.02):
        q = qs.check_quota("u1", "translate", is_pro=False)
        assert q["exceeded"] is False
        assert q["fraction"] == pytest.approx(1.0 / 3.0, abs=0.01)


def test_reservation_released_on_context_exit(mock_db):
    """Once the with-block exits, the reservation no longer counts."""
    with qs.reserve("u1", 0.02):
        pass
    q = qs.check_quota("u1", "translate", is_pro=False)
    assert q["exceeded"] is False
    assert q["fraction"] == pytest.approx(1.0, abs=0.001)


def test_reservation_released_even_on_exception(mock_db):
    """A handler failure must not leak the reservation forever."""
    with pytest.raises(RuntimeError):
        with qs.reserve("u1", 0.02):
            raise RuntimeError("boom")
    q = qs.check_quota("u1", "translate", is_pro=False)
    assert q["fraction"] == pytest.approx(1.0, abs=0.001)


def test_stacked_reservations_block_when_sum_exceeds_limit(mock_db):
    """Two concurrent in-flight reservations whose sum tops the limit
    must make a third check report exceeded — the core defense."""
    with qs.reserve("u1", 0.02), qs.reserve("u1", 0.02):
        q = qs.check_quota("u1", "translate", is_pro=False)
        assert q["exceeded"] is True


# ── concurrency repro ─────────────────────────────────────────────


def _estimate_for(_call_type: str) -> float:
    """Per-call estimate used by the gate. translate ≈ $0.012 each."""
    return 0.012


def test_concurrent_translate_requests_overspend_without_reservation(mock_db):
    """REPRODUCTION: without reservation, N concurrent same-user requests
    all see used=0 and pass the gate, even though each costs $0.012 and
    the free limit is $0.03 → only ~2 should be allowed.
    """
    passed = []

    def request_without_reservation():
        # Mirrors the OLD gate: check recorded usage only.
        q = qs.check_quota("u1", "translate", is_pro=False)
        if not q["exceeded"]:
            passed.append(True)
        # record() happens "later" — simulate the post-call lag by not
        # recording at all during the burst.

    with ThreadPoolExecutor(max_workers=10) as ex:
        for _ in range(10):
            ex.submit(request_without_reservation)

    # All 10 slip through — the bug. Free budget = $0.03 / $0.012 ≈ 2.
    assert len(passed) == 10, "expected the unguarded gate to leak all requests"


def test_concurrent_translate_requests_converge_with_reservation(mock_db):
    """With reservation: the gate counts in-flight reservations, so a
    burst of 10 concurrent requests converges to ~2 admissions (the
    real free budget), not 10.
    """
    admitted = []
    lock = threading.Lock()

    def request_with_reservation():
        # New gate: check recorded usage + outstanding reservations.
        q = qs.check_quota("u1", "translate", is_pro=False)
        if q["exceeded"]:
            return
        # Admitted → hold a reservation for the call's duration.
        with qs.reserve("u1", _estimate_for("translate")):
            with lock:
                admitted.append(True)
            # Simulate the LLM call taking time while the reservation
            # is held by all other in-flight requests.
            threading.Event().wait(0.05)

    with ThreadPoolExecutor(max_workers=10) as ex:
        futs = [ex.submit(request_with_reservation) for _ in range(10)]
        for f in futs:
            f.result()

    # $0.03 / $0.012 = 2.5 → at most 2 (3rd reservation would exceed).
    assert 1 <= len(admitted) <= 3, f"expected ~2 admissions, got {len(admitted)}"
    assert len(admitted) < 10, "reservation must stop the unbounded leak"


# ── TrackedLLM integration ────────────────────────────────────────


class _FakeUsage:
    def __init__(self, prompt: int, completion: int) -> None:
        self.prompt_tokens = prompt
        self.completion_tokens = completion
        self.total_tokens = prompt + completion


class _FakeResp:
    def __init__(self, prompt: int, completion: int) -> None:
        self.usage = _FakeUsage(prompt, completion)


def test_tracked_llm_holds_reservation_during_call(mock_db):
    """While a TrackedLLM call is in flight, the user's reserved cost is
    non-zero — so a concurrent gate check sees the in-flight spend.
    """
    from kg.tracked_llm import TrackedLLM

    observed = {}

    class _SlowClient:
        class chat:  # noqa: N801
            class completions:  # noqa: N801
                @staticmethod
                def create(**_kwargs):
                    # Mid-call: the reservation must already be visible.
                    observed["reserved_mid_call"] = qs._reserved_usd("u1")
                    return _FakeResp(100, 50)

    llm = TrackedLLM(_SlowClient(), "u1")
    llm.chat("translate")

    assert observed["reserved_mid_call"] == pytest.approx(qs.ESTIMATED_CALL_COST_USD)
    # After the call returns, the reservation is released.
    assert qs._reserved_usd("u1") == 0.0


def test_tracked_llm_releases_reservation_on_call_failure(mock_db):
    """A failing LLM call must not leak the reservation."""
    from kg.tracked_llm import TrackedLLM

    class _BoomClient:
        class chat:  # noqa: N801
            class completions:  # noqa: N801
                @staticmethod
                def create(**_kwargs):
                    raise RuntimeError("api down")

    llm = TrackedLLM(_BoomClient(), "u1")
    with pytest.raises(RuntimeError, match="api down"):
        llm.chat("translate")
    assert qs._reserved_usd("u1") == 0.0


def test_tracked_llm_enforced_quota_blocks_before_call(mock_db):
    from kg.exceptions import QuotaExceededError
    from kg.tracked_llm import TrackedLLM

    qs.configure_limits(pro=0.30, free=0.001)

    class _Client:
        called = False

        class chat:  # noqa: N801
            class completions:  # noqa: N801
                @staticmethod
                def create(**_kwargs):
                    _Client.called = True
                    return _FakeResp(100, 50)

    llm = TrackedLLM(_Client(), "u1", enforce_quota=True, is_pro=False)

    with pytest.raises(QuotaExceededError):
        llm.chat("translate")
    assert _Client.called is False
    assert qs._reserved_usd("u1") == 0.0


def test_enforced_reservation_reads_recorded_usage_outside_reservation_lock(mock_db, monkeypatch):
    """Admission must not hold reservation_lock while reading SQLite usage.

    token_tracker.record() takes the DB lock first and then releases the
    reservation on context exit. Holding reservation_lock while waiting on the
    DB lock creates the reverse order and can deadlock under load.
    """
    calls = []

    def recorded(user_id: str) -> float:
        calls.append(user_id)
        assert qs._reservation_lock.locked() is False
        return 0.0

    monkeypatch.setattr(qs, "_recorded_usd", recorded)

    with qs.reserve("u1", 0.001, enforce=True, is_pro=False):
        assert qs._reserved_usd("u1") == pytest.approx(0.001)

    assert calls == ["u1"]


def test_enforced_reservation_retries_if_inflight_finishes_during_recorded_read(mock_db, monkeypatch):
    """If a reservation is released while recorded usage is being read, retry
    the DB read so admission does not miss both the old reservation and the
    newly recorded usage."""
    from kg.exceptions import QuotaExceededError

    qs.configure_limits(pro=0.30, free=0.021)
    with qs._reservation_lock:
        qs._reservations[999_001] = ("u1", 0.02)
        qs._reservation_version += 1

    calls = 0

    def recorded(user_id: str) -> float:
        nonlocal calls
        assert user_id == "u1"
        calls += 1
        if calls == 1:
            with qs._reservation_lock:
                qs._reservations.pop(999_001, None)
                qs._reservation_version += 1
            return 0.0
        return 0.02

    monkeypatch.setattr(qs, "_recorded_usd", recorded)

    with pytest.raises(QuotaExceededError):
        with qs.reserve("u1", 0.005, enforce=True, is_pro=False):
            pass

    assert calls == 2
    assert qs._reserved_usd("u1") == 0.0


def test_enforced_reservation_retries_on_equal_sum_reservation_swap(mock_db, monkeypatch):
    """Reservation total can stay unchanged while composition changes.

    Example: A finishes and moves from reservation to recorded usage while B
    adds an equal reservation. Admission must notice the version change and
    re-read recorded usage, not trust the unchanged reserved total.
    """
    from kg.exceptions import QuotaExceededError

    qs.configure_limits(pro=0.30, free=0.04)
    with qs._reservation_lock:
        qs._reservations[999_101] = ("u1", 0.02)
        qs._reservation_version += 1

    calls = 0

    def recorded(user_id: str) -> float:
        nonlocal calls
        assert user_id == "u1"
        calls += 1
        if calls == 1:
            with qs._reservation_lock:
                qs._reservations.pop(999_101, None)
                qs._reservations[999_102] = ("u1", 0.02)
                qs._reservation_version += 2
            return 0.0
        return 0.02

    monkeypatch.setattr(qs, "_recorded_usd", recorded)

    with pytest.raises(QuotaExceededError):
        with qs.reserve("u1", 0.015, enforce=True, is_pro=False):
            pass

    assert calls == 2
    with qs._reservation_lock:
        qs._reservations.pop(999_102, None)
        qs._reservation_version += 1


def test_tracked_llm_pipeline_burst_blocks_via_gate(mock_db):
    """Simulated pipeline enrich fan-out: 5 concurrent TrackedLLM calls for
    a Free user. The reservation makes the gate observe in-flight spend, so
    a check during the burst reports the user as quota-exceeded.
    """
    from kg.tracked_llm import TrackedLLM

    barrier = threading.Barrier(6)  # 5 workers + main thread
    gate_seen_exceeded = []

    class _BlockingClient:
        class chat:  # noqa: N801
            class completions:  # noqa: N801
                @staticmethod
                def create(**_kwargs):
                    barrier.wait(timeout=5)  # hold all 5 reservations at once
                    return _FakeResp(100, 50)

    def worker():
        TrackedLLM(_BlockingClient(), "u1").chat("translate")

    with ThreadPoolExecutor(max_workers=5) as ex:
        futs = [ex.submit(worker) for _ in range(5)]
        barrier.wait(timeout=5)  # all 5 calls now in flight, reservations held
        # 5 * $0.012 = $0.06 reserved > Free $0.03 → gate must block now.
        q = qs.check_quota("u1", "translate", is_pro=False)
        gate_seen_exceeded.append(q["exceeded"])
        for f in futs:
            f.result()

    assert gate_seen_exceeded == [True], "gate must see in-flight burst as over-quota"
