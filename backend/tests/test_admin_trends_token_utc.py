"""Regression coverage for UTC filtering in admin token trends."""

from __future__ import annotations

import pytest


@pytest.fixture()
def token_usage_db(tmp_path, monkeypatch):
    import kg.token_tracker as token_tracker

    token_tracker.reset()
    monkeypatch.setattr(token_tracker, "DATA_DIR", tmp_path)
    monkeypatch.setattr(token_tracker, "DB_PATH", tmp_path / "token_usage.db")
    try:
        yield token_tracker
    finally:
        token_tracker.reset()


def test_token_trends_filter_mixed_offsets_by_utc_instant(token_usage_db):
    from kg.admin_trends import _tokens_by_day_and_type

    with token_usage_db._lock:
        conn = token_usage_db._get_conn()
        conn.executemany(
            "INSERT INTO token_usage "
            "(user_id, call_type, input_tokens, output_tokens, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            [
                ("older-utc", "judge", 1, 0, "2026-05-14T12:00:00+01:00"),
                ("newer-utc", "judge", 2, 0, "2026-05-14T12:30:00+00:00"),
            ],
        )
        conn.commit()

    assert _tokens_by_day_and_type("2026-05-14T12:00:00+00:00") == {"2026-05-14": {"judge": 2}}
