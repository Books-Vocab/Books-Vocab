"""Provider-neutral lexical lookup, FreeDictionary adapter and SQLite cache."""

from __future__ import annotations

import base64
import hashlib
import json
import sqlite3
import threading
import time
from collections import defaultdict, deque
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal, Protocol
from urllib.parse import quote

import httpx
from pydantic import BaseModel, Field

from .exceptions import ExternalServiceError, ForbiddenError, NotFoundError

MAX_SENSES = 20
MAX_EXAMPLES_PER_SENSE = 5
MAX_PAYLOAD_BYTES = 256 * 1024
MAX_SENSE_DEPTH = 8
MAX_SENSE_NODES = 200
DEFAULT_PROVIDER_HOURLY_LIMIT = 950


class LexicalAttribution(BaseModel):
    provider: str
    source_url: str
    license_name: str
    license_url: str
    attribution_text: str


class LexicalExample(BaseModel):
    key: str
    text: str


class LexicalSense(BaseModel):
    key: str
    part_of_speech: str | None = None
    definition: str
    examples: list[LexicalExample] = Field(default_factory=list)
    translations: list[str] = Field(default_factory=list)
    synonyms: list[str] = Field(default_factory=list)
    antonyms: list[str] = Field(default_factory=list)


class LexicalEntry(BaseModel):
    provider: str
    dictionary_id: str
    schema_version: str
    entry_key: str
    word: str
    language: str
    pronunciations: list[str] = Field(default_factory=list)
    forms: list[str] = Field(default_factory=list)
    senses: list[LexicalSense] = Field(default_factory=list)
    attribution: LexicalAttribution
    fetched_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    truncated: bool = False


class LexicalProviderCapabilities(BaseModel):
    exact_lookup: bool
    autocomplete: bool
    translations: bool
    pronunciation: bool
    cache_policy: Literal["persistent", "memory_only", "none"]


class LexicalProvider(Protocol):
    provider_id: str
    dictionary_id: str
    schema_version: str
    capabilities: LexicalProviderCapabilities

    def search(
        self, query: str, *, source_language: str, target_language: str
    ) -> LexicalEntry | None: ...

    def get_entry(
        self, entry_key: str, *, target_language: str = "zh-Hant"
    ) -> LexicalEntry | None: ...


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


class CachedLexicalValue(BaseModel):
    entry: LexicalEntry | None
    fresh: bool


class LexicalLookupResult(BaseModel):
    entry: LexicalEntry | None
    cache_status: Literal["miss", "fresh", "stale", "negative"]


class LexicalCache:
    def __init__(
        self,
        path: Path,
        *,
        positive_ttl: timedelta = timedelta(days=30),
        negative_ttl: timedelta = timedelta(hours=24),
    ) -> None:
        self.path = path
        self.positive_ttl = positive_ttl
        self.negative_ttl = negative_ttl
        path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(path) as conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS lexical_cache (
                    cache_key TEXT PRIMARY KEY,
                    provider TEXT NOT NULL,
                    entry_key TEXT,
                    payload_json TEXT,
                    is_negative INTEGER NOT NULL DEFAULT 0,
                    fetched_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL
                )"""
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS ix_lexical_cache_entry_key "
                "ON lexical_cache(provider, entry_key)"
            )
            conn.execute(
                """CREATE TABLE IF NOT EXISTS lexical_provider_request (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    provider TEXT NOT NULL,
                    requested_at REAL NOT NULL
                )"""
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS ix_lexical_provider_request_window "
                "ON lexical_provider_request(provider, requested_at)"
            )

    @staticmethod
    def query_key(provider: str, query: str, source_language: str, target_language: str) -> str:
        return "|".join((provider, source_language.lower(), target_language.lower(), query.strip().casefold()))

    def get_query(
        self, provider: str, query: str, source_language: str, target_language: str
    ) -> CachedLexicalValue | None:
        return self._get(self.query_key(provider, query, source_language, target_language))

    def get_entry(self, provider: str, entry_key: str) -> CachedLexicalValue | None:
        with sqlite3.connect(self.path) as conn:
            row = conn.execute(
                "SELECT payload_json, is_negative, expires_at FROM lexical_cache "
                "WHERE provider = ? AND entry_key = ? ORDER BY fetched_at DESC LIMIT 1",
                (provider, entry_key),
            ).fetchone()
        return self._row_value(row)

    def _get(self, cache_key: str) -> CachedLexicalValue | None:
        with sqlite3.connect(self.path) as conn:
            row = conn.execute(
                "SELECT payload_json, is_negative, expires_at FROM lexical_cache WHERE cache_key = ?",
                (cache_key,),
            ).fetchone()
        return self._row_value(row)

    @staticmethod
    def _row_value(row: tuple | None) -> CachedLexicalValue | None:
        if row is None:
            return None
        payload_json, is_negative, expires_at = row
        expires = datetime.fromisoformat(expires_at)
        now = datetime.now(UTC)
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=UTC)
        entry = None if is_negative else LexicalEntry.model_validate_json(payload_json)
        return CachedLexicalValue(entry=entry, fresh=expires > now)

    def put(
        self,
        provider: str,
        query: str,
        source_language: str,
        target_language: str,
        entry: LexicalEntry | None,
    ) -> None:
        now = datetime.now(UTC)
        expires = now + (self.positive_ttl if entry is not None else self.negative_ttl)
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                """INSERT INTO lexical_cache(
                       cache_key, provider, entry_key, payload_json, is_negative, fetched_at, expires_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(cache_key) DO UPDATE SET
                       entry_key=excluded.entry_key, payload_json=excluded.payload_json,
                       is_negative=excluded.is_negative, fetched_at=excluded.fetched_at,
                       expires_at=excluded.expires_at""",
                (
                    self.query_key(provider, query, source_language, target_language),
                    provider,
                    entry.entry_key if entry else None,
                    entry.model_dump_json() if entry else None,
                    int(entry is None),
                    now.isoformat(),
                    expires.isoformat(),
                ),
            )

    def reserve_provider_request(self, provider: str, *, hourly_limit: int) -> bool:
        """Atomically reserve one upstream call across workers sharing this cache."""
        now = time.time()
        window_start = now - 3600.0
        with sqlite3.connect(self.path, timeout=5.0, isolation_level=None) as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "DELETE FROM lexical_provider_request WHERE requested_at <= ?",
                (window_start,),
            )
            request_count = int(
                conn.execute(
                    "SELECT COUNT(*) FROM lexical_provider_request "
                    "WHERE provider = ? AND requested_at > ?",
                    (provider, window_start),
                ).fetchone()[0]
            )
            if request_count >= hourly_limit:
                conn.rollback()
                return False
            conn.execute(
                "INSERT INTO lexical_provider_request(provider, requested_at) VALUES (?, ?)",
                (provider, now),
            )
            conn.commit()
        return True


class LexicalService:
    def __init__(
        self,
        *,
        provider: LexicalProvider,
        cache: LexicalCache,
        provider_hourly_limit: int = DEFAULT_PROVIDER_HOURLY_LIMIT,
    ) -> None:
        if provider.capabilities.cache_policy != "persistent":
            raise ForbiddenError(
                f"Dictionary provider {provider.provider_id} does not permit persistent caching"
            )
        self.provider = provider
        self.cache = cache
        # The upstream FreeDictionary contract is 1,000 calls/hour/IP. Keep a
        # hard safety margin even if an invalid deployment value is supplied.
        self.provider_hourly_limit = max(1, min(provider_hourly_limit, 999))

    def _reserve_provider_request(self) -> None:
        if not self.cache.reserve_provider_request(
            self.provider.provider_id, hourly_limit=self.provider_hourly_limit
        ):
            raise ExternalServiceError(
                "dictionary_provider_hourly_limit", headers={"Retry-After": "3600"}
            )

    def search(
        self, query: str, *, source_language: str, target_language: str
    ) -> LexicalLookupResult:
        cached = self.cache.get_query(
            self.provider.provider_id, query, source_language, target_language
        )
        if cached is not None and cached.fresh:
            return LexicalLookupResult(
                entry=cached.entry,
                cache_status="fresh" if cached.entry is not None else "negative",
            )
        try:
            self._reserve_provider_request()
        except ExternalServiceError:
            if cached is not None and cached.entry is not None:
                return LexicalLookupResult(entry=cached.entry, cache_status="stale")
            raise
        try:
            entry = self.provider.search(
                query, source_language=source_language, target_language=target_language
            )
        except ExternalServiceError:
            if cached is not None and cached.entry is not None:
                return LexicalLookupResult(entry=cached.entry, cache_status="stale")
            raise
        self.cache.put(
            self.provider.provider_id, query, source_language, target_language, entry
        )
        return LexicalLookupResult(
            entry=entry, cache_status="miss" if entry is not None else "negative"
        )

    def get_entry(
        self,
        provider: str,
        entry_key: str,
        *,
        target_language: str,
        allow_provider: bool = True,
    ) -> LexicalLookupResult:
        """Resolve one entry. ``allow_provider=False`` serves cache only.

        Cache-only mode exists for saga resumption while the dictionary rollout
        flag is off: an interrupted materialization must be allowed to finish,
        but a rolled-back deployment must still never reach the provider.
        """
        if provider != self.provider.provider_id:
            raise NotFoundError("Dictionary provider", provider)
        try:
            source_language, _word = _decode_entry_key(entry_key)
        except (ValueError, UnicodeError) as exc:
            raise NotFoundError("Dictionary entry", entry_key) from exc
        if source_language != "en" or target_language != "zh-Hant":
            raise NotFoundError("Dictionary entry", entry_key)
        cached = self.cache.get_entry(provider, entry_key)
        if cached is not None and cached.fresh and cached.entry is not None:
            return LexicalLookupResult(entry=cached.entry, cache_status="fresh")
        if not allow_provider:
            if cached is not None and cached.entry is not None:
                return LexicalLookupResult(entry=cached.entry, cache_status="stale")
            raise ForbiddenError("Dictionary lookup is disabled")
        try:
            self._reserve_provider_request()
        except ExternalServiceError:
            if cached is not None and cached.entry is not None:
                return LexicalLookupResult(entry=cached.entry, cache_status="stale")
            raise
        try:
            entry = self.provider.get_entry(entry_key, target_language=target_language)
        except ExternalServiceError:
            if cached is not None and cached.entry is not None:
                return LexicalLookupResult(entry=cached.entry, cache_status="stale")
            raise
        if entry is None:
            raise NotFoundError("Dictionary entry", entry_key)
        self.cache.put(provider, entry.word, entry.language, target_language, entry)
        return LexicalLookupResult(entry=entry, cache_status="miss")


class LexicalRateLimiter:
    def __init__(self, *, limit: int = 20, window_seconds: float = 60.0) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def admit(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            events = self._events[key]
            while events and events[0] <= now - self.window_seconds:
                events.popleft()
            if len(events) >= self.limit:
                return False
            events.append(now)
            return True

    def reset(self) -> None:
        with self._lock:
            self._events.clear()


dictionary_rate_limiter = LexicalRateLimiter()
