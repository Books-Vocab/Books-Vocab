"""Tests for the merged _step_embed_and_judge pipeline step."""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from kg.judge import Judgement


# ── Fakes ──────────────────────────────────────────────────────


class _FakeLogger:
    def __init__(self) -> None:
        self.info_messages: list[str] = []
        self.warning_messages: list[str] = []
        self.error_messages: list[str] = []

    def info(self, msg, *args, **kwargs):
        self.info_messages.append(msg % args if args else msg)

    def warning(self, msg, *args, **kwargs):
        self.warning_messages.append(msg % args if args else msg)

    def error(self, msg, *args, **kwargs):
        self.error_messages.append(msg % args if args else msg)


def _make_card(cid: str, content: str, meaning: str, *, is_archived: bool = False, is_deleted: bool = False):
    return SimpleNamespace(
        id=cid,
        content=content,
        meaning=meaning,
        pos="n.",
        note="note",
        difficulty=None,
        is_deleted=is_deleted,
        is_archived=is_archived,
        notebook_id="default",
        embed_text=lambda c=content: c,
    )


class _FakeCards:
    def __init__(self, cards: list):
        self._cards = {c.id: c for c in cards}

    def all(self, include_deleted=False, notebook_id=None):
        return list(self._cards.values())

    def get_batch(self, ids):
        return {cid: self._cards[cid] for cid in ids if cid in self._cards}


class _FakeEmbeddings:
    def __init__(self, *, has_ids: set[str] | None = None, similar_map: dict[str, list[tuple[str, float]]] | None = None):
        self._has = has_ids or set()
        self._similar = similar_map or {}
        self.added: list[tuple[str, str]] = []

    def has(self, card_id: str) -> bool:
        return card_id in self._has

    def add_batch(self, items: list[tuple[str, str]]) -> None:
        for cid, text in items:
            self._has.add(cid)
            self.added.append((cid, text))

    def find_similar(self, card_id: str, k: int = 12) -> list[tuple[str, float]]:
        return self._similar.get(card_id, [])


class _FakeGraph:
    def __init__(self, *, links: dict[str, list] | None = None, pending: list[str] | None = None):
        self._links: dict[str, list] = links or {}
        self._pending: list[str] = list(pending) if pending else []
        self.created_links: list = []
        self._blocked: set[tuple[str, str]] = set()
        self.added_pending: list[str] = []

    def add_pending_judge(self, card_ids: list[str]) -> None:
        self._pending.extend(card_ids)
        self.added_pending.extend(card_ids)

    def pop_pending_judge(self) -> list[str]:
        result = list(self._pending)
        self._pending.clear()
        return result

    def get_links_for(self, card_id: str) -> list:
        return self._links.get(card_id, [])

    def has_link(self, a: str, b: str) -> bool:
        return False

    def batch_add_links(self, links: list) -> list:
        self.created_links.extend(links)
        return links


class _FakeJudge:
    """Records calls and returns predetermined results."""

    def __init__(self, results: dict[str, dict[str, Judgement | None]] | None = None):
        self._results = results or {}
        self.calls: list[str] = []

    def evaluate_batch(self, target_word, target_meaning, candidates, *, from_id="", similarities=None, max_links=None):
        self.calls.append(from_id)
        return self._results.get(from_id, {cid: None for cid, _, _ in candidates})


class _FailingJudge:
    """Judge that fails after N calls."""

    def __init__(self, fail_after: int):
        self._fail_after = fail_after
        self._count = 0
        self.calls: list[str] = []

    def evaluate_batch(self, target_word, target_meaning, candidates, *, from_id="", similarities=None, max_links=None):
        self._count += 1
        self.calls.append(from_id)
        if self._count > self._fail_after:
            raise RuntimeError("judge exploded")
        return {cid: None for cid, _, _ in candidates}


# ── Tests ──────────────────────────────────────────────────────


def test_embed_and_judge_creates_links():
    """New card embedded, judged, links created in one step."""
    from kg.pipeline_service import _step_embed_and_judge

    cards_list = [
        _make_card("c1", "evoke", "to bring to mind"),
        _make_card("c2", "invoke", "to call upon"),
        _make_card("c3", "revoke", "to cancel"),
    ]
    cards = _FakeCards(cards_list)

    # c1 not embedded yet; c2, c3 already embedded
    similar_map = {
        "c1": [("c2", 0.85), ("c3", 0.80)],
    }
    embeddings = _FakeEmbeddings(has_ids={"c2", "c3"}, similar_map=similar_map)

    judge_results = {
        "c1": {
            "c2": Judgement(link="shares_usage", confidence=0.9, reason="相近用法"),
            "c3": None,
        },
    }

    graph = _FakeGraph(pending=[])  # pending will be populated by embed phase
    logger = _FakeLogger()

    # Patch Judge
    import kg.judge as judge_mod
    orig_judge = judge_mod.Judge
    fake_judge = _FakeJudge(judge_results)

    class PatchedJudge:
        def __init__(self, llm, **kwargs):
            pass

        def evaluate_batch(self, *args, **kwargs):
            return fake_judge.evaluate_batch(*args, **kwargs)

    judge_mod.Judge = PatchedJudge
    try:
        asyncio.run(_step_embed_and_judge(
            "u1", {"id": "u1", "dir": Path("/tmp/u1"), "config": {}},
            card_store_factory=lambda d: cards,
            graph_store_factory=lambda d, notebook_id="default": graph,
            embedding_store_factory=lambda d, llm=None, notebook_id="default": embeddings,
            gemini_client_factory=lambda: None,
            logger=logger,
            link_kind_enum=lambda v: v,
        ))
    finally:
        judge_mod.Judge = orig_judge

    # c1 should have been embedded
    assert embeddings.has("c1")
    # c1 should have been added to pending_judge then judged
    assert "c1" in fake_judge.calls
    # One link should have been created (c1→c2 shares_usage)
    assert len(graph.created_links) == 1
    assert graph.created_links[0][0] == "c1"
    assert graph.created_links[0][1] == "c2"


def test_embed_and_judge_respects_max_degree():
    """Cards at MAX_DEGREE are skipped during judging."""
    from kg.pipeline_service import _step_embed_and_judge
    from kg.vocab_graph import MAX_DEGREE

    cards_list = [
        _make_card("c1", "evoke", "to bring to mind"),
        _make_card("c2", "invoke", "to call upon"),
    ]
    cards = _FakeCards(cards_list)

    similar_map = {"c1": [("c2", 0.85)]}
    embeddings = _FakeEmbeddings(has_ids={"c1", "c2"}, similar_map=similar_map)

    # c1 already at MAX_DEGREE
    fake_links = [SimpleNamespace(id=f"link{i}", status="active") for i in range(MAX_DEGREE)]
    graph = _FakeGraph(pending=["c1"], links={"c1": fake_links})
    logger = _FakeLogger()

    import kg.judge as judge_mod
    orig_judge = judge_mod.Judge
    fake_judge = _FakeJudge({})

    class PatchedJudge:
        def __init__(self, llm, **kwargs):
            pass
        def evaluate_batch(self, *args, **kwargs):
            return fake_judge.evaluate_batch(*args, **kwargs)

    judge_mod.Judge = PatchedJudge
    try:
        asyncio.run(_step_embed_and_judge(
            "u1", {"id": "u1", "dir": Path("/tmp/u1"), "config": {}},
            card_store_factory=lambda d: cards,
            graph_store_factory=lambda d, notebook_id="default": graph,
            embedding_store_factory=lambda d, llm=None, notebook_id="default": embeddings,
            gemini_client_factory=lambda: None,
            logger=logger,
            link_kind_enum=lambda v: v,
        ))
    finally:
        judge_mod.Judge = orig_judge

    # Judge should NOT have been called for c1 (at MAX_DEGREE)
    assert "c1" not in fake_judge.calls
    # No links created
    assert len(graph.created_links) == 0


def test_embed_and_judge_error_recovery():
    """If judge fails midway, unprocessed cards are requeued."""
    from kg.pipeline_service import _step_embed_and_judge

    cards_list = [
        _make_card("c1", "evoke", "to bring to mind"),
        _make_card("c2", "invoke", "to call upon"),
        _make_card("c3", "revoke", "to cancel"),
        _make_card("c4", "provoke", "to anger"),
    ]
    cards = _FakeCards(cards_list)

    # All embedded, all have similar pairs
    similar_map = {
        "c1": [("c2", 0.85)],
        "c2": [("c1", 0.85)],
        "c3": [("c4", 0.85)],
        "c4": [("c3", 0.85)],
    }
    embeddings = _FakeEmbeddings(has_ids={"c1", "c2", "c3", "c4"}, similar_map=similar_map)
    graph = _FakeGraph(pending=["c1", "c2", "c3", "c4"])
    logger = _FakeLogger()

    import kg.judge as judge_mod
    orig_judge = judge_mod.Judge
    # Fail after 1 successful judge call
    failing_judge = _FailingJudge(fail_after=1)

    class PatchedJudge:
        def __init__(self, llm, **kwargs):
            pass
        def evaluate_batch(self, *args, **kwargs):
            return failing_judge.evaluate_batch(*args, **kwargs)

    judge_mod.Judge = PatchedJudge
    try:
        with pytest.raises(RuntimeError, match="judge exploded"):
            asyncio.run(_step_embed_and_judge(
                "u1", {"id": "u1", "dir": Path("/tmp/u1"), "config": {}},
                card_store_factory=lambda d: cards,
                graph_store_factory=lambda d, notebook_id="default": graph,
                embedding_store_factory=lambda d, llm=None, notebook_id="default": embeddings,
                gemini_client_factory=lambda: None,
                logger=logger,
                link_kind_enum=lambda v: v,
            ))
    finally:
        judge_mod.Judge = orig_judge

    # Some cards should have been requeued (unprocessed from await iteration perspective)
    # Note: ThreadPoolExecutor submits all tasks concurrently, so all may execute,
    # but futures not yet awaited at exception time get their card IDs requeued.
    assert len(graph.added_pending) > 0
