"""Injectable lexical lookup orchestration and fallback policy."""

from __future__ import annotations

import time
from typing import Literal, Protocol

from pydantic import BaseModel

from .exceptions import ExternalServiceError, ForbiddenError, NotFoundError
from .lexical_cache import LexicalCache
from .lexical_models import LexicalEntry, LexicalProvider
from .lexical_provider import _decode_entry_key
from .lexical_rate_limit import LexicalRateLimiter

DEFAULT_PROVIDER_HOURLY_LIMIT = 950


class LexicalTelemetry(Protocol):
    def record_lookup(self, provider: str, operation: str, outcome: str, duration_ms: int) -> None: ...


class LexicalLookupResult(BaseModel):
    entry: LexicalEntry | None
    cache_status: Literal["miss", "fresh", "stale", "negative"]
    provider_called: bool = True


def _failure_outcome(exc: BaseException) -> str:
    """Classify a raised lookup into the `lexical_lookup_event` vocabulary."""
    if isinstance(exc, ForbiddenError):
        return "blocked"
    if isinstance(exc, NotFoundError):
        return "negative"
    label = getattr(exc, "label", "")
    if label == "dictionary_provider_rate_limited":
        return "rate_limited"
    if label == "dictionary_provider_hourly_limit":
        return "budget_exhausted"
    return "error"


class LexicalService:
    def __init__(
        self,
        *,
        provider: LexicalProvider,
        cache: LexicalCache,
        provider_hourly_limit: int = DEFAULT_PROVIDER_HOURLY_LIMIT,
        telemetry: LexicalTelemetry | None = None,
        rate_limiter: LexicalRateLimiter | None = None,
    ) -> None:
        if provider.capabilities.cache_policy != "persistent":
            raise ForbiddenError(
                f"Dictionary provider {provider.provider_id} does not permit persistent caching"
            )
        self.provider = provider
        self.cache = cache
        self.telemetry = telemetry or cache
        self.rate_limiter = rate_limiter
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

    def _instrumented(self, operation: str, call) -> LexicalLookupResult:
        """Record exactly one outcome + latency per admitted lookup."""
        started = time.monotonic()
        outcome = "error"
        try:
            result = call()
            outcome = (
                "negative_cached"
                if result.cache_status == "negative" and not result.provider_called
                else result.cache_status
            )
            return result
        except BaseException as exc:  # noqa: BLE001 — re-raised; only classified
            outcome = _failure_outcome(exc)
            raise
        finally:
            self.telemetry.record_lookup(
                self.provider.provider_id,
                operation,
                outcome,
                round((time.monotonic() - started) * 1000),
            )

    def search(
        self,
        query: str,
        *,
        source_language: str,
        target_language: str,
        limiter_key: str | None = None,
    ) -> LexicalLookupResult:
        return self._instrumented(
            "search",
            lambda: self._search(
                query,
                source_language=source_language,
                target_language=target_language,
                limiter_key=limiter_key,
            ),
        )

    def _search(
        self,
        query: str,
        *,
        source_language: str,
        target_language: str,
        limiter_key: str | None,
    ) -> LexicalLookupResult:
        if (
            limiter_key is not None
            and self.rate_limiter is not None
            and not self.rate_limiter.admit(limiter_key)
        ):
            raise ExternalServiceError(
                "dictionary_provider_rate_limited", headers={"Retry-After": "60"}
            )
        cached = self.cache.get_query(
            self.provider.provider_id, query, source_language, target_language
        )
        if cached is not None and cached.fresh:
            return LexicalLookupResult(
                entry=cached.entry,
                cache_status="fresh" if cached.entry is not None else "negative",
                provider_called=False,
            )
        try:
            self._reserve_provider_request()
        except ExternalServiceError:
            if cached is not None and cached.entry is not None:
                return LexicalLookupResult(
                    entry=cached.entry, cache_status="stale", provider_called=False
                )
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
    ) -> LexicalLookupResult:
        """Resolve one entry from cache or the configured provider."""
        if provider != self.provider.provider_id:
            raise NotFoundError("Dictionary provider", provider)
        try:
            source_language, _word = _decode_entry_key(entry_key)
        except (ValueError, UnicodeError) as exc:
            raise NotFoundError("Dictionary entry", entry_key) from exc
        if source_language != "en" or target_language != "zh-Hant":
            raise NotFoundError("Dictionary entry", entry_key)
        # Instrumentation starts only once the request is known well-formed —
        # a malformed entry key is a client error, not a lookup outcome.
        return self._instrumented(
            "entry",
            lambda: self._resolve_entry(
                provider,
                entry_key,
                target_language=target_language,
            ),
        )

    def _resolve_entry(
        self,
        provider: str,
        entry_key: str,
        *,
        target_language: str,
    ) -> LexicalLookupResult:
        cached = self.cache.get_entry(provider, entry_key)
        if cached is not None and cached.fresh and cached.entry is not None:
            return LexicalLookupResult(
                entry=cached.entry, cache_status="fresh", provider_called=False
            )
        try:
            self._reserve_provider_request()
        except ExternalServiceError:
            if cached is not None and cached.entry is not None:
                return LexicalLookupResult(
                    entry=cached.entry, cache_status="stale", provider_called=False
                )
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
