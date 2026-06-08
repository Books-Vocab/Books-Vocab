from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field

from kg.app_exception_handlers import (
    AppExceptionHandlers,
    _redact_validation_body,
    _redact_validation_payload,
    install_app_exception_handlers,
)
from kg.exceptions import BadRequestError


class _Payload(BaseModel):
    provider: str = Field(min_length=10)
    token: str


def test_install_app_exception_handlers_returns_named_bundle_and_handles_routes():
    app = FastAPI()
    handlers = install_app_exception_handlers(app, logger=logging.getLogger("kg.api"))

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

    bad_request = client.get("/bad-request")
    assert bad_request.status_code == 400
    assert bad_request.json()["code"] == "BadRequestError"

    boom = client.get("/boom")
    assert boom.status_code == 500
    assert boom.json()["detail"] == "Internal server error"
    assert "request_id" in boom.json()


def test_validation_redaction_helpers_preserve_legacy_contract():
    assert _redact_validation_payload(
        [{"loc": ["body", "accessToken"], "input": "secret-access-token"}]
    ) == [{"loc": ["body", "accessToken"], "input": "[REDACTED]"}]

    assert _redact_validation_body(
        "apiKey=secret-api-key&client-secret=secret-client&safe=visible"
    ) == "[non-json body omitted: secret-like field present]"
