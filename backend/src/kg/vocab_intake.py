"""Vocabulary intake: add new entries with inflection derivation."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from .api_models import VocabAddResponse, VocabEntry
from .exceptions import ValidationError
from .vocab_graph import embed_and_link_new_cards
from .vocab_shared import MAX_BATCH_SIZE, _clean_content, _normalize_word


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
        raise ValidationError(f"Batch size {len(entries)} exceeds maximum of {MAX_BATCH_SIZE}")
    all_cards = list(cards.all(notebook_id=notebook_id))
    existing = {_normalize_word(card.content) for card in all_cards}

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
            source=json.dumps(entry.source.model_dump()) if entry.source else None,
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
