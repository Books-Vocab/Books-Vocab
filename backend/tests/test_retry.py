from __future__ import annotations

import asyncio
import random

import pytest

from kg.retry import async_retry, sync_retry


def test_async_retry_success_first_attempt():
    call_count = 0

    async def fn():
        nonlocal call_count
        call_count += 1
        return "done"

    result = asyncio.run(async_retry(fn, max_attempts=3, retryable_exceptions=(OSError,), step_name="T", uid="u"))
    assert result == "done"
    assert call_count == 1


def test_async_retry_success_after_transient_failure():
    calls = []

    async def fn():
        calls.append(1)
        if len(calls) == 1:
            raise OSError("transient")
        return "done"

    result = asyncio.run(async_retry(fn, max_attempts=3, base_delay=0.0, retryable_exceptions=(OSError,), step_name="T", uid="u"))
    assert result == "done"
    assert len(calls) == 2


def test_async_retry_raises_after_max_attempts():
    calls = []

    async def fn():
        calls.append(1)
        raise OSError("always")

    with pytest.raises(OSError, match="always"):
        asyncio.run(async_retry(fn, max_attempts=3, base_delay=0.0, retryable_exceptions=(OSError,), step_name="T", uid="u"))
    assert len(calls) == 3


def test_async_retry_non_retryable_raises_immediately():
    calls = []

    async def fn():
        calls.append(1)
        raise ValueError("not retryable")

    with pytest.raises(ValueError, match="not retryable"):
        asyncio.run(async_retry(fn, max_attempts=3, base_delay=0.0, retryable_exceptions=(OSError,), step_name="T", uid="u"))
    assert len(calls) == 1


# ---------- edge: jitter distribution ----------


def test_jitter_spreads_delays_across_range(monkeypatch):
    """Jitter formula `delay *= 0.5 + random.random()` should yield
    delays in [base*0.5, base*1.5) when base_delay is constant.

    Drives random.random() with deterministic values to verify spread.
    """
    recorded_sleeps: list[float] = []

    async def fake_sleep(d: float) -> None:
        recorded_sleeps.append(d)

    # 5 deterministic random samples (one per retry attempt where delay is computed)
    samples = iter([0.0, 0.25, 0.5, 0.75, 0.999])
    monkeypatch.setattr("kg.retry.random.random", lambda: next(samples))
    monkeypatch.setattr("kg.retry.asyncio.sleep", fake_sleep)

    async def always_fail():
        raise OSError("transient")

    # Use base_delay=2 and max_delay large so exponential backoff isn't clamped.
    # max_attempts=6 → 5 retries (delays computed for attempt 0..4).
    async def run():
        with pytest.raises(OSError):
            await async_retry(
                always_fail,
                max_attempts=6,
                base_delay=2.0,
                max_delay=1000.0,
                retryable_exceptions=(OSError,),
                step_name="T",
                uid="u",
            )

    asyncio.run(run())

    # 5 sleeps recorded, one per retry.
    assert len(recorded_sleeps) == 5

    # Each sleep d at attempt i must satisfy: base*2^i * 0.5 <= d < base*2^i * 1.5
    for i, observed in enumerate(recorded_sleeps):
        base_expected = 2.0 * (2 ** i)
        lower = base_expected * 0.5
        upper = base_expected * 1.5
        assert lower <= observed < upper, (
            f"attempt {i}: delay {observed} not in [{lower}, {upper})"
        )

    # Normalise by base*2^i — should span the [0.5, 1.5) jitter range.
    ratios = [d / (2.0 * (2 ** i)) for i, d in enumerate(recorded_sleeps)]
    assert min(ratios) < 0.75, f"jitter never produced a low value: {ratios}"
    assert max(ratios) > 1.25, f"jitter never produced a high value: {ratios}"
    assert max(ratios) - min(ratios) > 0.5, f"jitter spread too narrow: {ratios}"


# ---------- edge: async cancellation propagation ----------


def test_cancel_during_async_retry_does_not_swallow_cancellation():
    """asyncio.CancelledError must propagate out of async_retry even when
    using the permissive default retryable_exceptions=(Exception,).

    In Python 3.8+, CancelledError inherits from BaseException (not Exception),
    so this guards against a future regression that changes the default.
    """
    attempts = 0

    async def slow_fail():
        nonlocal attempts
        attempts += 1
        # Sleep long enough that cancellation lands while we are inside fn.
        await asyncio.sleep(10)

    async def run():
        # Default retryable_exceptions=(Exception,) — the broadest catch.
        task = asyncio.create_task(
            async_retry(
                slow_fail,
                max_attempts=5,
                base_delay=0.0,
                step_name="T",
                uid="u",
            )
        )
        # Yield once so task starts and enters the inner sleep.
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        # fn should have been entered exactly once; retry must NOT swallow
        # cancellation and re-enter fn.
        assert attempts == 1

    asyncio.run(run())


def test_cancel_during_async_retry_sleep_propagates():
    """Cancellation while *sleeping between retries* must also propagate
    rather than be silently absorbed and treated as a new retry trigger.
    """
    fn_calls = 0

    async def always_fail():
        nonlocal fn_calls
        fn_calls += 1
        raise OSError("boom")

    async def run():
        task = asyncio.create_task(
            async_retry(
                always_fail,
                max_attempts=10,
                base_delay=5.0,  # long sleep so we can cancel during backoff
                max_delay=60.0,
                retryable_exceptions=(OSError,),
                step_name="T",
                uid="u",
            )
        )
        # Let the task hit the first failure and enter asyncio.sleep().
        for _ in range(5):
            await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        # Should have failed once, then been cancelled mid-sleep — no further attempts.
        assert fn_calls == 1

    asyncio.run(run())


# ---------- edge: nested retry attempt explosion ----------


def test_nested_retry_does_not_explode_attempts_multiplicatively():
    """Documents (characterises) nested retry behaviour.

    Outer retry wraps inner retry. When the inner exhausts its budget and
    re-raises a retryable exception, the outer re-invokes the inner — so total
    fn calls = outer_max * inner_max in the worst case (here 3*3 = 9).

    This test pins that behaviour so future changes (e.g. attempt budget
    sharing, exception tagging to short-circuit outer) are intentional.
    """
    inner_calls = 0

    async def inner_fail():
        nonlocal inner_calls
        inner_calls += 1
        raise OSError("inner")

    async def outer():
        return await async_retry(
            inner_fail,
            max_attempts=3,
            base_delay=0.0,
            retryable_exceptions=(OSError,),
            step_name="inner",
            uid="u",
        )

    async def run():
        with pytest.raises(OSError, match="inner"):
            await async_retry(
                outer,
                max_attempts=3,
                base_delay=0.0,
                retryable_exceptions=(OSError,),
                step_name="outer",
                uid="u",
            )

    asyncio.run(run())

    # Characterisation: current implementation does NOT share budgets, so
    # the call count is exactly outer × inner.
    assert inner_calls == 9, (
        f"expected 9 (3 outer × 3 inner) inner calls under naive nesting, got {inner_calls}"
    )


# ---------- edge: sync_retry jitter bounds ----------


def test_sync_retry_respects_max_delay_with_jitter(monkeypatch):
    """sync_retry should clamp exponential backoff to max_delay BEFORE jitter,
    then apply jitter — so observed sleep stays within [max_delay*0.5, max_delay*1.5).
    """
    sleeps: list[float] = []
    monkeypatch.setattr("kg.retry.time.sleep", lambda d: sleeps.append(d))
    # Force jitter to upper bound.
    monkeypatch.setattr("kg.retry.random.random", lambda: 0.999)

    attempts = 0

    def always_fail():
        nonlocal attempts
        attempts += 1
        raise OSError("boom")

    with pytest.raises(OSError):
        sync_retry(
            always_fail,
            max_attempts=5,
            base_delay=10.0,
            max_delay=4.0,  # smaller than base_delay → always clamped
            retryable_exceptions=(OSError,),
            step_name="T",
            uid="u",
        )

    # 4 sleeps recorded (one per retry, the final attempt does not sleep).
    assert len(sleeps) == 4
    for d in sleeps:
        assert d < 4.0 * 1.5, f"delay {d} exceeds max_delay*1.5 jitter ceiling"
        assert d >= 4.0 * 0.5, f"delay {d} below max_delay*0.5 jitter floor"
