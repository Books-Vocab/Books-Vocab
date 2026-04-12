from __future__ import annotations

from datetime import UTC, datetime

from kg.user_store import (
    collect_account_ids_for_deletion,
    normalize_users_payload,
    parse_datetime,
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
        assert result.tzinfo == UTC
        assert result.year == 2024
        assert result.month == 1
        assert result.day == 15

    def test_iso_with_offset(self):
        result = parse_datetime("2024-06-01T08:30:00+05:30")
        assert isinstance(result, datetime)
        assert result.tzinfo == UTC

    def test_unix_timestamp_int(self):
        result = parse_datetime(1700000000)
        assert isinstance(result, datetime)
        assert result.tzinfo == UTC
        assert result == datetime.fromtimestamp(1700000000, tz=UTC)

    def test_unix_timestamp_float(self):
        result = parse_datetime(1700000000.5)
        assert isinstance(result, datetime)
        assert result.tzinfo == UTC

    def test_invalid_string_returns_none(self):
        assert parse_datetime("not-a-date") is None

    def test_none_returns_none(self):
        assert parse_datetime(None) is None

    def test_datetime_with_utc_tzinfo(self):
        dt = datetime(2024, 1, 1, tzinfo=UTC)
        result = parse_datetime(dt)
        assert result == dt

    def test_naive_datetime_gets_utc(self):
        dt = datetime(2024, 1, 1)
        result = parse_datetime(dt)
        assert result.tzinfo == UTC


# ===========================================================================
# normalize_users_payload
# ===========================================================================

class TestNormalizeUsersPayload:

    def _normalize(self, users):
        return normalize_users_payload(users, _default_subscription)

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
                "config": {},
            }
        }
        result, changed = self._normalize(users)
        assert not changed

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


