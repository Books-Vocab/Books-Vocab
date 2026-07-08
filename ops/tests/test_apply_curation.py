from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
MA_DIR = ROOT / "ops" / "demo" / "marketing_account"


def _load_module(name: str):
    spec = importlib.util.spec_from_file_location(name, MA_DIR / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(MA_DIR))
    try:
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
    finally:
        try:
            sys.path.remove(str(MA_DIR))
        except ValueError:
            pass
    return module


apply_curation = _load_module("apply_curation")

ANCHOR = "2026-07-08T00:00:00+00:00"


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _card(word: str, nb: str = "詞彙本", *, count: int = 3, last_days_ago: int = 30,
          next_days: int = -5) -> dict:
    """next_days < 0 ⇒ 相對 anchor 已過期。"""
    anchor = datetime.fromisoformat(ANCHOR)
    review = {
        "review_count": count,
        "review_streak": min(count, 2),
        "lapse_count": 0,
        "review_interval_hours": 24.0,
        "next_review_at": _iso(anchor + timedelta(days=next_days)),
        "last_reviewed_at": _iso(anchor - timedelta(days=last_days_ago)),
        "last_review_feedback": 1,
    }
    if count == 0:
        review = {
            "review_count": 0, "review_streak": 0, "lapse_count": 0,
            "review_interval_hours": 12.0, "next_review_at": None,
            "last_reviewed_at": None, "last_review_feedback": -1,
        }
    return {
        "content": word, "pos": "n.", "meaning": f"{word} 的意思", "examples": [],
        "collocations": [], "note": "n", "difficulty": 3.0, "mode": "recognition",
        "root_form": None, "inflections": [], "is_archived": False,
        "notebook": nb, "review": review,
    }


def _spec() -> dict:
    return {
        "schema": "kg.seed_spec.v1",
        "notebooks": [{"name": "詞彙本", "color": None, "cover_pattern": None,
                       "sort_order": 0, "is_default": True}],
        "cards": [
            _card("alpha", last_days_ago=1),      # 巨型分量成員(a-b 相連)
            _card("beta", last_days_ago=2),
            _card("gamma", last_days_ago=3),      # 孤立、過期
            _card("delta", last_days_ago=4),      # 孤立、過期
            _card("fresh", count=0),              # new 卡
            _card("nsfw-word", last_days_ago=9),  # 將被剔除,連著 alpha
        ],
        "links": [
            {"from": "alpha", "to": "beta", "kind": "semantic",
             "confidence": 0.9, "reason": "r", "notebook": "詞彙本"},
            {"from": "alpha", "to": "nsfw-word", "kind": "semantic",
             "confidence": 0.9, "reason": "r", "notebook": "詞彙本"},
        ],
    }


def _plan() -> dict:
    return {
        "schema": "kg.curation_plan.v1",
        "notebooks": ["人物群像", "敘事筆法"],
        "remove": [{"word": "nsfw-word", "reason": "explicit"}],
        "assign": {"alpha": "人物群像", "beta": "人物群像", "gamma": "敘事筆法",
                   "delta": "敘事筆法", "fresh": "敘事筆法"},
    }


NB_META = {
    "人物群像": {"color": "#8C6A5D", "cover_pattern": "waves", "is_default": True},
    "敘事筆法": {"color": "#6B7A8F", "cover_pattern": "lines", "is_default": False},
}


def _run(spec=None, plan=None, target_due=1):
    return apply_curation.apply(
        spec if spec is not None else _spec(),
        plan if plan is not None else _plan(),
        notebook_meta=NB_META, anchor=ANCHOR, target_due=target_due,
    )


class TestCoverageAndNotebooks:
    def test_removed_cards_and_their_links_are_gone(self):
        out = _run()
        words = {c["content"] for c in out["cards"]}
        assert "nsfw-word" not in words
        assert len(out["cards"]) == 5
        assert all("nsfw-word" not in (l["from"], l["to"]) for l in out["links"])
        assert len(out["links"]) == 1

    def test_notebooks_rebuilt_with_meta_and_single_default(self):
        out = _run()
        nbs = {n["name"]: n for n in out["notebooks"]}
        assert set(nbs) == {"人物群像", "敘事筆法"}
        assert nbs["人物群像"]["is_default"] is True
        assert nbs["人物群像"]["cover_pattern"] == "waves"
        assert nbs["敘事筆法"]["is_default"] is False
        assert [n["sort_order"] for n in out["notebooks"]] == [0, 1]

    def test_cards_and_links_follow_assignment(self):
        out = _run()
        nb_of = {c["content"]: c["notebook"] for c in out["cards"]}
        assert nb_of["alpha"] == "人物群像" and nb_of["gamma"] == "敘事筆法"
        (link,) = out["links"]
        assert link["notebook"] == "人物群像"

    def test_unassigned_card_fails_loud(self):
        plan = _plan()
        del plan["assign"]["delta"]
        with pytest.raises(apply_curation.CurationError, match="delta"):
            _run(plan=plan)

    def test_cross_notebook_link_fails_loud(self):
        plan = _plan()
        plan["assign"]["beta"] = "敘事筆法"  # 拆散 alpha-beta 分量
        with pytest.raises(apply_curation.CurationError, match="alpha"):
            _run(plan=plan)


class TestReviewRebalance:
    def test_due_count_capped_at_target(self):
        out = _run(target_due=1)
        anchor = datetime.fromisoformat(ANCHOR)
        due = [c for c in out["cards"]
               if c["review"]["review_count"] > 0
               and datetime.fromisoformat(c["review"]["next_review_at"]) <= anchor]
        assert len(due) == 1
        # 最近複習者優先保留 due
        assert due[0]["content"] == "alpha"

    def test_deferred_cards_keep_interval_consistency(self):
        out = _run(target_due=1)
        anchor = datetime.fromisoformat(ANCHOR)
        for c in out["cards"]:
            r = c["review"]
            if r["review_count"] == 0 or c["content"] == "alpha":
                continue  # new 卡與「保留 due」的卡不被改寫，原值不動
            nxt = datetime.fromisoformat(r["next_review_at"])
            last = datetime.fromisoformat(r["last_reviewed_at"])
            got = (nxt - last).total_seconds() / 3600
            assert abs(got - r["review_interval_hours"]) < 0.01, c["content"]
            assert nxt > anchor
        # 未改動的卡保持原值（連原本的不自洽都保留——轉換不越權「修」資料）
        (alpha,) = [c for c in out["cards"] if c["content"] == "alpha"]
        assert alpha["review"]["review_interval_hours"] == 24.0

    def test_new_cards_untouched(self):
        out = _run()
        (fresh,) = [c for c in out["cards"] if c["content"] == "fresh"]
        assert fresh["review"]["review_count"] == 0
        assert fresh["review"]["next_review_at"] is None

    def test_deterministic_byte_stable(self):
        a = json.dumps(_run(), ensure_ascii=False, sort_keys=True)
        b = json.dumps(_run(), ensure_ascii=False, sort_keys=True)
        assert a == b


class TestEdgeCases:
    def test_reviewed_card_missing_last_reviewed_fails_loud(self):
        spec = _spec()
        (gamma,) = [c for c in spec["cards"] if c["content"] == "gamma"]
        gamma["review"]["last_reviewed_at"] = None
        with pytest.raises(apply_curation.CurationError, match="gamma"):
            _run(spec=spec)

    def test_spread_days_zero_fails_loud(self):
        with pytest.raises(apply_curation.CurationError, match="spread_days"):
            apply_curation.apply(_spec(), _plan(), notebook_meta=NB_META,
                                 anchor=ANCHOR, target_due=1, spread_days=0)

    def test_target_due_exceeding_overdue_is_noop(self):
        out = _run(target_due=99)
        # 全部過期卡維持 due，無卡被重排
        anchor = datetime.fromisoformat(ANCHOR)
        due = [c for c in out["cards"]
               if c["review"]["review_count"] > 0
               and datetime.fromisoformat(c["review"]["next_review_at"]) <= anchor]
        assert len(due) == 4

    def test_empty_plan_on_empty_spec_ok(self):
        spec = _spec()
        spec["cards"] = []
        spec["links"] = []
        plan = {"schema": "kg.curation_plan.v1", "notebooks": [], "remove": [],
                "assign": {}}
        out = apply_curation.apply(spec, plan, notebook_meta=NB_META,
                                   anchor=ANCHOR, target_due=1)
        assert out["cards"] == [] and out["links"] == []
