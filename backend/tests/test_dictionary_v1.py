from __future__ import annotations

import sqlite3
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest

from kg.cards import CardStore


def _provider_payload(word: str = "invoke") -> dict:
    return {
        "word": word,
        "entries": [
            {
                "language": {"code": "en", "name": "English"},
                "partOfSpeech": "verb",
                "pronunciations": [{"type": "ipa", "text": "/ɪnˈvəʊk/", "tags": []}],
                "forms": [{"word": "invoked", "tags": ["past"]}],
                "senses": [
                    {
                        "definition": "To call upon for help or support.",
                        "examples": ["They invoked an old rule."],
                        "quotes": [{"text": "must not persist", "reference": "book"}],
                        "synonyms": ["appeal to"],
                        "antonyms": [],
                        "translations": [
                            {"language": {"code": "zh", "name": "Chinese"}, "word": "援引"}
                        ],
                        "subsenses": [],
                    }
                ],
                "synonyms": [],
                "antonyms": [],
            }
        ],
        "source": {
            "url": f"https://en.wiktionary.org/wiki/{word}",
            "license": {
                "name": "CC BY-SA 4.0",
                "url": "https://creativecommons.org/licenses/by-sa/4.0/",
            },
        },
    }


def test_card_schema_migrates_dictionary_fields_and_defaults_old_cards(tmp_path):
    db = tmp_path / "cards.db"
    store = CardStore(db)
    old = store.add("legacy", "舊卡")
    store.close()

    # Rebuild a true pre-feature card table without any dictionary columns or
    # sidecars, then open CardStore twice to prove migration idempotence.
    with sqlite3.connect(db) as conn:
        new_columns = {
            "card_role", "review_eligible", "reader_hidden", "promotion_state", "promoted_at"
        }
        old_columns = [
            row[1] for row in conn.execute("PRAGMA table_info(card)") if row[1] not in new_columns
        ]
        projection = ", ".join(f'"{column}"' for column in old_columns)
        conn.execute("ALTER TABLE card RENAME TO card_dictionary_v1")
        conn.execute(f"CREATE TABLE card AS SELECT {projection} FROM card_dictionary_v1")
        conn.execute("DROP TABLE card_dictionary_v1")
        conn.execute("DROP TABLE dictionary_entry")
        conn.execute("DROP TABLE lexical_operations")
        conn.commit()

    CardStore(db).close()
    migrated = CardStore(db)
    migrated_old = migrated.get(old.id)
    migrated.close()

    with sqlite3.connect(db) as conn:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(card)")}
        assert {"card_role", "review_eligible", "reader_hidden", "promotion_state", "promoted_at"} <= cols
        row = conn.execute(
            "SELECT card_role, review_eligible, reader_hidden, promotion_state, promoted_at "
            "FROM card WHERE id = ?",
            (old.id,),
        ).fetchone()
        assert row == ("learning", 1, 0, "idle", None)
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"dictionary_entry", "lexical_operations"} <= tables
    assert migrated_old is not None
    assert (migrated_old.card_role, migrated_old.review_eligible, migrated_old.reader_hidden) == (
        "learning", True, False
    )


def test_free_dictionary_provider_normalizes_without_quotes_and_stable_ids():
    from kg.lexical import FreeDictionaryProvider

    payload = _provider_payload()
    transport = httpx.MockTransport(lambda _request: httpx.Response(200, json=payload))
    provider = FreeDictionaryProvider(client=httpx.Client(transport=transport))

    first = provider.search("invoke", source_language="en", target_language="zh-Hant")
    second = provider.search("invoke", source_language="en", target_language="zh-Hant")

    assert first.entry_key == second.entry_key
    assert [sense.key for sense in first.senses] == [sense.key for sense in second.senses]
    assert first.senses[0].examples[0].key == second.senses[0].examples[0].key
    assert first.word == "invoke"
    assert first.entry_key.startswith("en.")
    assert first.senses[0].translations == ["援引"]
    assert first.senses[0].examples[0].text == "They invoked an old rule."
    assert "must not persist" not in first.model_dump_json()
    assert first.attribution.provider == "free_dictionary"
    assert first.attribution.license_name == "CC BY-SA 4.0"


def test_legacy_vocab_projection_excludes_dictionary_cards_and_their_links(tmp_path):
    from kg.graph import GraphStore, LinkKind
    from kg.vocab_crud import list_vocab_cards

    cards = CardStore(tmp_path / "cards.db")
    learning = cards.add("learn", "學習", notebook_id="default")
    reference = cards.add(
        "invoke",
        "援引",
        notebook_id="default",
        card_role="dictionary",
        review_eligible=False,
    )
    graph = GraphStore(tmp_path / "graph.json", tmp_path / "candidates.json", tmp_path / "blocked.json")
    graph.add_link(learning.id, reference.id, LinkKind.SHARES_USAGE, 1.0, "related")

    def projection(card, _graph, cards_by_id):
        return SimpleNamespace(
            id=card.id,
            links=[other.id for other in cards_by_id.values() if other.id != card.id],
        )

    result, _ = list_vocab_cards(
        since=None,
        cards_store=cards,
        graph=graph,
        card_response_builder=projection,
        notebook_id="default",
        limit=100,
    )
    assert [item.id for item in result] == [learning.id]
    assert result[0].links == []


def test_graph_links_projection_defaults_learning_only_and_opt_in_is_complete(tmp_path):
    from kg.graph import GraphStore, LinkKind
    from kg.vocab_graph import graph_links_payload

    cards = CardStore(tmp_path / "cards.db")
    first = cards.add("one", "一", notebook_id="default")
    second = cards.add("two", "二", notebook_id="default")
    reference = cards.add(
        "invoke", "援引", notebook_id="default", card_role="dictionary", review_eligible=False
    )
    graph = GraphStore(tmp_path / "graph.json", tmp_path / "candidates.json")
    graph.add_link(first.id, second.id, LinkKind.SHARES_USAGE, 1.0, "learning")
    graph.add_link(first.id, reference.id, LinkKind.SHARES_USAGE, 1.0, "dictionary")

    legacy = graph_links_payload(graph=graph, cards_store=cards)
    complete = graph_links_payload(graph=graph, cards_store=cards, include_dictionary=True)
    assert {link.reason for link in legacy} == {"learning"}
    assert {link.reason for link in complete} == {"learning", "dictionary"}


def test_provider_traversal_is_bounded_and_truncation_is_truthful():
    from kg.lexical import MAX_SENSES, FreeDictionaryProvider

    payload = _provider_payload()
    # Exactly MAX_SENSES valid senses is not truncation.
    base = payload["entries"][0]["senses"][0]
    payload["entries"][0]["senses"] = [
        {**base, "definition": f"definition {index}", "examples": [f"example {index}"]}
        for index in range(MAX_SENSES)
    ]
    provider = FreeDictionaryProvider(
        client=httpx.Client(transport=httpx.MockTransport(lambda _r: httpx.Response(200, json=payload)))
    )
    exact = provider.search("invoke", source_language="en", target_language="zh-Hant")
    assert exact is not None and exact.truncated is False

    payload["entries"][0]["senses"].append(
        {**base, "definition": "one too many", "examples": ["extra"]}
    )
    capped = provider.search("invoke", source_language="en", target_language="zh-Hant")
    assert capped is not None and len(capped.senses) == MAX_SENSES and capped.truncated is True

    # Excess examples and excessive recursive depth are cut safely and marked.
    deep = {**base, "definition": "deep", "examples": [str(i) for i in range(20)]}
    cursor = deep
    for depth in range(30):
        child = {**base, "definition": f"nested {depth}", "examples": []}
        cursor["subsenses"] = [child]
        cursor = child
    payload["entries"][0]["senses"] = [deep]
    bounded = provider.search("invoke", source_language="en", target_language="zh-Hant")
    assert bounded is not None and bounded.truncated is True
    assert len(bounded.senses[0].examples) == 5
    assert len(bounded.senses) <= MAX_SENSES


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
        client=httpx.Client(transport=httpx.MockTransport(lambda _r: httpx.Response(200, json=payload)))
    )
    with pytest.raises(ExternalServiceError):
        provider.search("invoke", source_language="en", target_language="zh-Hant")


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
    first = LexicalService(
        provider=provider, cache=LexicalCache(cache_path), provider_hourly_limit=1
    )
    second = LexicalService(
        provider=provider, cache=LexicalCache(cache_path), provider_hourly_limit=1
    )
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


def test_negative_lookup_is_cached_for_24_hours(tmp_path):
    from kg.lexical import FreeDictionaryProvider, LexicalCache, LexicalService

    calls = 0

    def responder(_request):
        nonlocal calls
        calls += 1
        return httpx.Response(404)

    cache = LexicalCache(tmp_path / "lexical_cache.db")
    service = LexicalService(
        provider=FreeDictionaryProvider(
            client=httpx.Client(transport=httpx.MockTransport(responder))
        ),
        cache=cache,
    )
    assert service.search("missing", source_language="en", target_language="zh-Hant").cache_status == "negative"
    assert service.search("missing", source_language="en", target_language="zh-Hant").cache_status == "negative"
    assert calls == 1
    with sqlite3.connect(cache.path) as conn:
        fetched_at, expires_at = conn.execute(
            "SELECT fetched_at, expires_at FROM lexical_cache"
        ).fetchone()
    assert datetime.fromisoformat(expires_at) - datetime.fromisoformat(fetched_at) == timedelta(
        hours=24
    )


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
        provider=FreeDictionaryProvider(
            client=httpx.Client(transport=httpx.MockTransport(responder))
        ),
        cache=cache,
    )
    assert service.search("invoke", source_language="en", target_language="zh-Hant").entry
    with sqlite3.connect(cache.path) as conn:
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
                transport=httpx.MockTransport(
                    lambda _request: (_ for _ in ()).throw(httpx.ReadTimeout("timed out"))
                )
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
                        200, content=b"{not-json", headers={"Content-Type": "application/json"}
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
        client=httpx.Client(
            transport=httpx.MockTransport(lambda _r: httpx.Response(200, json=payload))
        )
    )
    entry = provider.search("invoke", source_language="en", target_language="zh-Hant")
    assert entry is not None and entry.truncated is True
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
        provider=FreeDictionaryProvider(
            client=httpx.Client(transport=httpx.MockTransport(responder))
        ),
        cache=cache,
        provider_hourly_limit=1,
    )
    assert service.search("invoke", source_language="en", target_language="zh-Hant").entry
    with sqlite3.connect(cache.path) as conn:
        conn.execute(
            "UPDATE lexical_cache SET expires_at = ?",
            ((datetime.now(UTC) - timedelta(seconds=1)).isoformat(),),
        )

    clock = 3601.0  # Crosses an hour boundary, but the first call is only two seconds old.
    stale = service.search("invoke", source_language="en", target_language="zh-Hant")
    assert stale.cache_status == "stale"
    with pytest.raises(ExternalServiceError):
        service.search("other", source_language="en", target_language="zh-Hant")
    assert calls == 1

    clock = 7200.0
    assert service.search("other", source_language="en", target_language="zh-Hant").entry
    assert calls == 2


def test_dictionary_cache_uses_fresh_hit_and_stale_on_provider_failure(tmp_path):
    from kg.lexical import FreeDictionaryProvider, LexicalCache, LexicalService

    calls = 0

    def responder(_request):
        nonlocal calls
        calls += 1
        if calls > 1:
            return httpx.Response(503, json={"error": "unavailable"})
        return httpx.Response(200, json=_provider_payload())

    provider = FreeDictionaryProvider(client=httpx.Client(transport=httpx.MockTransport(responder)))
    cache = LexicalCache(tmp_path / "lexical_cache.db", positive_ttl=timedelta(days=30))
    service = LexicalService(provider=provider, cache=cache)

    first = service.search("invoke", source_language="en", target_language="zh-Hant")
    assert first.cache_status == "miss"
    assert service.search("invoke", source_language="en", target_language="zh-Hant").cache_status == "fresh"
    assert calls == 1

    with sqlite3.connect(cache.path) as conn:
        conn.execute(
            "UPDATE lexical_cache SET expires_at = ?",
            ((datetime.now(UTC) - timedelta(seconds=1)).isoformat(),),
        )
        conn.commit()
    stale = service.search("invoke", source_language="en", target_language="zh-Hant")
    assert stale.cache_status == "stale"
    assert stale.entry is not None
    assert calls == 2


def test_dictionary_search_endpoint_requires_flag_and_returns_provider_neutral_payload(
    isolated_api, monkeypatch
):
    import kg.routers.dictionary as dictionary_router
    from kg.lexical import FreeDictionaryProvider, LexicalCache, LexicalService

    provider = FreeDictionaryProvider(
        client=httpx.Client(transport=httpx.MockTransport(lambda _r: httpx.Response(200, json=_provider_payload())))
    )
    service = LexicalService(
        provider=provider,
        cache=LexicalCache(isolated_api.data_dir / "lexical_cache.db"),
    )
    monkeypatch.setattr(dictionary_router, "_lexical_service", lambda _settings: service)

    disabled = isolated_api.client.get(
        "/api/dictionary/search?q=invoke&source_lang=en&target_lang=zh-Hant",
        headers=isolated_api.headers,
    )
    assert disabled.status_code == 403

    isolated_api.client.app.state.kg_settings = replace(
        isolated_api.client.app.state.kg_settings,
        dictionary_lookup_enabled=True,
    )
    response = isolated_api.client.get(
        "/api/dictionary/search?q=invoke&source_lang=en&target_lang=zh-Hant",
        headers=isolated_api.headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["cacheStatus"] == "miss"
    assert body["hits"][0]["provider"] == "free_dictionary"
    assert body["hits"][0]["word"] == "invoke"


@pytest.mark.asyncio
async def test_dictionary_cards_are_excluded_from_general_pipeline(tmp_path):
    from kg.pipeline_service.steps import _step_difficulty, _step_enrich

    cards = CardStore(tmp_path / "cards.db")
    reference = cards.add(
        "invoke", "援引", notebook_id="default", card_role="dictionary", review_eligible=False
    )
    user = {"id": "u1", "dir": tmp_path}
    logger = SimpleNamespace(info=lambda *_args: None, warning=lambda *_args: None)

    enriched = await _step_enrich(
        "u1",
        user,
        card_store_factory=lambda _path: cards,
        client_factory=lambda _provider: pytest.fail("dictionary card reached enrich provider"),
        logger=logger,
    )
    scored = await _step_difficulty(
        "u1", user, card_store_factory=lambda _path: cards, logger=logger
    )
    assert (enriched, scored) == (0, 0)
    assert cards.get(reference.id).difficulty is None


def test_dictionary_cards_reject_review_state_updates(tmp_path):
    from kg.api_models import ReviewStateEntry
    from kg.vocab_review import push_review_states

    cards = CardStore(tmp_path / "cards.db")
    reference = cards.add(
        "invoke", "援引", notebook_id="default", card_role="dictionary", review_eligible=False
    )
    result = push_review_states(
        [
            ReviewStateEntry(
                word="invoke",
                card_id=reference.id,
                review_interval_hours=24,
                next_review_at="2026-08-06T00:00:00Z",
                last_reviewed_at="2026-08-05T00:00:00Z",
                review_count=1,
                lapse_count=0,
                review_streak=1,
                last_review_feedback=1,
            )
        ],
        cards_store=cards,
        logger=SimpleNamespace(warning=lambda *_args: None),
    )
    assert result == {"updated": 0, "skipped": 1}
    assert cards.get(reference.id).review_count == 0


def test_all_legacy_vocab_lookup_and_mutation_paths_hide_dictionary_cards(tmp_path):
    from kg.exceptions import NotFoundError
    from kg.vocab_crud import (
        archive_vocab_word,
        batch_archive_vocab_words,
        batch_delete_vocab_words,
        delete_vocab_word,
        lookup_vocab_word,
        update_vocab_word_content,
    )

    cards = CardStore(tmp_path / "cards.db")
    reference = cards.add(
        "invoke", "援引", notebook_id="default", card_role="dictionary", review_eligible=False
    )
    graph = SimpleNamespace(get_links_for=lambda _card_id: [])

    def builder(card, _graph, _cards):
        return SimpleNamespace(id=card.id)

    with pytest.raises(NotFoundError):
        lookup_vocab_word(
            "invoke", cards_store=cards, graph=graph, card_response_builder=builder,
            notebook_id="default",
        )
    with pytest.raises(NotFoundError):
        update_vocab_word_content(
            "invoke", meaning="改寫", note=None, explanation=None,
            cards_store=cards, graph=graph, card_response_builder=builder,
            notebook_id="default",
        )
    with pytest.raises(NotFoundError):
        archive_vocab_word(
            "invoke", archived=True, cards_store=cards, notebook_id="default"
        )
    with pytest.raises(NotFoundError):
        delete_vocab_word("invoke", cards_store=cards, notebook_id="default")

    deleted = batch_delete_vocab_words(
        ["invoke"], cards_store=cards, notebook_id="default"
    )
    archived = batch_archive_vocab_words(
        ["invoke"], archived=True, cards_store=cards, notebook_id="default"
    )
    assert deleted["not_found"] == ["invoke"]
    assert archived["not_found"] == ["invoke"]
    assert cards.get(reference.id).is_deleted is False
    assert cards.get(reference.id).is_archived is False


def test_legacy_lookup_does_not_project_dictionary_neighbour(tmp_path):
    from kg.graph import GraphStore, LinkKind
    from kg.vocab_crud import lookup_vocab_word

    cards = CardStore(tmp_path / "cards.db")
    learning = cards.add("learn", "學習", notebook_id="default")
    reference = cards.add(
        "invoke", "援引", notebook_id="default", card_role="dictionary", review_eligible=False
    )
    graph = GraphStore(tmp_path / "graph.json", tmp_path / "candidates.json")
    graph.add_link(learning.id, reference.id, LinkKind.SHARES_USAGE, 1.0, "related")

    response = lookup_vocab_word(
        "learn",
        cards_store=cards,
        graph=graph,
        card_response_builder=lambda _card, _graph, by_id: sorted(by_id),
        notebook_id="default",
    )
    assert response == [learning.id]


def test_dictionary_detail_is_rate_limited_and_v1_languages_are_locked(
    isolated_api, monkeypatch
):
    import kg.routers.dictionary as dictionary_router
    from kg.lexical import (
        FreeDictionaryProvider,
        LexicalCache,
        LexicalService,
        dictionary_rate_limiter,
    )

    provider = FreeDictionaryProvider(
        client=httpx.Client(
            transport=httpx.MockTransport(lambda _r: httpx.Response(200, json=_provider_payload()))
        )
    )
    service = LexicalService(
        provider=provider,
        cache=LexicalCache(isolated_api.data_dir / "lexical_cache.db"),
    )
    monkeypatch.setattr(dictionary_router, "_lexical_service", lambda _settings: service)
    monkeypatch.setattr(dictionary_rate_limiter, "limit", 3)
    dictionary_rate_limiter.reset()
    isolated_api.client.app.state.kg_settings = replace(
        isolated_api.client.app.state.kg_settings,
        dictionary_lookup_enabled=True,
    )

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
    assert limited.status_code == 429
    assert limited.headers["Retry-After"] == "60"
    assert unsupported_source.status_code == 422
    assert unsupported_target.status_code == 422


def test_legacy_vocab_add_conflicts_without_leaking_existing_dictionary_id(tmp_path):
    from kg.api_models import VocabEntry
    from kg.exceptions import ConflictError
    from kg.vocab_intake import add_vocab_entries

    cards = CardStore(tmp_path / "cards.db")
    reference = cards.add(
        "invoke", "援引", notebook_id="default", card_role="dictionary", review_eligible=False
    )
    graph = SimpleNamespace(add_pending_judge=lambda _ids: None)
    embeddings = SimpleNamespace(has=lambda _id: False, add_batch=lambda _items: None)
    logger = SimpleNamespace(warning=lambda *_args: None)

    with pytest.raises(ConflictError) as exc_info:
        add_vocab_entries(
            [VocabEntry(word="invoke", translation="調用")],
            user={"id": "u1", "dir": tmp_path},
            cards=cards,
            embeddings=embeddings,
            graph=graph,
            logger=logger,
            notebook_id="default",
        )
    assert reference.id not in str(exc_info.value)

    with pytest.raises(ConflictError):
        cards.add("invoke", "調用", notebook_id="default")
    assert cards.get(reference.id).card_role == "dictionary"
