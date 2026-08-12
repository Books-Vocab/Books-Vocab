"""Compatibility facade for the decomposed lexical service.

New code should import from ``lexical_models``, ``lexical_provider``,
``lexical_cache``, ``lexical_service`` or ``lexical_rate_limit``.  This module
keeps the historical import surface stable for routers and downstream code.
"""

# This facade intentionally re-exports implementation symbols for legacy
# callers; the imported names below are its public compatibility surface.
# ruff: noqa: F401

from . import lexical_cache as _lexical_cache
from .lexical_cache import CachedLexicalValue, LexicalCache
from .lexical_models import (
    LexicalAttribution,
    LexicalEntry,
    LexicalExample,
    LexicalProvider,
    LexicalProviderCapabilities,
    LexicalSense,
)
from .lexical_provider import (
    MAX_EXAMPLES_PER_SENSE,
    MAX_PAYLOAD_BYTES,
    MAX_SENSE_DEPTH,
    MAX_SENSE_NODES,
    MAX_SENSES,
    CambridgeProvider,
    FreeDictionaryProvider,
    _decode_entry_key,
    _entry_key,
    _stable_key,
    _text,
)
from .lexical_rate_limit import LexicalRateLimiter, dictionary_rate_limiter
from .lexical_service import (
    DEFAULT_PROVIDER_HOURLY_LIMIT,
    LexicalLookupResult,
    LexicalService,
)

# Historical tests patch ``kg.lexical.time.time`` to control the shared
# provider-budget clock.  Keep that seam pointing at the cache module's time
# object while the implementation lives in ``lexical_cache``.
time = _lexical_cache.time

LOOKUP_OUTCOMES = (
    "fresh",
    "negative_cached",
    "stale",
    "miss",
    "negative",
    "throttled",
    "rate_limited",
    "budget_exhausted",
    "error",
    "blocked",
)
CACHE_SERVED_OUTCOMES = ("fresh", "negative_cached")
LOOKUP_FAILURE_OUTCOMES = (
    "stale",
    "rate_limited",
    "budget_exhausted",
    "error",
    "blocked",
)
LOOKUP_EVENT_RETENTION_DAYS = 14

__all__ = [
    "CachedLexicalValue",
    "CACHE_SERVED_OUTCOMES",
    "CambridgeProvider",
    "DEFAULT_PROVIDER_HOURLY_LIMIT",
    "FreeDictionaryProvider",
    "LOOKUP_EVENT_RETENTION_DAYS",
    "LOOKUP_FAILURE_OUTCOMES",
    "LOOKUP_OUTCOMES",
    "LexicalAttribution",
    "LexicalCache",
    "LexicalEntry",
    "LexicalExample",
    "LexicalLookupResult",
    "LexicalProvider",
    "LexicalProviderCapabilities",
    "LexicalRateLimiter",
    "LexicalSense",
    "LexicalService",
    "dictionary_rate_limiter",
]
