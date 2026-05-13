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

# 30s is the existing per-module value; keeping it consistent so behaviour
# does not regress when a module switches from inline PRAGMAs to this helper.
DEFAULT_BUSY_TIMEOUT_MS = 30000


def init_sqlite_pragmas(conn: sqlite3.Connection, *, busy_timeout_ms: int = DEFAULT_BUSY_TIMEOUT_MS) -> None:
    """Configure WAL + busy_timeout + synchronous=NORMAL on `conn`.

    Idempotent — calling on an already-WAL connection is a no-op. Must be
    invoked before any write or DDL so the journal mode change persists.
    """
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute(f"PRAGMA busy_timeout={int(busy_timeout_ms)};")
    conn.execute("PRAGMA synchronous=NORMAL;")
