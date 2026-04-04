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
