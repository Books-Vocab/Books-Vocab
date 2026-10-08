"""Tests for EmbeddingStore batch operations and _id_set optimization.

Also covers find_similar_batch (D2): one matmul for many query cards,
results identical to per-id find_similar.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import httpx
import numpy as np
import openai
import pytest

import kg.embeddings as embeddings_mod
from kg.embeddings import EMBEDDING_DIM, EMBEDDING_MODEL, EmbeddingStore
from kg.tracked_llm import TrackedLLM


def _make_store(tmp_path: Path, *, preload_ids: list[str] | None = None) -> tuple[EmbeddingStore, MagicMock]:
    """Create an EmbeddingStore with a mock OpenAI client wrapped in TrackedLLM."""
    emb_path = tmp_path / "embeddings.npy"
    ids_path = tmp_path / "ids.json"

    if preload_ids:
        n = len(preload_ids)
        np.save(emb_path, np.random.rand(n, EMBEDDING_DIM).astype(np.float32))
        ids_path.write_text(json.dumps(preload_ids))

    client = MagicMock()
    llm = TrackedLLM(client, "test_user")
    store = EmbeddingStore(emb_path, ids_path, llm)
    return store, client


def _mock_embedding_response(n: int = 1):
    """Create a mock OpenAI embedding response for n items."""
    resp = MagicMock()
    resp.usage = MagicMock(prompt_tokens=10 * n, total_tokens=10 * n)
    resp.data = []
    for i in range(n):
        item = MagicMock()
        item.index = i
        item.embedding = np.random.rand(EMBEDDING_DIM).tolist()
        resp.data.append(item)
    return resp


class TestAddBatch:
    def test_add_batch_exists(self, tmp_path: Path):
        """add_batch method must exist on EmbeddingStore."""
        store, _ = _make_store(tmp_path)
        assert hasattr(store, "add_batch"), "add_batch method missing"

    def test_add_batch_single_api_call(self, tmp_path: Path):
        """Batch of 5 items should make exactly 1 API call, not 5."""
        store, client = _make_store(tmp_path)
        items = [(f"card_{i}", f"text_{i}") for i in range(5)]
        client.embeddings.create.return_value = _mock_embedding_response(5)

        store.add_batch(items)

        assert client.embeddings.create.call_count == 1, (
            f"Expected 1 API call, got {client.embeddings.create.call_count}"
        )

    def test_add_batch_correct_count(self, tmp_path: Path):
        """All items should be stored after batch add."""
        store, client = _make_store(tmp_path)
        items = [(f"card_{i}", f"text_{i}") for i in range(3)]
        client.embeddings.create.return_value = _mock_embedding_response(3)

        store.add_batch(items)

        assert store.count() == 3
        for i in range(3):
            assert store.has(f"card_{i}")

    def test_add_batch_deduplicates_duplicate_ids_in_input_order(self, tmp_path: Path):
        """A batch stores each new card ID once, keeping its first occurrence."""
        store, client = _make_store(tmp_path, preload_ids=["existing"])
        requested_inputs: list[list[str]] = []

        def create_embeddings(**kwargs):
            requested_inputs.append(kwargs["input"])
            return _mock_embedding_response(len(kwargs["input"]))

        client.embeddings.create.side_effect = create_embeddings

        store.add_batch(
            [
                ("new-a", "first text"),
                ("new-a", "duplicate text"),
                ("existing", "already stored"),
                ("new-b", "second text"),
            ]
        )

        assert json.loads((tmp_path / "ids.json").read_text()) == [
            "existing",
            "new-a",
            "new-b",
        ]
        assert requested_inputs == [["first text", "second text"]]
        assert store._ids == ["existing", "new-a", "new-b"]
        assert store.count() == 3

        reloaded, _ = _make_store(tmp_path)
        assert reloaded._ids == ["existing", "new-a", "new-b"]
        assert reloaded.count() == 3

    def test_add_batch_skips_existing(self, tmp_path: Path):
        """Batch should skip cards that already exist."""
        store, client = _make_store(tmp_path, preload_ids=["existing_1"])
        items = [("existing_1", "text_a"), ("new_1", "text_b"), ("new_2", "text_c")]
        client.embeddings.create.return_value = _mock_embedding_response(2)

        store.add_batch(items)

        assert store.count() == 3  # 1 preloaded + 2 new
        assert store.has("existing_1")
        assert store.has("new_1")
        assert store.has("new_2")
        # API should only be called with 2 texts (skipping existing_1)
        call_args = client.embeddings.create.call_args
        assert len(call_args.kwargs.get("input", call_args[1].get("input", []))) == 2

    def test_add_batch_empty_after_filter(self, tmp_path: Path):
        """If all items already exist, no API call should be made."""
        store, client = _make_store(tmp_path, preload_ids=["a", "b"])
        items = [("a", "text_a"), ("b", "text_b")]

        store.add_batch(items)

        client.embeddings.create.assert_not_called()

    def test_add_batch_saves_to_disk(self, tmp_path: Path):
        """Batch add should persist to disk (single save)."""
        store, client = _make_store(tmp_path)
        items = [("c1", "hello"), ("c2", "world")]
        client.embeddings.create.return_value = _mock_embedding_response(2)

        store.add_batch(items)

        # Reload from disk
        store2, _ = _make_store(tmp_path)
        assert store2.count() == 2
        assert store2.has("c1")
        assert store2.has("c2")

    def test_add_batch_empty_list(self, tmp_path: Path):
        """Empty batch should be a no-op."""
        store, client = _make_store(tmp_path)
        store.add_batch([])
        client.embeddings.create.assert_not_called()


class TestIdSetOptimization:
    def test_has_uses_set(self, tmp_path: Path):
        """has() should use _id_set for O(1) lookups."""
        store, _ = _make_store(tmp_path, preload_ids=["x", "y", "z"])
        assert hasattr(store, "_id_set"), "_id_set attribute missing"
        assert isinstance(store._id_set, set)
        assert store.has("x")
        assert not store.has("missing")

    def test_id_set_synced_after_add(self, tmp_path: Path):
        """_id_set should stay in sync after single add."""
        store, client = _make_store(tmp_path)
        client.embeddings.create.return_value = _mock_embedding_response(1)
        store.add("card_1", "text")
        assert "card_1" in store._id_set

    def test_id_set_synced_after_batch(self, tmp_path: Path):
        """_id_set should stay in sync after batch add."""
        store, client = _make_store(tmp_path)
        client.embeddings.create.return_value = _mock_embedding_response(3)
        store.add_batch([("a", "t1"), ("b", "t2"), ("c", "t3")])
        assert store._id_set == {"a", "b", "c"}


class TestSingleAddDelegatesToBatch:
    def test_add_calls_batch_internally(self, tmp_path: Path):
        """Single add() should delegate to add_batch()."""
        store, client = _make_store(tmp_path)
        client.embeddings.create.return_value = _mock_embedding_response(1)

        with patch.object(store, "add_batch", wraps=store.add_batch) as mock_batch:
            store.add("card_1", "hello")
            mock_batch.assert_called_once()


def _store_with_vectors(tmp_path: Path, ids: list[str], vectors: np.ndarray) -> EmbeddingStore:
    """Build an EmbeddingStore whose matrix is exactly ``vectors`` (dim from
    the matrix), bypassing the API so similarity math is deterministic."""
    dim = vectors.shape[1]
    emb_path = tmp_path / "embeddings_default.npy"
    ids_path = tmp_path / "card_ids_default.json"
    meta_path = tmp_path / "embeddings_meta_default.json"
    np.save(emb_path, vectors.astype(np.float32))
    ids_path.write_text(json.dumps(ids))
    meta_path.write_text(json.dumps({"model": EMBEDDING_MODEL, "dim": dim, "created_at": "x"}))
    client = MagicMock()
    llm = TrackedLLM(client, "test_user")
    return EmbeddingStore(emb_path, ids_path, llm, model=EMBEDDING_MODEL, dim=dim)


class TestFindSimilarBatch:
    def test_find_similar_batch_matches_single(self, tmp_path: Path):
        rng = np.random.default_rng(123)
        n, dim = 40, 16
        vectors = rng.standard_normal((n, dim))
        ids = [f"c{i}" for i in range(n)]
        store = _store_with_vectors(tmp_path, ids, vectors)

        query_ids = ["c0", "c5", "c39"]
        for k in (1, 4, 10):
            batch = store.find_similar_batch(query_ids, k=k)
            assert set(batch.keys()) == set(query_ids)
            for q in query_ids:
                got = batch[q]
                ref = store.find_similar(q, k=k)
                # Identical id ranking; scores agree to float32 matmul precision
                # (batch uses a 2-D matmul vs the matvec in find_similar, so the
                # last few ULPs of the cosine can differ — not a logic gap).
                assert [c for c, _ in got] == [c for c, _ in ref], f"q={q} k={k}"
                for (_, gs), (_, rs) in zip(got, ref, strict=True):
                    assert abs(gs - rs) < 1e-5, f"q={q} k={k}"

    def test_find_similar_batch_single_matmul(self, tmp_path: Path, monkeypatch):
        rng = np.random.default_rng(99)
        n, dim = 30, 12
        vectors = rng.standard_normal((n, dim))
        ids = [f"c{i}" for i in range(n)]
        store = _store_with_vectors(tmp_path, ids, vectors)

        calls = {"matmul": 0}
        real_matmul = np.matmul

        def _spy_matmul(a, b, *args, **kwargs):
            calls["matmul"] += 1
            return real_matmul(a, b, *args, **kwargs)

        # @ on ndarrays dispatches to np.matmul; count full-matrix products.
        monkeypatch.setattr(np, "matmul", _spy_matmul)

        store.find_similar_batch(["c0", "c1", "c2", "c3"], k=5)
        assert calls["matmul"] == 1, f"expected one matmul, got {calls['matmul']}"

    def test_find_similar_batch_excludes_self(self, tmp_path: Path):
        rng = np.random.default_rng(5)
        n, dim = 12, 8
        vectors = rng.standard_normal((n, dim))
        ids = [f"c{i}" for i in range(n)]
        store = _store_with_vectors(tmp_path, ids, vectors)

        batch = store.find_similar_batch(["c0", "c7"], k=20)
        for q, neigh in batch.items():
            neigh_ids = [cid for cid, _ in neigh]
            assert q not in neigh_ids
            assert len(neigh) == n - 1  # all others, never self

    def test_find_similar_batch_missing_ids(self, tmp_path: Path):
        rng = np.random.default_rng(1)
        n, dim = 6, 8
        vectors = rng.standard_normal((n, dim))
        ids = [f"c{i}" for i in range(n)]
        store = _store_with_vectors(tmp_path, ids, vectors)

        batch = store.find_similar_batch(["c0", "ghost", "c2"], k=3)
        assert batch["ghost"] == []
        for q in ("c0", "c2"):
            got = batch[q]
            ref = store.find_similar(q, k=3)
            assert [c for c, _ in got] == [c for c, _ in ref]
            for (_, gs), (_, rs) in zip(got, ref, strict=True):
                assert abs(gs - rs) < 1e-5

    def test_find_similar_batch_empty_store(self, tmp_path: Path):
        store, _ = _make_store(tmp_path)
        assert store.find_similar_batch(["x", "y"], k=3) == {"x": [], "y": []}


# --------------------------------------------------------------------- #
# Provider request cap: add_batch chunks (#2264)
# --------------------------------------------------------------------- #
_CHUNK_DIM = 8
_PROVIDER_CAP = 100


def _chunk_items(n: int) -> list[tuple[str, str]]:
    return [(f"c{k:03d}", f"text:{k}") for k in range(n)]


def _chunk_ids(items: list[tuple[str, str]]) -> list[str]:
    return [cid for cid, _ in items]


def _chunk_vec(text: str) -> list[float]:
    """Deterministic per text, so a reload can prove rows still match ids."""
    return [float(text.split(":", 1)[1])] + [1.0] * (_CHUNK_DIM - 1)


def _chunk_bad_request() -> openai.BadRequestError:
    request = httpx.Request("POST", "https://provider.test/embeddings")
    return openai.BadRequestError(
        "too many inputs in one request", response=httpx.Response(400, request=request), body={}
    )


class _CappedEmbedClient:
    """Embedding client double that enforces the provider's input cap.

    Matches the ``client.embed("embed", input=..., model=...)`` surface that
    ``EmbeddingStore._embed`` calls. Records the size of every request,
    including rejected ones. ``fail_on_call`` / ``short_on_call`` (1-based)
    make that request fail with a non-retryable 400 or return one vector too
    few; ``on_call`` runs before the request is answered.
    """

    def __init__(self, *, fail_on_call=None, short_on_call=None, on_call=None) -> None:
        self.calls: list[int] = []
        self.fail_on_call = fail_on_call
        self.short_on_call = short_on_call
        self.on_call = on_call

    def embed(self, call_type, *, input, model):
        self.calls.append(len(input))
        call_no = len(self.calls)
        if self.on_call is not None:
            self.on_call(call_no)
        if len(input) > _PROVIDER_CAP or call_no == self.fail_on_call:
            raise _chunk_bad_request()
        texts = input[:-1] if call_no == self.short_on_call else input
        return SimpleNamespace(data=[SimpleNamespace(index=i, embedding=_chunk_vec(t)) for i, t in enumerate(texts)])


def _chunk_store(tmp_path: Path, client=None) -> EmbeddingStore:
    return EmbeddingStore(
        tmp_path / "embeddings_default.npy",
        tmp_path / "card_ids_default.json",
        client,
        dim=_CHUNK_DIM,
    )


def _chunk_assert_rows_match_ids(store: EmbeddingStore) -> None:
    assert store._embeddings is not None
    assert store._embeddings.shape == (len(store._ids), _CHUNK_DIM)
    for row, cid in zip(store._embeddings, store._ids, strict=True):
        assert row[0] == float(int(cid[1:])), f"row for {cid} holds another card's vector"


def _chunk_assert_persisted(tmp_path: Path, expected_ids: list[str]) -> None:
    """A fresh instance on the same files sees exactly ``expected_ids``."""
    reloaded = _chunk_store(tmp_path)
    assert reloaded._ids == expected_ids
    _chunk_assert_rows_match_ids(reloaded)


@pytest.fixture(autouse=True)
def sleeps(monkeypatch) -> list[float]:
    """Record (and skip) retry backoff sleeps inside kg.embeddings."""
    recorded: list[float] = []
    monkeypatch.setattr(embeddings_mod.time, "sleep", recorded.append)
    return recorded


def test_add_batch_splits_backlog_into_provider_sized_chunks(tmp_path: Path, sleeps: list[float]):
    client = _CappedEmbedClient()
    store = _chunk_store(tmp_path, client)
    items = _chunk_items(250)

    store.add_batch(items)

    assert client.calls == [100, 100, 50]
    assert store.count() == 250
    assert store._ids == _chunk_ids(items)
    _chunk_assert_rows_match_ids(store)
    _chunk_assert_persisted(tmp_path, _chunk_ids(items))
    assert sleeps == []


def test_chunk_size_constant_is_read_when_add_batch_runs(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(embeddings_mod, "_EMBED_BATCH_LIMIT", 2)
    client = _CappedEmbedClient()
    store = _chunk_store(tmp_path, client)

    store.add_batch(_chunk_items(5))

    assert client.calls == [2, 2, 1]
    assert store.count() == 5


def test_later_chunk_failure_keeps_earlier_chunks_and_next_call_resumes(tmp_path: Path, sleeps: list[float]):
    items = _chunk_items(250)
    failing = _CappedEmbedClient(fail_on_call=2)
    store = _chunk_store(tmp_path, failing)

    with pytest.raises(openai.BadRequestError):
        store.add_batch(items)

    # The 400 is not retried and chunk 3 is never sent.
    assert failing.calls == [100, 100]
    assert sleeps == []
    first_chunk = _chunk_ids(items[:100])
    assert store._ids == first_chunk
    _chunk_assert_persisted(tmp_path, first_chunk)

    healthy = _CappedEmbedClient()
    store.add_batch(items, llm=healthy)

    assert healthy.calls == [100, 50]
    assert store.count() == 250
    _chunk_assert_persisted(tmp_path, _chunk_ids(items))


def test_short_response_raises_and_appends_nothing_for_that_chunk(tmp_path: Path):
    items = _chunk_items(250)
    client = _CappedEmbedClient(short_on_call=2)
    store = _chunk_store(tmp_path, client)

    with pytest.raises(ValueError, match="count mismatch"):
        store.add_batch(items)

    assert client.calls == [100, 100]
    first_chunk = _chunk_ids(items[:100])
    assert store.count() == 100
    assert store._ids == first_chunk
    assert not any(store.has(cid) for cid in _chunk_ids(items[100:]))
    _chunk_assert_rows_match_ids(store)
    _chunk_assert_persisted(tmp_path, first_chunk)


def test_ids_landed_concurrently_between_chunks_are_not_re_embedded(tmp_path: Path):
    """Chunking widens the window between the up-front dedup and the last
    request, so each chunk re-checks membership before it is sent."""
    items = _chunk_items(250)
    other = _CappedEmbedClient()

    def land_c150_during_first_request(call_no: int) -> None:
        if call_no == 1:
            store.add_batch([("c150", "text:150")], llm=other)

    client = _CappedEmbedClient(on_call=land_c150_during_first_request)
    store = _chunk_store(tmp_path, client)

    store.add_batch(items)

    assert other.calls == [1]
    assert client.calls == [100, 99, 50]
    assert store.count() == 250
    assert sorted(store._ids) == _chunk_ids(items)
    _chunk_assert_rows_match_ids(store)


class _PipelineCards:
    def __init__(self, ids: list[str]) -> None:
        self._cards = [
            SimpleNamespace(id=cid, is_archived=False, embed_text=lambda k=int(cid[1:]): f"text:{k}") for cid in ids
        ]

    def all(self, include_deleted=False, notebook_id=None):
        return list(self._cards)


class _RecordingGraph:
    def __init__(self) -> None:
        self.pending: list[str] = []

    def add_pending_judge(self, card_ids) -> None:
        self.pending.extend(card_ids)


def test_pipeline_phase1_backfill_of_250_cards_chunks_and_queues_all(tmp_path: Path):
    import asyncio

    from kg.pipeline_service import _step_embed_and_judge

    all_ids = _chunk_ids(_chunk_items(250))
    client = _CappedEmbedClient()
    store = _chunk_store(tmp_path)
    cards = _PipelineCards(all_ids)
    graph = _RecordingGraph()
    user = {"id": "u_2264", "dir": tmp_path, "config": {"auto_link": {"enabled": False}}}

    created = asyncio.run(
        _step_embed_and_judge(
            "u_2264",
            user,
            card_store_factory=lambda d: cards,
            graph_store_factory=lambda d, notebook_id="default": graph,
            embedding_store_factory=lambda d, llm=None, notebook_id="default": store.bind(client),
            client_factory=lambda provider: None,
            logger=logging.getLogger("test.2264"),
            link_kind_enum=lambda v: v,
        )
    )

    assert created == 0  # auto_link disabled: the step returns after Phase 1
    assert client.calls == [100, 100, 50]
    assert store.count() == 250
    assert graph.pending == all_ids
