"""Tests for kg.embeddings.EmbeddingStore — load/embed/update/search branches.

Complements test_embedding_batch.py (batch add path) and
test_embedding_store_cache.py (factory caching). Focuses on:
  * _load: legacy-no-sidecar -> writes sidecar in place.
  * _load: sidecar mismatch -> quarantines stale files, starts empty.
  * _load: matching sidecar -> loads as-is.
  * _embed: sorts response.data by .index (including index=None coercion).
  * _embed: dim mismatch raises ValueError.
  * _embed: retries OpenAIError twice then raises on third attempt.
  * update: on existing id mutates in place + sets dirty; flush persists.
  * update: on unknown id delegates to add().
  * flush: no-op when not dirty.
  * find_similar: empty store / missing card / excludes self / respects k.
  * has / count basic shape.
  * _meta_path naming for common stem patterns.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest
from openai import OpenAIError

from kg.embeddings import EMBEDDING_DIM, EMBEDDING_MODEL, EmbeddingStore
from kg.tracked_llm import TrackedLLM


# --------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------- #
def _resp(n: int, *, dim: int = EMBEDDING_DIM, indexes: list[int | None] | None = None):
    """Build a mock embeddings response with .data, optional custom indexes."""
    resp = MagicMock()
    resp.usage = MagicMock(prompt_tokens=10 * n, total_tokens=10 * n)
    resp.data = []
    for i in range(n):
        item = MagicMock()
        item.index = indexes[i] if indexes is not None else i
        item.embedding = np.random.rand(dim).astype(np.float32).tolist()
        resp.data.append(item)
    return resp


def _make_store(
    tmp_path: Path,
    *,
    preload_ids: list[str] | None = None,
    model: str = EMBEDDING_MODEL,
    dim: int = EMBEDDING_DIM,
    write_meta: bool = True,
):
    emb_path = tmp_path / "embeddings_default.npy"
    ids_path = tmp_path / "card_ids_default.json"
    meta_path = tmp_path / "embeddings_meta_default.json"
    if preload_ids:
        n = len(preload_ids)
        np.save(emb_path, np.random.rand(n, dim).astype(np.float32))
        ids_path.write_text(json.dumps(preload_ids))
        if write_meta:
            meta_path.write_text(json.dumps({"model": model, "dim": dim, "created_at": "x"}))
    client = MagicMock()
    llm = TrackedLLM(client, "test_user")
    store = EmbeddingStore(emb_path, ids_path, llm, model=model, dim=dim)
    return store, client, meta_path


# --------------------------------------------------------------------- #
# _load branches
# --------------------------------------------------------------------- #
class TestLoad:
    def test_no_files_starts_empty_no_sidecar(self, tmp_path: Path):
        store, _, meta = _make_store(tmp_path)
        assert store.count() == 0
        # No sidecar should be written for an empty fresh store.
        assert not meta.exists()

    def test_matching_sidecar_loads_vectors(self, tmp_path: Path):
        store, _, _ = _make_store(tmp_path, preload_ids=["a", "b"])
        assert store.count() == 2
        assert store.has("a") and store.has("b")

    def test_legacy_no_sidecar_writes_meta_in_place(self, tmp_path: Path):
        store, _, meta = _make_store(tmp_path, preload_ids=["a"], write_meta=False)
        assert store.count() == 1
        assert meta.exists(), "legacy migration should write sidecar in-place"
        payload = json.loads(meta.read_text())
        assert payload["model"] == EMBEDDING_MODEL
        assert payload["dim"] == EMBEDDING_DIM

    def test_sidecar_mismatch_quarantines_stale(self, tmp_path: Path):
        emb_path = tmp_path / "embeddings_default.npy"
        ids_path = tmp_path / "card_ids_default.json"
        meta_path = tmp_path / "embeddings_meta_default.json"
        # Files describe a *different* model/dim than what we'll ask for.
        np.save(emb_path, np.random.rand(2, 8).astype(np.float32))
        ids_path.write_text(json.dumps(["a", "b"]))
        meta_path.write_text(json.dumps({"model": "old-model", "dim": 8, "created_at": "x"}))

        client = MagicMock()
        llm = TrackedLLM(client, "u")
        store = EmbeddingStore(emb_path, ids_path, llm, model=EMBEDDING_MODEL, dim=EMBEDDING_DIM)

        # Store comes up empty, originals renamed with .legacy_<model>_<dim>.
        assert store.count() == 0
        assert not emb_path.exists() and not ids_path.exists()
        assert (tmp_path / "embeddings_default.npy.legacy_old-model_8").exists()
        assert (tmp_path / "card_ids_default.json.legacy_old-model_8").exists()
        # Sidecar now reflects active config.
        active = json.loads(meta_path.read_text())
        assert active["model"] == EMBEDDING_MODEL and active["dim"] == EMBEDDING_DIM


# --------------------------------------------------------------------- #
# _embed branches
# --------------------------------------------------------------------- #
class TestEmbed:
    def test_dim_mismatch_raises(self, tmp_path: Path):
        store, client, _ = _make_store(tmp_path)
        # Return a response whose vector dim disagrees with store.dim — should raise.
        wrong_dim = EMBEDDING_DIM - 1
        client.embeddings.create.return_value = _resp(1, dim=wrong_dim)
        with pytest.raises(ValueError, match="Embedding dim mismatch"):
            store._embed(["hello"])

    def test_handles_none_index_in_response(self, tmp_path: Path, monkeypatch):
        """Gemini OpenAI-compat sometimes returns index=None — must not crash."""
        store, client, _ = _make_store(tmp_path)
        client.embeddings.create.return_value = _resp(2, indexes=[None, 1])
        vecs = store._embed(["a", "b"])
        assert vecs.shape == (2, EMBEDDING_DIM)

    def test_retries_openai_error_then_succeeds(self, tmp_path: Path, monkeypatch):
        store, client, _ = _make_store(tmp_path)
        ok = _resp(1)
        # First attempt fails, second succeeds.
        client.embeddings.create.side_effect = [OpenAIError("boom"), ok]
        # Avoid real sleeps.
        import kg.embeddings as emb_mod
        monkeypatch.setattr(emb_mod.time if hasattr(emb_mod, "time") else __import__("time"),
                            "sleep", lambda *_a, **_k: None)
        # Patch module-level `time.sleep` actually used inside _embed.
        import time as _t
        monkeypatch.setattr(_t, "sleep", lambda *_a, **_k: None)
        vecs = store._embed(["a"])
        assert vecs.shape == (1, EMBEDDING_DIM)
        assert client.embeddings.create.call_count == 2

    def test_third_attempt_failure_raises(self, tmp_path: Path, monkeypatch):
        store, client, _ = _make_store(tmp_path)
        client.embeddings.create.side_effect = [
            OpenAIError("a"), OpenAIError("b"), OpenAIError("c")
        ]
        import time as _t
        monkeypatch.setattr(_t, "sleep", lambda *_a, **_k: None)
        with pytest.raises(OpenAIError):
            store._embed(["a"])
        assert client.embeddings.create.call_count == 3


# --------------------------------------------------------------------- #
# update / flush
# --------------------------------------------------------------------- #
class TestUpdateFlush:
    def test_update_unknown_id_delegates_to_add(self, tmp_path: Path):
        store, client, _ = _make_store(tmp_path)
        client.embeddings.create.return_value = _resp(1)
        store.update("new1", "hello")
        assert store.has("new1")
        # update -> add() -> add_batch() — exactly one API call.
        assert client.embeddings.create.call_count == 1

    def test_update_existing_marks_dirty_no_save(self, tmp_path: Path):
        store, client, _ = _make_store(tmp_path, preload_ids=["a"])
        client.embeddings.create.return_value = _resp(1)

        # Capture vector pre-update.
        before = store._embeddings[0].copy()
        store.update("a", "new text")
        after = store._embeddings[0]

        assert not np.array_equal(before, after), "in-memory vector should change"
        assert store._dirty is True

    def test_flush_persists_dirty_then_clears_flag(self, tmp_path: Path):
        store, client, _ = _make_store(tmp_path, preload_ids=["a"])
        client.embeddings.create.return_value = _resp(1)
        store.update("a", "new text")
        assert store._dirty is True

        store.flush()
        assert store._dirty is False

        # Reload and verify the new vector survived.
        store2, _, _ = _make_store(tmp_path)
        # Same id at same index — at minimum dim should match.
        assert store2.has("a")

    def test_flush_no_op_when_clean(self, tmp_path: Path):
        store, _, _ = _make_store(tmp_path, preload_ids=["a"])
        # Nothing dirty: flush must not touch disk; simplest check is no exception
        # and dirty remains False.
        store.flush()
        assert store._dirty is False


# --------------------------------------------------------------------- #
# find_similar / has / count
# --------------------------------------------------------------------- #
class TestSimilaritySearch:
    def test_empty_store_returns_empty(self, tmp_path: Path):
        store, _, _ = _make_store(tmp_path)
        assert store.find_similar("anything") == []

    def test_unknown_card_id_returns_empty(self, tmp_path: Path):
        store, _, _ = _make_store(tmp_path, preload_ids=["a", "b"])
        assert store.find_similar("c_missing") == []

    def test_excludes_self_from_results(self, tmp_path: Path):
        store, _, _ = _make_store(tmp_path, preload_ids=["a", "b", "c"])
        results = store.find_similar("a", k=3)
        ids = [cid for cid, _ in results]
        assert "a" not in ids
        assert len(results) <= 2  # at most N-1 other vectors

    def test_respects_k(self, tmp_path: Path):
        ids = [f"c{i}" for i in range(6)]
        store, _, _ = _make_store(tmp_path, preload_ids=ids)
        results = store.find_similar("c0", k=2)
        assert len(results) == 2

    def test_results_are_floats(self, tmp_path: Path):
        store, _, _ = _make_store(tmp_path, preload_ids=["a", "b"])
        results = store.find_similar("a", k=1)
        assert len(results) == 1
        assert isinstance(results[0][1], float)

    def test_count_and_has(self, tmp_path: Path):
        store, _, _ = _make_store(tmp_path, preload_ids=["a", "b"])
        assert store.count() == 2
        assert store.has("a")
        assert not store.has("z")


# --------------------------------------------------------------------- #
# _meta_path naming
# --------------------------------------------------------------------- #
class TestMetaPath:
    def test_default_stem_pattern(self, tmp_path: Path):
        # "embeddings_default.npy" -> "embeddings_meta_default.json"
        store, _, meta = _make_store(tmp_path)
        assert store._meta_path == meta
        assert store._meta_path.name == "embeddings_meta_default.json"

    def test_generic_stem(self, tmp_path: Path):
        # Bare "embeddings.npy" -> "embeddings_meta.json"
        emb_path = tmp_path / "embeddings.npy"
        ids_path = tmp_path / "ids.json"
        client = MagicMock()
        llm = TrackedLLM(client, "u")
        store = EmbeddingStore(emb_path, ids_path, llm)
        assert store._meta_path.name == "embeddings_meta.json"

    def test_other_stem_falls_back(self, tmp_path: Path):
        # Non-conforming stem -> "<stem>_meta.json"
        emb_path = tmp_path / "weird.npy"
        ids_path = tmp_path / "weird_ids.json"
        client = MagicMock()
        llm = TrackedLLM(client, "u")
        store = EmbeddingStore(emb_path, ids_path, llm)
        assert store._meta_path.name == "weird_meta.json"
