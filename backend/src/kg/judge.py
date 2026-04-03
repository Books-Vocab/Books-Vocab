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

SELECTIVE_BATCH_SYSTEM_PROMPT = """Judge vocabulary relationships for the TARGET word.
You have {n} candidates but should select at most {max_links} with the MOST valuable learning relationships.

Selection criteria (in order):
1. Genuine contrasts — opposite or clearly different nuances of a similar concept
2. Strong usage pairs — consistently fill the same grammatical role or appear in the same contexts
3. REJECT vague connections — "both are body movements" or "both are adjectives" is NOT enough

For the best {max_links} candidates, respond:
{{"word": "<candidate>", "link": "contrasts_with" or "shares_usage", "confidence": <0.0-1.0>, "reason": "<繁體中文>"}}

For the rest, respond:
{{"word": "<candidate>", "link": "not_applicable", "confidence": 0.0, "reason": ""}}

Write each "reason" in 繁體中文 (1-2 sentences). Highlight the nuance/difference to help learners.
Respond as a JSON array, one object per candidate (in order)."""

BATCH_USER_TEMPLATE = """TARGET: {target_word} ({target_meaning})

Candidates:
{candidate_list}"""


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
                from . import judge_log
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
            from . import judge_log
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
