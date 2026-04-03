"""Tests for judge_log module."""

from __future__ import annotations

import threading


def test_record_and_retrieve(tmp_path, monkeypatch):
    """Insert accepted decision, verify all fields round-trip."""
    monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))

    # Force reimport with fresh env
    import importlib
    from kg import judge_log
    importlib.reload(judge_log)
    judge_log._reset()

    judge_log.record(
        user_id="u1",
        notebook_id="nb1",
        from_id="card_a",
        to_id="card_b",
        similarity=0.85,
        verdict="shares_usage",
        confidence=0.92,
        accepted=True,
        reject_reason=None,
        reason="兩詞都描述光澤",
        source="auto",
    )

    rows = judge_log.get_log("u1")
    assert len(rows) == 1
    r = rows[0]
    assert r["user_id"] == "u1"
    assert r["notebook_id"] == "nb1"
    assert r["from_id"] == "card_a"
    assert r["to_id"] == "card_b"
    assert abs(r["similarity"] - 0.85) < 1e-6
    assert r["verdict"] == "shares_usage"
    assert abs(r["confidence"] - 0.92) < 1e-6
    assert r["accepted"] is True
    assert r["reject_reason"] is None
    assert r["reason"] == "兩詞都描述光澤"
    assert r["source"] == "auto"
    assert r["created_at"]  # non-empty timestamp

    judge_log._reset()


def test_record_rejection(tmp_path, monkeypatch):
    """Insert rejected decision, verify reject_reason stored."""
    monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))

    import importlib
    from kg import judge_log
    importlib.reload(judge_log)
    judge_log._reset()

    judge_log.record(
        user_id="u1",
        notebook_id="nb1",
        from_id="card_a",
        to_id="card_c",
        similarity=0.72,
        verdict="not_applicable",
        confidence=0.3,
        accepted=False,
        reject_reason="low_confidence",
        reason="無明顯關聯",
        source="auto",
    )

    rows = judge_log.get_log("u1")
    assert len(rows) == 1
    r = rows[0]
    assert r["accepted"] is False
    assert r["reject_reason"] == "low_confidence"
    assert r["verdict"] == "not_applicable"

    # Test notebook filter
    rows2 = judge_log.get_log("u1", notebook_id="nb1")
    assert len(rows2) == 1
    rows3 = judge_log.get_log("u1", notebook_id="other")
    assert len(rows3) == 0

    judge_log._reset()
