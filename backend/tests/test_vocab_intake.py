"""Tests for kg.vocab_intake — add_vocab_entries + private helpers.

Covers branches not already exercised by test_vocab_service.py /
test_cards.py:
  * _build_example: word in context / alternative match / no match /
    pre-existing bold stripping / case-insensitive replace.
  * _derive_inflections: single-token vs phrase / missing root_form /
    lemminflect ImportError fallback / fallback when root is unknown.
  * add_vocab_entries: duplicate cardIds wiring / notebook scoping /
    skip when embedding API errors / VocabSource serialization /
    no-embedding when nothing created.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import pytest

from kg.api_models import VocabEntry, VocabSource
from kg.vocab_intake import _build_example, _derive_inflections, add_vocab_entries


@dataclass
class _IntakeCard:
    id: str
    content: str
    meaning: str = "m"
    examples: list[str] = field(default_factory=list)
    root_form: str | None = None
    inflections: list[str] = field(default_factory=list)
    notebook_id: str = "default"
    source: str | None = None
    is_deleted: bool = False

    def embed_text(self) -> str:
        return f"{self.content}: {self.meaning}"


class _IntakeCardsStore:
    """Minimal cards-store double tracking notebook scope and add() kwargs."""

    def __init__(self, preload: list[_IntakeCard] | None = None) -> None:
        self._cards: list[_IntakeCard] = list(preload or [])
        self.add_calls: list[dict[str, Any]] = []
        self._counter = 0
        self.all_calls: list[str | None] = []

    def all(self, include_deleted: bool = False, notebook_id: str | None = None) -> list[_IntakeCard]:
        self.all_calls.append(notebook_id)
        return [c for c in self._cards if c.notebook_id == notebook_id and (include_deleted or not c.is_deleted)]

    def add(self, **kwargs: Any) -> _IntakeCard:
        self.add_calls.append(kwargs)
        self._counter += 1
        card = _IntakeCard(
            id=f"id_{self._counter}",
            content=kwargs["content"],
            meaning=kwargs["meaning"],
            examples=list(kwargs.get("examples") or []),
            root_form=kwargs.get("root_form"),
            inflections=list(kwargs.get("inflections") or []),
            notebook_id=kwargs.get("notebook_id", "default"),
            source=kwargs.get("source"),
        )
        self._cards.append(card)
        return card

    def get(self, card_id: str) -> _IntakeCard | None:
        for c in self._cards:
            if c.id == card_id:
                return c
        return None


class _IntakeEmbeddings:
    def __init__(self, *, fail: bool = False) -> None:
        self.added: list[tuple[str, str]] = []
        self.fail = fail

    def has(self, card_id: str) -> bool:
        return any(cid == card_id for cid, _ in self.added)

    def add_batch(self, items: list[tuple[str, str]]) -> None:
        if self.fail:
            raise OSError("simulated disk failure")
        self.added.extend(items)


class _IntakeGraph:
    def __init__(self) -> None:
        self.pending: list[str] = []

    def add_pending_judge(self, card_ids: list[str]) -> None:
        self.pending.extend(card_ids)


def _silent_logger() -> logging.Logger:
    log = logging.getLogger("intake_test")
    log.addHandler(logging.NullHandler())
    return log


# --------------------------------------------------------------------- #
# _build_example
# --------------------------------------------------------------------- #
class TestBuildExample:
    def test_empty_context_returns_empty(self):
        assert _build_example("run", "") == ""

    def test_wraps_exact_word(self):
        assert _build_example("run", "I run fast") == "I **run** fast"

    def test_case_insensitive_match_normalises_word_case(self):
        # Match is case-insensitive but the replacement uses the entry word
        # verbatim — "Run" in context becomes "**run**" (the entry's casing).
        assert _build_example("run", "Run forward") == "**run** forward"

    def test_replaces_only_first_occurrence(self):
        out = _build_example("run", "run run run")
        assert out == "**run** run run"

    def test_strips_existing_bold_before_wrapping(self):
        # Pre-existing ** must not produce **double bold**.
        out = _build_example("run", "I **run** fast")
        assert out == "I **run** fast"
        assert "****" not in out

    def test_falls_back_to_alternative_inflection(self):
        # Word not present but an alternative (e.g. lemma) is — wrap that.
        out = _build_example("ran", "He runs daily", alternatives=["runs"])
        assert out == "He **runs** daily"

    def test_returns_context_unchanged_when_no_match(self):
        out = _build_example("ran", "She walks daily", alternatives=["run"])
        assert out == "She walks daily"


# --------------------------------------------------------------------- #
# _derive_inflections
# --------------------------------------------------------------------- #
class TestDeriveInflections:
    def test_phrase_returns_no_inflections(self):
        root, infl = _derive_inflections("ad hoc", "ad hoc", logger=_silent_logger())
        assert root is None
        assert infl == []

    def test_missing_root_form_returns_none(self):
        root, infl = _derive_inflections("running", None, logger=_silent_logger())
        assert root is None
        assert infl == []

    def test_blank_root_form_returns_none(self):
        root, infl = _derive_inflections("running", "   ", logger=_silent_logger())
        assert root is None
        assert infl == []

    def test_lemminflect_import_failure_is_swallowed(self, monkeypatch):
        """If lemminflect cannot import, function must return root + [] (no raise)."""
        import builtins

        real_import = builtins.__import__

        def fake_import(name: str, *a, **kw):
            if name == "lemminflect":
                raise ImportError("simulated")
            return real_import(name, *a, **kw)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        root, infl = _derive_inflections("running", "run", logger=_silent_logger())
        assert root == "run"
        assert infl == []

    def test_unknown_lemma_falls_back_to_word(self, monkeypatch):
        """When lemminflect returns empty for the root, fall back to word."""
        calls: list[str] = []

        def fake_get_all(lemma: str):
            calls.append(lemma)
            if lemma == "qzqzqz":
                return {}  # unknown root
            return {"VBZ": ("studies",), "VBD": ("studied",)}

        import sys
        import types

        fake_mod = types.ModuleType("lemminflect")
        fake_mod.getAllInflections = fake_get_all  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "lemminflect", fake_mod)

        root, infl = _derive_inflections("study", "qzqzqz", logger=_silent_logger())
        # Fallback path: root replaced by word.lower(), second lookup runs.
        assert root == "study"
        assert "studies" in infl and "studied" in infl
        assert calls == ["qzqzqz", "study"]


# --------------------------------------------------------------------- #
# add_vocab_entries
# --------------------------------------------------------------------- #
class TestAddVocabEntries:
    def _kwargs(self, cards=None, embeddings=None, graph=None):
        return dict(
            user={"id": "u1"},
            cards=cards or _IntakeCardsStore(),
            embeddings=embeddings or _IntakeEmbeddings(),
            graph=graph or _IntakeGraph(),
            logger=_silent_logger(),
        )

    def test_duplicate_still_returned_in_card_ids(self):
        existing = _IntakeCard(id="dup1", content="hello")
        store = _IntakeCardsStore(preload=[existing])
        entries = [VocabEntry(word="hello", translation="你好", context="hello world")]

        result = add_vocab_entries(entries, **self._kwargs(cards=store))

        assert result.created == 0
        assert result.skipped == 1
        assert result.duplicates == ["hello"]
        # Caller relies on cardIds even for duplicates so the client can link
        # back to the existing card.
        assert result.cardIds == {"hello": "dup1"}

    def test_notebook_scope_threads_through(self):
        # Same word lives in another notebook — must NOT be treated as duplicate
        # because cards.all() is called with notebook_id filter.
        store = _IntakeCardsStore(preload=[
            _IntakeCard(id="other", content="hello", notebook_id="nb_other")
        ])
        entries = [VocabEntry(word="hello", translation="你好", context="")]

        result = add_vocab_entries(entries, notebook_id="nb_target", **self._kwargs(cards=store))

        assert result.created == 1
        assert store.all_calls == ["nb_target"]
        assert store.add_calls[0]["notebook_id"] == "nb_target"

    def test_no_embedding_when_nothing_created(self):
        existing = _IntakeCard(id="x", content="cat")
        store = _IntakeCardsStore(preload=[existing])
        embeddings = _IntakeEmbeddings()
        graph = _IntakeGraph()

        result = add_vocab_entries(
            [VocabEntry(word="cat", translation="貓", context="")],
            **self._kwargs(cards=store, embeddings=embeddings, graph=graph),
        )

        assert result.created == 0
        assert embeddings.added == []
        assert graph.pending == []

    def test_embedding_failure_is_swallowed(self):
        """vocab_graph.embed_and_link_new_cards catches OSError — must not bubble."""
        store = _IntakeCardsStore()
        embeddings = _IntakeEmbeddings(fail=True)
        graph = _IntakeGraph()

        result = add_vocab_entries(
            [VocabEntry(word="cat", translation="貓", context="")],
            **self._kwargs(cards=store, embeddings=embeddings, graph=graph),
        )

        assert result.created == 1
        # graph.add_pending_judge must NOT be called when batch_items fails.
        assert graph.pending == []

    def test_vocab_source_is_json_serialised(self):
        store = _IntakeCardsStore()
        src = VocabSource(type="book", title="Moby Dick", chapter="1")
        entries = [VocabEntry(word="whale", translation="鯨", context="", source=src)]

        add_vocab_entries(entries, **self._kwargs(cards=store))

        import json
        raw = store.add_calls[0]["source"]
        assert raw is not None
        payload = json.loads(raw)
        assert payload["type"] == "book"
        assert payload["title"] == "Moby Dick"

    def test_no_source_passes_none(self):
        store = _IntakeCardsStore()
        add_vocab_entries(
            [VocabEntry(word="dog", translation="狗", context="")],
            **self._kwargs(cards=store),
        )
        assert store.add_calls[0]["source"] is None

    def test_clean_content_lowercases_first_letter(self):
        """add_vocab_entries delegates to _clean_content — verify wired in."""
        store = _IntakeCardsStore()
        add_vocab_entries(
            [VocabEntry(word="Hello.", translation="你好", context="")],
            **self._kwargs(cards=store),
        )
        # Trailing "." stripped, leading "H" lowercased.
        assert store.add_calls[0]["content"] == "hello"

    def test_pending_judge_only_for_successfully_embedded(self):
        store = _IntakeCardsStore()
        embeddings = _IntakeEmbeddings()
        graph = _IntakeGraph()

        add_vocab_entries(
            [VocabEntry(word="cat", translation="貓", context="")],
            **self._kwargs(cards=store, embeddings=embeddings, graph=graph),
        )

        assert len(embeddings.added) == 1
        assert graph.pending == [embeddings.added[0][0]]
