"""Tests for pipeline step execution helper."""

import asyncio
import logging
import sqlite3
from pathlib import Path

import pytest
from sqlalchemy import exc as sa_exc

from kg import pipeline_log
from kg.exceptions import QuotaExceededError
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


# --- #2089: step isolation must cover DB errors and cancellation -------------

_SECRET_PARAM = "SECRET-CARD-TEXT-do-not-leak"
_SQL = "UPDATE cards SET front = ? WHERE id = ?"


def _sqlalchemy_locked() -> sa_exc.OperationalError:
    return sa_exc.OperationalError(_SQL, {"front": _SECRET_PARAM}, sqlite3.OperationalError("database is locked"))


def _sqlite_locked() -> sqlite3.OperationalError:
    return sqlite3.OperationalError("database is locked")


async def _run_full_pipeline(monkeypatch, *, enrich, uid: str, run_id: str) -> list[str]:
    """Drive run_pipeline_background with stubbed steps; return the step call order."""
    import kg.pipeline_service.runner as runner

    calls: list[str] = []

    async def fake_enrich(*_args, **_kwargs):
        calls.append("Enrich")
        return await enrich()

    async def fake_embed_and_judge(*_args, **_kwargs):
        calls.append("EmbedAndJudge")
        return 0

    async def fake_difficulty(*_args, **_kwargs):
        calls.append("Difficulty")
        return 0

    monkeypatch.setattr(runner, "_step_enrich", fake_enrich)
    monkeypatch.setattr(runner, "_step_embed_and_judge", fake_embed_and_judge)
    monkeypatch.setattr(runner, "_step_difficulty", fake_difficulty)

    lock = asyncio.Lock()

    async def get_lock(_uid):
        return lock

    pipeline_log.start_run(run_id, uid, "default", "background")
    await run_pipeline_background(
        {"id": uid, "dir": Path(f"/tmp/{uid}"), "config": {}},
        get_user_lock_fn=get_lock,
        card_store_factory=lambda _dir: None,
        graph_store_factory=lambda _dir, notebook_id="default": None,
        embedding_store_factory=lambda _dir, llm=None, notebook_id="default": None,
        client_factory=lambda _provider: None,
        logger=logging.getLogger("test.pipeline.isolation"),
        link_kind_enum=lambda value: value,
        run_id=run_id,
        telemetry_started=True,
    )
    return calls


async def _run_single_step(uid: str, step_fn) -> tuple[str, dict]:
    """Run one step under telemetry; return (_run_step result, stored step row)."""
    run_id = f"{uid}_run"
    pipeline_log.start_run(run_id, uid, "default", "background")
    result = await _run_step(uid, "Enrich", step_fn, logger=logging.getLogger("test"), run_id=run_id)
    return result, pipeline_log.get_runs(uid)[0]["steps"][0]


@pytest.mark.parametrize("make_exc", [_sqlalchemy_locked, _sqlite_locked], ids=["sqlalchemy", "sqlite3"])
@pytest.mark.asyncio
async def test_db_error_in_enrich_does_not_skip_later_steps(monkeypatch, make_exc):
    async def enrich():
        raise make_exc()

    calls = await _run_full_pipeline(monkeypatch, enrich=enrich, uid="iso_db", run_id="iso_db_run")

    assert calls == ["Enrich", "EmbedAndJudge", "Difficulty"]
    run = pipeline_log.get_runs("iso_db")[0]
    assert run["status"] == "completed"
    steps = {s["name"]: s for s in run["steps"]}
    assert {name: s["status"] for name, s in steps.items()} == {
        "Enrich": "failed",
        "EmbedAndJudge": "ok",
        "Difficulty": "ok",
    }
    assert steps["Enrich"]["ended_at"] is not None


@pytest.mark.parametrize("make_exc", [_sqlalchemy_locked, _sqlite_locked], ids=["sqlalchemy", "sqlite3"])
@pytest.mark.asyncio
async def test_db_error_closes_step_as_failed_with_ended_at(make_exc):
    async def step():
        raise make_exc()

    result, row = await _run_single_step("iso_close", step)

    assert result == "failed"
    assert row["status"] == "failed"
    assert row["ended_at"] is not None
    assert "database is locked" in row["error"]


@pytest.mark.asyncio
async def test_sqlalchemy_statement_error_text_drops_sql_and_params():
    exc = _sqlalchemy_locked()
    # Positive control: the raw message really carries the SQL and card text.
    assert _SECRET_PARAM in str(exc)
    assert _SQL in str(exc)

    async def step():
        raise exc

    _, row = await _run_single_step("iso_sanitize", step)

    assert row["error"] == "OperationalError: database is locked"


@pytest.mark.asyncio
async def test_non_statement_sqlalchemy_error_keeps_its_message():
    async def step():
        raise sa_exc.TimeoutError("QueuePool limit of size 5 overflow 10 reached")

    result, row = await _run_single_step("iso_pool", step)

    assert result == "failed"
    assert "QueuePool limit of size 5 overflow 10 reached" in row["error"]


@pytest.mark.asyncio
async def test_step_error_text_is_bounded():
    async def step():
        raise ValueError("x" * 5000)

    _, row = await _run_single_step("iso_trunc", step)

    assert row["status"] == "failed"
    assert row["error"] == "x" * 500


@pytest.mark.asyncio
async def test_legacy_error_text_unchanged():
    async def step():
        raise RuntimeError("plain old failure")

    _, row = await _run_single_step("iso_legacy", step)

    assert row["error"] == "plain old failure"


@pytest.mark.asyncio
async def test_quota_exhausted_still_short_circuits(monkeypatch):
    async def enrich():
        raise QuotaExceededError(3600)

    calls = await _run_full_pipeline(monkeypatch, enrich=enrich, uid="iso_quota", run_id="iso_quota_run")

    assert calls == ["Enrich"]
    run = pipeline_log.get_runs("iso_quota")[0]
    assert run["status"] == "quota_exhausted"
    assert [s["status"] for s in run["steps"]] == ["quota_exhausted"]


@pytest.mark.asyncio
async def test_cancelled_step_is_closed_as_interrupted_and_reraises():
    async def step():
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await _run_single_step("iso_cancel", step)

    row = pipeline_log.get_runs("iso_cancel")[0]["steps"][0]
    assert row["status"] == "interrupted"
    assert row["error"] == "cancelled"
    assert row["ended_at"] is not None


@pytest.mark.asyncio
async def test_cancellation_mid_pipeline_ends_run_interrupted(monkeypatch):
    async def enrich():
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await _run_full_pipeline(monkeypatch, enrich=enrich, uid="iso_cp", run_id="iso_cp_run")

    run = pipeline_log.get_runs("iso_cp")[0]
    assert run["status"] == "interrupted"
    assert [(s["name"], s["status"]) for s in run["steps"]] == [("Enrich", "interrupted")]
    assert run["steps"][0]["ended_at"] is not None
