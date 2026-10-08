"""Subscription index — maps App Store transaction ids back to user ids."""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Mapping
from typing import Any

from fastapi import HTTPException

from ..types import UsersPayload
from ..user_store import is_real_user


def upsert_subscription_index(
    users: UsersPayload,
    user_id: str,
    original_transaction_id: str | None,
    transaction_id: str | None,
) -> None:
    index = users.get("_subscription_index")
    if not isinstance(index, dict):
        index = {}
        users["_subscription_index"] = index

    if isinstance(original_transaction_id, str) and original_transaction_id.strip():
        index[original_transaction_id.strip()] = user_id
    if isinstance(transaction_id, str) and transaction_id.strip():
        index[transaction_id.strip()] = user_id


def resolve_user_id_from_subscription_index(
    users: UsersPayload,
    original_transaction_id: str | None,
    transaction_id: str | None,
) -> str | None:
    """Return the live owner of a transaction, or ``None``. Read-only.

    The index can outlive its owner: account deletion predating #2255 left
    entries pointing at erased ids. A candidate only resolves while it still
    has a user record, so callers never re-create an erased account by writing
    a snapshot through a stale mapping; otherwise the next candidate is tried.
    ``_terminated`` is deliberately not consulted: it only makes the revocation
    watermark permanent, and the same provider id may sign in again and own a
    fresh record whose notifications must keep applying.
    """
    index = users.get("_subscription_index")
    if not isinstance(index, dict):
        return None
    for candidate in (original_transaction_id, transaction_id):
        if isinstance(candidate, str) and candidate.strip():
            resolved = index.get(candidate.strip())
            if isinstance(resolved, str) and resolved and is_real_user(resolved, users.get(resolved)):
                return resolved
    return None


def account_token_for_user(user_id: str) -> str:
    """The appAccountToken the iOS client attaches to purchases for ``user_id``."""
    return str(uuid.UUID(bytes=hashlib.sha256(user_id.encode()).digest()[:16]))


def _token_matches(token: str, user_id: str) -> bool:
    try:
        return uuid.UUID(token) == uuid.UUID(account_token_for_user(user_id))
    except (ValueError, AttributeError):
        return False


def resolve_claim_owner(
    users: UsersPayload,
    caller_id: str,
    snapshot: Mapping[str, Any],
    resolve=resolve_user_id_from_subscription_index,
) -> str:
    """Return the user a signed transaction may be written to, or raise.

    A JWS is bearer data: anyone holding it could otherwise re-point the index.
    The signed ``appAccountToken`` (derived from the user id) binds it to a user.
    A mismatching token is 403; a live different index owner without a token
    proving the caller is 409. Error details never carry entitlement data.
    """
    token = snapshot.get("app_account_token")
    if token is not None and not _token_matches(str(token), caller_id):
        raise HTTPException(status_code=403, detail="Transaction belongs to a different account")
    if token is not None:
        return caller_id
    owner = resolve(users, snapshot.get("original_transaction_id"), snapshot.get("transaction_id"))
    if owner is not None and owner != caller_id:
        raise HTTPException(status_code=409, detail="Transaction is already linked to a different account")
    return caller_id
