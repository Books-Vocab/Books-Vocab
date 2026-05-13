"""Sentry SDK initialization — opt-in via SENTRY_DSN env var.

No-op when SENTRY_DSN is unset, so dev/test runs without Sentry account.
Idempotent: safe to call multiple times (e.g. from create_app in tests).

Env vars:
    SENTRY_DSN                  Required for activation. Leave empty to disable.
    SENTRY_ENVIRONMENT          "production" / "staging" / "dev" (default: "production")
    SENTRY_RELEASE              Git SHA or version tag; falls back to KG_VERSION
    SENTRY_TRACES_SAMPLE_RATE   APM sampling 0.0–1.0 (default: 0.0 = error-only)
    SENTRY_PROFILES_SAMPLE_RATE Profiling sampling 0.0–1.0 (default: 0.0)
"""
from __future__ import annotations

import logging
import os
from typing import Any

_logger = logging.getLogger(__name__)
_initialized = False

# Query/header/cookie keys whose values must never reach Sentry.
_SCRUB_HEADER_KEYS = {"authorization", "cookie", "x-admin-token"}
_SCRUB_QUERY_KEYS = {"token", "admin_session", "code", "id_token", "access_token"}


def _scrub_event(event: dict[str, Any], _hint: dict[str, Any]) -> dict[str, Any]:
    """Strip auth credentials from outgoing events before they ship."""
    req = event.get("request")
    if isinstance(req, dict):
        qs = req.get("query_string")
        if isinstance(qs, str) and qs:
            req["query_string"] = _scrub_querystring(qs)
        headers = req.get("headers")
        if isinstance(headers, dict):
            for key in list(headers.keys()):
                if key.lower() in _SCRUB_HEADER_KEYS:
                    headers[key] = "[scrubbed]"
        cookies = req.get("cookies")
        if isinstance(cookies, dict):
            for key in list(cookies.keys()):
                if "session" in key.lower() or "token" in key.lower():
                    cookies[key] = "[scrubbed]"
    return event


def _scrub_querystring(qs: str) -> str:
    parts = []
    for chunk in qs.split("&"):
        if "=" in chunk:
            k, _ = chunk.split("=", 1)
            if k.lower() in _SCRUB_QUERY_KEYS:
                parts.append(f"{k}=[scrubbed]")
                continue
        parts.append(chunk)
    return "&".join(parts)


def init_sentry() -> bool:
    """Initialize Sentry if SENTRY_DSN is set. Returns True when active."""
    global _initialized
    if _initialized:
        return True

    dsn = os.getenv("SENTRY_DSN", "").strip()
    if not dsn:
        return False

    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.logging import LoggingIntegration
        from sentry_sdk.integrations.starlette import StarletteIntegration
    except ImportError:
        _logger.warning("SENTRY_DSN set but sentry-sdk not installed; skipping init")
        return False

    environment = os.getenv("SENTRY_ENVIRONMENT", "production").strip() or "production"
    release = (os.getenv("SENTRY_RELEASE") or os.getenv("KG_VERSION") or "").strip() or None

    def _float_env(name: str, default: float) -> float:
        raw = os.getenv(name, "").strip()
        if not raw:
            return default
        try:
            return max(0.0, min(1.0, float(raw)))
        except ValueError:
            _logger.warning("%s=%r is not a float; using default %s", name, raw, default)
            return default

    traces_rate = _float_env("SENTRY_TRACES_SAMPLE_RATE", 0.0)
    profiles_rate = _float_env("SENTRY_PROFILES_SAMPLE_RATE", 0.0)

    sentry_sdk.init(
        dsn=dsn,
        environment=environment,
        release=release,
        traces_sample_rate=traces_rate,
        profiles_sample_rate=profiles_rate,
        send_default_pii=False,
        include_local_variables=False,  # frame locals contain JWTs/passwords
        max_request_body_size="never",
        attach_stacktrace=True,
        before_send=_scrub_event,
        integrations=[
            StarletteIntegration(transaction_style="endpoint"),
            FastApiIntegration(transaction_style="endpoint"),
            # Breadcrumbs from WARNING+. Event capture disabled — Starlette
            # integration already captures exceptions; logger.error would double-report.
            LoggingIntegration(level=logging.WARNING, event_level=None),
        ],
    )
    _initialized = True
    _logger.info(
        "Sentry initialized env=%s release=%s traces=%s profiles=%s",
        environment, release or "-", traces_rate, profiles_rate,
    )
    return True


def is_active() -> bool:
    return _initialized
