"""Regression tests for vocabulary-facing timestamp serialization."""

from datetime import datetime, timedelta, timezone

from kg.vocab_shared import _dt_to_iso


def test_dt_to_iso_preserves_timezone_offsets_and_marks_naive_utc():
    naive = datetime(2026, 1, 2, 3, 4, 5)
    positive_offset = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone(timedelta(hours=8)))
    negative_offset = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone(timedelta(hours=-5)))

    assert _dt_to_iso(naive) == "2026-01-02T03:04:05Z"
    assert _dt_to_iso(positive_offset) == "2026-01-02T03:04:05+08:00"
    assert _dt_to_iso(negative_offset) == "2026-01-02T03:04:05-05:00"
