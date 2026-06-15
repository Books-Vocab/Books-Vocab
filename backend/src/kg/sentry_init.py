"""Sentry SDK initialization — opt-in via SENTRY_DSN env var.

No-op when SENTRY_DSN is unset, so dev/test runs without Sentry account.
Idempotent: safe to call multiple times (e.g. from create_app in tests).

Env vars:
    SENTRY_DSN                  Required for activation. Leave empty to disable.
    SENTRY_ENVIRONMENT          "production" / "staging" / "dev" (default: "production")
    SENTRY_RELEASE              Git SHA or version tag; falls back to KG_VERSION,
                                then to the contents of /app/VERSION (rsync'd by deploy).
    SENTRY_TRACES_SAMPLE_RATE   APM sampling 0.0–1.0 (default: 0.0 = error-only)
    SENTRY_PROFILES_SAMPLE_RATE Profiling sampling 0.0–1.0 (default: 0.0)
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Final

_logger = logging.getLogger(__name__)
_initialized = False
# Cached reference to the sentry_sdk module after a successful init().
# Stored at module scope so bind_user() can avoid re-importing on every
# authenticated request (hot path).
_sentry_module: Any | None = None

# Production: deploy.sh writes the deploy SHA to /app/VERSION (rsync'd into the
# container). Acts as the last-resort release identifier when no env override
# is present.
_DEFAULT_VERSION_FILE = Path("/app/VERSION")

# Query/header/cookie keys whose values must never reach Sentry.
_SCRUB_HEADER_KEYS: Final[frozenset[str]] = frozenset({"authorization", "cookie", "x-admin-token"})
_SCRUB_QUERY_KEYS: Final[frozenset[str]] = frozenset({"token", "admin_session", "code", "id_token", "access_token"})

# Per-path APM sampling. Keep LLM-call hot paths observable (slow + costly),
# drop pure-health endpoints, baseline everything else.
#
# Rates picked to keep monthly trace volume ≪ Sentry free tier (10k spans/mo):
#   • /api/pipeline + /api/translate + /api/explain ≈ ~5k req/mo at current
#     traffic → 5% = ~250 traces/mo, comfortable headroom.
#   • baseline 1% covers CRUD endpoints (~20k req/mo → ~200 traces/mo).
#   • health endpoints hit every 30s by docker healthcheck → would dominate
#     trace volume if sampled at all.
_TRACES_HOT_PATHS = ("/api/pipeline", "/api/translate", "/api/explain")
_TRACES_DROP_PATHS = ("/api/system/info", "/api/health", "/health")
_TRACES_HOT_RATE = 0.05
_TRACES_BASELINE_RATE = 0.01
_TRACES_DROP_RATE = 0.0


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


def _traces_sampler(sampling_context: dict[str, Any]) -> float:
    """Per-path APM sampling rate.

    Sentry calls this for every transaction. Returning 0 drops the trace
    entirely (no span ever leaves the process), so health-check noise costs
    us nothing. Returning >0 means the trace is kept with that probability.
    """
    path = ""
    scope = sampling_context.get("asgi_scope") if isinstance(sampling_context, dict) else None
    if isinstance(scope, dict):
        raw = scope.get("path")
        if isinstance(raw, str):
            path = raw

    if not path:
        return _TRACES_BASELINE_RATE

    for drop in _TRACES_DROP_PATHS:
        if path == drop or path.startswith(drop + "/"):
            return _TRACES_DROP_RATE
    for hot in _TRACES_HOT_PATHS:
        if path == hot or path.startswith(hot + "/"):
            return _TRACES_HOT_RATE
    return _TRACES_BASELINE_RATE


def _resolve_release(version_file: Path | None = None) -> str | None:
    """Pick the Sentry release identifier.

    Resolution order:
      1. ``SENTRY_RELEASE`` env (explicit override; deploy script sets this)
      2. ``KG_VERSION`` env (legacy fallback)
      3. ``/app/VERSION`` file contents (rsync'd by ``devops.sh cmd_deploy``)

    Returns ``None`` when none of the sources yield a non-empty value, letting
    ``sentry_sdk.init(release=None)`` default to its own SHA detection.
    """
    for env_key in ("SENTRY_RELEASE", "KG_VERSION"):
        raw = os.getenv(env_key, "").strip()
        if raw:
            return raw

    path = version_file if version_file is not None else _DEFAULT_VERSION_FILE
    try:
        if path.exists():
            contents = path.read_text().strip()
            if contents:
                return contents
    except OSError:  # pragma: no cover — defensive against unreadable mounts
        _logger.warning("Failed to read release from %s", path)
    return None


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
        _logger.warning("Silently handled exception; using fallback response", exc_info=True)
        return False

    environment = os.getenv("SENTRY_ENVIRONMENT", "production").strip() or "production"
    release = _resolve_release()

    def _float_env(name: str, default: float) -> float:
        raw = os.getenv(name, "").strip()
        if not raw:
            return default
        try:
            return max(0.0, min(1.0, float(raw)))
        except ValueError:
            _logger.warning("%s=%r is not a float; using default %s", name, raw, default)
            _logger.warning("Silently handled exception; using fallback response", exc_info=True)
            return default

    profiles_rate = _float_env("SENTRY_PROFILES_SAMPLE_RATE", 0.0)

    # Use traces_sampler (per-transaction callback) instead of a flat
    # traces_sample_rate. The flat rate was 0.0 in production, which gave us
    # zero APM signal. The sampler keeps health-check noise out while letting
    # us see the LLM hot paths. SENTRY_TRACES_SAMPLE_RATE env is still honored
    # as a debug override (set non-zero to bypass the per-path logic).
    flat_override = _float_env("SENTRY_TRACES_SAMPLE_RATE", 0.0)
    init_kwargs: dict[str, Any] = {
        "dsn": dsn,
        "environment": environment,
        "release": release,
        "profiles_sample_rate": profiles_rate,
        "send_default_pii": False,
        "include_local_variables": False,  # frame locals contain JWTs/passwords
        "max_request_body_size": "never",
        "attach_stacktrace": True,
        "before_send": _scrub_event,
        "before_send_transaction": _scrub_event,  # same scrub for trace payloads
        "integrations": [
            StarletteIntegration(transaction_style="endpoint"),
            FastApiIntegration(transaction_style="endpoint"),
            # Breadcrumbs from WARNING+. Event capture disabled — Starlette
            # integration already captures exceptions; logger.error would double-report.
            LoggingIntegration(level=logging.WARNING, event_level=None),
        ],
    }
    if flat_override > 0:
        init_kwargs["traces_sample_rate"] = flat_override
        traces_strategy = f"flat={flat_override}"
    else:
        init_kwargs["traces_sampler"] = _traces_sampler
        traces_strategy = (
            f"sampler(hot={_TRACES_HOT_RATE},base={_TRACES_BASELINE_RATE},drop=health)"
        )

    sentry_sdk.init(**init_kwargs)
    global _sentry_module
    _sentry_module = sentry_sdk
    _initialized = True
    _logger.info(
        "Sentry initialized env=%s release=%s traces=%s profiles=%s",
        environment, release or "-", traces_strategy, profiles_rate,
    )
    return True


def is_active() -> bool:
    return _initialized


def tag_request_id(request_id: str | None) -> None:
    """Attach ``request_id`` to the current Sentry scope as a tag.

    Called from the request_id middleware so every captured event / trace
    carries the same correlation id we already log in stdout + return via
    the ``X-Request-ID`` header. Falsy ``request_id`` is a no-op.

    No-op when Sentry isn't initialized. Swallows all errors — Sentry tagging
    must never disturb the request flow.
    """
    if not _initialized or _sentry_module is None or not request_id:
        return
    try:
        _sentry_module.set_tag("request_id", request_id)
    except Exception:  # pragma: no cover — sentry must never break the request
        _logger.exception("tag_request_id failed; suppressing to keep request flow")


def bind_user(user_id: str | None) -> None:
    """Tag the current Sentry scope with ``user_id`` (and nothing else).

    Called from the auth dependency so error events / traces are clusterable
    per-user without leaking PII. We deliberately omit email, IP, username —
    sendDefaultPii is off and we want to keep it that way.

    No-op when Sentry isn't initialized (dev/test, or DSN unset in prod).
    Falsy ``user_id`` clears the scope — a clear hook reserved for a future
    optional-auth dependency. The current ``get_current_user`` uses
    ``HTTPBearer(auto_error=True)``, so unauthenticated requests are rejected
    before this line runs and cannot reach an authenticated handler with a
    stale uid; the clear branch is kept so adding an optional-auth path later
    is a one-line change rather than a scope-leak audit.
    """
    if not _initialized or _sentry_module is None:
        return
    try:
        if user_id:
            _sentry_module.set_user({"id": user_id})
        else:
            _sentry_module.set_user(None)
    except Exception:  # pragma: no cover — sentry must never break the request
        _logger.exception("bind_user failed; suppressing to keep request flow")
