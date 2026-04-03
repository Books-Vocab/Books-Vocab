from __future__ import annotations

import asyncio
import logging
import threading
from collections import defaultdict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from openai import OpenAIError

from .retry import async_retry
from .types import UserRecord
from .user_store import resolve_mochi_api_key_from_config
from .vocab_graph import CANDIDATE_K, MAX_DEGREE, SIMILARITY_THRESHOLD

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
    judge = Judge(llm, model=gemini_model, user_id=uid, notebook_id=notebook_id)
    cards = card_store_factory(user["dir"])
    pending_links: list[tuple[str, str, Any, float, str]] = []

    # Pre-fetch all candidate cards in one batch
    _all_candidate_ids = set()
    for c in candidates:
        _all_candidate_ids.add(c.from_id)
        _all_candidate_ids.add(c.to_id)
    cards_cache = cards.get_batch(_all_candidate_ids) if _all_candidate_ids else {}

    # Group candidates by from_id (target word) for batch judge
    groups: dict[str, list[tuple[int, Any, Any]]] = defaultdict(list)
    for idx, candidate in enumerate(candidates):
        card_a = cards_cache.get(candidate.from_id)
        card_b = cards_cache.get(candidate.to_id)
        if not card_a or not card_b or card_a.is_deleted or card_b.is_deleted or card_a.is_archived or card_b.is_archived:
            continue
        groups[candidate.from_id].append((idx, candidate, card_b))

    # Batch judge: one LLM call per target word, parallel across targets
    executor = ThreadPoolExecutor(max_workers=8)
    loop = asyncio.get_running_loop()

    group_items = list(groups.items())
    futures: list[tuple[str, list[tuple[int, Any, Any]], asyncio.Future]] = []
    for from_id, group in group_items:
        card_a = cards_cache.get(from_id)
        if not card_a:
            continue
        batch_candidates = [
            (cand.to_id, card_b.content, card_b.meaning)
            for _, cand, card_b in group
        ]
        sims = {cand.to_id: getattr(cand, "similarity", 0.0) for _, cand, _ in group}
        futures.append((
            from_id,
            group,
            loop.run_in_executor(
                executor,
                lambda a=card_a, bc=batch_candidates, fid=from_id, s=sims: judge.evaluate_batch(
                    a.content, a.meaning, bc, from_id=fid, similarities=s,
                ),
            ),
        ))

    processed_groups = 0
    try:
        for from_id, group, fut in futures:
            batch_results = await fut
            processed_groups += 1
            for _, candidate, card_b in group:
                result = batch_results.get(candidate.to_id)
                if result:
                    pending_links.append((
                        candidate.from_id,
                        candidate.to_id,
                        link_kind_enum(result.link),
                        result.confidence,
                        result.reason,
                    ))
    except (OpenAIError, OSError, ValueError, RuntimeError):
        if pending_links:
            graph.batch_add_links(pending_links)
        # Requeue candidates from unprocessed groups
        for _, group, _ in futures[processed_groups:]:
            unprocessed = [cand for _, cand, _ in group]
            graph.requeue_candidates(unprocessed)
        raise
    finally:
        executor.shutdown(wait=False)

    # Single disk write for all judged links
    created = graph.batch_add_links(pending_links) if pending_links else []
    logger.info("[%s] Created %d links from %d groups", uid, len(created), len(group_items))


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
) -> None:
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
        return

    logger.info("[%s] Judging %d pending cards", uid, len(pending))
    judge = Judge(llm, model=gemini_model, user_id=uid, notebook_id=notebook_id)

    # Pre-fetch pending cards
    cards_cache = cards.get_batch(set(pending))

    all_links: list[tuple[str, str, Any, float, str]] = []

    def _active_degree(cid: str) -> int:
        return sum(1 for lk in graph.get_links_for(cid) if lk.status == "active")

    # ── Phase 2a: Prepare judge tasks ──
    judge_tasks: list[tuple[str, Any, list, dict, int | None]] = []
    for card_id in pending:
        card = cards_cache.get(card_id)
        if not card or card.is_deleted or card.is_archived:
            continue

        current_degree = _active_degree(card_id)
        if current_degree >= MAX_DEGREE:
            continue
        available = MAX_DEGREE - current_degree

        try:
            similar = embeddings.find_similar(card_id, k=CANDIDATE_K)
        except (OSError, ValueError) as exc:
            logger.warning("[%s] find_similar failed for '%s': %s", uid, card_id, exc)
            continue

        other_ids_needed: set[str] = set()
        for other_id, score in similar:
            if score <= SIMILARITY_THRESHOLD:
                continue
            if graph.has_link(card_id, other_id):
                continue
            other_ids_needed.add(other_id)

        if not other_ids_needed:
            continue

        others = cards.get_batch(other_ids_needed)
        filtered: list[tuple[str, str, str, float]] = []
        for other_id, score in similar:
            if other_id not in other_ids_needed:
                continue
            other = others.get(other_id)
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
        judge_tasks.append((card_id, card, batch_cands, sims, max_links))

    if not judge_tasks:
        logger.info("[%s] No cards need judging after filtering", uid)
        return

    # ── Phase 2b: Parallel judge ──
    executor = ThreadPoolExecutor(max_workers=8)
    loop = asyncio.get_running_loop()

    futures: list[tuple[str, asyncio.Future]] = []
    for card_id, card, batch_cands, sims, max_links in judge_tasks:
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

    # Track per-card link count to enforce MAX_DEGREE on the from-side
    from_link_counts: dict[str, int] = {}

    processed = 0
    try:
        for card_id, fut in futures:
            results = await fut
            processed += 1
            # Initialize from-side count if not tracked yet
            if card_id not in from_link_counts:
                from_link_counts[card_id] = _active_degree(card_id)
            for other_id, judgement in results.items():
                if judgement is None:
                    continue
                if from_link_counts[card_id] >= MAX_DEGREE:
                    break  # card_id already at cap
                if _active_degree(other_id) >= MAX_DEGREE:
                    continue
                all_links.append((
                    card_id, other_id,
                    link_kind_enum(judgement.link),
                    judgement.confidence,
                    judgement.reason,
                ))
                from_link_counts[card_id] += 1
    except Exception:
        # Requeue unprocessed cards
        unprocessed_ids = [cid for cid, _ in futures[processed:]]
        if unprocessed_ids:
            graph.add_pending_judge(unprocessed_ids)
        logger.warning("[%s] Judge interrupted at %d/%d, requeued %d",
                      uid, processed, len(futures), len(unprocessed_ids))
        if all_links:
            graph.batch_add_links(all_links)
        raise
    finally:
        executor.shutdown(wait=False)

    # Batch create all links
    created = graph.batch_add_links(all_links) if all_links else []
    logger.info("[%s] Created %d links from %d cards", uid, len(created), len(pending))


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

            await _run_step(uid, "EmbedAndJudge", lambda: _step_embed_and_judge(
                uid, user,
                card_store_factory=card_store_factory,
                graph_store_factory=graph_store_factory,
                embedding_store_factory=embedding_store_factory,
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
