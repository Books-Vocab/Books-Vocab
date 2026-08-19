"""Tests for kg.embeddings.EmbeddingStore — load/embed/update/search branches.

Complements test_embedding_batch.py (batch add path) and
test_embedding_store_cache.py (factory caching). Focuses on:
  * _load: legacy-no-sidecar -> writes sidecar in place.
  * _load: non-object, malformed, or unreadable sidecars recover as legacy.
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

    def test_non_object_sidecar_recovers_as_legacy(self, tmp_path: Path):
        store, _, meta = _make_store(tmp_path, preload_ids=["a", "b"])
        meta.write_text("[]")

        reloaded = EmbeddingStore(store.embeddings_path, store.ids_path, store.llm)

        assert reloaded.count() == 2
        payload = json.loads(meta.read_text())
        assert payload["model"] == EMBEDDING_MODEL
        assert payload["dim"] == EMBEDDING_DIM

    def test_malformed_sidecar_recovers_as_legacy(self, tmp_path: Path):
        store, _, meta = _make_store(tmp_path, preload_ids=["a", "b"])
        meta.write_text('{"model":')

        reloaded = EmbeddingStore(store.embeddings_path, store.ids_path, store.llm)

        assert reloaded.count() == 2
        payload = json.loads(meta.read_text())
        assert payload["model"] == EMBEDDING_MODEL
        assert payload["dim"] == EMBEDDING_DIM

    def test_unreadable_sidecar_recovers_as_legacy(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        store, _, meta = _make_store(tmp_path, preload_ids=["a", "b"])
        original_read_text = Path.read_text

        def raise_for_meta(path: Path, *args, **kwargs):
            if path == meta:
                raise OSError("sidecar unavailable")
            return original_read_text(path, *args, **kwargs)

        monkeypatch.setattr(Path, "read_text", raise_for_meta)
        reloaded = EmbeddingStore(store.embeddings_path, store.ids_path, store.llm)
        monkeypatch.undo()

        assert reloaded.count() == 2
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

    def test_single_vector_store_returns_empty_not_self(self, tmp_path: Path):
        """A store holding exactly one vector must not return that vector as
        its own neighbour — the self-exclusion filter leaves nothing."""
        store, _, _ = _make_store(tmp_path, preload_ids=["only"])
        assert store.find_similar("only", k=10) == []

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


# --------------------------------------------------------------------- #
# remove / remove_batch  (Bug A: deleted cards' vectors must be evicted)
# --------------------------------------------------------------------- #
class TestRemove:
    def test_remove_evicts_vector_and_id(self, tmp_path: Path):
        store, _, _ = _make_store(tmp_path, preload_ids=["a", "b", "c"])
        assert store.remove("b") is True
        assert store.count() == 2
        assert not store.has("b")
        assert store.has("a") and store.has("c")
        # Matrix row count must stay aligned with ids.
        assert store._embeddings.shape[0] == store.count() == len(store._ids)

    def test_remove_unknown_id_is_noop(self, tmp_path: Path):
        store, _, _ = _make_store(tmp_path, preload_ids=["a", "b"])
        assert store.remove("ghost") is False
        assert store.count() == 2

    def test_remove_on_empty_store_is_noop(self, tmp_path: Path):
        store, _, _ = _make_store(tmp_path)
        assert store.remove("anything") is False
        assert store.count() == 0

    def test_removed_card_excluded_from_find_similar(self, tmp_path: Path):
        """The core Bug A symptom: a deleted card must not pollute top-k."""
        store, _, _ = _make_store(tmp_path, preload_ids=["a", "b", "c"])
        store.remove("b")
        ids = {cid for cid, _ in store.find_similar("a", k=10)}
        assert "b" not in ids
        assert ids <= {"c"}

    def test_remove_persists_to_disk(self, tmp_path: Path):
        store, _, _ = _make_store(tmp_path, preload_ids=["a", "b", "c"])
        store.remove("b")
        # Reload: the eviction must survive a restart.
        store2, _, _ = _make_store(tmp_path)
        assert store2.count() == 2
        assert not store2.has("b")
        assert store2._embeddings.shape[0] == 2

    def test_remove_batch_evicts_multiple(self, tmp_path: Path):
        store, _, _ = _make_store(tmp_path, preload_ids=["a", "b", "c", "d"])
        removed = store.remove_batch(["b", "d", "ghost"])
        assert removed == 2
        assert store.count() == 2
        assert store.has("a") and store.has("c")
        assert store._embeddings.shape[0] == 2

    def test_remove_batch_empty_input_is_noop(self, tmp_path: Path):
        store, _, _ = _make_store(tmp_path, preload_ids=["a", "b"])
        assert store.remove_batch([]) == 0
        assert store.count() == 2

    def test_remove_last_card_leaves_consistent_empty_matrix(self, tmp_path: Path):
        store, _, _ = _make_store(tmp_path, preload_ids=["only"])
        store.remove("only")
        assert store.count() == 0
        # Whatever the empty representation, it must not desync find_similar.
        assert store.find_similar("only") == []


# --------------------------------------------------------------------- #
# _load consistency  (Bug B: half-finished _save -> row/id desync)
#
# A desynced store (matrix rows != ids len, or dim mismatch) must NOT
# raise from __init__ — that escalates a recoverable corruption into a
# hard factory failure that 500s every embedding-touching request for
# the notebook (single-worker deploy: one interrupted save wedges it).
# Instead it degrades like the meta-mismatch path: quarantine the stale
# files, log a warning, and come up as an empty store that the next
# pipeline run will re-embed. The legal empty store (0-row .npy + []
# ids — the result of removing the last card) must still load normally.
# --------------------------------------------------------------------- #
class TestLoadConsistency:
    def test_row_count_id_mismatch_degrades_to_empty(self, tmp_path: Path):
        """Crash between writing .npy and ids.json (3 rows, 2 ids): the store
        must come up empty, not raise, and quarantine the corrupt files."""
        emb_path = tmp_path / "embeddings_default.npy"
        ids_path = tmp_path / "card_ids_default.json"
        meta_path = tmp_path / "embeddings_meta_default.json"
        np.save(emb_path, np.random.rand(3, EMBEDDING_DIM).astype(np.float32))
        ids_path.write_text(json.dumps(["a", "b"]))  # one id short
        meta_path.write_text(json.dumps(
            {"model": EMBEDDING_MODEL, "dim": EMBEDDING_DIM, "created_at": "x"}
        ))
        client = MagicMock()
        llm = TrackedLLM(client, "u")
        # Must not raise.
        store = EmbeddingStore(emb_path, ids_path, llm)
        assert store.count() == 0
        # Corrupt files quarantined so the live names are clear for a rebuild.
        assert not emb_path.exists() and not ids_path.exists()
        legacy = list(tmp_path.glob("*.corrupt_*"))
        assert any(p.name.startswith("embeddings_default.npy") for p in legacy)
        assert any(p.name.startswith("card_ids_default.json") for p in legacy)
        # find_similar on the degraded store must be safe (no desync crash).
        assert store.find_similar("a") == []

    def test_legacy_no_sidecar_path_also_degrades_on_desync(self, tmp_path: Path):
        """The legacy (no-meta) load branch must degrade on desync too."""
        emb_path = tmp_path / "embeddings_default.npy"
        ids_path = tmp_path / "card_ids_default.json"
        np.save(emb_path, np.random.rand(3, EMBEDDING_DIM).astype(np.float32))
        ids_path.write_text(json.dumps(["a", "b"]))
        client = MagicMock()
        llm = TrackedLLM(client, "u")
        store = EmbeddingStore(emb_path, ids_path, llm)
        assert store.count() == 0
        assert not emb_path.exists() and not ids_path.exists()

    def test_dim_mismatch_degrades_to_empty(self, tmp_path: Path):
        """A populated matrix whose column count != self.dim must degrade,
        not raise — same recoverable-corruption class as row desync."""
        emb_path = tmp_path / "embeddings_default.npy"
        ids_path = tmp_path / "card_ids_default.json"
        meta_path = tmp_path / "embeddings_meta_default.json"
        # Sidecar claims active config, but the matrix has the wrong dim.
        np.save(emb_path, np.random.rand(2, EMBEDDING_DIM - 1).astype(np.float32))
        ids_path.write_text(json.dumps(["a", "b"]))
        meta_path.write_text(json.dumps(
            {"model": EMBEDDING_MODEL, "dim": EMBEDDING_DIM, "created_at": "x"}
        ))
        client = MagicMock()
        llm = TrackedLLM(client, "u")
        store = EmbeddingStore(emb_path, ids_path, llm)
        assert store.count() == 0
        assert not emb_path.exists() and not ids_path.exists()

    def test_aligned_store_loads_fine(self, tmp_path: Path):
        """Sanity: a correctly-aligned store still loads without error."""
        store, _, _ = _make_store(tmp_path, preload_ids=["a", "b", "c"])
        assert store.count() == 3

    def test_legal_empty_store_loads_normally(self, tmp_path: Path):
        """KEY invariant: a legitimate empty store — 0-row .npy + [] ids,
        the exact on-disk result of removing the last card — must load as a
        normal empty store, NOT be misclassified as corrupt and quarantined."""
        emb_path = tmp_path / "embeddings_default.npy"
        ids_path = tmp_path / "card_ids_default.json"
        meta_path = tmp_path / "embeddings_meta_default.json"
        np.save(emb_path, np.zeros((0, EMBEDDING_DIM), dtype=np.float32))
        ids_path.write_text(json.dumps([]))
        meta_path.write_text(json.dumps(
            {"model": EMBEDDING_MODEL, "dim": EMBEDDING_DIM, "created_at": "x"}
        ))
        client = MagicMock()
        llm = TrackedLLM(client, "u")
        store = EmbeddingStore(emb_path, ids_path, llm)
        assert store.count() == 0
        # Files must survive — a legal empty store is not corruption.
        assert emb_path.exists() and ids_path.exists()
        assert not list(tmp_path.glob("*.corrupt_*"))

    def test_legal_empty_store_legacy_no_sidecar_loads_normally(self, tmp_path: Path):
        """Same legal-empty invariant on the legacy (no-meta) branch."""
        emb_path = tmp_path / "embeddings_default.npy"
        ids_path = tmp_path / "card_ids_default.json"
        np.save(emb_path, np.zeros((0, EMBEDDING_DIM), dtype=np.float32))
        ids_path.write_text(json.dumps([]))
        client = MagicMock()
        llm = TrackedLLM(client, "u")
        store = EmbeddingStore(emb_path, ids_path, llm)
        assert store.count() == 0
        assert emb_path.exists() and ids_path.exists()
        assert not list(tmp_path.glob("*.corrupt_*"))


# --------------------------------------------------------------------- #
# _load truncated-file  (Bug B tail: half-finished _save -> truncated /
# unreadable .npy or ids.json)
#
# An interrupted _save (deploy restart / OOM / power loss) can leave the
# .npy or the ids.json physically truncated, not just row/id-desynced.
# `np.load` on a truncated .npy raises ValueError / EOFError; `json.loads`
# on a truncated ids.json raises JSONDecodeError. Both raise INSIDE _load,
# BEFORE _load_validated's structural checks ever run — so without this
# guard the exception escapes EmbeddingStore.__init__ -> factory fails ->
# every embedding-touching request for the notebook 500s. That is exactly
# the failure mode #546 set out to eliminate, only a different corruption
# shape. The fix degrades it identically: log a warning, quarantine the
# unreadable file as `.corrupt_<reason>`, come up as an empty store that
# the next pipeline run re-embeds. Legal files must stay untouched.
# --------------------------------------------------------------------- #
class TestLoadTruncatedFile:
    def _truncated_npy_bytes(self, frac: float = 0.5) -> bytes:
        """Return the first `frac` of a well-formed 3-row .npy's bytes."""
        import io

        buf = io.BytesIO()
        np.save(buf, np.random.rand(3, EMBEDDING_DIM).astype(np.float32))
        data = buf.getvalue()
        return data[: int(len(data) * frac)]

    def test_truncated_npy_degrades_to_empty(self, tmp_path: Path):
        """A .npy truncated mid-array (np.load raises ValueError) must NOT
        crash __init__: degrade to empty + quarantine, not 500."""
        emb_path = tmp_path / "embeddings_default.npy"
        ids_path = tmp_path / "card_ids_default.json"
        meta_path = tmp_path / "embeddings_meta_default.json"
        emb_path.write_bytes(self._truncated_npy_bytes(0.5))
        ids_path.write_text(json.dumps(["a", "b", "c"]))
        meta_path.write_text(json.dumps(
            {"model": EMBEDDING_MODEL, "dim": EMBEDDING_DIM, "created_at": "x"}
        ))
        client = MagicMock()
        llm = TrackedLLM(client, "u")
        # Must not raise.
        store = EmbeddingStore(emb_path, ids_path, llm)
        assert store.count() == 0
        # Both files quarantined so the live names are clear for a rebuild.
        assert not emb_path.exists() and not ids_path.exists()
        corrupt = list(tmp_path.glob("*.corrupt_*"))
        assert any(p.name.startswith("embeddings_default.npy") for p in corrupt)
        assert any(p.name.startswith("card_ids_default.json") for p in corrupt)
        # Degraded store must be safe to query.
        assert store.find_similar("a") == []

    def test_empty_npy_file_degrades_to_empty(self, tmp_path: Path):
        """A 0-byte .npy (np.load raises EOFError) must degrade, not crash."""
        emb_path = tmp_path / "embeddings_default.npy"
        ids_path = tmp_path / "card_ids_default.json"
        meta_path = tmp_path / "embeddings_meta_default.json"
        emb_path.write_bytes(b"")
        ids_path.write_text(json.dumps(["a"]))
        meta_path.write_text(json.dumps(
            {"model": EMBEDDING_MODEL, "dim": EMBEDDING_DIM, "created_at": "x"}
        ))
        client = MagicMock()
        llm = TrackedLLM(client, "u")
        store = EmbeddingStore(emb_path, ids_path, llm)
        assert store.count() == 0
        assert not emb_path.exists() and not ids_path.exists()

    def test_garbage_npy_file_degrades_to_empty(self, tmp_path: Path):
        """A .npy whose bytes are not a valid array (np.load raises ValueError
        about pickled data) must degrade, not crash."""
        emb_path = tmp_path / "embeddings_default.npy"
        ids_path = tmp_path / "card_ids_default.json"
        meta_path = tmp_path / "embeddings_meta_default.json"
        emb_path.write_bytes(b"\x00\x01garbage not a npy file at all")
        ids_path.write_text(json.dumps(["a"]))
        meta_path.write_text(json.dumps(
            {"model": EMBEDDING_MODEL, "dim": EMBEDDING_DIM, "created_at": "x"}
        ))
        client = MagicMock()
        llm = TrackedLLM(client, "u")
        store = EmbeddingStore(emb_path, ids_path, llm)
        assert store.count() == 0
        assert not emb_path.exists() and not ids_path.exists()

    def test_truncated_ids_json_degrades_to_empty(self, tmp_path: Path):
        """ids.json cut mid-write (json.loads raises JSONDecodeError) must
        degrade, not crash __init__."""
        emb_path = tmp_path / "embeddings_default.npy"
        ids_path = tmp_path / "card_ids_default.json"
        meta_path = tmp_path / "embeddings_meta_default.json"
        np.save(emb_path, np.random.rand(3, EMBEDDING_DIM).astype(np.float32))
        ids_path.write_text('["a","b","c')  # truncated mid-array
        meta_path.write_text(json.dumps(
            {"model": EMBEDDING_MODEL, "dim": EMBEDDING_DIM, "created_at": "x"}
        ))
        client = MagicMock()
        llm = TrackedLLM(client, "u")
        store = EmbeddingStore(emb_path, ids_path, llm)
        assert store.count() == 0
        assert not emb_path.exists() and not ids_path.exists()
        corrupt = list(tmp_path.glob("*.corrupt_*"))
        assert any(p.name.startswith("embeddings_default.npy") for p in corrupt)
        assert any(p.name.startswith("card_ids_default.json") for p in corrupt)

    def test_binary_garbage_ids_json_degrades_to_empty(self, tmp_path: Path):
        """ids.json holding raw non-UTF-8 bytes (read_text raises
        UnicodeDecodeError) must degrade, not crash."""
        emb_path = tmp_path / "embeddings_default.npy"
        ids_path = tmp_path / "card_ids_default.json"
        meta_path = tmp_path / "embeddings_meta_default.json"
        np.save(emb_path, np.random.rand(2, EMBEDDING_DIM).astype(np.float32))
        ids_path.write_bytes(b"\xff\xfe\x00\x01\x02garbage")
        meta_path.write_text(json.dumps(
            {"model": EMBEDDING_MODEL, "dim": EMBEDDING_DIM, "created_at": "x"}
        ))
        client = MagicMock()
        llm = TrackedLLM(client, "u")
        store = EmbeddingStore(emb_path, ids_path, llm)
        assert store.count() == 0
        assert not emb_path.exists() and not ids_path.exists()

    def test_truncated_npy_legacy_no_sidecar_degrades(self, tmp_path: Path):
        """The legacy (no-meta) load branch must degrade on a truncated .npy
        too — it calls the same _load_validated."""
        emb_path = tmp_path / "embeddings_default.npy"
        ids_path = tmp_path / "card_ids_default.json"
        emb_path.write_bytes(self._truncated_npy_bytes(0.5))
        ids_path.write_text(json.dumps(["a", "b", "c"]))
        client = MagicMock()
        llm = TrackedLLM(client, "u")
        store = EmbeddingStore(emb_path, ids_path, llm)
        assert store.count() == 0
        assert not emb_path.exists() and not ids_path.exists()

    def test_aligned_store_still_loads_after_fix(self, tmp_path: Path):
        """Regression guard: a correctly-written store must keep loading —
        the truncated-file try/except must not swallow legal vectors."""
        store, _, _ = _make_store(tmp_path, preload_ids=["a", "b", "c"])
        assert store.count() == 3
        assert not list(tmp_path.glob("*.corrupt_*"))

    def test_legal_empty_store_still_loads_after_fix(self, tmp_path: Path):
        """Regression guard: a legal 0-row empty store must not be quarantined
        by the truncated-file guard."""
        emb_path = tmp_path / "embeddings_default.npy"
        ids_path = tmp_path / "card_ids_default.json"
        meta_path = tmp_path / "embeddings_meta_default.json"
        np.save(emb_path, np.zeros((0, EMBEDDING_DIM), dtype=np.float32))
        ids_path.write_text(json.dumps([]))
        meta_path.write_text(json.dumps(
            {"model": EMBEDDING_MODEL, "dim": EMBEDDING_DIM, "created_at": "x"}
        ))
        client = MagicMock()
        llm = TrackedLLM(client, "u")
        store = EmbeddingStore(emb_path, ids_path, llm)
        assert store.count() == 0
        assert emb_path.exists() and ids_path.exists()
        assert not list(tmp_path.glob("*.corrupt_*"))
