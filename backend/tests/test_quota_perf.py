"""Tests for quota performance optimizations: composite index + check_and_get_quota."""

from __future__ import annotations

import os
import tempfile

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def isolated_tracker(tmp_path, monkeypatch):
    """Patch token_tracker to use a fresh DB in tmp_path."""
    monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
    import importlib
    import kg.token_tracker as tt
    importlib.reload(tt)
    tt._conn = None
    yield tt
    if tt._conn is not None:
        tt._conn.close()
        tt._conn = None


# ---------------------------------------------------------------------------
# Task 1: composite index
# ---------------------------------------------------------------------------

class TestCompositeIndex:

    def test_idx_user_created_exists(self, isolated_tracker):
        conn = isolated_tracker._get_conn()
        rows = conn.execute("PRAGMA index_list(token_usage)").fetchall()
        index_names = [r[1] for r in rows]
        assert "idx_user_created" in index_names

    def test_idx_user_created_covers_correct_columns(self, isolated_tracker):
        conn = isolated_tracker._get_conn()
        rows = conn.execute("PRAGMA index_info(idx_user_created)").fetchall()
        col_names = [r[2] for r in rows]
        assert col_names == ["user_id", "created_at"]


# ---------------------------------------------------------------------------
# Task 2: check_and_get_quota
# ---------------------------------------------------------------------------

class TestCheckAndGetQuota:

    def _fresh_quota_service(self, isolated_tracker):
        import importlib
        import kg.quota_service as qs
        importlib.reload(qs)
        return qs

    def test_not_exceeded_returns_correct_shape(self, isolated_tracker):
        qs = self._fresh_quota_service(isolated_tracker)
        result = qs.check_and_get_quota("user1", "translate_quick", is_pro=False)
        assert "exceeded" in result
        assert "fraction" in result
        assert "reset_seconds" in result

    def test_not_exceeded_fraction_is_one_when_no_usage(self, isolated_tracker):
        qs = self._fresh_quota_service(isolated_tracker)
        result = qs.check_and_get_quota("user1", "translate_quick", is_pro=False)
        assert result["exceeded"] is False
        assert result["fraction"] == 1.0

    def test_exceeded_when_usage_over_limit(self, isolated_tracker):
        qs = self._fresh_quota_service(isolated_tracker)
        # Force usage way over free limit by recording many tokens
        # FREE_DAILY_LIMIT_USD = 0.03; output price = 0.40/1M → need >75000 output tokens
        isolated_tracker.record("user2", "translate_quick", 0, 100_000)
        result = qs.check_and_get_quota("user2", "translate_quick", is_pro=False)
        assert result["exceeded"] is True
        assert result["fraction"] == 0.0

    def test_exceeded_fraction_is_zero(self, isolated_tracker):
        qs = self._fresh_quota_service(isolated_tracker)
        isolated_tracker.record("user3", "translate_quick", 0, 100_000)
        result = qs.check_and_get_quota("user3", "translate_quick", is_pro=False)
        assert result["fraction"] == 0.0

    def test_pro_has_higher_limit(self, isolated_tracker):
        qs = self._fresh_quota_service(isolated_tracker)
        # 75001 output tokens exceeds free limit but not pro limit
        isolated_tracker.record("user_pro", "translate_quick", 0, 76_000)
        free_result = qs.check_and_get_quota("user_pro", "translate_quick", is_pro=False)
        pro_result = qs.check_and_get_quota("user_pro", "translate_quick", is_pro=True)
        assert free_result["exceeded"] is True
        assert pro_result["exceeded"] is False

    def test_reset_seconds_is_86400(self, isolated_tracker):
        qs = self._fresh_quota_service(isolated_tracker)
        result = qs.check_and_get_quota("user4", "translate_quick")
        assert result["reset_seconds"] == 86400

    def test_matches_legacy_check_quota_shape(self, isolated_tracker):
        """check_and_get_quota 回傳結構應與舊 check_quota 一致。"""
        qs = self._fresh_quota_service(isolated_tracker)
        isolated_tracker.record("userA", "translate_quick", 100, 200)
        legacy = qs.check_quota("userA", "translate_quick", is_pro=False)
        unified = qs.check_and_get_quota("userA", "translate_quick", is_pro=False)
        assert legacy["exceeded"] == unified["exceeded"]
        assert legacy["fraction"] == unified["fraction"]
        assert legacy["reset_seconds"] == unified["reset_seconds"]
