"""Boundary contracts for the decomposed lexical service.

The legacy ``kg.lexical`` module remains a compatibility facade, while each
provider/cache/service seam must be independently replaceable in tests.
"""

from __future__ import annotations

import sqlite3
from datetime import timedelta

import pytest


class _TrackingConnection(sqlite3.Connection):
    closed = False
    fail_on_sql: str | None = None

    def execute(self, sql, parameters=(), /):
        if self.fail_on_sql is not None and self.fail_on_sql in sql:
            raise sqlite3.OperationalError("injected SQLite failure")
        return super().execute(sql, parameters)

    def close(self) -> None:
        self.closed = True
        super().close()


def _track_connections(monkeypatch):
    from kg import lexical_cache

    real_connect = sqlite3.connect
    connections: list[_TrackingConnection] = []

    def connect(*args, **kwargs):
        connection = real_connect(*args, factory=_TrackingConnection, **kwargs)
        connections.append(connection)
        return connection

    monkeypatch.setattr(lexical_cache.sqlite3, "connect", connect)
    return connections


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


def test_lexical_cache_closes_every_connection_after_success(tmp_path, monkeypatch) -> None:
    from kg.lexical_cache import LexicalCache

    connections = _track_connections(monkeypatch)
    cache = LexicalCache(tmp_path / "cache.db")

    cache.put("fake", "word", "en", "zh-Hant", None)
    assert cache.get_query("fake", "word", "en", "zh-Hant") is not None
    assert cache.get_entry("fake", "missing") is None
    cache.record_lookup("fake", "search", "negative", 1)
    assert cache.reserve_provider_request("fake", hourly_limit=1) is True
    assert cache.reserve_provider_request("fake", hourly_limit=1) is False

    assert connections
    assert all(connection.closed for connection in connections)


def test_lexical_cache_closes_and_rolls_back_after_sqlite_errors(
    tmp_path, monkeypatch
) -> None:
    from kg.lexical_cache import LexicalCache

    cache_path = tmp_path / "cache.db"
    cache = LexicalCache(cache_path)
    connections = _track_connections(monkeypatch)

    _TrackingConnection.fail_on_sql = "INSERT INTO lexical_cache"
    with pytest.raises(sqlite3.OperationalError, match="injected SQLite failure"):
        cache.put("fake", "word", "en", "zh-Hant", None)
    assert connections[-1].closed is True

    _TrackingConnection.fail_on_sql = "DELETE FROM lexical_lookup_event"
    cache.record_lookup("fake", "search", "error", 1)
    assert connections[-1].closed is True

    connection = sqlite3.connect(cache_path)
    try:
        count = connection.execute("SELECT COUNT(*) FROM lexical_lookup_event").fetchone()[0]
    finally:
        connection.close()
        _TrackingConnection.fail_on_sql = None
    assert count == 0
