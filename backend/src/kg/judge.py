"""LLM-based narrow judgement for card relationships."""

from __future__ import annotations

import logging

from pydantic import BaseModel

from .graph import LinkKind
from .tracked_llm import TrackedLLM

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """Judge vocabulary relationship. Choose ONE type:
- contrasts_with: Genuinely opposite or contrasting meanings
  YES: unkempt/primped, hunkered/loped, meticulous/sloppy
  NO: bust/midriff (different body parts, not opposites)
- shares_usage: Used in similar contexts or fill similar grammatical roles
  YES: luster/resplendent, haggling/extorting, cacophony/clang
- not_applicable: No meaningful learning relationship

Write "reason" in 繁體中文 (1-2 sentences). Explain the relationship AND highlight the nuance/difference between the two words to help learners distinguish them.
Example: "都形容光彩奪目，但 luster 偏指物體表面的光澤質感，resplendent 則強調整體華麗壯觀的視覺效果。"

Respond JSON: {"link": "<type>", "confidence": <0.0-1.0>, "reason": "<繁體中文>"}"""

USER_TEMPLATE = """Word A: {word_a}
Meaning A: {meaning_a}

Word B: {word_b}
Meaning B: {meaning_b}

Determine the relationship type and your confidence (0.0-1.0)."""


class Judgement(BaseModel):
    """LLM judgement result."""

    link: str  # LinkKind value or "not_applicable"
    confidence: float
    reason: str


class Judge:
    """LLM-based relationship judge."""

    def __init__(self, llm: TrackedLLM, model: str = "gemini-2.5-flash-lite") -> None:
        self.llm = llm
        self.model = model

    def evaluate(
        self,
        word_a: str,
        meaning_a: str,
        word_b: str,
        meaning_b: str,
    ) -> Judgement | None:
        """Evaluate relationship between two words.

        Returns None if not_applicable or low confidence.
        """
        user_msg = USER_TEMPLATE.format(
            word_a=word_a,
            meaning_a=meaning_a,
            word_b=word_b,
            meaning_b=meaning_b,
        )

        resp = self.llm.chat(
            "judge",
            model=self.model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            response_format={"type": "json_object"},
            temperature=0.1,
        )

        content = resp.choices[0].message.content
        if not content:
            return None

        import json
        import re

        def _extract_json(raw: str) -> dict:
            # Try direct parse first
            try:
                return json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                pass
            # Regex: grab first {...} block
            m = re.search(r'\{[^{}]*\}', raw, re.DOTALL)
            if m:
                return json.loads(m.group())
            raise ValueError("No JSON object found")

        try:
            data = _extract_json(content)
        except (json.JSONDecodeError, ValueError, TypeError) as e:
            logger.warning("Failed to parse LLM judgement after cleanup (%s), retrying. Raw: %r", e, content)
            # Retry once
            resp2 = self.llm.chat(
                "judge",
                model=self.model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_msg},
                ],
                response_format={"type": "json_object"},
                temperature=0.1,
            )
            content2 = resp2.choices[0].message.content or ""
            try:
                data = _extract_json(content2)
            except (json.JSONDecodeError, ValueError, TypeError) as e2:
                logger.warning("Retry also failed (%s). Raw: %r", e2, content2)
                return None

        try:
            confidence = float(data.get("confidence", 0.0))
            link_val = data.get("link", "not_applicable")
            reason_val = data.get("reason", "")
        except (ValueError, TypeError) as e:
            logger.warning("Failed to extract fields from judgement (%s): %r", e, data)
            return None

        judgement = Judgement(
            link=link_val,
            confidence=confidence,
            reason=reason_val,
        )

        # Early exit conditions
        if judgement.link == "not_applicable":
            return None
        if judgement.confidence < 0.7:
            return None

        # Validate link kind
        try:
            LinkKind(judgement.link)
        except ValueError:
            return None

        return judgement


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
        user_msg = USER_TEMPLATE.format(
            word_a=word_a, meaning_a=meaning_a,
            word_b=word_b, meaning_b=meaning_b,
        )

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
