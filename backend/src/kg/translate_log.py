"""Translate/explain LLM call log + cross-user cache (SQLite singleton)."""
from __future__ import annotations

import os
import sqlite3
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

CACHE_TTL_DAYS = 30

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None

def _db_path() -> Path:
    data_dir = Path(os.getenv("KG_DATA_DIR", str(Path(__file__).resolve().parent.parent.parent / "data")))
    return data_dir / "translate_log.db"

def _get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        db = _db_path()
        db.parent.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(str(db), check_same_thread=False)
        from .sqlite_utils import init_sqlite_pragmas
        init_sqlite_pragmas(_conn)
        _conn.execute("""
            CREATE TABLE IF NOT EXISTS translate_log (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     TEXT NOT NULL,
                operation   TEXT NOT NULL,
                word        TEXT NOT NULL,
                context     TEXT,
                context_hash TEXT NOT NULL,
                source_lang TEXT NOT NULL,
                target_lang TEXT NOT NULL,
                response_raw TEXT NOT NULL,
                latency_ms  INTEGER,
                created_at  TEXT NOT NULL
            )
        """)
        _conn.execute("CREATE INDEX IF NOT EXISTS idx_tl_cache ON translate_log(word, context_hash, source_lang, target_lang, operation)")
        _conn.execute("CREATE INDEX IF NOT EXISTS idx_tl_user ON translate_log(user_id, created_at)")
        _conn.commit()
    return _conn

def _reset() -> None:
    global _conn
    with _lock:
        if _conn is not None:
            _conn.close()
            _conn = None

def lookup(word: str, context_hash: str, source_lang: str, target_lang: str, operation: str) -> str | None:
    cutoff = (datetime.now(UTC) - timedelta(days=CACHE_TTL_DAYS)).isoformat()
    with _lock:
        conn = _get_conn()
        row = conn.execute(
            "SELECT response_raw FROM translate_log WHERE word=? AND context_hash=? AND source_lang=? AND target_lang=? AND operation=? AND created_at>? ORDER BY id DESC LIMIT 1",
            (word, context_hash, source_lang, target_lang, operation, cutoff),
        ).fetchone()
    return row[0] if row else None

def record(*, user_id, operation, word, context, context_hash, source_lang, target_lang, response_raw, latency_ms) -> None:
    if not user_id:
        return
    now = datetime.now(UTC).isoformat()
    with _lock:
        conn = _get_conn()
        conn.execute(
            "INSERT INTO translate_log (user_id, operation, word, context, context_hash, source_lang, target_lang, response_raw, latency_ms, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (user_id, operation, word, context, context_hash, source_lang, target_lang, response_raw, int(latency_ms or 0), now),
        )
        conn.commit()

def get_log(user_id: str, *, limit: int = 200) -> list[dict]:
    with _lock:
        conn = _get_conn()
        rows = conn.execute(
            "SELECT * FROM translate_log WHERE user_id = ? ORDER BY id DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()
    cols = ["id","user_id","operation","word","context","context_hash","source_lang","target_lang","response_raw","latency_ms","created_at"]
    return [dict(zip(cols, row)) for row in rows]
