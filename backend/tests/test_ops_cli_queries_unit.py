"""Unit tests for kg.ops_cli_queries — direct function calls (not subprocess).

These hit error branches and empty-DB paths that subprocess tests rarely
exercise, closing the coverage gap for the query-oriented CLI commands.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

import kg.ops_cli_queries as q


def _make_args(**kwargs) -> argparse.Namespace:
    """Build a Namespace with all expected attributes defaulted."""
    defaults = {
        "uid": "u1",
        "json": True,
        "hours": 24,
        "substring": "",
        "key": "",
        "sql": [],
        "date": None,
        "level": "basic",
        "spec": Path("/nonexistent"),
    }
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


def _seed_user(tmp_path: Path, uid: str = "u1") -> Path:
    data_dir = tmp_path
    (data_dir / "users").mkdir()
    users_file = data_dir / "users.json"
    users_file.write_text(f'{{"{uid}": {{"config": {{}}, "email": "{uid}@test.com"}}}}')

    user_dir = data_dir / "users" / uid
    user_dir.mkdir()
    conn = sqlite3.connect(str(user_dir / "cards.db"))
    conn.execute(
        "CREATE TABLE card (id TEXT PRIMARY KEY, content TEXT, meaning TEXT, "
        "is_deleted INTEGER DEFAULT 0, created_at TEXT, updated_at TEXT)"
    )
    now = datetime.now(UTC).isoformat()
    conn.execute(
        "INSERT INTO card VALUES (?,?,?,?,?,?)",
        ("c1", "apple", "蘋果", 0, now, now),
    )
    conn.commit()
    conn.close()
    return data_dir


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


# ── cmd_user_quota ───────────────────────────────────────────────────────


class TestUserQuota:
    def test_empty_db_json(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
        q.cmd_user_quota(_make_args(uid="u1"))
        out = capsys.readouterr().out
        assert "u1" in out
        assert "used_usd" in out

    def test_with_data(self, tmp_path, monkeypatch, capsys):
        _seed_token_db(tmp_path)
        monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
        q.cmd_user_quota(_make_args(uid="u1"))
        out = capsys.readouterr().out
        assert "translate" in out.lower() or "used_usd" in out


# ── cmd_user_stats ───────────────────────────────────────────────────────


class TestUserStats:
    def test_happy_path(self, tmp_path, monkeypatch, capsys):
        _seed_user(tmp_path)
        monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
        q.cmd_user_stats(_make_args(uid="u1"))
        out = capsys.readouterr().out
        assert "total" in out.lower() or "apple" in out

    def test_missing_db_exits_1(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
        (tmp_path / "users").mkdir()
        (tmp_path / "users.json").write_text('{"u1": {}}')
        with pytest.raises(SystemExit) as ei:
            q.cmd_user_stats(_make_args(uid="u1", json=False))
        assert ei.value.code == 1


# ── cmd_user_config ──────────────────────────────────────────────────────


class TestUserConfig:
    def test_happy_path(self, tmp_path, monkeypatch, capsys):
        _seed_user(tmp_path)
        monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
        q.cmd_user_config(_make_args(uid="u1"))
        out = capsys.readouterr().out
        assert "u1" in out

    def test_missing_user_exits_1(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
        (tmp_path / "users").mkdir()
        (tmp_path / "users.json").write_text('{}')
        with pytest.raises(SystemExit) as ei:
            q.cmd_user_config(_make_args(uid="ghost", json=False))
        assert ei.value.code == 1

    def test_auto_link_defaults_enabled(self, tmp_path, monkeypatch, capsys):
        # 向後相容:config 無 auto_link group → 投影預設 enabled=True。
        _seed_user(tmp_path)
        monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
        q.cmd_user_config(_make_args(uid="u1"))
        payload = json.loads(capsys.readouterr().out)
        assert payload["config"]["auto_link"] == {"enabled": True, "updated_at": None}

    def test_auto_link_disabled_surfaced(self, tmp_path, monkeypatch, capsys):
        _seed_user(tmp_path)
        users_file = tmp_path / "users.json"
        users_file.write_text(
            '{"u1": {"config": {"auto_link": {"enabled": false, "updated_at": 5.0}},'
            ' "email": "u1@test.com"}}'
        )
        monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
        q.cmd_user_config(_make_args(uid="u1"))
        payload = json.loads(capsys.readouterr().out)
        assert payload["config"]["auto_link"] == {"enabled": False, "updated_at": 5.0}


# ── cmd_world_state ──────────────────────────────────────────────────────


class TestWorldState:
    def test_json_output(self, tmp_path, monkeypatch, capsys):
        _seed_user(tmp_path)
        monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
        q.cmd_world_state(_make_args(uid="u1"))
        out = capsys.readouterr().out
        assert "schema" in out


# ── cmd_world_diff ───────────────────────────────────────────────────────


class TestWorldDiff:
    def test_missing_spec_raises(self, tmp_path, monkeypatch, capsys):
        _seed_user(tmp_path)
        monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
        with pytest.raises(FileNotFoundError):
            q.cmd_world_diff(_make_args(uid="u1", spec=tmp_path / "no.json"))


# ── cmd_quota_overview ───────────────────────────────────────────────────


class TestQuotaOverview:
    def test_empty_db(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
        q.cmd_quota_overview(_make_args())
        out = capsys.readouterr().out
        assert "count" in out

    def test_with_data(self, tmp_path, monkeypatch, capsys):
        _seed_token_db(tmp_path)
        monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
        q.cmd_quota_overview(_make_args())
        out = capsys.readouterr().out
        assert "u1" in out


# ── cmd_active_users ─────────────────────────────────────────────────────


class TestActiveUsers:
    def test_empty_db(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
        q.cmd_active_users(_make_args(hours=48))
        out = capsys.readouterr().out
        assert "hours" in out

    def test_with_data(self, tmp_path, monkeypatch, capsys):
        _seed_token_db(tmp_path)
        monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
        q.cmd_active_users(_make_args(hours=48))
        out = capsys.readouterr().out
        assert "u1" in out


# ── cmd_card_find ────────────────────────────────────────────────────────


class TestCardFind:
    def test_happy_path(self, tmp_path, monkeypatch, capsys):
        _seed_user(tmp_path)
        monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
        q.cmd_card_find(_make_args(uid="u1", substring="app"))
        out = capsys.readouterr().out
        assert "apple" in out.lower() or "count" in out

    def test_missing_db_exits_1(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
        (tmp_path / "users").mkdir()
        (tmp_path / "users.json").write_text('{"u1": {}}')
        with pytest.raises(SystemExit) as ei:
            q.cmd_card_find(_make_args(uid="u1", substring="x"))
        assert ei.value.code == 1


# ── cmd_card_get ─────────────────────────────────────────────────────────


class TestCardGet:
    def test_happy_path(self, tmp_path, monkeypatch, capsys):
        _seed_user(tmp_path)
        monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
        q.cmd_card_get(_make_args(uid="u1", key="c1"))
        out = capsys.readouterr().out
        assert "c1" in out

    def test_missing_db_exits_1(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
        (tmp_path / "users").mkdir()
        (tmp_path / "users.json").write_text('{"u1": {}}')
        with pytest.raises(SystemExit) as ei:
            q.cmd_card_get(_make_args(uid="u1", key="c1"))
        assert ei.value.code == 1


# ── cmd_db_query ─────────────────────────────────────────────────────────


class TestDbQuery:
    def test_schema_json(self, tmp_path, monkeypatch, capsys):
        _seed_user(tmp_path)
        monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
        q.cmd_db_query(_make_args(uid="u1", sql=["--schema", "--json"]))
        out = capsys.readouterr().out
        assert "card" in out

    def test_sql_query(self, tmp_path, monkeypatch, capsys):
        _seed_user(tmp_path)
        monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
        q.cmd_db_query(_make_args(uid="u1", sql=["SELECT", "id", "FROM", "card"]))
        out = capsys.readouterr().out
        assert "c1" in out

    def test_readonly_guard_blocks_write(self, tmp_path, monkeypatch, capsys):
        _seed_user(tmp_path)
        monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
        with pytest.raises(SystemExit) as ei:
            q.cmd_db_query(_make_args(uid="u1", sql=["DELETE", "FROM", "card"]))
        assert ei.value.code == 1

    def test_sql_error_json(self, tmp_path, monkeypatch, capsys):
        _seed_user(tmp_path)
        monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
        with pytest.raises(SystemExit) as ei:
            q.cmd_db_query(_make_args(uid="u1", sql=["SELECT", "nope", "FROM", "card", "--json"]))
        assert ei.value.code == 1


# ── cmd_sync_trace ───────────────────────────────────────────────────────


class TestSyncTrace:
    def test_empty_day(self, tmp_path, monkeypatch, capsys):
        _seed_user(tmp_path)
        monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        q.cmd_sync_trace(_make_args(uid="u1", date=today))
        out = capsys.readouterr().out
        assert "events" in out.lower() or "trace" in out.lower()

    def test_with_token_usage(self, tmp_path, monkeypatch, capsys):
        _seed_user(tmp_path)
        _seed_token_db(tmp_path)
        monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        q.cmd_sync_trace(_make_args(uid="u1", date=today))
        out = capsys.readouterr().out
        assert "translate" in out.lower() or "events" in out.lower()
