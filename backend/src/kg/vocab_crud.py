"""Vocabulary CRUD operations: list, lookup, archive, delete, batch, move."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from .api_models import CardResponse
from .exceptions import BadRequestError, NotFoundError, ValidationError
from .user_store import parse_datetime
from .vocab_shared import (
    MAX_BATCH_SIZE,
    MAX_WORD_LENGTH,
    _build_content_lookup,
    _normalize_word,
)

logger = logging.getLogger(__name__)


def list_vocab_cards(*, since: str | None, cards_store: Any, graph: Any, card_response_builder: Callable[[Any, Any, dict[str, Any]], CardResponse], notebook_id: str | None = None) -> list[CardResponse]:
    if since:
        parsed_since = parse_datetime(since)
        if parsed_since is None:
            raise BadRequestError("Invalid since timestamp format. Expected ISO 8601.")
        naive_since = parsed_since.replace(tzinfo=None) if parsed_since.tzinfo else parsed_since
        # Phase 1: only fetch modified cards (uses ix_card_updated_at index)
        modified = cards_store.get_modified_since(naive_since, notebook_id=notebook_id)
        modified_by_id: dict[str, Any] = {c.id: c for c in modified}
        # Phase 2: collect neighbour IDs for link resolution (graph is in-memory, N lookups OK)
        neighbour_ids: set[str] = set()
        for card in modified:
            if card.is_deleted:
                continue
            for link in graph.get_links_for(card.id):
                other_id = link.to_id if link.from_id == card.id else link.from_id
                if other_id not in modified_by_id:
                    neighbour_ids.add(other_id)
        neighbours = cards_store.get_batch(neighbour_ids) if neighbour_ids else {}
        # NOTE: cards_by_id is a subset (modified + neighbours), not the full table.
        # build_links_by_kind skips missing neighbours via `if not other_card`.
        cards_by_id = modified_by_id | neighbours
        cards = modified
    else:
        # Full sync: all non-deleted cards. Deleted neighbours are skipped by build_links_by_kind.
        cards_by_id = cards_store.all_as_dict(include_deleted=False, notebook_id=notebook_id)
        cards = list(cards_by_id.values())

    return [card_response_builder(card, graph, cards_by_id) for card in cards]


def lookup_vocab_word(word: str, *, cards_store: Any, graph: Any, card_response_builder: Callable[[Any, Any, dict[str, Any]], CardResponse], notebook_id: str | None = None) -> CardResponse:
    if len(word) > MAX_WORD_LENGTH:
        raise ValidationError("Word too long")
    card = cards_store.find_by_content(word, notebook_id=notebook_id)
    if not card:
        raise NotFoundError("Word", word)

    # Only fetch the target card + its graph-linked neighbours instead of full table.
    cards_by_id: dict[str, Any] = {card.id: card}
    for link in graph.get_links_for(card.id):
        linked_id = link.from_id if link.to_id == card.id else link.to_id
        if linked_id not in cards_by_id:
            linked_card = cards_store.get(linked_id)
            if linked_card:
                cards_by_id[linked_id] = linked_card

    return card_response_builder(card, graph, cards_by_id)


def archive_vocab_word(word: str, *, archived: bool, cards_store: Any, graph: Any = None, notebook_id: str | None = None) -> dict[str, str]:
    if len(word) > MAX_WORD_LENGTH:
        raise ValidationError("Word too long")
    card = cards_store.find_by_content(word, notebook_id=notebook_id)
    if not card:
        raise NotFoundError("Word", word)
    cards_store.update(card.id, is_archived=archived)
    if graph is not None:
        if archived:
            graph.cleanup_for_card(card.id)
        else:
            graph.restore_links_for(card.id, cards_store)
    return {"word": word, "id": card.id, "archived": archived}


def delete_vocab_word(word: str, *, cards_store: Any, graph: Any = None, notebook_id: str | None = None) -> dict[str, str]:
    if len(word) > MAX_WORD_LENGTH:
        raise ValidationError("Word too long")
    card = cards_store.find_by_content(word, notebook_id=notebook_id)
    if not card:
        raise NotFoundError("Word", word)
    cards_store.delete(card.id)
    if graph is not None:
        try:
            graph.cleanup_for_card(card.id, remove_blocked=True)
        except Exception:
            logger.error("Graph operation failed for card %s", card.id, exc_info=True)
            try:
                cards_store.restore(card.id)
            except Exception:
                logger.exception("restore failed for card %s after graph error", card.id)
            raise
    return {"deleted": word, "id": card.id}


def batch_delete_vocab_words(
    words: list[str],
    *,
    cards_store: Any,
    graph: Any = None,
    notebook_id: str | None = None,
) -> dict[str, Any]:
    """Delete multiple words in one call. Skips not-found words instead of raising."""
    if not words:
        raise ValidationError("No words provided")
    if len(words) > MAX_BATCH_SIZE:
        raise ValidationError(f"Too many words (max {MAX_BATCH_SIZE})")

    deleted_words: list[str] = []
    not_found: list[str] = []

    lookup = _build_content_lookup(cards_store, notebook_id=notebook_id)

    for word in words:
        card = lookup.get(_normalize_word(word))
        if not card:
            not_found.append(word)
            continue
        cards_store.delete(card.id)
        if graph is not None:
            try:
                graph.cleanup_for_card(card.id, remove_blocked=True)
            except Exception:
                try:
                    cards_store.restore(card.id)
                except Exception:
                    logger.exception("restore failed for card %s after graph error", card.id)
                not_found.append(word)
                continue
        deleted_words.append(word)

    return {"deleted": len(deleted_words), "deleted_words": deleted_words, "not_found": not_found}


def batch_archive_vocab_words(
    words: list[str],
    *,
    archived: bool,
    cards_store: Any,
    graph: Any = None,
    notebook_id: str | None = None,
) -> dict[str, Any]:
    """Archive or unarchive multiple words in one call. Skips not-found words."""
    if not words:
        raise ValidationError("No words provided")
    if len(words) > MAX_BATCH_SIZE:
        raise ValidationError(f"Too many words (max {MAX_BATCH_SIZE})")

    updated_words: list[str] = []
    not_found: list[str] = []

    lookup = _build_content_lookup(cards_store, notebook_id=notebook_id)

    for word in words:
        card = lookup.get(_normalize_word(word))
        if not card:
            not_found.append(word)
            continue
        cards_store.update(card.id, is_archived=archived)
        if graph is not None:
            if archived:
                graph.cleanup_for_card(card.id)
            else:
                graph.restore_links_for(card.id, cards_store)
        updated_words.append(word)

    return {"updated": len(updated_words), "updated_words": updated_words, "not_found": not_found}


def move_vocab_words(
    words: list[str],
    *,
    from_notebook_id: str,
    to_notebook_id: str,
    cards_store: Any,
    source_graph: Any = None,
    target_graph: Any = None,
) -> dict[str, int]:
    """Move specific cards between notebooks. Deprecates graph links in source, adds candidates in target."""
    if not words:
        raise ValidationError("No words provided")
    if from_notebook_id == to_notebook_id:
        raise ValidationError("Source and target notebook are the same")

    # Find card IDs before move (for graph cleanup) — single bulk lookup
    lookup = _build_content_lookup(cards_store, notebook_id=from_notebook_id)
    card_ids = []
    for word in words:
        card = lookup.get(_normalize_word(word))
        if card:
            card_ids.append(card.id)

    moved = cards_store.move_cards(words, from_notebook_id=from_notebook_id, to_notebook_id=to_notebook_id)

    # Deprecate graph links in source notebook
    if source_graph is not None:
        for card_id in card_ids:
            source_graph.cleanup_for_card(card_id)

    # Add candidates in target notebook so pipeline regenerates links
    if target_graph is not None:
        target_ids = [c.id for c in (cards_store.all(notebook_id=to_notebook_id) or []) if c.id not in card_ids and not c.is_deleted and not c.is_archived]
        candidate_pairs = []
        for card_id in card_ids:
            for other_id in target_ids[:20]:
                candidate_pairs.append((card_id, other_id, 0.0))
        if candidate_pairs:
            target_graph.batch_add_candidates(candidate_pairs)

    return {"moved": moved}
