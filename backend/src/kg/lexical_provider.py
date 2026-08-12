"""External dictionary provider adapters and entry-key helpers."""

from __future__ import annotations

import base64
import hashlib
import json
from typing import Final
from urllib.parse import quote

import httpx

from .exceptions import ExternalServiceError, ForbiddenError, NotFoundError
from .lexical_models import (
    LexicalAttribution,
    LexicalEntry,
    LexicalExample,
    LexicalProviderCapabilities,
    LexicalSense,
)

MAX_SENSES: Final = 20
MAX_EXAMPLES_PER_SENSE: Final = 5
MAX_PAYLOAD_BYTES: Final = 256 * 1024
MAX_SENSE_DEPTH: Final = 8
MAX_SENSE_NODES: Final = 200


def _stable_key(prefix: str, *parts: object) -> str:
    raw = json.dumps(parts, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"{prefix}_{hashlib.sha256(raw.encode()).hexdigest()[:20]}"


def _entry_key(language: str, word: str) -> str:
    encoded = base64.urlsafe_b64encode(word.encode()).decode().rstrip("=")
    return f"{language}.{encoded}"


def _decode_entry_key(value: str) -> tuple[str, str]:
    language, sep, encoded = value.partition(".")
    if not sep or not language or not encoded:
        raise ValueError("invalid entry key")
    encoded += "=" * (-len(encoded) % 4)
    return language, base64.urlsafe_b64decode(encoded).decode()


def _text(value: object, limit: int) -> str:
    return str(value or "").strip()[:limit]


class FreeDictionaryProvider:
    provider_id = "free_dictionary"
    dictionary_id = "wiktionary-en"
    schema_version = "v1"
    capabilities = LexicalProviderCapabilities(
        exact_lookup=True,
        autocomplete=False,
        translations=True,
        pronunciation=True,
        cache_policy="persistent",
    )

    def __init__(self, *, client: httpx.Client | None = None) -> None:
        self.client = client or httpx.Client(
            base_url="https://freedictionaryapi.com/api/v1", timeout=5.0
        )

    def search(
        self, query: str, *, source_language: str, target_language: str
    ) -> LexicalEntry | None:
        word = query.strip()
        if not word:
            return None
        try:
            response = self.client.get(
                "https://freedictionaryapi.com/api/v1/entries/"
                f"{quote(source_language, safe='')}/{quote(word, safe='')}",
                params={"translations": "true"},
            )
        except httpx.HTTPError as exc:
            raise ExternalServiceError("dictionary_provider_unavailable", exc=exc) from exc
        if response.status_code == 404:
            return None
        if response.status_code == 429:
            raise ExternalServiceError(
                "dictionary_provider_rate_limited", headers={"Retry-After": response.headers.get("Retry-After", "60")}
            )
        if response.status_code >= 500:
            raise ExternalServiceError("dictionary_provider_unavailable")
        try:
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ExternalServiceError("dictionary_provider_invalid_response", exc=exc) from exc
        if not isinstance(payload, dict):
            raise ExternalServiceError("dictionary_provider_invalid_response")
        return self._normalize(payload, source_language=source_language, target_language=target_language)

    def get_entry(
        self, entry_key: str, *, target_language: str = "zh-Hant"
    ) -> LexicalEntry | None:
        try:
            language, word = _decode_entry_key(entry_key)
        except (ValueError, UnicodeError) as exc:
            raise NotFoundError("Dictionary entry", entry_key) from exc
        if language != "en":
            raise NotFoundError("Dictionary entry", entry_key)
        return self.search(word, source_language=language, target_language=target_language)

    def _normalize(
        self, payload: dict, *, source_language: str, target_language: str
    ) -> LexicalEntry:
        raw_word = payload.get("word")
        raw_entries = payload.get("entries")
        if not isinstance(raw_word, str) or not raw_word.strip():
            raise ExternalServiceError("dictionary_provider_invalid_response")
        if not isinstance(raw_entries, list) or not raw_entries:
            raise ExternalServiceError("dictionary_provider_invalid_response")
        word = _text(raw_word, 256)
        was_truncated = len(raw_word.strip()) > 256
        source = payload.get("source") if isinstance(payload.get("source"), dict) else {}
        license_data = source.get("license") if isinstance(source.get("license"), dict) else {}
        source_url = _text(source.get("url"), 2000) or f"https://en.wiktionary.org/wiki/{quote(word)}"
        attribution = LexicalAttribution(
            provider=self.provider_id,
            source_url=source_url,
            license_name=_text(license_data.get("name"), 200) or "CC BY-SA 4.0",
            license_url=_text(license_data.get("url"), 2000)
            or "https://creativecommons.org/licenses/by-sa/4.0/",
            attribution_text="Dictionary data from Wiktionary via FreeDictionaryAPI.com",
        )
        pronunciations: list[str] = []
        forms: list[str] = []
        senses: list[LexicalSense] = []
        sense_nodes = 0

        def string_list(raw: object, *, limit: int, item_limit: int) -> list[str]:
            nonlocal was_truncated
            if raw is None:
                return []
            if not isinstance(raw, list) or any(not isinstance(item, str) for item in raw):
                raise ExternalServiceError("dictionary_provider_invalid_response")
            if len(raw) > limit:
                was_truncated = True
            values: list[str] = []
            for item in raw[:limit]:
                cleaned = _text(item, item_limit)
                if len(item.strip()) > item_limit:
                    was_truncated = True
                if cleaned:
                    values.append(cleaned)
            return values

        def append_senses(
            raw_senses: object, part_of_speech: str | None, *, depth: int = 0,
        ) -> None:
            nonlocal sense_nodes, was_truncated
            if raw_senses is None:
                return
            if not isinstance(raw_senses, list):
                raise ExternalServiceError("dictionary_provider_invalid_response")
            if depth > MAX_SENSE_DEPTH:
                if raw_senses:
                    was_truncated = True
                return
            for index, raw in enumerate(raw_senses):
                sense_nodes += 1
                if sense_nodes > MAX_SENSE_NODES:
                    was_truncated = True
                    return
                if len(senses) >= MAX_SENSES:
                    # Mark only when an unvisited node actually remains.
                    if index < len(raw_senses):
                        was_truncated = True
                    return
                if not isinstance(raw, dict):
                    raise ExternalServiceError("dictionary_provider_invalid_response")
                raw_definition = raw.get("definition")
                if raw_definition is not None and not isinstance(raw_definition, str):
                    raise ExternalServiceError("dictionary_provider_invalid_response")
                definition = _text(raw_definition, 4000)
                if isinstance(raw_definition, str) and len(raw_definition.strip()) > 4000:
                    was_truncated = True
                if definition:
                    raw_examples = string_list(
                        raw.get("examples"), limit=MAX_EXAMPLES_PER_SENSE, item_limit=1000
                    )
                    examples: list[LexicalExample] = []
                    for text in raw_examples:
                        if text:
                            examples.append(
                                LexicalExample(
                                    key=_stable_key("example", word, part_of_speech, definition, text),
                                    text=text,
                                )
                            )
                    translations: list[str] = []
                    raw_translations = raw.get("translations", [])
                    if not isinstance(raw_translations, list):
                        raise ExternalServiceError("dictionary_provider_invalid_response")
                    if len(raw_translations) > 50:
                        was_truncated = True
                    for item in raw_translations[:50]:
                        if not isinstance(item, dict):
                            raise ExternalServiceError("dictionary_provider_invalid_response")
                        language = item.get("language") if isinstance(item.get("language"), dict) else {}
                        code = str(language.get("code", "")).lower()
                        if code in {"zh", "zh-hant", "zh-tw"}:
                            if not isinstance(item.get("word"), str):
                                raise ExternalServiceError("dictionary_provider_invalid_response")
                            translated = _text(item.get("word"), 500)
                            if translated and translated not in translations:
                                translations.append(translated)
                    senses.append(
                        LexicalSense(
                            key=_stable_key("sense", word, part_of_speech, definition),
                            part_of_speech=part_of_speech,
                            definition=definition,
                            examples=examples,
                            translations=translations[:20],
                            synonyms=string_list(raw.get("synonyms"), limit=50, item_limit=256),
                            antonyms=string_list(raw.get("antonyms"), limit=50, item_limit=256),
                        )
                    )
                append_senses(raw.get("subsenses"), part_of_speech, depth=depth + 1)

        for raw_entry in raw_entries:
            if not isinstance(raw_entry, dict):
                raise ExternalServiceError("dictionary_provider_invalid_response")
            raw_pos = raw_entry.get("partOfSpeech")
            if raw_pos is not None and not isinstance(raw_pos, str):
                raise ExternalServiceError("dictionary_provider_invalid_response")
            part_of_speech = _text(raw_pos, 100) or None
            raw_pronunciations = raw_entry.get("pronunciations", [])
            raw_forms = raw_entry.get("forms", [])
            if not isinstance(raw_pronunciations, list) or not isinstance(raw_forms, list):
                raise ExternalServiceError("dictionary_provider_invalid_response")
            if len(raw_pronunciations) > 20 or len(raw_forms) > 100:
                was_truncated = True
            for item in raw_pronunciations[:20]:
                if isinstance(item, dict):
                    raw_value = item.get("text")
                    if not isinstance(raw_value, str):
                        raise ExternalServiceError("dictionary_provider_invalid_response")
                    value = _text(raw_value, 256)
                    if value and value not in pronunciations:
                        pronunciations.append(value)
                else:
                    raise ExternalServiceError("dictionary_provider_invalid_response")
            for item in raw_forms[:100]:
                if isinstance(item, dict):
                    raw_value = item.get("word")
                    if not isinstance(raw_value, str):
                        raise ExternalServiceError("dictionary_provider_invalid_response")
                    value = _text(raw_value, 256)
                    if value and value not in forms:
                        forms.append(value)
                else:
                    raise ExternalServiceError("dictionary_provider_invalid_response")
            append_senses(raw_entry.get("senses"), part_of_speech)

        if not senses:
            raise ExternalServiceError("dictionary_provider_invalid_response")

        entry = LexicalEntry(
            provider=self.provider_id,
            dictionary_id=self.dictionary_id,
            schema_version=self.schema_version,
            entry_key=_entry_key(source_language, word),
            word=word,
            language=source_language,
            pronunciations=pronunciations[:20],
            forms=forms[:100],
            senses=senses,
            attribution=attribution,
            truncated=was_truncated,
        )
        while len(entry.model_dump_json().encode()) > MAX_PAYLOAD_BYTES and entry.senses:
            entry.senses.pop()
            entry.truncated = True
        return entry


class CambridgeProvider:
    """Disabled adapter seam pending a persistence/offline distribution licence."""

    provider_id = "cambridge"
    dictionary_id = "cambridge"
    schema_version = "disabled"
    capabilities = LexicalProviderCapabilities(
        exact_lookup=True,
        autocomplete=False,
        translations=False,
        pronunciation=False,
        cache_policy="none",
    )

    def search(
        self, query: str, *, source_language: str, target_language: str
    ) -> LexicalEntry | None:
        raise ForbiddenError("Cambridge dictionary provider is not licensed for persistence")

    def get_entry(
        self, entry_key: str, *, target_language: str = "zh-Hant"
    ) -> LexicalEntry | None:
        raise ForbiddenError("Cambridge dictionary provider is not licensed for persistence")
