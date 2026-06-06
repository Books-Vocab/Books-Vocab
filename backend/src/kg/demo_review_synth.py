"""demo_review_synth.py — 把卡片複習聚合欄位確定式展開成逐筆 ReviewEvent。

來源 demo 帳號的 cards.db 只保留複習「聚合」(review_count / lapse_count /
review_streak / last_reviewed_at / last_review_feedback / review_interval_hours),
不存逐筆 review event。clone demo 帳號時需要逐筆事件來餵 iOS 的 heatmap / streak /
180 天 activity。本 module 為純函式、無副作用、確定式:

* **數量** = review_count。
* **feedback 序列**與 streak/lapse 自洽:末 review_streak 筆為 good(1),其餘
  review_count-review_streak 筆中恰好 lapse_count 筆為 lapse(0);streak=0 且末次
  feedback=0 時強制最後一筆為 lapse。
* **時間**錨定真實 last_reviewed_at 往過去回推,間隔依 SRS 慣例遞增(越早差距越大),
  超出 created_at..last_reviewed_at 視窗則等比壓縮;嚴格遞增、不早於 created_at。
* **event_id** = ``demo-<card_id>-<chronological_index>`` → 穩定;重跑經 store 的
  event_id 去重而冪等。

刻意不用 RNG —— 跨卡 heatmap 多樣性來自每張卡相異的真實 anchor/N/interval,
不需注入隨機,且保證確定式重跑。
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import timedelta, datetime

from .api_models.review import ReviewEventEntry

# SRS 間隔向過去回推的成長係數(越早的複習間隔越小)。約 1.7 ≈ SuperMemo ease 區間。
_INTERVAL_GROWTH = 1.7
# 最近一次複習間隔的下限(小時):interval_hours 過小時仍給事件可辨識的日間距。
_MIN_RECENT_GAP_HOURS = 8.0
# 壓縮視窗時保留的安全邊際(小時),確保最早事件嚴格晚於 created_at。
_WINDOW_EPSILON_HOURS = 0.5


@dataclass(frozen=True)
class CardReviewState:
    """單張卡的複習聚合(由 cards.db 一列投影而來)。"""

    card_id: str
    content: str
    notebook_id: str
    review_count: int
    lapse_count: int
    review_streak: int
    last_review_feedback: int
    last_reviewed_at: datetime | None
    created_at: datetime
    review_interval_hours: float


def _even_positions(span: int, count: int) -> list[int]:
    """在 [0, span) 取 count 個盡量均勻分散且相異的整數位置(置中)。"""
    if count <= 0 or span <= 0:
        return []
    count = min(count, span)
    return sorted({(2 * i + 1) * span // (2 * count) for i in range(count)})


def _feedback_sequence(n: int, lapses: int, streak: int, last_feedback: int) -> list[int]:
    """長度 n 的 0/1 序列(index 0 最舊)。末 streak 筆為 1;前段散佈 lapses 個 0。"""
    streak = max(0, min(streak, n))
    pre_len = n - streak
    lapses = max(0, min(lapses, pre_len))
    fb = [1] * n
    zero_positions = set(_even_positions(pre_len, lapses))
    # streak=0 且末次為 lapse:保證最後一筆落在 0,否則 last_feedback 與序列不符。
    if (
        streak == 0
        and last_feedback == 0
        and lapses >= 1
        and (pre_len - 1) not in zero_positions
    ):
        if zero_positions:
            zero_positions.discard(max(zero_positions))
        zero_positions.add(pre_len - 1)
    for pos in zero_positions:
        fb[pos] = 0
    return fb


def _backward_cumulative_offsets(n: int, recent_gap_hours: float) -> list[float]:
    """長度 n 的累積小時 offset,index 0 = 最舊(最大 offset),index n-1 = 0(末次)。

    從末次往過去回推,相鄰間隔依 _INTERVAL_GROWTH 遞增(越早差距越大)。
    """
    cum_new_to_old = [0.0]
    for k in range(1, n):
        gap = recent_gap_hours * (_INTERVAL_GROWTH ** (k - 1))
        cum_new_to_old.append(cum_new_to_old[-1] + gap)
    return [cum_new_to_old[n - 1 - i] for i in range(n)]


def _timestamps(card: CardReviewState) -> list[datetime]:
    n = card.review_count
    last = card.last_reviewed_at
    assert last is not None and n > 0
    if n == 1:
        return [last]
    recent_gap = max(card.review_interval_hours / _INTERVAL_GROWTH, _MIN_RECENT_GAP_HOURS)
    offsets = _backward_cumulative_offsets(n, recent_gap)  # 最舊在前
    span_hours = offsets[0]
    available = (last - card.created_at).total_seconds() / 3600.0 - _WINDOW_EPSILON_HOURS
    if available > 0 and span_hours > available:
        scale = available / span_hours
        offsets = [o * scale for o in offsets]
    elif available <= 0:
        # created_at 不早於 last(異常):退化為每筆 1h 等距,仍嚴格遞增。
        offsets = [float(n - 1 - i) for i in range(n)]
    return [last - timedelta(hours=o) for o in offsets]


def synthesize_review_events(card: CardReviewState) -> list[ReviewEventEntry]:
    """把單張卡的複習聚合展開成 review_count 筆 ReviewEventEntry(最舊在前)。"""
    n = card.review_count
    if n <= 0 or card.last_reviewed_at is None:
        return []
    fb = _feedback_sequence(n, card.lapse_count, card.review_streak, card.last_review_feedback)
    times = _timestamps(card)
    events: list[ReviewEventEntry] = []
    for i in range(n):
        iso = times[i].isoformat()
        events.append(
            ReviewEventEntry(
                event_id=f"demo-{card.card_id}-{i}",
                card_id=card.card_id,
                word_snapshot=card.content,
                notebook_id=card.notebook_id,
                feedback=fb[i],
                reviewed_at=iso,
                created_at=iso,
            )
        )
    return events


def synthesize_many(cards: Iterable[CardReviewState]) -> list[ReviewEventEntry]:
    """多張卡的合成攤平成單一事件序列。"""
    out: list[ReviewEventEntry] = []
    for card in cards:
        out.extend(synthesize_review_events(card))
    return out
