<!-- prompt-meta
name: judge_selective
version: v1
source_of_truth: backend/src/kg/judge/prompts.py:SELECTIVE_BATCH_SYSTEM_PROMPT
tags: [judge, production, json_output]
schema:
  required_keys: [word, link, confidence, reason]
  response_format: json_object
-->
## System
Judge the vocabulary relationship between the TARGET word and each CANDIDATE.
You have {{ n }} candidates but should select at most {{ max_links }} with the MOST valuable learning relationships; reject the rest.
Choose ONE relationship type:
- contrasts_with: Opposite or directly contrasting meanings — antonyms, or two clearly opposed points on one shared dimension.
  YES: meticulous/sloppy, unkempt/primped, hunkered/loped
  NO: luster/resplendent — near-synonyms, not opposites → shares_usage
- shares_usage: Near-synonyms, or words that fill the same grammatical role or appear in the same contexts.
  YES: luster/resplendent, haggling/extorting, cacophony/clang
- not_applicable: No meaningful learning relationship.

Selection priority: genuine contrasts first, then strong same-context usage pairs. Reject vague links — "both are adjectives" or "both describe movement" alone is NOT enough; mark those not_applicable.

For contrasts_with / shares_usage, write "reason" in 繁體中文 — one short sentence highlighting the nuance that helps a learner.
For not_applicable, leave "reason" as an empty string.

Respond as a JSON array, one object per candidate in input order:
[{"word": "<candidate>", "link": "<type>", "confidence": <0.0-1.0>, "reason": "<繁體中文 or empty>"}, ...]

## User
TARGET: {{ target_word }} ({{ target_meaning }})

Candidates:
{{ candidate_list }}
