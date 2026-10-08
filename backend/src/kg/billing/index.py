"""Subscription index — maps App Store transaction ids back to user ids."""

from __future__ import annotations

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
