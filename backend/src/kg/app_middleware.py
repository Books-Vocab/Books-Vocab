from __future__ import annotations

import uuid as _uuid
from collections.abc import Callable
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

RateLimiter = Any


@dataclass(frozen=True)
class AppMiddlewareRuntime:
    rate_limit_exempt_prefixes: tuple[str, ...]


@dataclass(frozen=True)
class AppMiddlewareDependencies:
    app: FastAPI
    cors_origins: tuple[str, ...]
    rate_limit_trusted_hops: int
    request_id_var: ContextVar[str]
    tag_request_id: Callable[[str | None], None]
    api_limiter: RateLimiter
    translate_limiter: RateLimiter


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
        idx = max(0, len(segments) - max(1, hops))
        return segments[idx]
    return client_host if client_host else "unknown"


def install_app_middlewares_from_dependencies(
    *,
    dependencies: AppMiddlewareDependencies,
) -> AppMiddlewareRuntime:
    app = dependencies.app
    cors_origins = dependencies.cors_origins
    rate_limit_trusted_hops = dependencies.rate_limit_trusted_hops
    request_id_var = dependencies.request_id_var
    tag_request_id = dependencies.tag_request_id
    api_limiter = dependencies.api_limiter
    translate_limiter = dependencies.translate_limiter

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(cors_origins),
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
    )

    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or _uuid.uuid4().hex[:16]
        request.state.request_id = request_id
        token = request_id_var.set(request_id)
        tag_request_id(request_id)
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)
        response.headers["X-Request-ID"] = request_id
        return response

    @app.middleware("http")
    async def limit_request_body(request: Request, call_next):
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > 10 * 1024 * 1024:
            return JSONResponse({"detail": "Request body too large"}, status_code=413)
        return await call_next(request)

    rate_limit_exempt_prefixes = (
        "/docs",
        "/openapi.json",
        "/privacy",
        "/support",
        "/terms",
        "/guide",
        "/api/billing/app-store/notifications",
        "/api/system/info",
        "/auth/web/google/callback",
        "/auth/web/apple/callback",
    )

    @app.middleware("http")
    async def rate_limit_middleware(request: Request, call_next):
        path = request.url.path
        if any(path.startswith(prefix) for prefix in rate_limit_exempt_prefixes):
            return await call_next(request)
        auth = request.headers.get("authorization", "")
        if len(auth) > 16:
            key = auth[-16:]
        else:
            xff = request.headers.get("x-forwarded-for", "")
            client_host = request.client.host if request.client else None
            key = _anon_rate_limit_key(xff, client_host, rate_limit_trusted_hops)
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

    return AppMiddlewareRuntime(
        rate_limit_exempt_prefixes=rate_limit_exempt_prefixes,
    )


def install_app_middlewares(
    app: FastAPI,
    *,
    cors_origins: tuple[str, ...],
    rate_limit_trusted_hops: int,
    request_id_var: ContextVar[str],
    tag_request_id: Callable[[str | None], None],
    api_limiter: RateLimiter,
    translate_limiter: RateLimiter,
) -> AppMiddlewareRuntime:
    """Backward-compatible wrapper around :func:`install_app_middlewares_from_dependencies`."""
    return install_app_middlewares_from_dependencies(
        dependencies=AppMiddlewareDependencies(
            app=app,
            cors_origins=cors_origins,
            rate_limit_trusted_hops=rate_limit_trusted_hops,
            request_id_var=request_id_var,
            tag_request_id=tag_request_id,
            api_limiter=api_limiter,
            translate_limiter=translate_limiter,
        )
    )
