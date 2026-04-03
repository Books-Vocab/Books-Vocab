"""LLM-based narrow judgement for card relationships."""

from __future__ import annotations

import json
import logging

from pydantic import BaseModel

from .graph import LinkKind
from .tracked_llm import TrackedLLM

logger = logging.getLogger(__name__)

MAX_BATCH_SIZE = 15  # 避免超大 batch 導致 token 爆炸或回應截斷


class Judgement(BaseModel):
    """LLM judgement result."""

    link: str  # LinkKind value or "not_applicable"
    confidence: float
    reason: str


BATCH_SYSTEM_PROMPT = """Judge vocabulary relationships for the TARGET word against each CANDIDATE.
For each candidate, choose ONE type:
- contrasts_with: Genuinely opposite or contrasting meanings
  YES: unkempt/primped, hunkered/loped, meticulous/sloppy
  NO: bust/midriff (different body parts, not opposites)
- shares_usage: Used in similar contexts or fill similar grammatical roles
  YES: luster/resplendent, haggling/extorting, cacophony/clang
- not_applicable: No meaningful learning relationship

Write each "reason" in 繁體中文 (1-2 sentences). Highlight the nuance/difference to help learners.

Respond as a JSON array, one object per candidate (in order):
[{"word": "<candidate>", "link": "<type>", "confidence": <0.0-1.0>, "reason": "<繁體中文>"}, ...]"""

BATCH_USER_TEMPLATE = """TARGET: {target_word} ({target_meaning})

Candidates:
{candidate_list}"""


def _parse_batch_response(
    content: str | None,
    candidates: list[tuple[str, str, str]],
) -> dict[str, Judgement | None]:
    """Parse LLM batch response, matching back to candidate card_ids.

    Uses card_id-keyed matching (not word-based) to avoid duplicate word collisions.
    Response items matched by position (array order matches candidate order).
    """
    if not content:
        return {cid: None for cid, _, _ in candidates}

    try:
        data = json.loads(content)
    except (json.JSONDecodeError, ValueError):
        logger.warning("Failed to parse batch judgement. Raw: %r", content[:200])
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
            results[cid] = None
            continue

        try:
            link_val = item.get("link", "not_applicable")
            confidence = float(item.get("confidence", 0.0))
            reason_val = item.get("reason", "")
        except (ValueError, TypeError):
            results[cid] = None
            continue

        if link_val == "not_applicable" or confidence < 0.7:
            results[cid] = None
            continue

        try:
            LinkKind(link_val)
        except ValueError:
            results[cid] = None
            continue

        results[cid] = Judgement(link=link_val, confidence=confidence, reason=reason_val)

    # Any candidates beyond response length → None
    for cid, _, _ in candidates[len(data):]:
        results.setdefault(cid, None)

    return results


class Judge:
    """LLM-based relationship judge (batch mode)."""

    def __init__(self, llm: TrackedLLM, model: str = "gemini-2.5-flash-lite") -> None:
        self.llm = llm
        self.model = model

    def evaluate_batch(
        self,
        target_word: str,
        target_meaning: str,
        candidates: list[tuple[str, str, str]],
    ) -> dict[str, Judgement | None]:
        """Evaluate target against multiple candidates in a single LLM call.

        Splits into chunks of MAX_BATCH_SIZE if needed.
        Returns {card_id: Judgement | None} for each candidate.
        """
        if not candidates:
            return {}

        # Split large batches
        if len(candidates) > MAX_BATCH_SIZE:
            merged: dict[str, Judgement | None] = {}
            for start in range(0, len(candidates), MAX_BATCH_SIZE):
                chunk = candidates[start:start + MAX_BATCH_SIZE]
                merged.update(self._call_batch(target_word, target_meaning, chunk))
            return merged

        return self._call_batch(target_word, target_meaning, candidates)

    def _call_batch(
        self,
        target_word: str,
        target_meaning: str,
        candidates: list[tuple[str, str, str]],
    ) -> dict[str, Judgement | None]:
        """Single LLM call for a batch of candidates."""
        cand_lines = "\n".join(
            f"{i+1}. {word} ({meaning})"
            for i, (_, word, meaning) in enumerate(candidates)
        )
        user_msg = BATCH_USER_TEMPLATE.format(
            target_word=target_word,
            target_meaning=target_meaning,
            candidate_list=cand_lines,
        )

        resp = self.llm.chat(
            "judge",
            model=self.model,
            messages=[
                {"role": "system", "content": BATCH_SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            response_format={"type": "json_object"},
            temperature=0.1,
        )

        content = resp.choices[0].message.content
        return _parse_batch_response(content, candidates)

    def evaluate(
        self,
        word_a: str,
        meaning_a: str,
        word_b: str,
        meaning_b: str,
    ) -> Judgement | None:
        """Single-pair evaluate (backward compatible)."""
        results = self.evaluate_batch(
            word_a, meaning_a,
            [("_single", word_b, meaning_b)],
        )
        return results.get("_single")


# ── ManualLinkJudge (unchanged, separate prompt) ─────────────

MANUAL_LINK_SYSTEM_PROMPT = """The user believes these two vocabulary words are related. Your job is to classify the relationship and explain it.

Choose ONE type:
- contrasts_with: The words have similar or overlapping meanings but differ in nuance, tone, formality, or usage scope
- shares_usage: The words appear in similar contexts, share thematic domains, or complement each other in usage

Do NOT return "not_applicable" — the user has decided these words are related. Find and articulate the connection.

Write "reason" in 繁體中文 (1-2 sentences). Explain the relationship AND highlight the nuance/difference between the two words to help learners distinguish them.

Respond JSON: {"link": "<type>", "confidence": <0.0-1.0>, "reason": "<繁體中文>"}"""


class ManualLinkJudge:
    """LLM judge for user-initiated links. Never returns None."""

    def __init__(self, llm: TrackedLLM, model: str = "gemini-2.5-flash-lite") -> None:
        self.llm = llm
        self.model = model

    def evaluate(
        self,
        word_a: str,
        meaning_a: str,
        word_b: str,
        meaning_b: str,
    ) -> Judgement:
        user_msg = f"Word A: {word_a}\nMeaning A: {meaning_a}\n\nWord B: {word_b}\nMeaning B: {meaning_b}\n\nDetermine the relationship type and your confidence (0.0-1.0)."

        resp = self.llm.chat(
            "manual_link_judge",
            model=self.model,
            messages=[
                {"role": "system", "content": MANUAL_LINK_SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            response_format={"type": "json_object"},
            temperature=0.1,
        )

        content = resp.choices[0].message.content or ""

        import re

        try:
            data = json.loads(content)
        except (json.JSONDecodeError, ValueError):
            m = re.search(r'\{[^{}]*\}', content, re.DOTALL)
            if m:
                try:
                    data = json.loads(m.group())
                except (json.JSONDecodeError, ValueError):
                    return Judgement(link="shares_usage", confidence=1.0, reason="使用者認為這兩個詞相關。")
            else:
                return Judgement(link="shares_usage", confidence=1.0, reason="使用者認為這兩個詞相關。")

        link_val = data.get("link", "shares_usage")
        reason_val = data.get("reason", "使用者認為這兩個詞相關。")

        if link_val not in ("contrasts_with", "shares_usage"):
            link_val = "shares_usage"

        return Judgement(link=link_val, confidence=1.0, reason=reason_val)
