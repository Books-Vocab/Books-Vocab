"""#2061: EmbeddingStore under concurrent writers.

One cached store per notebook is shared by request threads and the pipeline
(``run_in_executor``). Without a lock, concurrent ``add_batch`` /
``remove_batch`` interleave their read-modify-write of ``_embeddings`` /
``_ids`` (rows and ids drift apart, which ``find_similar`` silently
misattributes) and race on the *fixed* temp filenames in ``_save`` (one
writer's ``replace()`` moves another writer's half-written temp, or finds it
already gone).
"""

from __future__ import annotations

import os
import threading
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from kg.embeddings import EmbeddingStore

_DIM = 16


class _BarrierLLM:
    """Thread-safe fake embedder: concurrent calls return together, so every
    writer reaches the append + save section at the same moment."""

    def __init__(self, parties: int) -> None:
        self._barrier = threading.Barrier(parties)

    def embed(self, call_type: str, *, input: list[str], model: str):  # noqa: A002 - SDK kwarg name
        try:
            self._barrier.wait(timeout=5)
        except threading.BrokenBarrierError:
            pass
        rng = np.random.default_rng()
        data = [
            SimpleNamespace(index=i, embedding=rng.random(_DIM, dtype=np.float32).tolist()) for i in range(len(input))
        ]
        return SimpleNamespace(data=data, usage=None)


def _paths(tmp_path: Path) -> tuple[Path, Path]:
    return tmp_path / "embeddings_default.npy", tmp_path / "card_ids_default.json"


def _run_threads(target, n: int) -> list[BaseException]:
    errors: list[BaseException] = []

    def wrapped(i: int) -> None:
        try:
            target(i)
        except BaseException as exc:  # noqa: BLE001 - surfaced through the assertion
            errors.append(exc)

    threads = [threading.Thread(target=wrapped, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert not any(t.is_alive() for t in threads), "writer thread hung"
    return errors


def _assert_aligned(store: EmbeddingStore, expected_ids: set[str]) -> None:
    assert store._embeddings is not None
    assert len(store._ids) == store._embeddings.shape[0]
    assert set(store._ids) == expected_ids
    assert len(store._ids) == len(expected_ids), "duplicate rows for one card id"
    assert store._id_pos == {cid: i for i, cid in enumerate(store._ids)}


def _assert_disk_matches(tmp_path: Path, expected_ids: set[str]) -> None:
    emb_path, ids_path = _paths(tmp_path)
    reloaded = EmbeddingStore(emb_path, ids_path, None, model="m", dim=_DIM)
    assert not list(tmp_path.glob("*.corrupt_*")), "on-disk rows/ids desynced and were quarantined"
    _assert_aligned(reloaded, expected_ids)
    leftovers = sorted(p.name for p in tmp_path.iterdir() if "tmp" in p.name)
    assert leftovers == [], f"temp files left behind: {leftovers}"


def test_concurrent_add_batch_keeps_ids_and_rows_aligned(tmp_path: Path):
    workers, rounds, per_batch = 8, 4, 5
    emb_path, ids_path = _paths(tmp_path)
    store = EmbeddingStore(emb_path, ids_path, _BarrierLLM(workers), model="m", dim=_DIM)

    def work(w: int) -> None:
        for r in range(rounds):
            store.add_batch([(f"w{w}-r{r}-{i}", "text") for i in range(per_batch)])

    errors = _run_threads(work, workers)

    assert errors == []
    expected = {f"w{w}-r{r}-{i}" for w in range(workers) for r in range(rounds) for i in range(per_batch)}
    _assert_aligned(store, expected)
    _assert_disk_matches(tmp_path, expected)


def test_concurrent_add_and_remove_keep_ids_and_rows_aligned(tmp_path: Path):
    emb_path, ids_path = _paths(tmp_path)
    seed = [(f"seed-{i}", "text") for i in range(40)]
    EmbeddingStore(emb_path, ids_path, _BarrierLLM(1), model="m", dim=_DIM).add_batch(seed)
    adders = 4
    store = EmbeddingStore(emb_path, ids_path, _BarrierLLM(adders), model="m", dim=_DIM)

    def work(w: int) -> None:
        if w < adders:
            for r in range(3):
                store.add_batch([(f"a{w}-{r}-{i}", "text") for i in range(5)])
        else:
            for i in range(w - adders, 40, 4):
                store.remove_batch([f"seed-{i}"])

    errors = _run_threads(work, adders + 4)

    assert errors == []
    expected = {f"a{w}-{r}-{i}" for w in range(adders) for r in range(3) for i in range(5)}
    _assert_aligned(store, expected)
    _assert_disk_matches(tmp_path, expected)


def test_every_save_uses_its_own_temp_files(tmp_path: Path, monkeypatch):
    """Two store instances on one notebook's files (a cache eviction while a
    pipeline still holds the old instance; another process) must never share
    a temp path, or one writer's replace() swaps in the other's torn file."""
    emb_path, ids_path = _paths(tmp_path)
    first = EmbeddingStore(emb_path, ids_path, _BarrierLLM(1), model="m", dim=_DIM)
    second = EmbeddingStore(emb_path, ids_path, _BarrierLLM(1), model="m", dim=_DIM)

    replaced_from: list[str] = []
    real_replace = os.replace

    def spy_replace(src, dst):
        replaced_from.append(os.fspath(src))
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", spy_replace)

    first.add_batch([("c1", "text")])
    second.add_batch([("c2", "text")])
    first.remove_batch(["c1"])

    assert len(replaced_from) >= 7  # (npy + ids) x 3 saves + first sidecar
    assert len(set(replaced_from)) == len(replaced_from), f"temp path reused: {replaced_from}"
    assert all(Path(src).parent == tmp_path for src in replaced_from), "temp must live beside its target"
