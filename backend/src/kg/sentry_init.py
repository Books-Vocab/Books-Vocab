"""Sentry SDK initialization — opt-in via SENTRY_DSN env var.

No-op when SENTRY_DSN is unset, so dev/test runs without Sentry account.
Idempotent: safe to call multiple times (e.g. from create_app in tests).

Handled failures (caught + logged, never re-raised) do not become events on
their own — ``LoggingIntegration`` runs with ``event_level=None`` so unhandled
errors are not double-reported. Report them explicitly via
``capture_handled(exc, context=...)``.

Env vars:
    SENTRY_DSN                  Required for activation. Leave empty to disable.
    SENTRY_ENVIRONMENT          "production" / "staging" / "dev" (default: "production")
    SENTRY_RELEASE              Exact release string, used verbatim. When unset, the
                                release is ``kg-backend@<value>`` from KG_VERSION, then
                                from /app/VERSION (written by deploy, bind-mounted).
    SENTRY_TRACES_SAMPLE_RATE   APM sampling 0.0–1.0 (default: 0.0 = error-only)
    SENTRY_PROFILES_SAMPLE_RATE Profiling sampling 0.0–1.0 (default: 0.0)
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

from .exceptions import KGError

_logger = logging.getLogger(__name__)
_initialized = False
# Cached reference to the sentry_sdk module after a successful init().
# Stored at module scope so bind_user() can avoid re-importing on every
# authenticated request (hot path).
_sentry_module: Any | None = None

# Production: the deploy path writes the deploy SHA to backend/VERSION on the
# deploy host, bind-mounted to /app/VERSION (no rsync since the 2026-06-15 move
# to standby). Acts as the last-resort release identifier when no env override
# is present.
_DEFAULT_VERSION_FILE = Path("/app/VERSION")

# Sentry release namespace for this service. Bare deploy identifiers (git SHA)
# are qualified as ``kg-backend@<sha>`` so backend and iOS releases never
# collide in the same Sentry organization.
_RELEASE_PREFIX: Final[str] = "kg-backend@"

# Query/header/cookie keys whose values must never reach Sentry.
_SCRUB_HEADER_KEYS: Final[frozenset[str]] = frozenset(
    {"authorization", "cookie", "x-admin-token", "x-kg-api-key", "x-api-key"}
)
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
      1. ``SENTRY_RELEASE`` env — explicit override, returned verbatim
      2. ``KG_VERSION`` env (legacy fallback)
      3. ``/app/VERSION`` file contents (deploy writes the SHA, bind-mounted)

    Values from 2 and 3 are qualified as ``kg-backend@<value>`` unless they
    already contain ``@``. Returns ``None`` when no source yields a non-empty
    value, letting ``sentry_sdk.init(release=None)`` use its own detection.
    """
    explicit = os.getenv("SENTRY_RELEASE", "").strip()
    if explicit:
        return explicit

    raw = os.getenv("KG_VERSION", "").strip()
    if not raw:
        path = version_file if version_file is not None else _DEFAULT_VERSION_FILE
        try:
            if path.exists():
                raw = path.read_text().strip()
        except OSError:  # pragma: no cover — defensive against unreadable mounts
            _logger.warning("Failed to read release from %s", path)
    if not raw:
        return None
    return raw if "@" in raw else f"{_RELEASE_PREFIX}{raw}"


def init_sentry(*, job: str | None = None) -> bool:
    """Initialize Sentry if SENTRY_DSN is set. Returns True when active.

    ``job`` names a CLI / cron entrypoint; it is attached as a global ``job``
    tag so its events are separable from API-server events in the same
    environment. No-op (returns False) without a DSN.
    """
    active = _init_sdk()
    if active and job and _sentry_module is not None:
        try:
            _sentry_module.get_global_scope().set_tag("job", job)
        except Exception:  # pragma: no cover — tagging must never break the job
            _logger.exception("Failed to tag Sentry job=%s", job)
    return active


def _init_sdk() -> bool:
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
        traces_strategy = f"sampler(hot={_TRACES_HOT_RATE},base={_TRACES_BASELINE_RATE},drop=health)"

    sentry_sdk.init(**init_kwargs)
    global _sentry_module
    _sentry_module = sentry_sdk
    _initialized = True
    _logger.info(
        "Sentry initialized env=%s release=%s traces=%s profiles=%s",
        environment,
        release or "-",
        traces_strategy,
        profiles_rate,
    )
    return True


def is_active() -> bool:
    return _initialized


def _is_reportable(exc: BaseException) -> bool:
    """Whether a handled failure is worth a Sentry event.

    Cancellation / interpreter exit (non-``Exception`` BaseExceptions) and
    client-caused ``KGError`` (4xx: not found, quota, validation...) are
    expected outcomes, not defects.
    """
    if not isinstance(exc, Exception):
        return False
    if isinstance(exc, KGError) and 400 <= exc.status_code < 500:
        return False
    return True


def capture_handled(
    exc: BaseException,
    *,
    context: str,
    tags: Mapping[str, str] | None = None,
) -> bool:
    """Report a caught-and-swallowed failure to Sentry.

    ``context`` is a stable dotted identifier of the call site (e.g.
    ``pipeline.step``) and is always the ``context`` tag; ``tags`` adds
    low-cardinality extras and cannot override it. Returns True when an event
    was handed to the SDK. No-op without a DSN; never raises.
    """
    if not _initialized or _sentry_module is None or not _is_reportable(exc):
        return False
    try:
        _sentry_module.capture_exception(exc, tags={**(tags or {}), "context": context})
    except Exception:
        _logger.warning("capture_handled failed for context=%s", context, exc_info=True)
        return False
    return True


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
