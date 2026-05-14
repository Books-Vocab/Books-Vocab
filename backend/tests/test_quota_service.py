"""Tests for quota_service — token cost calculation, quota state, and limits."""

from __future__ import annotations

import sqlite3
import threading
from unittest.mock import patch

import pytest

from kg.quota_service import (
    EMBED_PER_M,
    INPUT_PER_M,
    OUTPUT_PER_M,
    check_and_get_quota,
    check_quota,
    configure_limits,
    get_quota_state,
    token_cost_usd,
)


# ── token_cost_usd ────────────────────────────────────────────────


class TestTokenCostUsd:
    def test_embed_cost(self):
        cost = token_cost_usd("embed", 1_000_000, 0)
        assert cost == pytest.approx(EMBED_PER_M)

    def test_embed_ignores_output_tokens(self):
        cost = token_cost_usd("embed", 1_000_000, 999_999)
        assert cost == pytest.approx(EMBED_PER_M)

    def test_llm_cost_input_only(self):
        cost = token_cost_usd("translate", 1_000_000, 0)
        assert cost == pytest.approx(INPUT_PER_M)

    def test_llm_cost_output_only(self):
        cost = token_cost_usd("translate", 0, 1_000_000)
        assert cost == pytest.approx(OUTPUT_PER_M)

    def test_llm_cost_mixed(self):
        cost = token_cost_usd("judge", 500_000, 500_000)
        expected = (500_000 / 1_000_000) * INPUT_PER_M + (500_000 / 1_000_000) * OUTPUT_PER_M
        assert cost == pytest.approx(expected)

    def test_zero_tokens(self):
        assert token_cost_usd("translate", 0, 0) == 0.0
        assert token_cost_usd("embed", 0, 0) == 0.0

    def test_small_token_count(self):
        cost = token_cost_usd("translate", 100, 50)
        assert cost > 0
        assert cost < 0.001


# ── configure_limits ───────────────────────────────────────────────


class TestConfigureLimits:
    def test_configure_changes_limits(self):
        configure_limits(pro=1.0, free=0.1)
        from kg.quota_service import PRO_DAILY_LIMIT_USD, FREE_DAILY_LIMIT_USD
        assert PRO_DAILY_LIMIT_USD == 1.0
        assert FREE_DAILY_LIMIT_USD == 0.1
        # Restore defaults
        configure_limits(pro=0.30, free=0.03)


# ── get_quota_state / check_quota (with mocked DB) ────────────────


@pytest.fixture
def mock_db():
    """Provide an in-memory SQLite DB and patch token_tracker to use it."""
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.execute("""
        CREATE TABLE token_usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            call_type TEXT NOT NULL,
            input_tokens INTEGER NOT NULL DEFAULT 0,
            output_tokens INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        )
    """)
    conn.commit()
    lock = threading.Lock()
    with patch("kg.quota_service._get_conn", return_value=conn), \
         patch("kg.quota_service._lock", lock):
        yield conn
    conn.close()


def _insert_usage(conn, user_id, call_type, input_tokens, output_tokens, created_at):
    conn.execute(
        "INSERT INTO token_usage (user_id, call_type, input_tokens, output_tokens, created_at) VALUES (?,?,?,?,?)",
        (user_id, call_type, input_tokens, output_tokens, created_at),
    )
    conn.commit()


class TestGetQuotaState:
    def test_no_usage_returns_full_quota(self, mock_db):
        state = get_quota_state("user1", is_pro=False)
        assert state["fraction"] == 1.0
        assert state["reset_seconds"] == 86400

    def test_some_usage_reduces_fraction(self, mock_db):
        from datetime import UTC, datetime
        now = datetime.now(UTC).isoformat()
        # Use half the free limit ($0.03 / 2 = $0.015)
        # $0.015 = 150,000 input tokens at $0.10/M
        _insert_usage(mock_db, "user1", "translate", 150_000, 0, now)
        state = get_quota_state("user1", is_pro=False)
        assert 0.0 < state["fraction"] < 1.0

    def test_pro_vs_free_limit(self, mock_db):
        from datetime import UTC, datetime
        now = datetime.now(UTC).isoformat()
        _insert_usage(mock_db, "user1", "translate", 150_000, 0, now)
        free_state = get_quota_state("user1", is_pro=False)
        pro_state = get_quota_state("user1", is_pro=True)
        # Pro has higher limit, so fraction remaining should be higher
        assert pro_state["fraction"] > free_state["fraction"]


class TestCheckQuota:
    def test_not_exceeded_when_empty(self, mock_db):
        result = check_quota("user1", "translate", is_pro=False)
        assert result["exceeded"] is False
        assert result["fraction"] == 1.0

    def test_exceeded_when_over_limit(self, mock_db):
        from datetime import UTC, datetime
        now = datetime.now(UTC).isoformat()
        # Free limit = $0.03 → need 300,000 input tokens at $0.10/M
        _insert_usage(mock_db, "user1", "translate", 300_000, 0, now)
        result = check_quota("user1", "translate", is_pro=False)
        assert result["exceeded"] is True
        assert result["fraction"] == 0.0


class TestCheckAndGetQuota:
    def test_matches_check_quota(self, mock_db):
        r1 = check_quota("user1", "translate", is_pro=False)
        r2 = check_and_get_quota("user1", "translate", is_pro=False)
        assert r1["exceeded"] == r2["exceeded"]
        assert r1["fraction"] == r2["fraction"]


# ── tier transitions & grant revoke (characterization) ────────────
#
# Context: quota_service is a stateless 24h rolling-window view over
# token_usage. It has no "tier change" event, no period reset, and no
# grant/revoke concept of its own — those live in billing/admin layers
# and only surface here as a different `is_pro` flag (or, for synthetic
# grants, a different configured limit via `configure_limits`).
#
# The tests below pin down *what actually happens* across those
# transitions so any future regression (e.g. someone adding a period
# reset hook without documenting it) is caught immediately.


class TestTierTransitions:
    def test_quota_free_to_pro_upgrade_resets_period_window(self, mock_db):
        """Free user at 80% usage → upgrade to pro.

        Behaviour: token_usage rows are NOT reset. The same accumulated
        cost is re-divided by the pro limit, so the fraction *appears*
        to jump back up (effective carry-over with higher ceiling).
        No explicit period-window reset happens at the quota_service
        layer — the rolling 24h window is unaffected by tier change.
        """
        from datetime import UTC, datetime
        now = datetime.now(UTC).isoformat()

        # 80% of free limit ($0.03 * 0.8 = $0.024) → 240,000 input tokens
        _insert_usage(mock_db, "user1", "translate", 240_000, 0, now)

        free_state = get_quota_state("user1", is_pro=False)
        assert free_state["fraction"] == pytest.approx(0.20, abs=0.01), (
            "free user should have ~20% remaining"
        )

        # Tier transition: same usage, evaluate as pro
        pro_state = get_quota_state("user1", is_pro=True)
        # $0.024 used / $0.30 pro limit = ~92% remaining
        assert pro_state["fraction"] == pytest.approx(0.92, abs=0.01), (
            "upgrade should NOT reset usage — same $0.024 against pro $0.30"
        )
        # Reset window unchanged across tier flip
        assert pro_state["reset_seconds"] == free_state["reset_seconds"] == 86400

    def test_quota_pro_to_free_downgrade_respects_remaining_period(self, mock_db):
        """Pro user at 50% pro usage → subscription expires → free tier.

        Behaviour: 50% of pro ($0.15) already exceeds free limit ($0.03)
        by 5x. quota_service does NOT carve out a fresh free-tier window
        — the accumulated cost is preserved, so the user lands in
        exceeded state immediately on downgrade. Reset window keeps
        ticking on the original 24h schedule.
        """
        from datetime import UTC, datetime
        now = datetime.now(UTC).isoformat()

        # 50% of pro limit ($0.30 * 0.5 = $0.15) → 1,500,000 input tokens
        _insert_usage(mock_db, "user1", "translate", 1_500_000, 0, now)

        pro_state = get_quota_state("user1", is_pro=True)
        assert pro_state["fraction"] == pytest.approx(0.50, abs=0.01)
        pro_check = check_quota("user1", "translate", is_pro=True)
        assert pro_check["exceeded"] is False

        # Downgrade: same period, evaluate as free
        free_state = get_quota_state("user1", is_pro=False)
        free_check = check_quota("user1", "translate", is_pro=False)
        # Cost ($0.15) >> free limit ($0.03) → exceeded, fraction floored to 0
        assert free_check["exceeded"] is True
        assert free_state["fraction"] == 0.0, (
            "downgrade does NOT reset the rolling window — past pro usage "
            "still counts against the smaller free ceiling"
        )
        # Reset window still 24h — no shortened period on downgrade
        assert free_state["reset_seconds"] == 86400


class TestGrantRevoke:
    def test_quota_grant_revoked_returns_to_baseline(self, mock_db):
        """Admin grants extra quota (modelled as raised limit) → revoke.

        Behaviour: quota_service has no first-class grant API; the
        admin layer (billing.py) toggles `is_pro` or, for bespoke
        grants, calls `configure_limits`. After revoke (limits
        restored), the same usage is re-evaluated against the
        baseline limit — *not* zeroed, *not* preserved as a credit.
        Token usage is the only state; limits are pure config.
        """
        from datetime import UTC, datetime
        from kg.quota_service import FREE_DAILY_LIMIT_USD, PRO_DAILY_LIMIT_USD

        baseline_pro = PRO_DAILY_LIMIT_USD
        baseline_free = FREE_DAILY_LIMIT_USD

        now = datetime.now(UTC).isoformat()
        # User burns $0.20 — fine under default pro $0.30 (~33% remaining)
        _insert_usage(mock_db, "user1", "translate", 2_000_000, 0, now)

        before_grant = get_quota_state("user1", is_pro=True)
        assert before_grant["fraction"] == pytest.approx(0.33, abs=0.01)

        # Admin grants a larger ceiling (e.g. promo): raise pro limit
        try:
            configure_limits(pro=1.0, free=baseline_free)
            during_grant = get_quota_state("user1", is_pro=True)
            # Same $0.20 against $1.00 → 80% remaining
            assert during_grant["fraction"] == pytest.approx(0.80, abs=0.01)
            grant_check = check_quota("user1", "translate", is_pro=True)
            assert grant_check["exceeded"] is False

            # Revoke: restore baseline limits
            configure_limits(pro=baseline_pro, free=baseline_free)
            after_revoke = get_quota_state("user1", is_pro=True)
            # Back to original ~33% — usage preserved, limit reset
            assert after_revoke["fraction"] == pytest.approx(0.33, abs=0.01)
            assert after_revoke["fraction"] == pytest.approx(
                before_grant["fraction"], abs=0.001
            ), "revoke should land exactly back at pre-grant fraction"

            # And current usage is still consistent against the baseline
            revoke_check = check_quota("user1", "translate", is_pro=True)
            assert revoke_check["exceeded"] is False
            assert revoke_check["fraction"] == after_revoke["fraction"]
        finally:
            # Always restore (defensive even though we already restored above)
            configure_limits(pro=baseline_pro, free=baseline_free)
