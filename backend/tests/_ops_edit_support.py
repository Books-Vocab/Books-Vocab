# ruff: noqa: F401, I001
"""Shared fixtures and helpers for the sharded backend test family."""

"""ops_edit.py 測試 — 第三輪 dogfooding（B 安全 / C 契約 / A 完備性）修復的回歸護欄。

全程 tmp_path 沙盒（KG_DATA_DIR 注入），subprocess 跑真 CLI，斷言混用 --json
stdout 與直接讀盤（cards.db / notebooks.db / graph_*.json），確保 verify 報的綠
與磁碟真實狀態一致 —— 正是本輪獵殺 false-green 的核心手法。
"""

import json

import sqlite3

from datetime import UTC, datetime

from pathlib import Path

import pytest

from ops_helpers import run_ops_cli as _cli

from ops_helpers import run_ops_edit as _edit

def _user_dir(tmp_path: Path, uid: str) -> Path:
    return tmp_path / "users" / uid

def _card_rows(tmp_path: Path, uid: str) -> list[dict]:
    db = _user_dir(tmp_path, uid) / "cards.db"
    if not db.exists():
        return []
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id, content, meaning, notebook_id, next_review_at, "
        "last_reviewed_at, review_interval_hours, review_count, "
        "last_review_feedback, source FROM card WHERE is_deleted = 0"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def _card_by_content(tmp_path: Path, uid: str, content: str) -> dict | None:
    return next((r for r in _card_rows(tmp_path, uid) if r["content"] == content), None)

def _card_field(tmp_path: Path, uid: str, content: str, field: str):
    """讀單卡的 JSON 欄位(examples/collocations)或純值,繞 verify 看磁碟真相。"""
    db = _user_dir(tmp_path, uid) / "cards.db"
    conn = sqlite3.connect(str(db))
    row = conn.execute(
        f"SELECT {field} FROM card WHERE content = ? AND is_deleted = 0", (content,)
    ).fetchone()
    conn.close()
    if row is None:
        return None
    val = row[0]
    if field in ("examples", "collocations", "inflections") and isinstance(val, str):
        return json.loads(val)
    return val

def _notebook_rows(tmp_path: Path, uid: str) -> list[dict]:
    db = _user_dir(tmp_path, uid) / "notebooks.db"
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id, name, sort_order FROM notebook WHERE is_deleted = 0"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def _graph_links(tmp_path: Path, uid: str, notebook_id: str = "default") -> list[dict]:
    p = _user_dir(tmp_path, uid) / f"graph_{notebook_id}.json"
    if not p.exists():
        return []
    data = json.loads(p.read_text())
    return data if isinstance(data, list) else list(data.values())

def _mk_user(tmp_path: Path, uid: str = "demo") -> str:
    r = _edit(str(tmp_path), "user-create", uid, "--commit", "--json")
    assert r.returncode == 0, r.stderr
    return uid

def _mk_notebook(tmp_path: Path, uid: str, name: str) -> str:
    """建 notebook 回傳其 hex id（讀 --json result）。"""
    r = _edit(str(tmp_path), "notebook-create", uid, name, "--commit", "--json")
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)["result"]["notebook"]["id"]
__all__ = (
    'Path',
    'UTC',
    '_card_by_content',
    '_card_field',
    '_card_rows',
    '_cli',
    '_edit',
    '_graph_links',
    '_mk_notebook',
    '_mk_user',
    '_notebook_rows',
    '_user_dir',
    'datetime',
    'json',
    'pytest',
    'sqlite3',
)
