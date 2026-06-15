from __future__ import annotations

import logging
import uuid
from typing import Any, Protocol

from openai import OpenAIError

from ..exceptions import KGError
from ..retry import async_retry
from ..types import UserRecord
from .runstate import _PIPELINE_RUNNING, _PIPELINE_RUNNING_LOCK
from .steps import _step_difficulty, _step_embed_and_judge, _step_enrich

# KGError covers QuotaExceededError raised mid-pipeline by TrackedLLM-quota
# guards (or any future service-layer guard). Without it, quota exhaustion
# leaks out of `_run_step` AND `run_pipeline_background`, leaving the run
# stuck "running" in pipeline_log telemetry and bubbling a 429-style error
# to a background task with no HTTP context to catch it.
_STEP_ERRORS = (OpenAIError, OSError, ValueError, RuntimeError, KGError)


class AsyncLockFactory(Protocol):
    async def __call__(self, user_id: str) -> Any:
        ...


class CardStoreFactory(Protocol):
    def __call__(self, user_dir: Any) -> Any:
        ...


class GraphStoreFactory(Protocol):
    def __call__(self, user_dir: Any, notebook_id: str = "default") -> Any:
        ...


class EmbeddingStoreFactory(Protocol):
    def __call__(self, user_dir: Any, llm: Any, notebook_id: str = "default") -> Any:
        ...


class ClientFactory(Protocol):
    def __call__(self, provider: Any) -> Any:
        ...


def _telemetry(logger: logging.Logger, method: str, *args: Any, **kwargs: Any) -> None:
    """Best-effort pipeline_log telemetry call.

    A telemetry write must never break (or abort) the actual pipeline run, so any
    failure (import, missing DB, SQLite error) is swallowed with a warning.
    """
    try:
        from .. import pipeline_log
        getattr(pipeline_log, method)(*args, **kwargs)
    except Exception:
        logger.warning("Failed to record pipeline telemetry", exc_info=True)


async def _run_step(
    uid: str,
    name: str,
    coro_fn,
    *,
    logger: logging.Logger,
    retry: bool = False,
    retryable_exceptions: tuple = (OpenAIError, OSError),
    run_id: str | None = None,
) -> str:
    """Execute a pipeline step with uniform error handling.

    Returns the step's terminal status: "ok", "failed", or "quota_exhausted".
    Quota exhaustion is a distinct outcome — caller (run_pipeline_background)
    short-circuits subsequent steps so the user's day-budget isn't burned on
    no-op work and the pipeline_log run reflects the actual halt reason.
    """
    from ..exceptions import QuotaExceededError

    if run_id:
        _telemetry(logger, "start_step", run_id, name)
    try:
        if retry:
            result = await async_retry(
                coro_fn, max_attempts=2,
                retryable_exceptions=retryable_exceptions,
                step_name=name, uid=uid,
            )
        else:
            result = await coro_fn()
        if run_id:
            items = result if isinstance(result, int) else 0
            _telemetry(logger, "end_step", run_id, name, status="ok", items=items)
        return "ok"
    except QuotaExceededError as exc:
        # Distinct from generic failure: caller short-circuits remaining steps
        # so we don't spam the LLM with calls that will all 429.
        logger.warning("[%s] %s halted on quota exhaustion: %s", uid, name, exc)
        if run_id:
            _telemetry(logger, "end_step", run_id, name, status="quota_exhausted", error=str(exc))
        return "quota_exhausted"
    except _STEP_ERRORS as exc:
        logger.error("[%s] %s failed: %s", uid, name, exc, exc_info=True)
        if run_id:
            _telemetry(logger, "end_step", run_id, name, status="failed", error=str(exc))
        return "failed"


async def run_pipeline_background(
    user: UserRecord,
    *,
    get_user_lock_fn: AsyncLockFactory,
    card_store_factory: CardStoreFactory,
    graph_store_factory: GraphStoreFactory,
    embedding_store_factory: EmbeddingStoreFactory,
    client_factory: ClientFactory,
    logger: logging.Logger,
    link_kind_enum: Any,
    force_enrich: bool = False,
    notebook_id: str = "default",
) -> None:
    uid = user["id"]
    lock = await get_user_lock_fn(uid)
    # Previously: `if lock.locked(): return` silently dropped concurrent triggers,
    # causing cards in a second notebook to sit forever in pending_judge_<nb>.json
    # when iOS's post-2026-04-11 `triggerPipelinesIsolated` fires two triggers for
    # different notebooks back-to-back (new notebook + migrated orphan into default).
    # Now: queue naturally via `async with lock`. Duplicate triggers for the same
    # notebook degrade to cheap no-ops via each step's early-exit path.
    if lock.locked():
        logger.info("[%s] Pipeline lock held, queueing notebook=%s.", uid, notebook_id)
    # Increment refcount BEFORE awaiting the lock so a queued run keeps the
    # `X-Pipeline-Pending` header sticky across the in-flight run's `finally`
    # decrement. Bool flag would race: in-flight pop happens after lock release
    # but queued set happens before lock acquire, so pop can clobber set.
    with _PIPELINE_RUNNING_LOCK:
        _PIPELINE_RUNNING[uid] = _PIPELINE_RUNNING.get(uid, 0) + 1
    try:
        async with lock:
            run_id = uuid.uuid4().hex[:12]
            trigger = "manual" if force_enrich else "background"
            _telemetry(logger, "start_run", run_id, uid, notebook_id, trigger)
            try:
                logger.info("[%s] Pipeline started.", uid)

                # Step isolation: each step catches its own errors so one
                # failure never aborts subsequent steps. The union covers
                # LLM calls (OpenAIError), file/DB I/O (OSError), and data
                # issues (ValueError, RuntimeError).

                pipeline_status = "completed"

                status = await _run_step(uid, "Enrich", lambda: _step_enrich(
                    uid, user,
                    card_store_factory=card_store_factory,
                    client_factory=client_factory,
                    logger=logger,
                    force=force_enrich,
                    notebook_id=notebook_id,
                ), logger=logger, retry=True, run_id=run_id)
                if status == "quota_exhausted":
                    pipeline_status = "quota_exhausted"

                if pipeline_status != "quota_exhausted":
                    status = await _run_step(uid, "EmbedAndJudge", lambda: _step_embed_and_judge(
                        uid, user,
                        card_store_factory=card_store_factory,
                        graph_store_factory=graph_store_factory,
                        embedding_store_factory=embedding_store_factory,
                        client_factory=client_factory,
                        logger=logger,
                        link_kind_enum=link_kind_enum,
                        notebook_id=notebook_id,
                    ), logger=logger, retry=True, run_id=run_id)
                    if status == "quota_exhausted":
                        pipeline_status = "quota_exhausted"

                if pipeline_status != "quota_exhausted":
                    # Difficulty is purely local (zipf lookup), no LLM cost,
                    # so we always run it unless an earlier step quota-halted
                    # (in which case the user is in a soft-degraded state and
                    # we want a clean halt boundary).
                    await _run_step(uid, "Difficulty", lambda: _step_difficulty(
                        uid, user,
                        card_store_factory=card_store_factory,
                        logger=logger,
                        notebook_id=notebook_id,
                    ), logger=logger, run_id=run_id)

                if pipeline_status == "quota_exhausted":
                    logger.warning("[%s] Pipeline halted: quota exhausted.", uid)
                else:
                    logger.info("[%s] Pipeline completed.", uid)
                _telemetry(logger, "end_run", run_id, pipeline_status)

            except _STEP_ERRORS as exc:
                # Mirrors `_STEP_ERRORS` so any unexpected leak from a step
                # (including QuotaExceededError, which `_run_step` already
                # catches via the same tuple) gets logged + telemetry-closed
                # instead of crashing the background task.
                logger.error("[%s] Pipeline unexpected error: %s", uid, exc, exc_info=True)
                _telemetry(logger, "end_run", run_id, "failed")
            except Exception as exc:
                # Defensive catch-all: when a queued run reaches the body
                # AFTER its owning user/notebook was deleted, store factories
                # can raise anything (KeyError from a missing user dict,
                # custom AppErrors, etc.). The lock-queue rewrite means
                # such queued runs always reach this code; we must absorb
                # the failure here so the exception doesn't escape into
                # caller / asyncio.gather and so refcount unwinds cleanly.
                logger.error(
                    "[%s] Pipeline aborted due to non-recoverable error "
                    "(user/notebook may have been deleted mid-queue): %s",
                    uid, exc, exc_info=True,
                )
                _telemetry(logger, "end_run", run_id, "failed")
    finally:
        # Pair with the increment above. The outer try/finally guards
        # against cancellation while awaiting `lock.__aenter__()` — the
        # decrement still runs and we don't leak the refcount.
        with _PIPELINE_RUNNING_LOCK:
            _PIPELINE_RUNNING[uid] = _PIPELINE_RUNNING.get(uid, 0) - 1
            if _PIPELINE_RUNNING[uid] <= 0:
                _PIPELINE_RUNNING.pop(uid, None)
