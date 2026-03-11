from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any, Callable

from fastapi import HTTPException

from .api_models import CardLinkSummaryResponse, CardResponse, GraphLinkResponse, ReviewStateEntry, VocabAddResponse, VocabEntry
from .user_store import parse_datetime


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
        if not other_card or other_card.is_deleted:
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
            ordered[kind.value] = sorted(items, key=lambda item: item.word.lower())

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
        examples=card.examples,
        mode=card.mode,
        isDeleted=card.is_deleted,
        isArchived=card.is_archived,
        pronunciation=card.pronunciation,
        inflections=card.inflections or [],
        linksByKind=links_by_kind,
        reviewIntervalHours=card.review_interval_hours,
        nextReviewAt=_dt_to_iso(card.next_review_at),
        lastReviewedAt=_dt_to_iso(card.last_reviewed_at),
        reviewCount=card.review_count,
        lapseCount=card.lapse_count,
        reviewStreak=card.review_streak,
        lastReviewFeedback=card.last_review_feedback,
    )


def list_vocab_cards(*, since: str | None, cards_store: Any, graph: Any, card_response_builder: Callable[[Any, Any, dict[str, Any]], CardResponse]) -> list[CardResponse]:
    if since:
        parsed_since = parse_datetime(since)
        if parsed_since is None:
            raise HTTPException(400, "Invalid since timestamp format. Expected ISO 8601.")
        cards = cards_store.get_modified_since(parsed_since)
    else:
        cards = list(cards_store.all())

    cards_by_id = {card.id: card for card in cards_store.all(include_deleted=True)}
    return [card_response_builder(card, graph, cards_by_id) for card in cards]


def push_review_states(
    entries: list[ReviewStateEntry],
    *,
    cards_store: Any,
    logger: logging.Logger,
) -> dict[str, int]:
    """Merge client review states into server cards. Returns {updated, skipped}."""
    card_by_word: dict[str, Any] = {}
    for card in cards_store.all():
        card_by_word[card.content.lower()] = card

    updated = 0
    skipped = 0
    for entry in entries:
        card = card_by_word.get(entry.word.lower())
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


def lookup_vocab_word(word: str, *, cards_store: Any, graph: Any, card_response_builder: Callable[[Any, Any, dict[str, Any]], CardResponse]) -> CardResponse:
    cards_by_id = {card.id: card for card in cards_store.all(include_deleted=True)}
    for card in cards_store.all():
        if card.content.lower() == word.lower():
            return card_response_builder(card, graph, cards_by_id)
    raise HTTPException(404, f"Word '{word}' not found")


def archive_vocab_word(word: str, *, archived: bool, cards_store: Any) -> dict[str, str]:
    for card in cards_store.all():
        if card.content.lower() == word.lower():
            cards_store.update(card.id, is_archived=archived)
            return {"word": word, "id": card.id, "archived": archived}
    raise HTTPException(404, f"Word '{word}' not found")


def delete_vocab_word(word: str, *, cards_store: Any) -> dict[str, str]:
    for card in cards_store.all():
        if card.content.lower() == word.lower():
            card_id = card.id
            cards_store.delete(card_id)
            return {"deleted": word, "id": card_id}
    raise HTTPException(404, f"Word '{word}' not found")


def graph_links_payload(*, graph: Any) -> list[GraphLinkResponse]:
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


def _build_example(word: str, context: str) -> str:
    if not context:
        return ""
    pattern = re.compile(re.escape(word), re.IGNORECASE)
    if pattern.search(context):
        return pattern.sub(f"**{word}**", context, count=1)
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
) -> VocabAddResponse:
    existing = {card.content.lower() for card in cards.all()}

    created = 0
    skipped = 0
    duplicates: list[str] = []
    card_ids: dict[str, str] = {}

    for entry in entries:
        word = entry.word.strip()
        if word.lower() in existing:
            skipped += 1
            duplicates.append(word)
            for card in cards.all():
                if card.content.lower() == word.lower():
                    card_ids[word] = card.id
                    break
            continue

        example = _build_example(word, entry.context)
        root, inflections = _derive_inflections(word, entry.root_form, logger=logger)

        card = cards.add(
            content=word,
            meaning=entry.translation.strip(),
            examples=[example] if example else [],
            root_form=root,
            inflections=inflections,
            pronunciation=entry.pronunciation,
        )
        card_ids[word] = card.id
        existing.add(word.lower())
        created += 1

    if created > 0:
        for entry in entries:
            word = entry.word.strip()
            card_id = card_ids.get(word)
            card = cards.get(card_id) if card_id else None
            if card and not embeddings.has(card.id):
                try:
                    embeddings.add(card.id, card.embed_text())
                    similar = embeddings.find_similar(card.id, k=3)
                    for other_id, score in similar:
                        if score > 0.655:
                            graph.add_candidate(card.id, other_id, score)
                except (OSError, ValueError) as exc:
                    logger.warning("Failed to generate embedding for '%s': %s", word, exc)
                    continue

    return VocabAddResponse(
        created=created,
        skipped=skipped,
        duplicates=duplicates,
        cardIds=card_ids,
    )
