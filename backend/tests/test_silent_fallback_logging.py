"""Regression guard for the silent-fallback logging sweep (PR#973).

The "log silent fallback paths" change mechanically stamped logging onto
except/fallback branches across many modules. Several modules bound a bare
``logger``/``log`` name that did not resolve in scope, so the *fallback* branch
— the one that exists precisely to degrade gracefully — raised ``NameError``
the instant it ran. compileall never executes those branches, so the breakage
was invisible until the error path fired. These tests exercise each fixed
branch directly so the logger binding can never silently regress again.
"""
from __future__ import annotations

import asyncio


def test_env_days_non_int_falls_back(monkeypatch):
    from kg import log_retention

    monkeypatch.setenv("KG_TEST_RETENTION_DAYS", "not-an-int")
    assert log_retention._env_days("KG_TEST_RETENTION_DAYS", 30) == 30


def test_settings_env_int_and_float_non_numeric_fall_back(monkeypatch):
    from kg import settings

    monkeypatch.setenv("KG_TEST_INT", "not-an-int")
    monkeypatch.setenv("KG_TEST_FLT", "not-a-float")
    assert settings._env_int("KG_TEST_INT", 7) == 7
    assert settings._env_float("KG_TEST_FLT", 1.5) == 1.5


def test_translate_parse_json_payload_malformed_returns_empty():
    from kg import translate_service

    assert translate_service._parse_json_payload("{not valid json") == {}


def test_normalize_ms_timestamp_non_numeric_uses_parser_fallback():
    from kg.billing import notifications

    # int(raw) raises -> fallback parser path; must not NameError.
    assert notifications.normalize_ms_timestamp("nope", parse_datetime_fn=lambda _s: None) is None


def test_redact_validation_body_secret_in_non_json_body():
    from kg import app_exception_handlers

    out = app_exception_handlers._redact_validation_body("access_token=secret-value")
    assert out == "[non-json body omitted: secret-like field present]"


def test_retry_returns_value_on_first_attempt():
    from kg import retry

    assert retry.sync_retry(lambda: 42) == 42

    async def _run():
        async def fn():
            return 7

        return await retry.async_retry(fn)

    assert asyncio.run(_run()) == 7


def test_create_app_registers_routes(monkeypatch):
    """The admin login route's union return annotation broke create_app() at
    route registration (FastAPI treated the Response union as a response_model).
    Guard that the full app still builds."""
    monkeypatch.setenv("JWT_SECRET", "test-secret-at-least-16-chars-long")
    from kg.api import create_app

    app = create_app()
    assert any(getattr(r, "path", None) == "/admin/login" for r in app.routes)
