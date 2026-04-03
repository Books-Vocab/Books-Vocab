"""LLM-based narrow judgement for card relationships."""

from __future__ import annotations

import logging

from pydantic import BaseModel

from .graph import LinkKind
from .tracked_llm import TrackedLLM

logger = logging.getLogger(__name__)

class Judgement(BaseModel):
    """LLM judgement result."""

    link: str  # LinkKind value or "not_applicable"
    confidence: float
    reason: str


BATCH_SYSTEM_PROMPT = """Judge vocabulary relationships for the TARGET word against each CANDIDATE.
For each candidate, choose ONE type:
- contrasts_with: Genuinely opposite or contrasting meanings
- shares_usage: Used in similar contexts or fill similar grammatical roles
- not_applicable: No meaningful learning relationship

Write each "reason" in 繁體中文 (1-2 sentences). Highlight the nuance/difference to help learners.

Respond as a JSON array, one object per candidate (in order):
[{"word": "<candidate>", "link": "<type>", "confidence": <0.0-1.0>, "reason": "<繁體中文>"}, ...]"""

BATCH_USER_TEMPLATE = """TARGET: {target_word} ({target_meaning})

Candidates:
{candidate_list}"""


class Judge:
    """LLM-based relationship judge (batch mode)."""

    def __init__(self, llm: TrackedLLM, model: str = "gemini-2.5-flash-lite") -> None:
        self.llm = llm
        self.model = model

    def evaluate_batch(
        self,
        target_word: str,
        target_meaning: str,
        candidates: list[tuple[str, str, str]],  # [(card_id, word, meaning), ...]
    ) -> dict[str, Judgement | None]:
        """Evaluate target against multiple candidates in a single LLM call.

        Returns {card_id: Judgement | None} for each candidate.
        """
        if not candidates:
            return {}

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
        if not content:
            return {cid: None for cid, _, _ in candidates}

        import json

        try:
            data = json.loads(content)
        except (json.JSONDecodeError, ValueError):
            logger.warning("Failed to parse batch judgement. Raw: %r", content[:200])
            return {cid: None for cid, _, _ in candidates}

        # Handle {"results": [...]} or bare array or single object
        if isinstance(data, dict):
            for key in ("results", "judgements", "items", "candidates"):
                if key in data and isinstance(data[key], list):
                    data = data[key]
                    break
            else:
                # Single object (has link/confidence keys) → wrap in list
                if "link" in data:
                    data = [data]
                else:
                    data = []
        if not isinstance(data, list):
            data = []

        # Build word→item index from response; fallback to positional matching
        response_by_word: dict[str, dict] = {}
        response_by_pos: list[dict] = []
        for item in data:
            if isinstance(item, dict):
                w = item.get("word", "")
                if w:
                    response_by_word[w] = item
                response_by_pos.append(item)

        # Match response items back to candidate card_ids
        results: dict[str, Judgement | None] = {}
        for i, (cid, word, _) in enumerate(candidates):
            item = response_by_word.get(word)
            if not item and i < len(response_by_pos):
                item = response_by_pos[i]  # positional fallback
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

            results[cid] = Judgement(
                link=link_val,
                confidence=confidence,
                reason=reason_val,
            )

        return results

    # Keep single evaluate for backward compatibility
    def evaluate(
        self,
        word_a: str,
        meaning_a: str,
        word_b: str,
        meaning_b: str,
    ) -> Judgement | None:
        """Single-pair evaluate (legacy wrapper)."""
        results = self.evaluate_batch(
            word_a, meaning_a,
            [("_single", word_b, meaning_b)],
        )
        # evaluate_batch matches by word, not card_id
        if "_single" in results:
            return results["_single"]
        # Fallback: return the first non-None result if any
        for v in results.values():
            return v
        return None


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

        import json
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
