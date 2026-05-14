"""Per-user podcast playback progress store (SQLite singleton).

Companion to ``podcast_log.db`` and ``pipeline_runs.db`` — shares the same
threading.Lock + ``check_same_thread=False`` pattern with WAL + busy_timeout
via :func:`init_sqlite_pragmas`.

Schema:

* Composite primary key ``(user_id, series_id, ep_num)`` so each user has at
  most one row per episode. Last-write-wins by ``updated_at`` is enforced in
  :func:`upsert` (not by a trigger) so a stale write returns the existing
  newer row to the caller without clobbering it.
* ``updated_at`` is stored as the client-supplied ISO8601 string verbatim —
  iOS is the source of truth for monotonicity within a single device, and
  cross-device drift is resolved on wall-clock comparison just like
  ``PodcastProgress.updatedAt`` on the client.

The DB lives at ``$KG_DATA_DIR/podcast_progress.db``. First-time access
auto-creates the table; no manual migration needed.
"""

from __future__ import annotations

import os
import sqlite3
import threading
from pathlib import Path

_DEFAULT_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None
_init_data_dir: Path | None = None
_override_data_dir: Path | None = None


def set_data_dir(path: Path | None) -> None:
    """Override the data_dir used by the singleton.

    Called from ``api.create_app`` so that the progress DB lives next to the
    same per-instance ``data_dir`` as the rest of the singletons honored via
    ``app.state.kg_settings``. Passing ``None`` reverts to the
    env-var/default resolution path (used by tests after swap-back).
    """
    global _override_data_dir, _conn, _init_data_dir
    with _lock:
        _override_data_dir = path
        if _conn is not None:
            try:
                _conn.close()
            except Exception:
                pass
        _conn = None
        _init_data_dir = None


def _resolve_data_dir() -> Path:
    if _override_data_dir is not None:
        return _override_data_dir
    return Path(os.getenv("KG_DATA_DIR", str(_DEFAULT_DATA_DIR)))


def _get_conn() -> sqlite3.Connection:
    """Return the singleton connection, opening it on first use.

    Re-opens automatically when the resolved data_dir changes between calls
    so the test fixture (which swaps ``data_dir`` per test) sees an isolated DB.
    """
    global _conn, _init_data_dir
    current_dir = _resolve_data_dir()
    if _conn is not None and _init_data_dir == current_dir:
        return _conn
    if _conn is not None:
        try:
            _conn.close()
        except Exception:
            pass
        _conn = None
    db_path = current_dir / "podcast_progress.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    from .sqlite_utils import init_sqlite_pragmas
    init_sqlite_pragmas(conn)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS podcast_progress (
            user_id TEXT NOT NULL,
            series_id TEXT NOT NULL,
            ep_num INTEGER NOT NULL,
            position_sec REAL NOT NULL,
            duration_sec REAL NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (user_id, series_id, ep_num)
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_pp_user ON podcast_progress(user_id)"
    )
    conn.commit()
    _conn = conn
    _init_data_dir = current_dir
    return _conn


def _reset() -> None:
    """Close + nullify connection + clear override (for tests)."""
    global _conn, _init_data_dir, _override_data_dir
    with _lock:
        if _conn is not None:
            try:
                _conn.close()
            except Exception:
                pass
            _conn = None
            _init_data_dir = None
        _override_data_dir = None


def upsert(
    *,
    user_id: str,
    series_id: str,
    ep_num: int,
    position_sec: float,
    duration_sec: float,
    updated_at: str,
) -> dict:
    """Insert or update the row for ``(user_id, series_id, ep_num)``.

    Last-write-wins: if an existing row has an ``updated_at`` >= the incoming
    one, the existing row is returned unchanged. Otherwise the row is
    overwritten and the new payload is returned.

    The comparison is lexicographic on the ISO8601 string, which is correct
    only when both values are in the same canonical form (UTC, fixed
    width). The router normalises client input to UTC ISO8601 before
    calling this function so the invariant holds.
    """
    with _lock:
        conn = _get_conn()
        row = conn.execute(
            "SELECT position_sec, duration_sec, updated_at FROM podcast_progress "
            "WHERE user_id = ? AND series_id = ? AND ep_num = ?",
            (user_id, series_id, ep_num),
        ).fetchone()
        if row is not None and row[2] >= updated_at:
            # Existing row is newer (or same instant) — ignore stale write.
            return {
                "series_id": series_id,
                "ep_num": ep_num,
                "position_sec": row[0],
                "duration_sec": row[1],
                "updated_at": row[2],
            }
        conn.execute(
            """
            INSERT INTO podcast_progress
                (user_id, series_id, ep_num, position_sec, duration_sec, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, series_id, ep_num) DO UPDATE SET
                position_sec = excluded.position_sec,
                duration_sec = excluded.duration_sec,
                updated_at = excluded.updated_at
            """,
            (user_id, series_id, ep_num, position_sec, duration_sec, updated_at),
        )
        conn.commit()
    return {
        "series_id": series_id,
        "ep_num": ep_num,
        "position_sec": position_sec,
        "duration_sec": duration_sec,
        "updated_at": updated_at,
    }


def get_single(*, user_id: str, series_id: str, ep_num: int) -> dict | None:
    with _lock:
        conn = _get_conn()
        row = conn.execute(
            "SELECT position_sec, duration_sec, updated_at FROM podcast_progress "
            "WHERE user_id = ? AND series_id = ? AND ep_num = ?",
            (user_id, series_id, ep_num),
        ).fetchone()
    if row is None:
        return None
    return {
        "series_id": series_id,
        "ep_num": ep_num,
        "position_sec": row[0],
        "duration_sec": row[1],
        "updated_at": row[2],
    }


def list_for_user(*, user_id: str) -> list[dict]:
    with _lock:
        conn = _get_conn()
        rows = conn.execute(
            "SELECT series_id, ep_num, position_sec, duration_sec, updated_at "
            "FROM podcast_progress WHERE user_id = ? ORDER BY updated_at DESC",
            (user_id,),
        ).fetchall()
    return [
        {
            "series_id": s, "ep_num": e,
            "position_sec": p, "duration_sec": d, "updated_at": u,
        }
        for s, e, p, d, u in rows
    ]
