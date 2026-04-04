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


def test_acceptance_stats(tmp_path, monkeypatch):
    """get_acceptance_stats returns correct rate from auto judge decisions."""
    monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))

    import importlib
    from kg import judge_log
    importlib.reload(judge_log)
    judge_log._reset()

    # Empty DB
    stats = judge_log.get_acceptance_stats()
    assert stats["total"] == 0
    assert stats["rate"] is None

    # 2 accepted, 1 rejected
    for accepted, verdict in [(True, "shares_usage"), (True, "contrasts_with"), (False, "not_applicable")]:
        judge_log.record(
            user_id="u1", notebook_id="nb1", from_id="a", to_id="b",
            similarity=0.8, verdict=verdict, confidence=0.9,
            accepted=accepted, source="auto",
        )

    # 1 manual (should be excluded from stats)
    judge_log.record(
        user_id="u1", notebook_id="nb1", from_id="a", to_id="c",
        similarity=None, verdict="shares_usage", confidence=1.0,
        accepted=True, source="manual",
    )

    stats = judge_log.get_acceptance_stats()
    assert stats["total"] == 3
    assert stats["accepted"] == 2
    assert stats["rejected"] == 1
    assert abs(stats["rate"] - 0.6667) < 0.001

    judge_log._reset()


def test_acceptance_stats_per_user(tmp_path, monkeypatch):
    """get_acceptance_stats with user_id filters to that user only."""
    monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))

    import importlib
    from kg import judge_log
    importlib.reload(judge_log)
    judge_log._reset()

    # u1: 2 accepted, 1 rejected
    for accepted, verdict in [(True, "shares_usage"), (True, "contrasts_with"), (False, "not_applicable")]:
        judge_log.record(
            user_id="u1", notebook_id="nb1", from_id="a", to_id="b",
            similarity=0.8, verdict=verdict, confidence=0.9,
            accepted=accepted, source="auto",
        )
    # u2: 1 accepted
    judge_log.record(
        user_id="u2", notebook_id="nb1", from_id="x", to_id="y",
        similarity=0.7, verdict="shares_usage", confidence=0.85,
        accepted=True, source="auto",
    )

    s1 = judge_log.get_acceptance_stats(user_id="u1")
    assert s1["total"] == 3
    assert s1["accepted"] == 2
    assert abs(s1["rate"] - 0.6667) < 0.001

    s2 = judge_log.get_acceptance_stats(user_id="u2")
    assert s2["total"] == 1
    assert s2["accepted"] == 1
    assert s2["rate"] == 1.0

    sg = judge_log.get_acceptance_stats()
    assert sg["total"] == 4

    s3 = judge_log.get_acceptance_stats(user_id="u_nobody")
    assert s3["total"] == 0
    assert s3["rate"] is None

    judge_log._reset()
