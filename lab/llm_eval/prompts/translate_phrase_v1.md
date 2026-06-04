<!-- prompt-meta
name: translate_phrase
version: v1
source_of_truth: backend/src/kg/translate_service.py:phrase_translate_prompt
tags: [translate, production, json_output]
schema:
  required_keys: [t]
  response_format: json_object
-->
## User
Translate the following {{ source_lang_name }} phrase/expression into {{ target_lang_name }} (use 繁體中文, never 简体).
Phrase: "{{ word }}"
Context: "{{ context }}"
Output pure JSON (no Markdown): { "t": "..." }
