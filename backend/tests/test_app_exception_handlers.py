from __future__ import annotations

import json
import logging
from dataclasses import replace

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field

from kg.app_exception_handlers import (
    AppExceptionHandlerDependencies,
    AppExceptionHandlers,
    _redact_validation_body,
    _redact_validation_payload,
    _sanitize_non_finite,
    install_app_exception_handlers_from_dependencies,
)
from kg.exceptions import BadRequestError, ExternalServiceError


class _Payload(BaseModel):
    provider: str = Field(min_length=10)
    token: str


def _dependencies(app: FastAPI) -> AppExceptionHandlerDependencies:
    return AppExceptionHandlerDependencies(
        app=app,
        logger=logging.getLogger("kg.api"),
    )


@pytest.fixture(autouse=True)
def _assert_test_clients_are_closed(monkeypatch):
    clients = []
    closed = set()
    original_init = TestClient.__init__
    original_close = TestClient.close

    def tracked_init(client, *args, **kwargs):
        original_init(client, *args, **kwargs)
        clients.append(client)

    def tracked_close(client):
        closed.add(id(client))
        return original_close(client)

    monkeypatch.setattr(TestClient, "__init__", tracked_init)
    monkeypatch.setattr(TestClient, "close", tracked_close)
    yield
    assert len(closed) == len(clients)


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
    try:
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
    finally:
        client.close()


def test_app_exception_handler_dependencies_are_replaceable_named_contract():
    deps = _dependencies(FastAPI())
    replacement = replace(deps, logger=logging.getLogger("kg.api.alt"))

    assert deps.logger.name == "kg.api"
    assert replacement.logger.name == "kg.api.alt"


def test_validation_redaction_helpers_preserve_legacy_contract():
    assert _redact_validation_payload([{"loc": ["body", "accessToken"], "input": "secret-access-token"}]) == [
        {"loc": ["body", "accessToken"], "input": "[REDACTED]"}
    ]

    assert (
        _redact_validation_body("apiKey=secret-api-key&client-secret=secret-client&safe=visible")
        == "[non-json body omitted: secret-like field present]"
    )


class _NonFinitePayload(BaseModel):
    count: int = 0
    name: str = ""
    ratio: float = Field(default=0.0, ge=0.0, le=1.0)


def _reject_constant(name: str):
    raise AssertionError(f"non-strict JSON constant {name}")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("NaN", "NaN"), ("Infinity", "Infinity"), ("-Infinity", "-Infinity"), ("1e309", "Infinity")],
)
@pytest.mark.parametrize("field", ["count", "name", "ratio"])
def test_validation_handler_returns_strict_json_422_for_non_finite_input(field, raw, expected):
    app = FastAPI()
    install_app_exception_handlers_from_dependencies(
        dependencies=_dependencies(app),
    )

    @app.post("/payload")
    def post_payload(payload: _NonFinitePayload):
        return payload

    client = TestClient(app, raise_server_exceptions=False)
    try:
        response = client.post(
            "/payload",
            content=f'{{"{field}": {raw}}}',
            headers={"content-type": "application/json"},
        )
    finally:
        client.close()

    assert response.status_code == 422, response.text
    body = json.loads(response.text, parse_constant=_reject_constant)
    assert body["detail"][0]["input"] == expected


def test_sanitize_non_finite_recurses_through_dict_list_and_tuple():
    value = {
        "a": float("nan"),
        "b": [float("inf"), {"c": float("-inf")}, 1.5],
        "d": (float("nan"), "x"),
    }

    assert _sanitize_non_finite(value) == {
        "a": "NaN",
        "b": ["Infinity", {"c": "-Infinity"}, 1.5],
        "d": ("NaN", "x"),
    }


def _kg_error_client(error: Exception) -> tuple[TestClient, FastAPI]:
    app = FastAPI()
    install_app_exception_handlers_from_dependencies(dependencies=_dependencies(app))

    @app.get("/fail")
    def fail():
        raise error

    return TestClient(app, raise_server_exceptions=False), app


def test_5xx_kg_error_logs_cause_but_response_stays_opaque(caplog):
    client, _app = _kg_error_client(ExternalServiceError("x", exc=httpx.ConnectError("boom")))
    try:
        with caplog.at_level(logging.WARNING, logger="kg.api"):
            response = client.get("/fail")
    finally:
        client.close()

    assert response.status_code == 502
    assert response.json() == {"code": "EXTERNAL_SERVICE_ERROR", "label": "x"}
    record = next(r for r in caplog.records if r.name == "kg.api" and r.levelno == logging.ERROR)
    assert record.exc_info is not None
    assert record.exc_info[0] is httpx.ConnectError
    assert "boom" in str(record.exc_info[1])


def test_4xx_kg_error_does_not_attach_exc_info(caplog):
    client, _app = _kg_error_client(BadRequestError("nope"))
    try:
        with caplog.at_level(logging.WARNING, logger="kg.api"):
            response = client.get("/fail")
    finally:
        client.close()

    assert response.status_code == 400
    record = next(r for r in caplog.records if r.name == "kg.api")
    assert record.exc_info is None


def test_validation_error_log_omits_raw_input_but_response_keeps_it(caplog):
    """#2303: the server log must not carry user-supplied field values."""
    app = FastAPI()
    handlers_deps = _dependencies(app)
    install_app_exception_handlers_from_dependencies(dependencies=handlers_deps)

    @app.post("/payload")
    def post_payload(payload: _NonFinitePayload):
        return payload

    sentinel = "private-user-note-xyz"
    client = TestClient(app, raise_server_exceptions=False)
    try:
        with caplog.at_level(logging.WARNING, logger=handlers_deps.logger.name):
            response = client.post("/payload", json={"count": sentinel})
    finally:
        client.close()

    assert response.status_code == 422
    assert response.json()["detail"][0]["input"] == sentinel
    logged = " ".join(r.getMessage() for r in caplog.records)
    assert "Validation error" in logged
    assert sentinel not in logged.split("errors=", 1)[1]
