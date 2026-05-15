"""LLM-based relationship judge (batch mode)."""

from __future__ import annotations

import logging

from ..tracked_llm import TrackedLLM
from .models import MAX_BATCH_SIZE, Judgement
from .parsing import _parse_batch_response
from .prompts import BATCH_SYSTEM_PROMPT, BATCH_USER_TEMPLATE, SELECTIVE_BATCH_SYSTEM_PROMPT

logger = logging.getLogger(__name__)


class Judge:
    """LLM-based relationship judge (batch mode)."""

    def __init__(self, llm: TrackedLLM, model: str = "gemini-2.5-flash-lite",
                 *, user_id: str = "", notebook_id: str = "default") -> None:
        self.llm = llm
        self.model = model
        self.user_id = user_id
        self.notebook_id = notebook_id

    def evaluate_batch(
        self,
        target_word: str,
        target_meaning: str,
        candidates: list[tuple[str, str, str]],
        *,
        from_id: str = "",
        similarities: dict[str, float] | None = None,
        max_links: int | None = None,
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
                merged.update(self._call_batch(target_word, target_meaning, chunk, from_id=from_id, similarities=similarities, max_links=max_links))
            return merged

        return self._call_batch(target_word, target_meaning, candidates, from_id=from_id, similarities=similarities, max_links=max_links)

    def _call_batch(
        self,
        target_word: str,
        target_meaning: str,
        candidates: list[tuple[str, str, str]],
        *,
        from_id: str = "",
        similarities: dict[str, float] | None = None,
        max_links: int | None = None,
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

        if max_links is not None and len(candidates) >= 5:
            system_prompt = SELECTIVE_BATCH_SYSTEM_PROMPT.format(
                n=len(candidates), max_links=max_links,
            )
        else:
            system_prompt = BATCH_SYSTEM_PROMPT

        resp = self.llm.chat(
            "judge",
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_msg},
            ],
            response_format={"type": "json_object"},
            temperature=0.1,
        )

        content = resp.choices[0].message.content
        raw_decisions: list[dict] = []
        result = _parse_batch_response(content, candidates, raw_decisions=raw_decisions)
        if self.user_id and raw_decisions:
            try:
                from .. import judge_log
                for d in raw_decisions:
                    judge_log.record(
                        user_id=self.user_id, notebook_id=self.notebook_id,
                        from_id=from_id, to_id=d["to_id"],
                        similarity=(similarities or {}).get(d["to_id"]),
                        verdict=d["verdict"], confidence=d["confidence"],
                        accepted=bool(d["accepted"]),
                        reject_reason=d.get("reject_reason"),
                        reason=d.get("reason", ""), source="auto",
                    )
            except Exception:
                logger.warning("Failed to write judge_log", exc_info=True)
        return result

    def evaluate(
        self,
        word_a: str,
        meaning_a: str,
        word_b: str,
        meaning_b: str,
        *,
        from_id: str = "",
        to_id: str = "",
        similarity: float | None = None,
    ) -> Judgement | None:
        """Single-pair evaluate (backward compatible)."""
        key = to_id or "_single"
        sims = {key: similarity} if similarity is not None else None
        results = self.evaluate_batch(
            word_a, meaning_a,
            [(key, word_b, meaning_b)],
            from_id=from_id,
            similarities=sims,
        )
        return results.get(key)
