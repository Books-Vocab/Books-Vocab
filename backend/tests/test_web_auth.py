"""Tests for the web OAuth flow (Chrome extension login)."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import kg.api as api_mod
import kg.deps as deps_mod
from conftest import TEST_GOOGLE_REDIRECT_URI, TEST_JWT_SECRET, _swap_settings
from kg.api import app
from kg.settings import KGSettings


@pytest.fixture()
def web_auth_env(tmp_path):
    data_dir = tmp_path
    (data_dir / "users").mkdir()
    users_file = data_dir / "users.json"
    users_file.write_text(json.dumps({}))

    original_settings = app.state.kg_settings
    original_load = app.state.load_users
    original_save = app.state.save_users
    test_settings = KGSettings(
        data_dir=data_dir,
        jwt_secret=TEST_JWT_SECRET,
        google_client_id="test-google-client-id",
        google_client_secret="test-google-client-secret",
        google_redirect_uri=TEST_GOOGLE_REDIRECT_URI,
        chrome_extension_id="test-extension-id-abc",
    )
    _swap_settings(test_settings)

    try:
        api_mod._USER_LOCKS.clear()
        deps_mod._USER_LOCKS_MUTEX = None
        client = TestClient(app, raise_server_exceptions=False)
        yield SimpleNamespace(client=client, data_dir=data_dir)
    finally:
        app.state.kg_settings = original_settings
        app.state.load_users = original_load
        app.state.save_users = original_save


def test_login_page_returns_200_with_google(web_auth_env):
    resp = web_auth_env.client.get("/login")
    assert resp.status_code == 200
    assert "Google" in resp.text


def test_login_page_returns_200_with_apple(web_auth_env):
    resp = web_auth_env.client.get("/login")
    assert resp.status_code == 200
    assert "Apple" in resp.text


def test_google_login_redirects_to_google(web_auth_env):
    resp = web_auth_env.client.get("/auth/web/google/login", follow_redirects=False)
    assert resp.status_code == 307
    location = resp.headers["location"]
    assert "accounts.google.com" in location
    assert "client_id=test-google-client-id" in location
    assert "redirect_uri=" in location
    assert "response_type=code" in location
    assert "scope=" in location


def test_web_auth_router_is_registered(web_auth_env):
    """The web_auth router should be included in the app."""
    routes = [r.path for r in app.routes]
    assert "/login" in routes
    assert "/auth/web/google/login" in routes
    assert "/auth/web/google/callback" in routes
    assert "/auth/web/apple/callback" in routes
