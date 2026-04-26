"""Tests for `_PIPELINE_RUNNING` refcount race (P0-2).

Background:
The previous implementation used a `dict[str, bool]` flag. A queued task
sets True before acquiring the lock; the in-flight task's `finally` calls
`pop(uid)` AFTER releasing the lock. The pop can race past the queued
task's set, clearing the flag while a second task is still pending. iOS
sees `X-Pipeline-Pending: false` and stops polling — second notebook
appears stale.

Fix: per-uid refcount. Increment on entry (covers both the lock-held
queued case and the immediate-acquire case); decrement on exit; flag is
True iff refcount > 0.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import kg.pipeline_service as ps
from kg.pipeline_service import is_pipeline_running, run_pipeline_background


class _FakeLogger:
    def info(self, *a, **k): pass
    def warning(self, *a, **k): pass
    def error(self, *a, **k): pass


class _CardsEmpty:
    def all(self, include_deleted: bool = False, notebook_id: str | None = None):
        return []
    def update(self, *a, **k): return None
    def batch_update(self, *a, **k): return 0
    def get(self, *a, **k): return None


class _GraphOk:
    def pop_candidates(self): return []
    def pop_pending_judge(self): return []
    def add_pending_judge(self, *a, **k): pass
    def add_candidate(self, *a, **k): pass
    def batch_add_candidates(self, *a, **k): return 0


class _EmbeddingsOk:
    def has(self, *a, **k): return True
    def add(self, *a, **k): pass
    def add_batch(self, *a, **k): pass
    def find_similar(self, *a, **k): return []


def test_is_pipeline_running_false_initially():
    """No pipelines running → flag False."""
    # Ensure clean state
    with ps._PIPELINE_RUNNING_LOCK:
        ps._PIPELINE_RUNNING.clear()
    assert is_pipeline_running("nope") is False


def test_refcount_two_concurrent_tasks_keep_flag_true():
    """Two tasks for same uid: flag stays True throughout overlap.

    Models the original race: task A finishes (decrements/pops) AFTER
    task B has incremented. Under refcount semantics, B's increment keeps
    the flag at 1 even after A's decrement → is_pipeline_running stays
    True until B also decrements.

    Direct reproduction: simulate both task entry points racing through
    the production increment/decrement code paths without needing real
    pipeline infra. We assert that the bool-style impl's race window
    (decrement-after-other-task's-increment) does not clear the flag.
    """
    uid = "race_uid"
    with ps._PIPELINE_RUNNING_LOCK:
        ps._PIPELINE_RUNNING.clear()

    # Re-implement the production enter/exit using ps internals.
    def enter():
        with ps._PIPELINE_RUNNING_LOCK:
            ps._PIPELINE_RUNNING[uid] = ps._PIPELINE_RUNNING.get(uid, 0) + 1

    def exit_():
        with ps._PIPELINE_RUNNING_LOCK:
            ps._PIPELINE_RUNNING[uid] = ps._PIPELINE_RUNNING.get(uid, 0) - 1
            if ps._PIPELINE_RUNNING[uid] <= 0:
                ps._PIPELINE_RUNNING.pop(uid, None)

    # Sequence reproducing the original incident (task A in-flight, task B
    # queued, both for same uid):
    enter()  # A enters
    assert is_pipeline_running(uid) is True

    enter()  # B queues — sees lock held, pre-sets flag
    assert is_pipeline_running(uid) is True

    # A's `finally` runs: with bool flag this would `pop(uid)` — clearing
    # B's set. With refcount, only decrements 2 → 1.
    exit_()
    assert is_pipeline_running(uid) is True, (
        "Refcount must keep flag True while another task is still pending"
    )

    # B finishes
    exit_()
    assert is_pipeline_running(uid) is False
    with ps._PIPELINE_RUNNING_LOCK:
        assert uid not in ps._PIPELINE_RUNNING


def test_refcount_in_real_pipeline_two_queued_runs():
    """End-to-end: two `run_pipeline_background` calls overlap through the
    same asyncio.Lock. Flag must stay True while the second is queued."""
    uid = "race_e2e"
    with ps._PIPELINE_RUNNING_LOCK:
        ps._PIPELINE_RUNNING.clear()

    user = {"id": uid, "dir": Path("/tmp/race_e2e"), "config": {}}
    shared_lock = asyncio.Lock()

    async def get_lock(_uid):
        return shared_lock

    async def run_task():
        await run_pipeline_background(
            user,
            get_user_lock_fn=get_lock,
            card_store_factory=lambda d: _CardsEmpty(),
            graph_store_factory=lambda d, notebook_id="default": _GraphOk(),
            embedding_store_factory=lambda d, llm=None, notebook_id="default": _EmbeddingsOk(),
            gemini_client_factory=lambda: None,
            logger=_FakeLogger(),
            link_kind_enum=lambda v: v,
        )

    async def driver():
        # Hold the lock while we start both tasks so each takes the
        # queued branch and increments before any release.
        await shared_lock.acquire()

        t1 = asyncio.create_task(run_task())
        for _ in range(5):
            await asyncio.sleep(0)
        assert is_pipeline_running(uid) is True

        t2 = asyncio.create_task(run_task())
        for _ in range(5):
            await asyncio.sleep(0)
        # Both queued → refcount 2
        with ps._PIPELINE_RUNNING_LOCK:
            assert ps._PIPELINE_RUNNING.get(uid) == 2

        shared_lock.release()
        await asyncio.gather(t1, t2)

        assert is_pipeline_running(uid) is False

    asyncio.run(driver())


def test_refcount_drops_to_zero_after_single_task():
    """Single task: flag True during, False after."""
    uid = "single_uid"
    with ps._PIPELINE_RUNNING_LOCK:
        ps._PIPELINE_RUNNING.clear()

    user = {"id": uid, "dir": Path("/tmp/single"), "config": {}}

    async def get_lock(_uid):
        return asyncio.Lock()

    async def driver():
        await run_pipeline_background(
            user,
            get_user_lock_fn=get_lock,
            card_store_factory=lambda d: _CardsEmpty(),
            graph_store_factory=lambda d, notebook_id="default": _GraphOk(),
            embedding_store_factory=lambda d, llm=None, notebook_id="default": _EmbeddingsOk(),
            gemini_client_factory=lambda: None,
            logger=_FakeLogger(),
            link_kind_enum=lambda v: v,
        )

    asyncio.run(driver())
    assert is_pipeline_running(uid) is False
    # And the entry should be popped from the dict to avoid memory leak
    with ps._PIPELINE_RUNNING_LOCK:
        assert uid not in ps._PIPELINE_RUNNING


def test_refcount_internal_value_increments_and_decrements():
    """Direct white-box check of refcount mechanics via manual
    increment/decrement following the same pattern as the production code.
    Ensures storage is integer-valued and pops at zero."""
    uid = "rc_uid"
    with ps._PIPELINE_RUNNING_LOCK:
        ps._PIPELINE_RUNNING.clear()

    # Simulate two overlapping tasks via the same lock-protected mutators
    # used in run_pipeline_background.
    def enter():
        with ps._PIPELINE_RUNNING_LOCK:
            ps._PIPELINE_RUNNING[uid] = ps._PIPELINE_RUNNING.get(uid, 0) + 1

    def exit_():
        with ps._PIPELINE_RUNNING_LOCK:
            ps._PIPELINE_RUNNING[uid] = ps._PIPELINE_RUNNING.get(uid, 0) - 1
            if ps._PIPELINE_RUNNING[uid] <= 0:
                ps._PIPELINE_RUNNING.pop(uid, None)

    enter()
    assert is_pipeline_running(uid) is True
    enter()
    assert is_pipeline_running(uid) is True
    exit_()
    # Critical: still True after one decrement
    assert is_pipeline_running(uid) is True
    exit_()
    assert is_pipeline_running(uid) is False
    with ps._PIPELINE_RUNNING_LOCK:
        assert uid not in ps._PIPELINE_RUNNING
