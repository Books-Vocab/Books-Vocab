"""Graph-related vocab operations: embedding, candidate linking, graph queries."""

from __future__ import annotations

import logging
from typing import Any

from .api_models import GraphLinkResponse


SIMILARITY_THRESHOLD = 0.70
CANDIDATE_K = 20


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
    for entry in entries:
        word = entry.word.strip()
        card_id = card_ids.get(word)
        card = cards.get(card_id) if card_id else None
        if card and not embeddings.has(card.id):
            try:
                embeddings.add(card.id, card.embed_text())
                similar = embeddings.find_similar(card.id, k=CANDIDATE_K)
                for other_id, score in similar:
                    if score > SIMILARITY_THRESHOLD:
                        other_card = cards.get(other_id)
                        if other_card and not other_card.is_archived:
                            graph.add_candidate(card.id, other_id, score)
            except (OSError, ValueError) as exc:
                logger.warning("Failed to generate embedding for '%s': %s", word, exc)
                continue


def graph_links_payload(*, graph: Any) -> list[GraphLinkResponse]:
    """Build graph links response from active links."""
    links = []
    for link in graph._links.values():
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
