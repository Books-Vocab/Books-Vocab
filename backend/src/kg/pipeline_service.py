from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

from openai import OpenAIError

from .user_store import resolve_mochi_api_key_from_config


async def _step_enrich(
    uid: str,
    user: dict[str, Any],
    *,
    card_store_factory: Callable[[Any], Any],
    gemini_client_factory: Callable[[], Any],
    logger: logging.Logger,
) -> None:
    logger.info("[%s] Step 1: Enrich", uid)
    cards = card_store_factory(user["dir"])
    targets = [card for card in cards.all() if not card.pos or not card.note]

    if not targets:
        logger.info("[%s] All cards already enriched", uid)
        return

    from .enrich import enrich_cards_stream

    client = gemini_client_factory()
    logger.info("[%s] Enriching %d cards...", uid, len(targets))
    updated = 0

    async for msg in enrich_cards_stream(client, targets, user_id=uid, batch_size=20, max_workers=5):
        if msg.get("status") == "error":
            logger.warning("[%s] Enrichment batch error: %s", uid, msg.get("detail"))

        if msg.get("results"):
            result_map = {result["word"].lower(): result for result in msg["results"]}
            for card in targets:
                enrichment = result_map.get(card.content.lower())
                if not enrichment:
                    continue
                kwargs = {}
                if enrichment.get("pos") and not card.pos:
                    kwargs["pos"] = enrichment["pos"]
                if enrichment.get("note") and not card.note:
                    kwargs["note"] = enrichment["note"]
                if kwargs:
                    updated_card = cards.update(card.id, **kwargs)
                    if updated_card:
                        card.pos = updated_card.pos
                        card.note = updated_card.note
                        updated += 1

    logger.info("[%s] Enriched %d cards", uid, updated)


async def _step_embed(
    uid: str,
    user: dict[str, Any],
    *,
    card_store_factory: Callable[[Any], Any],
    graph_store_factory: Callable[[Any], Any],
    embedding_store_factory: Callable[..., Any],
    logger: logging.Logger,
) -> None:
    cards = card_store_factory(user["dir"])
    embeddings = embedding_store_factory(user["dir"], user_id=uid)
    graph = graph_store_factory(user["dir"])
    missing = [card for card in cards.all() if not embeddings.has(card.id)]

    if not missing:
        return

    logger.info("[%s] Backfilling embeddings for %d cards", uid, len(missing))
    backfilled = 0
    for card in missing:
        try:
            embeddings.add(card.id, card.embed_text())
            similar = embeddings.find_similar(card.id, k=3)
            for other_id, score in similar:
                if score > 0.655:
                    graph.add_candidate(card.id, other_id, score)
            backfilled += 1
        except (OpenAIError, OSError, ValueError) as exc:
            logger.warning("[%s] Embedding backfill failed for '%s': %s", uid, card.content, exc)
    logger.info("[%s] Backfilled %d embeddings", uid, backfilled)


async def _step_link(
    uid: str,
    user: dict[str, Any],
    *,
    card_store_factory: Callable[[Any], Any],
    graph_store_factory: Callable[[Any], Any],
    gemini_client_factory: Callable[[], Any],
    logger: logging.Logger,
    link_kind_enum: Any,
) -> None:
    logger.info("[%s] Step 2: Link", uid)
    graph = graph_store_factory(user["dir"])
    candidates = graph.pop_candidates()

    if not candidates:
        logger.info("[%s] No pending candidates", uid)
        return

    from .judge import Judge

    client = gemini_client_factory()
    judge = Judge(client)
    cards = card_store_factory(user["dir"])
    created_links = 0
    index = 0

    try:
        for index, candidate in enumerate(candidates):  # noqa: B007
            card_a = cards.get(candidate.from_id)
            card_b = cards.get(candidate.to_id)
            if not card_a or not card_b or card_a.is_deleted or card_b.is_deleted:
                continue

            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                lambda a=card_a, b=card_b: judge.evaluate(
                    a.content, a.meaning, b.content, b.meaning, user_id=uid
                ),
            )

            if result:
                graph.add_link(
                    candidate.from_id,
                    candidate.to_id,
                    link_kind_enum(result.link),
                    result.confidence,
                    result.reason,
                )
                created_links += 1
    except Exception:  # broad catch: must requeue candidates before propagating
        graph.requeue_candidates(candidates[index:])
        raise

    logger.info("[%s] Created %d links", uid, created_links)


async def _step_difficulty(
    uid: str,
    user: dict[str, Any],
    *,
    card_store_factory: Callable[[Any], Any],
    logger: logging.Logger,
) -> None:
    logger.info("[%s] Step 3: Difficulty", uid)
    from .difficulty import get_zipf

    cards = card_store_factory(user["dir"])
    scored = 0
    for card in cards.all(include_deleted=False):
        difficulty = round(get_zipf(card.content), 2)
        if card.difficulty != difficulty:
            cards.update(card.id, difficulty=difficulty)
            scored += 1
    logger.info("[%s] Scored %d cards", uid, scored)


async def _step_external_sync(
    uid: str,
    user: dict[str, Any],
    *,
    card_store_factory: Callable[[Any], Any],
    graph_store_factory: Callable[[Any], Any],
    logger: logging.Logger,
    jwt_secret: str = "",
) -> None:
    logger.info("[%s] Step 4: Optional External Sync", uid)
    mochi_key = resolve_mochi_api_key_from_config(user["config"], jwt_secret)
    if not mochi_key:
        logger.info("[%s] Optional Mochi integration not configured, skipping external sync", uid)
        return

    from .mochi import MochiClient, MochiSync
    from .renderer import RenderIntent

    cards = card_store_factory(user["dir"])
    graph = graph_store_factory(user["dir"])
    mochi_client = MochiClient(mochi_key)
    syncer = MochiSync(
        mochi_client,
        cards,
        graph,
        map_path=user["dir"] / "mochi_map.json",
    )

    loop = asyncio.get_running_loop()
    stats = await loop.run_in_executor(None, lambda: syncer.sync(RenderIntent.FULL, dry_run=False))
    logger.info(
        "[%s] Optional external sync (Mochi): %d created, %d updated, %d deleted",
        uid, stats["created"], stats["updated"], stats["deleted"],
    )


async def run_pipeline_background(
    user: dict[str, Any],
    *,
    get_user_lock_fn: Callable[[str], Any],
    card_store_factory: Callable[[Any], Any],
    graph_store_factory: Callable[[Any], Any],
    embedding_store_factory: Callable[..., Any],
    gemini_client_factory: Callable[[], Any],
    logger: logging.Logger,
    link_kind_enum: Any,
    jwt_secret: str = "",
) -> None:
    uid = user["id"]
    lock = await get_user_lock_fn(uid)
    if lock.locked():
        logger.info("[%s] Pipeline already running, skipping.", uid)
        return

    async with lock:
        try:
            logger.info("[%s] Pipeline started.", uid)

            # Step isolation: each step logs its error (with traceback) and lets
            # subsequent steps run.  Broad catch is intentional here — a single
            # step failure must never abort the whole pipeline.

            try:
                await _step_enrich(uid, user, card_store_factory=card_store_factory, gemini_client_factory=gemini_client_factory, logger=logger)
            except Exception as exc:
                logger.error("[%s] Step 1 (Enrich) failed: %s", uid, exc, exc_info=True)

            try:
                await _step_embed(uid, user, card_store_factory=card_store_factory, graph_store_factory=graph_store_factory, embedding_store_factory=embedding_store_factory, logger=logger)
            except Exception as exc:
                logger.error("[%s] Step 1b (Embedding backfill) failed: %s", uid, exc, exc_info=True)

            try:
                await _step_link(uid, user, card_store_factory=card_store_factory, graph_store_factory=graph_store_factory, gemini_client_factory=gemini_client_factory, logger=logger, link_kind_enum=link_kind_enum)
            except Exception as exc:
                logger.error("[%s] Step 2 (Link) failed: %s", uid, exc, exc_info=True)

            try:
                await _step_difficulty(uid, user, card_store_factory=card_store_factory, logger=logger)
            except Exception as exc:
                logger.error("[%s] Step 3 (Difficulty) failed: %s", uid, exc, exc_info=True)

            try:
                await _step_external_sync(uid, user, card_store_factory=card_store_factory, graph_store_factory=graph_store_factory, logger=logger, jwt_secret=jwt_secret)
            except Exception as exc:
                logger.error("[%s] Step 4 (Optional External Sync) failed: %s", uid, exc, exc_info=True)

            logger.info("[%s] Pipeline completed.", uid)

        except Exception as exc:
            logger.error("[%s] Pipeline unexpected error: %s", uid, exc, exc_info=True)
