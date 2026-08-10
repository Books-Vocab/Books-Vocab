"""Per-user LLM token usage tracking (SQLite singleton)."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

from .ops_shared import data_dir
from .sqlite_lifecycle import SQLiteLifecycle

DATA_DIR = data_dir()
DB_PATH = DATA_DIR / "token_usage.db"

_lifecycle = SQLiteLifecycle()
_lock = _lifecycle.lock
_conn: sqlite3.Connection | None = None
_INITIAL_DB_PATH = DB_PATH


def _get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None and _lifecycle.connection is not None:
        _lifecycle.reset()
    db_path = DB_PATH if DB_PATH != _INITIAL_DB_PATH else data_dir() / "token_usage.db"
    _conn = _lifecycle.get_connection(db_path, _initialize_schema)
    return _conn


def _initialize_schema(conn: sqlite3.Connection) -> None:
        from .sqlite_utils import ensure_columns
        conn.execute("""
            CREATE TABLE IF NOT EXISTS token_usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                call_type TEXT NOT NULL,
                input_tokens INTEGER NOT NULL DEFAULT 0,
                output_tokens INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                provider TEXT,
                model TEXT
            )
        """)
        # Migrate pre-existing DBs: provider/model were added so each row
        # carries the truth used to price it. Older rows stay NULL and fall
        # back to the currently-routed provider in token_cost_usd().
        ensure_columns(conn, "token_usage", {"provider": "TEXT", "model": "TEXT"})
        conn.execute("CREATE INDEX IF NOT EXISTS idx_user ON token_usage(user_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_user_created ON token_usage(user_id, created_at)")
        # Bare created_at index for the retention pruner's
        # `DELETE ... WHERE created_at < ?`; the two composite indexes lead
        # with user_id so SQLite can't use them for a bare-created_at predicate.
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tu_created ON token_usage(created_at)")


def reset() -> None:
    global _conn
    _lifecycle.reset()
    _conn = None


def record(
    user_id: str,
    call_type: str,
    input_tokens: int,
    output_tokens: int,
    *,
    provider: str | None = None,
    model: str | None = None,
) -> None:
    """Record token usage for a user.

    ``provider`` / ``model`` pin the LLM that produced this row so cost can
    later be priced from the row itself, not from whatever is routed now.
    Both are optional; omitting them writes NULL (legacy / unknown callers).
    """
    if not user_id:
        return
    now = datetime.now(UTC).isoformat()
    with _lock:
        conn = _get_conn()
        conn.execute(
            "INSERT INTO token_usage "
            "(user_id, call_type, input_tokens, output_tokens, created_at, provider, model) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (user_id, call_type, int(input_tokens or 0), int(output_tokens or 0),
             now, provider, model),
        )
        conn.commit()


def get_all_stats() -> dict[str, dict]:
    """Return aggregated token usage per user per call_type."""
    with _lock:
        conn = _get_conn()
        rows = conn.execute("""
            SELECT user_id, call_type,
                   SUM(input_tokens) as total_input,
                   SUM(output_tokens) as total_output,
                   COUNT(*) as calls
            FROM token_usage
            GROUP BY user_id, call_type
        """).fetchall()
    stats: dict[str, dict] = {}
    for user_id, call_type, total_input, total_output, calls in rows:
        if user_id not in stats:
            stats[user_id] = {}
        stats[user_id][call_type] = {
            "input_tokens": total_input or 0,
            "output_tokens": total_output or 0,
            "calls": calls,
        }
    return stats
