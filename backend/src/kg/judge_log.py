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


def update_to_rejected(
    from_id: str,
    to_id: str,
    *,
    reason: str,
    source: str = "auto",
) -> bool:
    """Flip the most recent ``(from_id, to_id, source, accepted=1)`` row into
    ``accepted=0`` with ``reject_reason=reason``.

    Used when the LLM accepted a candidate but a downstream constraint
    (e.g. degree cap) rejected it. Mutating the existing row — rather than
    appending a second one — keeps ``get_acceptance_stats`` from double-counting
    the candidate against the model's acceptance rate.

    Returns ``True`` iff a row was updated.
    """
    with _lock:
        conn = _get_conn()
        cur = conn.execute(
            "UPDATE judge_log SET accepted=0, reject_reason=? "
            "WHERE id = ("
            "  SELECT id FROM judge_log "
            "  WHERE from_id=? AND to_id=? AND source=? AND accepted=1 "
            "  ORDER BY id DESC LIMIT 1"
            ")",
            (reason, from_id, to_id, source),
        )
        conn.commit()
        return cur.rowcount > 0


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
    """Return judge acceptance stats. Optionally filtered by user_id.

    Excludes rows with ``reject_reason='degree_cap'`` — those are pipeline
    cap evictions, not model decisions, so they would otherwise depress
    the apparent model acceptance rate.
    """
    if not DB_PATH.exists():
        return {"total": 0, "accepted": 0, "rejected": 0, "rate": None}
    base_where = (
        "source = 'auto' "
        "AND (reject_reason IS NULL OR reject_reason != 'degree_cap')"
    )
    with _lock:
        conn = _get_conn()
        if user_id is not None:
            row = conn.execute(
                f"SELECT COUNT(*) AS total, SUM(accepted) AS accepted "
                f"FROM judge_log WHERE {base_where} AND user_id = ?",
                (user_id,),
            ).fetchone()
        else:
            row = conn.execute(
                f"SELECT COUNT(*) AS total, SUM(accepted) AS accepted "
                f"FROM judge_log WHERE {base_where}"
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
