"""Per-user LLM token usage tracking (SQLite singleton)."""

from __future__ import annotations

import os
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path

DATA_DIR = Path(os.getenv("KG_DATA_DIR", str(Path(__file__).resolve().parent.parent.parent / "data")))
DB_PATH = DATA_DIR / "token_usage.db"

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None


def _get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        _conn.execute("PRAGMA journal_mode=WAL;")
        _conn.execute("PRAGMA synchronous=NORMAL;")
        _conn.execute("PRAGMA busy_timeout=30000;")
        _conn.execute("""
            CREATE TABLE IF NOT EXISTS token_usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                call_type TEXT NOT NULL,
                input_tokens INTEGER NOT NULL DEFAULT 0,
                output_tokens INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            )
        """)
        _conn.execute("CREATE INDEX IF NOT EXISTS idx_user ON token_usage(user_id)")
        _conn.execute("CREATE INDEX IF NOT EXISTS idx_user_created ON token_usage(user_id, created_at)")
        _conn.commit()
    return _conn


def record(user_id: str, call_type: str, input_tokens: int, output_tokens: int) -> None:
    """Record token usage for a user."""
    if not user_id:
        return
    now = datetime.now(UTC).isoformat()
    with _lock:
        conn = _get_conn()
        conn.execute(
            "INSERT INTO token_usage (user_id, call_type, input_tokens, output_tokens, created_at) VALUES (?, ?, ?, ?, ?)",
            (user_id, call_type, int(input_tokens or 0), int(output_tokens or 0), now),
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
