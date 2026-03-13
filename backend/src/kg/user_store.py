from __future__ import annotations

import copy
import json
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class CachedUserStore:
    def __init__(
        self,
        users_file: Path,
        normalize_fn: Callable[[dict[str, Any]], tuple[dict[str, Any], bool]],
        ttl: float = 2.0,
    ) -> None:
        self._users_file = users_file
        self._normalize_fn = normalize_fn
        self._ttl = ttl
        self._cache: dict[str, Any] | None = None
        self._cache_time: float = 0.0
        self._lock = threading.Lock()

    def load(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            now = time.monotonic()
            if self._cache is not None and (now - self._cache_time) < self._ttl:
                return copy.deepcopy(self._cache)
            data = load_users_from(self._users_file, self._normalize_fn)
            self._cache = data
            self._cache_time = now
            return copy.deepcopy(data)

    def save(self, users: dict[str, dict[str, Any]]) -> None:
        save_users_to(self._users_file, users, self._normalize_fn)
        normalized, _ = self._normalize_fn(users)
        with self._lock:
            self._cache = normalized
            self._cache_time = time.monotonic()

    def invalidate(self) -> None:
        with self._lock:
            self._cache = None
            self._cache_time = 0.0


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
    encrypt_fn: Callable[[str], str] | None = None,
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
        flat_mochi_key = config.pop("mochi_api_key", None)
        subscription = normalized_record.get("subscription")
        integrations = config.get("integrations")
        if not isinstance(integrations, dict):
            integrations = {}
        mochi_integration = integrations.get("mochi")
        if not isinstance(mochi_integration, dict):
            mochi_integration = {}

        if "mochi_api_key" in record:
            changed = True
        if "mochi_api_key" in config:
            changed = True

        if isinstance(legacy_mochi_key, str):
            legacy_mochi_key = legacy_mochi_key.strip()
        else:
            legacy_mochi_key = None

        if isinstance(flat_mochi_key, str):
            flat_mochi_key = flat_mochi_key.strip()
        else:
            flat_mochi_key = None

        nested_mochi_key = mochi_integration.get("api_key")
        if isinstance(nested_mochi_key, str):
            nested_mochi_key = nested_mochi_key.strip()
            if nested_mochi_key != mochi_integration.get("api_key"):
                changed = True
            if nested_mochi_key:
                mochi_integration["api_key"] = nested_mochi_key
            elif "api_key" in mochi_integration:
                mochi_integration.pop("api_key", None)
                changed = True
        else:
            nested_mochi_key = None

        resolved_mochi_key = nested_mochi_key or flat_mochi_key or legacy_mochi_key
        if resolved_mochi_key:
            from .secret_store import is_encrypted
            if encrypt_fn and not is_encrypted(resolved_mochi_key):
                resolved_mochi_key = encrypt_fn(resolved_mochi_key)
            if mochi_integration.get("api_key") != resolved_mochi_key:
                changed = True
            mochi_integration["api_key"] = resolved_mochi_key

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
            return raw.replace(tzinfo=UTC)
        return raw.astimezone(UTC)
    if isinstance(raw, (int, float)):
        return datetime.fromtimestamp(float(raw), tz=UTC)
    if isinstance(raw, str):
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(UTC)
        except ValueError:
            try:
                return datetime.fromtimestamp(float(raw), tz=UTC)
            except ValueError:
                return None
    return None


def resolve_mochi_api_key_from_config(config: dict[str, Any], jwt_secret: str = "") -> str | None:
    integrations = config.get("integrations", {})
    if isinstance(integrations, dict):
        mochi = integrations.get("mochi", {})
        if isinstance(mochi, dict):
            nested = mochi.get("api_key")
            if isinstance(nested, str):
                nested = nested.strip()
                if nested:
                    from .secret_store import decrypt_value
                    return decrypt_value(nested, jwt_secret) if jwt_secret else nested

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
