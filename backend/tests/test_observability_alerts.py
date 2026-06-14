"""Tests for kg.observability_alerts — threshold checks emit Sentry alerts."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from kg import (
    judge_log,
    llm_error_log,
    observability_alerts,
    pipeline_log,
    translate_log,
)

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
    # llm_error_log uses module-level DB_PATH
    monkeypatch.setattr(llm_error_log, "DB_PATH", tmp_path / "llm_errors.db")
    llm_error_log._reset()
    # Reset cooldown state (module-level dict)
    observability_alerts._cooldown_state.clear()
    yield
    pipeline_log._reset()
    judge_log._reset()
    translate_log._reset()
    llm_error_log._reset()
    observability_alerts._cooldown_state.clear()


class _SentryStub:
    """Strict stub mirroring `observability_alerts._capture` — records calls.

    Signature is strict on purpose: it matches the internal `_capture(message,
    level, tags)` contract. Any drift (e.g. stray kwargs from a buggy `_emit`)
    must surface as a TypeError, not be silently swallowed.
    """

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def __call__(self, message: str, level: str, tags: dict) -> None:
        self.calls.append({"message": message, "level": level, "tags": dict(tags)})


@pytest.fixture()
def sentry_stub(monkeypatch):
    """Replace observability_alerts._capture with a strict-signature recorder."""
    stub = _SentryStub()
    monkeypatch.setattr(observability_alerts, "_capture", stub)
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


def _insert_pipeline_run_explicit(
    run_id: str, status: str, *, started_minutes_ago: int, ended_minutes_ago: int | None
) -> None:
    """Insert a pipeline_run with independently controlled started_at / ended_at."""
    started = (datetime.now(UTC) - timedelta(minutes=started_minutes_ago)).isoformat()
    ended = (
        None if ended_minutes_ago is None
        else (datetime.now(UTC) - timedelta(minutes=ended_minutes_ago)).isoformat()
    )
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


def _insert_llm_error(
    *, minutes_ago: int, error_class: str = "RateLimitError", status_code: int = 429,
) -> None:
    created = (datetime.now(UTC) - timedelta(minutes=minutes_ago)).isoformat()
    conn = llm_error_log._get_conn()
    conn.execute(
        "INSERT INTO llm_errors (user_id, call_type, provider, model, error_class, "
        "status_code, message, created_at) "
        "VALUES ('u1', 'translate', 'openai', 'gpt-4o', ?, ?, '', ?)",
        (error_class, status_code, created),
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

    def test_interrupted_status_not_alerted_by_default(self, sentry_stub):
        # `interrupted` is operational (user-cancelled / shutdown) and should
        # not contribute to failure alerts unless explicitly opted in.
        for i in range(10):
            _insert_pipeline_run(f"r{i}", "interrupted", started_minutes_ago=5)
        observability_alerts.check_pipeline_failures(window_min=60, threshold=5)
        assert sentry_stub.calls == []

    def test_interrupted_counted_when_opt_in(self, sentry_stub):
        for i in range(5):
            _insert_pipeline_run(f"r{i}", "interrupted", started_minutes_ago=5)
        observability_alerts.check_pipeline_failures(
            window_min=60, threshold=5, include_interrupted=True,
        )
        assert len(sentry_stub.calls) == 1

    def test_long_run_failing_inside_window_is_counted(self, sentry_stub):
        """Long-running pipeline: started_at outside window, failure inside it.

        Semantically the check counts *failure events*. A run that began 120m
        ago but only failed 5m ago must count toward a 60m window — framing by
        `started_at` would wrongly drop it. Consistent with judge/translate
        checks which window by event-occurrence time (`created_at`).
        """
        for i in range(5):
            _insert_pipeline_run_explicit(
                f"r{i}", "failed", started_minutes_ago=120, ended_minutes_ago=5,
            )
        observability_alerts.check_pipeline_failures(window_min=60, threshold=5)
        assert len(sentry_stub.calls) == 1
        assert sentry_stub.calls[0]["tags"]["pipeline_failures"] == 5

    def test_failure_ended_outside_window_ignored(self, sentry_stub):
        """Inverse: run started inside window but failed long after window edge.

        Failure event is what counts — if it ended before the window opened it
        must not contribute, even though `started_at` is recent-ish.
        """
        for i in range(10):
            _insert_pipeline_run_explicit(
                f"r{i}", "failed", started_minutes_ago=200, ended_minutes_ago=120,
            )
        observability_alerts.check_pipeline_failures(window_min=60, threshold=5)
        assert sentry_stub.calls == []


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
# check_llm_error_rate
# ---------------------------------------------------------------------------


class TestCheckLlmErrorRate:
    def test_check_llm_error_rate_fires(self, sentry_stub):
        """≥ threshold terminal LLM errors in window → one Sentry capture."""
        for _ in range(observability_alerts.LLM_ERROR_THRESHOLD):
            _insert_llm_error(minutes_ago=5)
        observability_alerts.run_all_checks()
        llm_calls = [
            c for c in sentry_stub.calls
            if c["tags"].get("alert") == "llm_error_rate"
        ]
        assert len(llm_calls) == 1
        call = llm_calls[0]
        assert call["level"] == "error"
        assert "llm" in call["message"].lower()
        assert call["tags"].get("llm_errors") == observability_alerts.LLM_ERROR_THRESHOLD
        assert call["tags"].get("window_min") == observability_alerts.LLM_ERROR_WINDOW_MIN

    def test_llm_error_rate_cooldown(self, sentry_stub):
        """Second consecutive run is suppressed by COOLDOWN_MIN."""
        for _ in range(observability_alerts.LLM_ERROR_THRESHOLD):
            _insert_llm_error(minutes_ago=5)
        observability_alerts.check_llm_error_rate()
        observability_alerts.check_llm_error_rate()
        llm_calls = [
            c for c in sentry_stub.calls
            if c["tags"].get("alert") == "llm_error_rate"
        ]
        assert len(llm_calls) == 1

    def test_llm_error_rate_below_threshold_silent(self, sentry_stub):
        """Fewer than LLM_ERROR_MIN_TOTAL errors → no alert."""
        for _ in range(observability_alerts.LLM_ERROR_MIN_TOTAL - 1):
            _insert_llm_error(minutes_ago=5)
        observability_alerts.check_llm_error_rate()
        assert sentry_stub.calls == []

    def test_llm_error_rate_outside_window_ignored(self, sentry_stub):
        for _ in range(observability_alerts.LLM_ERROR_THRESHOLD + 5):
            _insert_llm_error(minutes_ago=observability_alerts.LLM_ERROR_WINDOW_MIN + 30)
        observability_alerts.check_llm_error_rate()
        assert sentry_stub.calls == []


# ---------------------------------------------------------------------------
# Threshold boundary contract — pins inclusive vs exclusive semantics so
# refactors can't silently flip them. The three checks intentionally differ:
#
#   pipeline.count   >= threshold   (>=)  — `if count < threshold: return`
#   judge.rate       >  threshold   (>)   — `if rate <= threshold: return`
#   translate.p95_ms >  threshold   (>)   — `if p95 <= threshold_ms: return`
#
# Pipeline is inclusive because an integer count crossing the threshold is
# unambiguous; the rate/latency checks are exclusive so that operators can set
# `threshold = baseline` without false-positives from sample noise touching it
# exactly.
# ---------------------------------------------------------------------------


class TestThresholdBoundary:
    """One test per check that pins the boundary direction explicitly.

    These exist alongside the per-check boundary tests above; they collect the
    contract in one place so an accidental `<` → `<=` flip in any of the three
    checks shows up here as a labelled failure rather than a stray red elsewhere.
    """

    def test_pipeline_failures_boundary_is_inclusive(self, sentry_stub):
        # threshold=5 → exactly 5 failures SHOULD alert (>=)
        for i in range(5):
            _insert_pipeline_run(f"r{i}", "failed", started_minutes_ago=10)
        observability_alerts.check_pipeline_failures(window_min=60, threshold=5)
        assert len(sentry_stub.calls) == 1, "pipeline check must be inclusive (>=)"

    def test_judge_rejection_rate_boundary_is_exclusive(self, sentry_stub):
        # threshold=0.5 → rate==0.5 must NOT alert (strict >)
        for _ in range(5):
            _insert_judge_decision(accepted=True, minutes_ago=10)
        for _ in range(5):
            _insert_judge_decision(accepted=False, minutes_ago=10)
        observability_alerts.check_judge_rejection_rate(
            window_min=60, min_total=10, threshold=0.5,
        )
        assert sentry_stub.calls == [], "judge rate check must be exclusive (>)"

    def test_translate_latency_p95_boundary_is_exclusive(self, sentry_stub):
        # Build 20 samples where p95 == threshold_ms exactly. Inclusive p95
        # index = ceil(0.95 * 20) - 1 = 18 (0-indexed). So sample[18] must be
        # the boundary value. With samples sorted ascending, we need indices
        # 0..18 == 5000 and 19 == 5000 too (all equal). That gives p95 == 5000
        # which must NOT trigger (rule is strict >).
        for _ in range(20):
            _insert_translate_log(latency_ms=5000, minutes_ago=5)
        observability_alerts.check_translate_latency_p95(
            window_min=15, threshold_ms=5000,
        )
        assert sentry_stub.calls == [], (
            "translate p95 check must be exclusive (>) — equal to threshold "
            "should not alert"
        )


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


class TestCooldownIsolation:
    """Verify the autouse fixture really clears `_cooldown_state` between tests.

    Without this, a Sentry alert fired in one test would suppress the same
    alert in the next test (cooldown is 30 minutes). The pair below is the
    canary: if isolation breaks, the second test fails with `len == 0`.
    Splitting the assertion across two test methods exercises the fixture's
    teardown path, not just the setup path.
    """

    def test_first_test_stamps_pipeline_cooldown(self, sentry_stub):
        # Sanity: cooldown dict is empty at start (fixture cleared it).
        assert observability_alerts._cooldown_state == {}
        for i in range(6):
            _insert_pipeline_run(f"r{i}", "failed", started_minutes_ago=10)
        observability_alerts.check_pipeline_failures(window_min=60, threshold=5)
        assert "pipeline_failures" in observability_alerts._cooldown_state
        assert len(sentry_stub.calls) == 1

    def test_second_test_sees_fresh_cooldown(self, sentry_stub):
        # Critical: the previous test left a `pipeline_failures` cooldown
        # stamp. If the autouse fixture didn't clear it, this alert would be
        # suppressed and `sentry_stub.calls` would be empty.
        assert observability_alerts._cooldown_state == {}, (
            "fixture must clear cooldown state — leak from prior test breaks "
            "every cooldown-sensitive assertion downstream"
        )
        for i in range(6):
            _insert_pipeline_run(f"r{i}", "failed", started_minutes_ago=10)
        observability_alerts.check_pipeline_failures(window_min=60, threshold=5)
        assert len(sentry_stub.calls) == 1


# ---------------------------------------------------------------------------
# run_all + sentry-not-available guard
# ---------------------------------------------------------------------------


class TestRunAll:
    def test_run_all_invokes_all_checks(self, monkeypatch, sentry_stub):
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
        monkeypatch.setattr(
            observability_alerts, "check_llm_error_rate",
            lambda **kw: called.append("llm"),
        )
        observability_alerts.run_all_checks()
        assert called == ["pipeline", "judge", "translate", "llm"]

    def test_run_all_swallows_exceptions(self, monkeypatch):
        # Spy that every check is *attempted* even though each raises — proving
        # the swallow path is exercised per-check, not short-circuited.
        attempted: list[str] = []

        def _boom(name):
            def _fn(**kw):
                attempted.append(name)
                raise RuntimeError("db unavailable")
            return _fn

        monkeypatch.setattr(
            observability_alerts, "check_pipeline_failures", _boom("pipeline"))
        monkeypatch.setattr(
            observability_alerts, "check_judge_rejection_rate", _boom("judge"))
        monkeypatch.setattr(
            observability_alerts, "check_translate_latency_p95", _boom("translate"))
        # Must not raise — alerts are best-effort.
        result = observability_alerts.run_all_checks()
        assert result is None
        # All three branches ran and each exception was swallowed individually.
        assert attempted == ["pipeline", "judge", "translate"]


class TestSentryGuard:
    def test_emit_no_op_when_sentry_unavailable(self, monkeypatch):
        # Even if the check decides to alert, a missing sentry_sdk must short
        # the emit at the availability guard (no _capture, no crash). We spy
        # _emit to prove the alert decision *was* made (threshold exceeded), and
        # spy _capture to prove the Sentry edge was never reached.
        monkeypatch.setattr(observability_alerts, "_sentry_sdk", None)

        emit_calls: list = []
        real_emit = observability_alerts._emit

        def _emit_spy(**kw):
            emit_calls.append(kw["alert_key"])
            return real_emit(**kw)

        capture_calls: list = []
        monkeypatch.setattr(
            observability_alerts, "_emit", _emit_spy)
        monkeypatch.setattr(
            observability_alerts, "_capture",
            lambda *a, **kw: capture_calls.append((a, kw)))

        for i in range(6):
            _insert_pipeline_run(f"r{i}", "failed", started_minutes_ago=10)
        # Should be a no-op at the Sentry edge (no exception, no capture).
        observability_alerts.check_pipeline_failures(window_min=60, threshold=5)

        # The alert path *was* taken (threshold exceeded) ...
        assert emit_calls == ["pipeline_failures"]
        # ... but with _sentry_sdk None the Sentry capture never fired.
        assert capture_calls == []

    def test_capture_uses_new_scope_for_tags(self, monkeypatch):
        """Regression: tags must flow through an explicit scope, not kwargs.

        `sentry_sdk.capture_message` in 2.x still forwards `tags=` via
        `**scope_kwargs`, but that surface is deprecated and disappears in
        3.x. `push_scope` itself is also deprecated in 2.x. We therefore
        route tags through `new_scope().set_tag()` and call
        `capture_message` with the strict `(message, level=)` signature.
        """
        recorded: dict = {"capture": [], "scope_tags": {}}

        class _FakeScope:
            def set_tag(self, key, value):
                recorded["scope_tags"][key] = value

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        def _fake_capture_message(message, level=None):
            recorded["capture"].append({"message": message, "level": level})

        class _FakeSDK:
            @staticmethod
            def new_scope():
                return _FakeScope()

            capture_message = staticmethod(_fake_capture_message)

        monkeypatch.setattr(observability_alerts, "_sentry_sdk", _FakeSDK)
        observability_alerts._capture(
            "msg", "error", {"alert": "x", "n": 3},
        )
        assert recorded["capture"] == [{"message": "msg", "level": "error"}]
        assert recorded["scope_tags"] == {"alert": "x", "n": 3}


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
