"""② 根因手術:orphaned-run reaper 與連線取得解耦。

調查鎖定的根因 —— `_get_conn` 首呼把 ``running→interrupted`` 寫進去,使「讀」
觸發「寫」。本測試釘住解耦後的契約:

* `_get_conn()` 純取得連線 + idempotent DDL,**不** reap(讀路徑無副作用);
* `reap_orphaned_runs()` 是唯一、具名、顯式的回收入口(crash recovery 語意 SoT);
* API lifespan 在單-worker 鎖之後顯式呼叫它(對齊 worker_guard 宣稱的 on-startup)。
"""
from __future__ import annotations

import inspect

import pytest

from kg import pipeline_log

pytestmark = pytest.mark.usefixtures("isolate_pipeline_db")


def test_get_conn_does_not_reap():
    """連線重開(模擬 restart)不得自動 reap —— 讀路徑必須無副作用。"""
    pipeline_log.start_run("orphan", "u1", "nb1", "manual")
    assert pipeline_log.get_runs("u1")[0]["status"] == "running"

    # 模擬 process restart:close & reopen。解耦後 _get_conn 不再 reap。
    pipeline_log._reset()
    runs = pipeline_log.get_runs("u1")
    assert runs[0]["status"] == "running", (
        "_get_conn 不應 reap —— 回收必須走顯式 reap_orphaned_runs()"
    )
    assert runs[0]["ended_at"] is None


def test_reap_orphaned_runs_marks_interrupted_and_counts():
    pipeline_log.start_run("orphan_a", "u1", "nb1", "manual")
    pipeline_log.start_run("orphan_b", "u1", "nb2", "background")
    pipeline_log.end_run("orphan_b", "completed")  # 已完成者不該被回收

    reaped = pipeline_log.reap_orphaned_runs()
    assert reaped == 1, "只有 1 個 running 孤兒應被回收"

    by_id = {r["run_id"]: r for r in pipeline_log.get_runs("u1")}
    assert by_id["orphan_a"]["status"] == "interrupted"
    assert by_id["orphan_a"]["ended_at"] is not None
    assert by_id["orphan_b"]["status"] == "completed"


def test_reap_is_idempotent():
    pipeline_log.start_run("orphan", "u1", "nb1", "manual")
    assert pipeline_log.reap_orphaned_runs() == 1
    assert pipeline_log.reap_orphaned_runs() == 0, "二次回收應為 no-op(0 列)"


def test_lifespan_wires_explicit_reaper():
    """API lifespan 必須顯式呼叫 reap_orphaned_runs —— 否則孤兒永不回收。"""
    from kg import api

    src = inspect.getsource(api.create_app)
    assert "reap_orphaned_runs" in src, (
        "lifespan 未呼叫 reap_orphaned_runs;reaper 已從 _get_conn 移除,"
        "startup 必須顯式回收"
    )
    # 時序紅線:全表回收只在單 worker 存活時安全,reap 必須在 worker 鎖之後。
    assert src.index("assert_single_worker") < src.index("reap_orphaned_runs"), (
        "reap_orphaned_runs 必須在 assert_single_worker 之後 —— 否則多 worker "
        "競態窗口內會 cross-mark 彼此正在跑的 run"
    )
