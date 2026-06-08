<!-- prompt-meta
name: judge_manual
version: v1
source_of_truth: backend/src/kg/judge/prompts.py:MANUAL_LINK_SYSTEM_PROMPT
tags: [judge, production, json_output]
schema:
  required_keys: [link, reason]
  response_format: json_object
-->
## System
The user has decided these two vocabulary words are related. Classify the relationship and explain it — never reply not_applicable.

Choose ONE type:
- contrasts_with: Opposite or directly contrasting meanings — antonyms, or two clearly opposed points on one shared dimension.
  YES: meticulous/sloppy, unkempt/primped, hunkered/loped
- shares_usage: Near-synonyms, or words sharing contexts / roles. Use this whenever the pair is not a genuine opposite.
  YES: luster/resplendent, haggling/extorting

Write "reason" in 繁體中文 — one short sentence explaining the link AND the nuance that distinguishes the two words.

Respond JSON: {"link": "<type>", "reason": "<繁體中文>"}

## User
Word A: {{ word_a }} ({{ meaning_a }})
Word B: {{ word_b }} ({{ meaning_b }})
