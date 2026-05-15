"""LLM judge for user-initiated links (separate prompt, never returns None)."""

from __future__ import annotations

import json
import logging

from ..tracked_llm import TrackedLLM
from .models import Judgement
from .prompts import MANUAL_LINK_SYSTEM_PROMPT

logger = logging.getLogger(__name__)


class ManualLinkJudge:
    """LLM judge for user-initiated links. Never returns None."""

    def __init__(self, llm: TrackedLLM, model: str = "gemini-2.5-flash-lite",
                 *, user_id: str = "", notebook_id: str = "default") -> None:
        self.llm = llm
        self.model = model
        self.user_id = user_id
        self.notebook_id = notebook_id

    def _log(self, *, from_id: str, to_id: str, judgement: Judgement) -> None:
        if not self.user_id:
            return
        try:
            from .. import judge_log
            judge_log.record(
                user_id=self.user_id, notebook_id=self.notebook_id,
                from_id=from_id, to_id=to_id, similarity=None,
                verdict=judgement.link, confidence=judgement.confidence,
                accepted=True, reject_reason=None,
                reason=judgement.reason, source="manual",
            )
        except Exception:
            logger.warning("Failed to write judge_log (manual)", exc_info=True)

    def evaluate(
        self,
        word_a: str,
        meaning_a: str,
        word_b: str,
        meaning_b: str,
        *,
        from_id: str = "",
        to_id: str = "",
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
                    j = Judgement(link="shares_usage", confidence=1.0, reason="使用者認為這兩個詞相關。")
                    self._log(from_id=from_id, to_id=to_id, judgement=j)
                    return j
            else:
                j = Judgement(link="shares_usage", confidence=1.0, reason="使用者認為這兩個詞相關。")
                self._log(from_id=from_id, to_id=to_id, judgement=j)
                return j

        link_val = data.get("link", "shares_usage")
        reason_val = data.get("reason", "使用者認為這兩個詞相關。")

        if link_val not in ("contrasts_with", "shares_usage"):
            link_val = "shares_usage"

        j = Judgement(link=link_val, confidence=1.0, reason=reason_val)
        self._log(from_id=from_id, to_id=to_id, judgement=j)
        return j
