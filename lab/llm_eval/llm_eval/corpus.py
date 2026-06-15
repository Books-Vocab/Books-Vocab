"""Private corpus builder for historical KG user data.

Historical user data is treated as candidate material, not gold. Rows emitted
by this builder start as ``gold_status=unverified`` until a human reviewer
explicitly promotes them.
"""

from __future__ import annotations

import logging
import json
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_UID_RE = re.compile(r"\b\d{6}\.[A-Fa-f0-9]{32}\.[A-Za-z0-9_-]+\b")
_CARD_ID_RE = re.compile(r"\b[A-Fa-f0-9]{12}\b")
_EMAIL_RE = re.compile(r"\b[^@\s]+@[^@\s]+\.[^@\s]+\b")


def sanitize_context(text: str, *, max_chars: int = 320) -> str:
    """Redact stable identifiers and truncate context for private eval use."""
    clean = text or ""
    clean = _UID_RE.sub("[USER_ID]", clean)
    clean = _CARD_ID_RE.sub("[CARD_ID]", clean)
    clean = _EMAIL_RE.sub("[EMAIL]", clean)
    clean = clean.replace("\n", " ").strip()
    if len(clean) > max_chars:
        return clean[: max_chars - 1].rstrip() + "…"
    return clean


def build_private_corpus(
    dump_path: Path,
    output_dir: Path,
    *,
    limit: int | None = None,
    context_chars: int = 320,
) -> dict[str, Path]:
    """Build ignored JSONL candidate corpora from an exported user dump."""
    payload = json.loads(dump_path.read_text(encoding="utf-8"))
    rows = list(_iter_cards(payload.get("cards", []), context_chars=context_chars))
    if limit is not None:
        rows = rows[:limit]

    output_dir.mkdir(parents=True, exist_ok=True)
    outputs = {
        "translate_quick": output_dir / "translate_quick_candidates.jsonl",
        "translate_phrase": output_dir / "translate_phrase_candidates.jsonl",
        "translate_explain": output_dir / "translate_explain_candidates.jsonl",
    }
    _write_jsonl(outputs["translate_quick"], rows)
    _write_jsonl(
        outputs["translate_phrase"],
        [r for r in rows if r.get("pos") == "phr." and r.get("gold_queue_eligible") is True],
    )
    _write_jsonl(
        outputs["translate_explain"],
        sorted(
            [
                r for r in rows
                if r.get("review", {}).get("review_count", 0) > 0
                and r.get("gold_queue_eligible") is True
            ],
            key=lambda r: (
                r.get("review", {}).get("last_review_feedback", 1),
                -r.get("review", {}).get("review_count", 0),
            ),
        ),
    )
    return outputs


def _iter_cards(cards: Iterable[dict[str, Any]], *, context_chars: int) -> Iterable[dict[str, Any]]:
    for idx, card in enumerate(cards, start=1):
        raw_word = str(card.get("content") or "").strip()
        if not raw_word:
            continue
        context = _first_example(card.get("examples"))
        pii_risk = _pii_risk(" ".join([
            raw_word,
            context,
            str(card.get("meaning") or ""),
            str(card.get("note") or ""),
            str(card.get("root_form") or ""),
        ]))
        yield {
            "id": f"candidate_{idx:04d}",
            "word": sanitize_context(raw_word, max_chars=80),
            "context": sanitize_context(context, max_chars=context_chars),
            "source_lang": "en",
            "target_lang": "zh-Hant",
            "source": "historical_user_data",
            "gold_status": "unverified",
            "pii_risk": pii_risk,
            "gold_queue_eligible": pii_risk != "high",
            "pos": card.get("pos"),
            "weak_reference": {
                "translation": sanitize_context(str(card.get("meaning") or ""), max_chars=120),
                "pos": card.get("pos"),
                "root": sanitize_context(str(card.get("root_form") or ""), max_chars=80),
                "note": sanitize_context(str(card.get("note") or ""), max_chars=200),
            },
            "review": {
                "review_count": int(card.get("review_count") or 0),
                "last_review_feedback": _int_or_default(card.get("last_review_feedback"), -1),
            },
            "source_trace": {
                "ordinal": idx,
            },
        }


def _first_example(raw: Any) -> str:
    if isinstance(raw, list):
        return str(raw[0]) if raw else ""
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
            if isinstance(data, list) and data:
                return str(data[0])
        except json.JSONDecodeError:
            logger.debug("Failed to parse first example JSON in llm_eval corpus")
            return raw
    return ""


def _pii_risk(text: str) -> str:
    if _EMAIL_RE.search(text or "") or _UID_RE.search(text or ""):
        return "high"
    if _CARD_ID_RE.search(text or ""):
        return "medium"
    return "low"


def _int_or_default(value: Any, default: int) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        logger.warning("Invalid integer value %r in corpus; using default %s", value, default)
        return default


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )
