"""extract_epub robustness — spine-order chapters + safe DC metadata.

Uses a lightweight fake mimicking the slice of the ebooklib ``EpubBook`` API that
``extract_epub`` / ``_dc`` / ``_doc_items_in_spine`` touch, so no real EPUB is
required and the manifest-vs-spine ordering trap can be constructed exactly.
"""

from __future__ import annotations

import ebooklib
import pytest

import pipeline


class _FakeItem:
    def __init__(self, item_id: str, name: str, body: str,
                 item_type: int = ebooklib.ITEM_DOCUMENT) -> None:
        self.id = item_id
        self._name = name
        self._body = body
        self._type = item_type

    def get_type(self) -> int:
        return self._type

    def get_name(self) -> str:
        return self._name

    def get_content(self) -> bytes:
        return f"<html><body><p>{self._body}</p></body></html>".encode()


class _FakeBook:
    """Manifest order = ``items`` list order; spine = ``spine`` idref order."""

    def __init__(self, items: list[_FakeItem], spine: list[str],
                 dc: dict | None = None) -> None:
        self._items = items
        self.spine = [(idref, "yes") for idref in spine]
        self._dc = dc if dc is not None else {}

    def get_metadata(self, ns: str, field: str) -> list:
        assert ns == "DC"
        val = self._dc.get(field)
        return [(val, {})] if val is not None else []

    def get_item_with_id(self, item_id: str):
        return next((i for i in self._items if i.id == item_id), None)

    def get_items_of_type(self, item_type: int):
        return [i for i in self._items if i.get_type() == item_type]


_FULL_DC = {"title": "T", "creator": "A", "language": "en"}


def _body(tag: str) -> str:
    # > 50 chars so the chapter survives the length filter.
    return f"chapter {tag} " * 10


# ─── A. spine ordering ───


def test_chapters_follow_spine_not_manifest(monkeypatch) -> None:
    # Manifest order is c, a, b; spine (reading order) is a, b, c.
    items = [
        _FakeItem("c", "c.xhtml", _body("C")),
        _FakeItem("a", "a.xhtml", _body("A")),
        _FakeItem("b", "b.xhtml", _body("B")),
    ]
    book = _FakeBook(items, spine=["a", "b", "c"], dc=_FULL_DC)
    monkeypatch.setattr(pipeline.epub, "read_epub", lambda _p: book)

    _, chapters = pipeline.extract_epub("dummy.epub")
    assert [name for name, _ in chapters] == ["a.xhtml", "b.xhtml", "c.xhtml"]


def test_spine_skips_non_document_items(monkeypatch) -> None:
    items = [
        _FakeItem("nav", "nav.xhtml", _body("NAV"), ebooklib.ITEM_NAVIGATION),
        _FakeItem("a", "a.xhtml", _body("A")),
    ]
    book = _FakeBook(items, spine=["nav", "a"], dc=_FULL_DC)
    monkeypatch.setattr(pipeline.epub, "read_epub", lambda _p: book)

    _, chapters = pipeline.extract_epub("dummy.epub")
    assert [name for name, _ in chapters] == ["a.xhtml"]


def test_empty_spine_falls_back_to_manifest(monkeypatch, capsys) -> None:
    items = [
        _FakeItem("a", "a.xhtml", _body("A")),
        _FakeItem("b", "b.xhtml", _body("B")),
    ]
    book = _FakeBook(items, spine=[], dc=_FULL_DC)
    monkeypatch.setattr(pipeline.epub, "read_epub", lambda _p: book)

    _, chapters = pipeline.extract_epub("dummy.epub")
    assert [name for name, _ in chapters] == ["a.xhtml", "b.xhtml"]
    assert "falling back to manifest order" in capsys.readouterr().out


# ─── B. safe DC metadata ───


def test_missing_creator_and_language_use_defaults(monkeypatch) -> None:
    items = [_FakeItem("a", "a.xhtml", _body("A"))]
    book = _FakeBook(items, spine=["a"], dc={"title": "Solo"})
    monkeypatch.setattr(pipeline.epub, "read_epub", lambda _p: book)

    meta, _ = pipeline.extract_epub("dummy.epub")
    assert meta["author"] == "Unknown"
    assert meta["language"] == "en"
    assert meta["title"] == "Solo"


def test_missing_title_raises_with_filename(monkeypatch) -> None:
    items = [_FakeItem("a", "a.xhtml", _body("A"))]
    book = _FakeBook(items, spine=["a"], dc={})
    monkeypatch.setattr(pipeline.epub, "read_epub", lambda _p: book)

    with pytest.raises(ValueError) as exc:
        pipeline.extract_epub("/books/mystery.epub")
    msg = str(exc.value)
    assert "title" in msg
    assert "/books/mystery.epub" in msg


def test_find_workspace_missing_title_raises_with_filename(monkeypatch, tmp_path) -> None:
    book = _FakeBook([], spine=[], dc={})
    monkeypatch.setattr(pipeline.epub, "read_epub", lambda _p: book)
    monkeypatch.setattr(pipeline, "WORKSPACES_DIR", tmp_path)

    with pytest.raises(ValueError) as exc:
        pipeline.find_workspace(tmp_path / "no_title.epub")
    assert "no_title.epub" in str(exc.value)


def test_find_saga_workspace_missing_title_raises_with_filename(monkeypatch, tmp_path) -> None:
    book = _FakeBook([], spine=[], dc={})
    monkeypatch.setattr(pipeline.epub, "read_epub", lambda _p: book)
    monkeypatch.setattr(pipeline, "WORKSPACES_DIR", tmp_path)

    with pytest.raises(ValueError) as exc:
        pipeline.find_saga_workspace("Saga", [tmp_path / "no_title.epub"])
    assert "no_title.epub" in str(exc.value)


def test_dc_empty_string_treated_as_missing(monkeypatch) -> None:
    # Some EPUBs carry an empty <dc:creator/> — should still hit the default.
    items = [_FakeItem("a", "a.xhtml", _body("A"))]
    book = _FakeBook(items, spine=["a"], dc={"title": "T", "creator": ""})
    monkeypatch.setattr(pipeline.epub, "read_epub", lambda _p: book)

    meta, _ = pipeline.extract_epub("dummy.epub")
    assert meta["author"] == "Unknown"
