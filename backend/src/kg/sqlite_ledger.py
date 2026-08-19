"""sqlite_ledger.py — 共用的 per-user append-only SQLite 帳本基礎件。

``review_events`` 與 ``graph_event_log`` 兩個帳本需要**完全相同**的 serialized-transaction
recipe(WAL + ``BEGIN IMMEDIATE`` + busy_timeout)與**嚴格單調、唯一**的 server 端
``ingested_at`` 取號時鐘。抽成單一副本,免得日後修 concurrency / tz 細節時兩邊 drift
(歷史上這段在 review/graph 各有一份近乎相同的 code,正是 review #12 指出的重複)。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import event


def install_serializable_sqlite(engine: Any) -> None:
    """每條 pooled 連線套 WAL + ``BEGIN IMMEDIATE``,把 read-max-then-insert 的 ingested_at
    取號序列化,使並發 writer(雙裝置同步 / 遷移批次 / GraphStore emit)下 ingested_at 仍嚴格
    單調且唯一。``busy_timeout`` 讓等待的 writer 阻塞而非 "database is locked" 失敗。"""

    @event.listens_for(engine, "connect")
    def _configure_connection(dbapi_conn, _record):  # noqa: ANN001
        cur = dbapi_conn.cursor()
        # Set the busy handler before journal-mode negotiation: WAL itself is
        # a writer-lock operation during concurrent legacy-store startup.
        cur.execute("PRAGMA busy_timeout=30000")
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.close()
        # 關閉 pysqlite 隱式 BEGIN,改由 begin-listener 顯式驅動。
        dbapi_conn.isolation_level = None

    @event.listens_for(engine, "begin")
    def _begin_immediate(conn):  # noqa: ANN001
        conn.exec_driver_sql("BEGIN IMMEDIATE")


def now_utc() -> datetime:
    """Indirection over the wall clock so tests can freeze it to exercise the
    monotonic ingestion guard (same-instant / backward-clock scenarios)."""
    return datetime.now(UTC)


def as_utc(dt: datetime) -> datetime:
    """正規化為 tz-aware UTC。naive(來源 cards.db / SQLite 存回的 naive)視為 UTC;aware 轉
    UTC。不轉的話 naive 與 aware 相比會 TypeError、isoformat 出 naive 字串又被 store 拒收。"""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def normalize_last_ingested(last: datetime | None) -> datetime | None:
    """``func.max(ingested_at)`` 回來可能是 naive(SQLite 去 tz)。補成 aware UTC 以便與
    ``now_utc()`` 比較,None 直通。"""
    if last is not None and last.tzinfo is None:
        return last.replace(tzinfo=UTC)
    return last


def next_ingested_at(last: datetime | None, now: datetime) -> datetime:
    """下一個嚴格遞增、唯一的 ingested_at:時鐘前進就用 ``now``,否則(NTP 回撥 / 同微秒多筆)
    取 ``last + 1µs``。呼叫端須把回傳值回寫成新的 ``last`` 續接。"""
    if last is None or now > last:
        return now
    return last + timedelta(microseconds=1)
