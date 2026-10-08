"""Card archive/unarchive/delete must bump linked peers' ``updated_at``.

A peer's ``linksByKind`` depends on the other end's archive/delete state, so a
peer whose own row never moves is skipped by incremental sync (#2496).

``test_vocab_archive_peer_updated_at.py`` covers the plain single/batch paths
with an active link; this file covers what it does not: hidden-link peers,
notebook scoping, the best-effort failure contract and the external delete route.
"""

from __future__ import annotations

import logging
import time
from types import SimpleNamespace

import pytest

from kg.cards import CardStore
from kg.graph import GraphStore, LinkKind
from kg.vocab_crud import archive_vocab_word, delete_vocab_word


@pytest.fixture()
def env(tmp_path):
    cards = CardStore(tmp_path / "cards.db")
    graph = GraphStore(
        links_path=tmp_path / "links.json",
        candidates_path=tmp_path / "candidates.json",
        blocked_path=tmp_path / "blocked.json",
    )
    ids = {name: cards.add(name, "m").id for name in ("a", "b", "c", "d")}
    graph.add_link(ids["a"], ids["b"], LinkKind.CONTRASTS_WITH, 0.9, "r")
    hidden = graph.add_link(ids["c"], ids["b"], LinkKind.SHARES_USAGE, 0.9, "r")
    graph.hide_link(hidden.id)
    return SimpleNamespace(cards=cards, graph=graph, ids=ids)


def _stamps(env):
    return {name: env.cards.get(cid).updated_at for name, cid in env.ids.items()}


def _touched(env, before):
    after = _stamps(env)
    return {n for n in before if after[n] > before[n]}


def _snapshot_then_wait(env):
    before = _stamps(env)
    time.sleep(0.01)
    return before


def test_archive_touches_active_and_hidden_peers(env):
    before = _snapshot_then_wait(env)
    archive_vocab_word("b", archived=True, cards_store=env.cards, graph=env.graph)
    assert {"a", "c"} <= _touched(env, before)
    assert "d" not in _touched(env, before)


def test_unarchive_touches_restored_and_hidden_peers(env):
    archive_vocab_word("b", archived=True, cards_store=env.cards, graph=env.graph)
    before = _snapshot_then_wait(env)
    archive_vocab_word("b", archived=False, cards_store=env.cards, graph=env.graph)
    touched = _touched(env, before)
    assert {"a", "c"} <= touched
    assert "d" not in touched


def test_delete_touches_active_and_hidden_peers(env):
    before = _snapshot_then_wait(env)
    delete_vocab_word("b", cards_store=env.cards, graph=env.graph)
    touched = _touched(env, before)
    assert {"a", "c"} <= touched
    assert "d" not in touched


def test_other_notebook_peer_not_touched(env):
    other = env.cards.add("x", "m", notebook_id="nb2")
    env.graph.add_link(other.id, env.ids["b"], LinkKind.CONTRASTS_WITH, 0.9, "r")
    before = env.cards.get(other.id).updated_at
    time.sleep(0.01)
    archive_vocab_word("b", archived=True, cards_store=env.cards, graph=env.graph)
    assert env.cards.get(other.id).updated_at == before


def test_touch_failure_is_logged_and_does_not_fail_archive(env, monkeypatch, caplog):
    def boom(*_a, **_k):
        raise RuntimeError("touch down")

    monkeypatch.setattr(env.cards, "batch_touch", boom)
    with caplog.at_level(logging.ERROR):
        resp = archive_vocab_word("b", archived=True, cards_store=env.cards, graph=env.graph)
    assert resp.archived is True
    assert env.cards.get(env.ids["b"]).is_archived is True
    assert any(r.levelno == logging.ERROR and "linked peers" in r.getMessage() for r in caplog.records)


@pytest.fixture()
def external(env, monkeypatch):
    from kg.routers import external_api

    monkeypatch.setattr(external_api, "_validate_notebook", lambda *_a, **_k: None)
    monkeypatch.setattr(external_api, "_card_store", lambda _d: env.cards)
    monkeypatch.setattr(external_api, "_graph_store", lambda _d, **_k: env.graph)
    monkeypatch.setattr(
        external_api,
        "_embedding_store",
        lambda *_a, **_k: SimpleNamespace(remove=lambda _id: None),
    )
    return external_api


def test_external_delete_touches_active_and_hidden_peers(env, external):
    before = _snapshot_then_wait(env)
    external._delete_external_card({"id": "u", "dir": "unused"}, env.ids["b"], "default")
    touched = _touched(env, before)
    assert {"a", "c"} <= touched
    assert "d" not in touched


def test_external_delete_restores_card_when_peer_read_fails(env, external, monkeypatch):
    def boom(_card_id):
        raise RuntimeError("graph read down")

    monkeypatch.setattr(env.graph, "get_links_for", boom)
    with pytest.raises(RuntimeError, match="graph read down"):
        external._delete_external_card({"id": "u", "dir": "unused"}, env.ids["b"], "default")
    restored = env.cards.get(env.ids["b"])
    assert restored is not None
    assert not restored.is_deleted
