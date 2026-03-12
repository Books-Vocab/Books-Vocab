from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import HTTPException

from .api_models import ExplainResponse, QuickTranslateResponse, TranslateRequest

SUPPORTED_LANGUAGES = {
    "en": "English",
    "ja": "Japanese",
    "ko": "Korean",
    "fr": "French",
    "de": "German",
    "es": "Spanish",
    "zh-Hant": "Traditional Chinese",
    "zh-Hans": "Simplified Chinese",
}

SUPPORTED_SOURCE_LANGS = {"en", "ja", "ko", "fr", "de", "es"}
SUPPORTED_TARGET_LANGS = {"zh-Hant", "zh-Hans", "en", "ja", "ko"}


def resolve_translation_langs(req: TranslateRequest, user: dict[str, Any]) -> tuple[str, str]:
    """Resolve source/target languages from request → user config → defaults."""
    source = req.source_lang
    target = req.target_lang

    user_config = user.get("config", {})
    translation_config = user_config.get("translation", {}) if isinstance(user_config, dict) else {}

    if not source:
        source = translation_config.get("source_lang", "en")
    if not target:
        target = translation_config.get("target_lang", "zh-Hant")

    if source not in SUPPORTED_SOURCE_LANGS:
        source = "en"
    if target not in SUPPORTED_TARGET_LANGS:
        target = "zh-Hant"

    return source, target


def quick_translate_prompt(req: TranslateRequest, source_lang: str, target_lang: str) -> str:
    src_name = SUPPORTED_LANGUAGES.get(source_lang, "English")
    tgt_name = SUPPORTED_LANGUAGES.get(target_lang, "Traditional Chinese")
    return f'''Translate from {src_name} to {tgt_name}. Provide translation, POS, and lemma (root form).
POS options: n. / v. / adj. / adv. / conj. / prep.
Word: "{req.word}"
Context: "{req.context[:300]}"

Lemma (r) rules:
- Must be a valid {src_name} dictionary word
- No cross-POS derivation (adjective lemma stays adjective, not its derived noun)
- Verb inflections → base form (e.g. hurrying→hurry, gazed→gaze)
- Plural nouns → singular (e.g. berries→berry); if no singular exists, return original
- If adjective/adverb is already base form, r = original word
- When uncertain, r = original word; never invent non-existent words

Output pure JSON (no Markdown): {{ "t": "...", "p": "...", "r": "..." }}'''


def phrase_translate_prompt(req: TranslateRequest, source_lang: str, target_lang: str) -> str:
    src_name = SUPPORTED_LANGUAGES.get(source_lang, "English")
    tgt_name = SUPPORTED_LANGUAGES.get(target_lang, "Traditional Chinese")
    return f'''Translate the following {src_name} phrase/expression into {tgt_name}. Provide the most precise translation.
Phrase: "{req.word}"
Context: "{req.context[:300]}"
Output pure JSON (no Markdown): {{ "t": "..." }}'''


def explain_translate_prompt(req: TranslateRequest, source_lang: str, target_lang: str) -> str:
    tgt_name = SUPPORTED_LANGUAGES.get(target_lang, "Traditional Chinese")
    return f'''Briefly explain the meaning of "{req.word}" in the given context using {tgt_name} (1-2 sentences).
Context: "{req.context[:300]}"
Output pure JSON (no Markdown) with a single key "e" for the explanation: {{ "e": "..." }}'''


def _parse_json_payload(raw: str | None) -> dict[str, Any]:
    try:
        data = json.loads(raw or "{}")
    except json.JSONDecodeError:
        logging.getLogger("kg").warning("Failed to parse JSON payload: %s", raw[:200] if raw else None)
        return {}
    if isinstance(data, list):
        data = data[0] if data else {}
    if not isinstance(data, dict):
        return {}
    return data


def track_usage(user_id: str, operation: str, response: Any) -> None:
    if not getattr(response, "usage", None):
        return
    from .token_tracker import record as track

    track(
        user_id,
        operation,
        getattr(response.usage, "prompt_tokens", 0) or 0,
        getattr(response.usage, "completion_tokens", 0) or 0,
    )


def run_quick_translate(req: TranslateRequest, user: dict[str, Any], *, client: Any, logger: logging.Logger) -> QuickTranslateResponse:
    source_lang, target_lang = resolve_translation_langs(req, user)
    response = client.chat.completions.create(
        model="gemini-2.5-flash-lite",
        messages=[{"role": "user", "content": quick_translate_prompt(req, source_lang, target_lang)}],
        temperature=0.3,
        response_format={"type": "json_object"},
    )
    if not response.choices:
        logger.error("translate/quick: Gemini returned empty choices. Full response: %s", response)
        raise HTTPException(500, "Gemini returned empty response")

    track_usage(user["id"], "translate_quick", response)
    data = _parse_json_payload(response.choices[0].message.content)
    return QuickTranslateResponse(
        t=data.get("t", ""),
        p=data.get("p"),
        r=data.get("r"),
    )


def run_phrase_translate(req: TranslateRequest, user: dict[str, Any], *, client: Any) -> dict[str, str]:
    source_lang, target_lang = resolve_translation_langs(req, user)
    response = client.chat.completions.create(
        model="gemini-2.5-flash-lite",
        messages=[{"role": "user", "content": phrase_translate_prompt(req, source_lang, target_lang)}],
        temperature=0.3,
        response_format={"type": "json_object"},
    )
    track_usage(user["id"], "translate_phrase", response)
    data = _parse_json_payload(response.choices[0].message.content)
    return {"t": data.get("t", "")}


def run_explain_translate(req: TranslateRequest, user: dict[str, Any], *, client: Any) -> ExplainResponse:
    source_lang, target_lang = resolve_translation_langs(req, user)
    response = client.chat.completions.create(
        model="gemini-2.5-flash-lite",
        messages=[{"role": "user", "content": explain_translate_prompt(req, source_lang, target_lang)}],
        temperature=0.3,
        response_format={"type": "json_object"},
    )
    track_usage(user["id"], "translate_explain", response)
    data = _parse_json_payload(response.choices[0].message.content)
    return ExplainResponse(e=data.get("e", ""))
