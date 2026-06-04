<!-- prompt-meta
name: translate_explain
version: v1
source_of_truth: backend/src/kg/translate_service.py:explain_translate_prompt
tags: [translate, production, json_output]
schema:
  required_keys: [e]
  response_format: json_object
-->
## User
Explain what "{{ word }}" means in the given context, then briefly break down the {{ source_lang_name }} components/structure. 1-2 sentences max, in {{ target_lang_name }} (use 繁體中文 characters, never 简体).

Word: "{{ word }}"
Context: "{{ context }}"
Output pure JSON (no Markdown): { "e": "..." }
