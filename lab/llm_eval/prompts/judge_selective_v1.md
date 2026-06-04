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
Judge vocabulary relationships for the TARGET word.
You have {{ n }} candidates but should select at most {{ max_links }} with the MOST valuable learning relationships.

Selection criteria (in order):
1. Genuine contrasts — opposite or clearly different nuances of a similar concept
2. Strong usage pairs — consistently fill the same grammatical role or appear in the same contexts
3. REJECT vague connections — "both are body movements" or "both are adjectives" is NOT enough

For the best {{ max_links }} candidates, respond:
{"word": "<candidate>", "link": "contrasts_with" or "shares_usage", "confidence": <0.0-1.0>, "reason": "<繁體中文>"}

For the rest, respond:
{"word": "<candidate>", "link": "not_applicable", "confidence": 0.0, "reason": ""}

Write each "reason" in 繁體中文 (1-2 sentences). Highlight the nuance/difference to help learners.
Respond as a JSON array, one object per candidate (in order).

## User
TARGET: {{ target_word }} ({{ target_meaning }})

Candidates:
{{ candidate_list }}
