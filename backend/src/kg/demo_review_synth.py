"""demo_review_synth.py — 把卡片複習聚合欄位確定式展開成逐筆 ReviewEvent。

來源 demo 帳號的 cards.db 只保留複習「聚合」(review_count / lapse_count /
review_streak / last_reviewed_at / last_review_feedback / review_interval_hours),
不存逐筆 review event。clone demo 帳號時需要逐筆事件來餵 iOS 的 heatmap / streak /
180 天 activity。本 module 為純函式、無副作用、確定式:

* **數量** = review_count。
* **feedback 序列**與 streak/lapse 自洽:末 review_streak 筆為 good(1);打斷 streak 的
  那一筆(緊鄰 good 尾)為 lapse(0),其餘 lapse 散佈於更早;streak=0 時末筆 feedback
  鏡射 last_review_feedback(∈{0,1})。事件回推的「當前 streak」因此 == 儲存的 streak。
* **時間**錨定真實 last_reviewed_at(末筆精確等於它),往過去映射到 created_at..last
  視窗,間隔依 SRS 慣例越早越大;保證嚴格遞增(µs 級夾),視窗異常(created≥last)時
  退化為自末次往前 µs 堆疊。輸入 timestamp 一律先正規化為 tz-aware UTC(來源 cards.db
  存 naive 'YYYY-MM-DD HH:MM:SS.ffffff',若不轉 store 會拒收)。
* **event_id** = ``demo-<card_id>-<chronological_index>`` → 穩定;重跑經 store 的
  event_id 去重而冪等。

刻意不用 RNG —— 跨卡 heatmap 多樣性來自每張卡相異的真實 anchor/N/interval,
不需注入隨機,且保證確定式重跑。
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

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


def _as_utc(dt: datetime | None) -> datetime | None:
    """正規化為 tz-aware UTC。naive(來源 cards.db 格式)視為 UTC;aware 轉 UTC。

    不轉的話 isoformat() 出 naive 字串,review_events store 的
    `_parse_required_timestamp` 會逐筆 BadRequestError;naive/aware 相減亦會 TypeError。
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _feedback_sequence(n: int, lapses: int, streak: int, last_feedback: int) -> list[int]:
    """長度 n 的 0/1 序列(index 0 最舊)。

    末 streak 筆為 good(1);打斷 streak 的那筆(緊鄰 good 尾, index pre_len-1)記為
    lapse,其餘 lapse 散佈於更早 → 事件回推的「當前 streak」== 儲存的 review_streak。
    streak=0 時末筆鏡射 last_review_feedback(∈{0,1}),使 iOS 顯示的末次結果一致;
    last_feedback=-1(從未評分的 sentinel)維持原均勻散佈(只會產生 0/1,不外洩 -1)。

    註:遇 (streak>0, last_feedback=0) 或 (streak=0, lapse_count=0, last_feedback=0)
    這類矛盾聚合,以較顯著的維度為準(streak>0 時信 streak;streak=0 時信 last_feedback),
    可能讓 0 的筆數與 lapse_count 差 1。真實資料這類矛盾極罕見。
    """
    streak = max(0, min(streak, n))
    pre_len = n - streak
    lapses = max(0, min(lapses, pre_len))
    fb = [1] * n
    if streak > 0:
        if lapses >= 1:
            breaker = pre_len - 1            # 緊鄰 good 尾的那筆 = 打斷 streak 的 lapse
            fb[breaker] = 0
            for pos in _even_positions(breaker, lapses - 1):
                fb[pos] = 0
        return fb
    # streak == 0:末筆即 index n-1,須鏡射 last_feedback。
    positions = set(_even_positions(pre_len, lapses))
    last_idx = n - 1
    if last_feedback == 0 and last_idx not in positions:
        if positions:
            positions.discard(max(positions))
        positions.add(last_idx)
    elif last_feedback == 1 and last_idx in positions:
        positions.discard(last_idx)
        for pos in _even_positions(last_idx, 1):  # 補一個更早的 0 維持 lapse 計數
            positions.add(pos)
    for pos in positions:
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
    """n 筆嚴格遞增、末筆精確錨定 last_reviewed_at 的 tz-aware UTC 時間序列。"""
    n = card.review_count
    last = _as_utc(card.last_reviewed_at)
    created = _as_utc(card.created_at)
    assert last is not None and created is not None and n > 0
    if n == 1:
        return [last]
    eps = timedelta(microseconds=1)
    recent_gap = max(card.review_interval_hours / _INTERVAL_GROWTH, _MIN_RECENT_GAP_HOURS)
    offsets = _backward_cumulative_offsets(n, recent_gap)  # 最舊在前,[0]=span,[n-1]=0
    span = offsets[0] or 1.0
    norm = [o / span for o in offsets]                     # 1 → 0 遞減(SRS 越早間隔越大)
    start = created if created < last else last            # 異常 created≥last 時退化
    total = last - start                                   # timedelta ≥ 0
    if total <= (n - 1) * eps:
        # 視窗過窄或 created≥last(異常):自末次往前堆 µs,保證相異 + 末筆錨定。
        return [last - (n - 1 - i) * eps for i in range(n)]
    times = [last - total * norm[i] for i in range(n)]     # 映射:最舊=start,末=last
    # 浮點/壓縮可能讓相鄰撞同一 µs;自 anchor 往舊回夾,強制嚴格遞增且不動末筆 anchor。
    for i in range(n - 2, -1, -1):
        if times[i] >= times[i + 1]:
            times[i] = times[i + 1] - eps
    return times


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
