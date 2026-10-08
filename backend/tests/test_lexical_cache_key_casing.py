"""Lexical cache keys preserve query casing (#2257).

Wiktionary headwords are case-sensitive ("Polish" the nationality vs
"polish" the verb), and the provider is called with the case-preserved query.
The cache key therefore must not fold case, or one casing's positive/negative
row is served for another casing's lookup.
"""

from __future__ import annotations

from _dictionary_lookup_support import _lexical_entry

COMPOSED_CAFE = "café"
DECOMPOSED_CAFE = "café"


class _CasingProvider:
    provider_id = "fake"
    dictionary_id = "fake-dictionary"
    schema_version = "v1"

    def __init__(self, entries: dict[str, object]) -> None:
        from kg.lexical_models import LexicalProviderCapabilities

        self.capabilities = LexicalProviderCapabilities(
            exact_lookup=True,
            autocomplete=False,
            translations=True,
            pronunciation=True,
            cache_policy="persistent",
        )
        self.entries = entries
        self.calls: list[str] = []

    def search(self, query: str, *, source_language: str, target_language: str):
        self.calls.append(query)
        return self.entries.get(query)

    def get_entry(self, entry_key: str, *, target_language: str = "zh-Hant"):
        from kg.lexical_provider import _decode_entry_key

        language, word = _decode_entry_key(entry_key)
        return self.search(word, source_language=language, target_language=target_language)


def _service(tmp_path, entries: dict[str, object]):
    from kg.lexical_cache import LexicalCache
    from kg.lexical_service import LexicalService

    provider = _CasingProvider(entries)
    service = LexicalService(provider=provider, cache=LexicalCache(tmp_path / "c.db"))
    return service, provider


def _search(service, query: str):
    return service.search(query, source_language="en", target_language="zh-Hant")


def test_distinct_casings_do_not_share_cache_row(tmp_path) -> None:
    service, provider = _service(tmp_path, {"Polish": _lexical_entry("Polish"), "polish": _lexical_entry("polish")})

    first = _search(service, "Polish")
    second = _search(service, "polish")

    assert first.entry is not None and first.entry.word == "Polish"
    assert second.entry is not None and second.entry.word == "polish"
    assert second.cache_status == "miss"
    assert second.provider_called is True
    assert provider.calls == ["Polish", "polish"]


def test_negative_on_one_casing_does_not_block_other(tmp_path) -> None:
    service, provider = _service(tmp_path, {"however": _lexical_entry("however")})

    first = _search(service, "However")
    second = _search(service, "however")

    assert first.cache_status == "negative"
    assert first.entry is None
    assert second.cache_status == "miss"
    assert second.provider_called is True
    assert second.entry is not None and second.entry.word == "however"
    assert provider.calls == ["However", "however"]


def test_resolve_entry_row_not_readable_by_other_casing(tmp_path) -> None:
    from kg.lexical_provider import _entry_key

    service, provider = _service(tmp_path, {"Polish": _lexical_entry("Polish"), "polish": _lexical_entry("polish")})

    resolved = service.get_entry("fake", _entry_key("en", "Polish"), target_language="zh-Hant")
    other_casing = _search(service, "polish")
    same_casing = _search(service, "Polish")

    assert resolved.entry is not None and resolved.entry.word == "Polish"
    assert other_casing.cache_status == "miss"
    assert other_casing.provider_called is True
    assert other_casing.entry is not None and other_casing.entry.word == "polish"
    assert same_casing.cache_status == "fresh"
    assert same_casing.provider_called is False
    assert same_casing.entry is not None and same_casing.entry.word == "Polish"
    assert provider.calls == ["Polish", "polish"]


def test_resolve_entry_caches_under_requested_word_not_provider_headword(tmp_path) -> None:
    from kg.lexical_provider import _entry_key

    # The provider answers the "polish" request with a "Polish" headword; that
    # response must not become the cached search result for "Polish".
    service, provider = _service(tmp_path, {"polish": _lexical_entry("Polish"), "Polish": _lexical_entry("Polish")})

    service.get_entry("fake", _entry_key("en", "polish"), target_language="zh-Hant")
    capitalized = _search(service, "Polish")

    assert capitalized.cache_status == "miss"
    assert capitalized.provider_called is True
    assert provider.calls == ["polish", "Polish"]


def test_query_key_preserves_case_but_strips_and_nfc() -> None:
    from kg.lexical_cache import LexicalCache

    def key(query: str) -> str:
        return LexicalCache.query_key("fake", query, "en", "zh-Hant")

    assert key("Polish") != key("polish")
    assert key(" polish ") == key("polish")
    assert key(DECOMPOSED_CAFE) == key(COMPOSED_CAFE)


def test_provider_receives_exactly_the_normalized_cache_key_query(tmp_path) -> None:
    service, provider = _service(tmp_path, {COMPOSED_CAFE: _lexical_entry(COMPOSED_CAFE)})

    first = _search(service, f"  {DECOMPOSED_CAFE}  ")
    second = _search(service, COMPOSED_CAFE)

    assert provider.calls == [COMPOSED_CAFE]
    assert first.cache_status == "miss"
    assert second.cache_status == "fresh"
    assert second.provider_called is False
