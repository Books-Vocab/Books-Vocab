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
    assert all(e.word_snapshot == "ephemeral" for e in events)
    assert all(e.notebook_id == "nbk" for e in events)
    assert all(e.card_id == "abc123" for e in events)


def test_event_ids_are_valid_uuids():
    """合成 review event_id 必須是合法 UUID,否則 iOS mergeReviewEvents 的
    UUID(uuidString:) guard 會整批丟棄合成複習史(#2)。仍須確定式 + 唯一。"""
    import uuid

    card = _state(review_count=5, card_id="abc123")
    events = synthesize_review_events(card)
    for e in events:
        parsed = uuid.UUID(e.event_id)  # 非法 → ValueError
        assert str(parsed) == e.event_id  # 規範化 36 字元含連字號形式
    # 確定式:重跑同卡 → 同 id(經 event_id 去重而冪等)
    again = synthesize_review_events(card)
    assert [e.event_id for e in events] == [e.event_id for e in again]
    # 不同卡 → 不同 id 空間
    other = synthesize_review_events(_state(review_count=5, card_id="xyz789"))
    assert set(e.event_id for e in events).isdisjoint(e.event_id for e in other)


def test_final_srs_snapshot_matches_stored_aggregate_on_contradiction():
    """末筆 streak_after/lapse_after 必須錨定卡片儲存聚合 —— 即使聚合矛盾
    (streak=0 但 last_feedback=1,real data 罕見)。否則逐筆回放末態 != 卡片現狀,
    污染本 PR 新增的研究欄(#10)。"""
    card = _state(review_count=4, lapse_count=2, review_streak=0, last_review_feedback=1)
    events = synthesize_review_events(card)
    assert events[-1].streak_after == 0   # == card.review_streak
    assert events[-1].lapse_after == 2    # == card.lapse_count


def test_final_srs_snapshot_matches_stored_aggregate_consistent():
    """一致聚合下 clamp 為 no-op:末態本就 == 聚合。"""
    card = _state(review_count=5, lapse_count=0, review_streak=5, last_review_feedback=1)
    events = synthesize_review_events(card)
    assert events[-1].streak_after == 5
    assert events[-1].lapse_after == 0


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


# ── review 補強:naive 輸入 / 壓縮相異性 / 退化 / streak 語意 / sentinel ──


def test_naive_timestamps_are_normalized_and_accepted_by_store(tmp_path):
    """來源 cards.db 存 naive timestamp;合成必須產出 tz-aware ISO 並能寫進 store。"""
    naive_last = datetime(2026, 6, 2, 16, 0)            # 無 tzinfo(模擬 sqlite 讀出)
    naive_created = datetime(2026, 3, 1, 8, 0)
    events = synthesize_review_events(
        _state(review_count=5, last_reviewed_at=naive_last, created_at=naive_created)
    )
    for e in events:
        ts = datetime.fromisoformat(e.reviewed_at)
        assert ts.tzinfo is not None
        assert datetime.fromisoformat(e.created_at).tzinfo is not None
    # 真正寫進 store(會跑 _parse_required_timestamp 的 tz-aware 驗證)
    store = ReviewEventStore(tmp_path / "review_events.db")
    res = push_review_events(events, event_store=store)
    assert res["inserted"] == 5


def test_mixed_naive_aware_does_not_raise():
    # naive created + aware last:不可 TypeError(相減前已正規化)。
    events = synthesize_review_events(
        _state(review_count=4,
               last_reviewed_at=datetime(2026, 6, 2, 16, 0, tzinfo=UTC),
               created_at=datetime(2026, 3, 1, 8, 0))
    )
    assert len(events) == 4


def test_heavy_compression_keeps_all_events_distinct_and_monotonic():
    # 大 N + 極窄視窗 + 大 interval:仍須 N 筆相異、嚴格遞增、末筆錨定。
    last = datetime(2026, 6, 2, 16, 0, tzinfo=UTC)
    created = last - timedelta(minutes=33)
    events = synthesize_review_events(
        _state(review_count=50, last_reviewed_at=last, created_at=created,
               review_interval_hours=1_000_000.0, card_id="dense")
    )
    times = [datetime.fromisoformat(e.reviewed_at) for e in events]
    assert len(times) == 50
    assert len(set(times)) == 50            # 無撞點(否則 heatmap 分佈失真)
    assert times == sorted(times)
    assert times[-1] == last


def test_degenerate_created_after_last_still_anchored_distinct_increasing():
    # created ≥ last(異常資料):末筆仍精確錨定、N 筆相異且嚴格遞增。
    last = datetime(2026, 6, 2, 16, 0, tzinfo=UTC)
    created = last + timedelta(hours=1)      # 建卡晚於末次複習(異常)
    events = synthesize_review_events(
        _state(review_count=6, last_reviewed_at=last, created_at=created)
    )
    times = [datetime.fromisoformat(e.reviewed_at) for e in events]
    assert len(set(times)) == 6
    assert times == sorted(times)
    assert times[-1] == last


def test_streak_breaker_is_a_lapse_so_event_streak_matches_stored():
    # streak>0 + 有 lapse:緊鄰 good 尾的那筆必為 lapse,事件回推 streak == 儲存值。
    events = synthesize_review_events(
        _state(review_count=6, lapse_count=1, review_streak=3, last_review_feedback=1)
    )
    fb = [e.feedback for e in events]
    assert fb[-3:] == [1, 1, 1]              # good 尾長度 == streak
    assert fb[-4] == 0                        # 打斷 streak 的那筆是 lapse
    assert fb.count(0) == 1


def test_streak_zero_last_feedback_mirrored_even_without_lapses():
    # 矛盾聚合 (streak=0, lapse=0, F=0):末筆仍鏡射 F=0(顯著維度優先)。
    events = synthesize_review_events(
        _state(review_count=3, lapse_count=0, review_streak=0, last_review_feedback=0)
    )
    assert [e.feedback for e in events][-1] == 0


def test_stale_streak_greater_than_count_is_clamped():
    # review_streak > review_count(髒資料):clamp 後全 good,不崩。
    events = synthesize_review_events(
        _state(review_count=3, lapse_count=1, review_streak=9, last_review_feedback=1)
    )
    assert [e.feedback for e in events] == [1, 1, 1]


def test_never_feedback_sentinel_only_emits_zero_or_one():
    # last_review_feedback=-1(從未評分):輸出只能是 0/1,符合 store 的 ge=0,le=1。
    events = synthesize_review_events(
        _state(review_count=4, lapse_count=1, review_streak=0, last_review_feedback=-1)
    )
    assert all(e.feedback in (0, 1) for e in events)


# ── Phase 3a:SRS 前後快照 + is_synthetic(供圖譜/複習史回溯研究)──


def test_all_synthetic_events_carry_synthetic_flag():
    events = synthesize_review_events(_state(review_count=5))
    assert all(e.is_synthetic is True for e in events)


def test_review_count_after_is_one_based_running_index():
    events = synthesize_review_events(_state(review_count=6))
    assert [e.review_count_after for e in events] == [1, 2, 3, 4, 5, 6]


def test_streak_and_lapse_after_match_stored_aggregate_at_end():
    card = _state(review_count=6, lapse_count=2, review_streak=3, last_review_feedback=1)
    events = synthesize_review_events(card)
    # 逐筆回放的末態必須 == 卡片儲存聚合(事件自包含、可獨立還原卡況)。
    assert events[-1].streak_after == 3
    assert events[-1].lapse_after == 2


def test_streak_after_resets_on_lapse_and_counts_consecutive_good():
    # fb = [1,0,1,1] → streak_after = [1,0,1,2];lapse_after = [0,1,1,1]。
    card = _state(review_count=4, lapse_count=1, review_streak=2, last_review_feedback=1)
    events = synthesize_review_events(card)
    assert [e.feedback for e in events] == [1, 0, 1, 1]
    assert [e.streak_after for e in events] == [1, 0, 1, 2]
    assert [e.lapse_after for e in events] == [0, 1, 1, 1]


def test_interval_before_chains_from_previous_after():
    events = synthesize_review_events(_state(review_count=5))
    for prev, cur in zip(events, events[1:], strict=False):
        assert cur.interval_before == prev.interval_after


def test_first_interval_before_is_srs_initial():
    events = synthesize_review_events(_state(review_count=3))
    assert events[0].interval_before == 12.0  # ReviewSettings.default initial


def test_last_interval_after_is_anchored_to_card_interval():
    card = _state(review_count=5, review_interval_hours=240.0)
    events = synthesize_review_events(card)
    assert events[-1].interval_after == 240.0


def test_interval_after_within_srs_bounds_except_anchor():
    card = _state(review_count=8, lapse_count=3, review_interval_hours=240.0)
    events = synthesize_review_events(card)
    for e in events[:-1]:  # 末筆是 anchor,不受 clamp 約束
        assert 6.0 <= e.interval_after <= 1440.0


def test_next_review_after_equals_reviewed_plus_interval():
    events = synthesize_review_events(_state(review_count=4))
    for e in events:
        reviewed = datetime.fromisoformat(e.reviewed_at)
        nxt = datetime.fromisoformat(e.next_review_after)
        delta_hours = (nxt - reviewed).total_seconds() / 3600.0
        assert abs(delta_hours - e.interval_after) < 1e-6


def test_next_review_before_chains_and_first_is_none():
    events = synthesize_review_events(_state(review_count=4))
    assert events[0].next_review_before is None
    for prev, cur in zip(events, events[1:], strict=False):
        assert cur.next_review_before == prev.next_review_after


def test_srs_snapshots_survive_store_round_trip(tmp_path):
    store = ReviewEventStore(tmp_path / "review_events.db")
    card = _state(review_count=5, lapse_count=1, review_streak=2,
                  review_interval_hours=240.0, card_id="srs")
    push_review_events(synthesize_review_events(card), event_store=store)
    pulled, _ = pull_review_events(since=None, event_store=store)
    pulled.sort(key=lambda e: e.reviewed_at)
    assert all(e.is_synthetic is True for e in pulled)
    assert [e.review_count_after for e in pulled] == [1, 2, 3, 4, 5]
    assert pulled[-1].interval_after == 240.0
    assert pulled[-1].streak_after == 2
    assert pulled[-1].lapse_after == 1
