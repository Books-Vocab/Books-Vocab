from __future__ import annotations

import threading
import time
from functools import lru_cache
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Query, Request

from ..api_models import (
    DictionaryEntryResponse,
    DictionarySearchHit,
    DictionarySearchResponse,
)
from ..deps import CurrentUser
from ..exceptions import ForbiddenError, KGError
from ..lexical import (
    FreeDictionaryProvider,
    LexicalCache,
    LexicalService,
    dictionary_rate_limiter,
)
from ..settings import KGSettings

router = APIRouter(tags=["dictionary"])


class DictionaryRateLimitError(KGError):
    status_code = 429


class _DictionaryLookupLeases:
    """One-shot bridge from an admitted search to its immediate detail fetch.

    A client search followed by opening its returned entry is one user action.
    A short-lived, one-shot lease prevents double charging while repeated or
    direct detail requests continue through the normal limiter.
    """

    def __init__(self, ttl_seconds: float = 120.0) -> None:
        self.ttl_seconds = ttl_seconds
        self._lock = threading.Lock()
        self._expires: dict[tuple[str, str, str], float] = {}

    def grant(self, user_id: str, provider: str, entry_key: str) -> None:
        now = time.monotonic()
        with self._lock:
            self._prune(now)
            self._expires[(user_id, provider, entry_key)] = now + self.ttl_seconds

    def consume(self, user_id: str, provider: str, entry_key: str) -> bool:
        now = time.monotonic()
        key = (user_id, provider, entry_key)
        with self._lock:
            self._prune(now)
            expires = self._expires.pop(key, None)
            return expires is not None and expires > now

    def _prune(self, now: float) -> None:
        expired = [key for key, expiry in self._expires.items() if expiry <= now]
        for key in expired:
            self._expires.pop(key, None)

    def reset(self) -> None:
        with self._lock:
            self._expires.clear()


dictionary_lookup_leases = _DictionaryLookupLeases()


@lru_cache(maxsize=8)
def _build_lexical_service(cache_path: str, positive_ttl_days: int, negative_ttl_hours: int) -> LexicalService:
    from datetime import timedelta

    return LexicalService(
        provider=FreeDictionaryProvider(),
        cache=LexicalCache(
            Path(cache_path),
            positive_ttl=timedelta(days=positive_ttl_days),
            negative_ttl=timedelta(hours=negative_ttl_hours),
        ),
    )


def _lexical_service(settings: KGSettings) -> LexicalService:
    if settings.dictionary_provider_default != "free_dictionary":
        raise ForbiddenError("Configured dictionary provider is not enabled")
    return _build_lexical_service(
        str(settings.data_dir / "lexical_cache.db"),
        settings.dictionary_cache_ttl_days,
        settings.dictionary_negative_cache_ttl_hours,
    )


def _require_enabled(settings: KGSettings) -> None:
    if not settings.dictionary_lookup_enabled:
        raise ForbiddenError("Dictionary lookup is disabled")


def _admit(service: LexicalService, user_id: str, operation: str) -> None:
    if not dictionary_rate_limiter.admit(user_id):
        # Recorded here because the limiter refuses before LexicalService runs;
        # user-facing 429s would otherwise be invisible to `dictionary-health`.
        service.cache.record_lookup(service.provider.provider_id, operation, "throttled", 0)
        raise DictionaryRateLimitError(f"Dictionary {operation} rate limit exceeded", headers={"Retry-After": "60"})


@router.get("/api/dictionary/search", response_model=DictionarySearchResponse)
def search_dictionary(
    request: Request,
    user: CurrentUser,
    q: str = Query(min_length=1, max_length=200, pattern=r".*\S.*"),
    source_lang: Literal["en"] = "en",
    target_lang: Literal["zh-Hant"] = "zh-Hant",
):
    settings: KGSettings = request.app.state.kg_settings
    _require_enabled(settings)
    service = _lexical_service(settings)
    _admit(service, user["id"], "search")
    result = service.search(q, source_language=source_lang, target_language=target_lang)
    hits: list[DictionarySearchHit] = []
    if result.entry is not None:
        entry = result.entry
        dictionary_lookup_leases.grant(user["id"], entry.provider, entry.entry_key)
        parts = list(dict.fromkeys(s.part_of_speech for s in entry.senses if s.part_of_speech))
        hits.append(
            DictionarySearchHit(
                provider=entry.provider,
                dictionaryId=entry.dictionary_id,
                entryKey=entry.entry_key,
                word=entry.word,
                language=entry.language,
                partsOfSpeech=parts,
                hasExamples=any(s.examples for s in entry.senses),
                attribution=entry.attribution,
            )
        )
    return DictionarySearchResponse(hits=hits, cacheStatus=result.cache_status)


@router.get(
    "/api/dictionary/entries/{provider}/{entry_key}",
    response_model=DictionaryEntryResponse,
)
def get_dictionary_entry(
    provider: str,
    entry_key: str,
    request: Request,
    user: CurrentUser,
    target_lang: Literal["zh-Hant"] = "zh-Hant",
):
    settings: KGSettings = request.app.state.kg_settings
    _require_enabled(settings)
    service = _lexical_service(settings)
    if not dictionary_lookup_leases.consume(user["id"], provider, entry_key):
        _admit(service, user["id"], "entry")
    result = service.get_entry(provider, entry_key, target_language=target_lang)
    return DictionaryEntryResponse(entry=result.entry, cacheStatus=result.cache_status)
