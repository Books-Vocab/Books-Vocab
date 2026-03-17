"""Tests for Notebook model and store."""

from __future__ import annotations

import pytest

from kg.notebook import NotebookStore, DEFAULT_NOTEBOOK_ID, DEFAULT_NOTEBOOK_NAME


@pytest.fixture()
def store(tmp_path):
    return NotebookStore(path=tmp_path / "notebooks.db")


def test_ensure_default_creates_notebook(store):
    nb = store.ensure_default()
    assert nb.id == DEFAULT_NOTEBOOK_ID
    assert nb.name == DEFAULT_NOTEBOOK_NAME
    assert nb.is_default is True


def test_ensure_default_idempotent(store):
    nb1 = store.ensure_default()
    nb2 = store.ensure_default()
    assert nb1.id == nb2.id


def test_create_notebook(store):
    nb = store.create(name="TOEFL", color="#FF0000")
    assert nb.name == "TOEFL"
    assert nb.color == "#FF0000"
    assert nb.is_default is False
    assert nb.id != DEFAULT_NOTEBOOK_ID


def test_list_notebooks(store):
    store.ensure_default()
    store.create(name="GRE")
    store.create(name="IELTS")
    all_nbs = store.all()
    assert len(all_nbs) == 3


def test_update_notebook(store):
    nb = store.create(name="Draft")
    updated = store.update(nb.id, name="Final")
    assert updated is not None
    assert updated.name == "Final"


def test_delete_notebook(store):
    nb = store.create(name="Temp")
    assert store.delete(nb.id) is True
    # Should not appear in default list
    assert all(n.id != nb.id for n in store.all())
    # Should appear in include_deleted
    assert any(n.id == nb.id for n in store.all(include_deleted=True))


def test_cannot_delete_default(store):
    store.ensure_default()
    assert store.delete(DEFAULT_NOTEBOOK_ID) is False


def test_get_modified_since(store):
    from datetime import UTC, datetime, timedelta
    before = datetime.now(UTC) - timedelta(seconds=1)
    store.create(name="New")
    modified = store.get_modified_since(before)
    assert len(modified) == 1
    assert modified[0].name == "New"


def test_cards_notebook_id_filter(tmp_path):
    from kg.cards import CardStore
    cs = CardStore(tmp_path / "cards.db")
    cs.add(content="apple", meaning="fruit", notebook_id="nb1")
    cs.add(content="banana", meaning="fruit", notebook_id="nb2")
    cs.add(content="cherry", meaning="fruit", notebook_id="nb1")

    assert cs.count(notebook_id="nb1") == 2
    assert cs.count(notebook_id="nb2") == 1
    assert cs.count() == 3

    all_nb1 = list(cs.all(notebook_id="nb1"))
    assert len(all_nb1) == 2
    assert {c.content for c in all_nb1} == {"apple", "cherry"}

    limited = cs.all_limited(limit=1, notebook_id="nb1")
    assert len(limited) == 1
