# ruff: noqa: F401, I001
"""Shared fixtures and helpers for the sharded backend test family."""

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
__all__ = (
    'CardStore',
    'SimpleNamespace',
    'UTC',
    '_CanonicalLexical',
    '_Judge',
    '_dictionary_service',
    '_lexical_entry',
    '_lookup_events',
    '_materialize_request',
    '_provider_payload',
    'annotations',
    'datetime',
    'httpx',
    'pytest',
    'replace',
    'sqlite3',
    'threading',
    'timedelta',
)
