"""D1: find_similar argpartition top-k correctness.

find_similar's internal top-k selection switched from a full
``argsort(...)[::-1][:k+1]`` to ``np.argpartition`` (partial selection)
to cut O(N log N) sort cost on large stores down to O(N + k log k).

These tests pin the externally observable contract: the new path must
return *exactly* the same (id, score) ranking as a reference argsort
implementation, must handle k >= N, and must keep tie ordering stable.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np

from kg.embeddings import EMBEDDING_MODEL, EmbeddingStore
from kg.tracked_llm import TrackedLLM


def _make_store_with_vectors(tmp_path: Path, ids: list[str], vectors: np.ndarray):
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


def _reference_find_similar(store: EmbeddingStore, card_id: str, k: int):
    """Old full-argsort implementation, used as the equivalence oracle."""
    idx = store._id_pos[card_id]
    query_vec = store._embeddings[idx]
    norms = store._get_norms()
    sims = (store._embeddings @ query_vec) / (norms * norms[idx] + 1e-9)
    top = np.argsort(sims)[::-1][: k + 1]
    out = []
    for i in top:
        if store._ids[i] != card_id:
            out.append((store._ids[i], float(sims[i])))
    return out[:k]


def test_find_similar_argpartition_matches_argsort(tmp_path: Path):
    rng = np.random.default_rng(42)
    n, dim = 50, 16
    vectors = rng.standard_normal((n, dim))
    ids = [f"c{i}" for i in range(n)]
    store = _make_store_with_vectors(tmp_path, ids, vectors)

    for k in (1, 5, 10, 25):
        for q in ("c0", "c17", "c49"):
            got = store.find_similar(q, k=k)
            ref = _reference_find_similar(store, q, k=k)
            got_ids = [cid for cid, _ in got]
            ref_ids = [cid for cid, _ in ref]
            assert got_ids == ref_ids, f"id ranking diverged for q={q} k={k}"
            for (gi, gs), (ri, rs) in zip(got, ref, strict=True):
                assert gi == ri
                assert gs == rs, f"score diverged for {gi}"


def test_find_similar_k_larger_than_n(tmp_path: Path):
    rng = np.random.default_rng(7)
    n, dim = 4, 8
    vectors = rng.standard_normal((n, dim))
    ids = [f"c{i}" for i in range(n)]
    store = _make_store_with_vectors(tmp_path, ids, vectors)

    # k far exceeds available neighbours -> all N-1 others, no self, no crash.
    got = store.find_similar("c0", k=100)
    got_ids = [cid for cid, _ in got]
    assert "c0" not in got_ids
    assert len(got) == n - 1
    assert got == _reference_find_similar(store, "c0", k=100)


def test_find_similar_ties_stable(tmp_path: Path):
    # Several identical vectors -> identical similarity scores (ties). The
    # partition path must still return a coherent top-k matching the argsort
    # oracle and never include self.
    dim = 8
    base = np.ones(dim)
    vectors = np.stack([base, base, base, base, base * 2.0])
    ids = ["a", "b", "c", "d", "e"]
    store = _make_store_with_vectors(tmp_path, ids, vectors)

    got = store.find_similar("a", k=3)
    got_ids = [cid for cid, _ in got]
    assert "a" not in got_ids
    assert len(got) == 3
    assert got == _reference_find_similar(store, "a", k=3)
