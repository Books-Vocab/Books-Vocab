"""D1: find_similar argpartition top-k correctness.

find_similar's internal top-k selection switched from a full
``argsort(...)[::-1][:k+1]`` to ``np.argpartition`` (partial selection)
to cut O(N log N) sort cost on large stores down to O(N + k log k).

The contract is deliberately asymmetric, and these tests pin both halves:

* **Continuous (no exact ties)** — argpartition is *fully equivalent* to a
  full argsort: same id ranking, same scores, element-for-element. 3072-dim
  float32 real embeddings effectively never tie exactly, so this is the
  branch the production judge pipeline actually exercises.
* **Exact ties straddling the top-k boundary** — when several elements share
  an *exactly equal* score and that tie block crosses the ``n-(k+1)``
  partition boundary, argpartition may select a *different subset of ids*
  than full argsort (which id falls just inside vs. just outside the cut is
  tie-break-dependent). The honest, weaker invariant that always holds: the
  returned **score multiset** equals full-sort's top-k score multiset. We do
  NOT assert id-set equality here, because that is genuinely not guaranteed.

Plus the k >= N degenerate case (pool is the whole array; partition is
skipped and a full sort runs).
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


def _vec_for_cosine(c: float) -> np.ndarray:
    """A 2-D vector whose cosine against the e0 axis (1,0) is exactly ``c``.

    cos = x / sqrt(x^2 + y^2); with x=c, y=sqrt(1-c^2) the vector is unit-norm
    and the cosine is ``c`` to float precision. Lets us hand-build a similarity
    spectrum with an *exact* tie block at a chosen position.
    """
    return np.array([c, np.sqrt(max(0.0, 1.0 - c * c))], dtype=np.float64)


def test_find_similar_tie_block_straddles_boundary_score_multiset(tmp_path: Path):
    """Honest, weaker tie contract: id subset MAY differ from full argsort, but
    the selected score multiset must match.

    Construction: query is ``q`` on the e0 axis. Its similarity spectrum is

        q=1.0 | a=b=c=d=0.8 (EXACT tie block) | e=0.5 f=0.3 g=0.1

    With k=3 -> want = k+1 = 4 and n = 8, the partition boundary sits at
    ``n-want = 4``. The four exactly-tied 0.8 elements (a,b,c,d) span ranks
    2..5 of the full order, i.e. the tie block *straddles* the want=4 cut: only
    three of {a,b,c,d} fit inside the kept pool and *which three* is
    tie-break-dependent. argpartition's choice can legitimately differ from
    full argsort's. So we assert the invariant that genuinely holds — the
    multiset of returned scores equals full-sort's top-k score multiset — and
    deliberately do NOT assert id-set equality.
    """
    spectrum = [1.0, 0.8, 0.8, 0.8, 0.8, 0.5, 0.3, 0.1]
    vectors = np.stack([_vec_for_cosine(c) for c in spectrum])
    ids = ["q", "a", "b", "c", "d", "e", "f", "g"]
    store = _make_store_with_vectors(tmp_path, ids, vectors)

    got = store.find_similar("q", k=3)
    ref = _reference_find_similar(store, "q", k=3)

    got_ids = [cid for cid, _ in got]
    assert "q" not in got_ids
    assert len(got) == 3

    # Weaker-but-true contract: same score multiset as the full-sort oracle.
    got_scores = sorted(round(s, 9) for _, s in got)
    ref_scores = sorted(round(s, 9) for _, s in ref)
    assert got_scores == ref_scores, f"score multiset diverged: {got_scores} vs {ref_scores}"

    # All three winners come from the tied 0.8 block (e=0.5 must never appear);
    # stored as float32 so compare with tolerance, not the literal 0.8.
    assert all(abs(s - 0.8) < 1e-6 for s in got_scores)
    assert set(got_ids) <= {"a", "b", "c", "d"}


def test_find_similar_continuous_full_equivalence(tmp_path: Path):
    """Strong contract on the production-realistic branch (no exact ties):
    argpartition is element-for-element identical to full argsort in *both*
    id ranking and scores. This is the branch 3072-dim float32 data hits."""
    rng = np.random.default_rng(2024)
    n, dim = 30, 12
    vectors = rng.standard_normal((n, dim))  # continuous -> no exact ties
    ids = [f"c{i}" for i in range(n)]
    store = _make_store_with_vectors(tmp_path, ids, vectors)

    for k in (1, 3, 7, 15):
        for q in ("c0", "c11", "c29"):
            got = store.find_similar(q, k=k)
            ref = _reference_find_similar(store, q, k=k)
            assert got == ref, f"full equivalence broke for q={q} k={k}"
