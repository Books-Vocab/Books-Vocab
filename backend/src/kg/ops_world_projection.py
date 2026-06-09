"""Shared world-state projection for ops read/write surfaces.

把 per-user scenario 真相投影成穩定、可 diff 的 shape：
- users.json 中該 uid 的 identity/config
- notebooks.db / cards.db
- graph_*.json（直接讀磁碟，繞過 GraphStore 快取）
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from .ops_edit_shared import user_dir_for, users_file
from .ops_shared import data_dir
from .user_store import load_users_from

SCHEMA = "kg.ops_world_state.v1"


def _passthrough_normalize(users: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    return users, False


def _load_record(data_root: Path, uid: str) -> dict[str, Any]:
    uf = users_file(data_root)
    users = load_users_from(uf, _passthrough_normalize) if uf.exists() else {}
    record = users.get(uid)
    return record if isinstance(record, dict) else {}


def _sqlite_rows(db_path: Path, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    if not db_path.exists():
        return []
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        return [dict(row) for row in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def _load_notebooks(user_dir: Path) -> list[dict[str, Any]]:
    rows = _sqlite_rows(
        user_dir / "notebooks.db",
        "SELECT id, name, color, sort_order, is_default, cover_pattern "
        "FROM notebook WHERE is_deleted = 0 ORDER BY sort_order, created_at, id",
    )
    return rows


def _load_cards(user_dir: Path) -> list[dict[str, Any]]:
    db_path = user_dir / "cards.db"
    if not db_path.exists():
        return []
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        cols = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(card)").fetchall()
            if isinstance(row["name"], str)
        }
        wanted = [
            "id",
            "content",
            "meaning",
            "notebook_id",
            "mode",
            "review_count",
            "review_streak",
            "lapse_count",
            "review_interval_hours",
            "next_review_at",
            "last_reviewed_at",
            "source",
        ]
        selected = [col for col in wanted if col in cols]
        if not selected:
            return []
        order_col = "notebook_id" if "notebook_id" in cols else "content" if "content" in cols else "id"
        deleted_predicate = "COALESCE(is_deleted, 0) = 0" if "is_deleted" in cols else "1 = 1"
        sql = (
            f"SELECT {', '.join(selected)} FROM card "
            f"WHERE {deleted_predicate} ORDER BY {order_col}, id"
        )
        rows = [dict(row) for row in conn.execute(sql).fetchall()]
    finally:
        conn.close()
    for row in rows:
        for col in wanted:
            row.setdefault(col, None)
    notebook_names = {nb["id"]: nb.get("name") for nb in _load_notebooks(user_dir) if isinstance(nb, dict)}
    for row in rows:
        notebook_id = row.get("notebook_id")
        row["notebook_name"] = notebook_names.get(notebook_id) if isinstance(notebook_id, str) else None
    return rows


def _load_graphs(user_dir: Path) -> list[dict[str, Any]]:
    cards_by_id = {
        str(card["id"]): card
        for card in _load_cards(user_dir)
        if isinstance(card, dict) and card.get("id") is not None
    }
    notebook_names = {nb["id"]: nb.get("name") for nb in _load_notebooks(user_dir) if isinstance(nb, dict)}
    graphs: list[dict[str, Any]] = []
    for path in sorted(user_dir.glob("graph_*.json")):
        notebook_id = path.stem.removeprefix("graph_")
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            links: list[dict[str, Any]] = []
        else:
            links = raw if isinstance(raw, list) else list(raw.values()) if isinstance(raw, dict) else []
        active_links = [
            {
                "id": link.get("id"),
                "from_id": link.get("from_id"),
                "to_id": link.get("to_id"),
                "from_content": cards_by_id.get(str(link.get("from_id")), {}).get("content"),
                "to_content": cards_by_id.get(str(link.get("to_id")), {}).get("content"),
                "kind": link.get("kind"),
                "confidence": link.get("confidence"),
                "reason": link.get("reason"),
                "status": link.get("status", "active"),
            }
            for link in links
            if isinstance(link, dict)
        ]
        graphs.append({
            "notebook_id": notebook_id,
            "notebook_name": notebook_names.get(notebook_id),
            "path": str(path),
            "links": active_links,
        })
    return graphs


def project_user_world(uid: str, *, data_root: Path | None = None) -> dict[str, Any]:
    root = data_root or data_dir()
    user_dir = user_dir_for(root, uid)
    record = _load_record(root, uid)
    return {
        "schema": SCHEMA,
        "user_id": uid,
        "dataDir": str(root),
        "userDir": str(user_dir),
        "record": record,
        "config": record.get("config", {}) if isinstance(record.get("config"), dict) else {},
        "notebooks": _load_notebooks(user_dir),
        "cards": _load_cards(user_dir),
        "graphs": _load_graphs(user_dir),
    }
