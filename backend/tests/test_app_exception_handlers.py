from __future__ import annotations

import logging
from dataclasses import replace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field

from kg.app_exception_handlers import (
    AppExceptionHandlerDependencies,
    AppExceptionHandlers,
    _redact_validation_body,
    _redact_validation_payload,
    install_app_exception_handlers,
    install_app_exception_handlers_from_dependencies,
)
from kg.exceptions import BadRequestError


class _Payload(BaseModel):
    provider: str = Field(min_length=10)
    token: str


def _dependencies(app: FastAPI) -> AppExceptionHandlerDependencies:
    return AppExceptionHandlerDependencies(
        app=app,
        logger=logging.getLogger("kg.api"),
    )


def test_install_app_exception_handlers_returns_named_bundle_and_handles_routes():
    app = FastAPI()
    handlers = install_app_exception_handlers_from_dependencies(
        dependencies=_dependencies(app),
    )

    @app.post("/validate")
    def validate(payload: _Payload):
        return payload.model_dump()

    @app.get("/bad-request")
    def bad_request():
        raise BadRequestError("broken request")

    @app.get("/boom")
    def boom():
        raise RuntimeError("boom")

    assert isinstance(handlers, AppExceptionHandlers)

    client = TestClient(app, raise_server_exceptions=False)

    validation = client.post("/validate", json={"provider": "short", "token": "secret-token"})
    assert validation.status_code == 422
    assert validation.json()["detail"][0]["type"] == "string_too_short"

    bad_request_response = client.get("/bad-request")
    assert bad_request_response.status_code == 400
    assert bad_request_response.json()["code"] == "BadRequestError"

    boom_response = client.get("/boom")
    assert boom_response.status_code == 500
    assert boom_response.json()["detail"] == "Internal server error"
    assert "request_id" in boom_response.json()


def test_install_app_exception_handlers_from_dependencies_matches_compat_wrapper():
    named_app = FastAPI()
    compat_app = FastAPI()

    named = install_app_exception_handlers_from_dependencies(
        dependencies=_dependencies(named_app),
    )
    compat = install_app_exception_handlers(
        compat_app,
        logger=logging.getLogger("kg.api"),
    )

    assert isinstance(named, AppExceptionHandlers)
    assert isinstance(compat, AppExceptionHandlers)
    assert callable(named.validation_error_handler)
    assert callable(named.kg_error_handler)
    assert callable(named.unhandled_exception_handler)
    assert callable(compat.validation_error_handler)
    assert callable(compat.kg_error_handler)
    assert callable(compat.unhandled_exception_handler)


def test_app_exception_handler_dependencies_are_replaceable_named_contract():
    deps = _dependencies(FastAPI())
    replacement = replace(deps, logger=logging.getLogger("kg.api.alt"))

    assert deps.logger.name == "kg.api"
    assert replacement.logger.name == "kg.api.alt"


def test_validation_redaction_helpers_preserve_legacy_contract():
    assert _redact_validation_payload(
        [{"loc": ["body", "accessToken"], "input": "secret-access-token"}]
    ) == [{"loc": ["body", "accessToken"], "input": "[REDACTED]"}]

    assert _redact_validation_body(
        "apiKey=secret-api-key&client-secret=secret-client&safe=visible"
    ) == "[non-json body omitted: secret-like field present]"
