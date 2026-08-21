"""Regression tests for UTC-instant filtering of quota usage rows."""

from __future__ import annotations

import sqlite3
import threading
from datetime import UTC, datetime, timedelta, timezone
from unittest.mock import patch

import pytest

import kg.quota_service as quota_service
from kg.quota_service import get_all_quota_usage, get_user_usage_range


@pytest.fixture
def quota_db():
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.execute(
        """CREATE TABLE token_usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            call_type TEXT NOT NULL,
            input_tokens INTEGER NOT NULL DEFAULT 0,
            output_tokens INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            provider TEXT,
            model TEXT
        )"""
    )
    conn.commit()
    with patch.object(quota_service, "_get_conn", return_value=conn), patch.object(
        quota_service, "_lock", threading.Lock()
    ):
        yield conn
    conn.close()


def _insert(conn, user_id: str, created_at: str, tokens: int = 100_000) -> None:
    conn.execute(
        "INSERT INTO token_usage "
        "(user_id, call_type, input_tokens, output_tokens, created_at) "
        "VALUES (?, 'translate', ?, 0, ?)",
        (user_id, tokens, created_at),
    )
    conn.commit()


def test_quota_readers_filter_mixed_offset_rows_by_utc_instant(quota_db):
    now = datetime.now(UTC).replace(microsecond=0)
    cutoff = now - timedelta(days=1)
    same_instant = cutoff.isoformat()
    same_instant_other_offset = cutoff.astimezone(timezone(timedelta(hours=-5))).isoformat()
    too_old = (cutoff - timedelta(seconds=1)).isoformat()
    too_old_other_offset = (cutoff - timedelta(seconds=1)).astimezone(
        timezone(timedelta(hours=-5))
    ).isoformat()
    _insert(quota_db, "u", same_instant)
    _insert(quota_db, "u", same_instant_other_offset)
    _insert(quota_db, "u", too_old)
    _insert(quota_db, "u", too_old_other_offset)

    with patch.object(quota_service, "_window_cutoff_iso", return_value=cutoff.isoformat()):
        assert quota_service._recorded_usd("u") == pytest.approx(0.02)
        assert get_all_quota_usage()["u"]["calls"]["translate"]["count"] == 2
        assert get_user_usage_range("u", since_iso=cutoff.isoformat())["total_calls"] == 2
