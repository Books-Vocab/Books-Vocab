"""Subscription index — maps App Store transaction ids back to user ids."""

from __future__ import annotations

from typing import Any


def upsert_subscription_index(
    users: dict[str, Any],
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
    users: dict[str, Any],
    original_transaction_id: str | None,
    transaction_id: str | None,
) -> str | None:
    index = users.get("_subscription_index")
    if not isinstance(index, dict):
        return None
    for candidate in (original_transaction_id, transaction_id):
        if isinstance(candidate, str) and candidate.strip():
            resolved = index.get(candidate.strip())
            if isinstance(resolved, str) and resolved:
                return resolved
    return None
