"""Review state sync operations for per-card spaced-repetition fields."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from .api_models import ReviewStateEntry
from .user_store import parse_datetime
from .vocab_shared import _normalize_word


def _merge_card_review_state(
    entry: ReviewStateEntry,
    card: Any,
    client_last: datetime,
    *,
    logger: logging.Logger,
) -> dict | None:
    """Merge one client entry into one matched card; return batch_update kwargs.

    Returns ``None`` when nothing changed (caller counts it as skipped). Policy:

    - server newer-or-equal → only raise ``review_count`` / ``lapse_count`` to
      the client max (counts are monotonic and conflict-free).
    - client newer → accept the full client schedule.

    The server-newer branch mutates ``card`` in place so a card matched by
    multiple entries in the same batch sees its already-bumped counts.
    """
    server_last = parse_datetime(card.last_reviewed_at)
    if server_last and server_last >= client_last:
        changed = False
        if entry.review_count > card.review_count:
            card.review_count = entry.review_count
            changed = True
        if entry.lapse_count > card.lapse_count:
            card.lapse_count = entry.lapse_count
            changed = True
        if not changed:
            return None
        return dict(review_count=card.review_count, lapse_count=card.lapse_count)

    # Client is newer — accept all fields.
    client_next = parse_datetime(entry.next_review_at)
    # Observability: a present-but-unparseable next_review_at silently resets
    # this card's schedule to None below. Surface it so bad/stale client payloads
    # are diagnosable. Skip whitespace-only / empty values, which mean "not
    # meaningfully sent" rather than malformed.
    if client_next is None and str(entry.next_review_at).strip():
        logger.warning(
            "push_review_states: card %s has unparseable next_review_at %r; "
            "schedule reset to None",
            card.id,
            entry.next_review_at,
        )
    return dict(
        review_interval_hours=entry.review_interval_hours,
        next_review_at=client_next,
        last_reviewed_at=client_last,
        review_count=max(entry.review_count, card.review_count),
        lapse_count=max(entry.lapse_count, card.lapse_count),
        review_streak=entry.review_streak,
        last_review_feedback=entry.last_review_feedback,
    )


def push_review_states(
    entries: list[ReviewStateEntry],
    *,
    cards_store: Any,
    logger: logging.Logger,
    notebook_id: str | None = None,
) -> dict[str, int]:
    """Merge client review states into server cards. Returns {updated, skipped}.

    When an entry carries ``card_id``, only that exact card is matched —
    preventing cross-notebook pollution for same-word cards.
    Entries without ``card_id`` fall back to word-based matching (backward compat).
    """
    # Build lookup indices lazily: word-index only when needed.
    cards_by_word: dict[str, list[Any]] | None = None

    def _get_cards_by_word() -> dict[str, list[Any]]:
        nonlocal cards_by_word
        if cards_by_word is None:
            cards_by_word = {}
            for card in cards_store.all(notebook_id=notebook_id):
                if not getattr(card, "review_eligible", True):
                    continue
                cards_by_word.setdefault(_normalize_word(card.content), []).append(card)
        return cards_by_word

    updated = 0
    skipped = 0
    pending_updates: list[tuple[str, dict]] = []
    # Pre-fetch all cards with card_id in one batch to avoid N+1
    _card_ids_to_fetch = {e.card_id for e in entries if e.card_id}
    _cards_by_id = cards_store.get_batch(_card_ids_to_fetch) if _card_ids_to_fetch else {}
    for entry in entries:
        # Prefer card_id for precise matching; fall back to word matching.
        if entry.card_id:
            card = _cards_by_id.get(entry.card_id)
            eligible = (
                card is not None
                and not card.is_deleted
                and getattr(card, "review_eligible", True)
            )
            cards = [card] if eligible else []
        else:
            cards = _get_cards_by_word().get(_normalize_word(entry.word), [])
        if not cards:
            skipped += 1
            continue

        client_last = parse_datetime(entry.last_reviewed_at)
        if client_last is None:
            skipped += 1
            continue

        for card in cards:
            update = _merge_card_review_state(entry, card, client_last, logger=logger)
            if update is None:
                skipped += 1
            else:
                pending_updates.append((card.id, update))
                updated += 1

    if pending_updates:
        cards_store.batch_update(pending_updates)
    return {"updated": updated, "skipped": skipped}
