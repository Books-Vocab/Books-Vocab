"""Tests for user lock management."""
import asyncio
import pytest
from kg.deps import get_user_lock, _USER_LOCKS


@pytest.fixture(autouse=True)
def _reset_locks():
    _USER_LOCKS.clear()
    yield
    _USER_LOCKS.clear()


@pytest.mark.asyncio
async def test_get_user_lock_returns_same_lock():
    lock1 = await get_user_lock("user_a")
    lock2 = await get_user_lock("user_a")
    assert lock1 is lock2


@pytest.mark.asyncio
async def test_concurrent_lock_creation():
    """Multiple concurrent calls for same user should get same lock."""
    results = await asyncio.gather(
        get_user_lock("user_b"),
        get_user_lock("user_b"),
        get_user_lock("user_b"),
    )
    assert results[0] is results[1] is results[2]
