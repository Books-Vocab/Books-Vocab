"""LLM-based narrow judgement for card relationships."""

from __future__ import annotations

import logging

from openai import OpenAI
from pydantic import BaseModel

from .graph import LinkKind

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

    def __init__(self, client: OpenAI, model: str = "gemini-2.5-flash-lite") -> None:
        self.client = client
        self.model = model

    def evaluate(
        self,
        word_a: str,
        meaning_a: str,
        word_b: str,
        meaning_b: str,
        user_id: str | None = None,
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

        resp = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            response_format={"type": "json_object"},
            temperature=0.1,
        )

        if user_id and resp.usage:
            from .token_tracker import record
            record(user_id, "judge",
                   getattr(resp.usage, "prompt_tokens", 0) or 0,
                   getattr(resp.usage, "completion_tokens", 0) or 0)

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
            resp2 = self.client.chat.completions.create(
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
