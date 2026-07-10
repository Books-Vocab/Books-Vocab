#!/usr/bin/env python3
"""行銷帳號複習歷史敘事塑形：seed spec + history plan → 新 seed spec（確定式）。

**本模組是「複習歷史敘事」的唯一 owner**：spec 的 review 時間欄位
（`last_reviewed_at` / `next_review_at` / `review_interval_hours`）只由這裡塑形；
原 `apply_curation._rebalance_reviews`（過期山攤平）已退役、由本工具收編。
計數器欄位（review_count / review_streak / lapse_count / last_review_feedback）
與所有非 review 欄位**原封不動**——塑形只重排時間線，不竄改學習事實。

輸入輸出都是 `kg.seed_spec.v1`（roundtrip 契約見 docs/reference/ops_state_plane.md
§1.1）；plan 是 `kg.history_plan.v1`（敘事參數，進 git 即歷史）。

設計不變量：
- **零 wall-clock、零隨機**：錨日來自 plan（絕不 today()）；所有「偽隨機」都是
  card content 的 sha256 派生 → 同輸入重跑 byte 相等。
- **冪等**：塑形只讀 content / notebook / counters + plan，無視輸入日期欄位 →
  shape(shape(x)) == shape(x)，committed spec 可直接當 drift gate。
- **與投影合成語意共讀**：敘事斷言（streak / 覆蓋 / forbidden day）用
  `ops/demo/spec_world.py` 的 `_card_history`（= iOS fixture 實際看到的合成事件）
  自檢，違反即 HistoryShapeError fail-loud，絕不輸出壞敘事。
- **自洽**：`review_interval_hours == next_review_at - last_reviewed_at`；
  `review_count > 0 ⇒ last_reviewed_at 非空`（synthesize_many 前置）。

敘事形狀（相對 anchor_day；day 分桶 = UTC ts + render offset。iOS dayKey 用
render 機器牆鐘時區（Calendar.current）→ plan 的 `render_utc_offset_hours` 列出
候選時區（如 [9, 8] = Tokyo/Taipei，首位 canonical），敘事斷言（streak /
forbidden day 零事件 / 覆蓋）必須在**每個** offset 下同時成立）：
- 目前 streak：[anchor-cs+1 .. anchor] 每日有事件（cs = current_streak_days）。
- 斷檔日：anchor-cs 零事件（streak 邊界）。
- 最長紀錄：[anchor-cs-ls .. anchor-cs-1] 每日有事件（ls = longest_streak_days），
  其前一日（pre-gap）零事件。
- 到期：primary/other 各 due_at_anchor 張在錨日（當地日任一時刻 render）到期；
  其餘 next_review 落在 (anchor, anchor+due_horizon_days]，線性遞減分佈。
- 事件 UTC 時刻限制在 event_utc_hours 窗（預設 01–14），確保 UTC 與 UTC+8 判定
  同一天（render 機器在 Asia/Taipei）。

iOS 端的「今天」是 render 牆鐘 → 錨日離今天越遠敘事越崩；`emit_ios` 對 > 48h 的
spec 印 WARN（`spec_staleness_warning`），重新錨定 = 改 plan `anchor_day` 重跑本
工具。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
_DEMO_DIR = _HERE.parent
if str(_DEMO_DIR) not in sys.path:
    sys.path.insert(0, str(_DEMO_DIR))

import spec_world  # noqa: E402

PLAN_SCHEMA = "kg.history_plan.v1"
SPEC_SCHEMA = "kg.seed_spec.v1"

_NEW_CARD_INTERVAL_HOURS = 12.0   # 對齊 export 面「已建卡未複習」的預設排程
_PLACE_HOUR_SALTS = 8             # first-fit 落日時每卡嘗試的時刻鹽數
_REPAIR_HOUR_SALTS = 24           # archived forbidden-day 碰撞：先試時刻鹽
_REPAIR_DAY_DELTAS = (-1, -2, -3, -5, -8, -13)  # archived 再試往更早挪日
_METRIC_WINDOW_DAYS = 183         # iOS Stats/ReviewCalendar @Query 6 個月 cutoff 鏡像

# fresh-green cohort：讓 primary「已複習」tab 頂端出現剛複習的亮綠卡（ratio≈0），
# 與既有琥珀卡交錯成綠→黃梯度。挑 primary learned 的低 review_count 卡（回推合成
# 事件短、絕不跨斷檔日），last=anchor 貼近凍結 now（elapsed≈0）、next=anchor+1..3
# （短 interval）→ 在 reviewed tab（依 nextReviewAt 升冪）排最前且 ratio≈0。
_FRESH_GREEN_TARGET = 16          # 目標亮綠卡數
_FRESH_MAX_REVIEW_COUNT = 3       # 只挑低 count 卡（回推事件短，不觸斷檔日）
_FRESH_NEXT_DAYS = (1, 2, 3)      # next = anchor + 這些天（短 interval → 綠）


class HistoryShapeError(Exception):
    pass


# --------------------------------------------------------------------------- #
# deterministic hash helpers（唯一「隨機」來源 = card content）
# --------------------------------------------------------------------------- #
def _u64(*parts: object) -> int:
    digest = hashlib.sha256("|".join(str(p) for p in parts).encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")


# --------------------------------------------------------------------------- #
# plan / narrative geometry
# --------------------------------------------------------------------------- #
class _Narrative:
    def __init__(self, plan: dict[str, Any]):
        if plan.get("schema") != PLAN_SCHEMA:
            raise HistoryShapeError(
                f"plan schema 必須是 {PLAN_SCHEMA}，got {plan.get('schema')!r}")
        try:
            self.anchor: date = date.fromisoformat(str(plan["anchor_day"]))
            offsets = plan["render_utc_offset_hours"]
            if not isinstance(offsets, list) or not offsets:
                raise ValueError("render_utc_offset_hours 必須是非空 list")
            # render 機器牆鐘時區候選（iOS dayKey 用 Calendar.current）。
            # 首位 = canonical（報表分桶）；敘事斷言須在每個 offset 下同時成立。
            self.offsets = [timedelta(hours=int(h)) for h in offsets]
            self.offset = self.offsets[0]
            self.current_days = int(plan["current_streak_days"])
            self.longest_days = int(plan["longest_streak_days"])
            due = plan["due_at_anchor"]
            self.due_primary = int(due["primary"])
            self.due_other = int(due["other"])
            self.horizon = int(plan["due_horizon_days"])
            self.weights = [float(w) for w in plan["weekday_weights"]]
            lo, hi = plan["event_utc_hours"]
            self.hour_lo, self.hour_hi = int(lo), int(hi)
            self.daily_primary_max = int(plan["daily_primary_events_max"])
        except (KeyError, TypeError, ValueError) as exc:
            raise HistoryShapeError(f"plan 欄位缺失或型別錯: {exc!r}") from exc
        if self.current_days < 1 or self.longest_days <= self.current_days:
            raise HistoryShapeError(
                "需 1 <= current_streak_days < longest_streak_days（否則 longest 顯示值會被目前 run 蓋掉）")
        if len(self.weights) != 7:
            raise HistoryShapeError("weekday_weights 必須是 7 元素（Mon..Sun）")
        max_off = max(td.total_seconds() / 3600 for td in self.offsets)
        min_off = min(td.total_seconds() / 3600 for td in self.offsets)
        if min_off < 0 or max_off > 14:
            raise HistoryShapeError("render_utc_offset_hours 必須落在 [0,14]")
        if not (0 <= self.hour_lo <= self.hour_hi <= 23 - int(max_off)):
            raise HistoryShapeError(
                f"event_utc_hours 必須落在 [0,{23 - int(max_off)}]"
                "（UTC 與所有 render offset 同日的交集）")
        if self.horizon < 1:
            raise HistoryShapeError("due_horizon_days 必須 >= 1")

        self.break_day = self.anchor - timedelta(days=self.current_days)
        self.pre_gap_day = self.anchor - timedelta(
            days=self.current_days + self.longest_days + 1)
        run_current = [self.anchor - timedelta(days=k)
                       for k in range(self.current_days)]
        run_longest = [self.break_day - timedelta(days=k)
                       for k in range(1, self.longest_days + 1)]
        self.narrative_days: list[date] = sorted(run_longest + run_current)
        # iOS Stats / ReviewCalendar 的 @Query 只看最近 6 個月（wall-clock ≈ anchor）
        # → 敘事指標窗口鏡像之；窗口內的深歷史（合成 tail 事件）用「防火巷」
        # 切斷：每 longest_days 一個零事件日，任何意外連續 run < longest_days，
        # 保證最長紀錄 == plan 值而非被 tail 巧合蓋掉。
        self.metric_floor = self.anchor - timedelta(days=_METRIC_WINDOW_DAYS)
        firebreaks: list[date] = []
        d = self.pre_gap_day
        floor = self.metric_floor - timedelta(days=self.longest_days)
        while True:
            d -= timedelta(days=self.longest_days)
            if d < floor:
                break
            firebreaks.append(d)
        self.forbidden_days = {self.break_day, self.pre_gap_day, *firebreaks}

    def day_of(self, dt: datetime, offset: timedelta | None = None) -> date:
        return (dt.astimezone(timezone.utc) + (offset or self.offset)).date()


def load_plan(path: Path) -> dict[str, Any]:
    try:
        plan = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HistoryShapeError(f"plan 不是可讀 JSON: {path}: {exc}") from exc
    _Narrative(plan)  # 驗證即載入
    return plan


# --------------------------------------------------------------------------- #
# deterministic allocation
# --------------------------------------------------------------------------- #
def _largest_remainder(weights: list[float], total: int, minimum: int) -> list[int]:
    """權重 → 整數配額（和恰為 total、每格 >= minimum）。"""
    n = len(weights)
    if total < minimum * n:
        raise HistoryShapeError(
            f"卡量不足：需要至少 {minimum * n} 張、只有 {total} 張可分配")
    spare = total - minimum * n
    weight_sum = sum(weights) or 1.0
    raw = [spare * w / weight_sum for w in weights]
    counts = [int(r) for r in raw]
    remainders = sorted(
        range(n), key=lambda i: (-(raw[i] - counts[i]), i))
    for i in remainders[: spare - sum(counts)]:
        counts[i] += 1
    return [minimum + c for c in counts]


def _event_time(content: str, d: date, *, hour_lo: int, hour_hi: int,
                salt: int = 0) -> datetime:
    span = hour_hi - hour_lo + 1
    hour = hour_lo + (_u64("hour", content, salt) % span)
    minute = _u64("minute", content, salt) % 60
    second = _u64("second", content, salt) % 60
    return datetime(d.year, d.month, d.day, hour, minute, second, tzinfo=timezone.utc)


def _synth_event_days(card_fields: dict[str, Any], narrative: _Narrative) -> set[date]:
    """以 spec_world 的合成語意（= iOS fixture 實際事件）算出此卡事件覆蓋的日集合。

    合成 tail 事件的 UTC 時刻不受 event_utc_hours 窗限制 → 對「每個」候選 render
    offset 各分桶一次取聯集：任何 offset 下踩到 forbidden day 都算碰撞。"""
    normalized = {
        "word": card_fields["content"],
        "review_count": card_fields["review_count"],
        "review_streak": card_fields["review_streak"],
        "lapse_count": card_fields["lapse_count"],
        "last_review_feedback": card_fields["last_review_feedback"],
        "review_interval_hours": card_fields["review_interval_hours"],
        "last_reviewed_at": spec_world._fmt_ts(card_fields["last_dt"]),
    }
    days: set[date] = set()
    for event in spec_world._card_history(normalized):
        dt = datetime.strptime(event["reviewedAt"], "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc)
        for offset in narrative.offsets:
            days.add(narrative.day_of(dt, offset))
    return days


# --------------------------------------------------------------------------- #
# core transform
# --------------------------------------------------------------------------- #
def _primary_notebook(spec: dict[str, Any]) -> str:
    """鏡像 spec_world._normalize 的 primary 選擇（active 卡最多，tie-break:
    is_default、再宣告順序）。"""
    names = [str(nb["name"]) for nb in spec["notebooks"]]
    active_count = {name: 0 for name in names}
    for card in spec["cards"]:
        if card["notebook"] not in active_count:
            raise HistoryShapeError(
                f"卡 {card.get('content')!r} 的 notebook {card['notebook']!r} 未在 "
                "spec.notebooks 宣告")
        if not card.get("is_archived"):
            active_count[card["notebook"]] += 1
    return max(
        names,
        key=lambda name: (active_count[name],
                          bool(next(nb.get("is_default") for nb in spec["notebooks"]
                                    if nb["name"] == name)),
                          -names.index(name)),
    )


def shape(spec: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
    if spec.get("schema") != SPEC_SCHEMA:
        raise HistoryShapeError(f"spec schema 不是 {SPEC_SCHEMA}: {spec.get('schema')!r}")
    narrative = _Narrative(plan)
    out = json.loads(json.dumps(spec, ensure_ascii=False))
    cards = out["cards"]

    contents = [c["content"] for c in cards]
    if len(set(contents)) != len(contents):
        dupes = sorted({w for w in contents if contents.count(w) > 1})
        raise HistoryShapeError(f"card content 全域重複（塑形以 content 為 key）: {dupes[:10]}")

    violators = sorted(
        c["content"] for c in cards
        if c["review"]["review_count"] > 0 and not c["review"].get("last_reviewed_at"))
    if violators:  # §1.1 spec 不變量：上游資料壞就 fail-loud，不硬扛
        raise HistoryShapeError(
            f"{len(violators)} 卡 review_count>0 但缺 last_reviewed_at: {violators[:10]}")

    primary = _primary_notebook(out)
    learned = [c for c in cards
               if c["review"]["review_count"] > 0 and not c.get("is_archived")]
    fresh = [c for c in cards
             if c["review"]["review_count"] == 0 and not c.get("is_archived")]
    archived = [c for c in cards if c.get("is_archived")]

    fields: dict[str, dict[str, Any]] = {}

    def _register(card: dict[str, Any], last_dt: datetime,
                  next_dt: datetime | None = None) -> None:
        r = card["review"]
        fields[card["content"]] = {
            "content": card["content"],
            "notebook": card["notebook"],
            "review_count": r["review_count"],
            "review_streak": r["review_streak"],
            "lapse_count": r["lapse_count"],
            "last_review_feedback": r["last_review_feedback"],
            "review_interval_hours": float(r["review_interval_hours"] or 12.0),
            "last_dt": last_dt,
            "next_dt": next_dt,
            "last_day": narrative.day_of(last_dt),
        }
        if next_dt is not None:
            fields[card["content"]]["review_interval_hours"] = round(
                (next_dt - last_dt).total_seconds() / 3600, 6)

    learned_primary = [c for c in learned if c["notebook"] == primary]
    learned_other = [c for c in learned if c["notebook"] != primary]
    days = narrative.narrative_days

    # -- 1. 先定 due 集合與所有 next（與敘事日無關，純 content hash） ---------- #
    #    due 卡在錨日（當地日）任一 render 時刻都成立：next <= anchor 當地日 00:00
    #    （= UTC anchor-1 16:00）→ 取 anchor-1 的 01–12Z；分配敘事日時再限制其
    #    last_day <= anchor-3 保證 next > last。
    def _pick_due(group: list[dict[str, Any]], want: int, label: str) -> set[str]:
        if len(group) < want:
            raise HistoryShapeError(f"{label} due 候選不足：需要 {want}、僅 {len(group)}")
        ranked = sorted(group, key=lambda c: (_u64("due", c["content"]), c["content"]))
        return {c["content"] for c in ranked[:want]}

    due_words = (_pick_due(learned_primary, narrative.due_primary, "primary")
                 | _pick_due(learned_other, narrative.due_other, "other"))

    due_day = narrative.anchor - timedelta(days=1)
    next_by_word: dict[str, datetime] = {
        word: _event_time(word + "#due", due_day, hour_lo=1, hour_hi=12)
        for word in due_words
    }

    # -- 1a. fresh-green cohort（primary 剛複習亮綠卡） ------------------------ #
    #    從 primary learned 的低 count 卡（排除 due）確定式挑一批：last=anchor 貼近
    #    凍結 now（hour 高段 → elapsed≈0）、next=anchor+1..3（interval 短）→ reviewed
    #    tab 頂端亮綠。碰撞感知：若合成回推事件撞斷檔日就換 off/hour 鹽，全撞則放回
    #    normal _assign（不強塞）。placed 者直接 register，_scatter_due/_assign 不再碰。
    def _place_fresh(card: dict[str, Any]) -> tuple[datetime, datetime] | None:
        word = card["content"]
        r = card["review"]
        chosen = _FRESH_NEXT_DAYS[_u64("freshnext", word) % len(_FRESH_NEXT_DAYS)]
        for off in (chosen, *sorted(o for o in _FRESH_NEXT_DAYS if o != chosen)):
            next_dt = _event_time(
                word + f"#freshnext{off}", narrative.anchor + timedelta(days=off),
                hour_lo=narrative.hour_lo, hour_hi=narrative.hour_hi)
            for salt in range(_PLACE_HOUR_SALTS):
                last_dt = _event_time(
                    word + "#freshlast", narrative.anchor,
                    hour_lo=max(narrative.hour_lo, narrative.hour_hi - 2),
                    hour_hi=narrative.hour_hi, salt=salt)
                interval = round((next_dt - last_dt).total_seconds() / 3600, 6)
                if interval <= 0:
                    continue
                trial = {
                    "content": word,
                    "review_count": r["review_count"],
                    "review_streak": r["review_streak"],
                    "lapse_count": r["lapse_count"],
                    "last_review_feedback": r["last_review_feedback"],
                    "review_interval_hours": interval,
                    "last_dt": last_dt,
                }
                if not (_synth_event_days(trial, narrative) & narrative.forbidden_days):
                    return last_dt, next_dt
        return None

    fresh_pool = [c for c in learned_primary
                  if c["content"] not in due_words
                  and 1 <= c["review"]["review_count"] <= _FRESH_MAX_REVIEW_COUNT]
    fresh_ranked = sorted(fresh_pool, key=lambda c: (_u64("fresh", c["content"]), c["content"]))
    fresh_words: set[str] = set()
    for card in fresh_ranked:
        if len(fresh_words) >= _FRESH_GREEN_TARGET:
            break
        placed = _place_fresh(card)
        if placed is None:
            continue  # 全撞斷檔日 → 放回 normal _assign
        last_dt, next_dt = placed
        next_by_word[card["content"]] = next_dt
        _register(card, last_dt, next_dt)
        fresh_words.add(card["content"])

    # 每日覆蓋由 non_due（扣掉 due + fresh）保證 → 前置檢查扣掉兩者。
    non_due_primary = len(learned_primary) - narrative.due_primary - len(fresh_words)
    if non_due_primary < len(days):
        raise HistoryShapeError(
            f"primary notebook {primary!r} 非 due/非 fresh 已學卡 {non_due_primary} 張 "
            f"（{len(learned_primary)} − due {narrative.due_primary} − fresh {len(fresh_words)}）"
            f"< 敘事日數 {len(days)}：無法保證每日覆蓋（調小 plan streak / fresh 參數或擴充 spec）")

    # 非 due 且非 fresh：next 落 (anchor, anchor+horizon]，線性遞減分佈
    non_due = [c for c in learned
               if c["content"] not in due_words and c["content"] not in fresh_words]
    decay_weights = [float(narrative.horizon + 1 - k)
                     for k in range(1, narrative.horizon + 1)]
    offsets = _largest_remainder(decay_weights, len(non_due), 0)
    slot_offsets = [k + 1 for k, cap in enumerate(offsets) for _ in range(cap)]
    ordered_non_due = sorted(
        non_due, key=lambda c: (_u64("next", c["content"]), c["content"]))
    for card, off in zip(ordered_non_due, slot_offsets):
        next_by_word[card["content"]] = _event_time(
            card["content"] + "#next", narrative.anchor + timedelta(days=off),
            hour_lo=narrative.hour_lo, hour_hi=narrative.hour_hi)

    # -- 2. 敘事日 first-fit 分配（碰撞感知） ---------------------------------- #
    #    合成 tail 事件的位置由 (counters, interval=next-last, last 時刻) 完全決定
    #    （spec_world._card_history）；大 interval 卡的 gap 會被 cap 在整數天
    #    （720h）→ 時刻鹽救不了 forbidden-day 對齊 → 必須在「選日」時就避開：
    #    對每個 (slot 日, 候選卡) 先算全事件日集合，撞 forbidden 就換卡/換鹽。
    def _try_place(card: dict[str, Any], d: date) -> datetime | None:
        word = card["content"]
        if word in due_words and d > narrative.anchor - timedelta(days=3):
            return None  # due 卡的 last 必須早於 next（anchor-1）
        r = card["review"]
        for salt in range(_PLACE_HOUR_SALTS):
            last_dt = _event_time(word, d, hour_lo=narrative.hour_lo,
                                  hour_hi=narrative.hour_hi, salt=salt)
            trial = {
                "content": word,
                "review_count": r["review_count"],
                "review_streak": r["review_streak"],
                "lapse_count": r["lapse_count"],
                "last_review_feedback": r["last_review_feedback"],
                "review_interval_hours": round(
                    (next_by_word[word] - last_dt).total_seconds() / 3600, 6),
                "last_dt": last_dt,
            }
            if trial["review_interval_hours"] <= 0:
                return None
            if not (_synth_event_days(trial, narrative) & narrative.forbidden_days):
                return last_dt
        return None

    day_weights = [narrative.weights[d.weekday()] for d in days]

    # -- 2a. due 卡確定式散佈：last_dt 均勻落在 [days[0], anchor-3]，使 interval ----
    #    自然分佈（非全部擠在窗口上界）。first-fit 早日優先曾把所有 due 卡塞到
    #    最舊敘事日 → interval 全群聚。改為預置散佈：按 content hash 排序後線性
    #    映射到合法窗的等距目標日，逐張 _try_place（含 forbidden 迴避 + 目標日
    #    撞牆時往鄰日退讓）。散佈後 due 卡已 _register，first-fit 只填 non-due。
    def _search_order(count: int):
        yield 0
        for radius in range(1, count):
            yield radius
            yield -radius

    def _scatter_due(group_due: list[dict[str, Any]], label: str) -> None:
        if not group_due:
            return
        eligible = [d for d in days if d <= narrative.anchor - timedelta(days=3)]
        if not eligible:
            raise HistoryShapeError(f"{label} 無合法 due 敘事日（anchor-3 之前無敘事日）")
        ranked = sorted(
            group_due, key=lambda c: (_u64("duescatter", c["content"]), c["content"]))
        n, m = len(ranked), len(eligible)
        for k, card in enumerate(ranked):
            # k ∈ [0,n-1] → 等距映射到 eligible index ∈ [0,m-1]（round-half-up）
            target = 0 if n == 1 else (2 * k * (m - 1) + (n - 1)) // (2 * (n - 1))
            placed = False
            for delta in _search_order(m):
                j = target + delta
                if 0 <= j < m:
                    last_dt = _try_place(card, eligible[j])
                    if last_dt is not None:
                        _register(card, last_dt, next_by_word[card["content"]])
                        placed = True
                        break
            if not placed:
                raise HistoryShapeError(
                    f"{label} due 卡 {card['content']!r} 無合法敘事日可散佈"
                    f"（{m} 個候選日全撞斷檔日）")

    def _assign(group: list[dict[str, Any]], minimum: int, label: str) -> None:
        # due 卡已由 _scatter_due 預置、fresh 卡已釘 anchor → 這裡只排其餘 non-due
        # （coverage 靠 non-due minimum 保證，due/fresh 是額外事件，不減損任何敘事日覆蓋）。
        non_due = [c for c in group
                   if c["content"] not in due_words and c["content"] not in fresh_words]
        if minimum > 0 and len(non_due) < len(days):
            raise HistoryShapeError(
                f"{label} non-due 已學卡 {len(non_due)} 張 < 敘事日數 {len(days)}："
                "無法保證每日覆蓋（調小 plan streak 參數或擴充 spec）")
        capacities = _largest_remainder(day_weights, len(non_due), minimum)
        queue = sorted(non_due, key=lambda c: (_u64("day", c["content"]), c["content"]))
        for d, cap in zip(days, capacities):
            for _ in range(cap):
                placed_at = None
                for i in range(len(queue)):
                    last_dt = _try_place(queue[i], d)
                    if last_dt is not None:
                        _register(queue[i], last_dt, next_by_word[queue[i]["content"]])
                        placed_at = i
                        break
                if placed_at is None:
                    raise HistoryShapeError(
                        f"{label} 敘事日 {d.isoformat()} 找不到可避開斷檔日的卡"
                        f"（剩 {len(queue)} 張候選）")
                queue.pop(placed_at)
        if queue:  # _largest_remainder 保證和相等，這裡防禦性檢查
            raise HistoryShapeError(f"{label} 有 {len(queue)} 張卡未分配到敘事日")

    _scatter_due([c for c in learned_primary if c["content"] in due_words], "primary")
    _scatter_due([c for c in learned_other if c["content"] in due_words], "other")
    _assign(learned_primary, minimum=1, label="primary")
    if learned_other:
        _assign(learned_other, minimum=0, label="other")

    # -- 4. archived：敘事窗之前退休，遠離 forbidden days --------------------- #
    for card in archived:
        word = card["content"]
        back = 2 + _u64("arch", word) % 60
        d = narrative.pre_gap_day - timedelta(days=back)
        _register(card, _event_time(word, d, hour_lo=narrative.hour_lo,
                                    hour_hi=narrative.hour_hi))
        fields[word]["next_dt"] = fields[word]["last_dt"] + timedelta(
            days=30 + _u64("archnext", word) % 60)
        fields[word]["review_interval_hours"] = round(
            (fields[word]["next_dt"] - fields[word]["last_dt"]).total_seconds() / 3600, 6)

    # -- 5. 未學卡：近錨日剛加入（保留 export 面 12h 預設排程形狀） ------------ #
    for card in fresh:
        word = card["content"]
        d = narrative.anchor - timedelta(days=_u64("new", word) % 3)
        last_dt = _event_time(word, d, hour_lo=narrative.hour_lo,
                              hour_hi=min(narrative.hour_hi, 10))
        _register(card, last_dt)
        fields[word]["review_interval_hours"] = _NEW_CARD_INTERVAL_HOURS
        fields[word]["next_dt"] = last_dt + timedelta(
            hours=_NEW_CARD_INTERVAL_HOURS)

    # -- 6. archived 的 forbidden-day 修復（tail 事件可能踩到深歷史防火巷） ---- #
    #    learned 卡已在 first-fit 分配時避開；archived 位置自由度大，用
    #    時刻鹽 + 往更早挪日即可。
    for card in sorted(archived, key=lambda c: c["content"]):
        word = card["content"]
        f = fields[word]
        if not (_synth_event_days(f, narrative) & narrative.forbidden_days):
            continue
        repaired = False
        base_day = f["last_day"]
        for delta_days in (0, *_REPAIR_DAY_DELTAS):
            new_day = base_day + timedelta(days=delta_days)
            if new_day in narrative.forbidden_days or new_day > (
                    narrative.pre_gap_day - timedelta(days=2)):
                continue
            for salt in range(_REPAIR_HOUR_SALTS):
                if delta_days == 0 and salt == 0:
                    continue  # 原狀已檢查
                candidate = _event_time(word, new_day, hour_lo=narrative.hour_lo,
                                        hour_hi=narrative.hour_hi, salt=salt)
                trial = dict(f, last_dt=candidate)
                trial["review_interval_hours"] = round(
                    (f["next_dt"] - candidate).total_seconds() / 3600, 6)
                if trial["review_interval_hours"] <= 0:
                    continue
                if _synth_event_days(trial, narrative) & narrative.forbidden_days:
                    continue
                f.update(last_dt=candidate, last_day=new_day,
                         review_interval_hours=trial["review_interval_hours"])
                repaired = True
                break
            if repaired:
                break
        if not repaired:
            raise HistoryShapeError(
                f"archived 卡 {word!r} 的合成事件無法避開斷檔日")

    # -- 7. 寫回 -------------------------------------------------------------- #
    for card in cards:
        f = fields[card["content"]]
        r = card["review"]
        r["last_reviewed_at"] = f["last_dt"].isoformat()
        r["next_review_at"] = f["next_dt"].isoformat()
        r["review_interval_hours"] = f["review_interval_hours"]

    _self_check(out, plan)
    return out


# --------------------------------------------------------------------------- #
# narrative self-check（輸出前 gate；違反 = 不輸出）
# --------------------------------------------------------------------------- #
def narrative_report(spec: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
    """以 spec_world 合成語意重算敘事指標（供自檢 / 測試 / CLI --report）。"""
    narrative = _Narrative(plan)
    primary = _primary_notebook(spec)

    # 每個候選 render offset 各建一份 primary 事件日直方圖（iOS dayKey 用
    # Calendar.current，牆鐘時區不歸我們管 → 敘事必須在每個 offset 下都成立）
    per_day_by_offset: list[dict[date, int]] = [{} for _ in narrative.offsets]
    all_event_days: set[date] = set()
    for card in spec["cards"]:
        r = card["review"]
        if r["review_count"] <= 0 or not r.get("last_reviewed_at"):
            continue
        last_dt = datetime.fromisoformat(r["last_reviewed_at"])
        if last_dt.tzinfo is None:
            last_dt = last_dt.replace(tzinfo=timezone.utc)
        card_fields = {
            "content": card["content"],
            "review_count": r["review_count"],
            "review_streak": r["review_streak"],
            "lapse_count": r["lapse_count"],
            "last_review_feedback": r["last_review_feedback"],
            "review_interval_hours": float(r["review_interval_hours"]),
            "last_dt": last_dt,
        }
        all_event_days |= _synth_event_days(card_fields, narrative)
        if card["notebook"] == primary and not card.get("is_archived"):
            normalized = {
                "word": card["content"],
                "review_count": r["review_count"],
                "review_streak": r["review_streak"],
                "lapse_count": r["lapse_count"],
                "last_review_feedback": r["last_review_feedback"],
                "review_interval_hours": float(r["review_interval_hours"]),
                "last_reviewed_at": spec_world._fmt_ts(last_dt),
            }
            for event in spec_world._card_history(normalized):
                dt = datetime.strptime(
                    event["reviewedAt"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                for i, offset in enumerate(narrative.offsets):
                    d = narrative.day_of(dt, offset)
                    if d < narrative.metric_floor:
                        continue  # 鏡像 iOS @Query 6 個月 cutoff：更深的事件不進指標
                    per_day_by_offset[i][d] = per_day_by_offset[i].get(d, 0) + 1

    def _streaks(per_day: dict[date, int]) -> tuple[int, int]:
        current = 0
        probe = narrative.anchor
        while per_day.get(probe, 0) > 0:
            current += 1
            probe -= timedelta(days=1)
        longest = run = 0
        if per_day:
            d = min(per_day)
            while d <= max(per_day):
                if per_day.get(d, 0) > 0:
                    run += 1
                    longest = max(longest, run)
                else:
                    run = 0
                d += timedelta(days=1)
        return current, longest

    streaks_by_offset = {
        int(offset.total_seconds() // 3600): _streaks(per_day)
        for offset, per_day in zip(narrative.offsets, per_day_by_offset)
    }
    per_day_primary = per_day_by_offset[0]  # canonical（報表用）
    current, longest = _streaks(per_day_primary)

    render_floor = (datetime(narrative.anchor.year, narrative.anchor.month,
                             narrative.anchor.day, tzinfo=timezone.utc)
                    - narrative.offset)
    due_primary = due_other = 0
    horizon_violations: list[str] = []
    for card in spec["cards"]:
        r = card["review"]
        if r["review_count"] <= 0 or card.get("is_archived"):
            continue
        nxt = datetime.fromisoformat(r["next_review_at"])
        if nxt.tzinfo is None:
            nxt = nxt.replace(tzinfo=timezone.utc)
        if nxt <= render_floor:
            if card["notebook"] == primary:
                due_primary += 1
            else:
                due_other += 1
        else:
            off = (narrative.day_of(nxt) - narrative.anchor).days
            if not 1 <= off <= narrative.horizon:
                horizon_violations.append(card["content"])

    narrative_counts = {
        d.isoformat(): per_day_primary.get(d, 0) for d in narrative.narrative_days}
    return {
        "primaryNotebook": primary,
        "currentStreak": current,
        "longestStreak": longest,
        "streaksByRenderOffset": {
            str(k): {"current": c, "longest": l}
            for k, (c, l) in sorted(streaks_by_offset.items())},
        "duePrimary": due_primary,
        "dueOther": due_other,
        "horizonViolations": horizon_violations,
        "forbiddenDayEvents": sorted(
            d.isoformat() for d in (all_event_days & narrative.forbidden_days)),
        "narrativeDayPrimaryEvents": narrative_counts,
        "anchorDayPrimaryEvents": per_day_primary.get(narrative.anchor, 0),
    }


def _self_check(spec: dict[str, Any], plan: dict[str, Any]) -> None:
    narrative = _Narrative(plan)
    report = narrative_report(spec, plan)
    problems: list[str] = []
    for off, s in report["streaksByRenderOffset"].items():
        if s["current"] != narrative.current_days:
            problems.append(
                f"offset+{off} currentStreak {s['current']} != {narrative.current_days}")
        if s["longest"] != narrative.longest_days:
            problems.append(
                f"offset+{off} longestStreak {s['longest']} != {narrative.longest_days}")
    if report["duePrimary"] != narrative.due_primary:
        problems.append(f"duePrimary {report['duePrimary']} != {narrative.due_primary}")
    if report["dueOther"] != narrative.due_other:
        problems.append(f"dueOther {report['dueOther']} != {narrative.due_other}")
    if report["horizonViolations"]:
        problems.append(f"next 超出 horizon: {report['horizonViolations'][:5]}")
    if report["forbiddenDayEvents"]:
        problems.append(f"斷檔日有事件: {report['forbiddenDayEvents']}")
    if report["anchorDayPrimaryEvents"] < 1:
        problems.append("錨日無 primary 事件")
    for day_iso, count in report["narrativeDayPrimaryEvents"].items():
        if count < 1:
            problems.append(f"敘事日 {day_iso} 無 primary 事件")
        if count > narrative.daily_primary_max:
            problems.append(
                f"敘事日 {day_iso} primary 事件 {count} > {narrative.daily_primary_max}")
    # 投影面全域 cap 建模：statsPopulated / reviewCalendarDense 只保留最近
    # N 筆事件——若合成事件總量觸頂，最舊敘事日會被截掉、streak 崩而自檢仍過。
    total_primary_events = sum(
        min(c["review"]["review_count"], spec_world._HISTORY_PER_CARD_MAX)
        for c in spec["cards"]
        if c["notebook"] == report["primaryNotebook"]
        and not c.get("is_archived") and c["review"]["review_count"] > 0)
    fixture_cap = min(spec_world._HISTORY_STATS_MAX, spec_world._HISTORY_DENSE_MAX)
    if total_primary_events > fixture_cap:
        problems.append(
            f"primary 合成事件 {total_primary_events} > fixture cap {fixture_cap}"
            "（最舊敘事日會被投影截斷）")
    if problems:
        raise HistoryShapeError("敘事自檢失敗: " + "; ".join(problems))


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("spec", help="輸入 kg.seed_spec.v1 JSON")
    ap.add_argument("plan", help="kg.history_plan.v1 JSON（敘事參數，進 git）")
    ap.add_argument("--out", help="輸出路徑（可同輸入路徑原地重錨；預設 stdout）")
    ap.add_argument("--report", action="store_true",
                    help="stderr 印敘事指標（streak / due / 每日事件量）")
    args = ap.parse_args()

    spec = json.loads(Path(args.spec).read_text(encoding="utf-8"))
    plan = load_plan(Path(args.plan))
    result = shape(spec, plan)
    payload = json.dumps(result, ensure_ascii=False, indent=1) + "\n"
    if args.report:
        print(json.dumps(narrative_report(result, plan), ensure_ascii=False, indent=2),
              file=sys.stderr)
    if args.out:
        Path(args.out).write_text(payload, encoding="utf-8")
        print(f"shape_history: {args.out} (cards={len(result['cards'])}, "
              f"anchor={plan['anchor_day']})")
    else:
        print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
