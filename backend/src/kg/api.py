"""FastAPI server for Knowledge Graph — lightweight bridge for BooksBrowser.

App factory, middleware stack, and route wiring.
Endpoint functions live in their respective routers/*.py files.
Shared dependencies live in deps.py.

Usage:
    uvicorn kg.api:app --reload --port 8000
"""

from __future__ import annotations

import atexit
import json
import logging
import re
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

logging.basicConfig(
    level=logging.INFO,
    format='{"ts":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","msg":"%(message)s"}',
)
logger = logging.getLogger(__name__)

_VALIDATION_SECRET_KEYS = {
    "access_token",
    "accesstoken",
    "admin_session",
    "adminsession",
    "api_key",
    "apikey",
    "authorization",
    "bearer",
    "client_secret",
    "clientsecret",
    "code",
    "cookie",
    "id_token",
    "idtoken",
    "password",
    "refresh_token",
    "refreshtoken",
    "signed_payload",
    "signedpayload",
    "secret",
    "token",
}
_VALIDATION_SECRET_RE = re.compile(
    r'(?P<prefix>["\']?(?:access[_-]?token|accessToken|admin[_-]?session|adminSession|api[_-]?key|apiKey|'
    r'authorization|bearer|client[_-]?secret|clientSecret|code|cookie|id[_-]?token|idToken|password|'
    r'refresh[_-]?token|refreshToken|signed[_-]?payload|signedPayload|secret|token)["\']?\s*[:=]\s*["\']?)'
    r"(?P<value>[^\"'\s,;}&]+)",
    re.IGNORECASE,
)


def _validation_key_norm(key: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(key).lower())


def _is_validation_secret_key(key: Any) -> bool:
    key_text = str(key).replace("-", "_").lower()
    return key_text in _VALIDATION_SECRET_KEYS or _validation_key_norm(key) in _VALIDATION_SECRET_KEYS


def _redact_validation_payload(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: dict[Any, Any] = {}
        secret_error_input = False
        loc = value.get("loc")
        if isinstance(loc, (list, tuple)):
            secret_error_input = any(_is_validation_secret_key(part) for part in loc)
        for key, item in value.items():
            if _is_validation_secret_key(key) or (key == "input" and secret_error_input):
                redacted[key] = "[REDACTED]"
            else:
                redacted[key] = _redact_validation_payload(item)
        return redacted
    if isinstance(value, list):
        return [_redact_validation_payload(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact_validation_payload(item) for item in value)
    return value


def _redact_validation_body(body: str | None) -> str | None:
    if body is None:
        return None
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError:
        if _VALIDATION_SECRET_RE.search(body):
            return "[non-json body omitted: secret-like field present]"
        return body[:500]
    return json.dumps(_redact_validation_payload(parsed), ensure_ascii=False, separators=(",", ":"))[:500]

# Memory ring-buffer log handler for the admin dashboard.
# Re-exported so existing tests (from kg.api import _mem_log) keep working.
from .mem_log import _MemoryLogHandler, install_memory_log_handler  # noqa: F401

_mem_log = install_memory_log_handler(maxlen=1000)

from .app_router_composition import build_app_routers, include_app_routers
from .app_runtime_state import install_runtime_user_state
from .app_middleware import _anon_rate_limit_key, install_app_middlewares
from .api_compat import *  # noqa: F401,F403 - stable kg.api compatibility surface
from .api_compat import (
    _build_entitlements_response,
    _card_store,
    _current_admin_grant_record,
    _default_subscription_payload,
)
from .rate_limit import api_limiter, translate_limiter
from .service_factories import clear_store_cache
from .settings import KGSettings, load_settings

load_dotenv()

# Initialize Sentry early so module-level errors and the lifespan are captured.
# No-op when SENTRY_DSN is unset.
from .sentry_init import init_sentry  # noqa: E402

init_sentry()


def create_app(settings: KGSettings | None = None) -> FastAPI:
    atexit.register(clear_store_cache)

    settings = settings or load_settings()

    # Sync quota limits with settings
    from .quota_service import configure_limits
    configure_limits(pro=settings.pro_daily_limit_usd, free=settings.free_daily_limit_usd)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        logger.info("KG API starting up")
        # Fail loud if a second worker boots: quota reservations, translate
        # singleflight and pipeline_log are all process-local and only
        # correct under --workers 1. Lock under the injected settings'
        # data_dir so a test app never touches the real backend/data/.
        from .worker_guard import assert_single_worker
        assert_single_worker(settings.data_dir / ".worker.lock")
        # Crash recovery: sweep orphaned 'running' pipeline runs → 'interrupted'.
        # Explicit startup step (not a side-effect of first DB access) so reads
        # stay write-free. Safe only post single-worker lock: workers must not
        # cross-mark each other's runs (see worker_guard).
        from .pipeline_log import reap_orphaned_runs
        reaped = reap_orphaned_runs()
        if reaped:
            logger.info("Reaped %d orphaned pipeline run(s) → interrupted", reaped)
        yield
        logger.info("KG API shutting down")
        from .worker_guard import release_worker_lock
        release_worker_lock()
        from .service_factories import reset_async_clients, reset_clients
        reset_clients()
        await reset_async_clients()

    app = FastAPI(title="Knowledge Graph API", version="0.1.0", lifespan=lifespan)
    app.state.kg_settings = settings

    # --- user store helpers ---
    runtime_user_state = install_runtime_user_state(
        app,
        settings,
        default_subscription_payload_fn=_default_subscription_payload,
    )

    # --- middleware stack ---
    from . import sentry_init as _sentry_init
    from .request_context import request_id_var

    install_app_middlewares(
        app,
        cors_origins=settings.cors_origins,
        rate_limit_trusted_hops=settings.rate_limit_trusted_hops,
        request_id_var=request_id_var,
        tag_request_id=_sentry_init.tag_request_id,
        api_limiter=api_limiter,
        translate_limiter=translate_limiter,
    )

    from fastapi.exceptions import RequestValidationError

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError):
        body = None
        try:
            body = await request.body()
            body = body.decode("utf-8", errors="replace")
        except Exception:
            pass
        errors = _redact_validation_payload(jsonable_encoder(exc.errors()))
        logger.warning(
            "Validation error [%s %s] body=%s errors=%s",
            request.method, request.url.path, _redact_validation_body(body), errors,
        )
        return JSONResponse(status_code=422, content={"detail": errors})

    from .exceptions import KGError

    @app.exception_handler(KGError)
    async def kg_error_handler(request: Request, exc: KGError):
        # Domain errors used to return silently — no log, no Sentry, no metric.
        # That blind spot hid the review-event watermark deadlock (a 400 on every
        # background sync, invisible server-side). Emit one structured line so the
        # whole class of client-rejected / upstream-failed requests is greppable
        # in `logs` and countable. 5xx → error (our fault), 4xx → warning.
        request_id = getattr(request.state, "request_id", "unknown")
        log = logger.error if exc.status_code >= 500 else logger.warning
        log(
            "%s [%s] %s %s -> %d: %s",
            type(exc).__name__, request_id, request.method, request.url.path,
            exc.status_code, exc,
        )
        return JSONResponse(
            status_code=exc.status_code,
            content=exc.to_detail(),
            headers=exc.headers if exc.headers else None,
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        request_id = getattr(request.state, "request_id", "unknown")
        logger.error("Unhandled exception [%s]: %s", request_id, exc, exc_info=True)
        return JSONResponse(status_code=500, content={"detail": "Internal server error", "request_id": request_id})

    # --- routers ---
    def _settings_fn() -> KGSettings:
        return app.state.kg_settings

    def _users_lock_file_fn() -> Path:
        return app.state.kg_settings.users_lock_file

    app_routers = build_app_routers(
        runtime_settings_fn=_settings_fn,
        runtime_users_lock_file_fn=_users_lock_file_fn,
        load_users_fn=runtime_user_state.load_users,
        save_users_fn=runtime_user_state.save_users,
        mem_log_getter=_mem_log.get,
        card_store_factory=_card_store,
        build_entitlements_response_fn=_build_entitlements_response,
        current_admin_grant_record_fn=_current_admin_grant_record,
    )
    include_app_routers(app, app_routers)

    # NOTE: the legacy public /api/podcast-media/ StaticFiles mount was removed
    # (2026-05). It served podcast audio/subtitles WITHOUT auth — a public-read
    # bypass of the authenticated /api/podcasts/{series_id}/{ep_num}/audio
    # endpoint. Production deprecation logs showed zero hits over a 12-day
    # window while the authenticated endpoint served all traffic, confirming
    # every shipped client had migrated. Do NOT reintroduce an unauthenticated
    # mount — route podcast media through the authenticated router instead.

    # --- public static assets (官網 design-system CSS + brand fonts) ---
    # Served at /static/* for the public pages (privacy/terms/support/guide). The
    # files live in backend/static/ so the rsync-only-backend/ deploy ships them;
    # kg-tokens.css / kg-components.css are GENERATED by ops/gen_web_tokens.py
    # (drift from the iOS SoT is guarded by ops/token_drift_check.py). This is a
    # read-only public asset mount — unlike the removed podcast-media mount, it
    # serves no user data, only design-system stylesheets and brand fonts.
    from fastapi.staticfiles import StaticFiles
    _static_dir = Path(__file__).resolve().parent.parent.parent / "static"
    if _static_dir.is_dir():
        app.mount("/static", StaticFiles(directory=_static_dir), name="static")

    # Pin the podcast_progress singleton to the same per-instance data_dir
    # as the rest of the app state — keeps test isolation honest when
    # conftest swaps the settings without touching env vars.
    from . import podcast_progress as _progress_store
    _progress_store.set_data_dir(settings.data_dir)

    return app


app = create_app()
