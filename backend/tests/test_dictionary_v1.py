from __future__ import annotations

import sqlite3
import threading
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


def _lexical_entry(word: str = "invoke"):
    from kg.lexical import FreeDictionaryProvider

    provider = FreeDictionaryProvider(
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda _request: httpx.Response(200, json=_provider_payload(word))
            )
        )
    )
    return provider.search(word, source_language="en", target_language="zh-Hant")


class _CanonicalLexical:
    def __init__(self, entry):
        self.entry = entry
        self.calls = 0

    def get_entry(self, provider, entry_key, *, target_language="zh-Hant"):
        from kg.lexical import LexicalLookupResult

        self.calls += 1
        assert provider == self.entry.provider
        assert entry_key == self.entry.entry_key
        return LexicalLookupResult(entry=self.entry, cache_status="fresh")


class _Judge:
    def __init__(self):
        self.calls = 0

    def evaluate(self, *_args, **_kwargs):
        from kg.judge.models import Judgement

        self.calls += 1
        return Judgement(link="shares_usage", confidence=1.0, reason="same context")


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
    entry = _lexical_entry()
    sense = entry.senses[0]
    reference, _ = cards.stage_dictionary_card(
        entry=entry,
        notebook_id="default",
        sense_key=sense.key,
        example_key=sense.examples[0].key,
    )
    cards.begin_lexical_operation("graph-projection", "fixture")
    cards.activate_dictionary_entry_and_complete_operation(
        card_id=reference.id,
        idempotency_key="graph-projection",
        response_json="{}",
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
    dictionary_router.dictionary_lookup_leases.reset()
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


def test_explicit_dictionary_search_and_its_first_detail_share_one_admission(
    isolated_api, monkeypatch
):
    import kg.routers.dictionary as dictionary_router
    from kg.lexical import FreeDictionaryProvider, LexicalCache, LexicalService, dictionary_rate_limiter

    provider = FreeDictionaryProvider(
        client=httpx.Client(
            transport=httpx.MockTransport(lambda _r: httpx.Response(200, json=_provider_payload()))
        )
    )
    service = LexicalService(
        provider=provider,
        cache=LexicalCache(isolated_api.data_dir / "lexical_cache-admission.db"),
    )
    monkeypatch.setattr(dictionary_router, "_lexical_service", lambda _settings: service)
    monkeypatch.setattr(dictionary_rate_limiter, "limit", 1)
    dictionary_rate_limiter.reset()
    dictionary_router.dictionary_lookup_leases.reset()
    isolated_api.client.app.state.kg_settings = replace(
        isolated_api.client.app.state.kg_settings,
        dictionary_lookup_enabled=True,
    )

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


def test_dictionary_entry_endpoint_returns_404_for_cached_negative_lookup(
    isolated_api, monkeypatch
):
    import kg.routers.dictionary as dictionary_router
    from kg.lexical import FreeDictionaryProvider, LexicalCache, LexicalService

    service = LexicalService(
        provider=FreeDictionaryProvider(
            client=httpx.Client(
                transport=httpx.MockTransport(lambda _request: httpx.Response(404))
            )
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


def _dictionary_service(tmp_path, *, entry=None, crash_hook=None):
    from kg.dictionary_cards import DictionaryCardService
    from kg.graph import GraphStore

    cards = CardStore(tmp_path / "cards.db")
    graph = GraphStore(
        tmp_path / "graph.json", tmp_path / "candidates.json", tmp_path / "blocked.json"
    )
    lexical = _CanonicalLexical(entry or _lexical_entry())
    judge = _Judge()
    service = DictionaryCardService(
        cards=cards, graph=graph, lexical=lexical, judge=judge, crash_hook=crash_hook
    )
    return service, cards, graph, lexical, judge


def _materialize_request(source_id: str, entry, **overrides):
    sense = entry.senses[0]
    values = {
        "source_card_id": source_id,
        "notebook_id": "default",
        "provider": entry.provider,
        "entry_key": entry.entry_key,
        "sense_key": sense.key,
        "example_key": sense.examples[0].key,
    }
    values.update(overrides)
    return values


def test_dictionary_materialize_link_fresh_replay_and_reuse_pinned_selection(tmp_path):
    service, cards, graph, lexical, judge = _dictionary_service(tmp_path)
    source = cards.add("summon", "召喚", notebook_id="default")
    request = _materialize_request(source.id, lexical.entry)

    fresh = service.materialize_and_link(idempotency_key="op-1", **request)
    replay = service.materialize_and_link(idempotency_key="op-1", **request)
    reused = service.materialize_and_link(
        idempotency_key="op-2",
        **{**request, "sense_key": "stale-client-sense", "example_key": "stale-client-example"},
    )

    target = cards.get(fresh.target_card.id)
    assert target is not None
    assert (target.card_role, target.review_eligible, target.reader_hidden) == (
        "dictionary", False, False
    )
    assert fresh.created_card is True and fresh.created_link is True and fresh.replayed is False
    assert replay.target_card.id == fresh.target_card.id and replay.replayed is True
    assert reused.target_card.id == fresh.target_card.id
    assert reused.created_card is False and reused.created_link is False
    assert graph.find_link_between(source.id, target.id).id == fresh.link.id
    assert len(list(cards.all())) == 2
    assert judge.calls == 2
    assert lexical.calls == 2

    detail = service.get_saved_card(target.id)
    assert detail.selected_sense_key == lexical.entry.senses[0].key
    assert detail.selected_example_key == lexical.entry.senses[0].examples[0].key
    assert detail.entry.attribution.license_name == "CC BY-SA 4.0"
    assert detail.materialization_status == "active"


def test_dictionary_materialize_reuses_learning_card_without_sidecar_or_demotion(tmp_path):
    service, cards, graph, lexical, _judge = _dictionary_service(tmp_path)
    source = cards.add("summon", "召喚", notebook_id="default")
    learning = cards.add("invoke", "援引（已學習）", notebook_id="default")

    result = service.materialize_and_link(
        idempotency_key="learning-reuse",
        **_materialize_request(source.id, lexical.entry),
    )

    assert result.target_card.id == learning.id
    assert result.created_card is False and result.created_link is True
    assert cards.get(learning.id).card_role == "learning"
    assert cards.get_dictionary_entry(learning.id) is None
    assert graph.find_link_between(source.id, learning.id) is not None


def test_dictionary_materialize_rejects_idempotency_mismatch_self_and_cross_notebook(tmp_path):
    from kg.exceptions import ConflictError, NotFoundError

    service, cards, _graph, lexical, _judge = _dictionary_service(tmp_path)
    source = cards.add("summon", "召喚", notebook_id="default")
    request = _materialize_request(source.id, lexical.entry)
    service.materialize_and_link(idempotency_key="same-key", **request)

    with pytest.raises(ConflictError):
        service.materialize_and_link(
            idempotency_key="same-key", **{**request, "example_key": "different"}
        )
    self_service, _, _, self_lexical, _ = _dictionary_service(
        tmp_path, entry=_lexical_entry("summon")
    )
    with pytest.raises(ConflictError):
        self_service.materialize_and_link(
            idempotency_key="self-link",
            **_materialize_request(source.id, self_lexical.entry),
        )

    foreign = cards.add("foreign", "外部", notebook_id="other")
    with pytest.raises(NotFoundError):
        service.materialize_and_link(
            idempotency_key="cross-notebook",
            **_materialize_request(foreign.id, lexical.entry),
        )


@pytest.mark.parametrize("crash_step", ["after_card_stage", "after_graph_write", "after_touch"])
def test_dictionary_materialize_crash_recovery_converges(tmp_path, crash_step):
    crashed = False

    def crash_hook(step):
        nonlocal crashed
        if step == crash_step and not crashed:
            crashed = True
            raise RuntimeError("injected crash")

    service, cards, graph, lexical, _judge = _dictionary_service(
        tmp_path, crash_hook=crash_hook
    )
    source = cards.add("summon", "召喚", notebook_id="default")
    request = _materialize_request(source.id, lexical.entry)
    with pytest.raises(RuntimeError, match="injected crash"):
        service.materialize_and_link(idempotency_key="recover", **request)

    assert service.list_projection(notebook_id="default", limit=100).items == []
    from kg.vocab_graph import graph_links_payload
    assert graph_links_payload(
        graph=graph, cards_store=cards, include_dictionary=True
    ) == []

    result = service.materialize_and_link(idempotency_key="recover", **request)
    assert result.replayed is False
    assert len([c for c in cards.all() if c.content.casefold() == "invoke"]) == 1
    assert len(graph.all_links()) == 1
    assert service.get_saved_card(result.target_card.id).materialization_status == "active"
    assert service.get_operation("recover").status == "completed"


def test_dictionary_selection_visibility_and_incremental_projection(tmp_path):
    from kg.exceptions import ConflictError
    from kg.lexical import LexicalExample, LexicalSense

    entry = _lexical_entry()
    second = LexicalSense(
        key="sense_second",
        part_of_speech="verb",
        definition="To cite as authority.",
        examples=[LexicalExample(key="example_second", text="Counsel invoked precedent.")],
        translations=["援引"],
    )
    entry.senses.append(second)
    service, cards, _graph, lexical, _judge = _dictionary_service(tmp_path, entry=entry)
    source = cards.add("summon", "召喚", notebook_id="default")
    result = service.materialize_and_link(
        idempotency_key="select", **_materialize_request(source.id, lexical.entry)
    )
    before = cards.get(result.target_card.id).updated_at

    selected = service.update_selection(
        result.target_card.id,
        sense_key=second.key,
        example_key=second.examples[0].key,
    )
    hidden = service.set_reader_visibility(result.target_card.id, reader_hidden=True)

    assert selected.selected_sense_key == second.key
    assert selected.selected_example_key == second.examples[0].key
    assert hidden.reader_hidden is True
    updated = cards.get(result.target_card.id)
    assert updated.meaning == "援引"
    assert updated.examples == ["Counsel invoked precedent."]
    assert updated.updated_at > before

    projection = service.list_projection(notebook_id="default", limit=100)
    assert [item.card.id for item in projection.items] == [result.target_card.id]
    assert projection.items[0].reader_hidden is True
    assert projection.items[0].dictionary.selected_example_key == "example_second"

    cards.update(result.target_card.id, card_role="learning")
    with pytest.raises(ConflictError):
        service.update_selection(
            result.target_card.id,
            sense_key=entry.senses[0].key,
            example_key=entry.senses[0].examples[0].key,
        )


def test_dictionary_materialize_concurrent_same_request_converges(tmp_path):
    service, cards, graph, lexical, _judge = _dictionary_service(tmp_path)
    source = cards.add("summon", "召喚", notebook_id="default")
    request = _materialize_request(source.id, lexical.entry)
    results = []
    errors = []

    def worker():
        try:
            results.append(
                service.materialize_and_link(idempotency_key="concurrent", **request)
            )
        except Exception as exc:  # pragma: no cover
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    target_ids = {result.target_card.id for result in results}
    assert len(target_ids) == 1
    assert sum(result.replayed for result in results) == 1
    assert len(graph.all_links()) == 1


def test_dictionary_saved_card_api_contract_and_rollout_read_availability(
    isolated_api, monkeypatch
):
    import kg.routers.dictionary as dictionary_router

    entry = _lexical_entry()
    user_dir = isolated_api.data_dir / "users" / isolated_api.user_id
    service, cards, _graph, lexical, _judge = _dictionary_service(user_dir, entry=entry)
    source = cards.add("summon", "召喚", notebook_id="default")
    monkeypatch.setattr(
        dictionary_router,
        "_dictionary_card_service",
        lambda _user, _settings, **_kwargs: service,
    )
    isolated_api.client.app.state.kg_settings = replace(
        isolated_api.client.app.state.kg_settings,
        dictionary_lookup_enabled=True,
    )
    sense = lexical.entry.senses[0]
    payload = {
        "sourceCardId": source.id,
        "notebookId": "default",
        "provider": lexical.entry.provider,
        "entryKey": lexical.entry.entry_key,
        "senseKey": sense.key,
        "exampleKey": sense.examples[0].key,
    }
    created = isolated_api.client.post(
        "/api/graph/links/from-dictionary",
        headers={**isolated_api.headers, "Idempotency-Key": "api-op"},
        json=payload,
    )
    assert created.status_code == 200, created.text
    body = created.json()
    assert body["createdCard"] is True
    assert body["targetCard"]["cardRole"] == "dictionary"
    assert body["dictionaryCard"]["dictionary"]["selectedExampleKey"] == sense.examples[0].key
    card_id = body["targetCard"]["id"]

    # Rollback flag only stops new materialization/search; saved reads and edits remain.
    isolated_api.client.app.state.kg_settings = replace(
        isolated_api.client.app.state.kg_settings,
        dictionary_lookup_enabled=False,
    )
    detail = isolated_api.client.get(
        f"/api/dictionary/cards/{card_id}", headers=isolated_api.headers
    )
    projection = isolated_api.client.get(
        "/api/dictionary-cards?notebook_id=default", headers=isolated_api.headers
    )
    visibility = isolated_api.client.patch(
        f"/api/cards/{card_id}/reader-visibility",
        headers=isolated_api.headers,
        json={"readerHidden": True},
    )
    selection = isolated_api.client.patch(
        f"/api/dictionary/cards/{card_id}/selection",
        headers=isolated_api.headers,
        json={"senseKey": sense.key, "exampleKey": sense.examples[0].key},
    )

    assert detail.status_code == 200
    assert detail.json()["selectedExampleKey"] == sense.examples[0].key
    assert detail.json()["entry"]["attribution"]["license_name"] == "CC BY-SA 4.0"
    assert projection.status_code == 200 and projection.json()[0]["card"]["id"] == card_id
    assert visibility.status_code == 200 and visibility.json()["readerHidden"] is True
    assert selection.status_code == 200

    replay_while_disabled = isolated_api.client.post(
        "/api/graph/links/from-dictionary",
        headers={**isolated_api.headers, "Idempotency-Key": "api-op"},
        json=payload,
    )
    mismatch_while_disabled = isolated_api.client.post(
        "/api/graph/links/from-dictionary",
        headers={**isolated_api.headers, "Idempotency-Key": "api-op"},
        json={**payload, "exampleKey": "different-request"},
    )
    assert replay_while_disabled.status_code == 200
    assert replay_while_disabled.json()["replayed"] is True
    assert mismatch_while_disabled.status_code == 409

    disabled_create = isolated_api.client.post(
        "/api/graph/links/from-dictionary",
        headers={**isolated_api.headers, "Idempotency-Key": "api-op-2"},
        json=payload,
    )
    assert disabled_create.status_code == 403

    import kg.deps_quota as deps_quota
    isolated_api.client.app.state.kg_settings = replace(
        isolated_api.client.app.state.kg_settings,
        dictionary_lookup_enabled=True,
    )
    monkeypatch.setattr(
        deps_quota,
        "_check_quota",
        lambda *_args, **_kwargs: pytest.fail("completed replay reached quota admission"),
    )
    replay_without_quota = isolated_api.client.post(
        "/api/graph/links/from-dictionary",
        headers={**isolated_api.headers, "Idempotency-Key": "api-op"},
        json=payload,
    )
    assert replay_without_quota.status_code == 200


def test_dictionary_materialize_api_requires_idempotency_key_and_rejects_hash_mismatch(
    isolated_api, monkeypatch
):
    import kg.routers.dictionary as dictionary_router

    user_dir = isolated_api.data_dir / "users" / isolated_api.user_id
    service, cards, _graph, lexical, _judge = _dictionary_service(user_dir)
    source = cards.add("summon", "召喚", notebook_id="default")
    monkeypatch.setattr(
        dictionary_router,
        "_dictionary_card_service",
        lambda _user, _settings, **_kwargs: service,
    )
    isolated_api.client.app.state.kg_settings = replace(
        isolated_api.client.app.state.kg_settings,
        dictionary_lookup_enabled=True,
    )
    sense = lexical.entry.senses[0]
    payload = {
        "sourceCardId": source.id,
        "notebookId": "default",
        "provider": lexical.entry.provider,
        "entryKey": lexical.entry.entry_key,
        "senseKey": sense.key,
        "exampleKey": sense.examples[0].key,
    }
    missing = isolated_api.client.post(
        "/api/graph/links/from-dictionary", headers=isolated_api.headers, json=payload
    )
    first = isolated_api.client.post(
        "/api/graph/links/from-dictionary",
        headers={**isolated_api.headers, "Idempotency-Key": "same-api-key"},
        json=payload,
    )
    mismatch = isolated_api.client.post(
        "/api/graph/links/from-dictionary",
        headers={**isolated_api.headers, "Idempotency-Key": "same-api-key"},
        json={**payload, "exampleKey": "not-the-same-request"},
    )
    replay = isolated_api.client.post(
        "/api/graph/links/from-dictionary",
        headers={**isolated_api.headers, "Idempotency-Key": "same-api-key"},
        json=payload,
    )

    assert missing.status_code == 422
    assert first.status_code == 200
    assert mismatch.status_code == 409
    assert replay.status_code == 200 and replay.json()["replayed"] is True


def test_dictionary_projection_cursor_tombstone_role_transfer_and_notebook_isolation(tmp_path):
    from kg.dictionary_cards import DictionaryCardService
    from kg.exceptions import BadRequestError
    from kg.graph import GraphStore

    cards = CardStore(tmp_path / "cards.db")
    graph = GraphStore(tmp_path / "graph.json", tmp_path / "candidates.json")
    service = DictionaryCardService(
        cards=cards,
        graph=graph,
        lexical=_CanonicalLexical(_lexical_entry()),
        judge=_Judge(),
    )

    created = []
    for index, (word, notebook_id) in enumerate(
        [("invoke", "default"), ("evoke", "default"), ("cite", "other")]
    ):
        entry = _lexical_entry(word)
        sense = entry.senses[0]
        card, was_created = cards.stage_dictionary_card(
            entry=entry,
            notebook_id=notebook_id,
            sense_key=sense.key,
            example_key=sense.examples[0].key,
        )
        assert was_created is True
        key = f"projection-{index}"
        cards.begin_lexical_operation(key, f"hash-{index}")
        cards.activate_dictionary_entry_and_complete_operation(
            card_id=card.id,
            idempotency_key=key,
            response_json="{}",
        )
        created.append(card)

    first = service.list_projection(notebook_id="default", limit=1)
    second = service.list_projection(
        notebook_id="default", limit=1, cursor=first.next_cursor
    )
    assert len(first.items) == len(second.items) == 1
    assert first.items[0].card.id != second.items[0].card.id
    assert second.next_cursor is None

    watermark = max(cards.get(created[0].id).updated_at, cards.get(created[1].id).updated_at)
    cards.update(created[0].id, card_role="learning", review_eligible=True)
    cards.delete(created[1].id)
    delta = service.list_projection(
        notebook_id="default", limit=10, since=watermark
    )
    assert {item.card.id for item in delta.items} == {created[0].id, created[1].id}
    assert any(item.card.card_role == "learning" for item in delta.items)
    assert any(item.card.is_deleted for item in delta.items)
    assert created[2].id not in {item.card.id for item in delta.items}

    with pytest.raises(BadRequestError):
        service.list_projection(notebook_id="default", limit=10, cursor="not-a-cursor")


def test_dictionary_materialize_api_rejects_foreign_notebook_before_provider_call(isolated_api):
    isolated_api.client.app.state.kg_settings = replace(
        isolated_api.client.app.state.kg_settings,
        dictionary_lookup_enabled=True,
    )
    response = isolated_api.client.post(
        "/api/graph/links/from-dictionary",
        headers={**isolated_api.headers, "Idempotency-Key": "foreign-notebook"},
        json={
            "sourceCardId": "missing",
            "notebookId": "not-owned",
            "provider": "free_dictionary",
            "entryKey": "en.aW52b2tl",
            "senseKey": "sense",
            "exampleKey": "example",
        },
    )
    assert response.status_code == 403


def test_dictionary_saga_retry_with_persisted_judgement_skips_quota_readmission(
    isolated_api, monkeypatch
):
    import kg.deps_quota as deps_quota
    import kg.routers.dictionary as dictionary_router

    crashed = False

    def crash_once(step):
        nonlocal crashed
        if step == "after_card_stage" and not crashed:
            crashed = True
            raise RuntimeError("injected crash")

    user_dir = isolated_api.data_dir / "users" / isolated_api.user_id
    service, cards, _graph, lexical, judge = _dictionary_service(
        user_dir, crash_hook=crash_once
    )
    source = cards.add("summon", "召喚", notebook_id="default")
    monkeypatch.setattr(
        dictionary_router,
        "_dictionary_card_service",
        lambda _user, _settings, **_kwargs: service,
    )
    isolated_api.client.app.state.kg_settings = replace(
        isolated_api.client.app.state.kg_settings,
        dictionary_lookup_enabled=True,
    )
    sense = lexical.entry.senses[0]
    payload = {
        "sourceCardId": source.id,
        "notebookId": "default",
        "provider": lexical.entry.provider,
        "entryKey": lexical.entry.entry_key,
        "senseKey": sense.key,
        "exampleKey": sense.examples[0].key,
    }
    first = isolated_api.client.post(
        "/api/graph/links/from-dictionary",
        headers={**isolated_api.headers, "Idempotency-Key": "resume-after-judge"},
        json=payload,
    )
    assert first.status_code == 500
    assert judge.calls == 1

    monkeypatch.setattr(
        deps_quota,
        "_check_quota",
        lambda *_args, **_kwargs: pytest.fail("resumable saga reached quota admission"),
    )
    resumed = isolated_api.client.post(
        "/api/graph/links/from-dictionary",
        headers={**isolated_api.headers, "Idempotency-Key": "resume-after-judge"},
        json=payload,
    )
    assert resumed.status_code == 200, resumed.text
    assert judge.calls == 1
    assert service.get_operation("resume-after-judge").status == "completed"


def test_saved_dictionary_routes_are_db_only_when_lookup_rollout_is_disabled(
    isolated_api, monkeypatch
):
    import kg.routers.dictionary as dictionary_router

    user_dir = isolated_api.data_dir / "users" / isolated_api.user_id
    cards = dictionary_router._card_store(user_dir)
    entry = _lexical_entry()
    sense = entry.senses[0]
    card, _ = cards.stage_dictionary_card(
        entry=entry,
        notebook_id="default",
        sense_key=sense.key,
        example_key=sense.examples[0].key,
    )
    cards.begin_lexical_operation("db-only-fixture", "fixture")
    cards.activate_dictionary_entry_and_complete_operation(
        card_id=card.id,
        idempotency_key="db-only-fixture",
        response_json="{}",
    )
    isolated_api.client.app.state.kg_settings = replace(
        isolated_api.client.app.state.kg_settings,
        dictionary_lookup_enabled=False,
        dictionary_provider_default="unavailable-provider",
    )
    monkeypatch.setattr(
        dictionary_router,
        "_lexical_service",
        lambda _settings: pytest.fail("saved route constructed lexical provider"),
    )
    monkeypatch.setattr(
        dictionary_router,
        "_manual_judge",
        lambda *_args, **_kwargs: pytest.fail("saved route constructed manual judge"),
    )

    detail = isolated_api.client.get(
        f"/api/dictionary/cards/{card.id}", headers=isolated_api.headers
    )
    projection = isolated_api.client.get(
        "/api/dictionary-cards?notebook_id=default", headers=isolated_api.headers
    )
    selected = isolated_api.client.patch(
        f"/api/dictionary/cards/{card.id}/selection",
        headers=isolated_api.headers,
        json={"senseKey": sense.key, "exampleKey": sense.examples[0].key},
    )
    visibility = isolated_api.client.patch(
        f"/api/cards/{card.id}/reader-visibility",
        headers=isolated_api.headers,
        json={"readerHidden": True},
    )

    assert detail.status_code == 200, detail.text
    assert projection.status_code == 200, projection.text
    assert selected.status_code == 200, selected.text
    assert visibility.status_code == 200, visibility.text


def test_disabled_rollout_finishes_an_interrupted_saga_but_still_blocks_new_ones(
    isolated_api, monkeypatch
):
    """Rolling back mid-flight must not wedge a staged card.

    The judge already ran and the card already holds the notebook's unique
    content slot, so the flag has no new work left to stop — only a staged row
    that ``get_saved_card`` refuses to return. Finishing it is the rollback
    contract; admitting a *new* materialization is not.
    """
    import kg.routers.dictionary as dictionary_router

    crashed = False

    def crash_once(step):
        nonlocal crashed
        if step == "after_card_stage" and not crashed:
            crashed = True
            raise RuntimeError("injected crash")

    user_dir = isolated_api.data_dir / "users" / isolated_api.user_id
    service, cards, _graph, lexical, judge = _dictionary_service(
        user_dir, crash_hook=crash_once
    )
    source = cards.add("summon", "召喚", notebook_id="default")
    monkeypatch.setattr(
        dictionary_router,
        "_dictionary_card_service",
        lambda _user, _settings, **_kwargs: service,
    )
    isolated_api.client.app.state.kg_settings = replace(
        isolated_api.client.app.state.kg_settings,
        dictionary_lookup_enabled=True,
    )
    sense = lexical.entry.senses[0]
    payload = {
        "sourceCardId": source.id,
        "notebookId": "default",
        "provider": lexical.entry.provider,
        "entryKey": lexical.entry.entry_key,
        "senseKey": sense.key,
        "exampleKey": sense.examples[0].key,
    }
    first = isolated_api.client.post(
        "/api/graph/links/from-dictionary",
        headers={**isolated_api.headers, "Idempotency-Key": "resume-while-disabled"},
        json=payload,
    )
    assert first.status_code == 500
    assert judge.calls == 1
    staged = cards.find_by_content(lexical.entry.word, notebook_id="default")
    assert staged is not None
    assert cards.get_dictionary_entry(staged.id).materialization_status == "staged"

    isolated_api.client.app.state.kg_settings = replace(
        isolated_api.client.app.state.kg_settings,
        dictionary_lookup_enabled=False,
    )
    resumed = isolated_api.client.post(
        "/api/graph/links/from-dictionary",
        headers={**isolated_api.headers, "Idempotency-Key": "resume-while-disabled"},
        json=payload,
    )
    assert resumed.status_code == 200, resumed.text
    assert judge.calls == 1
    assert cards.get_dictionary_entry(staged.id).materialization_status == "active"

    fresh_start = isolated_api.client.post(
        "/api/graph/links/from-dictionary",
        headers={**isolated_api.headers, "Idempotency-Key": "new-while-disabled"},
        json=payload,
    )
    assert fresh_start.status_code == 403


def test_disabled_rollout_resume_serves_the_entry_from_cache_without_the_provider(
    tmp_path,
):
    """Cache-only mode is what makes the resume above safe to admit.

    Without it a rolled-back deployment could still reach the provider through
    a resumed saga whose cached entry had expired.
    """
    from kg.exceptions import ForbiddenError
    from kg.lexical import LexicalCache, LexicalService

    entry = _lexical_entry()

    class _ExplodingProvider:
        provider_id = entry.provider
        dictionary_id = entry.dictionary_id
        schema_version = entry.schema_version
        capabilities = __import__(
            "kg.lexical", fromlist=["LexicalProviderCapabilities"]
        ).LexicalProviderCapabilities(
            exact_lookup=True,
            autocomplete=False,
            translations=True,
            pronunciation=True,
            cache_policy="persistent",
        )

        def search(self, *_args, **_kwargs):
            raise AssertionError("cache-only lookup reached the provider")

        def get_entry(self, *_args, **_kwargs):
            raise AssertionError("cache-only lookup reached the provider")

    cache = LexicalCache(tmp_path / "lexical_cache.db")
    service = LexicalService(provider=_ExplodingProvider(), cache=cache)

    with pytest.raises(ForbiddenError):
        service.get_entry(
            entry.provider,
            entry.entry_key,
            target_language="zh-Hant",
            allow_provider=False,
        )

    cache.put(entry.provider, entry.word, entry.language, "zh-Hant", entry)
    fresh = service.get_entry(
        entry.provider, entry.entry_key, target_language="zh-Hant", allow_provider=False
    )
    assert fresh.cache_status == "fresh"
    assert fresh.entry is not None and fresh.entry.entry_key == entry.entry_key

    expired = LexicalCache(
        tmp_path / "lexical_cache.db", positive_ttl=timedelta(seconds=-1)
    )
    expired.put(entry.provider, entry.word, entry.language, "zh-Hant", entry)
    stale_service = LexicalService(provider=_ExplodingProvider(), cache=expired)
    stale = stale_service.get_entry(
        entry.provider, entry.entry_key, target_language="zh-Hant", allow_provider=False
    )
    assert stale.cache_status == "stale"
    assert stale.entry is not None


def _lookup_events(cache_path):
    with sqlite3.connect(cache_path) as conn:
        return [
            {
                "provider": row[0],
                "operation": row[1],
                "outcome": row[2],
                "duration_ms": row[3],
                "created_at": row[4],
            }
            for row in conn.execute(
                "SELECT provider, operation, outcome, duration_ms, created_at "
                "FROM lexical_lookup_event ORDER BY id"
            )
        ]


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
