from __future__ import annotations

import asyncio
from typing import Any, Callable


async def run_pipeline_background(
    user: dict[str, Any],
    *,
    get_user_lock_fn: Callable[[str], Any],
    card_store_factory: Callable[[Any], Any],
    graph_store_factory: Callable[[Any], Any],
    embedding_store_factory: Callable[..., Any],
    gemini_client_factory: Callable[[], Any],
    logger: Any,
    link_kind_enum: Any,
) -> None:
    uid = user["id"]
    lock = await get_user_lock_fn(uid)
    if lock.locked():
        logger.info("[%s] Pipeline already running, skipping.", uid)
        return

    async with lock:
        try:
            logger.info("[%s] Pipeline started.", uid)

            try:
                logger.info("[%s] Step 1: Enrich", uid)
                cards = card_store_factory(user["dir"])
                all_cards = list(cards.all())
                targets = [card for card in all_cards if not card.pos or not card.note]

                if targets:
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
                else:
                    logger.info("[%s] All cards already enriched", uid)
            except Exception as exc:
                logger.error("[%s] Step 1 (Enrich) failed: %s", uid, exc, exc_info=True)

            try:
                cards = card_store_factory(user["dir"])
                embeddings = embedding_store_factory(user["dir"], user_id=uid)
                graph = graph_store_factory(user["dir"])
                missing = [card for card in cards.all() if not embeddings.has(card.id)]
                if missing:
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
                        except Exception as exc:
                            logger.warning("[%s] Embedding backfill failed for '%s': %s", uid, card.content, exc)
                    logger.info("[%s] Backfilled %d embeddings", uid, backfilled)
            except Exception as exc:
                logger.error("[%s] Step 1b (Embedding backfill) failed: %s", uid, exc, exc_info=True)

            try:
                logger.info("[%s] Step 2: Link", uid)
                graph = graph_store_factory(user["dir"])
                candidates = graph.pop_candidates()

                if candidates:
                    from .judge import Judge

                    client = gemini_client_factory()
                    judge = Judge(client)
                    created_links = 0
                    cards = card_store_factory(user["dir"])
                    index = 0

                    try:
                        for index, candidate in enumerate(candidates):
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
                    except Exception as exc:
                        graph.requeue_candidates(candidates[index:])
                        raise exc

                    logger.info("[%s] Created %d links", uid, created_links)
                else:
                    logger.info("[%s] No pending candidates", uid)
            except Exception as exc:
                logger.error("[%s] Step 2 (Link) failed: %s", uid, exc, exc_info=True)

            try:
                logger.info("[%s] Step 3: Difficulty", uid)
                from .difficulty import get_zipf

                cards = card_store_factory(user["dir"])
                all_cards = list(cards.all(include_deleted=False))
                scored = 0
                for card in all_cards:
                    zipf = get_zipf(card.content)
                    difficulty = round(zipf, 2)
                    if card.difficulty != difficulty:
                        cards.update(card.id, difficulty=difficulty)
                        scored += 1
                logger.info("[%s] Scored %d cards", uid, scored)
            except Exception as exc:
                logger.error("[%s] Step 3 (Difficulty) failed: %s", uid, exc, exc_info=True)

            try:
                logger.info("[%s] Step 4: Mochi Sync", uid)
                mochi_key = user["config"].get("mochi_api_key")
                if not mochi_key:
                    logger.info("[%s] Mochi API key not set, skipping sync", uid)
                else:
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

                    def _run_sync():
                        return syncer.sync(RenderIntent.FULL, dry_run=False)

                    stats = await loop.run_in_executor(None, _run_sync)
                    logger.info(
                        "[%s] Mochi Sync: %d created, %d updated, %d deleted",
                        uid, stats["created"], stats["updated"], stats["deleted"],
                    )
            except Exception as exc:
                logger.error("[%s] Step 4 (Mochi Sync) failed: %s", uid, exc, exc_info=True)

            logger.info("[%s] Pipeline completed.", uid)

        except Exception as exc:
            logger.error("[%s] Pipeline unexpected error: %s", uid, exc, exc_info=True)
