"""Tests for /api/admin/observability — site-wide aggregation panel."""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest

ADMIN_TOKEN = "test-admin-token-observability"
EXPECTED_ADMIN_APP_CLIENTS = 17
admin_app_constructed = 0
admin_app_explicit_close = 0


@pytest.fixture(scope="module", autouse=True)
def assert_admin_app_client_lifecycle():
    yield
    assert admin_app_constructed == EXPECTED_ADMIN_APP_CLIENTS
    assert admin_app_explicit_close == EXPECTED_ADMIN_APP_CLIENTS


@pytest.fixture()
def admin_app(admin_app_factory):
    global admin_app_constructed, admin_app_explicit_close

    harness = admin_app_factory(admin_token=ADMIN_TOKEN, setup_log_dbs=True)
    admin_app_constructed += 1
    client_close = MagicMock(wraps=harness.client.close)
    harness.client.close = client_close
    try:
        yield harness
    finally:
        harness.client.close()
        client_close.assert_called_once_with()
        admin_app_explicit_close += 1


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


def test_observability_response_declares_utc_tz(admin_app):
    body = _get(admin_app.client).json()
    assert body["tz"] == "UTC"


# ── log_db_health (row_count + oldest) ────────────────────────────────────


def test_observability_log_db_health_keys_present(admin_app):
    body = _get(admin_app.client).json()
    health = body["log_db_health"]
    for table in (
        "pipeline_runs",
        "judge_log",
        "translate_log",
        "translate_cache_hits",
        "token_usage",
    ):
        assert table in health, f"missing table: {table}"
        assert "row_count" in health[table]
        assert "oldest_created_at" in health[table]


def test_observability_log_db_health_empty(admin_app):
    body = _get(admin_app.client).json()
    health = body["log_db_health"]
    assert health["judge_log"]["row_count"] == 0
    assert health["judge_log"]["oldest_created_at"] is None
    assert health["token_usage"]["row_count"] == 0


def test_observability_log_db_health_counts_rows(admin_app):
    import kg.judge_log as jl
    import kg.pipeline_log as pl
    import kg.token_tracker as tt

    pl.start_run("h1", "u1", "nb1", "manual")
    pl.end_run("h1", "ok")
    jl.record(
        user_id="u1", notebook_id="nb1", from_id="a", to_id="b",
        similarity=0.5, verdict="merge", confidence=0.9, accepted=True,
    )
    jl.record(
        user_id="u1", notebook_id="nb1", from_id="c", to_id="d",
        similarity=0.5, verdict="merge", confidence=0.9, accepted=False,
    )
    tt.record("u1", "translate", 10, 20)

    body = _get(admin_app.client).json()
    health = body["log_db_health"]
    assert health["pipeline_runs"]["row_count"] == 1
    assert health["judge_log"]["row_count"] == 2
    assert health["token_usage"]["row_count"] == 1
    # oldest_created_at populated once rows exist
    assert health["judge_log"]["oldest_created_at"] is not None
    assert health["token_usage"]["oldest_created_at"] is not None


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


def test_admin_observability_judge_rejection_rate_excludes_degree_cap(admin_app):
    """``_judge_rejection_rate_24h`` measures **model** decisions on the
    admin /observability panel. Rows with ``reject_reason='degree_cap'``
    are pipeline cap evictions (not model rejections) and must be excluded
    from both numerator and denominator — mirroring ``get_acceptance_stats``.

    Seed: 5 model rejects + 3 degree_cap rejects + 2 accepted →
    panel rate must be 5/(5+2)=5/7, NOT 5/10 or 8/10.
    """
    import kg.judge_log as jl

    # 2 model-accepted
    for i in range(2):
        jl.record(
            user_id="u_obs", notebook_id="nb",
            from_id="a", to_id=f"acc_{i}",
            similarity=0.8, verdict="shares_usage", confidence=0.9,
            accepted=True,
        )
    # 5 model-rejected
    for i in range(5):
        jl.record(
            user_id="u_obs", notebook_id="nb",
            from_id="a", to_id=f"rej_{i}",
            similarity=0.6, verdict="not_applicable", confidence=0.3,
            accepted=False, reject_reason="low_confidence",
        )
    # 3 degree_cap rejects — must NOT affect rate
    for i in range(3):
        jl.record(
            user_id="u_obs", notebook_id="nb",
            from_id="a", to_id=f"cap_{i}",
            similarity=0.85, verdict="shares_usage", confidence=0.9,
            accepted=False, reject_reason="degree_cap",
        )

    body = _get(admin_app.client).json()
    m = body["judge_rejection_rate_24h"]
    # 2 accepted + 5 model rejected; 3 cap rows excluded.
    assert m["total"] == 7
    assert m["rejected"] == 5
    assert m["rate"] == pytest.approx(5 / 7, abs=1e-3)


# ── translate_cache_hit_rate_24h ──────────────────────────────────────────


def test_translate_cache_hit_rate_uses_real_counter(admin_app):
    """Hits come from translate_cache_hits counter; misses from translate_log rows."""
    import kg.translate_log as tl

    # 2 misses recorded (each = 1 LLM call)
    tl.record(
        user_id="u1", operation="translate_quick",
        word="apple", context="I ate an apple.",
        context_hash="hash_apple",
        source_lang="en", target_lang="zh-Hant",
        response_raw='{"t":"蘋果"}', latency_ms=100,
    )
    tl.record(
        user_id="u2", operation="translate_quick",
        word="banana", context="I ate a banana.",
        context_hash="hash_banana",
        source_lang="en", target_lang="zh-Hant",
        response_raw='{"t":"香蕉"}', latency_ms=100,
    )
    # 3 cache hits (short-circuited, never reach record())
    for _ in range(3):
        tl.record_cache_hit(
            user_id="u1", operation="translate_quick",
            word="apple", context_hash="hash_apple",
            source_lang="en", target_lang="zh-Hant",
        )

    body = _get(admin_app.client).json()
    m = body["translate_cache_hit_rate_24h"]
    # total = hits + misses = 3 + 2 = 5; hit rate = 3/5 = 0.6
    assert m["hits"] == 3
    assert m["misses"] == 2
    assert m["total"] == 5
    assert m["rate"] == pytest.approx(0.6, abs=1e-3)


def test_translate_cache_hit_rate_empty_returns_none_rate(admin_app):
    body = _get(admin_app.client).json()
    m = body["translate_cache_hit_rate_24h"]
    assert m["hits"] == 0
    assert m["misses"] == 0
    assert m["total"] == 0
    assert m["rate"] is None


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
