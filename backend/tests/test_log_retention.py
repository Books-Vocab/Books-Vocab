"""Tests for log_retention module — prune old rows from the 4 log SQLite singletons."""

from __future__ import annotations

import json
import subprocess
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from kg import judge_log, log_retention, pipeline_log, token_tracker, translate_log

# ─────────────────────────────────────────────────────────────────────────────
# Fixtures — redirect every log DB into tmp_path and reset singletons.
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture()
def isolated_logs(tmp_path, monkeypatch):
    monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))

    pipeline_log.DATA_DIR = tmp_path
    pipeline_log.DB_PATH = tmp_path / "pipeline_runs.db"
    judge_log.DATA_DIR = tmp_path
    judge_log.DB_PATH = tmp_path / "judge_log.db"
    token_tracker.DATA_DIR = tmp_path
    token_tracker.DB_PATH = tmp_path / "token_usage.db"
    # translate_log resolves path via _db_path() each connect — env var alone is enough.

    pipeline_log._reset()
    judge_log._reset()
    translate_log._reset()
    if token_tracker._conn is not None:
        token_tracker._conn.close()
        token_tracker._conn = None

    yield tmp_path

    pipeline_log._reset()
    judge_log._reset()
    translate_log._reset()
    if token_tracker._conn is not None:
        token_tracker._conn.close()
        token_tracker._conn = None


def _iso(days_ago: float) -> str:
    return (datetime.now(UTC) - timedelta(days=days_ago)).isoformat()


# ─────────────────────────────────────────────────────────────────────────────
# pipeline_log
# ─────────────────────────────────────────────────────────────────────────────


def _insert_pipeline_row(started_at: str, run_id: str | None = None) -> None:
    conn = pipeline_log._get_conn()
    conn.execute(
        "INSERT INTO pipeline_runs (run_id, user_id, notebook_id, trigger, started_at, ended_at, status, steps) "
        "VALUES (?, ?, ?, ?, ?, ?, 'completed', '[]')",
        (run_id or "r_" + uuid.uuid4().hex[:8], "u1", "nb1", "auto", started_at, started_at),
    )
    conn.commit()


def test_prune_pipeline_log_drops_only_old_rows(isolated_logs):
    _insert_pipeline_row(_iso(40))   # old
    _insert_pipeline_row(_iso(31))   # old
    _insert_pipeline_row(_iso(29))   # recent
    _insert_pipeline_row(_iso(1))    # recent

    deleted, remaining = log_retention.prune_pipeline_log(days=30)

    assert deleted == 2
    assert remaining == 2
    count = pipeline_log._get_conn().execute("SELECT COUNT(*) FROM pipeline_runs").fetchone()[0]
    assert count == 2


def test_prune_pipeline_log_noop_when_empty(isolated_logs):
    deleted, remaining = log_retention.prune_pipeline_log(days=30)
    assert deleted == 0
    assert remaining == 0


def test_prune_pipeline_log_preserves_index(isolated_logs):
    _insert_pipeline_row(_iso(40))
    log_retention.prune_pipeline_log(days=30)
    rows = pipeline_log._get_conn().execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='pipeline_runs'"
    ).fetchall()
    names = {r[0] for r in rows}
    assert "idx_pr_started" in names


# ─────────────────────────────────────────────────────────────────────────────
# judge_log
# ─────────────────────────────────────────────────────────────────────────────


def _insert_judge_row(created_at: str) -> None:
    conn = judge_log._get_conn()
    conn.execute(
        "INSERT INTO judge_log (user_id, notebook_id, from_id, to_id, similarity, "
        "verdict, confidence, accepted, source, created_at) "
        "VALUES ('u1', 'nb1', 'a', 'b', 0.8, 'related', 0.9, 1, 'auto', ?)",
        (created_at,),
    )
    conn.commit()


def test_prune_judge_log_drops_only_old_rows(isolated_logs):
    _insert_judge_row(_iso(80))   # old
    _insert_judge_row(_iso(61))   # old
    _insert_judge_row(_iso(59))   # recent
    _insert_judge_row(_iso(1))    # recent

    deleted, remaining = log_retention.prune_judge_log(days=60)

    assert deleted == 2
    assert remaining == 2


def test_prune_judge_log_preserves_index(isolated_logs):
    _insert_judge_row(_iso(80))
    log_retention.prune_judge_log(days=60)
    rows = judge_log._get_conn().execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='judge_log'"
    ).fetchall()
    names = {r[0] for r in rows}
    assert "idx_jl_created" in names


# ─────────────────────────────────────────────────────────────────────────────
# translate_log
# ─────────────────────────────────────────────────────────────────────────────


def _insert_translate_row(created_at: str) -> None:
    conn = translate_log._get_conn()
    conn.execute(
        "INSERT INTO translate_log (user_id, operation, word, context, context_hash, "
        "source_lang, target_lang, response_raw, latency_ms, created_at) "
        "VALUES ('u1', 'translate', 'word', 'ctx', 'h', 'en', 'zh', '{}', 100, ?)",
        (created_at,),
    )
    conn.commit()


def test_prune_translate_log_drops_only_old_rows(isolated_logs):
    _insert_translate_row(_iso(20))   # old
    _insert_translate_row(_iso(15))   # old
    _insert_translate_row(_iso(13))   # recent
    _insert_translate_row(_iso(1))    # recent

    deleted, remaining = log_retention.prune_translate_log(days=14)

    assert deleted == 2
    assert remaining == 2


def test_prune_translate_log_preserves_index(isolated_logs):
    _insert_translate_row(_iso(30))
    log_retention.prune_translate_log(days=14)
    rows = translate_log._get_conn().execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='translate_log'"
    ).fetchall()
    names = {r[0] for r in rows}
    assert "idx_tl_cache" in names
    assert "idx_tl_user" in names


# ─────────────────────────────────────────────────────────────────────────────
# token_usage
# ─────────────────────────────────────────────────────────────────────────────


def _insert_token_row(created_at: str) -> None:
    conn = token_tracker._get_conn()
    conn.execute(
        "INSERT INTO token_usage (user_id, call_type, input_tokens, output_tokens, created_at) "
        "VALUES ('u1', 'translate', 100, 50, ?)",
        (created_at,),
    )
    conn.commit()


def test_prune_token_usage_drops_only_old_rows(isolated_logs):
    _insert_token_row(_iso(120))   # old
    _insert_token_row(_iso(91))    # old
    _insert_token_row(_iso(89))    # recent
    _insert_token_row(_iso(1))     # recent

    deleted, remaining = log_retention.prune_token_usage(days=90)

    assert deleted == 2
    assert remaining == 2


def test_prune_token_usage_preserves_index(isolated_logs):
    _insert_token_row(_iso(120))
    log_retention.prune_token_usage(days=90)
    rows = token_tracker._get_conn().execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='token_usage'"
    ).fetchall()
    names = {r[0] for r in rows}
    assert "idx_user_created" in names


# ─────────────────────────────────────────────────────────────────────────────
# run_all
# ─────────────────────────────────────────────────────────────────────────────


def test_run_all_invokes_every_pruner(isolated_logs):
    _insert_pipeline_row(_iso(40))
    _insert_judge_row(_iso(80))
    _insert_translate_row(_iso(20))
    _insert_token_row(_iso(120))

    report = log_retention.run_all()

    assert report["pipeline_log"]["deleted"] == 1
    assert report["judge_log"]["deleted"] == 1
    assert report["translate_log"]["deleted"] == 1
    assert report["token_usage"]["deleted"] == 1
    # Defaults must match brief.
    assert report["pipeline_log"]["days"] == 30
    assert report["judge_log"]["days"] == 60
    assert report["translate_log"]["days"] == 14
    assert report["token_usage"]["days"] == 90


# ─────────────────────────────────────────────────────────────────────────────
# CLI entry
# ─────────────────────────────────────────────────────────────────────────────


def _cli_env(data_dir: Path) -> dict[str, str]:
    """subprocess env that exposes the in-tree ``kg`` package on PYTHONPATH."""
    src_dir = Path(__file__).resolve().parents[1] / "src"
    existing = __import__("os").environ
    extra_paths = [str(src_dir)]
    if existing.get("PYTHONPATH"):
        extra_paths.append(existing["PYTHONPATH"])
    return {
        **existing,
        "PYTHONPATH": ":".join(extra_paths),
        "KG_DATA_DIR": str(data_dir),
    }


def test_cli_all_flag_runs_every_pruner(isolated_logs):
    _insert_pipeline_row(_iso(40))
    _insert_judge_row(_iso(80))
    _insert_translate_row(_iso(20))
    _insert_token_row(_iso(120))

    pipeline_log._reset()
    judge_log._reset()
    translate_log._reset()
    if token_tracker._conn is not None:
        token_tracker._conn.close()
        token_tracker._conn = None

    result = subprocess.run(
        [sys.executable, "-m", "kg.log_retention", "--all", "--json"],
        capture_output=True,
        text=True,
        env=_cli_env(isolated_logs),
    )
    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout)
    assert out["pipeline_log"]["deleted"] == 1
    assert out["judge_log"]["deleted"] == 1
    assert out["translate_log"]["deleted"] == 1
    assert out["token_usage"]["deleted"] == 1


def test_cli_selective_flag(isolated_logs):
    _insert_pipeline_row(_iso(40))
    _insert_judge_row(_iso(80))

    pipeline_log._reset()
    judge_log._reset()

    result = subprocess.run(
        [sys.executable, "-m", "kg.log_retention", "--pipeline", "--days", "30", "--json"],
        capture_output=True,
        text=True,
        env=_cli_env(isolated_logs),
    )
    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout)
    assert "pipeline_log" in out
    assert out["pipeline_log"]["deleted"] == 1
    # Judge should NOT be touched.
    assert "judge_log" not in out


# ─────────────────────────────────────────────────────────────────────────────
# Admin endpoint
# ─────────────────────────────────────────────────────────────────────────────


TEST_JWT_SECRET = "test-secret-key-for-ci-at-least-32-bytes"
ADMIN_TOKEN = "test-admin-token-log-retention"


def _swap_settings(new_settings):
    from kg.api import app
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
    from kg.api import app
    from kg.settings import KGSettings

    (tmp_path / "users").mkdir()
    users_file = tmp_path / "users.json"
    users_file.write_text(json.dumps({"_meta": {}}))

    monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
    pipeline_log.DATA_DIR = tmp_path
    pipeline_log.DB_PATH = tmp_path / "pipeline_runs.db"
    judge_log.DATA_DIR = tmp_path
    judge_log.DB_PATH = tmp_path / "judge_log.db"
    token_tracker.DATA_DIR = tmp_path
    token_tracker.DB_PATH = tmp_path / "token_usage.db"
    pipeline_log._reset()
    judge_log._reset()
    translate_log._reset()
    if token_tracker._conn is not None:
        token_tracker._conn.close()
        token_tracker._conn = None

    original_settings = app.state.kg_settings
    test_settings = KGSettings(
        data_dir=tmp_path,
        jwt_secret=TEST_JWT_SECRET,
        admin_token=ADMIN_TOKEN,
    )
    _swap_settings(test_settings)

    try:
        client = TestClient(app, raise_server_exceptions=False)
        yield SimpleNamespace(client=client, data_dir=tmp_path)
    finally:
        app.state.kg_settings = original_settings
        pipeline_log._reset()
        judge_log._reset()
        translate_log._reset()
        if token_tracker._conn is not None:
            token_tracker._conn.close()
            token_tracker._conn = None


def test_admin_endpoint_requires_auth(admin_app):
    resp = admin_app.client.post("/api/admin/log-retention/run")
    assert resp.status_code == 403


def test_admin_endpoint_runs_all_pruners(admin_app):
    _insert_pipeline_row(_iso(40))
    _insert_judge_row(_iso(80))
    _insert_translate_row(_iso(20))
    _insert_token_row(_iso(120))

    resp = admin_app.client.post(
        "/api/admin/log-retention/run",
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["pipeline_log"]["deleted"] == 1
    assert body["judge_log"]["deleted"] == 1
    assert body["translate_log"]["deleted"] == 1
    assert body["token_usage"]["deleted"] == 1


# ─────────────────────────────────────────────────────────────────────────────
# Env-driven retention windows + empty-table safety + admin response shape
# ─────────────────────────────────────────────────────────────────────────────


def test_prune_judge_log_respects_retention_days_env(isolated_logs, monkeypatch):
    """``JUDGE_LOG_RETENTION_DAYS`` env var must drive ``prune_judge_log()``
    default window when caller does not pass ``days=``."""
    monkeypatch.setenv("JUDGE_LOG_RETENTION_DAYS", "7")

    for _ in range(5):
        _insert_judge_row(_iso(8))   # 8 days ago → must be pruned under 7d window
    for _ in range(5):
        _insert_judge_row(_iso(0))   # today → must survive

    deleted, remaining = log_retention.prune_judge_log()  # uses env default

    assert deleted == 5
    assert remaining == 5


def test_prune_translate_log_safe_with_no_data(isolated_logs):
    """Pruning an empty translate_log table must not raise and must report 0/0."""
    # Force schema creation without inserting any rows.
    translate_log._get_conn()

    deleted, remaining = log_retention.prune_translate_log(days=14)

    assert deleted == 0
    assert remaining == 0


def test_admin_trigger_prune_endpoint_returns_counts(admin_app):
    """Admin trigger endpoint returns deletion counts under flat keys
    (``judge_deleted`` / ``translate_deleted`` / ``pipeline_deleted``) and 403 without auth."""
    # No auth → 403.
    resp_no_auth = admin_app.client.post("/api/admin/log-retention/run")
    assert resp_no_auth.status_code == 403

    _insert_pipeline_row(_iso(40))
    _insert_judge_row(_iso(80))
    _insert_translate_row(_iso(20))

    resp = admin_app.client.post(
        "/api/admin/log-retention/run",
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["pipeline_deleted"] == 1
    assert body["judge_deleted"] == 1
    assert body["translate_deleted"] == 1
