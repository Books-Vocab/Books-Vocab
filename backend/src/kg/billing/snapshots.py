"""Persisting App Store subscription snapshots and raw event logs."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .index import upsert_subscription_index
from .payloads import default_subscription_payload


def append_app_store_event(notifications_file: Path, payload: dict[str, Any]) -> None:
    notifications_file.parent.mkdir(parents=True, exist_ok=True)
    with notifications_file.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False) + "\n")


def write_subscription_snapshot(
    users: dict[str, Any],
    user_id: str,
    *,
    product_id: str,
    status: str,
    is_trial: bool,
    expires_at: str | None,
    will_renew: bool,
    environment: str,
    transaction_id: str | None,
    original_transaction_id: str | None,
    price_display: str | None,
    source: str,
) -> dict[str, Any]:
    now_iso = datetime.now(tz=UTC).isoformat()
    record = users.setdefault(user_id, {})
    subscription = default_subscription_payload()
    existing = record.get("subscription")
    if isinstance(existing, dict):
        subscription.update(existing)

    normalized_status = status.strip() or "active"
    subscription.update(
        {
            "is_active": normalized_status in {"active", "trial", "grace_period"},
            "product_id": product_id.strip(),
            "plan_name": "Books & Vocab Pro",
            "price_display": price_display.strip() if isinstance(price_display, str) and price_display.strip() else subscription.get("price_display"),
            "status": normalized_status,
            "is_trial": is_trial,
            "trial_days": subscription.get("trial_days") or 7,
            "will_renew": will_renew,
            "expires_at": expires_at,
            "source": source,
            "last_synced_at": now_iso,
            "transaction_id": transaction_id,
            "original_transaction_id": original_transaction_id,
            "environment": environment,
        }
    )
    record["subscription"] = subscription
    upsert_subscription_index(users, user_id, original_transaction_id, transaction_id)
    return record
