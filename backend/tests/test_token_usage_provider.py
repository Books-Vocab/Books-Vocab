"""Phase 1: token_usage gains per-row ``provider`` / ``model`` columns.

Without these, ``token_cost_usd`` can only reprice history at whatever
provider is *currently* routed for a call_type — so a Gemini→DeepSeek
switch silently reprices ~24h of rolling-quota history. These tests pin
the schema + ``record()`` wiring that lets each row carry its own truth.
"""

from __future__ import annotations

import sqlite3


def _reset(tmp_path, monkeypatch):
    """Point token_tracker at a fresh DB under tmp_path and clear singleton."""
    monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
    import kg.token_tracker as tt

    if tt._conn is not None:
        tt._conn.close()
        tt._conn = None
    monkeypatch.setattr(tt, "DB_PATH", tmp_path / "token_usage.db")
    return tt


def _teardown(tt) -> None:
    if tt._conn is not None:
        tt._conn.close()
        tt._conn = None


def test_record_persists_provider_and_model(tmp_path, monkeypatch):
    """record() writes the provider/model it was given onto the row."""
    tt = _reset(tmp_path, monkeypatch)
    tt.record("u1", "translate_quick", 100, 50,
              provider="deepseek", model="deepseek-v4-flash")
    conn = tt._get_conn()
    row = conn.execute(
        "SELECT provider, model FROM token_usage WHERE user_id='u1'"
    ).fetchone()
    _teardown(tt)
    assert row == ("deepseek", "deepseek-v4-flash")


def test_record_provider_model_default_null(tmp_path, monkeypatch):
    """Callers omitting provider/model write NULL — never a crash."""
    tt = _reset(tmp_path, monkeypatch)
    tt.record("u1", "judge", 10, 5)
    conn = tt._get_conn()
    row = conn.execute(
        "SELECT provider, model FROM token_usage WHERE user_id='u1'"
    ).fetchone()
    _teardown(tt)
    assert row == (None, None)


def test_schema_migration_adds_columns_to_existing_db(tmp_path, monkeypatch):
    """An old token_usage.db lacking provider/model gains the columns on
    open, with existing rows preserved and backfilled NULL."""
    db_path = tmp_path / "token_usage.db"
    old = sqlite3.connect(str(db_path))
    old.execute(
        """
        CREATE TABLE token_usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            call_type TEXT NOT NULL,
            input_tokens INTEGER NOT NULL DEFAULT 0,
            output_tokens INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        )
        """
    )
    old.execute(
        "INSERT INTO token_usage "
        "(user_id, call_type, input_tokens, output_tokens, created_at) "
        "VALUES ('legacy', 'enrich', 7, 3, '2026-01-01T00:00:00+00:00')"
    )
    old.commit()
    old.close()

    tt = _reset(tmp_path, monkeypatch)
    conn = tt._get_conn()
    cols = {r[1] for r in conn.execute("PRAGMA table_info(token_usage)")}
    row = conn.execute(
        "SELECT provider, model FROM token_usage WHERE user_id='legacy'"
    ).fetchone()
    _teardown(tt)
    assert "provider" in cols and "model" in cols
    assert row == (None, None)


def test_get_all_stats_unaffected_by_new_columns(tmp_path, monkeypatch):
    """Phase 1 must not change aggregate behaviour — get_all_stats() still
    sums tokens regardless of provider/model presence."""
    tt = _reset(tmp_path, monkeypatch)
    tt.record("u1", "judge", 10, 5, provider="gemini", model="gemini-2.5-flash-lite")
    tt.record("u1", "judge", 20, 7, provider="deepseek", model="deepseek-v4-flash")
    stats = tt.get_all_stats()
    _teardown(tt)
    assert stats["u1"]["judge"] == {
        "input_tokens": 30,
        "output_tokens": 12,
        "calls": 2,
    }
