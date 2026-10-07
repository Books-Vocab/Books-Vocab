"""#2084: popped pending-judge ids must survive every way a judge run can end.

``_step_embed_and_judge`` pops the whole ``pending_judge`` queue before it
judges. Phase 1 only re-queues cards that have no embedding, so a popped
(already embedded) card that is not judged and not handed back is never
judged again. These tests drive the real ``GraphStore`` on disk and assert
what the *next* run or the *next process* would see:

- an exception anywhere after the pop requeues every unprocessed id;
- cancellation (``CancelledError`` is a ``BaseException``) requeues them too;
- a process killed mid-judge (deploy ``SIGKILL``) leaves every claimed id on
  disk until its links are persisted, so a fresh ``GraphStore`` requeues it.
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import sqlite3
import subprocess
import sys
import textwrap
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from openai import OpenAIError

import kg.judge as judge_mod
import kg.llm.providers as providers_mod
from kg.graph import GraphStore, LinkKind
from kg.pipeline_service import _step_embed_and_judge

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
IDS = ["c0", "c1", "c2", "c3"]


class _Logger:
    def __init__(self) -> None:
        self.warnings: list[str] = []

    def info(self, msg, *args, **kwargs):
        pass

    def warning(self, msg, *args, **kwargs):
        self.warnings.append(msg % args if args else msg)

    def error(self, msg, *args, **kwargs):
        pass


class _Card:
    def __init__(self, cid: str) -> None:
        self.id = cid
        self.content = cid
        self.meaning = f"meaning of {cid}"
        self.pos = "n."
        self.note = "ok"
        self.difficulty = 5.0
        self.is_deleted = False
        self.is_archived = False
        self.notebook_id = "default"

    def embed_text(self) -> str:
        return self.content


class _Cards:
    def __init__(self, ids: list[str], *, get_batch_error: Exception | None = None) -> None:
        self._cards = {cid: _Card(cid) for cid in ids}
        self.get_batch_error = get_batch_error

    def all(self, include_deleted: bool = False, notebook_id: str | None = None):
        return list(self._cards.values())

    def get_batch(self, card_ids):
        if self.get_batch_error is not None:
            raise self.get_batch_error
        return {cid: self._cards[cid] for cid in card_ids if cid in self._cards}

    def batch_update(self, updates):
        return len(updates)

    def batch_touch(self, ids, notebook_id=None):
        return len(ids)


class _Embeddings:
    """Every card is embedded; every other card is a strong neighbour."""

    def __init__(
        self,
        ids: list[str],
        *,
        batch_error: Exception | None = None,
        empty: bool = False,
    ) -> None:
        self._ids = list(ids)
        self.batch_error = batch_error
        self.empty = empty

    def has(self, card_id):
        return True

    def find_similar_batch(self, card_ids, k=3):
        if self.batch_error is not None:
            raise self.batch_error
        if self.empty:
            return {cid: [] for cid in card_ids}
        return {cid: [(other, 0.95) for other in self._ids if other != cid][:k] for cid in card_ids}


def _accept_first(candidates):
    return {
        cid: SimpleNamespace(link="shares_usage", confidence=0.9, reason="ok") if index == 0 else None
        for index, (cid, _word, _meaning) in enumerate(candidates)
    }


class _AcceptFirstJudge:
    def __init__(self, *args, **kwargs):
        pass

    def evaluate_batch(self, target_word, target_meaning, candidates, **kwargs):
        return _accept_first(candidates)


def _graph(tmp_path: Path) -> GraphStore:
    return GraphStore(
        links_path=tmp_path / "graph_default.json",
        candidates_path=tmp_path / "candidates_default.json",
        blocked_path=tmp_path / "blocked_default.json",
        pending_judge_path=tmp_path / "pending_judge_default.json",
    )


def _disk_pending(tmp_path: Path) -> set[str]:
    path = tmp_path / "pending_judge_default.json"
    return set(json.loads(path.read_text())) if path.exists() else set()


def _child_env() -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(filter(None, [str(SRC_DIR), env.get("PYTHONPATH")]))
    return env


_FRESH_PROCESS_READ = textwrap.dedent(
    """
    import json, sys
    from pathlib import Path
    from kg.graph import GraphStore
    d = Path(sys.argv[1])
    store = GraphStore(
        links_path=d / "graph_default.json",
        candidates_path=d / "candidates_default.json",
        blocked_path=d / "blocked_default.json",
        pending_judge_path=d / "pending_judge_default.json",
    )
    print(json.dumps(sorted(store._pending_judge)))
    """
)


def _pending_seen_by_fresh_process(tmp_path: Path) -> set[str]:
    """What a restarted process (no in-memory claims) would load as queued."""
    proc = subprocess.run(
        [sys.executable, "-c", _FRESH_PROCESS_READ, str(tmp_path)],
        env=_child_env(),
        capture_output=True,
        text=True,
        timeout=120,
        check=True,
    )
    return set(json.loads(proc.stdout))


async def _run_step(tmp_path: Path, graph: GraphStore, cards: _Cards, embeddings: _Embeddings, logger: _Logger):
    uid = f"u_claim_{tmp_path.name}"
    return await _step_embed_and_judge(
        uid,
        {"id": uid, "dir": tmp_path, "config": {}},
        card_store_factory=lambda d: cards,
        graph_store_factory=lambda d, notebook_id="default": graph,
        embedding_store_factory=lambda d, llm=None, notebook_id="default": embeddings,
        client_factory=lambda provider: None,
        logger=logger,
        link_kind_enum=LinkKind,
    )


def _assert_all_requeued(tmp_path: Path, graph: GraphStore) -> None:
    assert _disk_pending(tmp_path) == set(IDS), "popped ids must be back in pending_judge on disk"
    assert graph.pending_judge_count() == len(IDS), "requeued ids must be poppable by the next run"
    assert sorted(graph.pop_pending_judge()) == IDS


# ── Acceptance 1: any exception after the pop requeues every unprocessed id ──


@pytest.mark.parametrize("failure_point", ["judge_provider", "get_batch", "get_links_for", "find_similar_batch"])
def test_exception_after_pop_requeues_every_claimed_id(tmp_path, monkeypatch, failure_point):
    graph = _graph(tmp_path)
    graph.add_pending_judge(IDS)
    cards = _Cards(IDS)
    embeddings = _Embeddings(IDS)
    monkeypatch.setattr(judge_mod, "Judge", _AcceptFirstJudge)
    expected: type[BaseException]

    if failure_point == "judge_provider":
        real_provider_for = providers_mod.provider_for

        def provider_for(purpose):
            if purpose == "judge":
                raise RuntimeError("judge provider misconfigured")
            return real_provider_for(purpose)

        monkeypatch.setattr(providers_mod, "provider_for", provider_for)
        expected = RuntimeError
    elif failure_point == "get_batch":
        cards.get_batch_error = sqlite3.OperationalError("database is locked")
        expected = sqlite3.OperationalError
    elif failure_point == "get_links_for":

        def get_links_for(card_id):
            raise RuntimeError("graph index corrupted")

        monkeypatch.setattr(graph, "get_links_for", get_links_for)
        expected = RuntimeError
    else:
        embeddings.batch_error = RuntimeError("similarity backend crashed")
        expected = RuntimeError

    with pytest.raises(expected):
        asyncio.run(_run_step(tmp_path, graph, cards, embeddings, _Logger()))

    _assert_all_requeued(tmp_path, graph)


def test_failed_partial_link_persist_requeues_already_judged_cards(tmp_path, monkeypatch):
    """Judged cards whose links never reached disk are unprocessed too."""
    graph = _graph(tmp_path)
    graph.add_pending_judge(IDS)

    class _FailsOnC2:
        def __init__(self, *args, **kwargs):
            pass

        def evaluate_batch(self, target_word, target_meaning, candidates, **kwargs):
            if target_word == "c2":
                raise OpenAIError("judge rate-limited")
            return _accept_first(candidates)

    def batch_add_links(links, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(judge_mod, "Judge", _FailsOnC2)
    monkeypatch.setattr(graph, "batch_add_links", batch_add_links)

    with pytest.raises(OpenAIError):
        asyncio.run(_run_step(tmp_path, graph, _Cards(IDS), _Embeddings(IDS), _Logger()))

    _assert_all_requeued(tmp_path, graph)


# ── Acceptance 2: cancellation requeues every unprocessed id ──


def test_cancellation_during_evaluate_batch_requeues_every_claimed_id(tmp_path, monkeypatch):
    graph = _graph(tmp_path)
    graph.add_pending_judge(IDS)
    entered = threading.Event()
    release = threading.Event()

    class _BlockingJudge:
        def __init__(self, *args, **kwargs):
            pass

        def evaluate_batch(self, target_word, target_meaning, candidates, **kwargs):
            entered.set()
            release.wait(timeout=30)
            return _accept_first(candidates)

    monkeypatch.setattr(judge_mod, "Judge", _BlockingJudge)

    async def scenario():
        task = asyncio.create_task(_run_step(tmp_path, graph, _Cards(IDS), _Embeddings(IDS), _Logger()))
        while not entered.is_set():
            await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    try:
        asyncio.run(scenario())
    finally:
        release.set()

    _assert_all_requeued(tmp_path, graph)


def test_cancellation_during_phase1_embedding_still_queues_the_cards(tmp_path):
    """The embedding thread outlives a cancelled step and persists anyway.

    Phase 1 never revisits embedded cards, so a card embedded by that thread
    but not queued would never be judged.
    """
    graph = _graph(tmp_path)
    entered = threading.Event()
    release = threading.Event()
    finished = threading.Event()

    class _SlowEmbeddings(_Embeddings):
        def __init__(self, ids):
            super().__init__(ids)
            self._stored: set[str] = set()

        def has(self, card_id):
            return card_id in self._stored

        def add_batch(self, items):
            entered.set()
            release.wait(timeout=30)
            self._stored.update(cid for cid, _text in items)
            finished.set()

    embeddings = _SlowEmbeddings(IDS)

    async def scenario():
        task = asyncio.create_task(_run_step(tmp_path, graph, _Cards(IDS), embeddings, _Logger()))
        while not entered.is_set():
            await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        # Let the orphaned executor thread finish, as it does in production.
        release.set()

    try:
        asyncio.run(scenario())
    finally:
        release.set()
    assert finished.wait(timeout=30)

    assert all(embeddings.has(cid) for cid in IDS), "precondition: the cards ended up embedded"
    assert _disk_pending(tmp_path) == set(IDS), "embedded cards must be queued for judging"
    assert sorted(graph.pop_pending_judge()) == IDS


# ── Acceptance 3: a killed process leaves claimed ids for a fresh GraphStore ──


def test_sigkill_after_pop_leaves_ids_for_a_fresh_graph_store(tmp_path):
    script = textwrap.dedent(
        """
        import os, signal, sys
        from pathlib import Path
        from kg.graph import GraphStore
        d = Path(sys.argv[1])
        store = GraphStore(
            links_path=d / "graph_default.json",
            candidates_path=d / "candidates_default.json",
            blocked_path=d / "blocked_default.json",
            pending_judge_path=d / "pending_judge_default.json",
        )
        store.add_pending_judge(sys.argv[2:])
        assert store.pop_pending_judge() == sorted(sys.argv[2:])
        os.kill(os.getpid(), signal.SIGKILL)
        """
    )
    proc = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path), *IDS],
        env=_child_env(),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == -signal.SIGKILL, proc.stderr

    fresh = _graph(tmp_path)
    assert sorted(fresh.pop_pending_judge()) == IDS


def test_claimed_ids_stay_durable_until_links_persist(tmp_path, monkeypatch):
    """Mid-judge disk state is exactly what SIGKILL leaves behind."""
    graph = _graph(tmp_path)
    graph.add_pending_judge(IDS)
    entered = threading.Event()
    release = threading.Event()

    class _GatedJudge:
        def __init__(self, *args, **kwargs):
            pass

        def evaluate_batch(self, target_word, target_meaning, candidates, **kwargs):
            entered.set()
            release.wait(timeout=30)
            return _accept_first(candidates)

    monkeypatch.setattr(judge_mod, "Judge", _GatedJudge)

    async def scenario():
        task = asyncio.create_task(_run_step(tmp_path, graph, _Cards(IDS), _Embeddings(IDS), _Logger()))
        while not entered.is_set():
            await asyncio.sleep(0.01)
        mid_judge = await asyncio.to_thread(_pending_seen_by_fresh_process, tmp_path)
        release.set()
        return mid_judge, await task

    try:
        mid_judge, created = asyncio.run(scenario())
    finally:
        release.set()

    assert mid_judge == set(IDS), "a process killed mid-judge must leave every claimed id for the next process"
    assert created > 0
    assert _disk_pending(tmp_path) == set(), "ids must be acknowledged once their links are persisted"
    assert _pending_seen_by_fresh_process(tmp_path) == set()
    assert graph.pending_judge_count() == 0
    reloaded = _graph(tmp_path)
    assert reloaded.get_links_for("c0"), "links must be on disk before the claim is released"


def test_cards_without_candidates_are_acknowledged(tmp_path, monkeypatch):
    """The no-judge-task early return is a normal completion: ack, don't requeue."""
    graph = _graph(tmp_path)
    graph.add_pending_judge(IDS)
    monkeypatch.setattr(judge_mod, "Judge", _AcceptFirstJudge)

    created = asyncio.run(_run_step(tmp_path, graph, _Cards(IDS), _Embeddings(IDS, empty=True), _Logger()))

    assert created == 0
    assert _disk_pending(tmp_path) == set()
    assert _pending_seen_by_fresh_process(tmp_path) == set()
    assert graph.pending_judge_count() == 0
