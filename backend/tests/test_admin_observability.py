"""Tests for /api/admin/observability — site-wide aggregation panel."""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from kg.api import app
from kg.settings import KGSettings

TEST_JWT_SECRET = "test-secret-key-for-ci-at-least-32-bytes"
ADMIN_TOKEN = "test-admin-token-observability"


def _swap_settings(new_settings):
    from kg.billing import default_subscription_payload
    from kg.user_store import CachedUserStore, normalize_users_payload

    app.state.kg_settings = new_settings

    def _normalize(users):
        from kg.secret_store import encrypt_value
        jwt_secret = app.state.kg_settings.jwt_secret
        encrypt_fn = (lambda v: encrypt_value(v, jwt_secret)) if jwt_secret else None
        return normalize_users_payload(users, default_subscription_payload, encrypt_fn=encrypt_fn)

    user_store = CachedUserStore(new_settings.users_file, _normalize)
    app.state.user_store = user_store
    app.state.load_users = lambda: user_store.load()
    app.state.save_users = lambda users: user_store.save(users)


def _reset_log_singletons():
    """Reset SQLite singletons so each test starts with a clean db."""
    import kg.pipeline_log as pl
    import kg.judge_log as jl
    import kg.token_tracker as tt
    pl._reset()
    jl._reset()
    tt._reset() if hasattr(tt, "_reset") else None


@pytest.fixture()
def admin_app(tmp_path, monkeypatch):
    data_dir = tmp_path
    (data_dir / "users").mkdir()
    users_file = data_dir / "users.json"
    users_file.write_text(json.dumps({"_meta": {}}))

    # Redirect ALL log dbs to tmp_path
    monkeypatch.setenv("KG_DATA_DIR", str(data_dir))
    import kg.pipeline_log as pl
    import kg.judge_log as jl
    import kg.token_tracker as tt
    pl.DATA_DIR = data_dir
    pl.DB_PATH = data_dir / "pipeline_runs.db"
    jl.DATA_DIR = data_dir
    jl.DB_PATH = data_dir / "judge_log.db"
    tt.DATA_DIR = data_dir
    tt.DB_PATH = data_dir / "token_usage.db"
    pl._reset()
    jl._reset()
    if hasattr(tt, "_reset"):
        tt._reset()
    else:
        # token_tracker has no _reset; manually close
        if tt._conn is not None:
            tt._conn.close()
            tt._conn = None

    original_settings = app.state.kg_settings
    test_settings = KGSettings(
        data_dir=data_dir,
        jwt_secret=TEST_JWT_SECRET,
        admin_token=ADMIN_TOKEN,
    )
    _swap_settings(test_settings)

    try:
        client = TestClient(app, raise_server_exceptions=False)
        yield SimpleNamespace(client=client, data_dir=data_dir)
    finally:
        app.state.kg_settings = original_settings
        pl._reset()
        jl._reset()
        if tt._conn is not None:
            tt._conn.close()
            tt._conn = None


# ── auth boundary ─────────────────────────────────────────────────────────


def test_observability_unauthenticated_returns_403(admin_app):
    resp = admin_app.client.get("/api/admin/observability")
    assert resp.status_code == 403


def test_observability_wrong_token_returns_403(admin_app):
    resp = admin_app.client.get(
        "/api/admin/observability",
        headers={"Authorization": "Bearer wrong-token"},
    )
    assert resp.status_code == 403


def test_observability_with_admin_token_returns_200(admin_app):
    resp = admin_app.client.get(
        "/api/admin/observability",
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
    )
    assert resp.status_code == 200


# ── response shape ────────────────────────────────────────────────────────


def _get(client):
    return client.get(
        "/api/admin/observability",
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
    )


def test_observability_response_has_required_keys(admin_app):
    body = _get(admin_app.client).json()
    for key in [
        "translate_cache_hit_rate_24h",
        "pipeline_step_p95_24h",
        "pipeline_failure_rate_24h",
        "judge_rejection_rate_24h",
        "daily_token_spend_7d",
        "generated_at",
    ]:
        assert key in body, f"missing key: {key}"


def test_observability_empty_data_returns_zero_or_null_metrics(admin_app):
    body = _get(admin_app.client).json()
    # No data → cache hit rate should be None or 0 (no calls to measure)
    assert body["translate_cache_hit_rate_24h"]["total"] == 0
    assert body["pipeline_failure_rate_24h"]["total"] == 0
    assert body["judge_rejection_rate_24h"]["total"] == 0
    assert body["pipeline_step_p95_24h"]["steps"] == []
    # 7 daily buckets even when empty
    assert len(body["daily_token_spend_7d"]["days"]) == 7


# ── pipeline_failure_rate_24h ─────────────────────────────────────────────


def test_pipeline_failure_rate_counts_failed_vs_total(admin_app):
    import kg.pipeline_log as pl
    pl.start_run("r1", "u1", "nb1", "manual")
    pl.end_run("r1", "ok")
    pl.start_run("r2", "u1", "nb1", "manual")
    pl.end_run("r2", "failed")
    pl.start_run("r3", "u1", "nb1", "manual")
    pl.end_run("r3", "failed")

    body = _get(admin_app.client).json()
    m = body["pipeline_failure_rate_24h"]
    assert m["total"] == 3
    assert m["failed"] == 2
    assert m["rate"] == pytest.approx(2 / 3, abs=1e-3)


def test_pipeline_failure_rate_excludes_old_runs(admin_app):
    import kg.pipeline_log as pl
    pl.start_run("old", "u1", "nb1", "manual")
    pl.end_run("old", "failed")
    # Hand-edit started_at to 48h ago
    conn = pl._get_conn()
    long_ago = (datetime.now(UTC) - timedelta(hours=48)).isoformat()
    conn.execute("UPDATE pipeline_runs SET started_at = ? WHERE run_id = 'old'", (long_ago,))
    conn.commit()
    pl.start_run("new", "u1", "nb1", "manual")
    pl.end_run("new", "ok")

    body = _get(admin_app.client).json()
    m = body["pipeline_failure_rate_24h"]
    assert m["total"] == 1  # only "new" counted
    assert m["failed"] == 0


# ── pipeline_step_p95_24h ─────────────────────────────────────────────────


def test_pipeline_step_p95_returns_per_step_durations(admin_app):
    import kg.pipeline_log as pl
    # Build 10 runs with explicit step durations for "judge" step
    durations_ms = [100, 200, 300, 400, 500, 600, 700, 800, 900, 1000]
    base = datetime.now(UTC)
    for i, dur in enumerate(durations_ms):
        run_id = f"r{i}"
        pl.start_run(run_id, "u1", "nb1", "manual")
        # Inject a step with controlled duration via direct DB edit
        started = (base - timedelta(seconds=10)).isoformat()
        ended = (base - timedelta(seconds=10) + timedelta(milliseconds=dur)).isoformat()
        steps = [{"name": "judge", "status": "ok", "started_at": started, "ended_at": ended, "items": 1, "error": None}]
        conn = pl._get_conn()
        conn.execute("UPDATE pipeline_runs SET steps = ? WHERE run_id = ?", (json.dumps(steps), run_id))
        conn.commit()
        pl.end_run(run_id, "ok")

    body = _get(admin_app.client).json()
    steps = body["pipeline_step_p95_24h"]["steps"]
    assert len(steps) == 1
    judge = steps[0]
    assert judge["name"] == "judge"
    assert judge["count"] == 10
    # p95 of 10..1000 step series (nearest-rank): 950 or 1000 — accept anything in [900,1000]
    assert 900 <= judge["p95_ms"] <= 1000


# ── judge_rejection_rate_24h ──────────────────────────────────────────────


def test_judge_rejection_rate_24h(admin_app):
    import kg.judge_log as jl
    # 3 accepted, 1 rejected → rejection rate = 0.25
    for i in range(3):
        jl.record(
            user_id="u1", notebook_id="nb1",
            from_id=f"a{i}", to_id=f"b{i}",
            similarity=0.8, verdict="accept", confidence=0.9, accepted=True,
        )
    jl.record(
        user_id="u1", notebook_id="nb1",
        from_id="x", to_id="y",
        similarity=0.5, verdict="reject", confidence=0.9, accepted=False,
        reject_reason="below_threshold",
    )

    body = _get(admin_app.client).json()
    m = body["judge_rejection_rate_24h"]
    assert m["total"] == 4
    assert m["rejected"] == 1
    assert m["rate"] == pytest.approx(0.25, abs=1e-3)


# ── translate_cache_hit_rate_24h ──────────────────────────────────────────


def test_translate_cache_hit_rate_uses_dedup_logic(admin_app):
    import kg.translate_log as tl
    # 1 distinct query repeated 3 times = 2 cache hits out of 3 calls = 66.7%
    for _ in range(3):
        tl.record(
            user_id="u1", operation="translate_quick",
            word="apple", context="I ate an apple.",
            context_hash="hash_apple",
            source_lang="en", target_lang="zh-Hant",
            response_raw='{"t":"蘋果"}', latency_ms=100,
        )
    # 1 unique additional query — total 4 calls, 3 distinct → hits = 1
    tl.record(
        user_id="u2", operation="translate_quick",
        word="banana", context="I ate a banana.",
        context_hash="hash_banana",
        source_lang="en", target_lang="zh-Hant",
        response_raw='{"t":"香蕉"}', latency_ms=100,
    )

    body = _get(admin_app.client).json()
    m = body["translate_cache_hit_rate_24h"]
    assert m["total"] == 4
    assert m["distinct"] == 2  # apple + banana
    assert m["hits"] == 2  # 4 - 2
    assert m["rate"] == pytest.approx(0.5, abs=1e-3)


# ── daily_token_spend_7d ──────────────────────────────────────────────────


def test_daily_token_spend_7d_returns_7_buckets(admin_app):
    import kg.token_tracker as tt
    tt.record("u1", "translate_quick", 100, 50)
    tt.record("u2", "translate_explain", 200, 80)

    body = _get(admin_app.client).json()
    days = body["daily_token_spend_7d"]["days"]
    assert len(days) == 7
    # Today's bucket should hold our records
    today_total = sum(d["tokens"] for d in days if d["tokens"] > 0)
    assert today_total == 100 + 50 + 200 + 80
