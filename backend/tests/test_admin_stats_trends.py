"""Tests for /api/admin/stats/trends — 30-day global trend buckets."""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from kg.api import app
from kg.settings import KGSettings

TEST_JWT_SECRET = "test-secret-key-for-ci-at-least-32-bytes"
ADMIN_TOKEN = "test-admin-token-stats-trends"


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


@pytest.fixture()
def admin_app(tmp_path, monkeypatch):
    data_dir = tmp_path
    (data_dir / "users").mkdir()
    users_file = data_dir / "users.json"
    users_file.write_text(json.dumps({"_meta": {}}))

    monkeypatch.setenv("KG_DATA_DIR", str(data_dir))
    import kg.judge_log as jl
    import kg.pipeline_log as pl
    import kg.token_tracker as tt

    pl.DATA_DIR = data_dir
    pl.DB_PATH = data_dir / "pipeline_runs.db"
    jl.DATA_DIR = data_dir
    jl.DB_PATH = data_dir / "judge_log.db"
    tt.DATA_DIR = data_dir
    tt.DB_PATH = data_dir / "token_usage.db"
    pl._reset()
    jl._reset()
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


def _get(client, **params):
    qs = "&".join(f"{k}={v}" for k, v in params.items())
    url = "/api/admin/stats/trends" + (f"?{qs}" if qs else "")
    return client.get(url, headers={"Authorization": f"Bearer {ADMIN_TOKEN}"})


# ── auth boundary ─────────────────────────────────────────────────────────


def test_trends_unauthenticated_returns_403(admin_app):
    resp = admin_app.client.get("/api/admin/stats/trends")
    assert resp.status_code == 403


def test_trends_wrong_token_returns_403(admin_app):
    resp = admin_app.client.get(
        "/api/admin/stats/trends",
        headers={"Authorization": "Bearer wrong-token"},
    )
    assert resp.status_code == 403


def test_trends_with_admin_token_returns_200(admin_app):
    resp = _get(admin_app.client)
    assert resp.status_code == 200


# ── shape ────────────────────────────────────────────────────────────────


def test_trends_shape_30_buckets_aligned(admin_app):
    body = _get(admin_app.client).json()
    for key in (
        "window_days",
        "days",
        "errors_per_day",
        "tokens_per_day",
        "active_users_per_day",
        "call_types",
        "generated_at",
    ):
        assert key in body, f"missing key: {key}"
    assert body["window_days"] == 30
    assert len(body["days"]) == 30
    assert len(body["errors_per_day"]) == 30
    assert len(body["tokens_per_day"]) == 30
    assert len(body["active_users_per_day"]) == 30
    # token entries must each have date + total
    for entry in body["tokens_per_day"]:
        assert "date" in entry
        assert "total" in entry
    # days must be sorted ascending (oldest first)
    assert body["days"] == sorted(body["days"])
    # last day should be today UTC
    today_iso = datetime.now(UTC).date().isoformat()
    assert body["days"][-1] == today_iso


def test_trends_empty_data_returns_all_zero(admin_app):
    body = _get(admin_app.client).json()
    assert all(v == 0 for v in body["errors_per_day"])
    assert all(v == 0 for v in body["active_users_per_day"])
    assert all(t["total"] == 0 for t in body["tokens_per_day"])
    assert body["call_types"] == []


# ── data flow ────────────────────────────────────────────────────────────


def test_trends_counts_pipeline_failures_and_judge_rejects_today(admin_app):
    import kg.judge_log as jl
    import kg.pipeline_log as pl

    # 2 failed pipeline runs today + 1 success (not counted)
    pl.start_run("p_fail1", "u1", "nb1", "manual")
    pl.end_run("p_fail1", "failed")
    pl.start_run("p_fail2", "u2", "nb1", "manual")
    pl.end_run("p_fail2", "failed")
    pl.start_run("p_ok", "u1", "nb1", "manual")
    pl.end_run("p_ok", "ok")

    # 3 judge rejects (auto)
    for i in range(3):
        jl.record(
            user_id="u1", notebook_id="nb1",
            from_id=f"a{i}", to_id=f"b{i}",
            similarity=0.3, verdict="reject", confidence=0.9,
            accepted=False, reject_reason="below",
        )
    # 1 accepted (not counted as error)
    jl.record(
        user_id="u1", notebook_id="nb1",
        from_id="x", to_id="y",
        similarity=0.9, verdict="accept", confidence=0.9, accepted=True,
    )

    body = _get(admin_app.client).json()
    # Last bucket = today
    assert body["errors_per_day"][-1] == 2 + 3


def test_trends_tokens_breakdown_by_call_type(admin_app):
    import kg.token_tracker as tt

    tt.record("u1", "translate_quick", 100, 50)
    tt.record("u2", "judge", 200, 80)
    tt.record("u3", "translate_quick", 30, 20)

    body = _get(admin_app.client).json()
    call_types = body["call_types"]
    assert "translate_quick" in call_types
    assert "judge" in call_types

    today_bucket = body["tokens_per_day"][-1]
    assert today_bucket["translate_quick"] == 100 + 50 + 30 + 20
    assert today_bucket["judge"] == 200 + 80
    assert today_bucket["total"] == 100 + 50 + 30 + 20 + 200 + 80


def test_trends_active_users_distinct_count(admin_app):
    import kg.token_tracker as tt

    # 3 distinct users today; one user records twice
    tt.record("u1", "translate_quick", 10, 5)
    tt.record("u1", "judge", 20, 10)
    tt.record("u2", "translate_quick", 10, 5)
    tt.record("u3", "judge", 10, 5)

    body = _get(admin_app.client).json()
    assert body["active_users_per_day"][-1] == 3


def test_trends_window_excludes_old_data(admin_app):
    """Rows older than 30 days must not appear in any series."""
    import sqlite3
    import kg.token_tracker as tt
    import kg.pipeline_log as pl

    # Insert one normal row today, then back-date one record to 45 days ago
    tt.record("u1", "translate_quick", 100, 50)
    old_iso = (datetime.now(UTC) - timedelta(days=45)).isoformat()
    with tt._lock:
        conn = tt._get_conn()
        conn.execute(
            "INSERT INTO token_usage (user_id, call_type, input_tokens, output_tokens, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("u_old", "translate_quick", 999, 999, old_iso),
        )
        conn.commit()

    # Pipeline failure backdated 45 days
    pl.start_run("old_fail", "u_old", "nb1", "manual")
    pl.end_run("old_fail", "failed")
    with pl._lock:
        conn = pl._get_conn()
        conn.execute(
            "UPDATE pipeline_runs SET started_at = ? WHERE run_id = 'old_fail'",
            (old_iso,),
        )
        conn.commit()

    body = _get(admin_app.client).json()
    # Sum totals across the 30 buckets — must NOT include old record
    total_tokens = sum(t["total"] for t in body["tokens_per_day"])
    assert total_tokens == 100 + 50  # only today's record counted
    total_errors = sum(body["errors_per_day"])
    assert total_errors == 0  # old failure excluded


def test_trends_supports_custom_window(admin_app):
    body = _get(admin_app.client, days=7).json()
    assert body["window_days"] == 7
    assert len(body["days"]) == 7
    assert len(body["errors_per_day"]) == 7
    assert len(body["tokens_per_day"]) == 7
    assert len(body["active_users_per_day"]) == 7


def test_trends_window_clamped_to_max(admin_app):
    body = _get(admin_app.client, days=500).json()
    # MAX_WINDOW_DAYS = 90
    assert body["window_days"] == 90
    assert len(body["days"]) == 90
