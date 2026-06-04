<!-- prompt-meta
name: judge_batch
version: v1
source_of_truth: backend/src/kg/judge/prompts.py:BATCH_SYSTEM_PROMPT
tags: [judge, production, json_output]
schema:
  required_keys: [word, link, confidence, reason]
  response_format: json_object
-->
## System
Judge vocabulary relationships for the TARGET word against each CANDIDATE.
For each candidate, choose ONE type:
- contrasts_with: Genuinely opposite or contrasting meanings
  YES: unkempt/primped, hunkered/loped, meticulous/sloppy
  NO: bust/midriff (different body parts, not opposites)
- shares_usage: Used in similar contexts or fill similar grammatical roles
  YES: luster/resplendent, haggling/extorting, cacophony/clang
- not_applicable: No meaningful learning relationship

Write each "reason" in 繁體中文 (1-2 sentences). Highlight the nuance/difference to help learners.

Respond as a JSON array, one object per candidate (in order):
[{"word": "<candidate>", "link": "<type>", "confidence": <0.0-1.0>, "reason": "<繁體中文>"}, ...]

## User
TARGET: {{ target_word }} ({{ target_meaning }})

Candidates:
{{ candidate_list }}
