"""Integration tests for GET /api/user/profile.

Read-only identity face (displayName / email / provider) derived from the
stored user record (set at login by auth_service.resolve_and_link_user).
Distinct from GET /api/user/config (mutable settings bundle).
"""
from __future__ import annotations

import json
import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import kg.api as api_mod
import kg.deps as deps_mod
from conftest import TEST_JWT_SECRET, _swap_settings, make_jwt
from kg.api import app
from kg.settings import KGSettings


def _build_api(tmp_path, record: dict):
    data_dir = tmp_path
    (data_dir / "users").mkdir()
    user_id = "u_" + uuid.uuid4().hex[:8]
    (data_dir / "users.json").write_text(json.dumps({user_id: record}))

    token = make_jwt(user_id)
    headers = {"Authorization": f"Bearer {token}"}

    original_settings = app.state.kg_settings
    original_load = app.state.load_users
    original_save = app.state.save_users

    _swap_settings(KGSettings(data_dir=data_dir, jwt_secret=TEST_JWT_SECRET))
    api_mod._USER_LOCKS.clear()
    deps_mod._USER_LOCKS_MUTEX = None
    return SimpleNamespace(
        client=TestClient(app, raise_server_exceptions=False),
        user_id=user_id,
        headers=headers,
        _restore=lambda: (
            setattr(app.state, "kg_settings", original_settings),
            setattr(app.state, "load_users", original_load),
            setattr(app.state, "save_users", original_save),
        ),
    )


@pytest.fixture()
def profile_api_factory(tmp_path):
    built: list = []

    def _make(record: dict):
        api = _build_api(tmp_path, record)
        built.append(api)
        return api

    yield _make
    for api in built:
        api._restore()


def test_profile_returns_email_and_provider(profile_api_factory):
    api = profile_api_factory(
        {"config": {}, "provider": "google", "email": "alice@example.com"}
    )
    r = api.client.get("/api/user/profile", headers=api.headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["email"] == "alice@example.com"
    assert body["provider"] == "google"


def test_display_name_falls_back_to_email_local_part(profile_api_factory):
    api = profile_api_factory(
        {"config": {}, "provider": "apple", "email": "bob@example.com"}
    )
    body = api.client.get("/api/user/profile", headers=api.headers).json()
    assert body["displayName"] == "bob"


def test_explicit_display_name_used_when_present(profile_api_factory):
    api = profile_api_factory(
        {"config": {}, "provider": "google", "email": "c@x.com", "display_name": "Carol"}
    )
    body = api.client.get("/api/user/profile", headers=api.headers).json()
    assert body["displayName"] == "Carol"


def test_profile_null_email_yields_null_fields(profile_api_factory):
    api = profile_api_factory({"config": {}, "provider": "apple", "email": None})
    body = api.client.get("/api/user/profile", headers=api.headers).json()
    assert body["email"] is None
    assert body["provider"] == "apple"
    # No email and no display_name -> displayName is null (no fabrication).
    assert body["displayName"] is None


def test_profile_requires_auth(profile_api_factory):
    api = profile_api_factory({"config": {}, "provider": "google", "email": "a@b.com"})
    r = api.client.get("/api/user/profile")
    assert r.status_code == 401, r.text
