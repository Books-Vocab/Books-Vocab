"""External API key lifecycle.

Keys are bearer credentials for the versioned external API. Only a SHA-256
digest is stored in ``users.json``; the plaintext value is returned once at
creation time. Keeping the index in the existing user registry means account
erasure can remove credentials atomically with the user record.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from filelock import FileLock

from .types import UsersPayload

EXTERNAL_API_KEY_INDEX = "_external_api_keys"
EXTERNAL_API_KEY_PREFIX = "kg_"
MAX_ACTIVE_KEYS_PER_USER = 10

UsersLoader = Callable[[], UsersPayload]
UsersSaver = Callable[[UsersPayload], None]


def _now_iso() -> str:
    return datetime.now(tz=UTC).isoformat()


def _digest(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def _parse_key(value: str | None) -> tuple[str, str] | None:
    if not isinstance(value, str) or not value.startswith(EXTERNAL_API_KEY_PREFIX):
        return None
    body = value[len(EXTERNAL_API_KEY_PREFIX):]
    key_id, separator, secret = body.partition(".")
    if not separator or not key_id or not secret:
        return None
    if len(key_id) != 32 or any(char not in "0123456789abcdef" for char in key_id):
        return None
    return key_id, secret


def _index(users: UsersPayload, *, create: bool = False) -> dict[str, dict[str, Any]]:
    raw = users.get(EXTERNAL_API_KEY_INDEX)
    if isinstance(raw, dict):
        return raw
    if create:
        created: dict[str, dict[str, Any]] = {}
        users[EXTERNAL_API_KEY_INDEX] = created
        return created
    return {}


def _public_record(key_id: str, record: dict[str, Any]) -> dict[str, Any]:
    return {
        "keyId": key_id,
        "label": record.get("label") or "external client",
        "createdAt": record.get("created_at"),
        "revokedAt": record.get("revoked_at"),
    }


def issue_api_key(
    user_id: str,
    *,
    label: str,
    users_lock_file: Path,
    load_users: UsersLoader,
    save_users: UsersSaver,
) -> dict[str, Any]:
    """Create a key and return its plaintext exactly once."""

    now = _now_iso()
    with FileLock(str(users_lock_file)):
        users = load_users()
        user_record = users.get(user_id)
        if not isinstance(user_record, dict):
            raise KeyError(user_id)

        key_index = _index(users, create=True)
        active_count = sum(
            1
            for record in key_index.values()
            if isinstance(record, dict)
            and record.get("user_id") == user_id
            and not record.get("revoked_at")
        )
        if active_count >= MAX_ACTIVE_KEYS_PER_USER:
            raise ValueError("Maximum active external API keys reached")

        key_id = secrets.token_hex(16)
        secret = secrets.token_urlsafe(32)
        key_index[key_id] = {
            "user_id": user_id,
            "label": label,
            "created_at": now,
            "revoked_at": None,
            "secret_hash": _digest(secret),
        }
        save_users(users)

    return {
        "keyId": key_id,
        "label": label,
        "createdAt": now,
        "revokedAt": None,
        "apiKey": f"{EXTERNAL_API_KEY_PREFIX}{key_id}.{secret}",
    }


def list_api_keys(
    user_id: str,
    *,
    load_users: UsersLoader,
) -> list[dict[str, Any]]:
    users = load_users()
    key_index = _index(users)
    records = [
        _public_record(key_id, record)
        for key_id, record in key_index.items()
        if isinstance(record, dict) and record.get("user_id") == user_id
    ]
    records.sort(key=lambda record: record.get("createdAt") or "", reverse=True)
    return records


def revoke_api_key(
    user_id: str,
    key_id: str,
    *,
    users_lock_file: Path,
    load_users: UsersLoader,
    save_users: UsersSaver,
) -> dict[str, Any] | None:
    now = _now_iso()
    with FileLock(str(users_lock_file)):
        users = load_users()
        key_index = _index(users)
        record = key_index.get(key_id)
        if not isinstance(record, dict) or record.get("user_id") != user_id:
            return None
        if not record.get("revoked_at"):
            record["revoked_at"] = now
            save_users(users)
        return _public_record(key_id, record)


def authenticate_api_key(
    value: str | None,
    *,
    load_users: UsersLoader,
) -> tuple[str, str, dict[str, Any]] | None:
    """Resolve a key to ``(key_id, user_id, stored user record)``.

    The lookup is intentionally fail-closed: malformed values, missing index
    entries, revoked keys, deleted users, and digest mismatches all return the
    same ``None`` result to avoid credential-state disclosure.
    """

    parsed = _parse_key(value)
    if parsed is None:
        return None
    key_id, secret = parsed
    users = load_users()
    record = _index(users).get(key_id)
    if not isinstance(record, dict) or record.get("revoked_at"):
        return None
    expected = record.get("secret_hash")
    if not isinstance(expected, str) or not hmac.compare_digest(expected, _digest(secret)):
        return None
    user_id = record.get("user_id")
    user = users.get(user_id) if isinstance(user_id, str) else None
    if not isinstance(user_id, str) or not isinstance(user, dict) or user_id.startswith("_"):
        return None
    return key_id, user_id, user


def purge_external_api_keys(users: UsersPayload, user_ids: Iterable[str]) -> None:
    """Remove credentials for an account and any linked provider identities."""

    key_index = _index(users)
    ids = set(user_ids)
    for key_id, record in list(key_index.items()):
        if isinstance(record, dict) and record.get("user_id") in ids:
            key_index.pop(key_id, None)
    if not key_index and EXTERNAL_API_KEY_INDEX in users:
        users.pop(EXTERNAL_API_KEY_INDEX, None)


__all__ = [
    "EXTERNAL_API_KEY_INDEX",
    "EXTERNAL_API_KEY_PREFIX",
    "MAX_ACTIVE_KEYS_PER_USER",
    "authenticate_api_key",
    "issue_api_key",
    "list_api_keys",
    "purge_external_api_keys",
    "revoke_api_key",
]
