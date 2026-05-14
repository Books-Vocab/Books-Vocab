"""Tests for kg.observability_alerts — threshold checks emit Sentry alerts."""
from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from kg import judge_log, observability_alerts, pipeline_log, translate_log


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolate_log_dbs(tmp_path, monkeypatch):
    """Point all log DBs at temp paths + reset connections.

    Also resets the in-memory cooldown state in observability_alerts.
    """
    # pipeline_log uses module-level DB_PATH
    monkeypatch.setattr(pipeline_log, "DB_PATH", tmp_path / "pipeline_runs.db")
    pipeline_log._reset()
    # judge_log uses module-level DB_PATH
    monkeypatch.setattr(judge_log, "DB_PATH", tmp_path / "judge_log.db")
    judge_log._reset()
    # translate_log uses _db_path() lookup via env var
    monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
    translate_log._reset()
    # Reset cooldown state (module-level dict)
    observability_alerts._cooldown_state.clear()
    yield
    pipeline_log._reset()
    judge_log._reset()
    translate_log._reset()
    observability_alerts._cooldown_state.clear()


class _SentryStub:
    """Lightweight replacement for sentry_sdk.capture_message — records calls."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def __call__(self, message: str, level: str = "info", **kwargs) -> None:
        # sentry_sdk.capture_message signature accepts level= kwarg.
        # tags must be set via with sentry_sdk.push_scope(); but we use the
        # simpler stub that just records everything passed.
        self.calls.append({"message": message, "level": level, **kwargs})


@pytest.fixture()
def sentry_stub(monkeypatch):
    """Replace observability_alerts._emit's capture_message reference."""
    stub = _SentryStub()
    monkeypatch.setattr(observability_alerts, "_capture_message", stub)
    return stub


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _insert_pipeline_run(run_id: str, status: str, started_minutes_ago: int) -> None:
    """Insert a finished pipeline_run with custom timestamps for window testing."""
    started = (datetime.now(UTC) - timedelta(minutes=started_minutes_ago)).isoformat()
    ended = (datetime.now(UTC) - timedelta(minutes=max(0, started_minutes_ago - 1))).isoformat()
    conn = pipeline_log._get_conn()
    conn.execute(
        "INSERT INTO pipeline_runs (run_id, user_id, notebook_id, trigger, "
        "started_at, ended_at, status, steps) VALUES (?, 'u1', 'nb1', 'manual', ?, ?, ?, '[]')",
        (run_id, started, ended, status),
    )
    conn.commit()


def _insert_judge_decision(*, accepted: bool, minutes_ago: int) -> None:
    created = (datetime.now(UTC) - timedelta(minutes=minutes_ago)).isoformat()
    conn = judge_log._get_conn()
    conn.execute(
        "INSERT INTO judge_log (user_id, notebook_id, from_id, to_id, similarity, "
        "verdict, confidence, accepted, reject_reason, reason, source, created_at) "
        "VALUES ('u1', 'nb1', 'a', 'b', 0.5, ?, 0.9, ?, ?, '', 'auto', ?)",
        ("accept" if accepted else "reject",
         int(accepted),
         None if accepted else "low_conf",
         created),
    )
    conn.commit()


def _insert_translate_log(*, latency_ms: int, minutes_ago: int) -> None:
    created = (datetime.now(UTC) - timedelta(minutes=minutes_ago)).isoformat()
    conn = translate_log._get_conn()
    conn.execute(
        "INSERT INTO translate_log (user_id, operation, word, context, context_hash, "
        "source_lang, target_lang, response_raw, latency_ms, created_at) "
        "VALUES ('u1', 'translate', 'w', '', 'h', 'en', 'zh', '{}', ?, ?)",
        (latency_ms, created),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# check_pipeline_failures
# ---------------------------------------------------------------------------


class TestCheckPipelineFailures:
    def test_under_threshold_does_not_alert(self, sentry_stub):
        for i in range(4):
            _insert_pipeline_run(f"r{i}", "failed", started_minutes_ago=10)
        observability_alerts.check_pipeline_failures(window_min=60, threshold=5)
        assert sentry_stub.calls == []

    def test_at_threshold_alerts(self, sentry_stub):
        for i in range(5):
            _insert_pipeline_run(f"r{i}", "failed", started_minutes_ago=10)
        observability_alerts.check_pipeline_failures(window_min=60, threshold=5)
        assert len(sentry_stub.calls) == 1
        call = sentry_stub.calls[0]
        assert call["level"] == "error"
        assert "pipeline" in call["message"].lower()
        tags = call.get("tags") or {}
        assert tags.get("pipeline_failures") == 5
        assert tags.get("alert") == "pipeline_failures"

    def test_above_threshold_alerts(self, sentry_stub):
        for i in range(8):
            _insert_pipeline_run(f"r{i}", "failed", started_minutes_ago=10)
        observability_alerts.check_pipeline_failures(window_min=60, threshold=5)
        assert len(sentry_stub.calls) == 1
        assert sentry_stub.calls[0]["tags"]["pipeline_failures"] == 8

    def test_completed_runs_ignored(self, sentry_stub):
        for i in range(10):
            _insert_pipeline_run(f"r{i}", "completed", started_minutes_ago=10)
        observability_alerts.check_pipeline_failures(window_min=60, threshold=5)
        assert sentry_stub.calls == []

    def test_runs_outside_window_ignored(self, sentry_stub):
        for i in range(10):
            _insert_pipeline_run(f"r{i}", "failed", started_minutes_ago=120)
        observability_alerts.check_pipeline_failures(window_min=60, threshold=5)
        assert sentry_stub.calls == []

    def test_interrupted_status_counted_as_failure(self, sentry_stub):
        for i in range(5):
            _insert_pipeline_run(f"r{i}", "interrupted", started_minutes_ago=5)
        observability_alerts.check_pipeline_failures(window_min=60, threshold=5)
        assert len(sentry_stub.calls) == 1


# ---------------------------------------------------------------------------
# check_judge_rejection_rate
# ---------------------------------------------------------------------------


class TestCheckJudgeRejectionRate:
    def test_low_volume_does_not_alert(self, sentry_stub):
        # 5 total, all rejected — should not alert (min_total=10)
        for _ in range(5):
            _insert_judge_decision(accepted=False, minutes_ago=10)
        observability_alerts.check_judge_rejection_rate(
            window_min=60, min_total=10, threshold=0.5,
        )
        assert sentry_stub.calls == []

    def test_acceptable_rate_does_not_alert(self, sentry_stub):
        for _ in range(8):
            _insert_judge_decision(accepted=True, minutes_ago=10)
        for _ in range(2):
            _insert_judge_decision(accepted=False, minutes_ago=10)
        # 20% reject — under 50% threshold
        observability_alerts.check_judge_rejection_rate(
            window_min=60, min_total=10, threshold=0.5,
        )
        assert sentry_stub.calls == []

    def test_high_rejection_rate_alerts(self, sentry_stub):
        for _ in range(3):
            _insert_judge_decision(accepted=True, minutes_ago=10)
        for _ in range(7):
            _insert_judge_decision(accepted=False, minutes_ago=10)
        # 70% reject — above 50% threshold
        observability_alerts.check_judge_rejection_rate(
            window_min=60, min_total=10, threshold=0.5,
        )
        assert len(sentry_stub.calls) == 1
        call = sentry_stub.calls[0]
        assert call["level"] == "warning"
        tags = call.get("tags") or {}
        assert tags.get("alert") == "judge_rejection_rate"
        assert tags.get("total") == 10
        assert tags.get("rejected") == 7
        # rejection_rate tag as a stringified float or float
        rate = float(tags.get("rejection_rate"))
        assert rate == pytest.approx(0.7, rel=1e-3)

    def test_at_exact_threshold_does_not_alert(self, sentry_stub):
        # > 0.5 required, so 5/10 = 0.5 must NOT alert (strict >)
        for _ in range(5):
            _insert_judge_decision(accepted=True, minutes_ago=10)
        for _ in range(5):
            _insert_judge_decision(accepted=False, minutes_ago=10)
        observability_alerts.check_judge_rejection_rate(
            window_min=60, min_total=10, threshold=0.5,
        )
        assert sentry_stub.calls == []

    def test_outside_window_ignored(self, sentry_stub):
        for _ in range(15):
            _insert_judge_decision(accepted=False, minutes_ago=120)
        observability_alerts.check_judge_rejection_rate(
            window_min=60, min_total=10, threshold=0.5,
        )
        assert sentry_stub.calls == []


# ---------------------------------------------------------------------------
# check_translate_latency_p95
# ---------------------------------------------------------------------------


class TestCheckTranslateLatencyP95:
    def test_low_volume_no_alert(self, sentry_stub):
        # Fewer than min sample size — caller might still skip; module decides.
        # We assert no alert for very small samples.
        for _ in range(3):
            _insert_translate_log(latency_ms=1000, minutes_ago=5)
        observability_alerts.check_translate_latency_p95(
            window_min=15, threshold_ms=5000,
        )
        assert sentry_stub.calls == []

    def test_p95_under_threshold_does_not_alert(self, sentry_stub):
        # 20 calls all under 2s
        for _ in range(20):
            _insert_translate_log(latency_ms=1500, minutes_ago=5)
        observability_alerts.check_translate_latency_p95(
            window_min=15, threshold_ms=5000,
        )
        assert sentry_stub.calls == []

    def test_p95_above_threshold_alerts(self, sentry_stub):
        # 20 calls: 18 fast, 2 slow ⇒ p95 falls in slow range
        for _ in range(18):
            _insert_translate_log(latency_ms=1000, minutes_ago=5)
        for _ in range(2):
            _insert_translate_log(latency_ms=8000, minutes_ago=5)
        observability_alerts.check_translate_latency_p95(
            window_min=15, threshold_ms=5000,
        )
        assert len(sentry_stub.calls) == 1
        call = sentry_stub.calls[0]
        assert call["level"] == "warning"
        tags = call.get("tags") or {}
        assert tags.get("alert") == "translate_latency_p95"
        assert int(tags.get("p95_ms")) >= 5000

    def test_outside_window_ignored(self, sentry_stub):
        for _ in range(20):
            _insert_translate_log(latency_ms=10000, minutes_ago=60)
        observability_alerts.check_translate_latency_p95(
            window_min=15, threshold_ms=5000,
        )
        assert sentry_stub.calls == []


# ---------------------------------------------------------------------------
# Cooldown
# ---------------------------------------------------------------------------


class TestCooldown:
    def test_same_alert_suppressed_within_cooldown(self, sentry_stub):
        for i in range(6):
            _insert_pipeline_run(f"r{i}", "failed", started_minutes_ago=10)
        observability_alerts.check_pipeline_failures(window_min=60, threshold=5)
        observability_alerts.check_pipeline_failures(window_min=60, threshold=5)
        observability_alerts.check_pipeline_failures(window_min=60, threshold=5)
        assert len(sentry_stub.calls) == 1

    def test_cooldown_expires_after_window(self, sentry_stub, monkeypatch):
        for i in range(6):
            _insert_pipeline_run(f"r{i}", "failed", started_minutes_ago=10)
        observability_alerts.check_pipeline_failures(window_min=60, threshold=5)
        assert len(sentry_stub.calls) == 1
        # Travel forward in time past cooldown.
        future = datetime.now(UTC) + timedelta(minutes=31)

        class _Clock:
            @staticmethod
            def now(tz=None):
                return future

        monkeypatch.setattr(observability_alerts, "_now", lambda: future)
        observability_alerts.check_pipeline_failures(window_min=60, threshold=5)
        assert len(sentry_stub.calls) == 2

    def test_different_alerts_have_independent_cooldown(self, sentry_stub):
        # Pipeline failure alert fires
        for i in range(6):
            _insert_pipeline_run(f"r{i}", "failed", started_minutes_ago=10)
        observability_alerts.check_pipeline_failures(window_min=60, threshold=5)
        # Judge rejection alert should still fire independently
        for _ in range(3):
            _insert_judge_decision(accepted=True, minutes_ago=10)
        for _ in range(7):
            _insert_judge_decision(accepted=False, minutes_ago=10)
        observability_alerts.check_judge_rejection_rate(
            window_min=60, min_total=10, threshold=0.5,
        )
        assert len(sentry_stub.calls) == 2
        alerts = {c["tags"]["alert"] for c in sentry_stub.calls}
        assert alerts == {"pipeline_failures", "judge_rejection_rate"}


# ---------------------------------------------------------------------------
# run_all + sentry-not-available guard
# ---------------------------------------------------------------------------


class TestRunAll:
    def test_run_all_invokes_three_checks(self, monkeypatch, sentry_stub):
        called: list[str] = []
        monkeypatch.setattr(
            observability_alerts, "check_pipeline_failures",
            lambda **kw: called.append("pipeline"),
        )
        monkeypatch.setattr(
            observability_alerts, "check_judge_rejection_rate",
            lambda **kw: called.append("judge"),
        )
        monkeypatch.setattr(
            observability_alerts, "check_translate_latency_p95",
            lambda **kw: called.append("translate"),
        )
        observability_alerts.run_all_checks()
        assert called == ["pipeline", "judge", "translate"]

    def test_run_all_swallows_exceptions(self, monkeypatch):
        def _boom(**kw):
            raise RuntimeError("db unavailable")
        monkeypatch.setattr(observability_alerts, "check_pipeline_failures", _boom)
        monkeypatch.setattr(observability_alerts, "check_judge_rejection_rate", _boom)
        monkeypatch.setattr(observability_alerts, "check_translate_latency_p95", _boom)
        # Must not raise — alerts are best-effort.
        observability_alerts.run_all_checks()


class TestSentryGuard:
    def test_emit_no_op_when_sentry_unavailable(self, monkeypatch):
        # Even if check decides to alert, missing sentry_sdk should not crash.
        monkeypatch.setattr(observability_alerts, "_capture_message", None)
        for i in range(6):
            _insert_pipeline_run(f"r{i}", "failed", started_minutes_ago=10)
        # Should be a no-op (no exception, no Sentry call).
        observability_alerts.check_pipeline_failures(window_min=60, threshold=5)


class TestSystemInfoTriggersChecks:
    """`/api/system/info` is the chosen trigger surface — verify it fires checks."""

    def test_system_info_invokes_run_all_checks(self, monkeypatch):
        from fastapi.testclient import TestClient

        from kg.api import app
        from kg.routers import system as system_router

        called: list[bool] = []
        monkeypatch.setattr(
            system_router.observability_alerts,
            "run_all_checks",
            lambda: called.append(True),
        )

        with TestClient(app) as client:
            r = client.get("/api/system/info")
        assert r.status_code == 200, r.text
        assert called == [True]

    def test_system_info_unaffected_by_checks_exception(self, monkeypatch):
        from fastapi.testclient import TestClient

        from kg.api import app
        from kg.routers import system as system_router

        def _boom() -> None:
            raise RuntimeError("checks blew up")

        monkeypatch.setattr(
            system_router.observability_alerts, "run_all_checks", _boom
        )

        with TestClient(app) as client:
            r = client.get("/api/system/info")
        assert r.status_code == 200, r.text
