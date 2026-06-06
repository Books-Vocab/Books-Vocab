"""Human review queue generation for private candidate corpora."""

from __future__ import annotations

import json
import random
from collections.abc import Iterable
from pathlib import Path
from typing import Any

SUPPORTED_PROMPTS = {"translate_quick", "translate_explain"}


def build_gold_review_queue(
    candidates_path: Path,
    output_path: Path,
    *,
    prompt_name: str,
    limit: int = 50,
    seed: int | None = None,
) -> list[dict[str, Any]]:
    """Sample private candidates into a pending human review JSONL template."""
    if prompt_name not in SUPPORTED_PROMPTS:
        supported = ", ".join(sorted(SUPPORTED_PROMPTS))
        raise ValueError(f"unsupported prompt_name={prompt_name!r}; expected one of: {supported}")
    if limit < 1:
        raise ValueError("limit must be >= 1")

    candidates = [
        row
        for row in _read_jsonl(candidates_path)
        if row.get("gold_status") == "unverified"
        and row.get("gold_queue_eligible") is True
        and row.get("pii_risk") != "high"
    ]
    sampled = _sample(candidates, limit=limit, seed=seed)
    rows = [_to_review_row(row, prompt_name=prompt_name) for row in sampled]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    _write_jsonl(output_path, rows)
    return rows


def _sample(rows: list[dict[str, Any]], *, limit: int, seed: int | None) -> list[dict[str, Any]]:
    if len(rows) <= limit:
        return rows
    rng = random.Random(seed)
    indexed = list(enumerate(rows))
    rng.shuffle(indexed)
    selected = sorted(indexed[:limit], key=lambda item: item[0])
    return [row for _, row in selected]


def _to_review_row(candidate: dict[str, Any], *, prompt_name: str) -> dict[str, Any]:
    row = {
        "id": candidate.get("id"),
        "word": candidate.get("word", ""),
        "context": candidate.get("context", ""),
        "source_lang": candidate.get("source_lang", "en"),
        "target_lang": candidate.get("target_lang", "zh-Hant"),
        "source": candidate.get("source", "historical_user_data"),
        "gold_status": "unverified",
        "review_status": "pending",
        "pii_risk": candidate.get("pii_risk", "low"),
        "weak_reference": candidate.get("weak_reference", {}),
        "source_trace": candidate.get("source_trace", {}),
    }
    if prompt_name == "translate_quick":
        row.update(
            {
                "gold_translation": "",
                "gold_pos": "",
                "gold_root": "",
                "reviewer_notes": "",
            }
        )
        return row
    row.update(
        {
            "gold_keywords": [],
            "rubric_notes": "",
            "reviewer_notes": "",
        }
    )
    return row


def _read_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        data = json.loads(line)
        if not isinstance(data, dict):
            raise ValueError(f"{path}:{line_no} must contain a JSON object")
        yield data


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )
