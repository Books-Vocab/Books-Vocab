"""Admin mutation audit log (SQLite singleton).

Records every admin grant / revoke / quota mutation so that operator actions
on user accounts are auditable after the fact. Read back via the
``/api/admin/audit`` endpoint.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None


def _db_path() -> Path:
    data_dir = Path(
        os.getenv(
            "KG_DATA_DIR",
            str(Path(__file__).resolve().parent.parent.parent / "data"),
        )
    )
    return data_dir / "admin_audit.db"


def _get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        db = _db_path()
        db.parent.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(str(db), check_same_thread=False)
        from .sqlite_utils import init_sqlite_pragmas

        init_sqlite_pragmas(_conn)
        _conn.execute(
            """
            CREATE TABLE IF NOT EXISTS admin_audit_log (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                admin_uid    TEXT NOT NULL,
                action       TEXT NOT NULL,
                target_uid   TEXT,
                payload_json TEXT,
                created_at   TEXT NOT NULL
            )
            """
        )
        _conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_audit_created ON admin_audit_log(created_at)"
        )
        _conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_audit_target ON admin_audit_log(target_uid, created_at)"
        )
        _conn.commit()
    return _conn


def _reset() -> None:
    """Test helper: close + drop the singleton so a new ``KG_DATA_DIR`` is honored."""
    global _conn
    with _lock:
        if _conn is not None:
            _conn.close()
            _conn = None


def record_audit(
    *,
    admin_uid: str | None,
    action: str,
    target_uid: str | None = None,
    payload: dict[str, Any] | None = None,
) -> None:
    """Append one audit row. Never raises — audit must not break the mutation."""
    try:
        actor = (admin_uid or "admin").strip() or "admin"
        act = (action or "").strip()
        if not act:
            return
        target = (target_uid or None)
        if target is not None:
            target = target.strip() or None
        payload_str = None
        if payload is not None:
            try:
                payload_str = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
            except (TypeError, ValueError):
                payload_str = json.dumps({"_unserializable": repr(payload)[:500]})
        now = datetime.now(UTC).isoformat()
        with _lock:
            conn = _get_conn()
            conn.execute(
                "INSERT INTO admin_audit_log (admin_uid, action, target_uid, payload_json, created_at) VALUES (?,?,?,?,?)",
                (actor, act, target, payload_str, now),
            )
            conn.commit()
    except sqlite3.Error:
        # Audit failure must never break the underlying admin mutation.
        return


def list_audit(*, since: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    """Return audit rows newest-first.

    ``since`` is an ISO-8601 timestamp (inclusive lower bound). ``limit``
    is clamped to [1, 1000]. ``payload`` is decoded back to a dict when
    valid JSON, else passed through as a raw string.
    """
    try:
        lim = max(1, min(int(limit or 100), 1000))
    except (TypeError, ValueError):
        lim = 100
    with _lock:
        conn = _get_conn()
        if since:
            rows = conn.execute(
                "SELECT id, admin_uid, action, target_uid, payload_json, created_at "
                "FROM admin_audit_log WHERE created_at >= ? ORDER BY id DESC LIMIT ?",
                (since, lim),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, admin_uid, action, target_uid, payload_json, created_at "
                "FROM admin_audit_log ORDER BY id DESC LIMIT ?",
                (lim,),
            ).fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        payload_raw = row[4]
        payload: Any = None
        if payload_raw:
            try:
                payload = json.loads(payload_raw)
            except (TypeError, ValueError):
                payload = payload_raw
        out.append(
            {
                "id": row[0],
                "admin_uid": row[1],
                "action": row[2],
                "target_uid": row[3],
                "payload": payload,
                "created_at": row[5],
            }
        )
    return out
