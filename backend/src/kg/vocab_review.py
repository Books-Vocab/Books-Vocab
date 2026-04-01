"""Review state sync operations: push/pull review states and daily stats."""

from __future__ import annotations

import logging
from typing import Any

from .api_models import DailyReviewStatEntry, ReviewStateEntry
from .user_store import parse_datetime
from .vocab_shared import _normalize_word


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
            cards = [card] if card and not card.is_deleted else []
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
            server_last = parse_datetime(card.last_reviewed_at)
            if server_last and server_last >= client_last:
                # Server is newer or equal — only take max counts
                changed = False
                if entry.review_count > card.review_count:
                    card.review_count = entry.review_count
                    changed = True
                if entry.lapse_count > card.lapse_count:
                    card.lapse_count = entry.lapse_count
                    changed = True
                if changed:
                    pending_updates.append((card.id, dict(review_count=card.review_count, lapse_count=card.lapse_count)))
                    updated += 1
                else:
                    skipped += 1
                continue

            # Client is newer — accept all fields
            client_next = parse_datetime(entry.next_review_at)
            pending_updates.append((card.id, dict(
                review_interval_hours=entry.review_interval_hours,
                next_review_at=client_next,
                last_reviewed_at=client_last,
                review_count=max(entry.review_count, card.review_count),
                lapse_count=max(entry.lapse_count, card.lapse_count),
                review_streak=entry.review_streak,
                last_review_feedback=entry.last_review_feedback,
            )))
            updated += 1

    if pending_updates:
        cards_store.batch_update(pending_updates)
    return {"updated": updated, "skipped": skipped}


def push_daily_review_stats(
    entries: list[DailyReviewStatEntry],
    *,
    stats_store: Any,
    logger: logging.Logger,
) -> dict[str, int]:
    """Merge client daily review stats into server. Returns {upserted}."""
    upserted = 0
    for entry in entries:
        stats_store.upsert(
            day_key=entry.day_key,
            total=entry.total,
            remembered=entry.remembered,
            forgot=entry.forgot,
        )
        upserted += 1
    logger.info("push_daily_review_stats: upserted %d entries", upserted)
    return {"upserted": upserted}


def pull_daily_review_stats(
    *,
    since: str | None,
    stats_store: Any,
) -> list[DailyReviewStatEntry]:
    """Return all daily review stats, optionally filtered by since day_key."""
    if since:
        stats = stats_store.get_since(since)
    else:
        stats = stats_store.all()
    return [
        DailyReviewStatEntry(
            day_key=s.day_key,
            total=s.total,
            remembered=s.remembered,
            forgot=s.forgot,
        )
        for s in stats
    ]
