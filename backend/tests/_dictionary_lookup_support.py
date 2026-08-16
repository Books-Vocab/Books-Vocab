# ruff: noqa: F401, I001
"""Shared fixtures and helpers for pure dictionary lookup tests."""

from __future__ import annotations

import sqlite3
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import httpx
import pytest


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
    "UTC",
    "_lexical_entry",
    "_lookup_events",
    "_provider_payload",
    "annotations",
    "datetime",
    "httpx",
    "pytest",
    "replace",
    "sqlite3",
    "timedelta",
)
