"""Vocabulary intake: add new entries with inflection derivation."""

from __future__ import annotations

import logging
import re
from typing import Any

from .api_models import VocabAddResponse, VocabEntry
from .exceptions import ConflictError, ValidationError
from .vocab_graph import embed_and_link_new_cards
from .vocab_shared import (
    MAX_BATCH_SIZE,
    _build_content_lookup,
    _clean_content,
    _normalize_word,
)

_BOLD = re.compile(r"\*\*(.+?)\*\*")


def _build_example(word: str, context: str, alternatives: list[str] | None = None) -> str:
    if not context:
        return ""
    # Strip pre-existing markdown bold markers to avoid double-wrapping
    context = _BOLD.sub(r"\1", context)
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
    # Build content→card dict once; eliminates per-duplicate find_by_content() DB
    # call. Shares the same normalized lookup as the batch CRUD paths
    # (cards.all() defaults to include_deleted=False, matching _build_content_lookup).
    existing_by_norm = _build_content_lookup(cards, notebook_id=notebook_id)
    existing = set(existing_by_norm.keys())

    # Legacy intake must never surface a dictionary card id to clients that
    # interpret every /api/vocab card as review-eligible. Fail the whole batch
    # before any writes; promotion is the only supported dictionary→learning
    # transition and preserves the card id explicitly.
    if any(
        getattr(existing_by_norm.get(_normalize_word(_clean_content(entry.word))), "card_role", "learning")
        == "dictionary"
        for entry in entries
    ):
        raise ConflictError("Existing dictionary card requires explicit promotion")

    created = 0
    skipped = 0
    # Response 對外的 duplicates/cardIds 用 client 送出的『原始』word 當 key,讓 iOS sync
    # 能以 entry.word 字面配對回 pending queue 並出列 —— 後端清洗(_clean_content)會改寫
    # word(strip 尾標點 / 首字小寫),若回傳清洗後的 key,client 拿原始 "chateau," 永遠查
    # 不到 "chateau" → 卡在佇列重送。內部 card_ids 仍以清洗後 word 為 key,供
    # embed_and_link_new_cards 查找(它會自行 _clean_content,見 vocab_graph.py)。
    duplicates: list[str] = []
    card_ids: dict[str, str] = {}           # cleaned word -> id（內部 embed/link 用）
    response_card_ids: dict[str, str] = {}   # 原始 entry.word -> id（對外 response 用）

    for entry in entries:
        word = _clean_content(entry.word)
        norm = _normalize_word(word)
        if norm in existing:
            skipped += 1
            duplicates.append(entry.word)
            existing_card = existing_by_norm.get(norm)
            if existing_card:
                card_ids[word] = existing_card.id
                response_card_ids[entry.word] = existing_card.id
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
            source=entry.source.model_dump_json() if entry.source else None,
        )
        card_ids[word] = card.id
        response_card_ids[entry.word] = card.id
        existing.add(norm)
        existing_by_norm[norm] = card
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
        cardIds=response_card_ids,
    )
