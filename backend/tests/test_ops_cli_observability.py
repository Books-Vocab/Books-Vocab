"""Readonly observability time-series regression tests."""

from __future__ import annotations

import argparse
import json
import sqlite3
from contextlib import closing
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
        conn.executemany(
            "INSERT INTO token_usage "
            "(user_id, call_type, input_tokens, output_tokens, created_at, provider) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [
                ("u1", "translate", 1, 1, "2026-05-01T00:00:00+01:00", "gemini"),
                ("u1", "translate", 1, 1, "2026-05-01T00:30:00+00:00", "gemini"),
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
