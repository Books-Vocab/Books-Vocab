from __future__ import annotations

import hashlib
import json
import logging
import time
from collections.abc import Callable
from typing import Any

from . import translate_log
from .exceptions import ExternalServiceError

from .api_models import ExplainResponse, QuickTranslateResponse, TranslateRequest
from .languages import LANGUAGE_NAMES as SUPPORTED_LANGUAGES, SUPPORTED_SOURCE_LANGS, SUPPORTED_TARGET_LANGS
from .vocab_shared import _normalize_pos


def _context_around_word(context: str, word: str, max_len: int = 300) -> str:
    """Truncate context centered on the target word."""
    if len(context) <= max_len:
        return context
    pos = context.lower().find(word.lower())
    if pos < 0:
        return context[:max_len]
    half = (max_len - len(word)) // 2
    start = max(0, pos - half)
    end = min(len(context), pos + len(word) + half)
    return context[start:end].strip()


def _compute_context_hash(context: str) -> str:
    return hashlib.sha256((context or "").encode()).hexdigest()[:16]


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
Context: "{_context_around_word(req.context, req.word)}"

Translation (t) rules:
- Must be {tgt_name} (use 繁體中文 characters, never 简体)
- adj. translation must end with「的」(e.g. 輝煌的, 虔誠的)
- adv. translation must end with「地」(e.g. 沉思地, 端莊地)

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
    return f'''Translate the following {src_name} phrase/expression into {tgt_name} (use 繁體中文, never 简体).
Phrase: "{req.word}"
Context: "{_context_around_word(req.context, req.word)}"
Output pure JSON (no Markdown): {{ "t": "..." }}'''


def explain_translate_prompt(req: TranslateRequest, source_lang: str, target_lang: str) -> str:
    src_name = SUPPORTED_LANGUAGES.get(source_lang, "English")
    tgt_name = SUPPORTED_LANGUAGES.get(target_lang, "Traditional Chinese")
    return f'''You are a language tutor. Given a {src_name} word/phrase and its surrounding context, write a cohesive explanation in {tgt_name} that naturally weaves together:
1. The meaning in this specific context
2. Core {src_name} usage patterns (common collocations, typical sentence structures, register/formality)
3. Nuances, connotations, or subtle distinctions from near-synonyms if relevant

Write as a single flowing paragraph (3-5 sentences). Do NOT use section headers, bullet points, or numbered lists. The explanation should read like a knowledgeable tutor speaking naturally.

Word: "{req.word}"
Context: "{_context_around_word(req.context, req.word)}"
Output pure JSON (no Markdown): {{ "e": "..." }}'''


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


async def _run_llm_translate(
    *,
    req: TranslateRequest,
    user: dict[str, Any],
    llm: Any,
    model: str,
    prompt_fn: Callable,
    operation: str,
    logger: logging.Logger | None = None,
) -> dict:
    """Common LLM translate flow: resolve langs -> cache check -> call -> parse -> record."""
    source_lang, target_lang = resolve_translation_langs(req, user)
    ctx = _context_around_word(req.context, req.word)
    word_key = req.word.strip().lower()
    ctx_hash = _compute_context_hash(ctx)

    # Cache lookup
    cached = translate_log.lookup(word_key, ctx_hash, source_lang, target_lang, operation)
    if cached is not None:
        return _parse_json_payload(cached)

    # LLM call with latency tracking
    t0 = time.monotonic()
    response = await llm.chat_async(
        operation,
        model=model,
        messages=[{"role": "user", "content": prompt_fn(req, source_lang, target_lang)}],
        temperature=0.3,
        response_format={"type": "json_object"},
    )
    latency_ms = int((time.monotonic() - t0) * 1000)

    if not response.choices:
        if logger:
            logger.error("%s: Gemini returned empty choices. Full response: %s", operation, response)
        raise ExternalServiceError("Gemini returned empty response")

    raw = response.choices[0].message.content
    translate_log.record(
        user_id=llm.user_id, operation=operation,
        word=word_key, context=ctx, context_hash=ctx_hash,
        source_lang=source_lang, target_lang=target_lang,
        response_raw=raw or "", latency_ms=latency_ms,
    )
    return _parse_json_payload(raw)


async def run_quick_translate(req: TranslateRequest, user: dict[str, Any], *, llm: Any, logger: logging.Logger, model: str = "gemini-2.5-flash-lite") -> QuickTranslateResponse:
    data = await _run_llm_translate(req=req, user=user, llm=llm, model=model, prompt_fn=quick_translate_prompt, operation="translate_quick", logger=logger)
    return QuickTranslateResponse(t=data.get("t", ""), p=_normalize_pos(data.get("p")), r=data.get("r"))


async def run_phrase_translate(req: TranslateRequest, user: dict[str, Any], *, llm: Any, logger: logging.Logger | None = None, model: str = "gemini-2.5-flash-lite") -> dict[str, str]:
    data = await _run_llm_translate(req=req, user=user, llm=llm, model=model, prompt_fn=phrase_translate_prompt, operation="translate_phrase", logger=logger)
    return {"t": data.get("t", "")}


async def run_explain_translate(req: TranslateRequest, user: dict[str, Any], *, llm: Any, logger: logging.Logger | None = None, model: str = "gemini-2.5-flash-lite") -> ExplainResponse:
    data = await _run_llm_translate(req=req, user=user, llm=llm, model=model, prompt_fn=explain_translate_prompt, operation="translate_explain", logger=logger)
    return ExplainResponse(e=data.get("e", ""))
