"""Saga layout-planner + manifest round-trip tests (multi-book backbone)."""

from __future__ import annotations

import re

import pytest

import saga


def _meta(title: str, author: str = "Brandon Sanderson") -> dict:
    return {"title": title, "author": author}


MISTBORN = [
    _meta("The Final Empire"),
    _meta("The Well of Ascension"),
    _meta("The Hero of Ages"),
]


def test_plan_books_assigns_contiguous_indices_and_prefixed_slugs() -> None:
    books = saga.plan_books(MISTBORN)
    assert [b.index for b in books] == [1, 2, 3]
    assert books[0].slug == "01_the_final_empire"
    assert books[2].slug == "03_the_hero_of_ages"


def test_plan_books_rejects_empty() -> None:
    with pytest.raises(ValueError):
        saga.plan_books([])


def test_saga_dirname_is_order_sensitive() -> None:
    titles = [m["title"] for m in MISTBORN]
    reversed_titles = list(reversed(titles))
    d1 = saga.saga_dirname("Mistborn", titles)
    d2 = saga.saga_dirname("Mistborn", reversed_titles)
    assert d1 != d2, "reordering the saga must produce a distinct workspace"
    assert d1.startswith("mistborn_")


def test_saga_dirname_slug_is_backend_safe() -> None:
    # The whole dir name (slug + hash) must satisfy the backend series_id regex
    # ^[a-z0-9_]+$ — the same contract single-book workspaces honor.
    d = saga.saga_dirname("A Song of Ice & Fire!!!", ["x"])
    assert re.fullmatch(r"[a-z0-9_]+", d), d


def test_manifest_round_trips() -> None:
    books = saga.plan_books(MISTBORN)
    text = saga.render_series_manifest("Mistborn", books)
    recovered = saga.parse_series_manifest(text)
    assert recovered == books


def test_parse_rejects_missing_markers() -> None:
    with pytest.raises(ValueError, match="markers"):
        saga.parse_series_manifest("# Mistborn\nno markers here")


def test_parse_rejects_noncontiguous_order() -> None:
    bad = (
        "<!-- READING_ORDER:START -->\n"
        "| # | Dir | Title | Author |\n"
        "|---|-----|-------|--------|\n"
        "| 1 | 01_a | A | X |\n"
        "| 3 | 03_c | C | X |\n"  # gap: no index 2
        "<!-- READING_ORDER:END -->\n"
    )
    with pytest.raises(ValueError, match="contiguous"):
        saga.parse_series_manifest(bad)


def test_spoiler_horizon_is_later_books_only() -> None:
    books = saga.plan_books(MISTBORN)
    # While discussing book 1, books 2 and 3 are off-limits.
    horizon = saga.spoiler_horizon_books(books, current_index=1)
    assert [b.index for b in horizon] == [2, 3]
    # While discussing the last book, nothing is off-limits.
    assert saga.spoiler_horizon_books(books, current_index=3) == []


def test_flatten_chapters_continuous_numbering() -> None:
    books = saga.plan_books(MISTBORN)
    per_book = [
        [("a.x", "A1"), ("b.x", "A2")],          # book 1: 2 chapters
        [("c.x", "B1"), ("d.x", "B2"), ("e.x", "B3")],  # book 2: 3 chapters
        [("f.x", "C1")],                          # book 3: 1 chapter
    ]
    flat = saga.flatten_chapters(books, per_book)
    assert [fc.seq for fc in flat] == [1, 2, 3, 4, 5, 6]
    assert [fc.book_index for fc in flat] == [1, 1, 2, 2, 2, 3]
    # provenance preserved
    assert flat[2].name == "c.x" and flat[2].text == "B1"
    assert flat[2].book_slug == "02_the_well_of_ascension"


def test_flatten_rejects_length_mismatch() -> None:
    books = saga.plan_books(MISTBORN)
    with pytest.raises(ValueError, match="mismatch"):
        saga.flatten_chapters(books, [[("a", "x")]])  # only 1 book's chapters for 3 books


def test_book_boundaries() -> None:
    books = saga.plan_books(MISTBORN)
    per_book = [
        [("a.x", "A1"), ("b.x", "A2")],
        [("c.x", "B1"), ("d.x", "B2"), ("e.x", "B3")],
        [("f.x", "C1")],
    ]
    flat = saga.flatten_chapters(books, per_book)
    assert saga.book_boundaries(flat) == {1: (1, 2), 2: (3, 5), 3: (6, 6)}


def test_separator_row_not_parsed_as_book() -> None:
    # The markdown separator |---|...| must not be mistaken for a data row.
    books = saga.plan_books(MISTBORN)
    text = saga.render_series_manifest("Mistborn", books)
    assert len(saga.parse_series_manifest(text)) == 3
