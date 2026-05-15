"""Batch judgement response parsing."""

from __future__ import annotations

import json
import logging

from ..graph import LinkKind
from .models import Judgement

logger = logging.getLogger(__name__)


def _parse_batch_response(
    content: str | None,
    candidates: list[tuple[str, str, str]],
    *,
    raw_decisions: list[dict] | None = None,
) -> dict[str, Judgement | None]:
    """Parse LLM batch response, matching back to candidate card_ids.

    Uses card_id-keyed matching (not word-based) to avoid duplicate word collisions.
    Response items matched by position (array order matches candidate order).
    """
    if not content:
        if raw_decisions is not None:
            for cid, _, _ in candidates:
                raw_decisions.append({"to_id": cid, "verdict": "parse_error", "confidence": 0.0, "accepted": 0, "reject_reason": "parse_error", "reason": ""})
        return {cid: None for cid, _, _ in candidates}

    try:
        data = json.loads(content)
    except (json.JSONDecodeError, ValueError):
        logger.warning("Failed to parse batch judgement. Raw: %r", content[:200])
        if raw_decisions is not None:
            for cid, _, _ in candidates:
                raw_decisions.append({"to_id": cid, "verdict": "parse_error", "confidence": 0.0, "accepted": 0, "reject_reason": "parse_error", "reason": ""})
        return {cid: None for cid, _, _ in candidates}

    # Unwrap: {"results": [...]} or bare array or single object
    if isinstance(data, dict):
        for key in ("results", "judgements", "items", "candidates"):
            if key in data and isinstance(data[key], list):
                data = data[key]
                break
        else:
            if "link" in data:
                data = [data]
            else:
                data = []
    if not isinstance(data, list):
        data = []

    # Build word→item fallback index for reorder detection
    _word_index: dict[str, dict] = {}
    for item in data:
        if isinstance(item, dict):
            w = item.get("word", "")
            if w:
                _word_index[w] = item

    # Match by position first; cross-check word, fallback to word-keyed lookup
    results: dict[str, Judgement | None] = {}
    for i, (cid, word, _) in enumerate(candidates):
        item = None
        if i < len(data) and isinstance(data[i], dict):
            pos_item = data[i]
            pos_word = pos_item.get("word", "")
            if not pos_word or pos_word == word:
                item = pos_item  # positional match confirmed
            else:
                # Positional mismatch — LLM reordered, use word-keyed fallback
                item = _word_index.get(word)
                if item:
                    logger.debug("Judge reorder detected: pos %d expected '%s' got '%s', used word fallback", i, word, pos_word)
        else:
            item = _word_index.get(word)  # beyond response length, try word lookup

        if not item:
            if raw_decisions is not None:
                raw_decisions.append({"to_id": cid, "verdict": "no_response", "confidence": 0.0, "accepted": 0, "reject_reason": "no_response", "reason": ""})
            results[cid] = None
            continue

        try:
            link_val = item.get("link", "not_applicable")
            confidence = float(item.get("confidence", 0.0))
            reason_val = item.get("reason", "")
        except (ValueError, TypeError):
            if raw_decisions is not None:
                raw_decisions.append({"to_id": cid, "verdict": "parse_error", "confidence": 0.0, "accepted": 0, "reject_reason": "parse_error", "reason": ""})
            results[cid] = None
            continue

        if link_val == "not_applicable" or confidence < 0.7:
            reject = "not_applicable" if link_val == "not_applicable" else "low_confidence"
            if raw_decisions is not None:
                raw_decisions.append({"to_id": cid, "verdict": link_val, "confidence": confidence, "accepted": 0, "reject_reason": reject, "reason": reason_val})
            results[cid] = None
            continue

        try:
            LinkKind(link_val)
        except ValueError:
            if raw_decisions is not None:
                raw_decisions.append({"to_id": cid, "verdict": link_val, "confidence": confidence, "accepted": 0, "reject_reason": "invalid_kind", "reason": reason_val})
            results[cid] = None
            continue

        if raw_decisions is not None:
            raw_decisions.append({"to_id": cid, "verdict": link_val, "confidence": confidence, "accepted": 1, "reject_reason": None, "reason": reason_val})
        results[cid] = Judgement(link=link_val, confidence=confidence, reason=reason_val)

    # Any candidates beyond response length → None
    for cid, _, _ in candidates[len(data):]:
        if raw_decisions is not None and cid not in {d["to_id"] for d in raw_decisions}:
            raw_decisions.append({"to_id": cid, "verdict": "no_response", "confidence": 0.0, "accepted": 0, "reject_reason": "no_response", "reason": ""})
        results.setdefault(cid, None)

    return results
