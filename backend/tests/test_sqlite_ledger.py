"""sqlite_ledger 共用基礎件單元測試(review #12 抽出的單調時鐘 / tz 正規化)。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from kg.sqlite_ledger import as_utc, next_ingested_at, normalize_last_ingested


def test_next_ingested_at_advances_with_clock():
    last = datetime(2026, 6, 1, tzinfo=UTC)
    now = last + timedelta(seconds=5)
    assert next_ingested_at(last, now) == now


def test_next_ingested_at_steps_microsecond_when_clock_stalls():
    last = datetime(2026, 6, 1, tzinfo=UTC)
    assert next_ingested_at(last, last) == last + timedelta(microseconds=1)


def test_next_ingested_at_steps_on_backward_clock():
    last = datetime(2026, 6, 1, 0, 0, 5, tzinfo=UTC)
    now = last - timedelta(seconds=2)  # NTP 回撥
    assert next_ingested_at(last, now) == last + timedelta(microseconds=1)


def test_next_ingested_at_none_last_uses_now():
    now = datetime(2026, 6, 1, tzinfo=UTC)
    assert next_ingested_at(None, now) == now


def test_normalize_last_ingested_adds_utc_to_naive():
    naive = datetime(2026, 6, 1, 12, 0, 0)
    out = normalize_last_ingested(naive)
    assert out.tzinfo is UTC
    assert normalize_last_ingested(None) is None


def test_as_utc_naive_treated_as_utc():
    assert as_utc(datetime(2026, 6, 1)).tzinfo is UTC
    aware = datetime(2026, 6, 1, tzinfo=UTC)
    assert as_utc(aware) == aware
