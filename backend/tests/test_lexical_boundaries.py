"""Boundary contracts for the decomposed lexical service.

The legacy ``kg.lexical`` module remains a compatibility facade, while each
provider/cache/service seam must be independently replaceable in tests.
"""

from __future__ import annotations

from datetime import timedelta

import pytest


def test_lexical_layers_have_stable_import_boundaries() -> None:
    from kg.lexical import LexicalCache as LegacyCache
    from kg.lexical import LexicalEntry as LegacyEntry
    from kg.lexical import LexicalService as LegacyService
    from kg.lexical_cache import LexicalCache
    from kg.lexical_models import LexicalEntry
    from kg.lexical_service import LexicalService

    assert LegacyEntry is LexicalEntry
    assert LegacyCache is LexicalCache
    assert LegacyService is LexicalService


def test_service_accepts_injected_telemetry_and_limiter(tmp_path) -> None:
    from kg.exceptions import ExternalServiceError, ForbiddenError
    from kg.lexical_cache import LexicalCache
    from kg.lexical_models import LexicalProviderCapabilities
    from kg.lexical_rate_limit import LexicalRateLimiter
    from kg.lexical_service import LexicalService

    events: list[tuple[str, str, int]] = []

    class Telemetry:
        def record_lookup(self, provider: str, operation: str, outcome: str, duration_ms: int) -> None:
            events.append((provider, outcome, duration_ms))

    class FakeProvider:
        provider_id = "fake"
        capabilities = LexicalProviderCapabilities(
            exact_lookup=True,
            autocomplete=False,
            translations=False,
            pronunciation=False,
            cache_policy="persistent",
        )

        def search(self, query: str, *, source_language: str, target_language: str):
            raise ForbiddenError("fixture provider disabled")

        def get_entry(self, entry_key: str, *, target_language: str = "zh-Hant"):
            raise ForbiddenError("fixture provider disabled")

    limiter = LexicalRateLimiter(limit=1, window_seconds=60)
    service = LexicalService(
        provider=FakeProvider(),
        cache=LexicalCache(tmp_path / "cache.db"),
        telemetry=Telemetry(),
        rate_limiter=limiter,
    )

    assert service.rate_limiter is limiter
    assert service.telemetry is not None
    assert service.cache.positive_ttl == timedelta(days=30)

    with pytest.raises(ForbiddenError):
        service.search("word", source_language="en", target_language="zh-Hant", limiter_key="u1")
    with pytest.raises(ExternalServiceError):
        service.search("word", source_language="en", target_language="zh-Hant", limiter_key="u1")
    assert events and events[-1][0] == "fake"


def test_rate_limiter_reaps_expired_user_state(monkeypatch) -> None:
    from kg.lexical_rate_limit import LexicalRateLimiter

    now = [100.0]
    monkeypatch.setattr("kg.lexical_rate_limit.monotonic", lambda: now[0])
    limiter = LexicalRateLimiter(limit=1, window_seconds=10)

    assert limiter.admit("u1") is True
    assert limiter.admit("u1") is False
    now[0] = 111.0
    assert limiter.admit("u1") is True
    assert limiter.tracked_keys == 1
