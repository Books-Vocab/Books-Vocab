from __future__ import annotations

import logging
import re
import unicodedata
from collections.abc import Callable
from datetime import datetime
from typing import Any

from fastapi import HTTPException

from .api_models import (
    CardLinkSummaryResponse,
    CardResponse,
    DailyReviewStatEntry,
    ReviewStateEntry,
    VocabAddResponse,
    VocabEntry,
)
from .user_store import parse_datetime
from .vocab_graph import embed_and_link_new_cards
from .vocab_graph import graph_links_payload as graph_links_payload  # re-export

MAX_BATCH_SIZE = 500
MAX_WORD_LENGTH = 200


def _normalize_word(word: str) -> str:
    return unicodedata.normalize("NFC", word).strip().lower()


def _clean_content(word: str) -> str:
    """Clean up word content for storage: strip trailing punctuation, lowercase first char."""
    word = word.strip().rstrip(".,;:!?")
    # Lowercase first char unless it's an acronym (all caps) or proper noun in a phrase
    if word and word[0].isupper() and not word.isupper() and " " not in word:
        word = word[0].lower() + word[1:]
    return word


_POS_CANONICAL = {"n": "n.", "v": "v.", "adj": "adj.", "adv": "adv.", "phr": "phr.", "conj": "conj.", "prep": "prep."}


def _normalize_pos(pos: str | None) -> str | None:
    if not pos:
        return pos
    p = pos.strip()
    return _POS_CANONICAL.get(p, p)


def _dt_to_iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    s = dt.isoformat()
    if not s.endswith("Z") and "+" not in s:
        s += "Z"
    return s


def build_links_by_kind(card_id: str, *, graph: Any, cards_by_id: dict[str, Any], link_kinds: list[Any], link_labels: dict[Any, str]) -> dict[str, list[CardLinkSummaryResponse]]:
    grouped: dict[str, list[CardLinkSummaryResponse]] = {}

    for link in graph.get_links_for(card_id):
        other_id = link.to_id if link.from_id == card_id else link.from_id
        other_card = cards_by_id.get(other_id)
        if not other_card or other_card.is_deleted or other_card.is_archived:
            continue

        kind_key = link.kind.value
        grouped.setdefault(kind_key, []).append(
            CardLinkSummaryResponse(
                id=link.id,
                cardId=other_card.id,
                word=other_card.content,
                kind=kind_key,
                label=link_labels.get(link.kind, link.kind.value),
                confidence=link.confidence,
                reason=link.reason,
            )
        )

    ordered: dict[str, list[CardLinkSummaryResponse]] = {}
    for kind in link_kinds:
        items = grouped.get(kind.value)
        if items:
            ordered[kind.value] = sorted(items, key=lambda item: _normalize_word(item.word))

    return ordered


def card_response(card: Any, *, graph: Any, cards_by_id: dict[str, Any], tier_getter: Callable[[str], Any], link_kinds: list[Any], link_labels: dict[Any, str]) -> CardResponse:
    tier = tier_getter(card.content)
    links_by_kind = {}
    if not card.is_deleted:
        links_by_kind = build_links_by_kind(
            card.id,
            graph=graph,
            cards_by_id=cards_by_id,
            link_kinds=link_kinds,
            link_labels=link_labels,
        )

    return CardResponse(
        id=card.id,
        content=card.content,
        meaning=card.meaning,
        pos=card.pos,
        difficulty=card.difficulty,
        difficultyTier=tier.tag,
        note=card.note,
        collocations=card.collocations or [],
        examples=card.examples,
        mode=card.mode,
        isDeleted=card.is_deleted,
        isArchived=card.is_archived,
        inflections=card.inflections or [],
        linksByKind=links_by_kind,
        notebookId=getattr(card, "notebook_id", "default"),
        updatedAt=_dt_to_iso(card.updated_at),
        reviewIntervalHours=card.review_interval_hours,
        nextReviewAt=_dt_to_iso(card.next_review_at),
        lastReviewedAt=_dt_to_iso(card.last_reviewed_at),
        reviewCount=card.review_count,
        lapseCount=card.lapse_count,
        reviewStreak=card.review_streak,
        lastReviewFeedback=card.last_review_feedback,
    )


def list_vocab_cards(*, since: str | None, limit: int = 5000, cards_store: Any, graph: Any, card_response_builder: Callable[[Any, Any, dict[str, Any]], CardResponse], notebook_id: str | None = None) -> list[CardResponse]:
    if since:
        parsed_since = parse_datetime(since)
        if parsed_since is None:
            raise HTTPException(400, "Invalid since timestamp format. Expected ISO 8601.")
        cards = cards_store.get_modified_since(parsed_since, notebook_id=notebook_id)
    else:
        cards = cards_store.all_limited(limit=limit, notebook_id=notebook_id)

    cards_by_id = cards_store.all_as_dict(include_deleted=True, notebook_id=notebook_id)
    return [card_response_builder(card, graph, cards_by_id) for card in cards]


def push_review_states(
    entries: list[ReviewStateEntry],
    *,
    cards_store: Any,
    logger: logging.Logger,
    notebook_id: str | None = None,
) -> dict[str, int]:
    """Merge client review states into server cards. Returns {updated, skipped}."""
    card_by_word: dict[str, Any] = {}
    for card in cards_store.all(notebook_id=notebook_id):
        card_by_word[_normalize_word(card.content)] = card

    updated = 0
    skipped = 0
    for entry in entries:
        card = card_by_word.get(_normalize_word(entry.word))
        if not card:
            skipped += 1
            continue

        client_last = parse_datetime(entry.last_reviewed_at)
        if client_last is None:
            skipped += 1
            continue

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
                cards_store.update(card.id, review_count=card.review_count, lapse_count=card.lapse_count)
                updated += 1
            else:
                skipped += 1
            continue

        # Client is newer — accept all fields
        client_next = parse_datetime(entry.next_review_at)
        cards_store.update(
            card.id,
            review_interval_hours=entry.review_interval_hours,
            next_review_at=client_next,
            last_reviewed_at=client_last,
            review_count=max(entry.review_count, card.review_count),
            lapse_count=max(entry.lapse_count, card.lapse_count),
            review_streak=entry.review_streak,
            last_review_feedback=entry.last_review_feedback,
        )
        updated += 1

    return {"updated": updated, "skipped": skipped}


def lookup_vocab_word(word: str, *, cards_store: Any, graph: Any, card_response_builder: Callable[[Any, Any, dict[str, Any]], CardResponse], notebook_id: str | None = None) -> CardResponse:
    if len(word) > MAX_WORD_LENGTH:
        raise HTTPException(status_code=422, detail="Word too long")
    card = cards_store.find_by_content(word, notebook_id=notebook_id)
    if not card:
        raise HTTPException(404, f"Word '{word}' not found")
    cards_by_id = cards_store.all_as_dict(include_deleted=True, notebook_id=notebook_id)
    return card_response_builder(card, graph, cards_by_id)


def archive_vocab_word(word: str, *, archived: bool, cards_store: Any, graph: Any = None, notebook_id: str | None = None) -> dict[str, str]:
    if len(word) > MAX_WORD_LENGTH:
        raise HTTPException(status_code=422, detail="Word too long")
    card = cards_store.find_by_content(word, notebook_id=notebook_id)
    if not card:
        raise HTTPException(404, f"Word '{word}' not found")
    cards_store.update(card.id, is_archived=archived)
    if graph is not None:
        if archived:
            graph.deprecate_links_for(card.id)
            graph.remove_candidates_for(card.id)
        else:
            graph.restore_links_for(card.id, cards_store)
    return {"word": word, "id": card.id, "archived": archived}


def delete_vocab_word(word: str, *, cards_store: Any, graph: Any = None, notebook_id: str | None = None) -> dict[str, str]:
    if len(word) > MAX_WORD_LENGTH:
        raise HTTPException(status_code=422, detail="Word too long")
    card = cards_store.find_by_content(word, notebook_id=notebook_id)
    if not card:
        raise HTTPException(404, f"Word '{word}' not found")
    cards_store.delete(card.id)
    if graph is not None:
        graph.deprecate_links_for(card.id)
        graph.remove_candidates_for(card.id)
    return {"deleted": word, "id": card.id}


def _build_example(word: str, context: str, alternatives: list[str] | None = None) -> str:
    if not context:
        return ""
    # Strip pre-existing markdown bold markers to avoid double-wrapping
    context = re.sub(r"\*\*(.+?)\*\*", r"\1", context)
    pattern = re.compile(re.escape(word), re.IGNORECASE)
    if pattern.search(context):
        return pattern.sub(f"**{word}**", context, count=1)
    if alternatives:
        for alt in alternatives:
            alt_pattern = re.compile(re.escape(alt), re.IGNORECASE)
            match = alt_pattern.search(context)
            if match:
                actual = match.group()
                return alt_pattern.sub(f"**{actual}**", context, count=1)
    return context


def _derive_inflections(word: str, root_form: str | None, *, logger: logging.Logger) -> tuple[str | None, list[str]]:
    inflections: list[str] = []
    root = None
    if " " in word:
        return root, inflections

    root = (root_form or "").strip().lower() or None
    if not root:
        return root, inflections

    try:
        from lemminflect import getAllInflections

        infl_map = getAllInflections(root)
        if not infl_map:
            logger.warning("lemminflect found no inflections for root '%s', falling back to '%s'", root, word)
            root = word.lower()
            infl_map = getAllInflections(root)
        seen = {word.lower()}
        for forms in infl_map.values():
            for form in forms:
                lowered = form.lower()
                if lowered not in seen:
                    inflections.append(lowered)
                    seen.add(lowered)
    except (ImportError, ValueError, KeyError, TypeError) as exc:
        logger.warning("lemminflect failed for root '%s': %s", root, exc)

    return root, inflections


def add_vocab_entries(
    entries: list[VocabEntry],
    *,
    user: dict[str, Any],
    cards: Any,
    embeddings: Any,
    graph: Any,
    logger: logging.Logger,
    notebook_id: str = "default",
) -> VocabAddResponse:
    if len(entries) > MAX_BATCH_SIZE:
        raise HTTPException(
            status_code=422,
            detail=f"Batch size {len(entries)} exceeds maximum of {MAX_BATCH_SIZE}",
        )
    existing = {_normalize_word(card.content) for card in cards.all(notebook_id=notebook_id)}

    created = 0
    skipped = 0
    duplicates: list[str] = []
    card_ids: dict[str, str] = {}

    for entry in entries:
        word = _clean_content(entry.word)
        if _normalize_word(word) in existing:
            skipped += 1
            duplicates.append(word)
            existing_card = cards.find_by_content(word, notebook_id=notebook_id)
            if existing_card:
                card_ids[word] = existing_card.id
            continue

        root, inflections = _derive_inflections(word, entry.root_form, logger=logger)
        alternatives = inflections + ([root] if root else [])
        example = _build_example(word, entry.context, alternatives=alternatives)

        card = cards.add(
            content=word,
            meaning=entry.translation.strip(),
            examples=[example] if example else [],
            root_form=root,
            inflections=inflections,
            notebook_id=notebook_id,
        )
        card_ids[word] = card.id
        existing.add(_normalize_word(word))
        created += 1

    if created > 0:
        embed_and_link_new_cards(
            cards=cards, embeddings=embeddings, graph=graph,
            card_ids=card_ids, entries=entries, logger=logger,
        )

    return VocabAddResponse(
        created=created,
        skipped=skipped,
        duplicates=duplicates,
        cardIds=card_ids,
    )


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
