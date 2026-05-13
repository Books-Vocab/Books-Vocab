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
    global _conn
    if _conn is None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        from .sqlite_utils import init_sqlite_pragmas
        init_sqlite_pragmas(_conn)
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
        _conn.execute("CREATE INDEX IF NOT EXISTS idx_jl_user_source ON judge_log(user_id, source)")
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


def get_acceptance_stats(*, user_id: str | None = None) -> dict:
    """Return judge acceptance stats. Optionally filtered by user_id."""
    if not DB_PATH.exists():
        return {"total": 0, "accepted": 0, "rejected": 0, "rate": None}
    with _lock:
        conn = _get_conn()
        if user_id is not None:
            row = conn.execute(
                "SELECT COUNT(*) AS total, SUM(accepted) AS accepted FROM judge_log WHERE source = 'auto' AND user_id = ?",
                (user_id,),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT COUNT(*) AS total, SUM(accepted) AS accepted FROM judge_log WHERE source = 'auto'"
            ).fetchone()
    total = row[0] or 0
    accepted = row[1] or 0
    rejected = total - accepted
    return {
        "total": total,
        "accepted": accepted,
        "rejected": rejected,
        "rate": round(accepted / total, 4) if total > 0 else None,
    }
