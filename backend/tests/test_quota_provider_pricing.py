"""Phase 2: cost is priced from each row's OWN provider, not from
whatever provider is currently routed for its call_type.

Without this, a Gemini→DeepSeek switch reprices ~24h of rolling-quota
history at the new provider's rates — quota verdicts drift on switch day.
"""

from __future__ import annotations

import sqlite3
import threading
from datetime import UTC, datetime
from unittest.mock import patch

import pytest

from kg.llm.providers import REGISTRY
from kg.quota_service import token_cost_usd


class TestTokenCostUsdProvider:
    def test_explicit_provider_overrides_routing(self):
        gem = token_cost_usd("judge", 1_000_000, 0, provider="gemini")
        ds = token_cost_usd("judge", 1_000_000, 0, provider="deepseek")
        assert gem == pytest.approx(REGISTRY["gemini"].input_price_per_m)
        assert ds == pytest.approx(REGISTRY["deepseek"].input_price_per_m)
        assert gem != ds

    def test_none_provider_falls_back_to_routing(self, monkeypatch):
        """A NULL-provider row (legacy data) prices at the call_type's
        currently-routed provider — preserving pre-Phase-2 behaviour."""
        monkeypatch.delenv("LLM_PROVIDER_JUDGE", raising=False)
        monkeypatch.delenv("LLM_PROVIDER_DEFAULT", raising=False)
        cost = token_cost_usd("judge", 1_000_000, 0, provider=None)
        assert cost == pytest.approx(REGISTRY["gemini"].input_price_per_m)

    def test_unknown_provider_does_not_break_historical_reads(self):
        """A row tagged with a since-removed provider must not blow up a
        quota read — it falls back to the routed provider, not raises."""
        cost = token_cost_usd("judge", 1_000_000, 0, provider="retired_xyz")
        assert cost > 0

    def test_embed_provider_pricing(self):
        cost = token_cost_usd("embed", 1_000_000, 0, provider="gemini")
        assert cost == pytest.approx(REGISTRY["gemini"].embed_price_per_m)


@pytest.fixture
def mock_db():
    """In-memory token_usage DB with the Phase 1 provider/model columns."""
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.execute(
        """
        CREATE TABLE token_usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            call_type TEXT NOT NULL,
            input_tokens INTEGER NOT NULL DEFAULT 0,
            output_tokens INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            provider TEXT,
            model TEXT
        )
        """
    )
    conn.commit()
    lock = threading.Lock()
    with patch("kg.quota_service._get_conn", return_value=conn), \
         patch("kg.quota_service._lock", lock):
        yield conn
    conn.close()


def _insert(conn, user_id, call_type, t_in, t_out, when, provider=None, model=None):
    conn.execute(
        "INSERT INTO token_usage "
        "(user_id, call_type, input_tokens, output_tokens, created_at, provider, model) "
        "VALUES (?,?,?,?,?,?,?)",
        (user_id, call_type, t_in, t_out, when, provider, model),
    )
    conn.commit()


def test_used_usd_prices_each_row_by_its_own_provider(mock_db):
    """Two judge rows, two providers — total cost must sum each row at its
    own provider's rate, not reprice both at the routed provider."""
    from kg.quota_service import _used_usd

    now = datetime.now(UTC).isoformat()
    _insert(mock_db, "u1", "judge", 1_000_000, 0, now, "gemini", "gemini-2.5-flash-lite")
    _insert(mock_db, "u1", "judge", 1_000_000, 0, now, "deepseek", "deepseek-v4-flash")

    used = _used_usd("u1")
    expected = (
        REGISTRY["gemini"].input_price_per_m
        + REGISTRY["deepseek"].input_price_per_m
    )
    assert used == pytest.approx(expected)


def test_used_usd_null_provider_uses_routed(mock_db, monkeypatch):
    """A legacy NULL-provider row still costs — priced at routed provider."""
    monkeypatch.delenv("LLM_PROVIDER_JUDGE", raising=False)
    monkeypatch.delenv("LLM_PROVIDER_DEFAULT", raising=False)
    from kg.quota_service import _used_usd

    now = datetime.now(UTC).isoformat()
    _insert(mock_db, "u1", "judge", 1_000_000, 0, now, None, None)
    used = _used_usd("u1")
    assert used == pytest.approx(REGISTRY["gemini"].input_price_per_m)


def test_get_user_usage_range_groups_by_provider(mock_db):
    """get_user_usage_range aggregates same call_type across providers into
    one bucket, but each provider's tokens priced at its own rate."""
    from kg.quota_service import get_user_usage_range

    now = datetime.now(UTC).isoformat()
    _insert(mock_db, "u1", "judge", 1_000_000, 0, now, "gemini", "gemini-2.5-flash-lite")
    _insert(mock_db, "u1", "judge", 1_000_000, 0, now, "deepseek", "deepseek-v4-flash")

    out = get_user_usage_range("u1")
    assert out["calls"]["judge"]["count"] == 2
    assert out["tokens"]["judge"]["input_tokens"] == 2_000_000
    expected = (
        REGISTRY["gemini"].input_price_per_m
        + REGISTRY["deepseek"].input_price_per_m
    )
    assert out["total_cost_usd"] == pytest.approx(round(expected, 6))
