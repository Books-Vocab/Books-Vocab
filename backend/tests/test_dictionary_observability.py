# ruff: noqa: F401, F403, F405, I001
"""test dictionary observability.py test ownership shard."""



from _dictionary_v1_support import *  # noqa: F403



def test_lookups_record_outcome_and_latency_for_ops_observability(tmp_path):
    """hit/miss/stale/429/error/latency have no other source than this ledger."""
    from kg.exceptions import ExternalServiceError
    from kg.lexical import LexicalCache, LexicalProviderCapabilities, LexicalService

    entry = _lexical_entry()

    class _ScriptedProvider:
        provider_id = entry.provider
        dictionary_id = entry.dictionary_id
        schema_version = entry.schema_version
        capabilities = LexicalProviderCapabilities(
            exact_lookup=True,
            autocomplete=False,
            translations=True,
            pronunciation=True,
            cache_policy="persistent",
        )

        def __init__(self):
            self.script = []

        def search(self, _query, *, source_language, target_language):
            outcome = self.script.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        def get_entry(self, _entry_key, *, target_language="zh-Hant"):
            return self.search(None, source_language="en", target_language=target_language)

    provider = _ScriptedProvider()
    cache_path = tmp_path / "lexical_cache.db"
    service = LexicalService(provider=provider, cache=LexicalCache(cache_path))

    provider.script = [entry]
    assert service.search("invoke", source_language="en", target_language="zh-Hant").cache_status == "miss"
    assert service.search("invoke", source_language="en", target_language="zh-Hant").cache_status == "fresh"

    provider.script = [None]
    assert service.search("nope", source_language="en", target_language="zh-Hant").cache_status == "negative"

    provider.script = [ExternalServiceError("dictionary_provider_rate_limited")]
    with pytest.raises(ExternalServiceError):
        service.search("brandnew", source_language="en", target_language="zh-Hant")

    provider.script = [ExternalServiceError("dictionary_provider_unavailable")]
    with pytest.raises(ExternalServiceError):
        service.search("otherword", source_language="en", target_language="zh-Hant")

    events = _lookup_events(cache_path)
    assert [e["outcome"] for e in events] == [
        "miss",
        "fresh",
        "negative",
        "rate_limited",
        "error",
    ]
    assert {e["operation"] for e in events} == {"search"}
    assert {e["provider"] for e in events} == {entry.provider}
    assert all(isinstance(e["duration_ms"], int) and e["duration_ms"] >= 0 for e in events)

def test_stale_fallback_and_cache_only_block_are_recorded_distinctly(tmp_path):
    from kg.exceptions import ExternalServiceError, ForbiddenError
    from kg.lexical import LexicalCache, LexicalProviderCapabilities, LexicalService

    entry = _lexical_entry()

    class _FailingProvider:
        provider_id = entry.provider
        dictionary_id = entry.dictionary_id
        schema_version = entry.schema_version
        capabilities = LexicalProviderCapabilities(
            exact_lookup=True,
            autocomplete=False,
            translations=True,
            pronunciation=True,
            cache_policy="persistent",
        )

        def search(self, *_args, **_kwargs):
            raise ExternalServiceError("dictionary_provider_unavailable")

        def get_entry(self, *_args, **_kwargs):
            raise ExternalServiceError("dictionary_provider_unavailable")

    cache_path = tmp_path / "lexical_cache.db"
    expired = LexicalCache(cache_path, positive_ttl=timedelta(seconds=-1))
    expired.put(entry.provider, entry.word, entry.language, "zh-Hant", entry)
    service = LexicalService(provider=_FailingProvider(), cache=expired)

    assert service.get_entry(
        entry.provider, entry.entry_key, target_language="zh-Hant"
    ).cache_status == "stale"

    empty_path = tmp_path / "empty_cache.db"
    blocked = LexicalService(provider=_FailingProvider(), cache=LexicalCache(empty_path))
    with pytest.raises(ForbiddenError):
        blocked.get_entry(
            entry.provider,
            entry.entry_key,
            target_language="zh-Hant",
            allow_provider=False,
        )

    assert [e["outcome"] for e in _lookup_events(cache_path)] == ["stale"]
    assert [e["operation"] for e in _lookup_events(cache_path)] == ["entry"]
    assert [e["outcome"] for e in _lookup_events(empty_path)] == ["blocked"]

def test_per_user_throttle_refusals_are_recorded_for_ops(isolated_api, monkeypatch):
    """User-facing 429s come from our own limiter, not the provider's — an ops
    view that only counted provider 429s would report calm during a throttle
    storm."""
    import kg.routers.dictionary as dictionary_router
    from kg.lexical import (
        FreeDictionaryProvider,
        LexicalCache,
        LexicalService,
        dictionary_rate_limiter,
    )

    cache_path = isolated_api.data_dir / "lexical_cache-throttle.db"
    service = LexicalService(
        provider=FreeDictionaryProvider(
            client=httpx.Client(
                transport=httpx.MockTransport(
                    lambda _r: httpx.Response(200, json=_provider_payload())
                )
            )
        ),
        cache=LexicalCache(cache_path),
    )
    monkeypatch.setattr(dictionary_router, "_lexical_service", lambda _settings: service)
    monkeypatch.setattr(dictionary_rate_limiter, "limit", 1)
    dictionary_rate_limiter.reset()
    dictionary_router.dictionary_lookup_leases.reset()
    isolated_api.client.app.state.kg_settings = replace(
        isolated_api.client.app.state.kg_settings,
        dictionary_lookup_enabled=True,
    )

    admitted = isolated_api.client.get(
        "/api/dictionary/search?q=invoke", headers=isolated_api.headers
    )
    dictionary_router.dictionary_lookup_leases.reset()
    refused = isolated_api.client.get(
        "/api/dictionary/search?q=invoke", headers=isolated_api.headers
    )

    assert admitted.status_code == 200, admitted.text
    assert refused.status_code == 429
    assert [e["outcome"] for e in _lookup_events(cache_path)] == ["miss", "throttled"]

def test_cached_negative_is_not_reported_as_a_provider_call(tmp_path):
    """A cached "no such word" costs nothing upstream; counting it as a miss
    would make the cache look useless exactly when it is doing its job."""
    from kg.lexical import LexicalCache, LexicalProviderCapabilities, LexicalService

    entry = _lexical_entry()

    class _CountingProvider:
        provider_id = entry.provider
        dictionary_id = entry.dictionary_id
        schema_version = entry.schema_version
        capabilities = LexicalProviderCapabilities(
            exact_lookup=True,
            autocomplete=False,
            translations=True,
            pronunciation=True,
            cache_policy="persistent",
        )

        def __init__(self):
            self.calls = 0

        def search(self, *_args, **_kwargs):
            self.calls += 1
            return None

        def get_entry(self, *_args, **_kwargs):
            return self.search()

    provider = _CountingProvider()
    cache_path = tmp_path / "lexical_cache.db"
    service = LexicalService(provider=provider, cache=LexicalCache(cache_path))

    first = service.search("zzznotaword", source_language="en", target_language="zh-Hant")
    second = service.search("zzznotaword", source_language="en", target_language="zh-Hant")

    assert provider.calls == 1
    assert first.cache_status == second.cache_status == "negative", (
        "the client-facing cacheStatus contract must not change"
    )
    assert [e["outcome"] for e in _lookup_events(cache_path)] == [
        "negative",
        "negative_cached",
    ]
