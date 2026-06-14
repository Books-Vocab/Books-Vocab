"""C1 — make_sqlite_engine: per-pooled-connection WAL/NORMAL/busy_timeout via
the SQLAlchemy ``connect`` event listener.

The listener (vs a one-shot PRAGMA on the construction-time connection) is the
load-bearing guarantee: *every* pooled connection — including ones the pool
opens later after a dispose/reconnect — must carry WAL + busy_timeout. These
tests are the gatekeeper for that invariant.
"""

from __future__ import annotations

from sqlalchemy import text

from kg.sqlite_utils import DEFAULT_BUSY_TIMEOUT_MS, make_sqlite_engine


def test_make_sqlite_engine_sets_wal(tmp_path):
    engine = make_sqlite_engine(tmp_path / "wal.db")
    try:
        with engine.connect() as conn:
            mode = conn.exec_driver_sql("PRAGMA journal_mode").scalar()
        # On-disk sqlite supports WAL; tolerate degradation elsewhere by only
        # asserting here where tmp_path is a real filesystem.
        assert mode == "wal"
    finally:
        engine.dispose()


def test_pragmas_applied_to_every_pooled_connection(tmp_path):
    """Open several connections, dispose the pool, then reconnect — each fresh
    pooled connection must independently carry wal + busy_timeout=30000.

    A one-shot construction PRAGMA would fail busy_timeout here because the
    reconnect after dispose opens a brand-new dbapi connection.
    """
    engine = make_sqlite_engine(tmp_path / "pool.db")
    try:
        for _ in range(3):
            with engine.connect() as conn:
                assert conn.exec_driver_sql("PRAGMA journal_mode").scalar() == "wal"
                assert (
                    conn.exec_driver_sql("PRAGMA busy_timeout").scalar()
                    == DEFAULT_BUSY_TIMEOUT_MS
                )

        # Force every pooled connection to be discarded and reopened.
        engine.dispose()

        with engine.connect() as conn:
            assert conn.exec_driver_sql("PRAGMA journal_mode").scalar() == "wal"
            assert (
                conn.exec_driver_sql("PRAGMA busy_timeout").scalar()
                == DEFAULT_BUSY_TIMEOUT_MS
            )
            assert conn.exec_driver_sql("PRAGMA synchronous").scalar() == 1  # NORMAL
    finally:
        engine.dispose()


def test_creates_parent_dir(tmp_path):
    nested = tmp_path / "a" / "b" / "c" / "db.sqlite"
    assert not nested.parent.exists()
    engine = make_sqlite_engine(nested)
    try:
        assert nested.parent.exists()
        # Sanity: the engine is usable.
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    finally:
        engine.dispose()
