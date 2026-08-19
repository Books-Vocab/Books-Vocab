"""review_events schema 加寬測試 — SRS 前後快照 + is_synthetic + legacy migration。

複習帳本要供研究「每張卡學習曲線 / 遺忘規律」,逐筆事件必須自包含複習當下的 SRS 前後
狀態(間隔/下次複習/count/streak/lapse),不能只靠卡片現狀聚合。is_synthetic 區分
「合成的過去」(一次性遷移回填)與「真實的未來」。本測試護欄:新欄 round-trip、舊 db
自動 migration、預設值不破壞既有 client。
"""

from __future__ import annotations

import sqlite3
from contextlib import closing

from kg.api_models.review import ReviewEventEntry
from kg.review_events import ReviewEventStore, pull_review_events, push_review_events


def _entry(event_id: str, **overrides) -> ReviewEventEntry:
    base = dict(
        event_id=event_id,
        card_id="card-1",
        word_snapshot="ravishingly",
        notebook_id="default",
        feedback=1,
        reviewed_at="2026-03-01T12:00:00+00:00",
        created_at="2026-03-01T12:00:00+00:00",
        interval_before=12.0,
        interval_after=22.8,
        next_review_before="2026-03-01T12:00:00+00:00",
        next_review_after="2026-03-02T10:48:00+00:00",
        review_count_after=3,
        streak_after=2,
        lapse_after=1,
        is_synthetic=False,
    )
    base.update(overrides)
    return ReviewEventEntry(**base)


def test_new_fields_roundtrip(tmp_path):
    with closing(ReviewEventStore(tmp_path / "review_events.db")) as store:
        push_review_events([_entry("e1")], event_store=store)
        entries, _ = pull_review_events(since=None, event_store=store)
        e = entries[0]
        assert e.interval_before == 12.0
        assert e.interval_after == 22.8
        assert e.next_review_before is not None and e.next_review_before.startswith("2026-03-01")
        assert e.next_review_after is not None and e.next_review_after.startswith("2026-03-02")
        assert e.review_count_after == 3
        assert e.streak_after == 2
        assert e.lapse_after == 1
        assert e.is_synthetic is False


def test_is_synthetic_and_srs_default_when_absent(tmp_path):
    """舊 client 風格 entry(不帶新欄)仍合法:is_synthetic=False、SRS 快照 None。"""
    with closing(ReviewEventStore(tmp_path / "r.db")) as store:
        e = ReviewEventEntry(
            event_id="x",
            card_id="c",
            word_snapshot="w",
            feedback=1,
            reviewed_at="2026-03-01T12:00:00+00:00",
            created_at="2026-03-01T12:00:00+00:00",
        )
        assert e.is_synthetic is False
        assert e.interval_before is None
        push_review_events([e], event_store=store)
        entries, _ = pull_review_events(since=None, event_store=store)
        assert entries[0].is_synthetic is False
        assert entries[0].interval_after is None


def test_synthetic_flag_persists(tmp_path):
    with closing(ReviewEventStore(tmp_path / "r.db")) as store:
        push_review_events([_entry("e1", is_synthetic=True)], event_store=store)
        entries, _ = pull_review_events(since=None, event_store=store)
        assert entries[0].is_synthetic is True


def test_migration_adds_columns_to_legacy_db(tmp_path):
    """舊 schema db(無加寬欄位)開啟後自動 ADD COLUMN,舊資料 is_synthetic 落為 False。"""
    path = tmp_path / "legacy.db"
    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE reviewevent (
            event_id VARCHAR PRIMARY KEY,
            card_id VARCHAR,
            word_snapshot VARCHAR NOT NULL,
            notebook_id VARCHAR NOT NULL,
            feedback INTEGER NOT NULL,
            reviewed_at DATETIME NOT NULL,
            created_at DATETIME NOT NULL,
            ingested_at DATETIME
        )
        """
    )
    conn.execute(
        "INSERT INTO reviewevent VALUES "
        "('old1','c','musty','default',1,"
        "'2026-03-01 12:00:00','2026-03-01 12:00:00','2026-03-01 12:00:00')"
    )
    conn.commit()
    conn.close()

    with closing(ReviewEventStore(path)) as store:  # 開啟即觸發 migration
        with closing(sqlite3.connect(path)) as conn:
            cols = {row[1] for row in conn.execute("PRAGMA table_info(reviewevent)")}
        assert {
            "interval_before",
            "interval_after",
            "next_review_before",
            "next_review_after",
            "review_count_after",
            "streak_after",
            "lapse_after",
            "is_synthetic",
        } <= cols

        entries, _ = pull_review_events(since=None, event_store=store)
        assert len(entries) == 1
        assert entries[0].is_synthetic is False
        assert entries[0].interval_before is None


def test_migrated_legacy_db_accepts_new_synthetic_writes(tmp_path):
    """migration 後的舊 db 上新寫帶 SRS 快照 + is_synthetic=True 的事件,須完整落地 ——
    確認 ADD COLUMN 出來的欄位真能寫(非只讀得回 None)、新舊事件共存。"""
    path = tmp_path / "legacy.db"
    conn = sqlite3.connect(path)
    conn.execute(
        """CREATE TABLE reviewevent (
            event_id VARCHAR PRIMARY KEY, card_id VARCHAR,
            word_snapshot VARCHAR NOT NULL, notebook_id VARCHAR NOT NULL,
            feedback INTEGER NOT NULL, reviewed_at DATETIME NOT NULL,
            created_at DATETIME NOT NULL, ingested_at DATETIME)"""
    )
    conn.execute(
        "INSERT INTO reviewevent VALUES ('old1','c','musty','default',1,"
        "'2026-03-01 12:00:00','2026-03-01 12:00:00','2026-03-01 12:00:00')"
    )
    conn.commit()
    conn.close()

    with closing(ReviewEventStore(path)) as store:  # 觸發 migration
        push_review_events([_entry("new1", is_synthetic=True)], event_store=store)
        entries, _ = pull_review_events(since=None, event_store=store)
        by_id = {e.event_id: e for e in entries}
        assert set(by_id) == {"old1", "new1"}            # 新舊共存
        assert by_id["old1"].is_synthetic is False       # 舊事件 migration 落 False
        assert by_id["new1"].is_synthetic is True        # 新事件寫得進加寬欄
        assert by_id["new1"].interval_after == 22.8
        assert by_id["new1"].streak_after == 2
