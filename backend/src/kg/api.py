"""FastAPI server for Knowledge Graph — lightweight bridge for BooksBrowser.

App factory, middleware stack, and route wiring.
Endpoint definitions live in endpoints.py.

Usage:
    uvicorn kg.api:app --reload --port 8000
"""

from __future__ import annotations

import atexit
import collections
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


class _MemoryLogHandler(logging.Handler):
    """Ring-buffer log handler for the admin dashboard."""
    def __init__(self, maxlen: int = 1000):
        super().__init__()
        self._buf: collections.deque = collections.deque(maxlen=maxlen)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            from datetime import datetime as _dt
            from .request_context import request_id_var
            self._buf.append({
                "ts": _dt.fromtimestamp(record.created).strftime("%H:%M:%S"),
                "level": record.levelname,
                "name": record.name,
                "msg": record.getMessage(),
                "request_id": request_id_var.get("-"),
            })
        except Exception:
            pass  # handler must never crash the application

    def get(self, n: int = 200, level: str | None = None) -> list[dict]:
        rows = list(self._buf)
        if level:
            rows = [r for r in rows if r["level"] == level]
        return rows[-n:]

_mem_log = _MemoryLogHandler(maxlen=1000)
_mem_log.setLevel(logging.DEBUG)

def _attach_memory_log_handler(logger_name: str) -> None:
    target = logging.getLogger(logger_name)
    if not any(h is _mem_log for h in target.handlers):
        target.addHandler(_mem_log)

_attach_memory_log_handler("")  # root logger
_attach_memory_log_handler("uvicorn")
_attach_memory_log_handler("uvicorn.error")
_attach_memory_log_handler("uvicorn.access")

from .admin_wiring import create_admin_handlers
from .rate_limit import api_limiter, translate_limiter
from .route_registration import register_routes
from .service_factories import clear_store_cache
from .settings import KGSettings, load_settings
from .user_store import (
    CachedUserStore,
    normalize_users_payload,
)

# Re-export endpoints module symbols so existing tests (import kg.api as api_mod)
# and external code continue to work without changes.
from .endpoints import (  # noqa: F401
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
    _MAX_USER_LOCKS,
    _notification_status,
    _parse_datetime,
    _require_pro_access,
    _resolve_and_link_user,
    _resolve_user_id_from_subscription_index,
    _run_pipeline_background,
    _with_quota_check,
    _write_subscription_snapshot,
    add_vocab,
    app_store_notifications,
    archive_word,
    auth_verify,
    delete_user_account,
    delete_word,
    get_current_user,
    get_graph_links,
    get_guide,
    get_privacy_policy,
    get_support,
    get_terms,
    get_user_config,
    get_user_entitlements,
    get_user_lock,
    get_user_quota,
    health,
    list_vocab,
    lookup_word,
    pull_daily_stats,
    push_daily_stats,
    push_review,
    reconcile_app_store_subscription,
    run_pipeline,
    security,
    sync_app_store_subscription,
    translate_explain,
    translate_phrase,
    translate_quick,
    update_user_config,
)
# Re-export mutable globals that tests manipulate directly
from .endpoints import _USER_LOCKS, _USER_LOCKS_MUTEX  # noqa: F401

load_dotenv()


def create_app(settings: KGSettings | None = None) -> FastAPI:
    atexit.register(clear_store_cache)

    settings = settings or load_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        logger.info("KG API starting up")
        yield
        logger.info("KG API shutting down")
        from .service_factories import reset_gemini_client
        reset_gemini_client()

    app = FastAPI(title="Knowledge Graph API", version="0.1.0", lifespan=lifespan)
    app.state.kg_settings = settings

    # --- user store helpers (closures capturing app reference) ---
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
        allow_origins=[
            "https://wordnexus.lol",
            "http://localhost:8000",
            "http://127.0.0.1:8000",
        ],
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
    )

    from .request_context import request_id_var

    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or _uuid.uuid4().hex[:16]
        request.state.request_id = request_id
        token = request_id_var.set(request_id)
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)
        response.headers["X-Request-ID"] = request_id
        return response

    @app.middleware("http")
    async def limit_request_body(request, call_next):
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > 10 * 1024 * 1024:  # 10MB
            return JSONResponse({"detail": "Request body too large"}, status_code=413)
        return await call_next(request)

    _RATE_LIMIT_EXEMPT = {
        "/docs",
        "/openapi.json",
        "/privacy",
        "/support",
        "/terms",
        "/guide",
        "/api/billing/app-store/notifications",
        "/admin",
    }

    @app.middleware("http")
    async def rate_limit_middleware(request: Request, call_next):
        path = request.url.path
        if any(path.startswith(p) for p in _RATE_LIMIT_EXEMPT):
            return await call_next(request)

        auth = request.headers.get("authorization", "")
        key = auth[-16:] if len(auth) > 16 else (request.client.host if request.client else "unknown")

        limiter = translate_limiter if "/api/translate" in path else api_limiter

        if not await limiter.is_allowed(key):
            return JSONResponse(
                {"detail": "Too many requests"},
                status_code=429,
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

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        request_id = getattr(request.state, "request_id", "unknown")
        logger.error("Unhandled exception [%s]: %s", request_id, exc, exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error", "request_id": request_id},
        )

    # --- admin + route wiring ---
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

    register_routes(
        app,
        get_privacy_policy=get_privacy_policy,
        get_support=get_support,
        get_terms=get_terms,
        get_guide=get_guide,
        get_user_config=get_user_config,
        get_user_entitlements=get_user_entitlements,
        get_user_quota=get_user_quota,
        update_user_config=update_user_config,
        delete_user_account=delete_user_account,
        health=health,
        sync_app_store_subscription=sync_app_store_subscription,
        app_store_notifications=app_store_notifications,
        reconcile_app_store_subscription=reconcile_app_store_subscription,
        list_vocab=list_vocab,
        lookup_word=lookup_word,
        archive_word=archive_word,
        delete_word=delete_word,
        get_graph_links=get_graph_links,
        add_vocab=add_vocab,
        push_review=push_review,
        push_daily_stats=push_daily_stats,
        pull_daily_stats=pull_daily_stats,
        run_pipeline=run_pipeline,
        translate_quick=translate_quick,
        translate_phrase=translate_phrase,
        translate_explain=translate_explain,
        auth_verify=auth_verify,
        **admin_handlers,
    )
    return app


app = create_app()
