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


def test_concurrent_add_batch_same_id_adds_one_row(tmp_path: Path):
    """Two writers add the SAME ids; the barrier embedder makes both embed
    before either commits, so both pass the pre-embed "not present" filter.
    The post-embed re-check under the lock must keep exactly one row per id."""
    n = 5
    emb_path, ids_path = _paths(tmp_path)
    store = EmbeddingStore(emb_path, ids_path, _BarrierLLM(2), model="m", dim=_DIM)
    items = [(f"same-{i}", "text") for i in range(n)]

    errors = _run_threads(lambda _i: store.add_batch(list(items)), 2)

    assert errors == []
    assert store._embeddings is not None
    assert len(store._ids) == store._embeddings.shape[0] == n
    assert len(set(store._ids)) == n, f"duplicate ids: {store._ids}"
    expected = {cid for cid, _ in items}
    _assert_aligned(store, expected)
    _assert_disk_matches(tmp_path, expected)


class _GatedLLM:
    """Deterministic embedder (text "7" -> all-7.0 vector) whose calls can be
    parked mid-flight, so a test can interleave another writer exactly while
    ``update`` is embedding outside the lock."""

    def __init__(self) -> None:
        self.gate = False
        self.entered = threading.Event()
        self.release = threading.Event()

    def embed(self, call_type: str, *, input: list[str], model: str):  # noqa: A002 - SDK kwarg name
        if self.gate:
            self.entered.set()
            assert self.release.wait(timeout=5), "test never released the parked embedder"
        data = [SimpleNamespace(index=i, embedding=[float(text)] * _DIM) for i, text in enumerate(input)]
        return SimpleNamespace(data=data, usage=None)


def _seed_gated_store(tmp_path: Path, n: int = 6) -> tuple[EmbeddingStore, _GatedLLM]:
    """Store with cards c0..c{n-1}; c{i} holds the all-(i+1) vector."""
    emb_path, ids_path = _paths(tmp_path)
    llm = _GatedLLM()
    store = EmbeddingStore(emb_path, ids_path, llm, model="m", dim=_DIM)
    store.add_batch([(f"c{i}", str(i + 1)) for i in range(n)])
    return store, llm


def _update_while_removing(store: EmbeddingStore, llm: _GatedLLM, *, updated: str, text: str, removed: str) -> None:
    """Park ``update(updated, text)`` inside its embed call, run
    ``remove_batch([removed])`` to completion, then let the update resume."""
    llm.gate = True
    errors: list[BaseException] = []

    def do_update() -> None:
        try:
            store.update(updated, text)
        except BaseException as exc:  # noqa: BLE001 - surfaced through the assertion
            errors.append(exc)

    t = threading.Thread(target=do_update)
    t.start()
    assert llm.entered.wait(timeout=5), "update never reached its embed call"
    assert store.remove_batch([removed]) == 1
    llm.release.set()
    t.join(timeout=10)
    assert not t.is_alive(), "update thread hung"
    assert errors == [], errors


def _row(store: EmbeddingStore, cid: str) -> np.ndarray:
    assert store._embeddings is not None
    return store._embeddings[store._id_pos[cid]]


def test_update_racing_remove_of_same_card_does_not_resurrect_or_corrupt(tmp_path: Path):
    store, llm = _seed_gated_store(tmp_path)

    _update_while_removing(store, llm, updated="c2", text="99", removed="c2")

    survivors = {"c0", "c1", "c3", "c4", "c5"}
    assert "c2" not in store._ids, "removed card was resurrected by the racing update"
    _assert_aligned(store, survivors)
    for cid in survivors:  # a stale row index would have overwritten c3 with the update's vector
        assert np.all(_row(store, cid) == float(cid[1:]) + 1.0), f"{cid} vector was clobbered"
    store.flush()
    _assert_disk_matches(tmp_path, survivors)


def test_update_re_resolves_row_after_an_earlier_card_is_removed(tmp_path: Path):
    store, llm = _seed_gated_store(tmp_path)

    _update_while_removing(store, llm, updated="c4", text="99", removed="c0")

    survivors = {"c1", "c2", "c3", "c4", "c5"}
    _assert_aligned(store, survivors)
    assert np.all(_row(store, "c4") == 99.0), "update did not land on c4's (shifted) row"
    for cid in survivors - {"c4"}:  # a stale index would have hit c5's row instead
        assert np.all(_row(store, cid) == float(cid[1:]) + 1.0), f"{cid} vector was clobbered"
    store.flush()
    _assert_disk_matches(tmp_path, survivors)


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


# ---------------------------------------------------------------------------
# Two instances over one notebook's files (service-factory LRU eviction during
# a pipeline run, scripts/rebuild_embeddings.py beside the API).
# ---------------------------------------------------------------------------
class _CountingLLM(_GatedLLM):
    """Deterministic embedder (text "7" -> all-7.0) that records every input."""

    def __init__(self) -> None:
        super().__init__()
        self.inputs: list[str] = []

    def embed(self, call_type: str, *, input: list[str], model: str):  # noqa: A002 - SDK kwarg name
        self.inputs.extend(input)
        return super().embed(call_type, input=input, model=model)


def _two_stores(tmp_path: Path) -> tuple[EmbeddingStore, EmbeddingStore, _CountingLLM]:
    emb_path, ids_path = _paths(tmp_path)
    llm = _CountingLLM()
    a = EmbeddingStore(emb_path, ids_path, llm, model="m", dim=_DIM)
    b = EmbeddingStore(emb_path, ids_path, llm, model="m", dim=_DIM)
    return a, b, llm


def test_two_instances_adding_different_rows_keep_both(tmp_path: Path):
    a, b, _ = _two_stores(tmp_path)  # b is built before a's add -> stale
    a.add("a1", "1")
    b.add("b1", "2")
    assert a.refresh_if_stale() is True
    _assert_aligned(a, {"a1", "b1"})
    _assert_aligned(b, {"a1", "b1"})
    _assert_disk_matches(tmp_path, {"a1", "b1"})


def test_stale_instance_does_not_resurrect_removed_row(tmp_path: Path):
    emb_path, ids_path = _paths(tmp_path)
    llm = _CountingLLM()
    seed = EmbeddingStore(emb_path, ids_path, llm, model="m", dim=_DIM)
    seed.add_batch([("x", "1"), ("keep", "2")])
    a = EmbeddingStore(emb_path, ids_path, llm, model="m", dim=_DIM)
    b = EmbeddingStore(emb_path, ids_path, llm, model="m", dim=_DIM)
    assert a.remove_batch(["x"]) == 1
    b.add("y", "3")  # b still believes x exists
    _assert_disk_matches(tmp_path, {"keep", "y"})
    _assert_aligned(b, {"keep", "y"})


def test_add_batch_skips_ids_another_instance_already_embedded(tmp_path: Path):
    a, b, llm = _two_stores(tmp_path)
    a.add("shared", "5")
    llm.inputs.clear()
    b.add_batch([("shared", "5")])
    assert llm.inputs == [], "provider called (and billed) for an id already on disk"
    _assert_disk_matches(tmp_path, {"shared"})


def test_stale_update_then_flush_keeps_new_vector_and_other_rows(tmp_path: Path):
    emb_path, ids_path = _paths(tmp_path)
    llm = _CountingLLM()
    seed = EmbeddingStore(emb_path, ids_path, llm, model="m", dim=_DIM)
    seed.add_batch([("u", "1")])
    a = EmbeddingStore(emb_path, ids_path, llm, model="m", dim=_DIM)
    b = EmbeddingStore(emb_path, ids_path, llm, model="m", dim=_DIM)
    b.update("u", "9")  # deferred, not flushed
    a.add("other", "2")
    b.flush()
    reloaded = EmbeddingStore(emb_path, ids_path, None, model="m", dim=_DIM)
    _assert_aligned(reloaded, {"u", "other"})
    assert np.allclose(_row(reloaded, "u"), 9.0)
    assert np.allclose(_row(reloaded, "other"), 2.0)


def test_two_instances_threaded_mixed_add_remove(tmp_path: Path):
    emb_path, ids_path = _paths(tmp_path)
    llm = _CountingLLM()
    stores = [EmbeddingStore(emb_path, ids_path, llm, model="m", dim=_DIM) for _ in range(2)]

    def work(i: int) -> None:
        store = stores[i % 2]
        for r in range(3):
            store.add_batch([(f"w{i}-{r}-{j}", "1") for j in range(3)])
        store.remove_batch([f"w{i}-0-0", f"w{i}-1-0"])

    assert _run_threads(work, 8) == []
    expected = {f"w{i}-{r}-{j}" for i in range(8) for r in range(3) for j in range(3)}
    expected -= {f"w{i}-0-0" for i in range(8)} | {f"w{i}-1-0" for i in range(8)}
    for s in stores:
        s.refresh_if_stale()
        _assert_aligned(s, expected)
    _assert_disk_matches(tmp_path, expected)


def test_refresh_if_stale_is_stat_only_when_unchanged(tmp_path: Path, monkeypatch):
    a, _, _ = _two_stores(tmp_path)
    a.add("a1", "1")

    def boom(*args, **kwargs):
        raise AssertionError("np.load called for unchanged files")

    monkeypatch.setattr(np, "load", boom)
    assert a.refresh_if_stale() is False
    assert a.find_similar("a1") == []


def test_chunked_add_batch_keeps_other_instance_rows_and_skips_its_ids(tmp_path: Path, monkeypatch):
    """#2264 chunking x #2500: another instance persists rows (one of them
    belonging to a later chunk) while chunk 1 is embedding. Every chunk's
    append must re-read the disk, keep the foreign rows, and not re-embed
    the id that already landed."""
    import kg.embeddings as embeddings_mod

    monkeypatch.setattr(embeddings_mod, "_EMBED_BATCH_LIMIT", 2)
    emb_path, ids_path = _paths(tmp_path)
    other_llm = _CountingLLM()
    other = EmbeddingStore(emb_path, ids_path, other_llm, model="m", dim=_DIM)
    fired: list[bool] = []

    class _LandingLLM(_CountingLLM):
        def embed(self, call_type: str, *, input: list[str], model: str):  # noqa: A002 - SDK kwarg name
            if not fired:
                fired.append(True)
                other.add_batch([("foreign", "9"), ("c3", "4")])
            return super().embed(call_type, input=input, model=model)

    llm = _LandingLLM()
    store = EmbeddingStore(emb_path, ids_path, llm, model="m", dim=_DIM)
    store.add_batch([(f"c{i}", str(i)) for i in range(6)])

    expected = {"c0", "c1", "c2", "c3", "c4", "c5", "foreign"}
    assert llm.inputs.count("3") == 0, "c3 landed via the other instance but was embedded again"
    _assert_aligned(store, expected)
    _assert_disk_matches(tmp_path, expected)
