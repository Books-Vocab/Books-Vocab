"""Drift gate: admin 與 ops 對同一 token_usage.db 必須回傳一致的 cost 拆解。

終極目標判準 #3 的落地 —— cost-by-call_type 的業務語意只有一份
(`kg.admin_cost_summary` 的 connection-agnostic 核心),admin(RW conn)與
ops(`connect_ro`)各自連線、共用同一 query+fold。本測試把「兩面分歧」變成
紅燈:任何一方私自改謂詞 → by_call_type / totals 不一致 → fail。
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest


def _make_db(path: Path, rows: list[tuple], *, with_provider: bool, with_model: bool) -> Path:
    """建 token_usage.db。rows = (uid, call_type, in, out, created_at[, provider][, model])。"""
    extra = ""
    cols = "user_id, call_type, input_tokens, output_tokens, created_at"
    if with_provider:
        extra += ", provider TEXT"
        cols += ", provider"
    if with_model:
        extra += ", model TEXT"
        cols += ", model"
    db = path / "token_usage.db"
    conn = sqlite3.connect(str(db))
    conn.execute(
        f"""CREATE TABLE token_usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL, call_type TEXT NOT NULL,
            input_tokens INTEGER NOT NULL DEFAULT 0,
            output_tokens INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL{extra})"""
    )
    n = 5 + int(with_provider) + int(with_model)
    conn.executemany(
        f"INSERT INTO token_usage ({cols}) VALUES ({', '.join('?' * n)})", rows
    )
    conn.commit()
    conn.close()
    return db


_ROWS_FULL = [
    ("u1", "judge", 1_000_000, 100_000, "2026-06-07T00:00:00+00:00", "gemini", "gemini-2.5-flash-lite"),
    ("u1", "enrich", 500_000, 200_000, "2026-06-07T00:00:00+00:00", "deepseek", None),
    ("u1", "translate_quick", 300_000, 50_000, "2026-06-07T00:00:00+00:00", "gemini", "gemini-2.5-flash-lite"),
    ("u1", "translate_quick", 700_000, 10_000, "2026-06-07T00:00:00+00:00", "deepseek", None),
]


def test_core_exists():
    """共用核心 API 必須存在於單一 SoT 模組。"""
    from kg.admin_cost_summary import fold_user_summary, query_cost_rows  # noqa: F401


def test_query_fold_roundtrip_full_schema(tmp_path):
    from kg.admin_cost_summary import fold_user_summary, query_cost_rows

    db = _make_db(tmp_path, _ROWS_FULL, with_provider=True, with_model=True)
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    rows = query_cost_rows(conn, user_id="u1", since=None)
    conn.close()
    summary = fold_user_summary(rows)

    # 兩個 translate_quick provider 切片折回同一 call_type bucket。
    assert summary["by_call_type"]["translate_quick"]["calls"] == 2
    assert set(summary["by_call_type"]) == {"judge", "enrich", "translate_quick"}
    assert summary["by_service"]["judge"]["calls"] == 1
    assert summary["by_service"]["translate"]["calls"] == 2
    assert summary["total_calls"] == 4
    assert summary["total_cost_usd"] > 0


def test_admin_ops_parity(tmp_path):
    """同一 DB:admin 全功能 summary 的 by_call_type/totals == ops 核心折疊結果。"""
    from kg.admin_cost_summary import fold_user_summary, query_cost_rows

    db = _make_db(tmp_path, _ROWS_FULL, with_provider=True, with_model=True)

    # ops 面:connect_ro 風格唯讀連線。
    ro = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    ops_summary = fold_user_summary(query_cost_rows(ro, user_id="u1", since=None))
    ro.close()

    # admin 面:一般(RW)連線。
    rw = sqlite3.connect(str(db))
    admin_summary = fold_user_summary(query_cost_rows(rw, user_id="u1", since=None))
    rw.close()

    assert ops_summary["by_call_type"] == admin_summary["by_call_type"]
    assert ops_summary["total_cost_usd"] == admin_summary["total_cost_usd"]
    assert ops_summary["total_calls"] == admin_summary["total_calls"]


def test_legacy_no_provider_no_model(tmp_path):
    """缺 provider/model 欄的 legacy DB → 不報錯,model fallback 推斷。"""
    from kg.admin_cost_summary import fold_user_summary, query_cost_rows

    rows = [("u1", "embed", 1_000_000, 0, "2026-06-07T00:00:00+00:00")]
    db = _make_db(tmp_path, rows, with_provider=False, with_model=False)
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    summary = fold_user_summary(query_cost_rows(conn, user_id="u1", since=None))
    conn.close()
    assert summary["by_call_type"]["embed"]["calls"] == 1
    # model 欄缺 → 由 call_type 推斷 embed model。
    assert "gemini-embedding-2-preview" in summary["by_model"]
