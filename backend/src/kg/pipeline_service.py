from __future__ import annotations

import asyncio
import logging
import threading
import uuid
from collections import defaultdict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from openai import OpenAIError

from .exceptions import KGError
from .retry import async_retry
from .types import UserRecord
from .vocab_graph import CANDIDATE_K, MAX_DEGREE, SIMILARITY_THRESHOLD

# Per-uid refcount of in-flight + queued pipeline runs. Refcount (not bool)
# to defeat the race where the in-flight run's `finally` clears the flag
# AFTER the queued run has set it (the bool-flag impl observed: in-flight
# pop happens after lock release, queued set happens before lock acquire,
# so pop can clobber set). With refcount, both increments are visible and
# the flag only drops when every queued/running task has decremented.
_PIPELINE_RUNNING: dict[str, int] = {}
_PIPELINE_RUNNING_LOCK = threading.Lock()


def is_pipeline_running(user_id: str) -> bool:
    with _PIPELINE_RUNNING_LOCK:
        return _PIPELINE_RUNNING.get(user_id, 0) > 0


def _touch_linked_cards(
    cards: Any, all_links: list[tuple], *, notebook_id: str | None = None,
) -> None:
    """Bump updated_at for all cards involved in newly created links.

    This ensures incremental sync (filtered by updated_at) delivers the
    new links to iOS clients.
    """
    # Links are 5-tuples (from_id, to_id, kind, confidence, reason); index
    # explicitly so a future dataclass/namedtuple migration fails loudly
    # instead of silently shifting fields.
    touched_ids = {cid for link in all_links for cid in (link[0], link[1])}
    cards.batch_touch(touched_ids, notebook_id=notebook_id)


async def _step_enrich(
    uid: str,
    user: UserRecord,
    *,
    card_store_factory: Callable[[Any], Any],
    gemini_client_factory: Callable[[], Any],
    logger: logging.Logger,
    force: bool = False,
    notebook_id: str = "default",
    gemini_model: str = "gemini-2.5-flash-lite",
) -> int:
    logger.info("[%s] Step 1: Enrich (force=%s, notebook=%s)", uid, force, notebook_id)
    cards = card_store_factory(user["dir"])
    if force:
        targets = list(cards.all(include_deleted=False, notebook_id=notebook_id))
    else:
        targets = [card for card in cards.all(notebook_id=notebook_id) if not card.pos or not card.note]

    if not targets:
        logger.info("[%s] All cards already enriched", uid)
        return 0

    from .enrich import enrich_cards_stream
    from .tracked_llm import TrackedLLM

    llm = TrackedLLM(gemini_client_factory(), uid)
    logger.info("[%s] Enriching %d cards...", uid, len(targets))
    updated = 0

    async for msg in enrich_cards_stream(llm, targets, batch_size=20, max_workers=5, model=gemini_model):
        if msg.get("status") == "error":
            logger.warning("[%s] Enrichment batch error: %s", uid, msg.get("detail"))

        if msg.get("results"):
            result_map = {result["word"].lower(): result for result in msg["results"]}
            batch_updates: list[tuple[str, dict]] = []
            for card in targets:
                enrichment = result_map.get(card.content.lower())
                if not enrichment:
                    continue
                kwargs: dict[str, Any] = {}
                if enrichment.get("pos"):
                    if force or not card.pos:
                        from .vocab_shared import _normalize_pos
                        kwargs["pos"] = _normalize_pos(enrichment["pos"])
                if enrichment.get("note"):
                    if force or not card.note:
                        kwargs["note"] = enrichment["note"]
                if enrichment.get("collocations"):
                    kwargs["collocations"] = enrichment["collocations"]
                if enrichment.get("meaning_fix"):
                    kwargs["meaning"] = enrichment["meaning_fix"]
                if kwargs:
                    batch_updates.append((card.id, kwargs))
            if batch_updates:
                updated += cards.batch_update(batch_updates)

    logger.info("[%s] Enriched %d cards", uid, updated)
    return updated


def _sync_embed_loop(
    missing: list[Any],
    embeddings: Any,
    graph: Any,
    uid: str,
    logger: logging.Logger,
) -> int:
    # Batch embed all missing cards in a single API call
    items = [(card.id, card.embed_text()) for card in missing]
    try:
        embeddings.add_batch(items)
    except (OpenAIError, OSError, ValueError) as exc:
        logger.warning("[%s] Batch embedding failed: %s", uid, exc)
        return 0

    # Link candidates for newly embedded cards — batch to avoid per-pair disk writes
    backfilled = 0
    candidate_items: list[tuple[str, str, float]] = []
    for card in missing:
        if not embeddings.has(card.id):
            continue
        try:
            similar = embeddings.find_similar(card.id, k=CANDIDATE_K)
            for other_id, score in similar:
                if score > SIMILARITY_THRESHOLD:
                    candidate_items.append((card.id, other_id, score))
            backfilled += 1
        except (OSError, ValueError) as exc:
            logger.warning("[%s] Link candidate failed for '%s': %s", uid, card.content, exc)

    if candidate_items:
        graph.batch_add_candidates(candidate_items)
    return backfilled


async def _step_embed_and_judge(
    uid: str,
    user: UserRecord,
    *,
    card_store_factory: Callable[[Any], Any],
    graph_store_factory: Callable[..., Any],
    embedding_store_factory: Callable[..., Any],
    gemini_client_factory: Callable[[], Any],
    logger: logging.Logger,
    link_kind_enum: Any,
    notebook_id: str = "default",
    gemini_model: str = "gemini-2.5-flash-lite",
) -> int:
    """Combined embed + judge step. Replaces _step_embed + _step_link."""
    from .judge import Judge
    from .tracked_llm import TrackedLLM

    cards = card_store_factory(user["dir"])
    llm = TrackedLLM(gemini_client_factory(), uid)
    embeddings = embedding_store_factory(user["dir"], llm=llm, notebook_id=notebook_id)
    graph = graph_store_factory(user["dir"], notebook_id=notebook_id)

    # ── Phase 1: Embed missing cards ──
    missing = [
        card for card in cards.all(notebook_id=notebook_id)
        if not embeddings.has(card.id) and not card.is_archived
    ]
    newly_embedded: list[str] = []
    if missing:
        logger.info("[%s] Embedding %d cards", uid, len(missing))
        items = [(card.id, card.embed_text()) for card in missing]
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(None, embeddings.add_batch, items)
            newly_embedded = [card.id for card in missing if embeddings.has(card.id)]
        except (OpenAIError, OSError, ValueError) as exc:
            logger.warning("[%s] Batch embedding failed: %s", uid, exc)

        # Add newly embedded cards to pending_judge
        if newly_embedded:
            graph.add_pending_judge(newly_embedded)
            logger.info("[%s] Embedded %d cards, added to pending judge", uid, len(newly_embedded))

    # ── Phase 2: Judge pending cards ──
    pending = graph.pop_pending_judge()
    if not pending:
        logger.info("[%s] No pending cards to judge", uid)
        return 0

    logger.info("[%s] Judging %d pending cards", uid, len(pending))
    judge = Judge(llm, model=gemini_model, user_id=uid, notebook_id=notebook_id)

    # Pre-fetch pending cards
    cards_cache = cards.get_batch(set(pending))

    all_links: list[tuple[str, str, Any, float, str]] = []

    def _active_degree(cid: str) -> int:
        return sum(1 for lk in graph.get_links_for(cid) if lk.status == "active")

    # ── Phase 2a: Prepare judge tasks ──
    # Pass 1: collect all other_ids from find_similar across all pending cards
    # to do ONE batch fetch instead of per-card get_batch (fixes C2 N+1 query).
    per_card_similar: list[tuple[str, Any, int, list[tuple[str, float]]]] = []
    all_other_ids: set[str] = set()
    for card_id in pending:
        card = cards_cache.get(card_id)
        if not card or card.is_deleted or card.is_archived:
            continue

        current_degree = _active_degree(card_id)
        if current_degree >= MAX_DEGREE:
            continue

        try:
            similar = embeddings.find_similar(card_id, k=CANDIDATE_K)
        except (OSError, ValueError) as exc:
            logger.warning("[%s] find_similar failed for '%s': %s", uid, card_id, exc)
            continue

        candidates: list[tuple[str, float]] = []
        for other_id, score in similar:
            if score <= SIMILARITY_THRESHOLD:
                continue
            if graph.has_link(card_id, other_id):
                continue
            candidates.append((other_id, score))
            all_other_ids.add(other_id)

        if candidates:
            per_card_similar.append((card_id, card, current_degree, candidates))

    # Single batch fetch for ALL other_ids across all pending cards
    others_cache = cards.get_batch(all_other_ids) if all_other_ids else {}

    # Pass 2: filter candidates using the shared cache, build judge_tasks.
    # Include current_degree in the tuple so Phase 2b can initialize
    # from_link_counts without redundant get_links_for calls (fixes W3).
    judge_tasks: list[tuple[str, Any, list, dict, int | None, int]] = []
    for card_id, card, current_degree, candidates in per_card_similar:
        available = MAX_DEGREE - current_degree
        filtered: list[tuple[str, str, str, float]] = []
        for other_id, score in candidates:
            other = others_cache.get(other_id)
            if not other or other.is_deleted or other.is_archived:
                continue
            if _active_degree(other_id) >= MAX_DEGREE:
                continue
            filtered.append((other_id, other.content, other.meaning, score))

        if not filtered:
            continue

        batch_cands = [(oid, w, m) for oid, w, m, _ in filtered]
        sims = {oid: s for oid, _, _, s in filtered}
        max_links = available if len(filtered) >= 5 else None
        judge_tasks.append((card_id, card, batch_cands, sims, max_links, current_degree))

    if not judge_tasks:
        logger.info("[%s] No cards need judging after filtering", uid)
        return 0

    # ── Phase 2b: Parallel judge ──
    executor = ThreadPoolExecutor(max_workers=8)
    loop = asyncio.get_running_loop()

    futures: list[tuple[str, asyncio.Future]] = []
    for card_id, card, batch_cands, sims, max_links, _deg in judge_tasks:
        futures.append((
            card_id,
            loop.run_in_executor(
                executor,
                lambda c=card, bc=batch_cands, s=sims, ml=max_links, fid=card_id: judge.evaluate_batch(
                    c.content, c.meaning, bc,
                    from_id=fid, similarities=s, max_links=ml,
                ),
            ),
        ))

    # Track per-card link count to enforce MAX_DEGREE on both sides.
    # from_link_counts: from-side — seeded from current_degree computed in
    #   Phase 2a to avoid redundant get_links_for calls (W3 fix).
    # to_link_counts: to-side (the other_id being linked TO) — tracks
    #   in-flight links so multiple pending cards don't exceed MAX_DEGREE
    #   on a shared target (C1 fix).
    from_link_counts: dict[str, int] = {
        cid: deg for cid, _, _, _, _, deg in judge_tasks
    }
    to_link_counts: dict[str, int] = {}

    processed = 0
    try:
        for card_id, fut in futures:
            results = await fut
            processed += 1
            for other_id, judgement in results.items():
                if judgement is None:
                    continue
                if from_link_counts[card_id] >= MAX_DEGREE:
                    break  # card_id already at cap
                # Initialize to-side count on first access
                if other_id not in to_link_counts:
                    to_link_counts[other_id] = _active_degree(other_id)
                if to_link_counts[other_id] >= MAX_DEGREE:
                    continue
                all_links.append((
                    card_id, other_id,
                    link_kind_enum(judgement.link),
                    judgement.confidence,
                    judgement.reason,
                ))
                from_link_counts[card_id] += 1
                to_link_counts[other_id] += 1
    except Exception:
        # Requeue unprocessed cards. `processed` is incremented AFTER a
        # successful `await`, so on exception it still points to the card
        # that failed — `futures[processed:]` correctly includes it.
        unprocessed_ids = [cid for cid, _ in futures[processed:]]
        if unprocessed_ids:
            graph.add_pending_judge(unprocessed_ids)
        logger.warning("[%s] Judge interrupted at %d/%d, requeued %d",
                      uid, processed, len(futures), len(unprocessed_ids))
        if all_links:
            # Wrap both calls: a failure here must NOT mask the original
            # judge-loop exception that we're about to re-raise.
            try:
                graph.batch_add_links(all_links)
                _touch_linked_cards(cards, all_links, notebook_id=notebook_id)
            except Exception:
                logger.warning("[%s] Failed to persist partial links/touch", uid)
        # Drain in-flight futures: their exceptions are unobserved otherwise,
        # and asyncio logs "Future exception was never retrieved" at ERROR
        # level on GC. We're already aborting; cancel pending and silently
        # consume any exception already raised.
        for _cid, fut in futures[processed:]:
            if not fut.done():
                fut.cancel()
                continue
            if not fut.cancelled():
                fut.exception()  # mark as retrieved; return value discarded
        raise
    finally:
        executor.shutdown(wait=False)

    # Batch create all links
    created = graph.batch_add_links(all_links) if all_links else []

    # Touch all cards involved in new links so incremental sync picks them up.
    # Without this, cards with new pipeline-created links keep their old
    # updated_at and iOS incremental sync (filtered by updated_at) never
    # sends the new links to the client.
    if created:
        _touch_linked_cards(cards, all_links, notebook_id=notebook_id)

    logger.info("[%s] Created %d links from %d cards", uid, len(created), len(pending))
    return len(created)


async def _step_difficulty(
    uid: str,
    user: UserRecord,
    *,
    card_store_factory: Callable[[Any], Any],
    logger: logging.Logger,
    notebook_id: str = "default",
) -> int:
    logger.info("[%s] Step 3: Difficulty (notebook=%s)", uid, notebook_id)
    from .difficulty import get_zipf

    cards = card_store_factory(user["dir"])
    updates = []
    for card in cards.all(include_deleted=False, notebook_id=notebook_id):
        difficulty = round(get_zipf(card.content), 2)
        if card.difficulty != difficulty:
            updates.append((card.id, {"difficulty": difficulty}))
    scored = cards.batch_update(updates)
    logger.info("[%s] Scored %d cards", uid, scored)
    return scored


# KGError covers QuotaExceededError raised mid-pipeline by TrackedLLM-quota
# guards (or any future service-layer guard). Without it, quota exhaustion
# leaks out of `_run_step` AND `run_pipeline_background`, leaving the run
# stuck "running" in pipeline_log telemetry and bubbling a 429-style error
# to a background task with no HTTP context to catch it.
_STEP_ERRORS = (OpenAIError, OSError, ValueError, RuntimeError, KGError)


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
    from .exceptions import QuotaExceededError

    if run_id:
        try:
            from . import pipeline_log
            pipeline_log.start_step(run_id, name)
        except Exception:
            logger.warning("Failed to record pipeline telemetry", exc_info=True)
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
            try:
                from . import pipeline_log
                items = result if isinstance(result, int) else 0
                pipeline_log.end_step(run_id, name, status="ok", items=items)
            except Exception:
                logger.warning("Failed to record pipeline telemetry", exc_info=True)
        return "ok"
    except QuotaExceededError as exc:
        # Distinct from generic failure: caller short-circuits remaining steps
        # so we don't spam the LLM with calls that will all 429.
        logger.warning("[%s] %s halted on quota exhaustion: %s", uid, name, exc)
        if run_id:
            try:
                from . import pipeline_log
                pipeline_log.end_step(run_id, name, status="quota_exhausted", error=str(exc))
            except Exception:
                logger.warning("Failed to record pipeline telemetry", exc_info=True)
        return "quota_exhausted"
    except _STEP_ERRORS as exc:
        logger.error("[%s] %s failed: %s", uid, name, exc, exc_info=True)
        if run_id:
            try:
                from . import pipeline_log
                pipeline_log.end_step(run_id, name, status="failed", error=str(exc))
            except Exception:
                logger.warning("Failed to record pipeline telemetry", exc_info=True)
        return "failed"


async def run_pipeline_background(
    user: UserRecord,
    *,
    get_user_lock_fn: Callable[[str], Any],
    card_store_factory: Callable[[Any], Any],
    graph_store_factory: Callable[..., Any],
    embedding_store_factory: Callable[..., Any],
    gemini_client_factory: Callable[[], Any],
    logger: logging.Logger,
    link_kind_enum: Any,
    force_enrich: bool = False,
    notebook_id: str = "default",
    gemini_model: str = "gemini-2.5-flash-lite",
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
            try:
                from . import pipeline_log
                pipeline_log.start_run(run_id, uid, notebook_id, trigger)
            except Exception:
                logger.warning("Failed to record pipeline telemetry", exc_info=True)
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
                    gemini_client_factory=gemini_client_factory,
                    logger=logger,
                    force=force_enrich,
                    notebook_id=notebook_id,
                    gemini_model=gemini_model,
                ), logger=logger, retry=True, run_id=run_id)
                if status == "quota_exhausted":
                    pipeline_status = "quota_exhausted"

                if pipeline_status != "quota_exhausted":
                    status = await _run_step(uid, "EmbedAndJudge", lambda: _step_embed_and_judge(
                        uid, user,
                        card_store_factory=card_store_factory,
                        graph_store_factory=graph_store_factory,
                        embedding_store_factory=embedding_store_factory,
                        gemini_client_factory=gemini_client_factory,
                        logger=logger,
                        link_kind_enum=link_kind_enum,
                        notebook_id=notebook_id,
                        gemini_model=gemini_model,
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
                try:
                    from . import pipeline_log
                    pipeline_log.end_run(run_id, pipeline_status)
                except Exception:
                    logger.warning("Failed to record pipeline telemetry", exc_info=True)

            except _STEP_ERRORS as exc:
                # Mirrors `_STEP_ERRORS` so any unexpected leak from a step
                # (including QuotaExceededError, which `_run_step` already
                # catches via the same tuple) gets logged + telemetry-closed
                # instead of crashing the background task.
                logger.error("[%s] Pipeline unexpected error: %s", uid, exc, exc_info=True)
                try:
                    from . import pipeline_log
                    pipeline_log.end_run(run_id, "failed")
                except Exception:
                    logger.warning("Failed to record pipeline telemetry", exc_info=True)
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
                try:
                    from . import pipeline_log
                    pipeline_log.end_run(run_id, "failed")
                except Exception:
                    logger.warning("Failed to record pipeline telemetry", exc_info=True)
    finally:
        # Pair with the increment above. The outer try/finally guards
        # against cancellation while awaiting `lock.__aenter__()` — the
        # decrement still runs and we don't leak the refcount.
        with _PIPELINE_RUNNING_LOCK:
            _PIPELINE_RUNNING[uid] = _PIPELINE_RUNNING.get(uid, 0) - 1
            if _PIPELINE_RUNNING[uid] <= 0:
                _PIPELINE_RUNNING.pop(uid, None)
