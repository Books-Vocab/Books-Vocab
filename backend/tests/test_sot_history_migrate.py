"""sot_history_migrate 單元測試 — 一次性把單一用戶資料夾的複習聚合 + 圖譜終態
回填成合成歷史帳本的護欄。

遷移 = 清掉舊 review_events 垃圾(card_id NULL 的歷史殘留)→ 從 cards.db 聚合合成逐筆
複習史 → 從 graph_{nb}.json 終態合成 link 生命史 → 落 review_events.db / graph_events.db。
dry-run 預設(不寫)、apply 前自動備份(只備份一次,保住真正原始檔)、確定式冪等。

一致性不變量(灌完必須成立):
* 每卡合成事件數 == review_count
* 每卡複習事件時間嚴格遞增
* 圖譜 event 的 link_id 集合 == 終態 link 集合;每條 link ≥1 筆 link_added
* 全部 is_synthetic=True
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from kg.graph_event_log import GraphEventStore, GraphEventType, GraphSnapshotStore
from kg.review_events import ReviewEventStore, pull_review_events
from kg.sot_history_migrate import migrate_user


def _make_cards_db(path: Path, cards: list[dict]) -> None:
    conn = sqlite3.connect(path)
    conn.execute(
        """CREATE TABLE card (
            id TEXT PRIMARY KEY, content TEXT, meaning TEXT, notebook_id TEXT,
            is_deleted INTEGER DEFAULT 0, created_at TEXT,
            review_interval_hours REAL DEFAULT 12.0, last_reviewed_at TEXT,
            review_count INTEGER DEFAULT 0, lapse_count INTEGER DEFAULT 0,
            review_streak INTEGER DEFAULT 0, last_review_feedback INTEGER DEFAULT -1
        )"""
    )
    for c in cards:
        conn.execute(
            """INSERT INTO card (id, content, meaning, notebook_id, is_deleted,
                created_at, review_interval_hours, last_reviewed_at, review_count,
                lapse_count, review_streak, last_review_feedback)
               VALUES (:id,:content,:meaning,:notebook_id,:is_deleted,:created_at,
                :review_interval_hours,:last_reviewed_at,:review_count,:lapse_count,
                :review_streak,:last_review_feedback)""",
            {
                "meaning": "m", "is_deleted": 0, "notebook_id": "default",
                "review_interval_hours": 96.0, "lapse_count": 0, "review_streak": None,
                "last_review_feedback": 1, **c,
            },
        )
    conn.commit()
    conn.close()


def _make_graph(path: Path, links: list[dict]) -> None:
    path.write_text(json.dumps(links))


def _seed_user(tmp_path: Path) -> Path:
    user_dir = tmp_path / "user1"
    user_dir.mkdir()
    last = datetime(2026, 6, 1, 12, 0, tzinfo=UTC).strftime("%Y-%m-%d %H:%M:%S.%f")
    created = datetime(2026, 3, 1, 9, 0, tzinfo=UTC).strftime("%Y-%m-%d %H:%M:%S.%f")
    _make_cards_db(user_dir / "cards.db", [
        {"id": "cardA", "content": "alpha", "created_at": created,
         "last_reviewed_at": last, "review_count": 5, "review_streak": 5},
        {"id": "cardB", "content": "beta", "created_at": created,
         "last_reviewed_at": last, "review_count": 3, "lapse_count": 1,
         "review_streak": 1},
        {"id": "cardC", "content": "never", "created_at": created,
         "last_reviewed_at": None, "review_count": 0, "review_streak": 0},
    ])
    born = datetime(2026, 4, 1, 9, 0, tzinfo=UTC).isoformat()
    _make_graph(user_dir / "graph_default.json", [
        {"id": "lk1", "from_id": "cardA", "to_id": "cardB", "kind": "shares_usage",
         "confidence": 0.8, "reason": "r", "created_at": born, "status": "active"},
        {"id": "lk2", "from_id": "cardB", "to_id": "cardA", "kind": "contrasts_with",
         "confidence": 0.6, "reason": "r", "created_at": born, "status": "hidden"},
    ])
    return user_dir


def test_dry_run_reports_without_writing(tmp_path):
    user_dir = _seed_user(tmp_path)
    report = migrate_user(user_dir, apply=False)
    assert report.dry_run is True
    assert report.review_events_synthesized == 8   # 5 + 3 (cardC has 0)
    assert report.graph_events_synthesized == 3    # active=1 + hidden=2
    assert not (user_dir / "graph_events.db").exists()  # dry-run 不建檔
    assert report.backups == []


def test_apply_plants_synthetic_review_history(tmp_path):
    user_dir = _seed_user(tmp_path)
    migrate_user(user_dir, apply=True)
    store = ReviewEventStore(user_dir / "review_events.db")
    pulled, _ = pull_review_events(since=None, event_store=store)
    assert len(pulled) == 8
    assert all(e.is_synthetic for e in pulled)
    # 每卡事件數 == review_count
    by_card: dict[str, int] = {}
    for e in pulled:
        by_card[e.card_id] = by_card.get(e.card_id, 0) + 1
    assert by_card == {"cardA": 5, "cardB": 3}


def test_apply_plants_synthetic_graph_history(tmp_path):
    user_dir = _seed_user(tmp_path)
    migrate_user(user_dir, apply=True)
    store = GraphEventStore(user_dir / "graph_events.db")
    events = store.all()
    assert len(events) == 3
    assert all(e.is_synthetic for e in events)
    link_ids = {e.link_id for e in events}
    assert link_ids == {"lk1", "lk2"}                       # == 終態 link 集合
    added = [e for e in events if e.event_type == GraphEventType.LINK_ADDED]
    assert {e.link_id for e in added} == {"lk1", "lk2"}     # 每條 ≥1 add


def test_apply_takes_initial_synthetic_snapshot(tmp_path):
    user_dir = _seed_user(tmp_path)
    report = migrate_user(user_dir, apply=True)
    assert report.graph_snapshots_taken == 1
    snap = GraphSnapshotStore(user_dir / "graph_events.db").latest("default")
    assert snap is not None
    assert snap.is_synthetic is True
    assert snap.link_count == 2                       # 終態 2 links (lk1, lk2)
    assert {lk["id"] for lk in snap.links} == {"lk1", "lk2"}


def test_re_migration_does_not_stack_snapshots(tmp_path):
    user_dir = _seed_user(tmp_path)
    first = migrate_user(user_dir, apply=True)
    second = migrate_user(user_dir, apply=True)
    assert first.graph_snapshots_taken == 1
    assert second.graph_snapshots_taken == 0          # 已有 → 不重複堆疊
    snaps = GraphSnapshotStore(user_dir / "graph_events.db").all(notebook_id="default")
    assert len(snaps) == 1


def test_apply_purges_old_review_event_junk(tmp_path):
    user_dir = _seed_user(tmp_path)
    # 預先放一筆舊垃圾(card_id NULL 的歷史殘留)
    pre = ReviewEventStore(user_dir / "review_events.db")
    from kg.api_models.review import ReviewEventEntry
    from kg.review_events import push_review_events
    push_review_events([ReviewEventEntry(
        event_id="legacy-junk-1", card_id=None, word_snapshot="(跨裝置同步)",
        notebook_id="default", feedback=1,
        reviewed_at=datetime(2025, 1, 1, tzinfo=UTC).isoformat(),
        created_at=datetime(2025, 1, 1, tzinfo=UTC).isoformat(),
    )], event_store=pre)
    pre.engine.dispose()

    report = migrate_user(user_dir, apply=True)
    assert report.review_events_old_purged == 1
    store = ReviewEventStore(user_dir / "review_events.db")
    pulled, _ = pull_review_events(since=None, event_store=store)
    assert all(e.is_synthetic for e in pulled)        # 垃圾沒了,只剩合成
    assert not any(e.card_id is None for e in pulled)


def test_apply_backs_up_existing_review_events_once(tmp_path):
    user_dir = _seed_user(tmp_path)
    (user_dir / "review_events.db").write_bytes(b"ORIGINAL")  # 假裝既有檔
    migrate_user(user_dir, apply=True)
    bak = user_dir / "review_events.db.premigration.bak"
    assert bak.exists()
    assert bak.read_bytes() == b"ORIGINAL"
    # 二次遷移不可用合成後的 db 覆蓋原始備份
    migrate_user(user_dir, apply=True)
    assert bak.read_bytes() == b"ORIGINAL"


def test_apply_is_idempotent(tmp_path):
    user_dir = _seed_user(tmp_path)
    first = migrate_user(user_dir, apply=True)
    second = migrate_user(user_dir, apply=True)
    assert first.review_events_synthesized == second.review_events_synthesized == 8
    assert first.graph_events_synthesized == second.graph_events_synthesized == 3
    # 事件總數不因重跑膨脹
    store = GraphEventStore(user_dir / "graph_events.db")
    assert len(store.all()) == 3


def test_review_events_strictly_increasing_per_card(tmp_path):
    user_dir = _seed_user(tmp_path)
    migrate_user(user_dir, apply=True)
    store = ReviewEventStore(user_dir / "review_events.db")
    pulled, _ = pull_review_events(since=None, event_store=store)
    per_card: dict[str, list[str]] = {}
    for e in pulled:
        per_card.setdefault(e.card_id, []).append(e.reviewed_at)
    for times in per_card.values():
        parsed = sorted(datetime.fromisoformat(t) for t in times)
        assert len(set(parsed)) == len(parsed)  # 嚴格遞增 → 全相異


def _legacy_review_db(path: Path) -> None:
    """建一個 pre-widen schema 的 review_events.db(無 ingested_at/SRS/is_synthetic),
    塞一筆舊垃圾。用來驗 dry-run 不得改 schema。"""
    conn = sqlite3.connect(path)
    conn.execute(
        """CREATE TABLE reviewevent (
            event_id TEXT PRIMARY KEY, card_id TEXT, word_snapshot TEXT,
            notebook_id TEXT, feedback INTEGER, reviewed_at DATETIME, created_at DATETIME)"""
    )
    conn.execute(
        "INSERT INTO reviewevent VALUES ('junk-1', NULL, '(同步)', 'default', 1, "
        "'2025-01-01T00:00:00+00:00', '2025-01-01T00:00:00+00:00')"
    )
    conn.commit()
    conn.close()


def _review_columns(path: Path) -> set[str]:
    conn = sqlite3.connect(path)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(reviewevent)").fetchall()}
    conn.close()
    return cols


def test_dry_run_does_not_mutate_review_db(tmp_path):
    """dry-run「只報告不寫」:不得 ALTER TABLE / 建備份 / 改既有列。"""
    user_dir = _seed_user(tmp_path)
    review_db = user_dir / "review_events.db"
    _legacy_review_db(review_db)
    before = _review_columns(review_db)
    report = migrate_user(user_dir, apply=False)
    after = _review_columns(review_db)
    assert before == after  # schema 未被 probe 改動
    assert "is_synthetic" not in after and "ingested_at" not in after
    assert not (user_dir / "review_events.db.premigration.bak").exists()
    assert report.review_events_old_purged == 1  # 仍正確計數(唯讀)


def test_rerun_apply_preserves_real_events(tmp_path):
    """二次 apply 不得銷毀首次遷移後 iOS 推入的真實(is_synthetic=False)事件。"""
    from kg.api_models.review import ReviewEventEntry
    from kg.review_events import push_review_events

    user_dir = _seed_user(tmp_path)
    migrate_user(user_dir, apply=True)  # 首次:備份 + wipe 垃圾 + 種合成

    # 模擬上線後 iOS 推入真實事件
    store = ReviewEventStore(user_dir / "review_events.db")
    push_review_events([ReviewEventEntry(
        event_id="real-ios-1", card_id="cardA", word_snapshot="alpha",
        notebook_id="default", feedback=1,
        reviewed_at=datetime(2026, 6, 5, tzinfo=UTC).isoformat(),
        created_at=datetime(2026, 6, 5, tzinfo=UTC).isoformat(),
        is_synthetic=False,
    )], event_store=store)
    store.engine.dispose()

    migrate_user(user_dir, apply=True)  # 二次:不得銷毀 real-ios-1

    store2 = ReviewEventStore(user_dir / "review_events.db")
    pulled, _ = pull_review_events(since=None, event_store=store2)
    import uuid as _uuid
    ids = {e.event_id for e in pulled}
    assert "real-ios-1" in ids                  # 真實事件保住
    assert any(e.is_synthetic for e in pulled)  # 合成仍在
    # 合成 id 為合法 UUID(iOS 不會丟棄)
    for e in pulled:
        if e.is_synthetic:
            _uuid.UUID(e.event_id)


def test_rerun_does_not_purge_card_id_null_events_after_first_migration(tmp_path):
    """上線後 re-run 不得刪 card_id NULL 事件 —— 此時它可能是 word-only fallback 的真實複習,
    非同步殘渣。purge 僅限首次遷移(上線前,card_id NULL 必為殘渣)。"""
    from kg.api_models.review import ReviewEventEntry
    from kg.review_events import push_review_events

    user_dir = _seed_user(tmp_path)
    migrate_user(user_dir, apply=True)  # 首次遷移(設下 marker)

    # 上線後:一筆 card_id NULL 但真實的 word-only 複習(正是本 PR 別處在修的 nil-card-id 類)
    store = ReviewEventStore(user_dir / "review_events.db")
    push_review_events([ReviewEventEntry(
        event_id="legacy-real-nullcard", card_id=None, word_snapshot="serendipity",
        notebook_id="default", feedback=1,
        reviewed_at=datetime(2026, 6, 6, tzinfo=UTC).isoformat(),
        created_at=datetime(2026, 6, 6, tzinfo=UTC).isoformat(),
        is_synthetic=False,
    )], event_store=store)
    store.engine.dispose()

    migrate_user(user_dir, apply=True)  # 二次遷移:不得 purge 該真實事件

    store2 = ReviewEventStore(user_dir / "review_events.db")
    pulled, _ = pull_review_events(since=None, event_store=store2)
    assert "legacy-real-nullcard" in {e.event_id for e in pulled}


def test_multiple_notebooks_are_all_migrated(tmp_path):
    user_dir = tmp_path / "u"
    user_dir.mkdir()
    last = datetime(2026, 6, 1, 12, 0, tzinfo=UTC).strftime("%Y-%m-%d %H:%M:%S.%f")
    created = datetime(2026, 3, 1, 9, 0, tzinfo=UTC).strftime("%Y-%m-%d %H:%M:%S.%f")
    _make_cards_db(user_dir / "cards.db", [
        {"id": "c1", "content": "a", "notebook_id": "default", "created_at": created,
         "last_reviewed_at": last, "review_count": 2, "review_streak": 2},
        {"id": "c2", "content": "b", "notebook_id": "work", "created_at": created,
         "last_reviewed_at": last, "review_count": 3, "review_streak": 3},
    ])
    born = datetime(2026, 4, 1, 9, 0, tzinfo=UTC).isoformat()
    _make_graph(user_dir / "graph_default.json", [
        {"id": "L1", "from_id": "c1", "to_id": "c1", "kind": "shares_usage",
         "confidence": 0.5, "reason": "r", "created_at": born, "status": "active"}])
    _make_graph(user_dir / "graph_work.json", [
        {"id": "L2", "from_id": "c2", "to_id": "c2", "kind": "shares_usage",
         "confidence": 0.5, "reason": "r", "created_at": born, "status": "active"}])
    report = migrate_user(user_dir, apply=True)
    assert sorted(report.notebooks) == ["default", "work"]
    assert report.review_events_synthesized == 5   # 2 + 3
    assert report.graph_events_synthesized == 2    # L1 + L2
    store = GraphEventStore(user_dir / "graph_events.db")
    nbs = {e.notebook_id for e in store.all()}
    assert nbs == {"default", "work"}
