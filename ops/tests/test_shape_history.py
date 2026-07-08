"""shape_history.py（行銷帳號複習歷史敘事塑形）契約測試。

覆蓋四類不變量：
1. 確定性 / 冪等 — 同輸入 byte 相等；shape(shape(x)) == shape(x)（塑形只讀
   content/notebook/counters + plan，無視輸入日期欄位）。
2. 敘事斷言 — 以 spec_world 真投影（reviewCalendarDense.reviewHistory）重算
   iOS ReviewActivityLog 語意的 current/longest streak、錨日事件存在、
   forbidden day 零事件、每敘事日 primary 覆蓋。
3. 到期分佈 — 錨日 due 數（primary/other 分開）、非 due 卡 next 落在
   (anchor, anchor+horizon]、遞減分佈。
4. 守恆 — review 計數器與非 review 欄位 byte 不動；interval == next - last；
   roundtrip 前置（review_count>0 ⇒ last_reviewed_at）。
"""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
MA_DIR = ROOT / "ops" / "demo" / "marketing_account"
DEMO_DIR = ROOT / "ops" / "demo"


def _load_module(name: str, directory: Path):
    spec = importlib.util.spec_from_file_location(name, directory / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(directory))
    try:
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
    finally:
        try:
            sys.path.remove(str(directory))
        except ValueError:
            pass
    return module


shape_history = _load_module("shape_history", MA_DIR)
spec_world = _load_module("spec_world", DEMO_DIR)


# --------------------------------------------------------------------------- #
# 小型合成 spec：plan 參數縮小（streak 5 / longest 8 / horizon 10）跑得快。
# --------------------------------------------------------------------------- #
def _plan(**overrides) -> dict:
    plan = {
        "schema": "kg.history_plan.v1",
        "anchor_day": "2026-07-09",
        "render_utc_offset_hours": [9, 8],
        "current_streak_days": 5,
        "longest_streak_days": 8,
        "due_at_anchor": {"primary": 2, "other": 1},
        "due_horizon_days": 10,
        "weekday_weights": [1.0, 1.0, 1.0, 1.0, 1.2, 1.6, 1.5],
        "event_utc_hours": [1, 14],
        "daily_primary_events_max": 30,
    }
    plan.update(overrides)
    return plan


def _card(word: str, nb: str, *, count: int = 4, streak: int = 2, lapse: int = 1,
          feedback: int = 1) -> dict:
    review = {
        "review_count": count,
        "review_streak": min(streak, count),
        "lapse_count": lapse if count else 0,
        "review_interval_hours": 48.0,
        "next_review_at": "2026-01-05T00:00:00+00:00",
        "last_reviewed_at": "2026-01-01T00:00:00+00:00" if count else None,
        "last_review_feedback": feedback if count else -1,
    }
    if count == 0:
        review.update({"review_streak": 0, "lapse_count": 0,
                       "review_interval_hours": 12.0,
                       "next_review_at": None, "last_review_feedback": -1})
    return {
        "content": word, "pos": "n.", "meaning": f"{word} 意", "examples": [f"the {word}."],
        "collocations": [], "note": None, "difficulty": 3.0, "mode": "recognition",
        "root_form": word, "inflections": [], "is_archived": False,
        "notebook": nb, "review": review,
    }


def _spec(n_primary: int = 40, n_other: int = 12, n_new: int = 2) -> dict:
    cards = [_card(f"alpha{i:03d}", "主本", count=3 + i % 5) for i in range(n_primary)]
    cards += [_card(f"beta{i:03d}", "副本", count=3 + i % 4) for i in range(n_other)]
    cards += [_card(f"nova{i:02d}", "主本", count=0) for i in range(n_new)]
    return {
        "schema": "kg.seed_spec.v1",
        "notebooks": [
            {"name": "主本", "color": None, "cover_pattern": None,
             "sort_order": 0, "is_default": True},
            {"name": "副本", "color": None, "cover_pattern": None,
             "sort_order": 1, "is_default": False},
        ],
        "cards": cards,
        "links": [],
    }


def _dumps(spec: dict) -> str:
    return json.dumps(spec, ensure_ascii=False, indent=1)


ANCHOR = date(2026, 7, 9)
# render 機器牆鐘時區候選（iOS dayKey = Calendar.current）：Tokyo(+9)/Taipei(+8)。
# 敘事必須在每個 offset 下同時成立 —— L2 曾抓到 +8 假設下最長紀錄在 +9 主機膨脹成 82。
OFFSETS = (timedelta(hours=9), timedelta(hours=8))


def _day(ts: str, offset: timedelta = OFFSETS[0]) -> date:
    dt = datetime.fromisoformat(ts)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (dt.astimezone(timezone.utc) + offset).date()


def _norm_day(ts: str, offset: timedelta) -> date:
    """spec_world 正規化格式（YYYY-MM-DDTHH:MM:SSZ）→ render-offset day。"""
    dt = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    return (dt + offset).date()


def _primary_event_days(shaped: dict, offset: timedelta = OFFSETS[0]) -> dict[date, int]:
    """走真投影：reviewCalendarDense.reviewHistory（primary notebook 全 active 卡）。"""
    domains, _ = spec_world.derive_domains(shaped)
    history = domains["vocabulary"]["reviewCalendarDense"]["reviewHistory"]
    days: dict[date, int] = {}
    for event in history:
        d = _norm_day(event["reviewedAt"], offset)
        days[d] = days.get(d, 0) + 1
    return days


def _streaks(days: dict[date, int], anchor: date) -> tuple[int, int]:
    """鏡像 ios ReviewActivityLog.streaks 語意（current 從 anchor 往回數）。"""
    current = 0
    probe = anchor
    while days.get(probe, 0) > 0:
        current += 1
        probe -= timedelta(days=1)
    if not days:
        return 0, 0
    first, last = min(days), max(days)
    longest = run = 0
    d = first
    while d <= last:
        if days.get(d, 0) > 0:
            run += 1
            longest = max(longest, run)
        else:
            run = 0
        d += timedelta(days=1)
    return current, longest


class TestDeterminism:
    def test_byte_stable(self):
        a = shape_history.shape(_spec(), _plan())
        b = shape_history.shape(_spec(), _plan())
        assert _dumps(a) == _dumps(b)

    def test_idempotent(self):
        once = shape_history.shape(_spec(), _plan())
        twice = shape_history.shape(once, _plan())
        assert _dumps(once) == _dumps(twice)


class TestNarrative:
    def test_streaks_match_plan_via_projection(self):
        shaped = shape_history.shape(_spec(), _plan())
        for offset in OFFSETS:
            current, longest = _streaks(_primary_event_days(shaped, offset), ANCHOR)
            assert current == 5, f"offset {offset}"
            assert longest == 8, f"offset {offset}"

    def test_anchor_day_has_events(self):
        shaped = shape_history.shape(_spec(), _plan())
        for offset in OFFSETS:
            assert _primary_event_days(shaped, offset).get(ANCHOR, 0) >= 1

    def test_forbidden_gap_days_have_zero_events_all_notebooks(self):
        plan = _plan()
        shaped = shape_history.shape(_spec(), plan)
        break_day = ANCHOR - timedelta(days=plan["current_streak_days"])
        pre_gap = break_day - timedelta(days=plan["longest_streak_days"] + 1)
        all_days: set[date] = set()
        for card in shaped["cards"]:
            r = card["review"]
            if r["review_count"] <= 0 or not r["last_reviewed_at"]:
                continue
            norm = {
                "word": card["content"],
                "review_count": r["review_count"],
                "review_streak": r["review_streak"],
                "lapse_count": r["lapse_count"],
                "last_review_feedback": r["last_review_feedback"],
                "review_interval_hours": r["review_interval_hours"],
                "last_reviewed_at": spec_world._norm_ts(
                    r["last_reviewed_at"], owner=card["content"]),
            }
            for event in spec_world._card_history(norm):
                for offset in OFFSETS:
                    all_days.add(_norm_day(event["reviewedAt"], offset))
        assert break_day not in all_days
        assert pre_gap not in all_days

    def test_every_narrative_day_covered_and_bounded(self):
        plan = _plan()
        shaped = shape_history.shape(_spec(), plan)
        days = _primary_event_days(shaped)
        total_days = plan["current_streak_days"] + plan["longest_streak_days"] + 1
        narrative = [ANCHOR - timedelta(days=k) for k in range(total_days)]
        break_day = ANCHOR - timedelta(days=plan["current_streak_days"])
        for d in narrative:
            if d == break_day:
                assert days.get(d, 0) == 0
            else:
                assert days.get(d, 0) >= 1, f"{d} 無 primary 事件"
                assert days[d] <= plan["daily_primary_events_max"]


class TestDueDistribution:
    def test_due_counts_by_group(self):
        plan = _plan()
        shaped = shape_history.shape(_spec(), plan)
        # render 視窗下界：anchor 當地日 00:00（= UTC anchor-1 16:00）
        render_floor = datetime(2026, 7, 8, 16, 0, tzinfo=timezone.utc)
        due_primary = due_other = 0
        for card in shaped["cards"]:
            r = card["review"]
            if r["review_count"] <= 0:
                continue
            nxt = datetime.fromisoformat(r["next_review_at"])
            if nxt <= render_floor:
                if card["notebook"] == "主本":
                    due_primary += 1
                else:
                    due_other += 1
        assert due_primary == plan["due_at_anchor"]["primary"]
        assert due_other == plan["due_at_anchor"]["other"]

    def test_non_due_next_in_horizon_and_decreasing(self):
        plan = _plan()
        shaped = shape_history.shape(_spec(), plan)
        render_ceiling = datetime(2026, 7, 9, 16, 0, tzinfo=timezone.utc)
        offsets = []
        for card in shaped["cards"]:
            r = card["review"]
            if r["review_count"] <= 0:
                continue
            nxt = datetime.fromisoformat(r["next_review_at"])
            if nxt <= datetime(2026, 7, 8, 16, 0, tzinfo=timezone.utc):
                continue  # due 卡
            assert nxt > render_ceiling, card["content"]
            off = (_day(r["next_review_at"]) - ANCHOR).days
            assert 1 <= off <= plan["due_horizon_days"], card["content"]
            offsets.append(off)
        horizon = plan["due_horizon_days"]
        near = sum(1 for o in offsets if o <= horizon // 2)
        far = sum(1 for o in offsets if o > horizon // 2)
        assert near > far  # 遞減分佈：前半 horizon 多於後半


class TestConservation:
    def test_counters_and_non_review_fields_preserved(self):
        original = _spec()
        shaped = shape_history.shape(original, _plan())
        assert len(shaped["cards"]) == len(original["cards"])
        for before, after in zip(original["cards"], shaped["cards"]):
            for key in before:
                if key == "review":
                    continue
                assert before[key] == after[key], (before["content"], key)
            for counter in ("review_count", "review_streak", "lapse_count",
                            "last_review_feedback"):
                assert before["review"][counter] == after["review"][counter]
        assert shaped["notebooks"] == original["notebooks"]
        assert shaped["links"] == original["links"]

    def test_interval_equals_next_minus_last(self):
        shaped = shape_history.shape(_spec(), _plan())
        for card in shaped["cards"]:
            r = card["review"]
            if r["review_count"] <= 0:
                continue
            nxt = datetime.fromisoformat(r["next_review_at"])
            last = datetime.fromisoformat(r["last_reviewed_at"])
            hours = (nxt - last).total_seconds() / 3600
            assert nxt > last
            assert abs(hours - r["review_interval_hours"]) < 1e-4, card["content"]

    def test_reviewed_cards_keep_last_reviewed_roundtrip_invariant(self):
        shaped = shape_history.shape(_spec(), _plan())
        for card in shaped["cards"]:
            r = card["review"]
            if r["review_count"] > 0:
                assert r["last_reviewed_at"], card["content"]

    def test_new_cards_get_recent_dates_near_anchor(self):
        shaped = shape_history.shape(_spec(), _plan())
        for card in shaped["cards"]:
            r = card["review"]
            if r["review_count"] > 0:
                continue
            assert r["review_interval_hours"] == 12.0
            last = datetime.fromisoformat(r["last_reviewed_at"])
            nxt = datetime.fromisoformat(r["next_review_at"])
            assert nxt - last == timedelta(hours=12)
            assert 0 <= (ANCHOR - _day(r["last_reviewed_at"])).days <= 3


class TestFailLoud:
    def test_primary_too_thin_fails(self):
        spec = _spec(n_primary=5, n_other=2)  # 5 < 敘事日數 14
        with pytest.raises(shape_history.HistoryShapeError, match="primary"):
            shape_history.shape(spec, _plan())

    def test_reviewed_card_missing_last_reviewed_fails(self):
        spec = _spec()
        spec["cards"][0]["review"]["last_reviewed_at"] = None
        # 塑形無視輸入日期 → 不會炸在讀取；但輸入不變量仍要 fail-loud
        with pytest.raises(shape_history.HistoryShapeError, match="alpha000"):
            shape_history.shape(spec, _plan())

    def test_wrong_plan_schema_fails(self):
        with pytest.raises(shape_history.HistoryShapeError, match="schema"):
            shape_history.shape(_spec(), _plan(schema="kg.other.v1"))


class TestCommittedMarketingSpec:
    """committed spec v2 的 drift gate：塑形是冪等的，重跑必 byte 相等。"""

    @pytest.fixture()
    def committed(self) -> tuple[dict, dict]:
        spec = json.loads((MA_DIR / "marketing_account_spec.json").read_text("utf-8"))
        plan = json.loads((MA_DIR / "history_plan.json").read_text("utf-8"))
        return spec, plan

    def test_shape_is_idempotent_on_committed_spec(self, committed):
        spec, plan = committed
        reshaped = shape_history.shape(spec, plan)
        assert _dumps(reshaped) == _dumps(spec), (
            "committed marketing spec 與 shape_history 輸出 drift；"
            "重跑 shape_history.py 並 commit spec v2")

    def test_committed_spec_meets_narrative(self, committed):
        spec, plan = committed
        anchor = date.fromisoformat(plan["anchor_day"])
        for hours in plan["render_utc_offset_hours"]:
            days = _primary_event_days(spec, timedelta(hours=hours))
            current, longest = _streaks(days, anchor)
            assert current == plan["current_streak_days"], f"offset +{hours}"
            assert longest == plan["longest_streak_days"], f"offset +{hours}"
            assert days.get(anchor, 0) >= 1, f"offset +{hours}"
