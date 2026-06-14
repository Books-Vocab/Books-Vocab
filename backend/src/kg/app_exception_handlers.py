from __future__ import annotations

import json
import logging
import re
from collections.abc import Awaitable
from dataclasses import dataclass
from typing import Any, Protocol

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class AppExceptionHandler(Protocol):
    def __call__(self, request: Request, exc: Exception) -> Awaitable[JSONResponse]:
        ...

from .exceptions import KGError

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


@dataclass(frozen=True)
class AppExceptionHandlers:
    validation_error_handler: AppExceptionHandler
    kg_error_handler: AppExceptionHandler
    unhandled_exception_handler: AppExceptionHandler


@dataclass(frozen=True)
class AppExceptionHandlerDependencies:
    app: FastAPI
    logger: logging.Logger | Any


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


def install_app_exception_handlers_from_dependencies(
    *,
    dependencies: AppExceptionHandlerDependencies,
) -> AppExceptionHandlers:
    app = dependencies.app
    logger = dependencies.logger

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
            request.method,
            request.url.path,
            _redact_validation_body(body),
            errors,
        )
        return JSONResponse(status_code=422, content={"detail": errors})

    @app.exception_handler(KGError)
    async def kg_error_handler(request: Request, exc: KGError):
        request_id = getattr(request.state, "request_id", "unknown")
        log = logger.error if exc.status_code >= 500 else logger.warning
        log(
            "%s [%s] %s %s -> %d: %s",
            type(exc).__name__,
            request_id,
            request.method,
            request.url.path,
            exc.status_code,
            exc,
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
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error", "request_id": request_id},
        )

    return AppExceptionHandlers(
        validation_error_handler=validation_error_handler,
        kg_error_handler=kg_error_handler,
        unhandled_exception_handler=unhandled_exception_handler,
    )


def install_app_exception_handlers(
    app: FastAPI,
    *,
    logger: logging.Logger | Any,
) -> AppExceptionHandlers:
    """Backward-compatible wrapper around :func:`install_app_exception_handlers_from_dependencies`."""
    return install_app_exception_handlers_from_dependencies(
        dependencies=AppExceptionHandlerDependencies(
            app=app,
            logger=logger,
        )
    )
