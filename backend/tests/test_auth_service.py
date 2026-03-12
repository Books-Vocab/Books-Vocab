from __future__ import annotations

import json

import jwt as pyjwt

from kg.auth_service import create_jwt_token, resolve_and_link_user

TEST_JWT_SECRET = "test-secret-key-for-ci-at-least-32-bytes"


def test_create_jwt_token_produces_decodable_payload():
    token = create_jwt_token(
        "user-123",
        "google",
        jwt_secret=TEST_JWT_SECRET,
        jwt_algorithm="HS256",
        jwt_expiry_minutes=15,
    )
    payload = pyjwt.decode(token, TEST_JWT_SECRET, algorithms=["HS256"])
    assert payload["sub"] == "user-123"
    assert payload["provider"] == "google"


def test_resolve_and_link_user_merges_by_email(tmp_path):
    users_file = tmp_path / "users.json"
    lock_file = tmp_path / "users.json.lock"
    users_file.write_text(json.dumps({}))

    def load_users():
        return json.loads(users_file.read_text())

    def save_users(users):
        users_file.write_text(json.dumps(users))

    canonical = resolve_and_link_user(
        "google-sub",
        "google",
        users_lock_file=str(lock_file),
        load_users_fn=load_users,
        save_users_fn=save_users,
        email="same@example.com",
    )
    assert canonical == "google-sub"

    linked = resolve_and_link_user(
        "apple-sub",
        "apple",
        users_lock_file=str(lock_file),
        load_users_fn=load_users,
        save_users_fn=save_users,
        email="same@example.com",
    )
    assert linked == "google-sub"

    stored = json.loads(users_file.read_text())
    assert stored["_email_index"]["same@example.com"] == "google-sub"
    assert stored["google-sub"]["linked_ids"] == ["apple-sub"]
    assert stored["apple-sub"]["_linked_to"] == "google-sub"
