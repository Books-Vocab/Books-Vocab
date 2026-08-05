"""Graph-related vocab operations: embedding, candidate linking, graph queries."""

from __future__ import annotations

import logging
from typing import Any

from .api_models import GraphLinkResponse
from .vocab_shared import _clean_content

SIMILARITY_THRESHOLD = 0.70
CANDIDATE_K = 12
MAX_DEGREE = 6  # 每張卡最多連結數


def embed_and_link_new_cards(
    *,
    cards: Any,
    embeddings: Any,
    graph: Any,
    card_ids: dict[str, str],
    entries: list[Any],
    logger: logging.Logger,
) -> None:
    """Embed new cards and mark them for graph judging."""
    # Collect cards that need embedding
    batch_items: list[tuple[str, str]] = []
    batch_cards: list[Any] = []
    for entry in entries:
        # card_ids is keyed by the CLEANED word (see vocab_intake.add_vocab_entries),
        # so we must clean here too — a bare strip() would miss any word that
        # _clean_content rewrites (trailing punctuation / uppercase first char),
        # leaving that card silently un-embedded and unlinked.
        word = _clean_content(entry.word)
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

    # Mark successfully embedded cards for pending judge
    embedded_ids = [card.id for card in batch_cards if embeddings.has(card.id)]
    if embedded_ids:
        graph.add_pending_judge(embedded_ids)


def graph_links_payload(
    *, graph: Any, cards_store: Any | None = None, include_dictionary: bool = False,
) -> list[GraphLinkResponse]:
    """Build graph links response from active links."""
    active_links = [link for link in graph.all_links() if link.status == "active"]
    cards_by_id: dict[str, Any] = {}
    active_dictionary_ids: set[str] = set()
    if cards_store is not None:
        endpoint_ids = {
            card_id for link in active_links for card_id in (link.from_id, link.to_id)
        }
        cards_by_id = cards_store.get_batch(endpoint_ids)
        if include_dictionary:
            dictionary_ids = {
                card_id
                for card_id, card in cards_by_id.items()
                if getattr(card, "card_role", "learning") == "dictionary"
            }
            active_dictionary_ids = cards_store.get_active_dictionary_card_ids(dictionary_ids)
    links = []
    for link in active_links:
        if cards_store is not None and not include_dictionary:
            from_card = cards_by_id.get(link.from_id)
            to_card = cards_by_id.get(link.to_id)
            if (
                (from_card is not None and getattr(from_card, "card_role", "learning") != "learning")
                or (to_card is not None and getattr(to_card, "card_role", "learning") != "learning")
            ):
                continue
        if cards_store is not None and include_dictionary:
            endpoint_cards = (cards_by_id.get(link.from_id), cards_by_id.get(link.to_id))
            if any(
                card is not None
                and getattr(card, "card_role", "learning") == "dictionary"
                and card.id not in active_dictionary_ids
                for card in endpoint_cards
            ):
                continue
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
