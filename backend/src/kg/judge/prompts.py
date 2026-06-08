"""LLM prompt templates for card relationship judgement.

Single source of truth for the three judge call paths (batch / selective /
manual). All three share one canonical definition of the link types so the
same pair is judged identically regardless of entry point:

- contrasts_with — strict opposite / antonym (meticulous↔sloppy). NOT a
  near-synonym: luster/resplendent are similar, so they are shares_usage.
- shares_usage  — near-synonyms or words filling the same role / context.
- not_applicable — no meaningful learning relationship (auto paths only;
  the manual path never returns this).

Cost note (deepseek-v4-flash: output is 2x input, system prompt is prefix
-cached): keep the system prompt rich but push the *output* to the floor —
empty reason for not_applicable, no confidence field on the manual path.
"""

from __future__ import annotations

# Shared canonical link-type definition. Embedded verbatim into every system
# prompt so batch / selective / manual cannot drift apart again.
_LINK_TYPES = """Choose ONE relationship type:
- contrasts_with: Opposite or directly contrasting meanings — antonyms, or two clearly opposed points on one shared dimension.
  YES: meticulous/sloppy, unkempt/primped, hunkered/loped
  NO: luster/resplendent — near-synonyms, not opposites → shares_usage
- shares_usage: Near-synonyms, or words that fill the same grammatical role or appear in the same contexts.
  YES: luster/resplendent, haggling/extorting, cacophony/clang
- not_applicable: No meaningful learning relationship."""

# Reason-writing rule shared by the auto (batch/selective) paths. The reason
# is only meaningful for a real link; not_applicable reasons are log-only and
# never shown, so leaving them empty is pure output-token savings.
_AUTO_REASON_RULE = (
    'For contrasts_with / shares_usage, write "reason" in 繁體中文 — one short '
    "sentence highlighting the nuance that helps a learner.\n"
    'For not_applicable, leave "reason" as an empty string.'
)

# Response schema line shared by batch and selective (parsing matches by the
# "word" field and filters on "confidence" against the 0.7 threshold, so both
# keys are required even for rejects).
_AUTO_SCHEMA = (
    "Respond as a JSON array, one object per candidate in input order:\n"
    '[{"word": "<candidate>", "link": "<type>", "confidence": <0.0-1.0>, '
    '"reason": "<繁體中文 or empty>"}, ...]'
)

BATCH_SYSTEM_PROMPT = f"""Judge the vocabulary relationship between the TARGET word and each CANDIDATE.
{_LINK_TYPES}

{_AUTO_REASON_RULE}

{_AUTO_SCHEMA}"""

SELECTIVE_BATCH_SYSTEM_PROMPT = f"""Judge the vocabulary relationship between the TARGET word and each CANDIDATE.
You have {{n}} candidates but should select at most {{max_links}} with the MOST valuable learning relationships; reject the rest.
{_LINK_TYPES}

Selection priority: genuine contrasts first, then strong same-context usage pairs. Reject vague links — "both are adjectives" or "both describe movement" alone is NOT enough; mark those not_applicable.

{_AUTO_REASON_RULE}

{_AUTO_SCHEMA}"""

BATCH_USER_TEMPLATE = """TARGET: {target_word} ({target_meaning})

Candidates:
{candidate_list}"""

MANUAL_LINK_SYSTEM_PROMPT = """The user has decided these two vocabulary words are related. Classify the relationship and explain it — never reply not_applicable.

Choose ONE type:
- contrasts_with: Opposite or directly contrasting meanings — antonyms, or two clearly opposed points on one shared dimension.
  YES: meticulous/sloppy, unkempt/primped
- shares_usage: Near-synonyms, or words sharing contexts / roles. Use this whenever the pair is not a genuine opposite.
  YES: luster/resplendent, haggling/extorting

Write "reason" in 繁體中文 — one short sentence explaining the link AND the nuance that distinguishes the two words.

Respond JSON: {"link": "<type>", "reason": "<繁體中文>"}"""

MANUAL_USER_TEMPLATE = """Word A: {word_a} ({meaning_a})
Word B: {word_b} ({meaning_b})"""
