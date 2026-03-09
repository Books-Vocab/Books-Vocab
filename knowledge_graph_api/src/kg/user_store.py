from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


def load_users_from(users_file: Path, normalize_users_payload: Callable[[dict[str, Any]], tuple[dict[str, Any], bool]]) -> dict[str, dict[str, Any]]:
    if not users_file.exists():
        return {}
    data = json.loads(users_file.read_text())
    normalized, _ = normalize_users_payload(data)
    return normalized


def save_users_to(
    users_file: Path,
    users: dict[str, dict[str, Any]],
    normalize_users_payload: Callable[[dict[str, Any]], tuple[dict[str, Any], bool]],
) -> None:
    normalized, _ = normalize_users_payload(users)
    tmp_path = users_file.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(normalized, indent=2))
    tmp_path.replace(users_file)


def normalize_users_payload(
    users: dict[str, Any],
    default_subscription_payload: Callable[[], dict[str, Any]],
) -> tuple[dict[str, Any], bool]:
    changed = False
    normalized: dict[str, Any] = {}

    for user_id, record in users.items():
        if not isinstance(record, dict) or user_id.startswith("_"):
            normalized[user_id] = record
            continue

        normalized_record = dict(record)
        had_config = isinstance(normalized_record.get("config"), dict)
        config = dict(normalized_record.get("config", {})) if had_config else {}
        legacy_mochi_key = normalized_record.pop("mochi_api_key", None)
        subscription = normalized_record.get("subscription")
        integrations = config.get("integrations")
        if not isinstance(integrations, dict):
            integrations = {}
        mochi_integration = integrations.get("mochi")
        if not isinstance(mochi_integration, dict):
            mochi_integration = {}

        if "mochi_api_key" in record:
            changed = True
            if isinstance(legacy_mochi_key, str):
                legacy_mochi_key = legacy_mochi_key.strip()
            if legacy_mochi_key and not config.get("mochi_api_key"):
                config["mochi_api_key"] = legacy_mochi_key

        nested_mochi_key = mochi_integration.get("api_key")
        if isinstance(nested_mochi_key, str):
            nested_mochi_key = nested_mochi_key.strip()
            if nested_mochi_key != mochi_integration.get("api_key"):
                changed = True
                mochi_integration["api_key"] = nested_mochi_key
            if nested_mochi_key and not config.get("mochi_api_key"):
                config["mochi_api_key"] = nested_mochi_key
                changed = True

        flat_mochi_key = config.get("mochi_api_key")
        if isinstance(flat_mochi_key, str):
            flat_mochi_key = flat_mochi_key.strip()
            if flat_mochi_key != config.get("mochi_api_key"):
                changed = True
                config["mochi_api_key"] = flat_mochi_key
            if flat_mochi_key and mochi_integration.get("api_key") != flat_mochi_key:
                mochi_integration["api_key"] = flat_mochi_key
                changed = True

        if mochi_integration:
            integrations["mochi"] = mochi_integration
        elif "mochi" in integrations:
            integrations.pop("mochi", None)
            changed = True

        if integrations:
            if config.get("integrations") != integrations:
                changed = True
            config["integrations"] = integrations
        elif "integrations" in config:
            config.pop("integrations", None)
            changed = True

        if had_config or config:
            if normalized_record.get("config") != config:
                changed = True
            normalized_record["config"] = config
        elif "config" in normalized_record:
            normalized_record.pop("config", None)
            changed = True

        if subscription is not None:
            if isinstance(subscription, dict):
                normalized_subscription = default_subscription_payload()
                normalized_subscription.update(subscription)
                if normalized_subscription != subscription:
                    changed = True
                normalized_record["subscription"] = normalized_subscription
            else:
                normalized_record.pop("subscription", None)
                changed = True

        normalized[user_id] = normalized_record

    return normalized, changed


def parse_datetime(raw: Any) -> datetime | None:
    if raw is None:
        return None
    if isinstance(raw, datetime):
        if raw.tzinfo is None:
            return raw.replace(tzinfo=timezone.utc)
        return raw.astimezone(timezone.utc)
    if isinstance(raw, (int, float)):
        return datetime.fromtimestamp(float(raw), tz=timezone.utc)
    if isinstance(raw, str):
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(timezone.utc)
        except ValueError:
            try:
                return datetime.fromtimestamp(float(raw), tz=timezone.utc)
            except ValueError:
                return None
    return None


def resolve_mochi_api_key_from_config(config: dict[str, Any]) -> str | None:
    integrations = config.get("integrations", {})
    if isinstance(integrations, dict):
        mochi = integrations.get("mochi", {})
        if isinstance(mochi, dict):
            nested = mochi.get("api_key")
            if isinstance(nested, str):
                nested = nested.strip()
                if nested:
                    return nested

    legacy = config.get("mochi_api_key")
    if isinstance(legacy, str):
        legacy = legacy.strip()
        if legacy:
            return legacy

    return None


def collect_account_ids_for_deletion(users: dict[str, dict[str, Any]], user_id: str) -> tuple[str, list[str]]:
    """Return canonical id + all related ids that must be purged."""
    record = users.get(user_id, {})
    canonical_id = user_id
    if isinstance(record, dict):
        linked_to = record.get("_linked_to")
        if isinstance(linked_to, str) and linked_to:
            canonical_id = linked_to

    ids: set[str] = {canonical_id, user_id}
    canonical_record = users.get(canonical_id, {})
    if isinstance(canonical_record, dict):
        linked_ids = canonical_record.get("linked_ids", [])
        if isinstance(linked_ids, list):
            ids.update(uid for uid in linked_ids if isinstance(uid, str) and uid)

    for uid, info in users.items():
        if uid.startswith("_"):
            continue
        if isinstance(info, dict) and info.get("_linked_to") == canonical_id:
            ids.add(uid)

    return canonical_id, sorted(ids)
