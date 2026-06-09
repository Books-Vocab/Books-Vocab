"""Unit tests for kg.ops_cli_costs — direct function calls."""
from __future__ import annotations

import argparse
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest

import kg.ops_cli_costs as costs


def _make_args(**kwargs) -> argparse.Namespace:
    defaults = {"uid": "u1", "json": True, "range": "24h"}
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


def _seed_token_db(tmp_path: Path) -> Path:
    conn = sqlite3.connect(str(tmp_path / "token_usage.db"))
    conn.execute(
        "CREATE TABLE token_usage (id INTEGER PRIMARY KEY, user_id TEXT, "
        "call_type TEXT, input_tokens INTEGER, output_tokens INTEGER, created_at TEXT)"
    )
    now = datetime.now(UTC).isoformat()
    conn.execute(
        "INSERT INTO token_usage (user_id, call_type, input_tokens, output_tokens, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        ("u1", "translate", 100, 50, now),
    )
    conn.commit()
    conn.close()
    return tmp_path


class TestCmdCost:
    def test_empty_db(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
        costs.cmd_cost(_make_args(uid="u1"))
        out = capsys.readouterr().out
        assert "u1" in out

    def test_with_data(self, tmp_path, monkeypatch, capsys):
        _seed_token_db(tmp_path)
        monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
        costs.cmd_cost(_make_args(uid="u1"))
        out = capsys.readouterr().out
        assert "translate" in out.lower()

    def test_text_output(self, tmp_path, monkeypatch, capsys):
        _seed_token_db(tmp_path)
        monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
        costs.cmd_cost(_make_args(uid="u1", json=False))
        out = capsys.readouterr().out
        assert "$" in out


class TestCmdCostOverview:
    def test_empty_db(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
        costs.cmd_cost_overview(_make_args())
        out = capsys.readouterr().out
        assert "count" in out.lower() or "users" in out.lower()

    def test_with_data(self, tmp_path, monkeypatch, capsys):
        _seed_token_db(tmp_path)
        monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
        costs.cmd_cost_overview(_make_args())
        out = capsys.readouterr().out
        assert "u1" in out

    def test_text_output(self, tmp_path, monkeypatch, capsys):
        _seed_token_db(tmp_path)
        monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
        costs.cmd_cost_overview(_make_args(json=False))
        out = capsys.readouterr().out
        assert "$" in out


class TestCmdFleetOverview:
    def test_empty_data_dir(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
        costs.cmd_fleet_overview(_make_args())
        out = capsys.readouterr().out
        assert "count" in out.lower() or "users" in out.lower()

    def test_with_user(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
        user_dir = tmp_path / "users" / "u1"
        user_dir.mkdir(parents=True)
        (tmp_path / "users.json").write_text('{"u1": {"config": {}}}')

        conn = sqlite3.connect(str(user_dir / "cards.db"))
        conn.execute(
            "CREATE TABLE card (id TEXT PRIMARY KEY, content TEXT, is_deleted INTEGER)"
        )
        conn.execute("INSERT INTO card VALUES ('c1', 'apple', 0)")
        conn.commit()
        conn.close()

        costs.cmd_fleet_overview(_make_args())
        out = capsys.readouterr().out
        assert "u1" in out

    def test_text_output(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
        costs.cmd_fleet_overview(_make_args(json=False))
        out = capsys.readouterr().out
        assert "fleet" in out.lower() or "users" in out.lower()
