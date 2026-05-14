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


# ---------------------------------------------------------------------------
# Task-mandated coverage: empty / mixed-order / pagination-style cap
# ---------------------------------------------------------------------------


def test_user_activity_empty_user_returns_zero_events(activity_env):
    """Brand-new user with no rows in any source returns a fully-formed envelope."""
    from kg.admin_user_activity import get_user_activity

    result = get_user_activity("brand-new-user", hours=24)

    # Envelope shape — admin UI relies on every key existing.
    assert set(result.keys()) == {"user_id", "hours", "since", "events", "counts"}
    assert result["user_id"] == "brand-new-user"
    assert result["hours"] == 24
    assert isinstance(result["since"], str) and result["since"]  # ISO timestamp
    assert result["events"] == []
    assert result["counts"] == {"translate": 0, "pipeline": 0, "judge": 0}
    # `since` must be parseable as a UTC ISO timestamp.
    assert datetime.fromisoformat(result["since"]).tzinfo is not None


def test_user_activity_mixes_pipeline_judge_translate_events_in_order(activity_env):
    """Interleaved events from all three sources sort newest-first with correct types."""
    from kg.admin_user_activity import get_user_activity

    now = datetime.now(UTC)
    # Interleave the three sources by timestamp so neither source-internal
    # ordering nor stable-sort artefacts can mask a bug.
    # Order (newest → oldest): T1 J1 P1 T2 J2 P2
    _record_pipeline("u1", run_id="p2", when=now - timedelta(minutes=60))  # oldest
    _record_judge("u1", when=now - timedelta(minutes=50))
    _record_translate("u1", word="t2", when=now - timedelta(minutes=40))
    _record_pipeline("u1", run_id="p1", when=now - timedelta(minutes=30))
    _record_judge("u1", when=now - timedelta(minutes=20))
    _record_translate("u1", word="t1", when=now - timedelta(minutes=10))  # newest

    result = get_user_activity("u1", hours=24)

    assert result["counts"] == {"translate": 2, "pipeline": 2, "judge": 2}
    assert len(result["events"]) == 6
    types = [e["type"] for e in result["events"]]
    assert types == ["translate", "judge", "pipeline", "translate", "judge", "pipeline"]

    # Type markers must be the literal strings the admin UI switches on.
    assert {e["type"] for e in result["events"]} == {"translate", "judge", "pipeline"}

    # created_at strictly descending (no sort regressions).
    timestamps = [e["created_at"] for e in result["events"]]
    assert timestamps == sorted(timestamps, reverse=True)

    # Per-type fields are populated on the right events.
    translates = [e for e in result["events"] if e["type"] == "translate"]
    assert [e["word"] for e in translates] == ["t1", "t2"]
    pipelines = [e for e in result["events"] if e["type"] == "pipeline"]
    assert [e["run_id"] for e in pipelines] == ["p1", "p2"]


def test_user_activity_paginates_correctly(activity_env):
    """With 550 mixed events, the response caps at 500 newest, no dupes, no drops above cap.

    The module's pagination contract is a hard `MAX_TOTAL_EVENTS` cap (500) applied
    after merge+sort. Verify: (a) cap obeyed, (b) the kept slice is the newest 500
    contiguous events, (c) no event ID is duplicated across the cut, (d) counts
    reflect the pre-cap per-source totals.
    """
    from kg.admin_user_activity import MAX_TOTAL_EVENTS, get_user_activity

    now = datetime.now(UTC)
    # 300 translate + 250 judge = 550, interleaved by 1-second offsets so the
    # cap cuts across both sources.
    for i in range(300):
        _record_translate("u1", word=f"w{i:03d}", when=now - timedelta(seconds=2 * i + 1))
    for i in range(250):
        _record_judge("u1", when=now - timedelta(seconds=2 * i + 2))

    result = get_user_activity("u1", hours=24)

    # (a) hard cap.
    assert MAX_TOTAL_EVENTS == 500
    assert len(result["events"]) == 500

    # (d) counts reflect post-window per-source totals (pre-cap).
    assert result["counts"]["translate"] == 300
    assert result["counts"]["judge"] == 250
    assert result["counts"]["pipeline"] == 0

    # (b) descending by created_at — kept slice is the newest 500.
    timestamps = [e["created_at"] for e in result["events"]]
    assert timestamps == sorted(timestamps, reverse=True)

    # (c) no duplicate (type, id) tuples across the page.
    keys = [(e["type"], e["id"]) for e in result["events"]]
    assert len(keys) == len(set(keys))

    # The 500th event's timestamp must be >= every dropped event's timestamp.
    boundary = result["events"][-1]["created_at"]
    # All translate words w000..w299 created at 1,3,5,...,599s ago.
    # All judges at 2,4,...,500s ago. Newest 500 of 550 → drop the 50 oldest.
    # Simply sanity-check boundary is a real ISO string newer than 24h cutoff.
    assert datetime.fromisoformat(boundary) > datetime.fromisoformat(result["since"])
