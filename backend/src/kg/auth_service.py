from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import jwt
from filelock import FileLock

from .types import UsersPayload


def create_jwt_token(
    user_id: str,
    provider: str,
    *,
    jwt_secret: str,
    jwt_algorithm: str,
    jwt_expiry_minutes: int,
) -> str:
    now = datetime.now(tz=UTC)
    expires = now + timedelta(minutes=jwt_expiry_minutes)

    payload = {
        "sub": user_id,
        "provider": provider,
        "iat": now,
        "exp": expires,
        # Standard `iat` is encoded as an integer Unix timestamp (floored to
        # whole seconds), so it cannot tell apart a token issued just before
        # vs. just after an account deletion that landed in the same second.
        # `iat_us` carries the microsecond-precise issuance instant; the
        # revocation-watermark check (user_context.resolve_current_user)
        # prefers it so a fresh post-deletion login JWT is not falsely
        # rejected by a same-second deletion watermark.
        "iat_us": now.isoformat(),
    }
    return jwt.encode(payload, jwt_secret, algorithm=jwt_algorithm)


def resolve_and_link_user(
    provider_user_id: str,
    provider: str,
    *,
    users_lock_file: str,
    load_users_fn: Callable[[], UsersPayload],
    save_users_fn: Callable[[UsersPayload], None],
    email: str | None = None,
) -> str:
    with FileLock(users_lock_file):
        users = load_users_fn()

        if "_email_index" not in users:
            users["_email_index"] = {}

        canonical_id = None
        now = datetime.now(tz=UTC).isoformat()

        if email and email in users["_email_index"]:
            canonical_id = users["_email_index"][email]

            if canonical_id != provider_user_id:
                if "linked_ids" not in users[canonical_id]:
                    users[canonical_id]["linked_ids"] = []

                if provider_user_id not in users[canonical_id]["linked_ids"]:
                    users[canonical_id]["linked_ids"].append(provider_user_id)

                if provider_user_id not in users:
                    users[provider_user_id] = {}
                users[provider_user_id]["_linked_to"] = canonical_id
        else:
            canonical_id = provider_user_id
            if canonical_id not in users:
                users[canonical_id] = {}
            if email:
                users["_email_index"][email] = canonical_id

        if canonical_id not in users:
            users[canonical_id] = {}

        users[canonical_id].update({
            "provider": provider,
            "email": email,
            "last_login": now,
        })

        # Clear stale revocation watermarks on a fresh login so the dict does
        # not grow unbounded. But account-deletion watermarks are PERMANENT:
        # ids recorded in `_terminated` must never be popped, otherwise a JWT
        # issued before the deletion would be revived by simply logging in
        # again (same sub, or same email via a different provider).
        revoked_before = users.get("_revoked_before")
        if isinstance(revoked_before, dict):
            terminated = users.get("_terminated")
            terminated_ids = set(terminated) if isinstance(terminated, list) else set()
            for uid in (canonical_id, provider_user_id):
                if uid not in terminated_ids:
                    revoked_before.pop(uid, None)
            if not revoked_before:
                users.pop("_revoked_before", None)

        save_users_fn(users)
        return canonical_id
