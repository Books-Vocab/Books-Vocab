"""Concurrency regression for the four global SQLite log singletons.

`judge_log`, `translate_log`, `pipeline_log`, and `token_tracker` all share
one `sqlite3.Connection` across threads via `check_same_thread=False`. Without
WAL + busy_timeout (configured via `kg.sqlite_utils.init_sqlite_pragmas`),
concurrent writers collide on the writer-exclusive transaction and surface
``OperationalError: database is locked``.

These tests open N threads that pound each table with inserts and assert no
`OperationalError` escapes the module's own lock-and-commit.
"""

from __future__ import annotations

import sqlite3
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed


def _drive(fn, n_threads: int, calls_per_thread: int) -> list[BaseException]:
    """Run `fn(i)` from `n_threads` threads, `calls_per_thread` times each.
    Returns the list of exceptions raised (empty list = success)."""
    errors: list[BaseException] = []
    err_lock = threading.Lock()

    def worker(start_idx: int) -> None:
        for i in range(calls_per_thread):
            try:
                fn(start_idx * calls_per_thread + i)
            except BaseException as e:  # noqa: BLE001
                with err_lock:
                    errors.append(e)
                raise

    with ThreadPoolExecutor(max_workers=n_threads) as ex:
        futures = [ex.submit(worker, i) for i in range(n_threads)]
        for f in as_completed(futures):
            try:
                f.result()
            except BaseException:
                pass  # already captured
    return errors


def test_pragmas_helper_applied(monkeypatch, tmp_path):
    """Direct unit check: opening a fresh connection via init_sqlite_pragmas
    flips journal_mode to WAL and sets a non-zero busy_timeout."""
    from kg.sqlite_utils import init_sqlite_pragmas

    conn = sqlite3.connect(str(tmp_path / "x.db"))
    init_sqlite_pragmas(conn)
    mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    timeout = conn.execute("PRAGMA busy_timeout").fetchone()[0]
    sync = conn.execute("PRAGMA synchronous").fetchone()[0]
    assert mode.lower() == "wal", f"expected WAL, got {mode!r}"
    assert timeout >= 1000, f"expected busy_timeout>=1000ms, got {timeout}"
    # synchronous=NORMAL is value 1 per SQLite docs.
    assert sync == 1, f"expected synchronous=NORMAL (1), got {sync}"


def test_judge_log_concurrent_writes_no_locked(tmp_path, monkeypatch):
    monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
    import kg.judge_log as jl
    jl._reset()
    # Force module's DB_PATH to recompute against the new KG_DATA_DIR.
    monkeypatch.setattr(jl, "DB_PATH", tmp_path / "judge_log.db")

    def record(i: int) -> None:
        jl.record(
            user_id=f"u_{i % 4}",
            notebook_id="nb",
            from_id=f"f{i}", to_id=f"t{i}",
            similarity=0.5,
            verdict="accept", confidence=0.9, accepted=True,
        )

    errors = _drive(record, n_threads=8, calls_per_thread=25)
    jl._reset()
    assert not any(isinstance(e, sqlite3.OperationalError) for e in errors), (
        f"sqlite OperationalError under concurrent judge_log writes: {errors!r}"
    )
    assert not errors, f"unexpected errors: {errors!r}"


def test_translate_log_concurrent_writes_no_locked(tmp_path, monkeypatch):
    monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
    import kg.translate_log as tl
    tl._reset()

    def record(i: int) -> None:
        tl.record(
            user_id=f"u_{i % 4}",
            operation="explain",
            word=f"word_{i}",
            context=f"ctx_{i}",
            context_hash=f"h_{i}",
            source_lang="en", target_lang="zh-Hant",
            response_raw="{}",
            latency_ms=100,
        )

    errors = _drive(record, n_threads=8, calls_per_thread=25)
    tl._reset()
    assert not any(isinstance(e, sqlite3.OperationalError) for e in errors), (
        f"sqlite OperationalError under concurrent translate_log writes: {errors!r}"
    )
    assert not errors, f"unexpected errors: {errors!r}"


def test_pipeline_log_concurrent_writes_no_locked(tmp_path, monkeypatch):
    monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
    import kg.pipeline_log as pl
    pl._reset()
    monkeypatch.setattr(pl, "DB_PATH", tmp_path / "pipeline_runs.db")

    def record(i: int) -> None:
        run_id = f"run_{uuid.uuid4().hex[:12]}"
        pl.start_run(run_id, f"u_{i % 4}", "nb", "test")
        pl.start_step(run_id, "step_a")
        pl.end_step(run_id, "step_a", status="ok", items=1)
        pl.end_run(run_id, "completed")

    errors = _drive(record, n_threads=6, calls_per_thread=15)
    pl._reset()
    assert not any(isinstance(e, sqlite3.OperationalError) for e in errors), (
        f"sqlite OperationalError under concurrent pipeline_log writes: {errors!r}"
    )
    assert not errors, f"unexpected errors: {errors!r}"


def test_token_tracker_concurrent_writes_no_locked(tmp_path, monkeypatch):
    monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
    import kg.token_tracker as tt
    # token_tracker has no _reset helper — close the connection manually so
    # the next _get_conn() rebuilds with the patched DB_PATH.
    if tt._conn is not None:
        tt._conn.close()
        tt._conn = None
    monkeypatch.setattr(tt, "DB_PATH", tmp_path / "token_usage.db")

    def record(i: int) -> None:
        tt.record(f"u_{i % 4}", "translate", 100, 50)

    errors = _drive(record, n_threads=8, calls_per_thread=25)
    if tt._conn is not None:
        tt._conn.close()
        tt._conn = None
    assert not any(isinstance(e, sqlite3.OperationalError) for e in errors), (
        f"sqlite OperationalError under concurrent token_tracker writes: {errors!r}"
    )
    assert not errors, f"unexpected errors: {errors!r}"


# ---------------------------------------------------------------------------
# CardStore same-card concurrent modification.
#
# CardStore opens its SQLite DB in WAL mode with busy_timeout=30000ms, so the
# writer-exclusive transaction is serialised. These are characterization tests:
# they pound a single card (or a single notebook) from N threads and assert the
# final on-disk state is self-consistent — no lost row, no "tombstone that was
# updated after delete", no corrupted review state.
# ---------------------------------------------------------------------------


def test_concurrent_update_same_card_consistent(tmp_path):
    """N threads update the SAME card simultaneously. The row must survive,
    stay non-deleted, and land on exactly one of the values each thread wrote."""
    from kg.cards import CardStore

    store = CardStore(tmp_path / "cards.db")
    card = store.add(content="alpha", meaning="initial")
    cid = card.id

    n_threads, calls = 8, 20

    def do_update(i: int) -> None:
        store.update(cid, note=f"note_{i}", review_count=i)

    errors = _drive(do_update, n_threads=n_threads, calls_per_thread=calls)
    store.close()

    assert not any(isinstance(e, sqlite3.OperationalError) for e in errors), (
        f"sqlite OperationalError under concurrent same-card update: {errors!r}"
    )
    assert not errors, f"unexpected errors: {errors!r}"

    store2 = CardStore(tmp_path / "cards.db")
    try:
        # Exactly one row, still present, not soft-deleted.
        all_rows = list(store2.all(include_deleted=True))
        assert len(all_rows) == 1, f"lost/duplicated row: {all_rows!r}"
        final = store2.get(cid)
        assert final is not None, "card vanished after concurrent updates"
        assert final.is_deleted is False
        # The surviving note/review_count must be a value some thread wrote.
        total = n_threads * calls
        valid_notes = {f"note_{i}" for i in range(total)}
        assert final.note in valid_notes, f"final.note not from any writer: {final.note!r}"
        assert 0 <= final.review_count < total, (
            f"review_count out of written range: {final.review_count}"
        )
    finally:
        store2.close()


def test_concurrent_delete_and_update_same_card(tmp_path):
    """delete + update race on the SAME card, repeated many rounds.

    CHARACTERIZATION (documents a known TOCTOU): both ``delete()`` and
    ``update()`` do read-then-write inside a Session — they read the row,
    check ``is_deleted``, then commit. WAL+busy_timeout serialises the
    *commits* but not the read→commit window, so when update reads a still-
    live row, then delete commits the tombstone, update's later commit lands
    on the now-deleted row. Result: a row with ``is_deleted=1`` AND the
    updated fields applied (a "resurrected tombstone" field-wise).

    This is benign for sync correctness (the row is still deleted, so clients
    drop it) but the test pins the two legal end states so a regression that
    e.g. *un*-deletes the row or loses the row entirely is caught."""
    from kg.cards import CardStore

    store = CardStore(tmp_path / "cards.db")
    n_rounds = 30
    cids: list[str] = []
    for r in range(n_rounds):
        cids.append(store.add(content=f"beta_{r}", meaning="initial").id)

    errors: list[BaseException] = []
    err_lock = threading.Lock()

    def guard(fn, *a):
        try:
            fn(*a)
        except BaseException as e:  # noqa: BLE001
            with err_lock:
                errors.append(e)

    for cid in cids:
        barrier = threading.Barrier(2)

        def do_delete(c=cid, b=barrier) -> None:
            b.wait()
            store.delete(c)

        def do_update(c=cid, b=barrier) -> None:
            b.wait()
            store.update(c, note="raced", review_count=99)

        with ThreadPoolExecutor(max_workers=2) as ex:
            f1 = ex.submit(guard, do_delete)
            f2 = ex.submit(guard, do_update)
            f1.result()
            f2.result()
    store.close()

    assert not any(isinstance(e, sqlite3.OperationalError) for e in errors), (
        f"sqlite OperationalError under delete/update race: {errors!r}"
    )
    assert not errors, f"unexpected errors: {errors!r}"

    store2 = CardStore(tmp_path / "cards.db")
    try:
        for cid in cids:
            final = store2.get(cid)
            assert final is not None, f"card row {cid} disappeared"
            # Two legal outcomes only:
            #   A) update won the read+commit ordering, card stays live & updated
            #   B) delete committed; card is a tombstone (fields may or may not
            #      reflect the racing update — both acceptable since deleted).
            if not final.is_deleted:
                # update applied and delete must not have committed a tombstone
                assert final.note == "raced", (
                    f"{cid}: live card but update lost: note={final.note!r}"
                )
                assert final.review_count == 99
            # If is_deleted: nothing more to assert — the card is correctly
            # tombstoned; field state is irrelevant to a deleted card.
    finally:
        store2.close()


def test_card_store_uses_make_sqlite_engine(tmp_path, monkeypatch):
    """CardStore must build its engine via the shared make_sqlite_engine helper
    (pool-wide WAL listener), not an inline one-shot PRAGMA. Spy on the symbol
    the store actually calls and assert it fired with the cards.db path."""
    import kg.cards.store as cs
    from kg.sqlite_utils import make_sqlite_engine as real

    calls: list[object] = []

    def spy(path, **kw):
        calls.append(path)
        return real(path, **kw)

    monkeypatch.setattr(cs, "make_sqlite_engine", spy)
    store = cs.CardStore(tmp_path / "cards.db")
    try:
        assert calls, "CardStore did not call make_sqlite_engine"
        assert str(calls[0]).endswith("cards.db")
    finally:
        store.close()


def test_notebook_store_uses_make_sqlite_engine(tmp_path, monkeypatch):
    """NotebookStore must build its engine via make_sqlite_engine."""
    import kg.notebook as nb
    from kg.sqlite_utils import make_sqlite_engine as real

    calls: list[object] = []

    def spy(path, **kw):
        calls.append(path)
        return real(path, **kw)

    monkeypatch.setattr(nb, "make_sqlite_engine", spy)
    store = nb.NotebookStore(tmp_path / "notebooks.db")
    try:
        assert calls, "NotebookStore did not call make_sqlite_engine"
        assert str(calls[0]).endswith("notebooks.db")
    finally:
        store.close()


def test_concurrent_batch_touch_no_corruption(tmp_path):
    """N threads batch_touch the SAME notebook concurrently. Review state
    (review_count, next_review_at, is_deleted) must be untouched — batch_touch
    only bumps updated_at — and every card must remain readable & consistent."""
    from kg.cards import CardStore

    store = CardStore(tmp_path / "cards.db")
    ids: list[str] = []
    for i in range(12):
        c = store.add(content=f"word_{i}", meaning=f"m_{i}", notebook_id="nb")
        # Seed distinct review state we expect to remain invariant.
        store.update(c.id, review_count=i, review_streak=i * 2)
        ids.append(c.id)

    def do_touch(_i: int) -> None:
        store.batch_touch(ids, notebook_id="nb")

    errors = _drive(do_touch, n_threads=8, calls_per_thread=15)
    store.close()

    assert not any(isinstance(e, sqlite3.OperationalError) for e in errors), (
        f"sqlite OperationalError under concurrent batch_touch: {errors!r}"
    )
    assert not errors, f"unexpected errors: {errors!r}"

    store2 = CardStore(tmp_path / "cards.db")
    try:
        rows = store2.all_as_dict(include_deleted=True, notebook_id="nb")
        assert len(rows) == 12, f"card count changed: {len(rows)}"
        for i, cid in enumerate(ids):
            card = rows[cid]
            assert card.is_deleted is False, f"{cid} flipped to deleted"
            assert card.review_count == i, (
                f"review_count corrupted: {cid} -> {card.review_count} (want {i})"
            )
            assert card.review_streak == i * 2, (
                f"review_streak corrupted: {cid} -> {card.review_streak}"
            )
    finally:
        store2.close()
