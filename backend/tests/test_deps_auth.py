from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from starlette.requests import Request

import kg.deps as deps


def _make_request():
    state = SimpleNamespace(
        kg_settings=object(),
        load_users=lambda: {"user-123": {"config": {}}},
    )
    app = SimpleNamespace(state=state)
    return Request({"type": "http", "app": app, "headers": []})


def test_get_current_user_optional_returns_guest_without_auth_header():
    request = _make_request()

    assert deps.get_current_user_optional(request, credentials=None, authorization=None) is None


def test_get_current_user_optional_rejects_invalid_authorization_header():
    request = _make_request()

    with pytest.raises(HTTPException) as exc_info:
        deps.get_current_user_optional(
            request,
            credentials=None,
            authorization="Token not-a-bearer-header",
        )

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Invalid authentication credentials"
    assert exc_info.value.headers == {"WWW-Authenticate": "Bearer"}


@pytest.mark.parametrize("use_optional_dependency", [False, True])
def test_auth_dependencies_share_the_same_user_resolution_path(monkeypatch, use_optional_dependency):
    request = _make_request()
    settings = request.app.state.kg_settings
    load_users = request.app.state.load_users
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="jwt-token")
    observed: dict[str, object] = {}

    def fake_resolve_current_user(token, *, settings, load_users, parse_datetime):
        observed["token"] = token
        observed["settings"] = settings
        observed["load_users"] = load_users
        observed["parsed"] = parse_datetime("2026-06-08T12:34:56")
        return {"id": "user-123"}

    def fake_bind_user(user_id):
        observed["bound_user_id"] = user_id

    monkeypatch.setattr(deps, "resolve_current_user", fake_resolve_current_user)
    monkeypatch.setattr(deps, "bind_user", fake_bind_user)

    if use_optional_dependency:
        user = deps.get_current_user_optional(request, credentials=credentials, authorization=None)
    else:
        user = deps.get_current_user(request, credentials=credentials)

    assert user == {"id": "user-123"}
    assert observed == {
        "token": "jwt-token",
        "settings": settings,
        "load_users": load_users,
        "parsed": deps._parse_datetime("2026-06-08T12:34:56"),
        "bound_user_id": "user-123",
    }
