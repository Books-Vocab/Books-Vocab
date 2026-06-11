from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from openai import OpenAIError

from ..types import UserRecord
from ..vocab_graph import CANDIDATE_K, MAX_DEGREE, SIMILARITY_THRESHOLD


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
    client_factory: Callable[..., Any],
    logger: logging.Logger,
    force: bool = False,
    notebook_id: str = "default",
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

    from ..deps_quota import _is_pro
    from ..enrich import enrich_cards_stream
    from ..llm.providers import provider_for
    from ..tracked_llm import TrackedLLM

    provider = provider_for("enrich")
    llm = TrackedLLM(
        client_factory(provider),
        uid,
        provider=provider,
        enforce_quota=True,
        is_pro=_is_pro(user),
    )
    logger.info("[%s] Enriching %d cards...", uid, len(targets))
    updated = 0

    async for msg in enrich_cards_stream(llm, targets, batch_size=20, max_workers=5, model=provider.chat_model):
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
                        from ..vocab_shared import _normalize_pos
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


async def _step_embed_and_judge(
    uid: str,
    user: UserRecord,
    *,
    card_store_factory: Callable[[Any], Any],
    graph_store_factory: Callable[..., Any],
    embedding_store_factory: Callable[..., Any],
    client_factory: Callable[..., Any],
    logger: logging.Logger,
    link_kind_enum: Any,
    notebook_id: str = "default",
) -> int:
    """Combined embed + judge step. Replaces _step_embed + _step_link."""
    from ..deps_quota import _is_pro
    from ..judge import Judge
    from ..llm.providers import provider_for
    from ..tracked_llm import TrackedLLM
    is_pro = _is_pro(user)

    cards = card_store_factory(user["dir"])
    # `embed` resolves independently of the chat default — DeepSeek has no
    # embeddings endpoint, so flipping LLM_PROVIDER_DEFAULT must not drag it.
    embed_provider = provider_for("embed")
    embed_llm = TrackedLLM(
        client_factory(embed_provider),
        uid,
        provider=embed_provider,
        enforce_quota=True,
        is_pro=is_pro,
    )
    embeddings = embedding_store_factory(user["dir"], llm=embed_llm, notebook_id=notebook_id)
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
    # Per-user auto_link 開關(user config 的 auto_link group):關閉時不消費
    # pending_judge——新卡仍照常 embed 並入列(上方 Phase 1),重新開啟後下一輪
    # pipeline 續判,不丟失。缺省/壞型別 fallback enabled=True 向後相容,語意
    # 對齊 user_handlers._build_user_config_response。
    user_config = user.get("config")
    auto_link_cfg = user_config.get("auto_link") if isinstance(user_config, dict) else None
    if isinstance(auto_link_cfg, dict) and not auto_link_cfg.get("enabled", True):
        logger.info("[%s] Auto-link disabled by user config; judge skipped", uid)
        return 0

    pending = graph.pop_pending_judge()
    if not pending:
        logger.info("[%s] No pending cards to judge", uid)
        return 0

    logger.info("[%s] Judging %d pending cards", uid, len(pending))
    judge_provider = provider_for("judge")
    judge_llm = TrackedLLM(
        client_factory(judge_provider),
        uid,
        provider=judge_provider,
        enforce_quota=True,
        is_pro=is_pro,
    )
    from ..settings import load_settings
    judge = Judge(
        judge_llm, model=judge_provider.chat_model,
        user_id=uid, notebook_id=notebook_id,
        confidence_threshold=load_settings().judge_confidence_threshold,
    )

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

    # Per-card similarity map for audit logging when degree cap forces a
    # reject — built lazily so we only pay if a cap actually fires.
    sims_by_card: dict[str, dict[str, float]] = {
        cid: s for cid, _, _, s, _, _ in judge_tasks
    }

    def _log_degree_cap(from_id: str, to_id: str, judgement) -> None:
        """Mark an LLM-accepted candidate as cap-evicted in judge_log.

        ``Judge.evaluate_batch`` has already inserted an ``accepted=1`` row
        for this candidate. Inserting a second ``accepted=0`` row would
        double-count the pair and pollute ``get_acceptance_stats``. Instead,
        flip the existing row to ``accepted=0`` with
        ``reject_reason='degree_cap'`` so the audit trail tells "LLM
        accepted, pipeline capped" without inflating the denominator.
        """
        if not uid:
            return
        try:
            from .. import judge_log
            updated = judge_log.update_to_rejected(
                from_id, to_id, reason="degree_cap",
            )
            if not updated:
                # Fallback: no prior accepted row (e.g. judge bypassed
                # logging). Insert a fresh degree_cap row so the eviction
                # is still observable.
                judge_log.record(
                    user_id=uid, notebook_id=notebook_id,
                    from_id=from_id, to_id=to_id,
                    similarity=sims_by_card.get(from_id, {}).get(to_id),
                    verdict=judgement.link, confidence=judgement.confidence,
                    accepted=False, reject_reason="degree_cap",
                    reason=judgement.reason, source="auto",
                )
        except Exception:
            logger.warning("[%s] Failed to write degree_cap judge_log", uid, exc_info=True)

    processed = 0
    try:
        for card_id, fut in futures:
            results = await fut
            # NOTE: do NOT `break` on from-cap — we still need to walk
            # remaining results so over-cap accepted candidates get
            # logged as degree_cap rejects (audit trail).
            for other_id, judgement in results.items():
                if judgement is None:
                    continue
                if from_link_counts[card_id] >= MAX_DEGREE:
                    _log_degree_cap(card_id, other_id, judgement)
                    continue  # from-side at cap; keep logging surplus
                # Initialize to-side count on first access
                if other_id not in to_link_counts:
                    to_link_counts[other_id] = _active_degree(other_id)
                if to_link_counts[other_id] >= MAX_DEGREE:
                    _log_degree_cap(card_id, other_id, judgement)
                    continue
                all_links.append((
                    card_id, other_id,
                    link_kind_enum(judgement.link),
                    judgement.confidence,
                    judgement.reason,
                ))
                from_link_counts[card_id] += 1
                to_link_counts[other_id] += 1
            # Increment ONLY after a card's results are FULLY consumed.
            # If an exception fires inside the inner loop above (e.g.
            # `link_kind_enum` rejects an illegal enum value), `processed`
            # still points at the failing card so `futures[processed:]`
            # re-includes it for requeue. Phase 2a's `graph.has_link`
            # check then skips any links this card already persisted, so
            # the re-judge neither double-links nor double-counts.
            processed += 1
    except Exception:
        # Requeue unprocessed cards. `processed` is incremented only AFTER
        # a card's results are fully consumed, so on exception it still
        # points to the card that failed — whether the failure was in
        # `await fut` or mid result-consumption — and `futures[processed:]`
        # correctly includes it.
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
                logger.warning("[%s] Failed to persist partial links/touch", uid, exc_info=True)
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
    from ..difficulty import get_zipf

    cards = card_store_factory(user["dir"])
    updates = []
    for card in cards.all(include_deleted=False, notebook_id=notebook_id):
        difficulty = round(get_zipf(card.content), 2)
        if card.difficulty != difficulty:
            updates.append((card.id, {"difficulty": difficulty}))
    scored = cards.batch_update(updates)
    logger.info("[%s] Scored %d cards", uid, scored)
    return scored
