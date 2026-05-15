"""LLM prompt templates for card relationship judgement."""

from __future__ import annotations

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

MANUAL_LINK_SYSTEM_PROMPT = """The user believes these two vocabulary words are related. Your job is to classify the relationship and explain it.

Choose ONE type:
- contrasts_with: The words have similar or overlapping meanings but differ in nuance, tone, formality, or usage scope
- shares_usage: The words appear in similar contexts, share thematic domains, or complement each other in usage

Do NOT return "not_applicable" — the user has decided these words are related. Find and articulate the connection.

Write "reason" in 繁體中文 (1-2 sentences). Explain the relationship AND highlight the nuance/difference between the two words to help learners distinguish them.

Respond JSON: {"link": "<type>", "confidence": <0.0-1.0>, "reason": "<繁體中文>"}"""
