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


def ensure_columns(conn: sqlite3.Connection, table: str, columns: dict[str, str]) -> None:
    """Idempotently ``ALTER TABLE ... ADD COLUMN`` any column in ``columns`` not
    already present on ``table``. ``columns`` maps name → SQL declaration
    (e.g. ``{"provider": "TEXT"}``).

    Replaces the hand-rolled ``{r[1] for r in PRAGMA table_info(...)}`` diff each
    singleton repeats for schema migration. ``table`` / column identifiers are
    module-internal literals (never user input), as before.
    """
    existing = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
    for col, decl in columns.items():
        if col not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")
