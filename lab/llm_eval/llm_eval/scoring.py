"""Rule-based FORMAT scoring for LLM eval outputs.

Scope is deliberately narrow: only objective, mechanical checks that verify the
output obeys the prompt's own stated format rules (valid JSON, schema keys,
Traditional-Chinese-only, POS suffix conventions, valid link kinds / confidence
ranges). These are cheap first-pass gates.

Translation/semantic QUALITY is NOT scored here — synonym-vs-synonym and
nuance judgements are done by agent review of the eval report (see the `review`
CLI command), not by brittle gold exact-match.
"""

from __future__ import annotations

import logging
import math
from typing import Any, Protocol

logger = logging.getLogger("llm_eval")

# ── OpenCC instance for simplified→traditional detection ──
# Using opencc-python-reimplemented (pure Python, no native deps).
try:
    import opencc
    _S2T_CONVERTER = opencc.OpenCC("s2t")
except Exception:
    _S2T_CONVERTER = None

# POS suffix rules
_POS_SUFFIX_MAP: dict[str, str] = {
    "adj.": "的",
    "adv.": "地",
}

# Valid POS values
_VALID_POS: set[str] = {"n.", "v.", "adj.", "adv.", "conj.", "prep.", "phr."}

# Valid judge link kinds
_VALID_LINK_KINDS: set[str] = {"contrasts_with", "shares_usage", "not_applicable"}


class Scorer(Protocol):
    """A scorer evaluates one parsed output and returns a dict of scores."""

    def score(self, parsed: Any, sample: dict[str, Any]) -> dict[str, float]:
        ...


class JsonSchemaScorer:
    """Check JSON parseability and required keys."""

    def __init__(self, required_keys: list[str], *, allow_list: bool = False) -> None:
        self.required_keys = required_keys
        self.allow_list = allow_list

    def score(self, parsed: Any, sample: dict[str, Any]) -> dict[str, float]:
        result: dict[str, float] = {"json_valid": 1.0 if parsed else 0.0}
        if not parsed:
            result["schema_conform"] = 0.0
            return result
        if isinstance(parsed, list):
            if not self.allow_list:
                result["schema_conform"] = 0.0
                return result
            if any(not isinstance(item, dict) for item in parsed):
                result["schema_conform"] = 0.0
                return result
            items = [item for item in parsed if isinstance(item, dict)]
            if not items:
                result["schema_conform"] = 0.0
                return result
            missing = [
                key
                for item in items
                for key in self.required_keys
                if key not in item
            ]
            result["schema_conform"] = 1.0 if not missing else 0.0
            return result
        if not isinstance(parsed, dict):
            result["schema_conform"] = 0.0
            return result
        missing = [k for k in self.required_keys if k not in parsed]
        result["schema_conform"] = 1.0 if not missing else 0.0
        return result


class TranslateQualityScorer:
    """KG-specific translate_quick quality checks."""

    def score(self, parsed: Any, sample: dict[str, Any]) -> dict[str, float]:
        result: dict[str, float] = {}
        if not parsed or not isinstance(parsed, dict):
            result["trad_chinese"] = 0.0
            result["pos_correct"] = 0.0
            result["lemma_ok"] = 0.0
            return result

        # Traditional Chinese check
        t_val = str(parsed.get("t", ""))
        result["trad_chinese"] = 0.0 if _contains_simplified(t_val) else 1.0

        # POS suffix check
        pos = str(parsed.get("p", "")).strip().lower()
        result["pos_correct"] = 0.0
        if pos in _VALID_POS:
            expected_suffix = _POS_SUFFIX_MAP.get(pos)
            if expected_suffix:
                result["pos_correct"] = 1.0 if t_val.endswith(expected_suffix) else 0.0
            else:
                result["pos_correct"] = 1.0  # n./v./conj./prep. have no suffix rule

        # Lemma sanity check (not a full dictionary validation — just heuristics)
        r_val = str(parsed.get("r", "")).strip()
        result["lemma_ok"] = _check_lemma(r_val, sample.get("word", ""))

        return result


class JudgeBatchScorer:
    """Judge batch output quality checks."""

    def score(self, parsed: Any, sample: dict[str, Any]) -> dict[str, float]:
        result: dict[str, float] = {}
        if not parsed or not isinstance(parsed, list):
            result["link_valid"] = 0.0
            result["confidence_range"] = 0.0
            result["reason_trad"] = 0.0
            return result

        link_valid = 1.0
        confidence_range = 1.0
        reason_trad = 1.0

        for item in parsed:
            if not isinstance(item, dict):
                continue
            link = item.get("link", "")
            if link not in _VALID_LINK_KINDS:
                link_valid = 0.0
            conf = item.get("confidence", 0.0)
            try:
                c = float(conf)
                if not math.isfinite(c) or c < 0 or c > 1:
                    confidence_range = 0.0
            except (ValueError, TypeError):
                confidence_range = 0.0
            reason = str(item.get("reason", ""))
            if reason and _contains_simplified(reason):
                reason_trad = 0.0

        result["link_valid"] = link_valid
        result["confidence_range"] = confidence_range
        result["reason_trad"] = reason_trad
        return result


class EnrichScorer:
    """Enrichment output quality checks."""

    def score(self, parsed: Any, sample: dict[str, Any]) -> dict[str, float]:
        result: dict[str, float] = {}
        if not parsed or not isinstance(parsed, list):
            result["pos_valid"] = 0.0
            result["note_trad"] = 0.0
            result["meaning_fix_trad"] = 0.0
            return result

        pos_valid = 1.0
        note_trad = 1.0
        meaning_fix_trad = 1.0

        for item in parsed:
            if not isinstance(item, dict):
                continue
            pos = item.get("pos", "")
            if pos and pos not in _VALID_POS:
                pos_valid = 0.0
            note = str(item.get("note", ""))
            if note and _contains_simplified(note):
                note_trad = 0.0
            mf = item.get("meaning_fix")
            if mf is not None:
                mf_str = str(mf)
                if _contains_simplified(mf_str):
                    meaning_fix_trad = 0.0
                # Check adj./adv. suffix
                if pos == "adj." and not mf_str.endswith("的"):
                    meaning_fix_trad = 0.0
                if pos == "adv." and not mf_str.endswith("地"):
                    meaning_fix_trad = 0.0

        result["pos_valid"] = pos_valid
        result["note_trad"] = note_trad
        result["meaning_fix_trad"] = meaning_fix_trad
        return result


# ── scoring dispatcher ──

_PROMPT_SCORERS: dict[str, list[Scorer]] = {
    "translate_quick": [
        JsonSchemaScorer(["t", "p", "r"]),
        TranslateQualityScorer(),
    ],
    "translate_phrase": [
        JsonSchemaScorer(["t"]),
    ],
    "translate_explain": [
        JsonSchemaScorer(["e"]),
    ],
    "judge_batch": [
        JsonSchemaScorer(["word", "link", "confidence", "reason"], allow_list=True),
        JudgeBatchScorer(),
    ],
    "judge_selective": [
        JsonSchemaScorer(["word", "link", "confidence", "reason"], allow_list=True),
        JudgeBatchScorer(),
    ],
    "judge_manual": [
        JsonSchemaScorer(["link", "confidence", "reason"]),
    ],
    "enrich": [
        JsonSchemaScorer(["word", "pos", "note", "collocations", "meaning_fix"], allow_list=True),
        EnrichScorer(),
    ],
}


def score_result(
    prompt_name: str,
    parsed: Any,
    sample: dict[str, Any],
) -> dict[str, float]:
    """Score a single result. Returns dict of check_name → 0.0/1.0 scores."""
    scorers = _PROMPT_SCORERS.get(prompt_name, [])
    if not scorers:
        return {}

    scores: dict[str, float] = {}
    for scorer in scorers:
        scores.update(scorer.score(parsed or {}, sample))
    return scores


def _contains_simplified(text: str) -> bool:
    """Check if text contains simplified Chinese characters using OpenCC."""
    if _S2T_CONVERTER is None:
        logger.warning("OpenCC not available, skipping simplified Chinese check")
        return False
    converted = _S2T_CONVERTER.convert(text)
    return converted != text


def _check_lemma(lemma: str, original_word: str) -> float:
    """Heuristic lemma validation. 1.0 = looks OK, 0.0 = suspicious."""
    if not lemma:
        return 0.0
    lemma = lemma.strip().lower()
    original = original_word.strip().lower()

    # Basic checks
    if not lemma.isascii():
        return 0.0  # lemma should be English
    if " " in lemma:
        return 0.0  # no multi-word lemmas
    if len(lemma) > 50:
        return 0.0

    # If lemma == original, that's fine (base form or uncertain)
    if lemma == original:
        return 1.0

    # If original ends with common inflections and lemma is shorter, likely OK
    # (this is a very loose heuristic — full validation needs a dictionary)
    return 1.0
