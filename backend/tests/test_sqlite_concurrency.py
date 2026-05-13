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
