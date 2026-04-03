"""Judge decision log (SQLite singleton) — records ALL judge decisions."""

from __future__ import annotations

import os
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path

DATA_DIR = Path(os.getenv("KG_DATA_DIR", str(Path(__file__).resolve().parent.parent.parent / "data")))
DB_PATH = DATA_DIR / "judge_log.db"

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None


def _get_conn() -> sqlite3.Connection:
    global _conn, DB_PATH, DATA_DIR
    # Re-read env each time in case it changed (tests)
    DATA_DIR = Path(os.getenv("KG_DATA_DIR", str(Path(__file__).resolve().parent.parent.parent / "data")))
    DB_PATH = DATA_DIR / "judge_log.db"
    if _conn is None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        _conn.execute("PRAGMA journal_mode=WAL;")
        _conn.execute("PRAGMA synchronous=NORMAL;")
        _conn.execute("PRAGMA busy_timeout=30000;")
        _conn.execute("""
            CREATE TABLE IF NOT EXISTS judge_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                notebook_id TEXT NOT NULL,
                from_id TEXT NOT NULL,
                to_id TEXT NOT NULL,
                similarity REAL,
                verdict TEXT NOT NULL,
                confidence REAL NOT NULL,
                accepted INTEGER NOT NULL,
                reject_reason TEXT,
                reason TEXT,
                source TEXT NOT NULL DEFAULT 'auto',
                created_at TEXT NOT NULL
            )
        """)
        _conn.execute("CREATE INDEX IF NOT EXISTS idx_jl_user_nb ON judge_log(user_id, notebook_id)")
        _conn.execute("CREATE INDEX IF NOT EXISTS idx_jl_created ON judge_log(created_at)")
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
    notebook_id: str,
    from_id: str,
    to_id: str,
    similarity: float | None,
    verdict: str,
    confidence: float,
    accepted: bool,
    reject_reason: str | None = None,
    reason: str = "",
    source: str = "auto",
) -> None:
    """Record a judge decision."""
    if not user_id:
        return
    now = datetime.now(UTC).isoformat()
    with _lock:
        conn = _get_conn()
        conn.execute(
            """INSERT INTO judge_log
               (user_id, notebook_id, from_id, to_id, similarity,
                verdict, confidence, accepted, reject_reason, reason, source, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (user_id, notebook_id, from_id, to_id, similarity,
             verdict, float(confidence), int(accepted), reject_reason, reason, source, now),
        )
        conn.commit()


def get_log(user_id: str, *, notebook_id: str | None = None, limit: int = 1000) -> list[dict]:
    """Retrieve judge log entries for a user."""
    with _lock:
        conn = _get_conn()
        if notebook_id is not None:
            rows = conn.execute(
                "SELECT * FROM judge_log WHERE user_id = ? AND notebook_id = ? ORDER BY id DESC LIMIT ?",
                (user_id, notebook_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM judge_log WHERE user_id = ? ORDER BY id DESC LIMIT ?",
                (user_id, limit),
            ).fetchall()
    cols = ["id", "user_id", "notebook_id", "from_id", "to_id", "similarity",
            "verdict", "confidence", "accepted", "reject_reason", "reason", "source", "created_at"]
    result = []
    for row in rows:
        d = dict(zip(cols, row))
        d["accepted"] = bool(d["accepted"])
        result.append(d)
    return result
