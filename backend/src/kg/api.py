"""FastAPI server for Knowledge Graph — lightweight bridge for BooksBrowser.

App factory, middleware stack, and route wiring.
Endpoint functions live in their respective routers/*.py files.
Shared dependencies live in deps.py.

Usage:
    uvicorn kg.api:app --reload --port 8000
"""

from __future__ import annotations

import atexit
import logging
import uuid as _uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

logging.basicConfig(
    level=logging.INFO,
    format='{"ts":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","msg":"%(message)s"}',
)
logger = logging.getLogger(__name__)

# Memory ring-buffer log handler for the admin dashboard.
# Re-exported so existing tests (from kg.api import _mem_log) keep working.
from .mem_log import _MemoryLogHandler, install_memory_log_handler  # noqa: F401

_mem_log = install_memory_log_handler(maxlen=1000)

from .admin_wiring import create_admin_handlers

# Re-export deps symbols so existing tests (import kg.api as api_mod) continue to work.
from .deps import (  # noqa: F401  # noqa: F401
    _MAX_USER_LOCKS,
    _USER_LOCKS,
    _USER_LOCKS_MUTEX,
    _apply_quota_headers,
    _build_entitlements_response,
    _build_links_by_kind,
    _card_response,
    _card_store,
    _check_quota,
    _collect_account_ids_for_deletion,
    _create_jwt_token,
    _current_admin_grant_record,
    _current_subscription_record,
    _daily_stats_store,
    _default_subscription_payload,
    _embedding_store,
    _gemini_async_client,
    _gemini_client,
    _get_settings,
    _graph_store,
    _is_pro,
    _notification_status,
    _parse_datetime,
    _resolve_and_link_user,
    _resolve_user_id_from_subscription_index,
    _with_quota_check,
    _write_subscription_snapshot,
    get_current_user,
    get_user_lock,
    security,
)
from .rate_limit import api_limiter, translate_limiter
from .routers import (
    auth_router,
    billing_router,
    build_admin_router,
    notebook_router,
    pipeline_router,
    static_pages_router,
    system_router,
    translate_router,
    user_router,
    vocab_router,
    web_auth_router,
)

# Re-export endpoint functions from routers for backward compatibility.
from .routers.auth import auth_verify  # noqa: F401
from .routers.billing import (  # noqa: F401
    app_store_notifications,
    reconcile_app_store_subscription,
    sync_app_store_subscription,
)
from .routers.pipeline import _run_pipeline_background, run_pipeline  # noqa: F401
from .routers.podcast import router as podcast_router
from .routers.static_pages import get_guide, get_privacy_policy, get_support, get_terms  # noqa: F401
from .routers.translate import translate_explain, translate_phrase, translate_quick  # noqa: F401
from .routers.user import (  # noqa: F401
    delete_user_account,
    get_user_config,
    get_user_entitlements,
    get_user_quota,
    health,
    update_user_config,
)
from .routers.vocab import (  # noqa: F401
    add_vocab,
    archive_word,
    delete_word,
    get_graph_links,
    list_vocab,
    lookup_word,
    pull_daily_stats,
    push_daily_stats,
    push_review,
)
from .service_factories import clear_store_cache
from .settings import KGSettings, load_settings
from .user_store import (
    CachedUserStore,
    normalize_users_payload,
)

load_dotenv()

# Initialize Sentry early so module-level errors and the lifespan are captured.
# No-op when SENTRY_DSN is unset.
from .sentry_init import init_sentry  # noqa: E402

init_sentry()


def _anon_rate_limit_key(xff: str, client_host: str | None, hops: int) -> str:
    """Derive the rate-limit key for an anonymous (no-auth) request.

    `hops` = number of trusted proxy hops in front of the app. The real client
    IP is taken from the `hops`-th-from-end X-Forwarded-For segment.

    Production contract: single-layer bare Caddy on AWS public net appends the
    real client IP to the END of XFF, so hops=1 selects the last segment — this
    is byte-for-byte identical to the legacy `xff.split(",")[-1].strip()`.
    Raise hops to N+1 only when N trusted proxies (CDN/ALB) front Caddy.

    Safe fallbacks: empty XFF -> client_host (or "unknown"); hops exceeding the
    available segment count -> the frontmost segment (never raises IndexError).
    """
    if xff:
        segments = [s.strip() for s in xff.split(",")]
        # hops=1 -> index -1 (last). Clamp so hops beyond segment count (or a
        # non-positive misconfig) safely lands on the frontmost segment.
        idx = max(0, len(segments) - max(1, hops))
        return segments[idx]
    return client_host if client_host else "unknown"


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
        yield
        logger.info("KG API shutting down")
        from .worker_guard import release_worker_lock
        release_worker_lock()
        from .service_factories import reset_async_gemini_client, reset_gemini_client
        reset_gemini_client()
        await reset_async_gemini_client()

    app = FastAPI(title="Knowledge Graph API", version="0.1.0", lifespan=lifespan)
    app.state.kg_settings = settings

    # --- user store helpers ---
    def _normalize_users_payload_fn(users: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        from .secret_store import encrypt_value
        jwt_secret = app.state.kg_settings.jwt_secret
        encrypt_fn = (lambda v: encrypt_value(v, jwt_secret)) if jwt_secret else None
        return normalize_users_payload(users, _default_subscription_payload, encrypt_fn=encrypt_fn)

    user_store = CachedUserStore(app.state.kg_settings.users_file, _normalize_users_payload_fn)
    app.state.user_store = user_store

    def _load_users_fn() -> dict[str, dict[str, Any]]:
        return app.state.user_store.load()

    def _save_users_fn(users: dict[str, dict[str, Any]]) -> None:
        app.state.user_store.save(users)

    app.state.load_users = _load_users_fn
    app.state.save_users = _save_users_fn
    app.state.normalize_users_payload = _normalize_users_payload_fn

    # --- middleware stack ---
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
    )

    from . import sentry_init as _sentry_init
    from .request_context import request_id_var

    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or _uuid.uuid4().hex[:16]
        request.state.request_id = request_id
        token = request_id_var.set(request_id)
        # Tag the Sentry scope so error events / traces carry the same
        # correlation id surfaced in logs + the X-Request-ID response header.
        # No-op when Sentry isn't initialized (dev/test).
        _sentry_init.tag_request_id(request_id)
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)
        response.headers["X-Request-ID"] = request_id
        return response

    @app.middleware("http")
    async def limit_request_body(request, call_next):
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > 10 * 1024 * 1024:
            return JSONResponse({"detail": "Request body too large"}, status_code=413)
        return await call_next(request)

    # Rate-limit exempt prefixes. Compared with `path.startswith(p)` so any
    # path that begins with one of these is bypassed.
    #
    # Why OAuth callbacks are exempt:
    # * `/auth/web/google/callback` is reached by the user's browser after
    #   Google's redirect — but the limiter key falls back to XFF / client.host
    #   (no Authorization header yet), which collides across shared NAT and
    #   can 429 unrelated users mid-login.
    # * `/auth/web/apple/callback` is reached via a POST from Apple's servers
    #   themselves, so every callback shares one source IP. With a Pro user
    #   community larger than `API_RATE_LIMIT` per minute, Apple sign-in
    #   would silently fail for everyone after the burst.
    # The callbacks are state-validated (oauth_state cookie + provider state)
    # and naturally rare per session, so abuse protection is already in place.
    _RATE_LIMIT_EXEMPT = {
        "/docs", "/openapi.json", "/privacy", "/support", "/terms", "/guide",
        "/api/billing/app-store/notifications",
        "/api/system/info",
        "/auth/web/google/callback",
        "/auth/web/apple/callback",
    }

    @app.middleware("http")
    async def rate_limit_middleware(request: Request, call_next):
        path = request.url.path
        if any(path.startswith(p) for p in _RATE_LIMIT_EXEMPT):
            return await call_next(request)
        auth = request.headers.get("authorization", "")
        if len(auth) > 16:
            key = auth[-16:]
        else:
            xff = request.headers.get("x-forwarded-for", "")
            client_host = request.client.host if request.client else None
            key = _anon_rate_limit_key(
                xff, client_host, settings.rate_limit_trusted_hops
            )
        limiter = translate_limiter if "/api/translate" in path else api_limiter
        if not await limiter.is_allowed(key):
            return JSONResponse(
                {"detail": "Too many requests"}, status_code=429,
                headers={"Retry-After": str(limiter.window_seconds)},
            )
        return await call_next(request)

    @app.middleware("http")
    async def security_headers_middleware(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["X-XSS-Protection"] = "0"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        if request.url.scheme == "https":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response

    from fastapi.exceptions import RequestValidationError

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError):
        body = None
        try:
            body = await request.body()
            body = body.decode("utf-8", errors="replace")[:500]
        except Exception:
            pass
        logger.warning(
            "Validation error [%s %s] body=%s errors=%s",
            request.method, request.url.path, body, exc.errors(),
        )
        return JSONResponse(status_code=422, content={"detail": exc.errors()})

    from .exceptions import KGError

    @app.exception_handler(KGError)
    async def kg_error_handler(request: Request, exc: KGError):
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
    app.include_router(system_router)
    app.include_router(static_pages_router)
    app.include_router(user_router)
    app.include_router(billing_router)
    app.include_router(vocab_router)
    app.include_router(notebook_router)
    app.include_router(pipeline_router)
    app.include_router(translate_router)
    app.include_router(auth_router)
    app.include_router(web_auth_router)
    app.include_router(podcast_router)

    # Admin router uses builder pattern (runtime closures)
    def _settings_fn() -> KGSettings:
        return app.state.kg_settings

    def _users_lock_file_fn() -> Path:
        return app.state.kg_settings.users_lock_file

    admin_handlers = create_admin_handlers(
        runtime_settings_fn=_settings_fn,
        runtime_users_lock_file_fn=_users_lock_file_fn,
        load_users_fn=_load_users_fn,
        save_users_fn=_save_users_fn,
        mem_log_getter=_mem_log.get,
        card_store_factory=_card_store,
        build_entitlements_response_fn=_build_entitlements_response,
        current_admin_grant_record_fn=_current_admin_grant_record,
    )
    login_r, html_r, api_r = build_admin_router(
        **admin_handlers, runtime_settings_fn=_settings_fn,
    )
    app.include_router(login_r)
    app.include_router(html_r)
    app.include_router(api_r)

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
