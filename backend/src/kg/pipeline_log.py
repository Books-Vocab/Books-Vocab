"""Pipeline execution log (SQLite singleton) — records pipeline runs and their steps."""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import UTC, datetime

from .ops_shared import data_dir

DATA_DIR = data_dir()
DB_PATH = DATA_DIR / "pipeline_runs.db"

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None


def _get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        from .sqlite_utils import open_singleton
        _conn = open_singleton(DB_PATH)
        _conn.execute("""
            CREATE TABLE IF NOT EXISTS pipeline_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT UNIQUE NOT NULL,
                user_id TEXT NOT NULL,
                notebook_id TEXT NOT NULL,
                trigger TEXT NOT NULL,
                started_at TEXT NOT NULL,
                ended_at TEXT,
                status TEXT NOT NULL DEFAULT 'running',
                steps TEXT NOT NULL DEFAULT '[]'
            )
        """)
        _conn.execute("CREATE INDEX IF NOT EXISTS idx_pr_user ON pipeline_runs(user_id)")
        _conn.execute("CREATE INDEX IF NOT EXISTS idx_pr_started ON pipeline_runs(started_at)")
        # Mark orphaned runs from previous crashes as interrupted
        _conn.execute(
            "UPDATE pipeline_runs SET status='interrupted', ended_at=? WHERE status='running'",
            (datetime.now(UTC).isoformat(),),
        )
        _conn.commit()
    return _conn


def _reset() -> None:
    """Close & nullify connection (for tests)."""
    global _conn
    with _lock:
        if _conn is not None:
            _conn.close()
            _conn = None


def start_run(run_id: str, user_id: str, notebook_id: str, trigger: str) -> None:
    """Insert a new pipeline run with status='running', steps='[]'."""
    now = datetime.now(UTC).isoformat()
    with _lock:
        conn = _get_conn()
        conn.execute(
            "INSERT INTO pipeline_runs (run_id, user_id, notebook_id, trigger, started_at, steps) "
            "VALUES (?, ?, ?, ?, ?, '[]')",
            (run_id, user_id, notebook_id, trigger, now),
        )
        conn.commit()


def start_step(run_id: str, name: str) -> None:
    """Append a step entry with status='running', started_at=now to the run's steps JSON."""
    now = datetime.now(UTC).isoformat()
    with _lock:
        conn = _get_conn()
        row = conn.execute("SELECT steps FROM pipeline_runs WHERE run_id = ?", (run_id,)).fetchone()
        if not row:
            return
        steps = json.loads(row[0])
        steps.append({"name": name, "status": "running", "started_at": now, "ended_at": None, "items": 0, "error": None})
        conn.execute("UPDATE pipeline_runs SET steps = ? WHERE run_id = ?", (json.dumps(steps, ensure_ascii=False), run_id))
        conn.commit()


def end_step(run_id: str, name: str, *, status: str = "ok", items: int = 0, error: str | None = None) -> None:
    """Update the matching step's status, ended_at, items, error in the steps JSON."""
    now = datetime.now(UTC).isoformat()
    with _lock:
        conn = _get_conn()
        row = conn.execute("SELECT steps FROM pipeline_runs WHERE run_id = ?", (run_id,)).fetchone()
        if not row:
            return
        steps = json.loads(row[0])
        for step in reversed(steps):
            if step["name"] == name:
                step["status"] = status
                step["ended_at"] = now
                step["items"] = items
                step["error"] = error
                break
        conn.execute("UPDATE pipeline_runs SET steps = ? WHERE run_id = ?", (json.dumps(steps, ensure_ascii=False), run_id))
        conn.commit()


def end_run(run_id: str, status: str) -> None:
    """Set ended_at and status on the run."""
    now = datetime.now(UTC).isoformat()
    with _lock:
        conn = _get_conn()
        conn.execute(
            "UPDATE pipeline_runs SET ended_at = ?, status = ? WHERE run_id = ?",
            (now, status, run_id),
        )
        conn.commit()


def _duration_s(start: str | None, end: str | None) -> float | None:
    """Seconds between two ISO timestamps, or None if either is missing or unparseable."""
    if not (start and end):
        return None
    try:
        return round((datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds(), 2)
    except (ValueError, TypeError):
        return None


def get_runs(user_id: str, *, limit: int = 20) -> list[dict]:
    """Return recent runs for a user, newest first. Parses steps JSON."""
    with _lock:
        conn = _get_conn()
        rows = conn.execute(
            "SELECT run_id, user_id, notebook_id, trigger, started_at, ended_at, status, steps "
            "FROM pipeline_runs WHERE user_id = ? ORDER BY started_at DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()
    result = []
    for run_id, uid, nb, trigger, started, ended, status, steps_json in rows:
        steps = json.loads(steps_json)
        for step in steps:
            step["duration_s"] = _duration_s(step.get("started_at"), step.get("ended_at"))
        duration_s = _duration_s(started, ended)
        result.append({
            "run_id": run_id, "user_id": uid, "notebook_id": nb,
            "trigger": trigger, "started_at": started, "ended_at": ended,
            "status": status, "duration_s": duration_s, "steps": steps,
        })
    return result
