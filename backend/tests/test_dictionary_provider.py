"""Pure dictionary provider and cache behavior."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from _dictionary_lookup_support import _provider_payload


def test_free_dictionary_provider_normalizes_without_quotes_and_stable_ids():
    from kg.lexical import FreeDictionaryProvider

    provider = FreeDictionaryProvider(
        client=httpx.Client(
            transport=httpx.MockTransport(lambda _request: httpx.Response(200, json=_provider_payload()))
        )
    )
    first = provider.search("invoke", source_language="en", target_language="zh-Hant")
    second = provider.search("invoke", source_language="en", target_language="zh-Hant")

    assert first.entry_key == second.entry_key
    assert [sense.key for sense in first.senses] == [sense.key for sense in second.senses]
    assert first.senses[0].examples[0].key == second.senses[0].examples[0].key
    assert first.senses[0].translations == ["援引"]
    assert first.senses[0].examples[0].text == "They invoked an old rule."
    assert "must not persist" not in first.model_dump_json()
    assert first.attribution.license_name == "CC BY-SA 4.0"


@pytest.mark.parametrize(
    "payload",
    [
        {"word": "invoke", "entries": []},
        {"word": "invoke", "entries": [{"partOfSpeech": "verb", "senses": "bad"}]},
        {"word": 42, "entries": []},
    ],
)
def test_provider_malformed_or_empty_entry_fails_closed(payload):
    from kg.exceptions import ExternalServiceError
    from kg.lexical import FreeDictionaryProvider

    provider = FreeDictionaryProvider(
        client=httpx.Client(transport=httpx.MockTransport(lambda _request: httpx.Response(200, json=payload)))
    )
    with pytest.raises(ExternalServiceError):
        provider.search("invoke", source_language="en", target_language="zh-Hant")


def test_dictionary_cache_uses_fresh_hit_and_stale_on_provider_failure(tmp_path):
    from kg.lexical import FreeDictionaryProvider, LexicalCache, LexicalService

    calls = 0

    def responder(_request):
        nonlocal calls
        calls += 1
        if calls > 1:
            return httpx.Response(503, json={"error": "unavailable"})
        return httpx.Response(200, json=_provider_payload())

    cache = LexicalCache(tmp_path / "lexical_cache.db", positive_ttl=timedelta(days=30))
    service = LexicalService(
        provider=FreeDictionaryProvider(client=httpx.Client(transport=httpx.MockTransport(responder))),
        cache=cache,
    )

    assert service.search("invoke", source_language="en", target_language="zh-Hant").cache_status == "miss"
    assert service.search("invoke", source_language="en", target_language="zh-Hant").cache_status == "fresh"
    assert calls == 1

    with closing(sqlite3.connect(cache.path)) as conn, conn:
        conn.execute(
            "UPDATE lexical_cache SET expires_at = ?",
            ((datetime.now(UTC) - timedelta(seconds=1)).isoformat(),),
        )
        conn.commit()

    stale = service.search("invoke", source_language="en", target_language="zh-Hant")
    assert stale.cache_status == "stale"
    assert stale.entry is not None
    assert calls == 2


def test_negative_lookup_is_cached_for_24_hours(tmp_path):
    from kg.lexical import FreeDictionaryProvider, LexicalCache, LexicalService

    calls = 0

    def responder(_request):
        nonlocal calls
        calls += 1
        return httpx.Response(404)

    service = LexicalService(
        provider=FreeDictionaryProvider(client=httpx.Client(transport=httpx.MockTransport(responder))),
        cache=LexicalCache(tmp_path / "lexical_cache.db"),
    )
    first = service.search("missing", source_language="en", target_language="zh-Hant")
    second = service.search("missing", source_language="en", target_language="zh-Hant")
    assert first.cache_status == "negative"
    assert second.cache_status == "negative"
    assert calls == 1
    with closing(sqlite3.connect(service.cache.path)) as conn, conn:
        fetched_at, expires_at = conn.execute("SELECT fetched_at, expires_at FROM lexical_cache").fetchone()
    assert datetime.fromisoformat(expires_at) - datetime.fromisoformat(fetched_at) == timedelta(hours=24)


def test_provider_traversal_is_bounded_and_truncation_is_truthful():
    from kg.lexical import MAX_SENSES, FreeDictionaryProvider

    payload = _provider_payload()
    base = payload["entries"][0]["senses"][0]
    payload["entries"][0]["senses"] = [
        {**base, "definition": f"definition {index}", "examples": [f"example {index}"]} for index in range(MAX_SENSES)
    ]
    provider = FreeDictionaryProvider(
        client=httpx.Client(transport=httpx.MockTransport(lambda _request: httpx.Response(200, json=payload)))
    )
    exact = provider.search("invoke", source_language="en", target_language="zh-Hant")
    assert exact.truncated is False

    payload["entries"][0]["senses"].append({**base, "definition": "one too many", "examples": ["extra"]})
    capped = provider.search("invoke", source_language="en", target_language="zh-Hant")
    assert len(capped.senses) == MAX_SENSES
    assert capped.truncated is True

    deep = {**base, "definition": "deep", "examples": [str(index) for index in range(20)]}
    cursor = deep
    for depth in range(30):
        child = {**base, "definition": f"nested {depth}", "examples": []}
        cursor["subsenses"] = [child]
        cursor = child
    payload["entries"][0]["senses"] = [deep]
    bounded = provider.search("invoke", source_language="en", target_language="zh-Hant")
    assert bounded.truncated is True
    assert len(bounded.senses[0].examples) == 5
    assert len(bounded.senses) <= MAX_SENSES


def test_persistent_provider_hourly_budget_is_shared_across_services(tmp_path):
    from kg.exceptions import ExternalServiceError
    from kg.lexical import FreeDictionaryProvider, LexicalCache, LexicalService

    calls = 0

    def responder(request):
        nonlocal calls
        calls += 1
        word = request.url.path.rsplit("/", 1)[-1]
        return httpx.Response(200, json=_provider_payload(word))

    provider = FreeDictionaryProvider(client=httpx.Client(transport=httpx.MockTransport(responder)))
    cache_path = tmp_path / "lexical_cache.db"
    first = LexicalService(provider=provider, cache=LexicalCache(cache_path), provider_hourly_limit=1)
    second = LexicalService(provider=provider, cache=LexicalCache(cache_path), provider_hourly_limit=1)
    assert first.search("one", source_language="en", target_language="zh-Hant").entry
    with pytest.raises(ExternalServiceError):
        second.search("two", source_language="en", target_language="zh-Hant")
    assert calls == 1


def test_provider_capabilities_and_cambridge_disabled_seam(tmp_path):
    from kg.exceptions import ForbiddenError
    from kg.lexical import CambridgeProvider, FreeDictionaryProvider, LexicalCache, LexicalService

    assert FreeDictionaryProvider.capabilities.cache_policy == "persistent"
    assert FreeDictionaryProvider.capabilities.exact_lookup is True
    assert FreeDictionaryProvider.capabilities.autocomplete is False
    assert CambridgeProvider.capabilities.cache_policy == "none"
    with pytest.raises(ForbiddenError):
        LexicalService(provider=CambridgeProvider(), cache=LexicalCache(tmp_path / "cache.db"))


@pytest.mark.parametrize("failure", ["429", "timeout"])
def test_stale_cache_survives_provider_429_and_timeout(tmp_path, failure):
    from kg.lexical import FreeDictionaryProvider, LexicalCache, LexicalService

    calls = 0

    def responder(_request):
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(200, json=_provider_payload())
        if failure == "429":
            return httpx.Response(429, headers={"Retry-After": "60"})
        raise httpx.ReadTimeout("timed out")

    cache = LexicalCache(tmp_path / "lexical_cache.db")
    service = LexicalService(
        provider=FreeDictionaryProvider(client=httpx.Client(transport=httpx.MockTransport(responder))),
        cache=cache,
    )
    assert service.search("invoke", source_language="en", target_language="zh-Hant").entry
    with closing(sqlite3.connect(cache.path)) as conn, conn:
        conn.execute(
            "UPDATE lexical_cache SET expires_at = ?",
            ((datetime.now(UTC) - timedelta(seconds=1)).isoformat(),),
        )
    result = service.search("invoke", source_language="en", target_language="zh-Hant")
    assert result.cache_status == "stale"
    assert result.entry is not None


def test_timeout_without_stale_cache_and_malformed_json_fail_closed(tmp_path):
    from kg.exceptions import ExternalServiceError
    from kg.lexical import FreeDictionaryProvider, LexicalCache, LexicalService

    timeout_service = LexicalService(
        provider=FreeDictionaryProvider(
            client=httpx.Client(
                transport=httpx.MockTransport(lambda _request: (_ for _ in ()).throw(httpx.ReadTimeout("timed out")))
            )
        ),
        cache=LexicalCache(tmp_path / "timeout.db"),
    )
    with pytest.raises(ExternalServiceError):
        timeout_service.search("invoke", source_language="en", target_language="zh-Hant")

    malformed_service = LexicalService(
        provider=FreeDictionaryProvider(
            client=httpx.Client(
                transport=httpx.MockTransport(
                    lambda _request: httpx.Response(
                        200,
                        content=b"{not-json",
                        headers={"Content-Type": "application/json"},
                    )
                )
            )
        ),
        cache=LexicalCache(tmp_path / "malformed.db"),
    )
    with pytest.raises(ExternalServiceError):
        malformed_service.search("invoke", source_language="en", target_language="zh-Hant")


def test_normalized_payload_is_actually_capped_at_256_kib():
    from kg.lexical import MAX_PAYLOAD_BYTES, FreeDictionaryProvider

    payload = _provider_payload()
    payload["entries"][0]["senses"] = [
        {
            "definition": f"{index}-" + "d" * 3998,
            "examples": ["e" * 1000 for _ in range(5)],
            "synonyms": ["s" * 256 for _ in range(50)],
            "antonyms": ["a" * 256 for _ in range(50)],
            "translations": [],
            "subsenses": [],
        }
        for index in range(20)
    ]
    provider = FreeDictionaryProvider(
        client=httpx.Client(transport=httpx.MockTransport(lambda _request: httpx.Response(200, json=payload)))
    )
    entry = provider.search("invoke", source_language="en", target_language="zh-Hant")
    assert entry.truncated is True
    assert len(entry.model_dump_json().encode()) <= MAX_PAYLOAD_BYTES


def test_provider_budget_is_rolling_and_exhaustion_still_returns_stale(tmp_path, monkeypatch):
    import kg.lexical as lexical
    from kg.exceptions import ExternalServiceError
    from kg.lexical import FreeDictionaryProvider, LexicalCache, LexicalService

    clock = 3599.0
    monkeypatch.setattr(lexical.time, "time", lambda: clock)
    calls = 0

    def responder(request):
        nonlocal calls
        calls += 1
        word = request.url.path.rsplit("/", 1)[-1]
        return httpx.Response(200, json=_provider_payload(word))

    cache = LexicalCache(tmp_path / "lexical_cache.db")
    service = LexicalService(
        provider=FreeDictionaryProvider(client=httpx.Client(transport=httpx.MockTransport(responder))),
        cache=cache,
        provider_hourly_limit=1,
    )
    assert service.search("invoke", source_language="en", target_language="zh-Hant").entry
    with closing(sqlite3.connect(cache.path)) as conn, conn:
        conn.execute(
            "UPDATE lexical_cache SET expires_at = ?",
            ((datetime.now(UTC) - timedelta(seconds=1)).isoformat(),),
        )

    clock = 3601.0
    assert service.search("invoke", source_language="en", target_language="zh-Hant").cache_status == "stale"
    with pytest.raises(ExternalServiceError):
        service.search("other", source_language="en", target_language="zh-Hant")
    assert calls == 1

    clock = 7200.0
    assert service.search("other", source_language="en", target_language="zh-Hant").entry
    assert calls == 2


def _enable_lookup(isolated_api, monkeypatch, *, cache_name="lexical_cache.db"):
    import kg.routers.dictionary as dictionary_router
    from kg.lexical import FreeDictionaryProvider, LexicalCache, LexicalService

    service = LexicalService(
        provider=FreeDictionaryProvider(
            client=httpx.Client(
                transport=httpx.MockTransport(lambda _request: httpx.Response(200, json=_provider_payload()))
            )
        ),
        cache=LexicalCache(isolated_api.data_dir / cache_name),
    )
    monkeypatch.setattr(dictionary_router, "_lexical_service", lambda _settings: service)
    isolated_api.client.app.state.kg_settings = replace(
        isolated_api.client.app.state.kg_settings,
        dictionary_lookup_enabled=True,
    )
    dictionary_router.dictionary_lookup_leases.reset()
    return dictionary_router, service


def test_dictionary_search_endpoint_requires_flag_and_returns_provider_neutral_payload(isolated_api, monkeypatch):
    import kg.routers.dictionary as dictionary_router

    disabled = isolated_api.client.get(
        "/api/dictionary/search?q=invoke&source_lang=en&target_lang=zh-Hant",
        headers=isolated_api.headers,
    )
    assert disabled.status_code == 403

    _enable_lookup(isolated_api, monkeypatch)
    response = isolated_api.client.get(
        "/api/dictionary/search?q=invoke&source_lang=en&target_lang=zh-Hant",
        headers=isolated_api.headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["cacheStatus"] == "miss"
    assert body["hits"][0]["provider"] == "free_dictionary"
    assert body["hits"][0]["word"] == "invoke"
    assert all(route.methods == {"GET"} for route in dictionary_router.router.routes)


def test_dictionary_detail_is_rate_limited_and_v1_languages_are_locked(isolated_api, monkeypatch):
    from kg.lexical import dictionary_rate_limiter

    dictionary_router, _service = _enable_lookup(isolated_api, monkeypatch)
    monkeypatch.setattr(dictionary_rate_limiter, "limit", 3)
    dictionary_rate_limiter.reset()

    search = isolated_api.client.get(
        "/api/dictionary/search?q=invoke&source_lang=en&target_lang=zh-Hant",
        headers=isolated_api.headers,
    )
    entry_key = search.json()["hits"][0]["entryKey"]
    unsupported_entry_language = isolated_api.client.get(
        "/api/dictionary/entries/free_dictionary/fr.bW90?target_lang=zh-Hant",
        headers=isolated_api.headers,
    )
    detail = isolated_api.client.get(
        f"/api/dictionary/entries/free_dictionary/{entry_key}?target_lang=zh-Hant",
        headers=isolated_api.headers,
    )
    limited = isolated_api.client.get(
        f"/api/dictionary/entries/free_dictionary/{entry_key}?target_lang=zh-Hant",
        headers=isolated_api.headers,
    )
    actually_limited = isolated_api.client.get(
        f"/api/dictionary/entries/free_dictionary/{entry_key}?target_lang=zh-Hant",
        headers=isolated_api.headers,
    )
    unsupported_source = isolated_api.client.get(
        "/api/dictionary/search?q=invoke&source_lang=fr&target_lang=zh-Hant",
        headers=isolated_api.headers,
    )
    unsupported_target = isolated_api.client.get(
        "/api/dictionary/search?q=invoke&source_lang=en&target_lang=fr",
        headers=isolated_api.headers,
    )

    assert detail.status_code == 200
    assert unsupported_entry_language.status_code == 404
    assert limited.status_code == 200
    assert actually_limited.status_code == 429
    assert actually_limited.headers["Retry-After"] == "60"
    assert unsupported_source.status_code == 422
    assert unsupported_target.status_code == 422
    dictionary_router.dictionary_lookup_leases.reset()


def test_explicit_dictionary_search_and_its_first_detail_share_one_admission(isolated_api, monkeypatch):
    from kg.lexical import dictionary_rate_limiter

    dictionary_router, _service = _enable_lookup(isolated_api, monkeypatch, cache_name="lexical_cache-admission.db")
    monkeypatch.setattr(dictionary_rate_limiter, "limit", 1)
    dictionary_rate_limiter.reset()

    search = isolated_api.client.get(
        "/api/dictionary/search?q=invoke&source_lang=en&target_lang=zh-Hant",
        headers=isolated_api.headers,
    )
    entry_key = search.json()["hits"][0]["entryKey"]
    first_detail = isolated_api.client.get(
        f"/api/dictionary/entries/free_dictionary/{entry_key}",
        headers=isolated_api.headers,
    )
    abusive_repeat = isolated_api.client.get(
        f"/api/dictionary/entries/free_dictionary/{entry_key}",
        headers=isolated_api.headers,
    )

    assert search.status_code == 200
    assert first_detail.status_code == 200
    assert abusive_repeat.status_code == 429
    dictionary_router.dictionary_lookup_leases.reset()


def test_dictionary_entry_endpoint_returns_404_for_cached_negative_lookup(isolated_api, monkeypatch):
    import kg.routers.dictionary as dictionary_router
    from kg.lexical import FreeDictionaryProvider, LexicalCache, LexicalService

    service = LexicalService(
        provider=FreeDictionaryProvider(
            client=httpx.Client(transport=httpx.MockTransport(lambda _request: httpx.Response(404)))
        ),
        cache=LexicalCache(isolated_api.data_dir / "lexical-cache-negative-entry.db"),
    )
    monkeypatch.setattr(dictionary_router, "_lexical_service", lambda _settings: service)
    dictionary_router.dictionary_lookup_leases.reset()
    isolated_api.client.app.state.kg_settings = replace(
        isolated_api.client.app.state.kg_settings,
        dictionary_lookup_enabled=True,
    )
    response = isolated_api.client.get(
        "/api/dictionary/entries/free_dictionary/en.bWlzc2luZw",
        headers=isolated_api.headers,
    )
    assert response.status_code == 404
