"""Integration tests: judge_log + Judge / ManualLinkJudge."""

from __future__ import annotations

import importlib
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
    from kg import judge_log
    importlib.reload(judge_log)
    judge_log._reset()
    yield
    judge_log._reset()


def _make_llm(response_content: str, user_id: str = "u1"):
    """Build a mock TrackedLLM that returns given content."""
    llm = MagicMock()
    llm.user_id = user_id
    choice = SimpleNamespace(message=SimpleNamespace(content=response_content))
    llm.chat.return_value = SimpleNamespace(choices=[choice])
    return llm


# ── Batch Judge ──────────────────────────────────────────

def test_batch_judge_logs_all_decisions():
    from kg.judge import Judge
    from kg import judge_log

    resp = json.dumps([
        {"word": "bright", "link": "shares_usage", "confidence": 0.9, "reason": "兩詞都描述光澤"},
        {"word": "dull", "link": "not_applicable", "confidence": 0.8, "reason": "無關"},
        {"word": "dim", "link": "contrasts_with", "confidence": 0.5, "reason": "對比但低信心"},
    ])
    llm = _make_llm(resp)
    judge = Judge(llm, user_id="u1", notebook_id="nb1")

    candidates = [
        ("c1", "bright", "明亮"),
        ("c2", "dull", "暗淡"),
        ("c3", "dim", "昏暗"),
    ]
    results = judge.evaluate_batch("shiny", "閃亮", candidates, from_id="f1", similarities={"c1": 0.9, "c2": 0.7, "c3": 0.6})

    rows = judge_log.get_log("u1")
    assert len(rows) == 3

    by_to = {r["to_id"]: r for r in rows}
    # c1: accepted
    assert by_to["c1"]["accepted"] is True
    assert by_to["c1"]["verdict"] == "shares_usage"
    assert by_to["c1"]["reject_reason"] is None
    assert by_to["c1"]["similarity"] == pytest.approx(0.9)
    # c2: not_applicable
    assert by_to["c2"]["accepted"] is False
    assert by_to["c2"]["reject_reason"] == "not_applicable"
    # c3: low_confidence
    assert by_to["c3"]["accepted"] is False
    assert by_to["c3"]["reject_reason"] == "low_confidence"


def test_single_evaluate_logs():
    from kg.judge import Judge
    from kg import judge_log

    resp = json.dumps([
        {"word": "bright", "link": "shares_usage", "confidence": 0.9, "reason": "相關"},
    ])
    llm = _make_llm(resp)
    judge = Judge(llm, user_id="u1", notebook_id="nb1")

    judge.evaluate("shiny", "閃亮", "bright", "明亮", from_id="f1", to_id="c1", similarity=0.85)

    rows = judge_log.get_log("u1")
    assert len(rows) == 1
    assert rows[0]["from_id"] == "f1"
    assert rows[0]["to_id"] == "_single"  # thin wrapper uses _single as card_id


# ── ManualLinkJudge ──────────────────────────────────────

def test_manual_judge_logs():
    from kg.judge import ManualLinkJudge
    from kg import judge_log

    resp = json.dumps({"link": "contrasts_with", "confidence": 0.95, "reason": "對比詞"})
    llm = _make_llm(resp)
    judge = ManualLinkJudge(llm, user_id="u1", notebook_id="nb1")

    result = judge.evaluate("hot", "熱", "cold", "冷", from_id="f1", to_id="t1")
    assert result.link == "contrasts_with"

    rows = judge_log.get_log("u1")
    assert len(rows) == 1
    r = rows[0]
    assert r["source"] == "manual"
    assert r["accepted"] is True
    assert r["from_id"] == "f1"
    assert r["to_id"] == "t1"


def test_manual_judge_parse_error_logs():
    from kg.judge import ManualLinkJudge
    from kg import judge_log

    llm = _make_llm("NOT JSON AT ALL")
    judge = ManualLinkJudge(llm, user_id="u1", notebook_id="nb1")

    result = judge.evaluate("hot", "熱", "cold", "冷", from_id="f1", to_id="t1")
    assert result.link == "shares_usage"  # fallback

    rows = judge_log.get_log("u1")
    assert len(rows) == 1
    r = rows[0]
    assert r["source"] == "manual"
    assert r["accepted"] is True
