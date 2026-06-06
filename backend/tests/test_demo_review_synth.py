"""demo_review_synth 單元測試 — 從卡片複習聚合欄位重建逐筆 review event 的演算法護欄。

來源帳號 cards.db 只存複習「聚合」(review_count / lapse_count / review_streak /
last_reviewed_at / last_review_feedback),不存逐筆事件。要讓 demo 帳號的 iOS
heatmap / streak / 180 天 activity 有料,必須把聚合**確定式**展開成 N 筆事件:
時間錨定真實 last_reviewed_at 反推、feedback 序列與 streak/lapse 自洽、event_id
依索引穩定 → 重跑冪等(store 以 event_id 去重)。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from kg.demo_review_synth import CardReviewState, synthesize_review_events
from kg.review_events import ReviewEventStore, pull_review_events, push_review_events


_UNSET = object()


def _state(
    *,
    review_count: int,
    lapse_count: int = 0,
    review_streak: int | None = None,
    last_review_feedback: int = 1,
    last_reviewed_at=_UNSET,  # _UNSET=用預設;顯式 None=測缺值路徑
    created_at: datetime | None = None,
    review_interval_hours: float = 96.0,
    card_id: str = "card-1",
    content: str = "serendipity",
    notebook_id: str = "default",
) -> CardReviewState:
    last = datetime(2026, 6, 2, 16, 0, tzinfo=UTC) if last_reviewed_at is _UNSET else last_reviewed_at
    created = created_at or ((last or datetime(2026, 6, 2, 16, 0, tzinfo=UTC)) - timedelta(days=60))
    streak = review_streak if review_streak is not None else review_count
    return CardReviewState(
        card_id=card_id,
        content=content,
        notebook_id=notebook_id,
        review_count=review_count,
        lapse_count=lapse_count,
        review_streak=streak,
        last_review_feedback=last_review_feedback,
        last_reviewed_at=last,
        created_at=created,
        review_interval_hours=review_interval_hours,
    )


def test_event_count_equals_review_count():
    events = synthesize_review_events(_state(review_count=5))
    assert len(events) == 5


def test_zero_review_count_yields_no_events():
    assert synthesize_review_events(_state(review_count=0)) == []


def test_missing_last_reviewed_yields_no_events():
    assert synthesize_review_events(_state(review_count=4, last_reviewed_at=None)) == []


def test_feedback_sequence_is_consistent_with_streak_and_lapses():
    # N=5, 1 lapse, current streak 2, 末次 good。
    events = synthesize_review_events(
        _state(review_count=5, lapse_count=1, review_streak=2, last_review_feedback=1)
    )
    fb = [e.feedback for e in events]
    assert fb.count(0) == 1, fb            # 恰好 lapse_count 個 0
    assert fb[-2:] == [1, 1], fb           # 末 streak 筆皆 good
    assert fb[-1] == 1                      # 末次 == last_review_feedback


def test_all_good_when_no_lapses():
    events = synthesize_review_events(_state(review_count=4, lapse_count=0, review_streak=4))
    assert [e.feedback for e in events] == [1, 1, 1, 1]


def test_last_event_is_lapse_when_streak_zero_and_last_feedback_bad():
    # streak=0 + 末次 feedback=0:最後一筆必須是 lapse。
    events = synthesize_review_events(
        _state(review_count=3, lapse_count=1, review_streak=0, last_review_feedback=0)
    )
    fb = [e.feedback for e in events]
    assert fb[-1] == 0, fb
    assert fb.count(0) == 1, fb


def test_timestamps_strictly_increasing_tz_aware_anchored_to_last_reviewed():
    last = datetime(2026, 6, 2, 16, 18, 35, tzinfo=UTC)
    created = datetime(2026, 3, 24, 7, 46, tzinfo=UTC)
    events = synthesize_review_events(
        _state(review_count=6, last_reviewed_at=last, created_at=created)
    )
    times = [datetime.fromisoformat(e.reviewed_at) for e in events]
    assert all(t.tzinfo is not None for t in times)
    assert times == sorted(times)
    assert len(set(times)) == len(times)          # 嚴格遞增 → 全相異
    assert times[-1] == last                       # 錨定真實末次複習
    assert times[0] >= created                      # 不早於建卡


def test_created_at_field_is_tz_aware_iso():
    events = synthesize_review_events(_state(review_count=3))
    for e in events:
        ts = datetime.fromisoformat(e.created_at)
        assert ts.tzinfo is not None


def test_event_ids_unique_stable_and_carry_card_metadata():
    card = _state(review_count=5, card_id="abc123", content="ephemeral", notebook_id="nbk")
    events = synthesize_review_events(card)
    ids = [e.event_id for e in events]
    assert len(set(ids)) == 5
    assert all(eid.startswith("demo-abc123-") for eid in ids)
    assert all(e.word_snapshot == "ephemeral" for e in events)
    assert all(e.notebook_id == "nbk" for e in events)
    assert all(e.card_id == "abc123" for e in events)


def test_deterministic_across_calls():
    card = _state(review_count=7, lapse_count=2, review_streak=3, card_id="det-1")
    a = synthesize_review_events(card)
    b = synthesize_review_events(card)
    assert [(e.event_id, e.feedback, e.reviewed_at) for e in a] == [
        (e.event_id, e.feedback, e.reviewed_at) for e in b
    ]


def test_short_window_compresses_without_violating_monotonicity():
    # 大 N 但 created→last 視窗很窄:必須壓縮間隔且仍嚴格遞增、不早於 created。
    last = datetime(2026, 6, 2, 16, 0, tzinfo=UTC)
    created = last - timedelta(hours=30)
    events = synthesize_review_events(
        _state(review_count=12, last_reviewed_at=last, created_at=created,
               review_interval_hours=720.0)
    )
    times = [datetime.fromisoformat(e.reviewed_at) for e in events]
    assert times == sorted(times)
    assert len(set(times)) == 12
    assert times[0] >= created
    assert times[-1] == last


def test_round_trips_through_review_event_store(tmp_path):
    store = ReviewEventStore(tmp_path / "review_events.db")
    cards = [
        _state(review_count=5, card_id="c1", content="alpha"),
        _state(review_count=3, lapse_count=1, review_streak=1, card_id="c2", content="beta"),
    ]
    total = 0
    for card in cards:
        events = synthesize_review_events(card)
        total += len(events)
        push_review_events(events, event_store=store)

    pulled, cursor = pull_review_events(since=None, event_store=store)
    assert len(pulled) == total == 8
    assert cursor is not None


def test_re_synth_and_repush_is_idempotent(tmp_path):
    store = ReviewEventStore(tmp_path / "review_events.db")
    card = _state(review_count=6, card_id="idem")
    first = push_review_events(synthesize_review_events(card), event_store=store)
    second = push_review_events(synthesize_review_events(card), event_store=store)
    assert first["inserted"] == 6
    assert second["inserted"] == 0      # 重跑全被 event_id 去重
    assert second["skipped"] == 6
