"""Readonly observability time-series regression tests."""

from __future__ import annotations

import argparse
import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

import kg.admin_cost_summary as admin_cost_summary
import kg.ops_cli_observability as observability


def _make_args(**overrides) -> argparse.Namespace:
    args = {
        "metric": "calls",
        "bucket": "day",
        "range": "all",
        "uid": "all",
        "fill_zero": False,
        "json": True,
    }
    args.update(overrides)
    return argparse.Namespace(**args)


def _seed_token_usage_db(data_dir: Path) -> None:
    with closing(sqlite3.connect(data_dir / "token_usage.db")) as conn, conn:
        conn.execute(
            "CREATE TABLE token_usage ("
            "id INTEGER PRIMARY KEY, user_id TEXT, call_type TEXT, "
            "input_tokens INTEGER, output_tokens INTEGER, created_at TEXT, provider TEXT)"
        )
        conn.execute("CREATE INDEX idx_tu_created ON token_usage(created_at)")
        conn.executemany(
            "INSERT INTO token_usage "
            "(user_id, call_type, input_tokens, output_tokens, created_at, provider) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [
                ("u1", "translate", 1, 1, "2026-05-01T00:00:00+01:00", "gemini"),
                ("u1", "translate", 1, 1, "2026-05-01T00:30:00+00:00", "gemini"),
            ],
        )


class _FixedDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        value = cls(2026, 8, 21, 12, tzinfo=UTC)
        return value if tz is None else value.astimezone(tz)


def _seed_trends_token_usage_db(data_dir: Path) -> None:
    with closing(sqlite3.connect(data_dir / "token_usage.db")) as conn, conn:
        conn.execute(
            "CREATE TABLE token_usage ("
            "id INTEGER PRIMARY KEY, user_id TEXT, call_type TEXT, "
            "input_tokens INTEGER, output_tokens INTEGER, created_at TEXT, provider TEXT)"
        )
        conn.executemany(
            "INSERT INTO token_usage "
            "(user_id, call_type, input_tokens, output_tokens, created_at, provider) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [
                ("included-user", "translate", 3, 4, "2026-08-20T23:30:00-01:00", "gemini"),
                ("excluded-user", "translate", 100, 100, "2026-08-20T23:30:00+00:00", "gemini"),
            ],
        )


def test_timeseries_filters_created_at_by_utc_instant(tmp_path, monkeypatch, capsys):
    """A fixed-offset event before the UTC cutoff must not be counted."""
    _seed_token_usage_db(tmp_path)
    monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(
        admin_cost_summary,
        "since_iso",
        lambda _range: "2026-05-01T00:00:00+00:00",
    )

    observability.cmd_timeseries(_make_args())

    payload = json.loads(capsys.readouterr().out)
    assert payload["series"] == [{"bucket": "2026-05-01", "value": 1}]


def test_timeseries_uses_conservative_created_at_index_bound(tmp_path, monkeypatch, capsys):
    _seed_token_usage_db(tmp_path)
    monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(
        admin_cost_summary,
        "since_iso",
        lambda _range: "2026-05-01T00:00:00+00:00",
    )

    statements: list[str] = []
    traced_conn = sqlite3.connect(tmp_path / "token_usage.db")
    traced_conn.set_trace_callback(statements.append)
    monkeypatch.setattr(observability, "connect_ro", lambda _path: traced_conn)

    observability.cmd_timeseries(_make_args())
    capsys.readouterr()

    assert any(
        "FROM token_usage WHERE created_at >= '2026-04-30'" in statement
        for statement in statements
    )
    with closing(sqlite3.connect(tmp_path / "token_usage.db")) as conn:
        plan = conn.execute(
            "EXPLAIN QUERY PLAN SELECT * FROM token_usage WHERE created_at >= ?",
            ("2026-04-30",),
        ).fetchall()
    assert any("USING INDEX idx_tu_created" in row[-1] for row in plan)


def test_trends_filters_and_groups_token_usage_by_utc_instant(tmp_path, monkeypatch, capsys):
    _seed_trends_token_usage_db(tmp_path)
    monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(observability, "datetime", _FixedDatetime)

    observability.cmd_trends(argparse.Namespace(window=1, json=True))

    payload = json.loads(capsys.readouterr().out)
    assert payload["days"] == ["2026-08-21"]
    assert payload["active_users_per_day"] == [1]
    assert payload["tokens_per_day"] == [7]
