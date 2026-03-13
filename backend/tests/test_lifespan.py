"""Tests for FastAPI lifespan and global exception handler."""
from __future__ import annotations

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from kg.api import create_app
from kg.settings import KGSettings


def _make_test_settings(tmp_path):
    users_file = tmp_path / "users.json"
    users_file.write_text("{}")
    return KGSettings(
        data_dir=tmp_path,
        jwt_secret="test-secret-key-for-ci-at-least-32-bytes",
        admin_token="adm-secret",
        app_store_allow_unsigned_sync=True,
        app_store_allow_unsigned_notifications=True,
    )


def test_lifespan_startup_shutdown(tmp_path, caplog):
    """App startup/shutdown log messages are emitted."""
    import logging

    settings = _make_test_settings(tmp_path)
    app = create_app(settings)

    with caplog.at_level(logging.INFO, logger="kg.api"):
        with TestClient(app):
            pass  # context exit triggers shutdown

    messages = [r.message for r in caplog.records]
    assert any("starting up" in m for m in messages)
    assert any("shutting down" in m for m in messages)


def test_unhandled_exception_returns_500_with_request_id(tmp_path):
    """Unhandled Exception is caught; response is 500 with request_id, no traceback."""
    settings = _make_test_settings(tmp_path)
    app = create_app(settings)

    @app.get("/test-boom")
    def boom():
        raise RuntimeError("something went very wrong")

    with TestClient(app, raise_server_exceptions=False) as client:
        resp = client.get("/test-boom")

    assert resp.status_code == 500
    body = resp.json()
    assert body["detail"] == "Internal server error"
    assert "request_id" in body
    # No internal traceback text in body
    assert "RuntimeError" not in str(body)
    assert "something went very wrong" not in str(body)


def test_http_exception_not_intercepted(tmp_path):
    """HTTPException is NOT intercepted by the custom handler; FastAPI handles it normally."""
    settings = _make_test_settings(tmp_path)
    app = create_app(settings)

    @app.get("/test-http-exc")
    def raise_http():
        raise HTTPException(status_code=403, detail="Forbidden by test")

    with TestClient(app, raise_server_exceptions=False) as client:
        resp = client.get("/test-http-exc")

    assert resp.status_code == 403
    assert resp.json()["detail"] == "Forbidden by test"
