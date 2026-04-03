from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

from kg.pipeline_service import run_pipeline_background


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


class _CardsOk:
    def all(self, include_deleted: bool = False, notebook_id: str | None = None):
        return [
            SimpleNamespace(
                id="c1",
                content="evoke",
                meaning="to bring to mind",
                pos="v.",
                note="note",
                difficulty=None,
                is_deleted=False,
                is_archived=False,
                notebook_id="default",
                embed_text=lambda: "evoke",
            )
        ]

    def update(self, card_id, **kwargs):
        return None

    def batch_update(self, updates):
        return 0

    def get(self, card_id):
        return None

    def get_batch(self, ids):
        cards = {c.id: c for c in self.all()}
        return {cid: cards[cid] for cid in ids if cid in cards}


class _GraphOk:
    def pop_candidates(self):
        return []

    def pop_pending_judge(self):
        return []

    def add_pending_judge(self, card_ids):
        pass

    def get_links_for(self, card_id):
        return []

    def has_link(self, a, b):
        return False

    def candidate_count(self):
        return 0

    def link_count(self):
        return 0


class _EmbeddingsBoom:
    def has(self, card_id):
        raise RuntimeError("embedding unavailable")


async def _locked_lock():
    lock = asyncio.Lock()
    await lock.acquire()
    return lock


def test_pipeline_service_skips_when_lock_is_held():
    logger = _FakeLogger()
    user = {"id": "u1", "dir": Path("/tmp/u1"), "config": {}}
    lock = asyncio.run(_locked_lock())

    async def get_user_lock_fn(user_id: str):
        return lock

    asyncio.run(
        run_pipeline_background(
            user,
            get_user_lock_fn=get_user_lock_fn,
            card_store_factory=lambda user_dir: _CardsOk(),
            graph_store_factory=lambda user_dir, notebook_id="default": _GraphOk(),
            embedding_store_factory=lambda user_dir, llm=None, notebook_id="default": _EmbeddingsBoom(),
            gemini_client_factory=lambda: None,
            logger=logger,
            link_kind_enum=lambda value: value,
        )
    )

    assert any("skipping" in message.lower() for message in logger.info_messages)


def test_pipeline_service_logs_error_when_step_fails():
    logger = _FakeLogger()
    user = {"id": "u2", "dir": Path("/tmp/u2"), "config": {}}

    async def get_user_lock_fn(user_id: str):
        return asyncio.Lock()

    asyncio.run(
        run_pipeline_background(
            user,
            get_user_lock_fn=get_user_lock_fn,
            card_store_factory=lambda user_dir: _CardsOk(),
            graph_store_factory=lambda user_dir, notebook_id="default": _GraphOk(),
            embedding_store_factory=lambda user_dir, llm=None, notebook_id="default": _EmbeddingsBoom(),
            gemini_client_factory=lambda: None,
            logger=logger,
            link_kind_enum=lambda value: value,
        )
    )

    assert any("Embed" in message for message in logger.error_messages)
    assert any("Pipeline completed." in message for message in logger.info_messages)


# ---------------------------------------------------------------------------
# Parallel _step_link tests
# ---------------------------------------------------------------------------

import threading
import time


class _ConcurrentJudge:
    """Judge that records concurrent execution and measures overlap."""

    def __init__(self, delay: float = 0.05):
        self.delay = delay
        self.calls: list[str] = []
        self.max_concurrent = 0
        self._active = 0
        self._lock = threading.Lock()

    def evaluate(self, word_a, meaning_a, word_b, meaning_b):
        with self._lock:
            self._active += 1
            if self._active > self.max_concurrent:
                self.max_concurrent = self._active
        time.sleep(self.delay)
        with self._lock:
            self._active -= 1
            self.calls.append(f"{word_a}-{word_b}")
        return None  # no link to create


class _GraphWithCandidates:
    def __init__(self, pairs: list[tuple[str, str]]):
        self._pairs = pairs
        self.batch_links_called = False
        self._pending: list[str] = []

    def pop_candidates(self):
        return [
            SimpleNamespace(from_id=a, to_id=b)
            for a, b in self._pairs
        ]

    def pop_pending_judge(self):
        result = list(self._pending)
        self._pending.clear()
        return result

    def add_pending_judge(self, card_ids):
        self._pending.extend(card_ids)

    def get_links_for(self, card_id):
        return []

    def has_link(self, a, b):
        return False

    def batch_add_links(self, links):
        self.batch_links_called = True
        return links

    def requeue_candidates(self, candidates):
        pass


class _CardsForLink:
    def __init__(self, ids: list[str]):
        self._cards = {
            cid: SimpleNamespace(
                id=cid, content=f"word_{cid}", meaning=f"meaning_{cid}",
                pos="n.", note="some note",
                is_deleted=False, is_archived=False,
                embed_text=lambda: "text",
                difficulty=None,
                notebook_id="default",
            )
            for cid in ids
        }

    def all(self, include_deleted=False, notebook_id=None):
        return list(self._cards.values())

    def batch_update(self, updates):
        return 0

    def get_batch(self, ids):
        return {cid: self._cards[cid] for cid in ids if cid in self._cards}


class _EmbeddingsWithSimilar:
    """Embeddings that return similar pairs for concurrency test."""

    def __init__(self, similar_map: dict[str, list[tuple[str, float]]]):
        self._similar = similar_map

    def has(self, card_id):
        return True

    def add_batch(self, items):
        pass

    def find_similar(self, card_id, k=12):
        return self._similar.get(card_id, [])


class _GraphWithPending:
    """Graph with pending_judge cards for concurrency test."""

    def __init__(self, pending: list[str]):
        self._pending = list(pending)
        self.batch_links_called = False
        self.created_links: list = []

    def pop_pending_judge(self):
        result = list(self._pending)
        self._pending.clear()
        return result

    def add_pending_judge(self, card_ids):
        self._pending.extend(card_ids)

    def get_links_for(self, card_id):
        return []

    def has_link(self, a, b):
        return False

    def batch_add_links(self, links):
        self.batch_links_called = True
        self.created_links.extend(links)
        return links


def test_step_embed_and_judge_runs_judge_concurrently():
    """_step_embed_and_judge 必須並行呼叫 judge.evaluate_batch（max_concurrent > 1）。"""
    from kg.pipeline_service import _step_embed_and_judge

    # 10 cards, each similar to the next
    ids = [f"c{i}" for i in range(10)]
    similar_map = {ids[i]: [(ids[j], 0.85)] for i in range(10) for j in range(10) if i != j}
    fake_judge = _ConcurrentJudge(delay=0.05)

    async def run():
        import kg.judge as judge_mod
        orig = judge_mod.Judge

        class FakeJudge:
            def __init__(self, llm, **kwargs):
                pass

            def evaluate_batch(self, target_word, target_meaning, candidates, **kwargs):
                results = {}
                for cid, word, meaning in candidates:
                    r = fake_judge.evaluate(target_word, target_meaning, word, meaning)
                    results[cid] = r
                return results

        judge_mod.Judge = FakeJudge
        try:
            user = {"id": "u_par", "dir": None, "config": {}}
            await _step_embed_and_judge(
                "u_par", user,
                card_store_factory=lambda d: _CardsForLink(ids),
                graph_store_factory=lambda d, notebook_id="default": _GraphWithPending(ids),
                embedding_store_factory=lambda d, llm=None, notebook_id="default": _EmbeddingsWithSimilar(similar_map),
                gemini_client_factory=lambda: None,
                logger=_FakeLogger(),
                link_kind_enum=lambda v: v,
            )
        finally:
            judge_mod.Judge = orig

    asyncio.run(run())

    # 並行驗證：若仍為串行，max_concurrent == 1；並行後應 > 1
    assert fake_judge.max_concurrent > 1, (
        f"Expected concurrent judge calls, got max_concurrent={fake_judge.max_concurrent}. "
        "Looks like _step_embed_and_judge is still sequential."
    )
    assert len(fake_judge.calls) >= 5, f"Expected at least 5 judge calls, got {len(fake_judge.calls)}"
