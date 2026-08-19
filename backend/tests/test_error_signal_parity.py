"""Drift gate:business-error 謂詞(「什麼算 error」)只有一份 SoT。

admin_trends / ops_cli cmd_trends / admin_observability 都把「errors = failed
pipeline + auto-judge rejects(degree_cap 除外)」攤進各自的 SQL。本檔兩層守護:

1. **結構層**(cheap):釘住各消費面引用同一組 SoT 常數、不再硬編字面。
2. **行為層**(`test_*_db_parity`):對**同一組真實 DB**實跑 admin 與 ops 兩條
   公開 call-path,斷言逐日 error 計數**完全相等**,且等於手算期望值 ——
   degree_cap reject 被排除、只有 status=failed 與 auto reject 入帳。
   這條才真正擋得住「常數本身語意錯」或「某面私改 query 形狀」——
   純字串相等/inspect 檢查(tautology)抓不到。
"""
from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path


def test_sot_constants_exist():
    from kg.error_signals import (  # noqa: F401
        JUDGE_AUTO_REJECT_WHERE,
        JUDGE_AUTO_SOURCE_WHERE,
        JUDGE_REJECTED_WHERE,
        PIPELINE_FAILURE_STATUS,
        PIPELINE_FAILURE_WHERE,
    )


def test_judge_reject_predicate_references_degree_cap_sot():
    """auto-judge reject 謂詞必須由原子謂詞 + judge_log 的 DEGREE_CAP_EXCLUSION_SQL
    組成,不得獨立硬編字面。"""
    from kg.error_signals import (
        JUDGE_AUTO_REJECT_WHERE,
        JUDGE_AUTO_SOURCE_WHERE,
        JUDGE_REJECTED_WHERE,
    )
    from kg.judge_log import DEGREE_CAP_EXCLUSION_SQL

    assert DEGREE_CAP_EXCLUSION_SQL in JUDGE_AUTO_REJECT_WHERE
    assert JUDGE_AUTO_SOURCE_WHERE in JUDGE_AUTO_REJECT_WHERE
    assert JUDGE_REJECTED_WHERE in JUDGE_AUTO_REJECT_WHERE


def test_pipeline_failure_where_composed_from_status_token():
    """WHERE 片段由裸 STATUS token 組成 —— IN 清單/CASE 等形狀可重用同一 token。"""
    from kg.error_signals import PIPELINE_FAILURE_STATUS, PIPELINE_FAILURE_WHERE

    assert PIPELINE_FAILURE_STATUS == "failed"
    assert PIPELINE_FAILURE_WHERE == f"status = '{PIPELINE_FAILURE_STATUS}'"


def test_admin_trends_uses_sot():
    """admin_trends 的 judge-reject / pipeline-failure extra_where 必須 == SoT 常數。"""
    import kg.admin_trends as at
    import kg.error_signals as es

    assert es.JUDGE_AUTO_REJECT_WHERE == at._JUDGE_REJECT_WHERE
    assert es.PIPELINE_FAILURE_WHERE == at._PIPELINE_FAILURE_WHERE


def test_observability_uses_error_signal_sot():
    """admin_observability 的失敗率 / 拒絕率 query 必須走 error_signals SoT,
    不得硬編 status='failed' / accepted=0 / source='auto' 等裸字面(第三處 drift 源)。"""
    import inspect

    import kg.admin_observability as ao

    fail_src = inspect.getsource(ao._pipeline_failure_rate_24h)
    assert "es.PIPELINE_FAILURE_WHERE" in fail_src
    assert "es.PIPELINE_FAILURE_STATUS" in fail_src
    assert "status='failed'" not in fail_src.replace(" ", "")

    # judge query 完全由 SoT 原子謂詞組出 SQL(positive 斷言即足以證明走 SoT;
    # source='auto'/accepted=0 是刻意不守的單欄 token,不做 negative 字面斷言)。
    rej_src = inspect.getsource(ao._judge_rejection_rate_24h)
    assert "es.JUDGE_REJECTED_WHERE" in rej_src
    assert "es.JUDGE_AUTO_SOURCE_WHERE" in rej_src


def test_ops_cli_uses_sot():
    """ops_cli cmd_trends 不得再出現硬編的 degree_cap / failure 字面 —— 必須走 SoT。"""
    import inspect
    import sys

    backend_root = str(Path(__file__).resolve().parent.parent)
    if backend_root not in sys.path:
        sys.path.insert(0, backend_root)
    import ops_cli

    src = inspect.getsource(ops_cli.cmd_trends).replace(" ", "")
    assert "reject_reason!='degree_cap'" not in src, "ops_cli 仍硬編 degree_cap 字面"
    assert "status='failed'" not in src, "ops_cli 仍硬編 pipeline failure 字面"


def test_observability_alerts_uses_degree_cap_sot():
    """check_judge_rejection_rate 的 degree_cap 排除必須走 judge_log SoT 常數。"""
    import inspect

    import kg.observability_alerts as oa

    src = inspect.getsource(oa.check_judge_rejection_rate)
    assert "reject_reason != 'degree_cap'" not in src.replace("  ", " ")


# ---------------------------------------------------------------------------
# 行為層 parity:同一組真實 DB,admin 與 ops 兩條 call-path 的 error 計數必須相等
# ---------------------------------------------------------------------------

_TS = datetime.now(UTC).replace(microsecond=0).isoformat()  # 落在今日窗口內


def _make_pipeline_db(path: Path) -> Path:
    """建 pipeline_runs.db。混入 failed / ok / running 以驗『只算 failed』。"""
    db = path / "pipeline_runs.db"
    conn = sqlite3.connect(str(db))
    conn.execute(
        """CREATE TABLE pipeline_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT UNIQUE NOT NULL, user_id TEXT NOT NULL,
            notebook_id TEXT NOT NULL, trigger TEXT NOT NULL,
            started_at TEXT NOT NULL, ended_at TEXT,
            status TEXT NOT NULL DEFAULT 'running', steps TEXT NOT NULL DEFAULT '[]')"""
    )
    runs = [
        ("r1", "failed"), ("r2", "failed"), ("r3", "failed"),  # 3 個業務失敗
        ("r4", "ok"), ("r5", "ok"),                            # 成功,不算
        ("r6", "running"),                                      # 進行中,不算
    ]
    conn.executemany(
        "INSERT INTO pipeline_runs (run_id, user_id, notebook_id, trigger, "
        "started_at, status) VALUES (?, 'u1', 'nb', 'manual', ?, ?)",
        [(rid, _TS, st) for rid, st in runs],
    )
    conn.commit()
    conn.close()
    return db


def _make_judge_db(path: Path) -> Path:
    """建 judge_log.db。混入 degree_cap / accepted / manual 以驗排除規則。"""
    db = path / "judge_log.db"
    conn = sqlite3.connect(str(db))
    conn.execute(
        """CREATE TABLE judge_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL, notebook_id TEXT NOT NULL,
            from_id TEXT NOT NULL, to_id TEXT NOT NULL, similarity REAL,
            verdict TEXT NOT NULL, confidence REAL NOT NULL,
            accepted INTEGER NOT NULL, reject_reason TEXT, reason TEXT,
            source TEXT NOT NULL DEFAULT 'auto', created_at TEXT NOT NULL)"""
    )
    # (accepted, reject_reason, source) — 期望入帳的只有 auto + accepted=0 + 非 degree_cap
    rows = [
        (0, None, "auto"),            # ✓ 業務 reject
        (0, "low_conf", "auto"),      # ✓ 業務 reject
        (0, "degree_cap", "auto"),    # ✗ 容量保護,排除
        (1, None, "auto"),            # ✗ accepted,非 reject
        (0, None, "manual"),          # ✗ 人工,非 auto
    ]
    conn.executemany(
        "INSERT INTO judge_log (user_id, notebook_id, from_id, to_id, verdict, "
        "confidence, accepted, reject_reason, source, created_at) "
        "VALUES ('u1','nb','a','b','dup',0.9,?,?,?,?)",
        [(acc, rr, src, _TS) for acc, rr, src in rows],
    )
    conn.commit()
    conn.close()
    return db


# 手算期望:3 failed pipeline + 2 auto non-degree_cap reject = 5
_EXPECTED_TOTAL_ERRORS = 5


def test_error_signal_db_parity(tmp_path, monkeypatch):
    """同一組 DB:admin_trends.collect_trends 與 ops_cli.cmd_trends 的逐日 error
    計數必須完全相等,且總和 == 手算期望(degree_cap 排除、只算 failed/auto-reject)。"""
    import io
    import json as _json
    import sys
    from contextlib import redirect_stdout
    from types import SimpleNamespace

    _make_pipeline_db(tmp_path)
    _make_judge_db(tmp_path)

    # --- admin 公開入口:monkeypatch pl/jl 單例指向 tmp DB ---
    monkeypatch.setenv("KG_DATA_DIR", str(tmp_path))
    import kg.judge_log as jl
    import kg.pipeline_log as pl
    import kg.token_tracker as tt

    monkeypatch.setattr(pl, "DB_PATH", tmp_path / "pipeline_runs.db", raising=True)
    monkeypatch.setattr(jl, "DB_PATH", tmp_path / "judge_log.db", raising=True)
    pl._conn = None
    jl._conn = None
    tt.reset()
    try:
        from kg.admin_trends import collect_trends

        admin = collect_trends(window_days=30)
    finally:
        for mod in (pl, jl):
            if mod._conn is not None:
                mod._conn.close()
                mod._conn = None
        tt.reset()

    # --- ops 公開入口:cmd_trends(--json),connect_ro 讀同一批 DB ---
    backend_root = str(Path(__file__).resolve().parent.parent)
    if backend_root not in sys.path:
        sys.path.insert(0, backend_root)
    import ops_cli

    buf = io.StringIO()
    with redirect_stdout(buf):
        ops_cli.cmd_trends(SimpleNamespace(window=30, json=True))
    ops = _json.loads(buf.getvalue())

    # 1) 兩面逐日序列完全相等(真正的 admin↔ops parity)
    assert ops["errors_per_day"] == admin["errors_per_day"]
    # 2) 總和 == 手算期望(語意正確:degree_cap 排除、只算 failed/auto-reject)
    assert sum(admin["errors_per_day"]) == _EXPECTED_TOTAL_ERRORS
    assert ops["total_errors"] == _EXPECTED_TOTAL_ERRORS

    assert tt._conn is None
