"""Tests for the /api/system/info endpoint (no auth required)."""
from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient

from kg.api import app


class TestSystemInfoEndpoint:

    def test_returns_200_without_auth(self):
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get("/api/system/info")
        assert r.status_code == 200, r.text

    def test_response_contains_version(self):
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get("/api/system/info")
        body = r.json()
        assert "version" in body

    def test_response_contains_started_at(self):
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get("/api/system/info")
        body = r.json()
        assert "started_at" in body
        assert body["started_at"] is not None

    def test_response_contains_uptime_seconds(self):
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get("/api/system/info")
        body = r.json()
        assert "uptime_seconds" in body
        assert isinstance(body["uptime_seconds"], (int, float))
        assert body["uptime_seconds"] >= 0

    def test_response_contains_migration_version(self):
        client = TestClient(app, raise_server_exceptions=False)
        r = client.get("/api/system/info")
        body = r.json()
        assert "migration_version" in body

    def test_version_surfaces_captured_value(self):
        # VERSION is read once at import into _VERSION (immutable per process);
        # the endpoint must surface that captured value.
        with patch("kg.routers.system._VERSION", "abc1234"):
            client = TestClient(app, raise_server_exceptions=False)
            r = client.get("/api/system/info")
        assert r.json()["version"] == "abc1234"

    def test_version_unknown_when_file_missing(self):
        # When the VERSION file is absent at import the captured value is "unknown".
        with patch("kg.routers.system._VERSION", "unknown"):
            client = TestClient(app, raise_server_exceptions=False)
            r = client.get("/api/system/info")
        assert r.json()["version"] == "unknown"

    def test_response_contains_sentry_field(self):
        # deploy.md's post-deploy gate falls back to checking the /api/system/info
        # body for a `sentry` field as proof the DSN was wired. The field must
        # exist and reflect sentry_init.is_active().
        with patch("kg.routers.system.sentry_init.is_active", return_value=True):
            client = TestClient(app, raise_server_exceptions=False)
            r = client.get("/api/system/info")
        body = r.json()
        assert "sentry" in body
        assert body["sentry"] is True

    def test_sentry_field_false_when_inactive(self):
        with patch("kg.routers.system.sentry_init.is_active", return_value=False):
            client = TestClient(app, raise_server_exceptions=False)
            r = client.get("/api/system/info")
        assert r.json()["sentry"] is False

    def test_endpoint_exempt_from_rate_limit(self):
        """The system info endpoint should not be rate-limited."""
        client = TestClient(app, raise_server_exceptions=False)
        # Hit it many times — should never get 429
        for _ in range(20):
            r = client.get("/api/system/info")
            assert r.status_code != 429

    # ---------------------------------------------------------------------
    # Wiring: /api/system/info must fire observability_alerts.run_all_checks
    # piggyback-style on every poll. This is the only entry point for the
    # threshold alerts — if this call disappears, alerting silently halts.
    # ---------------------------------------------------------------------

    def test_invokes_observability_run_all_checks(self):
        with patch("kg.routers.system.observability_alerts.run_all_checks") as m:
            client = TestClient(app, raise_server_exceptions=False)
            r = client.get("/api/system/info")
            assert r.status_code == 200
            assert m.call_count == 1, (
                "system_info handler must call observability_alerts.run_all_checks "
                "once per request — wiring regression"
            )

    def test_invokes_observability_checks_via_threadpool(self):
        async def fake_threadpool(fn, *args, **kwargs):
            calls.append((fn, args, kwargs))
            return fn(*args, **kwargs)

        calls = []
        with patch("kg.routers.system.run_in_threadpool", new=fake_threadpool), \
             patch("kg.routers.system.observability_alerts.run_all_checks") as m:
            client = TestClient(app, raise_server_exceptions=False)
            r = client.get("/api/system/info")
        assert r.status_code == 200
        assert calls == [(m, (), {})]

    def test_observability_exception_does_not_break_endpoint(self):
        """If run_all_checks raises despite its own swallow, /api/system/info
        must still return 200. The handler has a belt-and-suspenders guard
        precisely for this case."""
        with patch(
            "kg.routers.system.observability_alerts.run_all_checks",
            side_effect=RuntimeError("synthetic observability failure"),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            r = client.get("/api/system/info")
            assert r.status_code == 200, r.text
            body = r.json()
            assert "version" in body  # endpoint still produces a normal payload
