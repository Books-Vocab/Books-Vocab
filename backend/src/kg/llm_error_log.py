"""Log real LLM infrastructure failures (429/5xx/timeout) — the missing signal.

Unlike token_tracker (which only records successful calls with usage data),
this singleton captures exceptions that abort before a response is returned.
Every row represents a terminal LLM failure that the SDK's default retries
could not recover from. Best-effort recording: the tracked_llm wrapper
swallows any recording error so an LLM outage can never be masked by a
logging fault.
"""
from __future__ import annotations

import sqlite3
import threading
from datetime import UTC, datetime

from .ops_shared import data_dir

DATA_DIR = data_dir()
DB_PATH = DATA_DIR / "llm_errors.db"

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None


def _get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        from .sqlite_utils import ensure_columns, open_singleton
        _conn = open_singleton(DB_PATH)
        _conn.execute("""
            CREATE TABLE IF NOT EXISTS llm_errors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                call_type TEXT NOT NULL,
                provider TEXT,
                model TEXT,
                error_class TEXT NOT NULL,
                status_code INTEGER,
                message TEXT,
                created_at TEXT NOT NULL
            )
        """)
        # Ensure columns for future migrations (mirrors token_tracker pattern).
        ensure_columns(_conn, "llm_errors", {
            "provider": "TEXT",
            "model": "TEXT",
            "status_code": "INTEGER",
            "message": "TEXT",
        })
        _conn.execute("CREATE INDEX IF NOT EXISTS idx_le_user ON llm_errors(user_id)")
        _conn.execute("CREATE INDEX IF NOT EXISTS idx_le_user_created ON llm_errors(user_id, created_at)")
        # Bare created_at index for the retention pruner.
        _conn.execute("CREATE INDEX IF NOT EXISTS idx_le_created ON llm_errors(created_at)")
        _conn.commit()
    return _conn


def _reset() -> None:
    """Close & nullify connection (for tests)."""
    global _conn
    with _lock:
        if _conn is not None:
            _conn.close()
            _conn = None


def record(
    *,
    user_id: str,
    call_type: str,
    provider: str | None = None,
    model: str | None = None,
    error_class: str,
    status_code: int | None = None,
    message: str | None = None,
) -> None:
    """Record a terminal LLM failure.

    ``error_class`` is ``type(exc).__name__`` (e.g. ``"RateLimitError"``).
    ``status_code`` is the HTTP status when available (429, 500, etc.);
    ``None`` for timeouts and connection errors.
    ``message`` is ``str(exc)`` truncated to 500 chars.
    """
    if not user_id:
        return
    now = datetime.now(UTC).isoformat()
    with _lock:
        conn = _get_conn()
        conn.execute(
            "INSERT INTO llm_errors "
            "(user_id, call_type, provider, model, error_class, status_code, message, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (user_id, call_type, provider, model, error_class, status_code,
             (message or "")[:500], now),
        )
        conn.commit()
