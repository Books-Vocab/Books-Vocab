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

_logger = logging.getLogger(__name__)
_initialized = False


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
        attach_stacktrace=True,
        integrations=[
            FastApiIntegration(transaction_style="endpoint"),
            StarletteIntegration(transaction_style="endpoint"),
            LoggingIntegration(level=logging.INFO, event_level=logging.ERROR),
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
