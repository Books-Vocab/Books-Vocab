from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import jwt as pyjwt
import pytest
from fastapi import HTTPException

from kg.settings import KGSettings
from kg.user_context import resolve_current_user

TEST_JWT_SECRET = "test-secret-key-for-ci-at-least-32-bytes"
TEST_ALGORITHM = "HS256"


def _make_settings(tmp_path: Path) -> KGSettings:
    return KGSettings(
        data_dir=tmp_path,
        jwt_secret=TEST_JWT_SECRET,
        jwt_algorithm=TEST_ALGORITHM,
    )


def _make_jwt(user_id: str, *, expires_in: timedelta = timedelta(hours=1)) -> str:
    payload = {
        "sub": user_id,
        "iat": datetime.now(tz=UTC),
        "exp": datetime.now(tz=UTC) + expires_in,
    }
    return pyjwt.encode(payload, TEST_JWT_SECRET, algorithm=TEST_ALGORITHM)


def _load_users_fn(users_file: Path):
    def _load():
        return json.loads(users_file.read_text())
    return _load


def _parse_datetime(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except (ValueError, TypeError):
        return None


def test_valid_jwt_resolves_user(tmp_path):
    users_file = tmp_path / "users.json"
    user_id = "user-abc"
    users_file.write_text(json.dumps({user_id: {"config": {}}}))

    token = _make_jwt(user_id)
    settings = _make_settings(tmp_path)

    result = resolve_current_user(
        token,
        settings=settings,
        load_users=_load_users_fn(users_file),
        parse_datetime=_parse_datetime,
    )
    assert result["id"] == user_id


def test_invalid_token_raises_401(tmp_path):
    users_file = tmp_path / "users.json"
    users_file.write_text(json.dumps({}))

    settings = _make_settings(tmp_path)

    with pytest.raises(HTTPException) as exc_info:
        resolve_current_user(
            "not-a-jwt-token",
            settings=settings,
            load_users=_load_users_fn(users_file),
            parse_datetime=_parse_datetime,
        )

    assert exc_info.value.status_code == 401


def test_random_string_token_raises_401_not_used_as_user_id(tmp_path):
    users_file = tmp_path / "users.json"
    arbitrary_id = "some-arbitrary-user-id"
    users_file.write_text(json.dumps({arbitrary_id: {"config": {}}}))

    settings = _make_settings(tmp_path)

    with pytest.raises(HTTPException) as exc_info:
        resolve_current_user(
            arbitrary_id,
            settings=settings,
            load_users=_load_users_fn(users_file),
            parse_datetime=_parse_datetime,
        )

    assert exc_info.value.status_code == 401


def test_expired_jwt_raises_401(tmp_path):
    users_file = tmp_path / "users.json"
    user_id = "user-expired"
    users_file.write_text(json.dumps({user_id: {"config": {}}}))

    token = _make_jwt(user_id, expires_in=timedelta(seconds=-1))
    settings = _make_settings(tmp_path)

    with pytest.raises(HTTPException) as exc_info:
        resolve_current_user(
            token,
            settings=settings,
            load_users=_load_users_fn(users_file),
            parse_datetime=_parse_datetime,
        )

    assert exc_info.value.status_code == 401


def test_jwt_signed_with_wrong_secret_raises_401(tmp_path):
    users_file = tmp_path / "users.json"
    user_id = "user-forged"
    users_file.write_text(json.dumps({user_id: {"config": {}}}))

    forged_token = pyjwt.encode(
        {"sub": user_id, "exp": datetime.now(tz=UTC) + timedelta(hours=1)},
        "wrong-secret-key-totally-different",
        algorithm=TEST_ALGORITHM,
    )
    settings = _make_settings(tmp_path)

    with pytest.raises(HTTPException) as exc_info:
        resolve_current_user(
            forged_token,
            settings=settings,
            load_users=_load_users_fn(users_file),
            parse_datetime=_parse_datetime,
        )

    assert exc_info.value.status_code == 401
