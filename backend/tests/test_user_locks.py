"""Tests for user lock management."""
import asyncio

import pytest

import kg.deps as deps
from kg.deps import _USER_LOCKS, get_user_lock


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


@pytest.mark.asyncio
async def test_lru_keeps_held_and_queued_user_lock(monkeypatch):
    monkeypatch.setattr(deps, "_MAX_USER_LOCKS", 1)

    lock = await get_user_lock("user_a")
    await lock.acquire()
    queued = asyncio.create_task(lock.acquire())
    await asyncio.sleep(0)

    try:
        assert not queued.done()
        await get_user_lock("user_b")
        assert await get_user_lock("user_a") is lock

        # Release the holder without yielding: the waiter is still queued
        # while the lock is momentarily unlocked, so LRU must retain it.
        lock.release()
        assert not queued.done()
        await get_user_lock("user_c")
        assert await get_user_lock("user_a") is lock
    finally:
        if not queued.done():
            if lock.locked():
                lock.release()
            await queued
        if lock.locked():
            lock.release()
