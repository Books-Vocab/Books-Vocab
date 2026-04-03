"""Graph-related vocab operations: embedding, candidate linking, graph queries."""

from __future__ import annotations

import logging
from typing import Any

from .api_models import GraphLinkResponse


SIMILARITY_THRESHOLD = 0.70
CANDIDATE_K = 12


def embed_and_link_new_cards(
    *,
    cards: Any,
    embeddings: Any,
    graph: Any,
    card_ids: dict[str, str],
    entries: list[Any],
    logger: logging.Logger,
) -> None:
    """Generate embeddings for new cards and create graph link candidates."""
    # Collect cards that need embedding
    batch_items: list[tuple[str, str]] = []
    batch_cards: list[Any] = []
    for entry in entries:
        word = entry.word.strip()
        card_id = card_ids.get(word)
        card = cards.get(card_id) if card_id else None
        if card and not embeddings.has(card.id):
            batch_items.append((card.id, card.embed_text()))
            batch_cards.append(card)

    if not batch_items:
        return

    # Single API call for all embeddings
    try:
        embeddings.add_batch(batch_items)
    except (OSError, ValueError) as exc:
        logger.warning("Batch embedding failed: %s", exc)
        return

    # Link candidates for newly embedded cards — batch to avoid per-pair disk writes
    # Phase 1: collect all similar pairs and other_ids
    all_similar: list[tuple[Any, list[tuple[str, float]]]] = []
    all_other_ids: set[str] = set()
    for card in batch_cards:
        if not embeddings.has(card.id):
            continue
        try:
            similar = embeddings.find_similar(card.id, k=CANDIDATE_K)
            filtered = [(oid, sc) for oid, sc in similar if sc > SIMILARITY_THRESHOLD]
            if filtered:
                all_similar.append((card, filtered))
                all_other_ids.update(oid for oid, _ in filtered)
        except (OSError, ValueError) as exc:
            logger.warning("Failed to link candidates for '%s': %s", card.id, exc)

    # Phase 2: batch fetch neighbour cards, then build candidates
    others_by_id = cards.get_batch(all_other_ids) if all_other_ids else {}
    candidate_items: list[tuple[str, str, float]] = []
    for card, similar in all_similar:
        for other_id, score in similar:
            other_card = others_by_id.get(other_id)
            if other_card and not other_card.is_archived:
                candidate_items.append((card.id, other_id, score))

    if candidate_items:
        graph.batch_add_candidates(candidate_items)


def graph_links_payload(*, graph: Any) -> list[GraphLinkResponse]:
    """Build graph links response from active links."""
    links = []
    for link in graph.all_links():
        if link.status != "active":
            continue
        links.append(
            GraphLinkResponse(
                id=link.id,
                fromId=link.from_id,
                toId=link.to_id,
                kind=link.kind.value,
                confidence=link.confidence,
                reason=link.reason,
            )
        )
    return links
