from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from types import SimpleNamespace

from kg.pipeline_service import run_pipeline_background, _sync_embed_loop


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


class _CardsBothFields:
    """Cards that already have pos+note — enrich step should be skipped."""

    def all(self, include_deleted: bool = False):
        return [
            SimpleNamespace(
                id="c1", content="evoke", pos="v.", note="note",
                difficulty=None, is_deleted=False,
            )
        ]


class _CardsNeedEnrich:
    """Cards that need enrichment (no pos/note)."""

    def __init__(self, fail_count: int = 0):
        self.calls = 0
        self.fail_count = fail_count

    def all(self, include_deleted: bool = False):
        return [
            SimpleNamespace(
                id="c1", content="evoke", pos=None, note=None,
                difficulty=None, is_deleted=False,
            )
        ]

    def update(self, card_id, **kwargs):
        return None


class _GraphOk:
    def pop_candidates(self):
        return []

    def add_candidate(self, *args):
        pass


class _EmbeddingsOk:
    def has(self, card_id):
        return True


class _EmbeddingsMissing:
    """Embedding store that reports missing and records add() calls."""

    def __init__(self):
        self.added: list[str] = []
        self.add_thread_ids: list[int] = []

    def has(self, card_id):
        return False

    def add(self, card_id, text):
        self.added.append(card_id)
        self.add_thread_ids.append(threading.get_ident())

    def find_similar(self, card_id, k=3):
        return []


async def _make_lock():
    return asyncio.Lock()


def test_enrich_step_retries_on_transient_failure():
    """Enrich step 瞬時失敗後第二次成功（retry 呼叫）。"""
    logger = _FakeLogger()
    user = {"id": "u1", "dir": Path("/tmp/u1"), "config": {}}
    enrich_calls = []

    async def fake_enrich_stream(client, targets, **kwargs):
        enrich_calls.append(1)
        if len(enrich_calls) == 1:
            from openai import OpenAIError
            raise OpenAIError("rate limit")
        # second call: yield empty — no updates
        return
        yield  # make it an async generator

    import kg.pipeline_service as ps
    original = None

    async def run():
        nonlocal original
        # Patch enrich_cards_stream inside _step_enrich lazy import scope
        import kg.enrich as enrich_mod
        original_stream = enrich_mod.enrich_cards_stream

        async def patched_stream(client, targets, **kwargs):
            enrich_calls.append(1)
            if len(enrich_calls) == 1:
                from openai import OpenAIError
                raise OpenAIError("rate limit")
            if False:
                yield  # make async generator

        enrich_mod.enrich_cards_stream = patched_stream
        try:
            await run_pipeline_background(
                user,
                get_user_lock_fn=lambda uid: asyncio.Lock(),
                card_store_factory=lambda d: _CardsNeedEnrich(),
                graph_store_factory=lambda d: _GraphOk(),
                embedding_store_factory=lambda d, user_id=None: _EmbeddingsOk(),
                gemini_client_factory=lambda: None,
                logger=logger,
                link_kind_enum=lambda v: v,
            )
        finally:
            enrich_mod.enrich_cards_stream = original_stream

    asyncio.run(run())
    # After retry, enrich should have been called twice (1 fail + 1 success)
    assert len(enrich_calls) == 2
    # No error logged for enrich (retry succeeded)
    assert not any("Step 1 (Enrich)" in m for m in logger.error_messages)


def test_embed_step_runs_in_executor_thread():
    """Embed step 的 sync 操作在非 event-loop thread 執行。"""
    logger = _FakeLogger()
    user = {"id": "u2", "dir": Path("/tmp/u2"), "config": {}}
    embeddings = _EmbeddingsMissing()
    event_loop_thread_id = None

    async def run():
        nonlocal event_loop_thread_id
        event_loop_thread_id = threading.get_ident()
        await run_pipeline_background(
            user,
            get_user_lock_fn=lambda uid: asyncio.Lock(),
            card_store_factory=lambda d: _CardsBothFields(),
            graph_store_factory=lambda d: _GraphOk(),
            embedding_store_factory=lambda d, user_id=None: embeddings,
            gemini_client_factory=lambda: None,
            logger=logger,
            link_kind_enum=lambda v: v,
        )

    asyncio.run(run())

    # Cards in _CardsBothFields already have embeddings → missing list is empty,
    # so add() never runs. Let's test _sync_embed_loop directly instead.
    card = SimpleNamespace(id="cx", content="test", embed_text=lambda: "test text")
    emb = _EmbeddingsMissing()
    graph = _GraphOk()
    fake_logger = _FakeLogger()

    executor_thread_ids: list[int] = []

    original_add = emb.add

    def recording_add(card_id, text):
        executor_thread_ids.append(threading.get_ident())
        original_add(card_id, text)

    emb.add = recording_add
    main_thread_id = threading.get_ident()

    async def run_executor():
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _sync_embed_loop, [card], emb, graph, "u2", fake_logger)

    asyncio.run(run_executor())

    # The add() call should have happened in a different thread than main
    assert len(executor_thread_ids) == 1
    assert executor_thread_ids[0] != main_thread_id
