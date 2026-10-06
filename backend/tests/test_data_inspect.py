"""ops/data_inspect.py — 唯讀連線 + graph_default.json naming + KG_DATA_DIR 回歸測試。"""

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "ops" / "data_inspect.py"


def _mk_cards_db(path: Path, rows: list[tuple]) -> None:
    """rows: (id, content, meaning, is_deleted)。"""
    conn = sqlite3.connect(str(path))
    conn.execute(
        "CREATE TABLE card (id TEXT PRIMARY KEY, content TEXT, meaning TEXT, "
        "note TEXT, pos TEXT, difficulty REAL, is_deleted INTEGER DEFAULT 0)"
    )
    conn.executemany(
        "INSERT INTO card (id, content, meaning, is_deleted) VALUES (?, ?, ?, ?)", rows
    )
    conn.commit()
    conn.close()


def _run(data_dir: str, *args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "KG_DATA_DIR": data_dir}
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True, text=True, env=env,
    )


def test_sql_is_read_only(tmp_path):
    """sql 子命令走唯讀連線 — UPDATE 應失敗且 DB 未被改動。"""
    udir = tmp_path / "users" / "user1"
    udir.mkdir(parents=True)
    _mk_cards_db(udir / "cards.db", [("c1", "hello", "你好", 0)])

    r = _run(str(tmp_path), "-u", "user1", "sql", "UPDATE card SET content='X'")
    assert r.returncode != 0  # readonly DB → 寫入被拒

    conn = sqlite3.connect(str(udir / "cards.db"))
    assert conn.execute("SELECT content FROM card").fetchone()[0] == "hello"
    conn.close()


@pytest.mark.parametrize(
    "payload",
    [
        [
            {"id": "l1", "from_id": "c1", "to_id": "c2", "kind": "synonym",
             "confidence": 0.9, "created_at": "2026-01-01"},
        ],
        {
            "links": [
                {"id": "l1", "from_id": "c1", "to_id": "c2", "kind": "synonym",
                 "confidence": 0.9, "created_at": "2026-01-01"},
            ],
        },
    ],
    ids=["bare-list", "links-mapping"],
)
def test_graph_reads_default_json(tmp_path, payload):
    """graph 子命令保留 graph_default.json 的兩種合法形狀。"""
    udir = tmp_path / "users" / "user1"
    udir.mkdir(parents=True)
    _mk_cards_db(udir / "cards.db", [
        ("c1", "hello", "你好", 0), ("c2", "world", "世界", 0),
    ])
    (udir / "graph_default.json").write_text(json.dumps(payload))

    r = _run(str(tmp_path), "-u", "user1", "graph")
    assert r.returncode == 0, r.stderr
    assert "synonym" in r.stdout
    assert "hello" in r.stdout


def test_graph_non_list_links_fail_closed(tmp_path):
    """Malformed non-list links do not raise a TypeError traceback."""
    udir = tmp_path / "users" / "user1"
    udir.mkdir(parents=True)
    _mk_cards_db(udir / "cards.db", [("c1", "hello", "你好", 0)])
    (udir / "graph_default.json").write_text(json.dumps({"links": None}))

    r = _run(str(tmp_path), "-u", "user1", "graph")
    assert r.returncode == 0, r.stderr
    assert "Total: 0" in r.stdout
    assert "Traceback" not in r.stderr


def test_overview_respects_kg_data_dir(tmp_path):
    """overview 尊重 KG_DATA_DIR 環境變數。"""
    udir = tmp_path / "users" / "user1"
    udir.mkdir(parents=True)
    _mk_cards_db(udir / "cards.db", [("c1", "hello", "你好", 0)])

    r = _run(str(tmp_path), "-u", "user1", "overview")
    assert r.returncode == 0
    assert "user1" in r.stdout
