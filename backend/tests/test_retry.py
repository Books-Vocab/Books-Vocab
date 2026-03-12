from __future__ import annotations

import asyncio
import pytest

from kg.retry import async_retry


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
