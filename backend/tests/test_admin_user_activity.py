"""Tests for admin_user_activity — unified recent-activity timeline."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest


@pytest.fixture()
def activity_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Isolate translate_log + pipeline_log + judge_log under tmp_path."""
    monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
    import kg.judge_log as jl
    import kg.pipeline_log as pl
    import kg.translate_log as tl

    # pipeline_log + judge_log resolve DB_PATH at module load → patch them.
    monkeypatch.setattr(pl, "DATA_DIR", tmp_path, raising=True)
    monkeypatch.setattr(pl, "DB_PATH", tmp_path / "pipeline_runs.db", raising=True)
    monkeypatch.setattr(jl, "DATA_DIR", tmp_path, raising=True)
    monkeypatch.setattr(jl, "DB_PATH", tmp_path / "judge_log.db", raising=True)

    tl._reset()
    pl._reset()
    jl._reset()
    try:
        yield tmp_path
    finally:
        tl._reset()
        pl._reset()
        jl._reset()


def _record_translate(user_id: str, *, word: str, when: datetime) -> None:
    """Insert a translate_log row at a specific timestamp (bypasses record())."""
    import kg.translate_log as tl

    with tl._lock:
        conn = tl._get_conn()
        conn.execute(
            "INSERT INTO translate_log (user_id, operation, word, context, context_hash,"
            " source_lang, target_lang, response_raw, latency_ms, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            (user_id, "translate_quick", word, "", "h_" + word, "en", "zh-Hant",
             '{"t":"x"}', 5, when.isoformat()),
        )
        conn.commit()


def _record_pipeline(user_id: str, *, run_id: str, when: datetime, status: str = "ok") -> None:
    import kg.pipeline_log as pl

    with pl._lock:
        conn = pl._get_conn()
        conn.execute(
            "INSERT INTO pipeline_runs (run_id, user_id, notebook_id, trigger,"
            " started_at, ended_at, status, steps) VALUES (?,?,?,?,?,?,?, '[]')",
            (run_id, user_id, "default", "manual", when.isoformat(),
             (when + timedelta(seconds=2)).isoformat(), status),
        )
        conn.commit()


def _record_judge(user_id: str, *, when: datetime, accepted: bool = True) -> None:
    import kg.judge_log as jl

    with jl._lock:
        conn = jl._get_conn()
        conn.execute(
            "INSERT INTO judge_log (user_id, notebook_id, from_id, to_id, similarity,"
            " verdict, confidence, accepted, reject_reason, reason, source, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (user_id, "default", "c1", "c2", 0.8, "accept", 0.9,
             int(accepted), None, "", "auto", when.isoformat()),
        )
        conn.commit()


# ---------------------------------------------------------------------------
# get_user_activity unit tests
# ---------------------------------------------------------------------------

def test_empty_returns_empty_events(activity_env):
    from kg.admin_user_activity import get_user_activity

    result = get_user_activity("u1", hours=24)
    assert result["user_id"] == "u1"
    assert result["hours"] == 24
    assert result["events"] == []
    assert result["counts"] == {"translate": 0, "pipeline": 0, "judge": 0}


def test_merges_three_sources_sorted_desc(activity_env):
    from kg.admin_user_activity import get_user_activity

    now = datetime.now(UTC)
    _record_translate("u1", word="apple", when=now - timedelta(minutes=10))
    _record_pipeline("u1", run_id="r1", when=now - timedelta(minutes=5))
    _record_judge("u1", when=now - timedelta(minutes=20))

    result = get_user_activity("u1", hours=24)
    assert len(result["events"]) == 3
    types = [e["type"] for e in result["events"]]
    # Newest first: pipeline (5m) → translate (10m) → judge (20m)
    assert types == ["pipeline", "translate", "judge"]
    assert result["counts"] == {"translate": 1, "pipeline": 1, "judge": 1}


def test_window_excludes_old_events(activity_env):
    from kg.admin_user_activity import get_user_activity

    now = datetime.now(UTC)
    _record_translate("u1", word="recent", when=now - timedelta(hours=1))
    _record_translate("u1", word="old", when=now - timedelta(hours=48))

    result = get_user_activity("u1", hours=24)
    words = [e.get("word") for e in result["events"] if e["type"] == "translate"]
    assert words == ["recent"]


def test_isolates_user(activity_env):
    from kg.admin_user_activity import get_user_activity

    now = datetime.now(UTC)
    _record_translate("u1", word="apple", when=now - timedelta(minutes=1))
    _record_translate("u2", word="banana", when=now - timedelta(minutes=1))
    _record_pipeline("u2", run_id="r2", when=now - timedelta(minutes=1))

    result = get_user_activity("u1", hours=24)
    assert len(result["events"]) == 1
    assert result["events"][0]["word"] == "apple"


def test_translate_event_shape(activity_env):
    from kg.admin_user_activity import get_user_activity

    now = datetime.now(UTC)
    _record_translate("u1", word="hello", when=now - timedelta(minutes=1))

    result = get_user_activity("u1", hours=24)
    ev = result["events"][0]
    assert ev["type"] == "translate"
    assert ev["word"] == "hello"
    assert ev["operation"] == "translate_quick"
    assert "created_at" in ev


def test_pipeline_event_shape(activity_env):
    from kg.admin_user_activity import get_user_activity

    now = datetime.now(UTC)
    _record_pipeline("u1", run_id="run-xyz", when=now - timedelta(minutes=2), status="ok")

    result = get_user_activity("u1", hours=24)
    ev = result["events"][0]
    assert ev["type"] == "pipeline"
    assert ev["run_id"] == "run-xyz"
    assert ev["status"] == "ok"
    assert "created_at" in ev


def test_judge_event_shape(activity_env):
    from kg.admin_user_activity import get_user_activity

    now = datetime.now(UTC)
    _record_judge("u1", when=now - timedelta(minutes=2), accepted=False)

    result = get_user_activity("u1", hours=24)
    ev = result["events"][0]
    assert ev["type"] == "judge"
    assert ev["accepted"] is False
    assert "created_at" in ev


def test_hours_clamp_to_max(activity_env):
    """hours must be clamped to <= 168 (7 days)."""
    from kg.admin_user_activity import get_user_activity

    result = get_user_activity("u1", hours=10000)
    assert result["hours"] == 168


def test_hours_min_one(activity_env):
    """hours must be >= 1."""
    from kg.admin_user_activity import get_user_activity

    result = get_user_activity("u1", hours=0)
    assert result["hours"] == 1
    result2 = get_user_activity("u1", hours=-5)
    assert result2["hours"] == 1


def test_caps_total_events(activity_env):
    """Even with many rows, response is capped (no unbounded scan dump)."""
    from kg.admin_user_activity import get_user_activity

    now = datetime.now(UTC)
    for i in range(600):
        _record_translate("u1", word=f"w{i}", when=now - timedelta(seconds=i + 1))

    result = get_user_activity("u1", hours=24)
    assert len(result["events"]) <= 500
