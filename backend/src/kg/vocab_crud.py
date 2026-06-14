"""Vocabulary CRUD operations: list, lookup, archive, delete, batch."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime
from typing import Any, NamedTuple

from .api_models import CardResponse
from .api_models.vocab import ArchiveWordResponse, DeleteWordResponse
from .exceptions import BadRequestError, NotFoundError, ValidationError
from .user_store import parse_datetime
from .vocab_shared import (
    MAX_BATCH_SIZE,
    MAX_WORD_LENGTH,
    _build_content_lookup,
    _clean_content,
    _normalize_word,
)

logger = logging.getLogger(__name__)


def _resolve_with_neighbours(cards: list[Any], graph: Any, cards_store: Any) -> dict[str, Any]:
    """Build the ``cards_by_id`` map for a page: the page's own cards plus the
    graph neighbours (on other pages / soft-deleted) needed to render links.

    The page itself is a *subset* of the full table, so any neighbour not on the
    page is fetched via ``get_batch`` (one query). ``build_links_by_kind`` still
    tolerates a missing neighbour (``if not other_card``), so a cross-page or
    deleted neighbour that can't be resolved is simply skipped rather than
    dropping the whole link silently.
    """
    by_id: dict[str, Any] = {c.id: c for c in cards}
    neighbour_ids: set[str] = set()
    for card in cards:
        if card.is_deleted:
            continue
        for link in graph.get_links_for(card.id):
            other_id = link.to_id if link.from_id == card.id else link.from_id
            if other_id not in by_id:
                neighbour_ids.add(other_id)
    if neighbour_ids:
        by_id |= cards_store.get_batch(neighbour_ids)
    return by_id


def _page_cursor(cards: list[Any], limit: int) -> tuple[datetime, str] | None:
    """Cursor for the next page, or ``None`` when this page drained the source.

    A full page (``len == limit``) means more rows *may* remain, so emit the
    last card's ``(updated_at, id)``. A short page means the source is drained.
    """
    if limit and len(cards) == limit:
        last = cards[-1]
        return (last.updated_at, last.id)
    return None


def list_vocab_cards(
    *,
    since: str | None,
    cards_store: Any,
    graph: Any,
    card_response_builder: Callable[[Any, Any, dict[str, Any]], CardResponse],
    notebook_id: str | None = None,
    limit: int = 5000,
    after: tuple[datetime, str] | None = None,
) -> tuple[list[CardResponse], tuple[datetime, str] | None]:
    """List vocab cards as ``(responses, next_cursor)``.

    Both the full-sync (``since=None``) and incremental (``since=...``) paths
    page by the composite cursor ``(updated_at, id)`` with a bounded ``limit``.
    ``after`` is the previous page's cursor; ``next_cursor`` is non-None only
    when a full page was returned (more rows may remain). Cards are returned in
    ascending ``(updated_at, id)`` order so the cursor advances monotonically.
    """
    if since:
        parsed_since = parse_datetime(since)
        if parsed_since is None:
            raise BadRequestError("Invalid since timestamp format. Expected ISO 8601.")
        naive_since = parsed_since.replace(tzinfo=None) if parsed_since.tzinfo else parsed_since
        # Incremental: fetch the modified set (already bounded), then order and
        # slice it by the same cursor so since + full-sync paginate identically.
        modified = cards_store.get_modified_since(naive_since, notebook_id=notebook_id)
        modified = sorted(modified, key=lambda c: (c.updated_at, c.id))
        if after is not None:
            modified = [c for c in modified if (c.updated_at, c.id) > after]
        cards = modified[:limit]
    else:
        # Full sync: DB-bounded page (no full-table materialisation).
        cards = cards_store.page_cards(
            limit=limit, after=after, include_deleted=False, notebook_id=notebook_id
        )

    cards_by_id = _resolve_with_neighbours(cards, graph, cards_store)
    responses = [card_response_builder(card, graph, cards_by_id) for card in cards]
    return responses, _page_cursor(cards, limit)


def _resolve_card_or_raise(cards_store: Any, word: str, notebook_id: str | None) -> Any:
    if len(word) > MAX_WORD_LENGTH:
        raise ValidationError("Word too long")
    card = cards_store.find_by_content(word, notebook_id=notebook_id)
    if not card:
        raise NotFoundError("Word", word)
    return card


def lookup_vocab_word(word: str, *, cards_store: Any, graph: Any, card_response_builder: Callable[[Any, Any, dict[str, Any]], CardResponse], notebook_id: str | None = None) -> CardResponse:
    card = _resolve_card_or_raise(cards_store, word, notebook_id)

    # Only fetch the target card + its graph-linked neighbours instead of full table.
    cards_by_id: dict[str, Any] = {card.id: card}
    for link in graph.get_links_for(card.id):
        linked_id = link.from_id if link.to_id == card.id else link.to_id
        if linked_id not in cards_by_id:
            linked_card = cards_store.get(linked_id)
            if linked_card:
                cards_by_id[linked_id] = linked_card

    return card_response_builder(card, graph, cards_by_id)


def archive_vocab_word(word: str, *, archived: bool, cards_store: Any, graph: Any = None, notebook_id: str | None = None) -> ArchiveWordResponse:
    card = _resolve_card_or_raise(cards_store, word, notebook_id)
    cards_store.update(card.id, is_archived=archived)
    if graph is not None:
        try:
            if archived:
                graph.cleanup_for_card(card.id, source="manual")
            else:
                graph.restore_links_for(card.id, cards_store, source="manual")
        except Exception:
            # Roll the card's archive state back to its original value so a
            # failed graph op never leaves card state and the response out of
            # sync, then re-raise (mirrors delete_vocab_word).
            logger.error("Graph operation failed for card %s", card.id, exc_info=True)
            try:
                cards_store.update(card.id, is_archived=not archived)
            except Exception:
                logger.exception("Rollback failed for card %s after graph error", card.id)
            raise
    return ArchiveWordResponse(word=word, id=card.id, archived=archived)


def update_vocab_word_content(
    word: str,
    *,
    meaning: str | None,
    note: str | None,
    explanation: str | None,
    cards_store: Any,
    graph: Any,
    card_response_builder: Callable[[Any, Any, dict[str, Any]], CardResponse],
    notebook_id: str | None = None,
) -> CardResponse:
    """Update editorial content (meaning / note) of a single card.

    `explanation` is a write-through alias for the `note` column; an explicit
    `note` takes precedence when both are supplied. Raises BadRequestError when
    no content field is provided (the empty-body case), NotFoundError when the
    word does not resolve in the notebook.
    """
    card = _resolve_card_or_raise(cards_store, word, notebook_id)

    updates: dict[str, Any] = {}
    if meaning is not None:
        updates["meaning"] = meaning
    note_value = note if note is not None else explanation
    if note_value is not None:
        updates["note"] = note_value

    if not updates:
        raise BadRequestError("No content fields to update")

    cards_store.update(card.id, **updates)

    # Re-read the card + its graph neighbours so the response reflects the
    # committed state (mirrors lookup_vocab_word's neighbour resolution).
    return lookup_vocab_word(
        word,
        cards_store=cards_store,
        graph=graph,
        card_response_builder=card_response_builder,
        notebook_id=notebook_id,
    )


def _evict_embedding(embeddings: Any, card_id: str) -> None:
    """Evict a deleted card's vector. Best-effort: the card is already gone,
    so an embedding-store failure must not fail the request — it only leaves
    a stale row that the next pipeline run / restart tolerates."""
    if embeddings is None:
        return
    try:
        embeddings.remove(card_id)
    except Exception:
        logger.warning("Failed to evict embedding for card %s", card_id, exc_info=True)


def delete_vocab_word(
    word: str,
    *,
    cards_store: Any,
    graph: Any = None,
    embeddings: Any = None,
    notebook_id: str | None = None,
) -> DeleteWordResponse:
    card = _resolve_card_or_raise(cards_store, word, notebook_id)
    cards_store.delete(card.id)
    if graph is not None:
        try:
            graph.cleanup_for_card(card.id, remove_blocked=True, source="manual")
        except Exception:
            logger.error("Graph operation failed for card %s", card.id, exc_info=True)
            try:
                cards_store.restore(card.id, notebook_id=card.notebook_id)
            except Exception:
                logger.exception("Restore failed for card %s after graph error", card.id)
            raise
    # Card is committed-deleted past this point — drop its embedding so it
    # stops polluting find_similar. Done after the rollback window so a
    # restored card keeps its vector.
    _evict_embedding(embeddings, card.id)
    return DeleteWordResponse(deleted=word, id=card.id)


class _GraphOpFailed(Exception):
    """Signals that a per-card graph op failed (and was rolled back).

    Routes the word to the ``failed`` bucket without aborting the batch. Only
    *graph* failures use this — a store-mutation failure (e.g. a commit error)
    propagates out of ``_batch_apply`` and aborts the batch, matching the
    pre-refactor contract where the store call sat outside the graph try/except.
    """


class BulkResult(NamedTuple):
    succeeded: list[tuple[str, Any]]
    not_found: list[str]
    failed: list[str]


def _batch_apply(
    words: list[str],
    *,
    cards_store: Any,
    notebook_id: str | None,
    apply: Callable[[Any], None],
) -> BulkResult:
    """Shared skeleton for batch vocab mutations.

    Validates the batch size, builds one content lookup, and runs ``apply(card)``
    for each resolved word. ``apply`` performs the card mutation + graph op; on a
    graph failure it must roll its own state back and raise ``_GraphOpFailed``,
    which routes the word to ``failed`` rather than aborting the batch. Any other
    exception propagates and aborts the batch (preserving pre-refactor behaviour
    for store-level failures).

    Returns ``(succeeded, not_found, failed)`` where ``succeeded`` is a list of
    ``(word, card)`` pairs in input order. Callers shape these into the three
    disjoint buckets the client uses to converge (see #720).
    """
    if not words:
        raise ValidationError("No words provided")
    if len(words) > MAX_BATCH_SIZE:
        raise ValidationError(f"Too many words (max {MAX_BATCH_SIZE})")

    succeeded: list[tuple[str, Any]] = []
    not_found: list[str] = []
    failed: list[str] = []

    lookup = _build_content_lookup(cards_store, notebook_id=notebook_id)
    seen_words_by_key: dict[str, set[str]] = {}
    outcome_by_key: dict[str, tuple[str, Any | None]] = {}

    for word in words:
        key = _normalize_word(_clean_content(word))
        seen_words = seen_words_by_key.setdefault(key, set())
        if word in seen_words:
            continue
        seen_words.add(word)
        previous = outcome_by_key.get(key)
        if previous is not None:
            status, card = previous
            if status == "succeeded" and card is not None:
                succeeded.append((word, card))
            elif status == "not_found":
                not_found.append(word)
            elif status == "failed":
                failed.append(word)
            continue
        card = lookup.get(key)
        if not card:
            not_found.append(word)
            outcome_by_key[key] = ("not_found", None)
            continue
        try:
            apply(card)
        except _GraphOpFailed:
            failed.append(word)
            outcome_by_key[key] = ("failed", None)
            continue
        succeeded.append((word, card))
        outcome_by_key[key] = ("succeeded", card)

    return BulkResult(succeeded, not_found, failed)


def batch_delete_vocab_words(
    words: list[str],
    *,
    cards_store: Any,
    graph: Any = None,
    embeddings: Any = None,
    notebook_id: str | None = None,
) -> dict[str, Any]:
    """Delete multiple words in one call. Skips not-found words instead of raising.

    Returns three disjoint buckets so the client can converge correctly:

    - ``deleted_words`` — successfully deleted (card gone, graph cleaned).
    - ``not_found`` — lookup miss only: no such card on the server. The client
      may safely converge/remove these locally.
    - ``failed`` — graph cleanup raised, so the card was restored and **still
      exists on the server**. The client must NOT converge these; the word
      should be retried on the next sync. (Routing graph failures here instead
      of ``not_found`` prevents iOS from permanently dropping a still-present
      card — see #720.)
    """

    def _delete(card: Any) -> None:
        cards_store.delete(card.id)
        if graph is not None:
            try:
                graph.cleanup_for_card(card.id, remove_blocked=True, source="manual")
            except Exception as exc:
                logger.error("Graph operation failed for card %s", card.id, exc_info=True)
                try:
                    cards_store.restore(card.id, notebook_id=card.notebook_id)
                except Exception:
                    logger.exception("Restore failed for card %s after graph error", card.id)
                raise _GraphOpFailed from exc

    succeeded, not_found, failed = _batch_apply(
        words, cards_store=cards_store, notebook_id=notebook_id, apply=_delete
    )
    deleted_words = [word for word, _ in succeeded]
    deleted_ids = [card.id for _, card in succeeded]

    # Evict embeddings for all committed-deleted cards in one batched save.
    # Best-effort: the cards are already gone, so a store failure must not
    # turn a successful delete into a request error.
    if embeddings is not None and deleted_ids:
        try:
            embeddings.remove_batch(deleted_ids)
        except Exception:
            logger.warning(
                "Failed to evict embeddings for %d deleted cards",
                len(deleted_ids), exc_info=True,
            )

    return {
        "deleted": len(deleted_words),
        "deleted_words": deleted_words,
        "not_found": not_found,
        "failed": failed,
    }


def batch_archive_vocab_words(
    words: list[str],
    *,
    archived: bool,
    cards_store: Any,
    graph: Any = None,
    notebook_id: str | None = None,
) -> dict[str, Any]:
    """Archive or unarchive multiple words in one call. Skips not-found words.

    Returns three disjoint buckets so the client can converge correctly:

    - ``updated_words`` — archive state successfully changed (card + graph).
    - ``not_found`` — lookup miss only: no such card on the server. The client
      may safely converge/remove these locally.
    - ``failed`` — graph cleanup/restore raised, so the archive state was rolled
      back and the card **still exists on the server** in its original state.
      The client must NOT converge these; the word should be retried on the next
      sync. (Routing graph failures here instead of ``not_found`` prevents iOS
      from permanently dropping/mislabelling a still-present card — see #720.)
    """

    def _archive(card: Any) -> None:
        cards_store.update(card.id, is_archived=archived)
        if graph is not None:
            try:
                if archived:
                    graph.cleanup_for_card(card.id, source="manual")
                else:
                    graph.restore_links_for(card.id, cards_store, source="manual")
            except Exception as exc:
                # Roll the card's archive state back to its original value so a
                # failed graph op never leaves card state and the response out of
                # sync (mirrors batch_delete_vocab_words).
                logger.error("Graph operation failed for card %s", card.id, exc_info=True)
                try:
                    cards_store.update(card.id, is_archived=not archived)
                except Exception:
                    logger.exception(
                        "Rollback failed for card %s after graph error", card.id
                    )
                raise _GraphOpFailed from exc

    succeeded, not_found, failed = _batch_apply(
        words, cards_store=cards_store, notebook_id=notebook_id, apply=_archive
    )
    updated_words = [word for word, _ in succeeded]

    return {
        "updated": len(updated_words),
        "updated_words": updated_words,
        "not_found": not_found,
        "failed": failed,
    }
