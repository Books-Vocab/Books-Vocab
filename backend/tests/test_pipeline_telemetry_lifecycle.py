"""Lifecycle edge tests for pipeline_log (start_run / start_step / end_run)."""

from __future__ import annotations

import asyncio
import logging
import threading
from pathlib import Path

import pytest

from kg import pipeline_log
from kg.pipeline_service import is_pipeline_running
from kg.pipeline_service import runner as pipeline_runner

pytestmark = pytest.mark.usefixtures("isolate_pipeline_db")


def test_pipeline_log_run_without_end_marked_running_until_timeout(tmp_path):
    """A run that never calls end_run stays 'running'; the explicit startup
    crash-recovery sweep (reap_orphaned_runs, wired into the API lifespan)
    reaps it to 'interrupted'.

    No wall-clock timeout exists today — recovery is the explicit startup
    reap. (Reaping is decoupled from _get_conn so reads never mutate; see
    test_pipeline_reaper_decoupling.)
    """
    pipeline_log.start_run("orphan_run", "u1", "nb1", "manual")
    pipeline_log.start_step("orphan_run", "Enrich")
    # intentionally no end_step / end_run — simulate a crashed worker

    runs = pipeline_log.get_runs("u1")
    assert len(runs) == 1
    assert runs[0]["status"] == "running"
    assert runs[0]["ended_at"] is None

    # Simulate a process restart: reopen the connection, then run the explicit
    # startup sweep the lifespan performs.
    pipeline_log._reset()
    pipeline_log.reap_orphaned_runs()

    runs_after = pipeline_log.get_runs("u1")
    assert len(runs_after) == 1
    assert runs_after[0]["status"] == "interrupted", (
        "Orphaned run should be reaped to 'interrupted' on connection re-init"
    )
    assert runs_after[0]["ended_at"] is not None


def test_pipeline_log_step_outside_run_handled_gracefully():
    """Calling start_step / end_step with an unknown run_id must not raise.

    Current contract: silently no-op (the `if not row: return` guard).
    """
    # No start_run for "ghost_run" — these should not crash.
    pipeline_log.start_step("ghost_run", "Enrich")
    pipeline_log.end_step("ghost_run", "Enrich", items=99)
    pipeline_log.end_run("ghost_run", "completed")

    # No run row was ever created.
    assert pipeline_log.get_runs("u_any") == []


def test_pipeline_log_concurrent_runs_same_user_independent():
    """Two concurrent runs for the same user keep separate step lists."""
    pipeline_log.start_run("run_a", "u1", "nb1", "manual")
    pipeline_log.start_run("run_b", "u1", "nb2", "background")

    # Interleave steps across both runs from two threads.
    def worker(run_id: str, names: list[str], items: int) -> None:
        for name in names:
            pipeline_log.start_step(run_id, name)
            pipeline_log.end_step(run_id, name, items=items)

    t1 = threading.Thread(target=worker, args=("run_a", ["Enrich", "Difficulty"], 10))
    t2 = threading.Thread(target=worker, args=("run_b", ["EmbedAndJudge", "ExternalSync"], 20))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    pipeline_log.end_run("run_a", "completed")
    pipeline_log.end_run("run_b", "completed")

    runs = {r["run_id"]: r for r in pipeline_log.get_runs("u1")}
    assert set(runs.keys()) == {"run_a", "run_b"}

    a_steps = {s["name"] for s in runs["run_a"]["steps"]}
    b_steps = {s["name"] for s in runs["run_b"]["steps"]}
    assert a_steps == {"Enrich", "Difficulty"}
    assert b_steps == {"EmbedAndJudge", "ExternalSync"}
    # No cross-pollination.
    assert a_steps.isdisjoint(b_steps)
    # Each run's steps all carry their own items count.
    assert all(s["items"] == 10 for s in runs["run_a"]["steps"])
    assert all(s["items"] == 20 for s in runs["run_b"]["steps"])


def test_pipeline_background_completion_closes_run(monkeypatch):
    """A normal background run must retain its completed terminal status."""
    uid = "normal_pipeline"
    run_id = "normal_run"
    user = {"id": uid, "dir": Path("/tmp/normal_pipeline"), "config": {}}

    async def completed_step(*args, **kwargs):
        return "ok"

    async def get_lock(_uid):
        return asyncio.Lock()

    monkeypatch.setattr(pipeline_runner, "_run_step", completed_step)

    async def driver():
        await pipeline_runner.run_pipeline_background(
            user,
            get_user_lock_fn=get_lock,
            card_store_factory=lambda _dir: None,
            graph_store_factory=lambda _dir, notebook_id="default": None,
            embedding_store_factory=lambda _dir, llm=None, notebook_id="default": None,
            client_factory=lambda _provider: None,
            logger=logging.getLogger("test.pipeline.normal"),
            link_kind_enum=lambda value: value,
            run_id=run_id,
        )

    asyncio.run(driver())

    runs = pipeline_log.get_runs(uid)
    assert runs[0]["status"] == "completed"
    assert runs[0]["ended_at"] is not None
    assert is_pipeline_running(uid) is False


def test_pipeline_background_cancellation_closes_run_and_propagates(monkeypatch):
    """Cancellation must close the run as interrupted, then re-raise."""
    uid = "cancelled_pipeline"
    run_id = "cancelled_run"
    user = {"id": uid, "dir": Path("/tmp/cancelled_pipeline"), "config": {}}
    started = asyncio.Event()

    async def blocked_step(_uid, name, _coro_fn, *, logger, **_kwargs):
        pipeline_log.start_step(run_id, name)
        started.set()
        await asyncio.Event().wait()

    async def get_lock(_uid):
        return asyncio.Lock()

    monkeypatch.setattr(pipeline_runner, "_run_step", blocked_step)

    async def driver():
        task = asyncio.create_task(
            pipeline_runner.run_pipeline_background(
                user,
                get_user_lock_fn=get_lock,
                card_store_factory=lambda _dir: None,
                graph_store_factory=lambda _dir, notebook_id="default": None,
                embedding_store_factory=lambda _dir, llm=None, notebook_id="default": None,
                client_factory=lambda _provider: None,
                logger=logging.getLogger("test.pipeline.cancel"),
                link_kind_enum=lambda value: value,
                run_id=run_id,
            )
        )
        await asyncio.wait_for(started.wait(), timeout=1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(driver())

    runs = pipeline_log.get_runs(uid)
    assert runs[0]["status"] == "interrupted"
    assert runs[0]["ended_at"] is not None
    assert is_pipeline_running(uid) is False


def test_pipeline_background_cancellation_keeps_cancelled_error_when_telemetry_warns(
    monkeypatch, caplog
):
    """A telemetry failure is warning-visible without swallowing cancellation."""
    uid = "cancelled_warning_pipeline"
    run_id = "cancelled_warning_run"
    user = {"id": uid, "dir": Path("/tmp/cancelled_warning_pipeline"), "config": {}}
    started = asyncio.Event()

    async def blocked_step(_uid, name, _coro_fn, *, logger, **_kwargs):
        pipeline_log.start_step(run_id, name)
        started.set()
        await asyncio.Event().wait()

    async def get_lock(_uid):
        return asyncio.Lock()

    def fail_end_run(*args, **kwargs):
        raise OSError("telemetry unavailable")

    monkeypatch.setattr(pipeline_runner, "_run_step", blocked_step)
    monkeypatch.setattr(pipeline_log, "end_run", fail_end_run)
    caplog.set_level(logging.WARNING)

    async def driver():
        task = asyncio.create_task(
            pipeline_runner.run_pipeline_background(
                user,
                get_user_lock_fn=get_lock,
                card_store_factory=lambda _dir: None,
                graph_store_factory=lambda _dir, notebook_id="default": None,
                embedding_store_factory=lambda _dir, llm=None, notebook_id="default": None,
                client_factory=lambda _provider: None,
                logger=logging.getLogger("test.pipeline.cancel.warning"),
                link_kind_enum=lambda value: value,
                run_id=run_id,
            )
        )
        await asyncio.wait_for(started.wait(), timeout=1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(driver())

    assert "Pipeline cancelled" in caplog.text
    assert "Failed to record pipeline telemetry" in caplog.text
    assert is_pipeline_running(uid) is False
