"""Admin mutation audit log (SQLite singleton).

Records every admin grant / revoke / quota mutation so that operator actions
on user accounts are auditable after the fact. Read back via the
``/api/admin/audit`` endpoint.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .ops_shared import data_dir

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None
logger = logging.getLogger(__name__)


def _db_path() -> Path:
    return data_dir() / "admin_audit.db"


def _get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        from .sqlite_utils import open_singleton

        _conn = open_singleton(_db_path())
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
                logger.warning(
                    "Failed to JSON serialize audit payload for action=%s, using fallback repr: %r",
                    action,
                    payload,
                )
                payload_str = json.dumps({"_unserializable": repr(payload)[:500]}, ensure_ascii=False)
        now = datetime.now(UTC).isoformat()
        with _lock:
            conn = _get_conn()
            conn.execute(
                "INSERT INTO admin_audit_log (admin_uid, action, target_uid, payload_json, created_at) VALUES (?,?,?,?,?)",
                (actor, act, target, payload_str, now),
            )
            conn.commit()
    except sqlite3.Error as exc:
        # Audit failure must never break the underlying admin mutation.
        logger.warning("Failed to insert admin audit row for action %s: %s", action, exc)
        return


def list_audit(
    *, since: str | None = None, limit: int = 100, action: str | None = None
) -> list[dict[str, Any]]:
    """Return audit rows newest-first.

    ``since`` is an ISO-8601 timestamp (inclusive lower bound). ``limit``
    is clamped to [1, 1000]. ``action`` optionally restricts rows to an exact
    ``action`` match (e.g. ``grant_pro`` / ``revoke_pro``); a blank/whitespace
    value is treated as no filter. ``payload`` is decoded back to a dict when
    valid JSON, else passed through as a raw string.
    """
    try:
        lim = max(1, min(int(limit or 100), 1000))
    except (TypeError, ValueError):
        logger.warning("Invalid audit limit %r; using fallback 100", limit)
        lim = 100
    act = (action or "").strip() or None
    clauses: list[str] = []
    params: list[Any] = []
    if since:
        clauses.append("created_at >= ?")
        params.append(since)
    if act is not None:
        clauses.append("action = ?")
        params.append(act)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    params.append(lim)
    with _lock:
        conn = _get_conn()
        rows = conn.execute(
            "SELECT id, admin_uid, action, target_uid, payload_json, created_at "
            f"FROM admin_audit_log{where} ORDER BY id DESC LIMIT ?",
            tuple(params),
        ).fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        payload_raw = row[4]
        payload: Any = None
        if payload_raw:
            try:
                payload = json.loads(payload_raw)
            except (TypeError, ValueError):
                logger.warning("Failed to decode audit payload JSON for row id=%s, passing raw string", row[0])
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
