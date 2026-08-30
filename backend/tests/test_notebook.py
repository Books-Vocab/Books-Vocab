"""Tests for Notebook model and store."""

from __future__ import annotations

import pytest

from kg.notebook import DEFAULT_NOTEBOOK_ID, DEFAULT_NOTEBOOK_NAME, NotebookStore


@pytest.fixture()
def store(tmp_path):
    notebook_store = NotebookStore(path=tmp_path / "notebooks.db")
    try:
        yield notebook_store
    finally:
        notebook_store.close()


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


def test_get_modified_since_orders_equal_updated_at_by_id(store):
    from datetime import UTC, datetime, timedelta

    from sqlmodel import Session

    from kg.notebook import Notebook

    updated_at = datetime(2026, 1, 1, tzinfo=UTC)
    with Session(store.engine) as session:
        session.add_all(
            [
                Notebook(
                    id="nb-z",
                    name="Z",
                    created_at=updated_at,
                    updated_at=updated_at,
                ),
                Notebook(
                    id="nb-a",
                    name="A",
                    created_at=updated_at,
                    updated_at=updated_at,
                ),
            ]
        )
        session.commit()

    modified = store.get_modified_since(updated_at - timedelta(seconds=1))

    assert [notebook.id for notebook in modified] == ["nb-a", "nb-z"]


def test_all_orders_equal_sort_order_and_created_at_by_id(store):
    from datetime import UTC, datetime

    from sqlmodel import Session

    from kg.notebook import Notebook

    created_at = datetime(2026, 1, 1, tzinfo=UTC)
    with Session(store.engine) as session:
        session.add_all(
            [
                Notebook(
                    id="nb-z",
                    name="Z",
                    sort_order=1,
                    created_at=created_at,
                ),
                Notebook(
                    id="nb-a",
                    name="A",
                    sort_order=1,
                    created_at=created_at,
                ),
            ]
        )
        session.commit()

    assert [notebook.id for notebook in store.all()] == ["nb-a", "nb-z"]


def test_cards_notebook_id_filter(tmp_path):
    from kg.cards import CardStore

    cs = CardStore(tmp_path / "cards.db")
    try:
        cs.add(content="apple", meaning="fruit", notebook_id="nb1")
        cs.add(content="banana", meaning="fruit", notebook_id="nb2")
        cs.add(content="cherry", meaning="fruit", notebook_id="nb1")

        assert cs.count(notebook_id="nb1") == 2
        assert cs.count(notebook_id="nb2") == 1
        assert cs.count() == 3

        all_nb1 = list(cs.all(notebook_id="nb1"))
        assert len(all_nb1) == 2
        assert {c.content for c in all_nb1} == {"apple", "cherry"}

        all_nb1_list = list(cs.all(notebook_id="nb1"))
        assert len(all_nb1_list) == 2
    finally:
        cs.close()
