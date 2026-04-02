from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from openai import OpenAIError

from .retry import async_retry
from .types import UserRecord
from .user_store import resolve_mochi_api_key_from_config
from .vocab_graph import CANDIDATE_K, SIMILARITY_THRESHOLD

_PIPELINE_RUNNING: dict[str, bool] = {}
_PIPELINE_RUNNING_LOCK = threading.Lock()


def is_pipeline_running(user_id: str) -> bool:
    with _PIPELINE_RUNNING_LOCK:
        return _PIPELINE_RUNNING.get(user_id, False)


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
) -> None:
    logger.info("[%s] Step 1: Enrich (force=%s, notebook=%s)", uid, force, notebook_id)
    cards = card_store_factory(user["dir"])
    if force:
        targets = list(cards.all(include_deleted=False, notebook_id=notebook_id))
    else:
        targets = [card for card in cards.all(notebook_id=notebook_id) if not card.pos or not card.note]

    if not targets:
        logger.info("[%s] All cards already enriched", uid)
        return

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


async def _step_embed(
    uid: str,
    user: UserRecord,
    *,
    card_store_factory: Callable[[Any], Any],
    graph_store_factory: Callable[..., Any],
    embedding_store_factory: Callable[..., Any],
    gemini_client_factory: Callable[[], Any],
    logger: logging.Logger,
    notebook_id: str = "default",
) -> None:
    cards = card_store_factory(user["dir"])
    from .tracked_llm import TrackedLLM
    llm = TrackedLLM(gemini_client_factory(), uid)
    embeddings = embedding_store_factory(user["dir"], llm=llm, notebook_id=notebook_id)
    graph = graph_store_factory(user["dir"], notebook_id=notebook_id)
    missing = [card for card in cards.all(notebook_id=notebook_id) if not embeddings.has(card.id) and not card.is_archived]

    if not missing:
        return

    logger.info("[%s] Backfilling embeddings for %d cards", uid, len(missing))
    loop = asyncio.get_running_loop()
    backfilled = await loop.run_in_executor(
        None, _sync_embed_loop, missing, embeddings, graph, uid, logger
    )
    logger.info("[%s] Backfilled %d embeddings", uid, backfilled)


async def _step_link(
    uid: str,
    user: UserRecord,
    *,
    card_store_factory: Callable[[Any], Any],
    graph_store_factory: Callable[..., Any],
    gemini_client_factory: Callable[[], Any],
    logger: logging.Logger,
    link_kind_enum: Any,
    notebook_id: str = "default",
    gemini_model: str = "gemini-2.5-flash-lite",
) -> None:
    logger.info("[%s] Step 2: Link (notebook=%s)", uid, notebook_id)
    graph = graph_store_factory(user["dir"], notebook_id=notebook_id)
    candidates = graph.pop_candidates()

    if not candidates:
        logger.info("[%s] No pending candidates", uid)
        return

    from .judge import Judge
    from .tracked_llm import TrackedLLM

    llm = TrackedLLM(gemini_client_factory(), uid)
    judge = Judge(llm, model=gemini_model)
    cards = card_store_factory(user["dir"])
    pending_links: list[tuple[str, str, Any, float, str]] = []
    index = 0

    # Pre-fetch all candidate cards in one batch
    _all_candidate_ids = set()
    for c in candidates:
        _all_candidate_ids.add(c.from_id)
        _all_candidate_ids.add(c.to_id)
    cards_cache = cards.get_batch(_all_candidate_ids) if _all_candidate_ids else {}

    # Filter valid candidates first, preserving original index for error requeue
    valid_pairs: list[tuple[int, Any, Any, Any]] = []
    for idx, candidate in enumerate(candidates):
        card_a = cards_cache.get(candidate.from_id)
        card_b = cards_cache.get(candidate.to_id)
        if not card_a or not card_b or card_a.is_deleted or card_b.is_deleted or card_a.is_archived or card_b.is_archived:
            continue
        valid_pairs.append((idx, candidate, card_a, card_b))

    executor = ThreadPoolExecutor(max_workers=8)
    loop = asyncio.get_running_loop()
    # Submit all judge tasks concurrently up front
    futures: list[tuple[int, Any, asyncio.Future]] = [
        (idx, candidate, loop.run_in_executor(
            executor,
            lambda a=card_a, b=card_b: judge.evaluate(
                a.content, a.meaning, b.content, b.meaning,
            ),
        ))
        for idx, candidate, card_a, card_b in valid_pairs
    ]
    # Track how many futures have been awaited for requeue on error
    awaited_count = 0
    try:
        for idx, candidate, fut in futures:
            index = idx
            result = await fut
            awaited_count += 1
            if result:
                pending_links.append((
                    candidate.from_id,
                    candidate.to_id,
                    link_kind_enum(result.link),
                    result.confidence,
                    result.reason,
                ))
    except (OpenAIError, OSError, ValueError, RuntimeError):
        # Flush accumulated links before requeuing un-awaited candidates
        if pending_links:
            graph.batch_add_links(pending_links)
        # Requeue candidates whose futures we haven't yet awaited
        not_yet_awaited = [c for _, c, _ in futures[awaited_count:]]
        if not_yet_awaited:
            graph.requeue_candidates(not_yet_awaited)
        raise
    finally:
        executor.shutdown(wait=False)

    # Single disk write for all judged links
    created = graph.batch_add_links(pending_links) if pending_links else []
    logger.info("[%s] Created %d links", uid, len(created))


async def _step_difficulty(
    uid: str,
    user: UserRecord,
    *,
    card_store_factory: Callable[[Any], Any],
    logger: logging.Logger,
    notebook_id: str = "default",
) -> None:
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


async def _step_external_sync(
    uid: str,
    user: UserRecord,
    *,
    card_store_factory: Callable[[Any], Any],
    graph_store_factory: Callable[..., Any],
    logger: logging.Logger,
    jwt_secret: str = "",
    notebook_id: str = "default",
) -> None:
    logger.info("[%s] Step 4: Optional External Sync (notebook=%s)", uid, notebook_id)
    mochi_key = resolve_mochi_api_key_from_config(user["config"], jwt_secret)
    if not mochi_key:
        logger.info("[%s] Optional Mochi integration not configured, skipping external sync", uid)
        return

    from .mochi import MochiClient, MochiSync
    from .renderer import RenderIntent

    cards = card_store_factory(user["dir"])
    graph = graph_store_factory(user["dir"], notebook_id=notebook_id)
    mochi_client = MochiClient(mochi_key)
    syncer = MochiSync(
        mochi_client,
        cards,
        graph,
        map_path=user["dir"] / "mochi_map.json",
    )

    loop = asyncio.get_running_loop()
    try:
        stats = await loop.run_in_executor(None, lambda: syncer.sync(RenderIntent.FULL, dry_run=False))
    finally:
        mochi_client.close()
    logger.info(
        "[%s] Optional external sync (Mochi): %d created, %d updated, %d deleted",
        uid, stats["created"], stats["updated"], stats["deleted"],
    )


_STEP_ERRORS = (OpenAIError, OSError, ValueError, RuntimeError)


async def _run_step(
    uid: str,
    name: str,
    coro_fn,
    *,
    logger: logging.Logger,
    retry: bool = False,
    retryable_exceptions: tuple = (OpenAIError, OSError),
) -> None:
    """Execute a pipeline step with uniform error handling."""
    try:
        if retry:
            await async_retry(
                coro_fn, max_attempts=2,
                retryable_exceptions=retryable_exceptions,
                step_name=name, uid=uid,
            )
        else:
            await coro_fn()
    except _STEP_ERRORS as exc:
        logger.error("[%s] %s failed: %s", uid, name, exc, exc_info=True)


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
    jwt_secret: str = "",
    force_enrich: bool = False,
    notebook_id: str = "default",
    gemini_model: str = "gemini-2.5-flash-lite",
) -> None:
    uid = user["id"]
    lock = await get_user_lock_fn(uid)
    if lock.locked():
        logger.info("[%s] Pipeline already running, skipping.", uid)
        return

    async with lock:
        with _PIPELINE_RUNNING_LOCK:
            _PIPELINE_RUNNING[uid] = True
        try:
            logger.info("[%s] Pipeline started.", uid)

            # Step isolation: each step catches its own errors so one failure
            # never aborts subsequent steps.  The union covers LLM calls
            # (OpenAIError), file/DB I/O (OSError), and data issues (ValueError,
            # RuntimeError).

            await _run_step(uid, "Enrich", lambda: _step_enrich(
                uid, user,
                card_store_factory=card_store_factory,
                gemini_client_factory=gemini_client_factory,
                logger=logger,
                force=force_enrich,
                notebook_id=notebook_id,
                gemini_model=gemini_model,
            ), logger=logger, retry=True)

            await _run_step(uid, "Embed", lambda: _step_embed(
                uid, user,
                card_store_factory=card_store_factory,
                graph_store_factory=graph_store_factory,
                embedding_store_factory=embedding_store_factory,
                gemini_client_factory=gemini_client_factory,
                logger=logger,
                notebook_id=notebook_id,
            ), logger=logger, retry=True)

            await _run_step(uid, "Link", lambda: _step_link(
                uid, user,
                card_store_factory=card_store_factory,
                graph_store_factory=graph_store_factory,
                gemini_client_factory=gemini_client_factory,
                logger=logger,
                link_kind_enum=link_kind_enum,
                notebook_id=notebook_id,
                gemini_model=gemini_model,
            ), logger=logger, retry=True)

            await _run_step(uid, "Difficulty", lambda: _step_difficulty(
                uid, user,
                card_store_factory=card_store_factory,
                logger=logger,
                notebook_id=notebook_id,
            ), logger=logger)

            # Core steps done — clear pending flag so iOS clients stop polling.
            # The asyncio lock remains held to prevent concurrent pipeline runs.
            with _PIPELINE_RUNNING_LOCK:
                _PIPELINE_RUNNING[uid] = False
            logger.info("[%s] Core pipeline done, clients unblocked.", uid)

            await _run_step(uid, "ExternalSync", lambda: _step_external_sync(
                uid, user,
                card_store_factory=card_store_factory,
                graph_store_factory=graph_store_factory,
                logger=logger,
                jwt_secret=jwt_secret,
                notebook_id=notebook_id,
            ), logger=logger)

            logger.info("[%s] Pipeline completed.", uid)

        except (OpenAIError, OSError, ValueError, RuntimeError) as exc:
            logger.error("[%s] Pipeline unexpected error: %s", uid, exc, exc_info=True)
        finally:
            with _PIPELINE_RUNNING_LOCK:
                _PIPELINE_RUNNING.pop(uid, None)
