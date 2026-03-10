from __future__ import annotations

from datetime import datetime, timezone

import pytest

from kg.user_store import (
    collect_account_ids_for_deletion,
    normalize_users_payload,
    parse_datetime,
    resolve_mochi_api_key_from_config,
)


def _default_subscription():
    return {
        "is_active": False,
        "status": "inactive",
        "plan_name": None,
        "trial_days": 7,
        "will_renew": False,
    }


# ===========================================================================
# parse_datetime
# ===========================================================================

class TestParseDatetime:

    def test_iso_with_z_suffix(self):
        result = parse_datetime("2024-01-15T12:00:00Z")
        assert isinstance(result, datetime)
        assert result.tzinfo == timezone.utc
        assert result.year == 2024
        assert result.month == 1
        assert result.day == 15

    def test_iso_with_offset(self):
        result = parse_datetime("2024-06-01T08:30:00+05:30")
        assert isinstance(result, datetime)
        assert result.tzinfo == timezone.utc

    def test_unix_timestamp_int(self):
        result = parse_datetime(1700000000)
        assert isinstance(result, datetime)
        assert result.tzinfo == timezone.utc
        assert result == datetime.fromtimestamp(1700000000, tz=timezone.utc)

    def test_unix_timestamp_float(self):
        result = parse_datetime(1700000000.5)
        assert isinstance(result, datetime)
        assert result.tzinfo == timezone.utc

    def test_invalid_string_returns_none(self):
        assert parse_datetime("not-a-date") is None

    def test_none_returns_none(self):
        assert parse_datetime(None) is None

    def test_datetime_with_utc_tzinfo(self):
        dt = datetime(2024, 1, 1, tzinfo=timezone.utc)
        result = parse_datetime(dt)
        assert result == dt

    def test_naive_datetime_gets_utc(self):
        dt = datetime(2024, 1, 1)
        result = parse_datetime(dt)
        assert result.tzinfo == timezone.utc


# ===========================================================================
# normalize_users_payload
# ===========================================================================

class TestNormalizeUsersPayload:

    def _normalize(self, users):
        return normalize_users_payload(users, _default_subscription)

    def test_legacy_mochi_key_migrated_to_nested(self):
        users = {
            "u1": {"mochi_api_key": "legacy_key", "config": {}},
        }
        result, changed = self._normalize(users)
        assert changed
        assert "mochi_api_key" not in result["u1"]
        assert result["u1"]["config"]["integrations"]["mochi"]["api_key"] == "legacy_key"

    def test_flat_config_mochi_key_migrated_to_nested(self):
        users = {
            "u1": {"config": {"mochi_api_key": "flat_key"}},
        }
        result, changed = self._normalize(users)
        assert changed
        assert "mochi_api_key" not in result["u1"]["config"]
        assert result["u1"]["config"]["integrations"]["mochi"]["api_key"] == "flat_key"

    def test_nested_key_takes_priority_over_flat(self):
        users = {
            "u1": {
                "mochi_api_key": "legacy",
                "config": {
                    "mochi_api_key": "flat",
                    "integrations": {"mochi": {"api_key": "nested"}},
                },
            }
        }
        result, _ = self._normalize(users)
        assert result["u1"]["config"]["integrations"]["mochi"]["api_key"] == "nested"

    def test_subscription_defaults_filled(self):
        users = {
            "u1": {"config": {}, "subscription": {"is_active": True, "status": "active"}},
        }
        result, changed = self._normalize(users)
        sub = result["u1"]["subscription"]
        assert "trial_days" in sub
        assert "will_renew" in sub

    def test_empty_integrations_cleaned_up(self):
        users = {
            "u1": {"config": {"integrations": {}}},
        }
        result, _ = self._normalize(users)
        assert "integrations" not in result["u1"].get("config", {})

    def test_already_normal_payload_returns_changed_false(self):
        users = {
            "u1": {
                "config": {
                    "integrations": {"mochi": {"api_key": "mk_abc"}},
                },
            }
        }
        result, changed = self._normalize(users)
        assert not changed
        assert result["u1"]["config"]["integrations"]["mochi"]["api_key"] == "mk_abc"

    def test_underscore_prefixed_keys_pass_through(self):
        users = {
            "_revoked_before": {"u1": "2024-01-01"},
            "u1": {"config": {}},
        }
        result, _ = self._normalize(users)
        assert result["_revoked_before"] == {"u1": "2024-01-01"}


# ===========================================================================
# collect_account_ids_for_deletion
# ===========================================================================

class TestCollectAccountIdsForDeletion:

    def test_no_linked_accounts_returns_only_self(self):
        users = {"u1": {"config": {}}}
        canonical, ids = collect_account_ids_for_deletion(users, "u1")
        assert canonical == "u1"
        assert ids == ["u1"]

    def test_linked_to_points_to_canonical(self):
        users = {
            "canonical": {"linked_ids": ["linked1"], "config": {}},
            "linked1": {"_linked_to": "canonical"},
        }
        canonical, ids = collect_account_ids_for_deletion(users, "linked1")
        assert canonical == "canonical"
        assert "canonical" in ids
        assert "linked1" in ids

    def test_canonical_has_linked_ids_array(self):
        users = {
            "canonical": {"linked_ids": ["linked1", "linked2"], "config": {}},
            "linked1": {"_linked_to": "canonical"},
            "linked2": {"_linked_to": "canonical"},
        }
        canonical, ids = collect_account_ids_for_deletion(users, "canonical")
        assert canonical == "canonical"
        assert set(ids) == {"canonical", "linked1", "linked2"}

    def test_linked_to_nonexistent_canonical_safe(self):
        users = {
            "u1": {"_linked_to": "ghost_canonical"},
        }
        canonical, ids = collect_account_ids_for_deletion(users, "u1")
        assert canonical == "ghost_canonical"
        assert "u1" in ids
        assert "ghost_canonical" in ids


# ===========================================================================
# resolve_mochi_api_key_from_config
# ===========================================================================

class TestResolveMochiApiKeyFromConfig:

    def test_nested_path_returns_key(self):
        config = {"integrations": {"mochi": {"api_key": "mk_valid"}}}
        assert resolve_mochi_api_key_from_config(config) == "mk_valid"

    def test_missing_integrations_returns_none(self):
        assert resolve_mochi_api_key_from_config({}) is None

    def test_missing_mochi_returns_none(self):
        assert resolve_mochi_api_key_from_config({"integrations": {}}) is None

    def test_whitespace_only_returns_none(self):
        config = {"integrations": {"mochi": {"api_key": "   "}}}
        assert resolve_mochi_api_key_from_config(config) is None

    def test_missing_api_key_returns_none(self):
        config = {"integrations": {"mochi": {}}}
        assert resolve_mochi_api_key_from_config(config) is None
