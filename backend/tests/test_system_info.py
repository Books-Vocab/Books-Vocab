"""Tests for the /api/system/info endpoint (no auth required)."""

from __future__ import annotations

import asyncio
import threading
import time
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import httpx
import pytest
from fastapi.testclient import TestClient

from kg.api import app


@pytest.fixture(autouse=True)
def _test_clients_are_closed():
    clients = []
    closed = set()
    original_init = TestClient.__init__
    original_close = TestClient.close

    def track_init(client, *args, **kwargs):
        clients.append(client)
        return original_init(client, *args, **kwargs)

    def track_close(client):
        closed.add(id(client))
        return original_close(client)

    with patch.object(TestClient, "__init__", track_init), patch.object(TestClient, "close", track_close):
        yield

    assert {id(client) for client in clients} == closed


class TestSystemInfoEndpoint:
    def test_returns_200_without_auth(self):
        client = TestClient(app, raise_server_exceptions=False)
        try:
            r = client.get("/api/system/info")
            assert r.status_code == 200, r.text
        finally:
            client.close()

    def test_response_contains_version(self):
        client = TestClient(app, raise_server_exceptions=False)
        try:
            r = client.get("/api/system/info")
            body = r.json()
            assert "version" in body
        finally:
            client.close()

    def test_response_contains_started_at(self):
        client = TestClient(app, raise_server_exceptions=False)
        try:
            r = client.get("/api/system/info")
            body = r.json()
            assert "started_at" in body
            assert body["started_at"] is not None
        finally:
            client.close()

    def test_response_contains_uptime_seconds(self):
        client = TestClient(app, raise_server_exceptions=False)
        try:
            r = client.get("/api/system/info")
            body = r.json()
            assert "uptime_seconds" in body
            assert isinstance(body["uptime_seconds"], (int, float))
            assert body["uptime_seconds"] >= 0
        finally:
            client.close()

    def test_response_contains_migration_version(self):
        client = TestClient(app, raise_server_exceptions=False)
        try:
            r = client.get("/api/system/info")
            body = r.json()
            assert "migration_version" in body
        finally:
            client.close()

    def test_version_surfaces_captured_value(self):
        # VERSION is read once at import into _VERSION (immutable per process);
        # the endpoint must surface that captured value.
        with patch("kg.routers.system._VERSION", "abc1234"):
            client = TestClient(app, raise_server_exceptions=False)
            try:
                r = client.get("/api/system/info")
                assert r.json()["version"] == "abc1234"
            finally:
                client.close()

    def test_version_unknown_when_file_missing(self):
        # When the VERSION file is absent at import the captured value is "unknown".
        with patch("kg.routers.system._VERSION", "unknown"):
            client = TestClient(app, raise_server_exceptions=False)
            try:
                r = client.get("/api/system/info")
                assert r.json()["version"] == "unknown"
            finally:
                client.close()

    def test_response_contains_sentry_field(self):
        # deploy.md's post-deploy gate falls back to checking the /api/system/info
        # body for a `sentry` field as proof the DSN was wired. The field must
        # exist and reflect sentry_init.is_active().
        with patch("kg.routers.system.sentry_init.is_active", return_value=True):
            client = TestClient(app, raise_server_exceptions=False)
            try:
                r = client.get("/api/system/info")
                body = r.json()
                assert "sentry" in body
                assert body["sentry"] is True
            finally:
                client.close()

    def test_sentry_field_false_when_inactive(self):
        with patch("kg.routers.system.sentry_init.is_active", return_value=False):
            client = TestClient(app, raise_server_exceptions=False)
            try:
                r = client.get("/api/system/info")
                assert r.json()["sentry"] is False
            finally:
                client.close()

    def test_endpoint_exempt_from_rate_limit(self):
        """The system info endpoint should not be rate-limited."""
        client = TestClient(app, raise_server_exceptions=False)
        try:
            # Hit it many times — should never get 429
            for _ in range(20):
                r = client.get("/api/system/info")
                assert r.status_code != 429
        finally:
            client.close()

    def test_response_is_not_cacheable(self):
        """Dynamic deployment and uptime data must not be served stale."""
        with patch("kg.routers.system.observability_alerts.run_all_checks"):
            client = TestClient(app, raise_server_exceptions=False)
            try:
                r = client.get("/api/system/info")
                assert r.status_code == 200
                assert r.headers.get("cache-control") == "no-store"
            finally:
                client.close()

    # ---------------------------------------------------------------------
    # Wiring: /api/system/info must fire observability_alerts.run_all_checks
    # piggyback-style on the first poll of each throttle interval (see
    # TestObservabilityChecksThrottle). This is the only entry point for the
    # threshold alerts — if this call disappears, alerting silently halts.
    # ---------------------------------------------------------------------

    def test_invokes_observability_run_all_checks(self):
        with patch("kg.routers.system.observability_alerts.run_all_checks") as m:
            client = TestClient(app, raise_server_exceptions=False)
            try:
                r = client.get("/api/system/info")
                assert r.status_code == 200
                assert m.call_count == 1, (
                    "system_info handler must call observability_alerts.run_all_checks "
                    "on the first request of a throttle interval — wiring regression"
                )
            finally:
                client.close()

    def test_invokes_observability_checks_via_threadpool(self):
        async def fake_threadpool(fn, *args, **kwargs):
            calls.append((fn, args, kwargs))
            return fn(*args, **kwargs)

        calls = []
        with (
            patch("kg.routers.system.run_in_threadpool", new=fake_threadpool),
            patch("kg.routers.system.observability_alerts.run_all_checks") as m,
        ):
            client = TestClient(app, raise_server_exceptions=False)
            try:
                r = client.get("/api/system/info")
                assert r.status_code == 200
                assert calls == [(m, (), {})]
            finally:
                client.close()

    def test_observability_exception_does_not_break_endpoint(self):
        """If run_all_checks raises despite its own swallow, /api/system/info
        must still return 200. The handler has a belt-and-suspenders guard
        precisely for this case."""
        with patch(
            "kg.routers.system.observability_alerts.run_all_checks",
            side_effect=RuntimeError("synthetic observability failure"),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            try:
                r = client.get("/api/system/info")
                assert r.status_code == 200, r.text
                body = r.json()
                assert "version" in body  # endpoint still produces a normal payload
            finally:
                client.close()


class _CountingChecks:
    """Thread-safe stand-in for ``run_all_checks`` that stays in flight briefly.

    The sleep keeps the first run open while the rest of a concurrent burst
    arrives, so an unthrottled handler is caught running the checks per request.
    """

    def __init__(self, hold_s: float = 0.0) -> None:
        self._lock = threading.Lock()
        self._hold_s = hold_s
        self.calls = 0

    def __call__(self) -> None:
        with self._lock:
            self.calls += 1
        if self._hold_s:
            time.sleep(self._hold_s)


async def _burst(n: int) -> list[int]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        responses = await asyncio.gather(*(client.get("/api/system/info") for _ in range(n)))
    return [r.status_code for r in responses]


class TestObservabilityChecksThrottle:
    """Issue #2087: the endpoint is unauthenticated and rate-limit exempt, so the
    log-DB threshold checks it piggybacks must run at most once per interval per
    process, however many requests arrive."""

    def test_concurrent_burst_runs_checks_once_within_interval(self):
        checks = _CountingChecks(hold_s=0.05)
        with patch("kg.routers.system.observability_alerts.run_all_checks", new=checks):
            statuses = asyncio.run(asyncio.wait_for(_burst(50), timeout=30.0))
        assert statuses == [200] * 50
        assert checks.calls == 1, f"50 concurrent requests ran the checks {checks.calls} times"

    def test_sequential_requests_within_interval_run_checks_once(self):
        checks = _CountingChecks()
        with patch("kg.routers.system.observability_alerts.run_all_checks", new=checks):
            client = TestClient(app, raise_server_exceptions=False)
            try:
                for _ in range(5):
                    r = client.get("/api/system/info")
                    assert r.status_code == 200, r.text
                    assert "version" in r.json()
            finally:
                client.close()
        assert checks.calls == 1

    def test_wall_clock_jump_does_not_reopen_the_throttle(self):
        # The interval is measured on the monotonic clock: an NTP step or a
        # wall-clock jump must not let a flood through.
        from kg import observability_alerts

        checks = _CountingChecks()
        with patch("kg.routers.system.observability_alerts.run_all_checks", new=checks):
            client = TestClient(app, raise_server_exceptions=False)
            try:
                assert client.get("/api/system/info").status_code == 200
                jumped = datetime.now(UTC) + timedelta(days=1)
                with patch.object(observability_alerts, "_now", lambda: jumped):
                    assert client.get("/api/system/info").status_code == 200
            finally:
                client.close()
        assert checks.calls == 1

    def test_checks_run_again_once_the_interval_elapses(self):
        # Throttling must not turn into "alerting halts": the next request
        # after the interval runs the checks again.
        from kg import observability_alerts

        clock = [1000.0]
        checks = _CountingChecks()
        with (
            patch.object(observability_alerts, "_monotonic", lambda: clock[0]),
            patch("kg.routers.system.observability_alerts.run_all_checks", new=checks),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            try:
                assert client.get("/api/system/info").status_code == 200
                clock[0] += observability_alerts.CHECK_INTERVAL_S - 0.001
                assert client.get("/api/system/info").status_code == 200
                assert checks.calls == 1
                clock[0] += 0.001
                assert client.get("/api/system/info").status_code == 200
            finally:
                client.close()
        assert checks.calls == 2

    def test_throttled_requests_do_not_take_a_threadpool_slot(self):
        dispatched = []

        async def fake_threadpool(fn, *args, **kwargs):
            dispatched.append(fn)
            return fn(*args, **kwargs)

        with (
            patch("kg.routers.system.run_in_threadpool", new=fake_threadpool),
            patch("kg.routers.system.observability_alerts.run_all_checks", new=_CountingChecks()),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            try:
                for _ in range(5):
                    assert client.get("/api/system/info").status_code == 200
            finally:
                client.close()
        assert len(dispatched) == 1
