<!-- prompt-meta
name: translate_quick
version: v1
source_of_truth: backend/src/kg/translate_service.py:quick_translate_prompt
tags: [translate, production, json_output]
schema:
  required_keys: [t, p, r]
  response_format: json_object
-->
## User
Translate from {{ source_lang_name }} to {{ target_lang_name }}. Provide translation, POS, and lemma (root form).
POS options: n. / v. / adj. / adv. / conj. / prep.
Word: "{{ word }}"
Context: "{{ context }}"

Translation (t) rules:
- Must be {{ target_lang_name }} (use 繁體中文 characters, never 简体)
- adj. translation must end with「的」(e.g. 輝煌的, 虔誠的)
- adv. translation must end with「地」(e.g. 沉思地, 端莊地)

Lemma (r) rules:
- Must be a valid {{ source_lang_name }} dictionary word
- No cross-POS derivation (adjective lemma stays adjective, not its derived noun)
- Verb inflections → base form (e.g. hurrying→hurry, gazed→gaze)
- Plural nouns → singular (e.g. berries→berry); if no singular exists, return original
- If adjective/adverb is already base form, r = original word
- When uncertain, r = original word; never invent non-existent words

Output pure JSON (no Markdown): { "t": "...", "p": "...", "r": "..." }
