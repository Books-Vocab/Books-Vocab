"""Unit tests for kg.admin_trends pure helpers + collect_trends shape.

The HTTP-level test (test_admin_stats_trends.py) drives the endpoint and
sets up the per-log SQLite paths via monkeypatch on DATA_DIR. This file
focuses on the date-window math and the empty-DB shape invariants that
the renderer relies on.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from kg.admin_trends import (
    DEFAULT_WINDOW_DAYS,
    MAX_WINDOW_DAYS,
    _date_range,
    collect_trends,
)

# ---- _date_range -----------------------------------------------------------

def test_date_range_length_matches_window_days():
    assert len(_date_range(30)) == 30
    assert len(_date_range(1)) == 1
    assert len(_date_range(MAX_WINDOW_DAYS)) == MAX_WINDOW_DAYS


def test_date_range_is_oldest_first_and_consecutive():
    days = _date_range(7)
    deltas = [(days[i + 1] - days[i]).days for i in range(len(days) - 1)]
    assert all(d == 1 for d in deltas)


def test_date_range_ends_today_utc():
    days = _date_range(5)
    today_utc = datetime.now(UTC).date()
    assert days[-1] == today_utc
    assert days[0] == today_utc - timedelta(days=4)


# ---- collect_trends shape on empty DB --------------------------------------

@pytest.fixture()
def empty_log_dbs(tmp_path, monkeypatch):
    """Point pipeline_log / judge_log / token_tracker at a clean tmp dir.

    Mirrors the strategy used by test_admin_stats_trends.py — without this
    the trend helpers would query whatever DB the test session inherited.
    """
    import kg.judge_log as jl
    import kg.pipeline_log as pl
    import kg.token_tracker as tt

    monkeypatch.setattr(pl, "DATA_DIR", tmp_path, raising=False)
    monkeypatch.setattr(pl, "DB_PATH", tmp_path / "pipeline_runs.db", raising=False)
    monkeypatch.setattr(jl, "DATA_DIR", tmp_path, raising=False)
    monkeypatch.setattr(jl, "DB_PATH", tmp_path / "judge_log.db", raising=False)
    monkeypatch.setattr(tt, "DATA_DIR", tmp_path, raising=False)
    monkeypatch.setattr(tt, "DB_PATH", tmp_path / "token_usage.db", raising=False)
    pl._reset()
    jl._reset()
    if tt._conn is not None:
        tt._conn.close()
        tt._conn = None
    yield
    pl._reset()
    jl._reset()
    if tt._conn is not None:
        tt._conn.close()
        tt._conn = None


def test_collect_trends_empty_db_default_window(empty_log_dbs):
    result = collect_trends()
    assert result["window_days"] == DEFAULT_WINDOW_DAYS
    assert len(result["days"]) == DEFAULT_WINDOW_DAYS
    assert len(result["errors_per_day"]) == DEFAULT_WINDOW_DAYS
    assert len(result["tokens_per_day"]) == DEFAULT_WINDOW_DAYS
    assert len(result["active_users_per_day"]) == DEFAULT_WINDOW_DAYS
    # zero-filled
    assert all(v == 0 for v in result["errors_per_day"])
    assert all(v == 0 for v in result["active_users_per_day"])
    # tokens_per_day entries always carry 'date' + 'total' even with no rows
    for entry in result["tokens_per_day"]:
        assert "date" in entry
        assert entry["total"] == 0
    assert result["call_types"] == []  # empty DB → no legend entries


def test_collect_trends_window_clamped_low(empty_log_dbs):
    # negative coerced up to the floor (1). Note: 0 / None fall through the
    # `window_days or DEFAULT` branch and default to 30 — that's by design,
    # so we exercise the actual clamp path with a negative input.
    result = collect_trends(window_days=-5)
    assert result["window_days"] == 1
    assert len(result["days"]) == 1


def test_collect_trends_window_zero_falls_through_to_default(empty_log_dbs):
    # documents the `window_days or DEFAULT_WINDOW_DAYS` truthiness branch
    result = collect_trends(window_days=0)
    assert result["window_days"] == DEFAULT_WINDOW_DAYS


def test_collect_trends_window_clamped_high(empty_log_dbs):
    result = collect_trends(window_days=MAX_WINDOW_DAYS + 100)
    assert result["window_days"] == MAX_WINDOW_DAYS
    assert len(result["days"]) == MAX_WINDOW_DAYS


def test_collect_trends_arrays_are_length_aligned(empty_log_dbs):
    result = collect_trends(window_days=14)
    n = len(result["days"])
    assert n == 14
    assert len(result["errors_per_day"]) == n
    assert len(result["tokens_per_day"]) == n
    assert len(result["active_users_per_day"]) == n


def test_collect_trends_days_are_iso_oldest_first(empty_log_dbs):
    result = collect_trends(window_days=5)
    days = result["days"]
    # ISO date strings, sortable lex == chronological
    assert days == sorted(days)
    # Last day is today UTC
    today_utc = datetime.now(UTC).date().isoformat()
    assert days[-1] == today_utc
