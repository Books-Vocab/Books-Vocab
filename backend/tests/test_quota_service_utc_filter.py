"""Regression tests for UTC-instant filtering in quota usage readers."""

from __future__ import annotations

import sqlite3
import threading
from unittest.mock import patch

import pytest

from kg.quota_service import (
    check_and_get_quota,
    check_quota,
    get_all_quota_usage,
    get_quota_state,
    get_user_usage_range,
)

_CUTOFF = "2026-01-02T00:00:00+00:00"
_STALE_OFFSET = "2026-01-02T00:30:00+02:00"
_INCLUDED_UTC = "2026-01-02T00:30:00+00:00"


@pytest.fixture
def quota_db():
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.execute(
        """
        CREATE TABLE token_usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            call_type TEXT NOT NULL,
            input_tokens INTEGER NOT NULL DEFAULT 0,
            output_tokens INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            provider TEXT,
            model TEXT
        )
        """
    )
    conn.commit()
    lock = threading.Lock()
    with (
        patch("kg.quota_service._get_conn", return_value=conn),
        patch("kg.quota_service._lock", lock),
        patch("kg.quota_service._window_cutoff_iso", return_value=_CUTOFF),
    ):
        yield conn
    conn.close()


def _insert_usage(conn, created_at: str, input_tokens: int) -> None:
    conn.execute(
        """
        INSERT INTO token_usage
            (user_id, call_type, input_tokens, output_tokens, created_at, provider, model)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        ("user1", "translate", input_tokens, 0, created_at, "gemini", "test"),
    )
    conn.commit()


def test_quota_readers_filter_mixed_offsets_by_utc_instant(quota_db):
    """All quota readers must use the instant, not the raw ISO text, boundary."""
    _insert_usage(quota_db, _STALE_OFFSET, 300_000)
    _insert_usage(quota_db, _INCLUDED_UTC, 150_000)

    ranged = get_user_usage_range("user1", since_iso=_CUTOFF)
    assert ranged["calls"]["translate"]["count"] == 1
    assert ranged["tokens"]["translate"]["input_tokens"] == 150_000
    assert ranged["total_calls"] == 1

    all_usage = get_all_quota_usage()
    assert all_usage["user1"]["calls"]["translate"]["count"] == 1
    assert all_usage["user1"]["used_usd"] == pytest.approx(0.015)

    state = get_quota_state("user1", is_pro=False)
    check = check_quota("user1", "translate", is_pro=False)
    checked = check_and_get_quota("user1", "translate", is_pro=False)
    assert state["fraction"] == pytest.approx(0.5)
    assert check["exceeded"] is False
    assert checked == check
