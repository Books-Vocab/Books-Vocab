"""Shared SQLite pragmas for the global log-style singletons.

Four modules — judge_log, translate_log, pipeline_log, token_tracker — open
a single `sqlite3.Connection` shared across threads via
`check_same_thread=False`, with a `threading.Lock` serialising callers.

Without WAL + busy_timeout, concurrent uvicorn workers (or multi-thread tests)
can collide on the writer-exclusive transaction and surface
``OperationalError: database is locked``. WAL lets readers and a single
writer coexist; busy_timeout makes contending writers block briefly instead
of returning the error immediately. `synchronous=NORMAL` is the documented
safe pairing for WAL (full durability requires `synchronous=FULL`, but the
log singletons are append-only and can tolerate the rare last-row loss on
power failure).

All four singletons must call ``init_sqlite_pragmas(conn)`` once, before
issuing DDL, so the journal mode change takes effect on a fresh connection.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlmodel import create_engine

# 30s is the existing per-module value; keeping it consistent so behaviour
# does not regress when a module switches from inline PRAGMAs to this helper.
DEFAULT_BUSY_TIMEOUT_MS = 30000


def make_sqlite_engine(
    path: Path | str, *, busy_timeout_ms: int = DEFAULT_BUSY_TIMEOUT_MS
) -> Engine:
    """Build a SQLModel/SQLAlchemy ``Engine`` for a per-user SQLite file whose
    **every** pooled connection carries WAL + ``synchronous=NORMAL`` +
    ``busy_timeout``.

    Unlike a one-shot ``PRAGMA`` on the construction-time connection (the
    pattern this replaces in cards/notebook/library stores), the
    ``connect``-event listener re-applies the pragmas to any connection the
    pool opens later — after a dispose/reconnect, or a fresh pooled
    connection under concurrency. This is a behaviour *improvement*, not a
    pure equivalence: pool-wide WAL instead of just the first connection.

    Deliberately **separate from** ``sqlite_ledger.install_serializable_sqlite``:
    that one additionally drives ``BEGIN IMMEDIATE`` for the append-only
    ledgers' serialized take-a-number semantics, which CRUD stores neither
    need nor want (it hurts read concurrency).

    WAL can silently degrade on ``:memory:`` / some network filesystems, so the
    listener never asserts the resulting ``journal_mode``; it only requests it.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{path.absolute()}")
    timeout = int(busy_timeout_ms)

    @event.listens_for(engine, "connect")
    def _configure_connection(dbapi_conn, _record):  # noqa: ANN001
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.execute(f"PRAGMA busy_timeout={timeout}")
        cur.close()

    return engine


def init_sqlite_pragmas(conn: sqlite3.Connection, *, busy_timeout_ms: int = DEFAULT_BUSY_TIMEOUT_MS) -> None:
    """Configure WAL + busy_timeout + synchronous=NORMAL on `conn`.

    Idempotent — calling on an already-WAL connection is a no-op. Must be
    invoked before any write or DDL so the journal mode change persists.
    """
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute(f"PRAGMA busy_timeout={int(busy_timeout_ms)};")
    conn.execute("PRAGMA synchronous=NORMAL;")


def open_singleton(
    db_path: Path | str, *, busy_timeout_ms: int = DEFAULT_BUSY_TIMEOUT_MS
) -> sqlite3.Connection:
    """Open a log-style singleton connection: mkdir parent, connect cross-thread,
    apply the shared pragmas. Caller still issues its own DDL and ``commit``.

    Centralises the ``mkdir(parents=True) + connect(check_same_thread=False) +
    init_sqlite_pragmas`` prologue every singleton's ``_get_conn`` repeats.
    """
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    init_sqlite_pragmas(conn, busy_timeout_ms=busy_timeout_ms)
    return conn


def _driver_execute(conn: Any, sql: str) -> Any:
    """Execute raw SQLite SQL on either sqlite3 or SQLAlchemy connections."""
    execute_driver_sql = getattr(conn, "exec_driver_sql", None)
    if execute_driver_sql is not None:
        return execute_driver_sql(sql)
    return conn.execute(sql)


def _in_transaction(conn: Any) -> bool:
    marker = getattr(conn, "in_transaction", False)
    return bool(marker() if callable(marker) else marker)


def _is_duplicate_column(exc: BaseException) -> bool:
    return "duplicate column" in str(exc).lower()


def ensure_columns(conn: Any, table: str, columns: dict[str, str]) -> set[str]:
    """Idempotently add missing columns on sqlite3 or SQLAlchemy connections.

    Schema introspection and every ``ALTER TABLE`` run under one writer
    transaction.  Without ``BEGIN IMMEDIATE``, two legacy connections can both
    observe the same missing column and one fails with ``duplicate column`` (or
    a lock-upgrade error).  Callers own the surrounding commit; a fresh
    connection is required so this helper can acquire the writer lock before
    reading ``PRAGMA table_info``.

    ``table`` / column identifiers are module-internal literals, never user
    input.  The returned set is the columns this call actually added; existing
    callers may ignore it.
    """
    if not columns:
        return set()

    owns_transaction = not _in_transaction(conn)
    # Set the busy handler before taking the writer lock so direct sqlite3
    # callers with a short connection timeout still receive the helper's
    # bounded wait contract.
    _driver_execute(conn, f"PRAGMA busy_timeout={DEFAULT_BUSY_TIMEOUT_MS}")
    if owns_transaction:
        try:
            _driver_execute(conn, "BEGIN IMMEDIATE")
        except Exception as exc:  # noqa: BLE001 - normalize driver wrappers
            # sqlite_ledger installs a SQLAlchemy ``begin`` listener that emits
            # BEGIN IMMEDIATE itself.  SQLAlchemy invokes that listener before
            # forwarding our explicit statement, so the second BEGIN reports
            # "within a transaction" even though the required lock is held.
            if "within a transaction" not in str(exc).lower() or not _in_transaction(conn):
                raise

    added: set[str] = set()
    try:
        existing = {row[1] for row in _driver_execute(conn, f"PRAGMA table_info({table})")}
        for col, decl in columns.items():
            if col in existing:
                continue
            added_here = False
            try:
                _driver_execute(conn, f"ALTER TABLE {table} ADD COLUMN {col} {decl}")
                added_here = True
            except Exception as exc:  # noqa: BLE001 - normalize SQLite driver wrappers
                if not _is_duplicate_column(exc):
                    raise
                # A legacy caller may have altered outside this helper. Re-read
                # before deciding that a duplicate is a real schema conflict.
                current = {row[1] for row in _driver_execute(conn, f"PRAGMA table_info({table})")}
                if col not in current:
                    raise
            existing.add(col)
            if added_here:
                added.add(col)
    except Exception:
        if owns_transaction:
            conn.rollback()
        raise
    return added
