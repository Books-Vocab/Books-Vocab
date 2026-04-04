"""Pipeline execution log (SQLite singleton) — records pipeline runs and their steps."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path

DATA_DIR = Path(os.getenv("KG_DATA_DIR", str(Path(__file__).resolve().parent.parent.parent / "data")))
DB_PATH = DATA_DIR / "pipeline_runs.db"

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
        conn.execute("UPDATE pipeline_runs SET steps = ? WHERE run_id = ?", (json.dumps(steps), run_id))
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
        conn.execute("UPDATE pipeline_runs SET steps = ? WHERE run_id = ?", (json.dumps(steps), run_id))
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
            if step.get("started_at") and step.get("ended_at"):
                try:
                    s = datetime.fromisoformat(step["started_at"])
                    e = datetime.fromisoformat(step["ended_at"])
                    step["duration_s"] = round((e - s).total_seconds(), 2)
                except (ValueError, TypeError):
                    step["duration_s"] = None
            else:
                step["duration_s"] = None
        duration_s = None
        if started and ended:
            try:
                duration_s = round((datetime.fromisoformat(ended) - datetime.fromisoformat(started)).total_seconds(), 2)
            except (ValueError, TypeError):
                pass
        result.append({
            "run_id": run_id, "user_id": uid, "notebook_id": nb,
            "trigger": trigger, "started_at": started, "ended_at": ended,
            "status": status, "duration_s": duration_s, "steps": steps,
        })
    return result
