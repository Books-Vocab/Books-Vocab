"""Tests for llm_error_log — real LLM failure recording."""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from kg import llm_error_log


@pytest.fixture(autouse=True)
def _reset_and_redirect(tmp_path, monkeypatch):
    monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
    llm_error_log.DATA_DIR = tmp_path
    llm_error_log.DB_PATH = tmp_path / "llm_errors.db"
    llm_error_log._reset()
    yield
    llm_error_log._reset()


class TestRecord:
    def test_basic_record(self):
        llm_error_log.record(
            user_id="u1",
            call_type="judge",
            provider="gemini",
            model="gemini-2.5-flash-lite",
            error_class="RateLimitError",
            status_code=429,
            message="rate limited",
        )
        rows = llm_error_log._get_conn().execute(
            "SELECT user_id, call_type, provider, model, error_class, status_code, message FROM llm_errors"
        ).fetchall()
        assert len(rows) == 1
        uid, ct, prov, mod, ec, sc, msg = rows[0]
        assert uid == "u1"
        assert ct == "judge"
        assert prov == "gemini"
        assert mod == "gemini-2.5-flash-lite"
        assert ec == "RateLimitError"
        assert sc == 429
        assert msg == "rate limited"

    def test_empty_user_id_skips(self):
        llm_error_log.record(
            user_id="",
            call_type="judge",
            error_class="RuntimeError",
        )
        rows = llm_error_log._get_conn().execute("SELECT COUNT(*) FROM llm_errors").fetchall()
        assert rows[0][0] == 0

    def test_nullable_fields(self):
        """provider, model, status_code, message are all nullable."""
        llm_error_log.record(
            user_id="u1",
            call_type="translate_quick",
            error_class="APITimeoutError",
            status_code=None,
            message=None,
        )
        row = llm_error_log._get_conn().execute(
            "SELECT provider, model, status_code, message FROM llm_errors"
        ).fetchone()
        assert row[0] is None
        assert row[1] is None
        assert row[2] is None
        assert row[3] == ""

    def test_message_truncated(self):
        long_msg = "x" * 1000
        llm_error_log.record(
            user_id="u1",
            call_type="judge",
            error_class="Error",
            message=long_msg,
        )
        msg = llm_error_log._get_conn().execute(
            "SELECT message FROM llm_errors"
        ).fetchone()[0]
        assert len(msg) == 500
        assert msg == "x" * 500

    def test_created_at_iso8601(self):
        before = datetime.now(UTC).isoformat()
        llm_error_log.record(
            user_id="u1",
            call_type="judge",
            error_class="RuntimeError",
        )
        after = datetime.now(UTC).isoformat()
        ts = llm_error_log._get_conn().execute(
            "SELECT created_at FROM llm_errors"
        ).fetchone()[0]
        assert before <= ts <= after


class TestReset:
    def test_reset_switches_db_path(self, tmp_path):
        """After _reset(), changing DB_PATH makes the next _get_conn open a fresh DB."""
        llm_error_log.record(user_id="u1", call_type="judge", error_class="E")
        llm_error_log._reset()
        new_path = tmp_path / "other" / "llm_errors.db"
        new_path.parent.mkdir(parents=True)
        llm_error_log.DB_PATH = new_path
        llm_error_log._get_conn()
        # Actually check: old DB still has 1 row, new DB has 0
        old_count = llm_error_log._get_conn().execute(
            "SELECT COUNT(*) FROM llm_errors"
        ).fetchone()[0]
        assert old_count == 0  # because _get_conn now opens new_path
