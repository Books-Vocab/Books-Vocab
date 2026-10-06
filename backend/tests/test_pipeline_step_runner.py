"""Tests for pipeline step execution helper."""

import asyncio
import logging
from pathlib import Path

import pytest

from kg import pipeline_log
from kg.pipeline_service import _run_step, is_pipeline_running, run_pipeline_background

pytestmark = pytest.mark.usefixtures("isolate_pipeline_db")


@pytest.mark.asyncio
async def test_run_step_success():
    called = []

    async def step():
        called.append(True)

    await _run_step("test_user", "TestStep", step, logger=logging.getLogger("test"))
    assert called == [True]


@pytest.mark.asyncio
async def test_run_step_catches_errors():
    async def failing_step():
        raise ValueError("boom")

    # Should not raise
    await _run_step("test_user", "FailStep", failing_step, logger=logging.getLogger("test"))


@pytest.mark.asyncio
async def test_background_cancellation_while_waiting_for_lock_closes_started_run():
    """An externally-started run must close telemetry if cancelled in the queue."""
    uid = "queued_cancelled_user"
    run_id = "queued_cancelled_run"
    user = {"id": uid, "dir": Path("/tmp/queued_cancelled_user"), "config": {}}
    lock = asyncio.Lock()
    await lock.acquire()
    pipeline_log.start_run(run_id, uid, "default", "background")

    async def get_user_lock(_uid):
        return lock

    task = asyncio.create_task(
        run_pipeline_background(
            user,
            get_user_lock_fn=get_user_lock,
            card_store_factory=lambda _dir: None,
            graph_store_factory=lambda _dir, notebook_id="default": None,
            embedding_store_factory=lambda _dir, llm=None, notebook_id="default": None,
            client_factory=lambda _provider: None,
            logger=logging.getLogger("test.pipeline.queued-cancel"),
            link_kind_enum=lambda value: value,
            run_id=run_id,
            telemetry_started=True,
        )
    )
    await asyncio.sleep(0)
    assert not task.done()

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    run = pipeline_log.get_runs(uid)[0]
    assert run["status"] == "interrupted"
    assert run["ended_at"] is not None
    assert is_pipeline_running(uid) is False
