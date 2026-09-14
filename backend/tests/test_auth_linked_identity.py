from __future__ import annotations

import json

from kg.auth_service import resolve_and_link_user
from kg.user_handlers import get_user_profile_response


def test_linked_provider_relogin_without_email_preserves_canonical_identity(tmp_path):
    users_file = tmp_path / "users.json"
    lock_file = tmp_path / "users.json.lock"
    users_file.write_text("{}")

    def load_users():
        return json.loads(users_file.read_text())

    def save_users(users):
        users_file.write_text(json.dumps(users))

    canonical_id = resolve_and_link_user(
        "google-sub",
        "google",
        users_lock_file=str(lock_file),
        load_users_fn=load_users,
        save_users_fn=save_users,
        email="shared@example.com",
    )
    assert (
        resolve_and_link_user(
            "apple-sub",
            "apple",
            users_lock_file=str(lock_file),
            load_users_fn=load_users,
            save_users_fn=save_users,
            email="shared@example.com",
        )
        == canonical_id
    )

    # Apple omits email on subsequent sign-ins. This must not erase the
    # verified email retained on the canonical account.
    assert (
        resolve_and_link_user(
            "apple-sub",
            "apple",
            users_lock_file=str(lock_file),
            load_users_fn=load_users,
            save_users_fn=save_users,
            email=None,
        )
        == canonical_id
    )

    record = load_users()[canonical_id]
    assert record["email"] == "shared@example.com"
    assert record["provider"] == "apple"
    profile = get_user_profile_response({"id": canonical_id, "record": record, "config": {}})
    assert profile.email == "shared@example.com"
