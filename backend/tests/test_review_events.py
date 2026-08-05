from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from kg.api_models import ReviewEventEntry
from kg.exceptions import BadRequestError
from kg.review_events import (
    ReviewEvent,
    ReviewEventStore,
    _format_timestamp,
    _parse_iso8601_timestamp,
    pull_review_events,
    push_review_events,
)


def _event(
    event_id: str = "evt-1",
    *,
    reviewed_at: datetime | None = None,
    word: str = "serendipity",
    card_id: str | None = "card-1",
) -> ReviewEventEntry:
    reviewed = reviewed_at or datetime(2026, 6, 1, 10, 0, tzinfo=UTC)
    return ReviewEventEntry(
        event_id=event_id,
        card_id=card_id,
        word_snapshot=word,
        notebook_id="default",
        feedback=1,
        reviewed_at=reviewed.isoformat(),
        created_at=(reviewed + timedelta(seconds=5)).isoformat(),
    )


def test_review_event_store_empty(tmp_path):
    store = ReviewEventStore(tmp_path / "review_events.db")

    assert store.all() == []


def test_push_and_pull_review_events_round_trip(tmp_path):
    store = ReviewEventStore(tmp_path / "review_events.db")
    first = _event("evt-1", reviewed_at=datetime(2026, 6, 1, 10, 0, tzinfo=UTC))
    second = _event("evt-2", reviewed_at=datetime(2026, 6, 2, 10, 0, tzinfo=UTC), word="ephemeral")

    result = push_review_events([second, first], event_store=store)
    pulled, cursor = pull_review_events(since=None, event_store=store)

    assert result == {"inserted": 2, "skipped": 0}
    # ingestion order: both arrive in the same insert_many call; ordering is by ingested_at
    assert {event.event_id for event in pulled} == {"evt-1", "evt-2"}
    assert cursor is not None


def test_duplicate_event_id_is_skipped(tmp_path):
    store = ReviewEventStore(tmp_path / "review_events.db")
    first = _event("evt-1", word="first")
    duplicate = _event("evt-1", word="second")

    assert push_review_events([first], event_store=store) == {"inserted": 1, "skipped": 0}
    assert push_review_events([duplicate], event_store=store) == {"inserted": 0, "skipped": 1}

    pulled, _cursor = pull_review_events(since=None, event_store=store)
    assert len(pulled) == 1
    assert pulled[0].word_snapshot == "first"


def test_cursor_advances_by_ingestion_order(tmp_path):
    store = ReviewEventStore(tmp_path / "review_events.db")
    push_review_events([_event("a")], event_store=store)
    _first, cursor1 = pull_review_events(since=None, event_store=store)

    push_review_events([_event("b", word="bravo")], event_store=store)
    pulled, cursor2 = pull_review_events(since=cursor1, event_store=store)

    assert [event.event_id for event in pulled] == ["b"]
    assert cursor2 != cursor1


def test_late_arriving_past_event_is_not_skipped_by_cursor(tmp_path):
    """An event whose reviewed_at is in the past but ingested later must still be
    pulled by a cursor advanced past an earlier ingestion."""
    store = ReviewEventStore(tmp_path / "review_events.db")
    recent = _event("recent", reviewed_at=datetime(2026, 6, 10, 10, 0, tzinfo=UTC))
    push_review_events([recent], event_store=store)
    _first, cursor1 = pull_review_events(since=None, event_store=store)

    # Device pushes a much older review only now (offline backfill).
    late = _event("late", reviewed_at=datetime(2026, 6, 1, 9, 0, tzinfo=UTC), word="tardy")
    push_review_events([late], event_store=store)

    pulled, _cursor2 = pull_review_events(since=cursor1, event_store=store)
    assert [event.event_id for event in pulled] == ["late"]


def test_empty_pull_keeps_cursor(tmp_path):
    store = ReviewEventStore(tmp_path / "review_events.db")
    push_review_events([_event("a")], event_store=store)
    _first, cursor1 = pull_review_events(since=None, event_store=store)

    pulled, cursor2 = pull_review_events(since=cursor1, event_store=store)
    assert pulled == []
    assert cursor2 == cursor1


@pytest.mark.parametrize("bad_since", ["garbage", "2026-13-99", "1717668000", "not-a-date"])
def test_since_must_be_iso8601(tmp_path, bad_since):
    store = ReviewEventStore(tmp_path / "review_events.db")

    with pytest.raises(BadRequestError):
        pull_review_events(since=bad_since, event_store=store)


# `since` 是 client 回送的 watermark，歷史版本可能寫入過非嚴格 ISO8601 的字串
# （naive、空格分隔、basic offset）。為打破「壞 watermark → 400 → 不前進 → 永遠 400」
# 的死鎖，pull 端的 since parser 刻意容錯：能還原成同一時間點的都接受並正規化為
# tz-aware UTC。注意這與 ingestion 的 _parse_required_timestamp（reviewed_at/created_at
# 仍嚴格要求 tz-aware，見 test_event_timestamps_must_be_timezone_aware_iso8601）分歧。
@pytest.mark.parametrize(
    "lenient_since",
    [
        "2026-06-01T10:00:00+00:00",  # 標準（含冒號 offset）
        "2026-06-01T10:00:00Z",  # Z 後綴
        "2026-06-01T10:00:00",  # naive → 視為 UTC
        "2026-06-01 10:00:00+00:00",  # 空格分隔（非 T）
        "2026-06-01 10:00:00 +0000",  # Swift Date.description 風格（basic offset + 前空格）
        "2026-06-01",  # 純日期 → 當天 00:00 UTC
    ],
)
def test_since_accepts_lenient_client_formats(lenient_since):
    parsed = _parse_iso8601_timestamp(lenient_since)
    assert parsed.tzinfo is not None
    assert parsed.utcoffset() == timedelta(0)


def test_since_lenient_formats_are_equivalent():
    """同一時間點的不同寫法 parse 成完全相同的 instant。"""
    canonical = _parse_iso8601_timestamp("2026-06-01T10:00:00+00:00")
    for variant in (
        "2026-06-01T10:00:00Z",
        "2026-06-01T10:00:00",
        "2026-06-01 10:00:00+00:00",
        "2026-06-01 10:00:00 +0000",
    ):
        assert _parse_iso8601_timestamp(variant) == canonical


# 契約守門（C/G2）：後端在 pull 回送的 cursor 由 _format_timestamp 產生，client 會原封
# 不動把它存成下一輪的 `since` 再送回。若 _format_timestamp 產出的任何寫法不被
# _parse_iso8601_timestamp 接受，就是「後端自產自拒」→ watermark 永不前進的死鎖
# （正是本次事件的根因類型）。此守門確保兩者永遠對稱，任一端日後漂移立即紅。
@pytest.mark.parametrize(
    "moment",
    [
        datetime(2026, 6, 1, 10, 0, tzinfo=UTC),  # 整秒
        datetime(2026, 6, 1, 10, 0, 0, 123456, tzinfo=UTC),  # 含微秒
        datetime(2026, 1, 1, 0, 0, tzinfo=UTC),  # 年初邊界
        datetime(2026, 12, 31, 23, 59, 59, 999999, tzinfo=UTC),  # 年末邊界 + 微秒
        datetime(2026, 6, 1, 10, 0),  # naive → _format_timestamp 視為 UTC
    ],
)
def test_server_cursor_always_accepted_by_since_parser(moment):
    cursor = _format_timestamp(moment)
    parsed = _parse_iso8601_timestamp(cursor)
    expected = moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)
    assert parsed == expected


# 生產事故根因（2026-06-08）：cursor `_format_timestamp` 產出帶 '+00:00' offset，client
# 用 URLComponents 原樣回送（'+' 是 RFC 3986 query 合法字元，不被 percent-encode），
# Starlette 依 x-www-form-urlencoded 解碼把 '+' → 空格 → handler 收到 '...183209 00:00'
# → fromisoformat 炸 → 400 → watermark 永不前進 → review 下載永久 400（push 走 body 不受影響）。
# 既有契約守門（test_server_cursor_always_accepted_by_since_parser）直接傳字串、沒過
# URL 編碼，故抓不到；唯有「裸 '+' 走 wire」才重現（見 test_review_events_api 的回歸測試）。
# 三層修法：① cursor 改吐 'Z'（源頭去 '+'）② parser 容忍被吃成空格的 '+'（解現場存量）
# ③ iOS 端 '+' → '%2B'（合約正確，另在 iOS commit）。
def test_since_tolerates_url_decoded_plus_offset():
    """② parser 容錯：'+' offset 被 query 解碼吃成空格後，仍須 parse 成同一時間點。"""
    eaten = "2026-06-06T07:02:00.183209 00:00"  # '+00:00' 的 '+' → 空格
    canonical = _parse_iso8601_timestamp("2026-06-06T07:02:00.183209+00:00")
    assert _parse_iso8601_timestamp(eaten) == canonical


def test_cursor_is_url_safe_no_plus():
    """① 源頭修法：emit 的 cursor 不得帶 '+'（用 'Z'），才能對任何 client（新舊）無損
    穿越 query string。"""
    cursor = _format_timestamp(datetime(2026, 6, 1, 10, 0, 0, 123456, tzinfo=UTC))
    assert "+" not in cursor, cursor
    assert cursor.endswith("Z"), cursor


@pytest.mark.parametrize(
    "moment",
    [
        datetime(2026, 6, 1, 10, 0, tzinfo=UTC),
        datetime(2026, 6, 1, 10, 0, 0, 183209, tzinfo=UTC),
        datetime(2026, 12, 31, 23, 59, 59, 999999, tzinfo=UTC),
    ],
)
def test_server_cursor_survives_query_string_round_trip(moment):
    """完整 wire round-trip：emit cursor → 模擬 query string 的 '+'→空格解碼 → 重新 parse，
    須還原同一 instant。守住整條 client↔server cursor 迴圈（既有守門只覆蓋 in-process 字串）。"""
    cursor = _format_timestamp(moment)
    on_wire = cursor.replace("+", " ")  # Starlette 交給 handler 的樣子
    assert _parse_iso8601_timestamp(on_wire) == moment


@pytest.mark.parametrize("field_name", ["reviewed_at", "created_at"])
@pytest.mark.parametrize("bad_value", ["2026-06-01", "1717668000", "2026-06-01T10:00:00"])
def test_event_timestamps_must_be_timezone_aware_iso8601(tmp_path, field_name, bad_value):
    store = ReviewEventStore(tmp_path / "review_events.db")
    event = _event("evt-bad-time")
    data = event.model_dump()
    data[field_name] = bad_value

    with pytest.raises(BadRequestError):
        push_review_events([ReviewEventEntry(**data)], event_store=store)


def test_unknown_card_id_is_preserved(tmp_path):
    store = ReviewEventStore(tmp_path / "review_events.db")
    event = _event("evt-unknown", card_id="deleted-card")

    push_review_events([event], event_store=store)

    pulled, _cursor = pull_review_events(since=None, event_store=store)
    assert pulled[0].card_id == "deleted-card"


def test_monotonic_guard_keeps_ingested_at_unique_when_clock_is_frozen(tmp_path, monkeypatch):
    """With a frozen wall clock (models same-microsecond bursts and backward steps),
    ingested_at must still be strictly increasing and unique — both within one
    insert_many call and continued across the next call. This is what lets the strict
    ``>`` cursor never skip an event. Without the max+1µs guard every row would share
    the frozen timestamp and collide."""
    frozen = datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC)
    monkeypatch.setattr("kg.review_events._now", lambda: frozen)

    store = ReviewEventStore(tmp_path / "review_events.db")
    push_review_events([_event(f"a-{i}") for i in range(5)], event_store=store)
    push_review_events([_event(f"b-{i}") for i in range(5)], event_store=store)

    ingested = [row.ingested_at for row in store.all()]
    assert len(ingested) == 10
    assert len(set(ingested)) == 10, "frozen clock collided ingested_at"
    assert ingested == sorted(ingested), "ingested_at not strictly increasing"


def test_legacy_store_without_ingested_at_is_migrated(tmp_path):
    """A pre-existing DB created before the ingested_at column must self-upgrade
    and backfill ingested_at from reviewed_at on open."""
    db_path = tmp_path / "review_events.db"
    table = ReviewEvent.__tablename__
    conn = sqlite3.connect(db_path)
    conn.execute(
        f"CREATE TABLE {table} ("
        "event_id TEXT PRIMARY KEY, card_id TEXT, word_snapshot TEXT, "
        "notebook_id TEXT, feedback INTEGER, reviewed_at TEXT, created_at TEXT)"
    )
    conn.execute(
        f"INSERT INTO {table} VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("legacy-1", "card-x", "legacyword", "default", 1,
         "2026-05-01 09:00:00.000000", "2026-05-01 09:00:05.000000"),
    )
    conn.commit()
    conn.close()

    store = ReviewEventStore(db_path)
    pulled, cursor = pull_review_events(since=None, event_store=store)

    assert [event.event_id for event in pulled] == ["legacy-1"]
    assert cursor is not None


def _count_reviewevent_selects(store: ReviewEventStore, entries: list[ReviewEventEntry]) -> int:
    """Run push_review_events and return how many SELECTs touched the events table."""
    from sqlalchemy import event as sa_event

    table = ReviewEvent.__tablename__
    seen: list[str] = []

    def _before(conn, cursor, statement, parameters, context, executemany):
        normalized = " ".join(statement.split()).lower()
        if normalized.startswith("select") and table in normalized:
            seen.append(normalized)

    sa_event.listen(store.engine, "before_cursor_execute", _before)
    try:
        push_review_events(entries, event_store=store)
    finally:
        sa_event.remove(store.engine, "before_cursor_execute", _before)
    return len(seen)


def test_duplicate_push_existence_check_does_not_scale_with_batch_size(tmp_path):
    """Re-pushing an already-stored history must not cost one SELECT per event.

    The iOS client has no push watermark yet, so every sync re-sends the entire
    review history; a per-entry ``session.get`` turned that into thousands of
    point queries that all resolve to "already have it". The existence check
    must be batched, so the statement count stays flat as the batch grows.
    """
    small = [_event(f"small-{i}") for i in range(20)]
    large = [_event(f"large-{i}") for i in range(200)]

    small_store = ReviewEventStore(tmp_path / "small.db")
    large_store = ReviewEventStore(tmp_path / "large.db")
    push_review_events(small, event_store=small_store)
    push_review_events(large, event_store=large_store)

    small_selects = _count_reviewevent_selects(small_store, small)
    large_selects = _count_reviewevent_selects(large_store, large)

    assert small_selects <= 4, f"even a 20-event batch issued {small_selects} SELECTs"
    # 10x the entries must not mean 10x the queries.
    assert large_selects - small_selects <= 2, (
        f"existence check scales with batch size: {small_selects} -> {large_selects}"
    )


def test_duplicate_event_id_within_one_batch_is_skipped(tmp_path):
    """Batching the existence check must not lose the intra-batch duplicate guard.

    The per-entry ``session.get`` caught a repeated event_id inside a single
    payload via autoflush. A pre-fetched id set only knows what was already
    committed, so the batch loop has to track ids it just added.
    """
    store = ReviewEventStore(tmp_path / "review_events.db")
    first = _event("evt-dup", word="first")
    second = _event("evt-dup", word="second")

    assert push_review_events([first, second], event_store=store) == {
        "inserted": 1,
        "skipped": 1,
    }

    pulled, _cursor = pull_review_events(since=None, event_store=store)
    assert [event.word_snapshot for event in pulled] == ["first"]
