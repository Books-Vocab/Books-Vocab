"""graph_event_log.py — per-user append-only ledger of knowledge-graph mutations.

每次圖譜連結變動(新增 / 改 confidence / 隱藏 / 取消隱藏 / 棄用 / 刪除)append 一筆不可變
事件。與 ``review_events`` 對稱:per-user SQLite、``event_id`` 冪等去重、server 端單調
遞增 ``ingested_at`` 當 pull / 研究 cursor。圖譜本身(``graph_{nb}.json``)只存「當前態」,
本帳本補上「怎麼變成現在這樣」的完整歷史,供未來深度研究(圖譜成長曲線 / link 密度演進 /
聚類形成過程)。

``is_synthetic`` 區分「合成的過去」(一次性遷移回填,``True``)與「真實的未來」(上線後在
GraphStore 寫方法 emit,``False``),研究時可 ``WHERE is_synthetic`` 一刀切開、互不污染。

純記錄、不重算:event 記 per-mutation diff(``confidence_before/after``、
``status_before/after``),搭配定期整檔 snapshot 即可重建任意時間點的圖譜。圖譜本身是純
增量 mutation(無全量重算),故 diff event + 週期 snapshot 與資料模型天然契合。
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any

from sqlalchemy import event, func
from sqlmodel import Field as SQLField
from sqlmodel import Session, SQLModel, create_engine, select


def _install_serializable_sqlite(engine: Any) -> None:
    """每條 pooled 連線套 WAL + ``BEGIN IMMEDIATE``,把 read-max-then-insert 的
    ``ingested_at`` 取號序列化,使並發寫入(合成 / 遷移批次,以及未來 GraphStore emit)下
    ``ingested_at`` 仍嚴格單調且唯一。與 ``review_events`` 同一套 serialized-transaction
    recipe;``busy_timeout`` 讓等待的 writer 阻塞而非 "database is locked" 失敗。"""

    @event.listens_for(engine, "connect")
    def _configure_connection(dbapi_conn, _record):  # noqa: ANN001
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.execute("PRAGMA busy_timeout=30000")
        cur.close()
        # 關閉 pysqlite 隱式 BEGIN,改由 begin-listener 顯式驅動。
        dbapi_conn.isolation_level = None

    @event.listens_for(engine, "begin")
    def _begin_immediate(conn):  # noqa: ANN001
        conn.exec_driver_sql("BEGIN IMMEDIATE")


def _now() -> datetime:
    """Indirection over the wall clock so tests can exercise the monotonic guard."""
    return datetime.now(UTC)


def _as_utc(dt: datetime) -> datetime:
    """正規化為 tz-aware UTC。naive(來源 cards.db 'YYYY-MM-DD HH:MM:SS' 或合成產出)
    視為 UTC;aware 轉 UTC。不轉的話 SQLite 存回的 naive 與 aware cursor 相比會 TypeError。"""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


class GraphEventType(StrEnum):
    """一筆圖譜變動的種類。對應 GraphStore 的 mutation 方法。"""

    LINK_ADDED = "link_added"
    LINK_UPDATED = "link_updated"        # confidence / kind / reason / status 改值
    LINK_HIDDEN = "link_hidden"
    LINK_UNHIDDEN = "link_unhidden"      # hidden → active(取消隱藏)
    LINK_DEPRECATED = "link_deprecated"  # 刪卡連帶,標 status=deprecated
    LINK_RESTORED = "link_restored"      # deprecated → active(卡復原連帶,與 unhidden 區隔)
    LINK_DELETED = "link_deleted"        # 硬刪(物理移除 link + block pair)


class GraphEventSource(StrEnum):
    """變動的觸發管道。研究時可區分人工 vs AI vs ops。"""

    AUTO = "auto"        # pipeline embed+judge 自動建 / 改
    MANUAL = "manual"    # 使用者手動 API(vocab_graph_ops / vocab_crud)
    OPS = "ops"          # ops_edit 工具
    SYNTH = "synth"      # 一次性合成歷史回填(配 is_synthetic=True)


@dataclass(frozen=True)
class GraphEventDraft:
    """一筆待寫入的圖譜變動事件。server 端的 ``ingested_at`` 由 store 賦值,不在此。"""

    event_id: str
    event_type: str
    link_id: str
    from_id: str
    to_id: str
    kind: str
    confidence_before: float | None
    confidence_after: float | None
    reason: str | None
    status_before: str | None
    status_after: str | None
    source: str
    notebook_id: str
    occurred_at: datetime
    is_synthetic: bool = False


class GraphEvent(SQLModel, table=True):
    """One immutable graph mutation event, keyed by a stable event id."""

    event_id: str = SQLField(primary_key=True)
    event_type: str = SQLField(index=True)
    link_id: str = SQLField(index=True)
    from_id: str
    to_id: str
    kind: str
    confidence_before: float | None = SQLField(default=None)
    confidence_after: float | None = SQLField(default=None)
    reason: str | None = SQLField(default=None)
    status_before: str | None = SQLField(default=None)
    status_after: str | None = SQLField(default=None)
    source: str = SQLField(default="auto", index=True)
    notebook_id: str = SQLField(default="default", index=True)
    # 變動實際發生的業務時間(合成回填時錨定真實歷史;真實事件為 mutation 當下)。
    occurred_at: datetime = SQLField(index=True)
    # Server-assigned ingestion time — 單調 watermark,研究 / pull cursor 沿此維度走,
    # 永不漏掉 occurred_at 在過去的遲到事件。
    ingested_at: datetime = SQLField(default_factory=lambda: datetime.now(UTC), index=True)
    is_synthetic: bool = SQLField(default=False, index=True)


class GraphEventStore:
    """SQLite-backed per-user graph mutation event store (append-only)."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(f"sqlite:///{self.path.absolute()}")
        _install_serializable_sqlite(self.engine)
        GraphEvent.metadata.create_all(
            self.engine, tables=[GraphEvent.__table__], checkfirst=True
        )

    def insert_many(self, drafts: list[GraphEventDraft]) -> dict[str, int]:
        """冪等批次 append。已存在的 ``event_id`` skip;每筆取得嚴格遞增唯一 ingested_at。"""
        inserted = 0
        skipped = 0
        with Session(self.engine) as session:
            # 從現有 max 續接單調 ingestion clock,使新事件 ingested_at 嚴格遞增、唯一 ——
            # 即使遇 NTP 回撥或同微秒多筆寫入。
            last_ingested = session.exec(select(func.max(GraphEvent.ingested_at))).one()
            if last_ingested is not None and last_ingested.tzinfo is None:
                last_ingested = last_ingested.replace(tzinfo=UTC)
            for d in drafts:
                if session.get(GraphEvent, d.event_id) is not None:
                    skipped += 1
                    continue
                now = _now()
                if last_ingested is None or now > last_ingested:
                    ingested_at = now
                else:
                    ingested_at = last_ingested + timedelta(microseconds=1)
                last_ingested = ingested_at
                session.add(
                    GraphEvent(
                        event_id=d.event_id,
                        event_type=d.event_type,
                        link_id=d.link_id,
                        from_id=d.from_id,
                        to_id=d.to_id,
                        kind=d.kind,
                        confidence_before=d.confidence_before,
                        confidence_after=d.confidence_after,
                        reason=d.reason,
                        status_before=d.status_before,
                        status_after=d.status_after,
                        source=d.source,
                        notebook_id=d.notebook_id,
                        occurred_at=_as_utc(d.occurred_at),
                        ingested_at=ingested_at,
                        is_synthetic=d.is_synthetic,
                    )
                )
                inserted += 1
            session.commit()
        return {"inserted": inserted, "skipped": skipped}

    def append(
        self,
        *,
        event_id: str,
        event_type: str,
        link_id: str,
        from_id: str,
        to_id: str,
        kind: str,
        source: str,
        notebook_id: str,
        occurred_at: datetime,
        confidence_before: float | None = None,
        confidence_after: float | None = None,
        reason: str | None = None,
        status_before: str | None = None,
        status_after: str | None = None,
        is_synthetic: bool = False,
    ) -> dict[str, int]:
        """單筆便利寫入(供 GraphStore 寫方法 emit)。``event_type`` / ``source`` / ``kind``
        接受 str 或 StrEnum(一律 ``str()`` 正規化為字面值)。"""
        return self.insert_many(
            [
                GraphEventDraft(
                    event_id=event_id,
                    event_type=str(event_type),
                    link_id=link_id,
                    from_id=from_id,
                    to_id=to_id,
                    kind=str(kind),
                    confidence_before=confidence_before,
                    confidence_after=confidence_after,
                    reason=reason,
                    status_before=status_before,
                    status_after=status_after,
                    source=str(source),
                    notebook_id=notebook_id,
                    occurred_at=occurred_at,
                    is_synthetic=is_synthetic,
                )
            ]
        )

    def all(self) -> list[GraphEvent]:
        with Session(self.engine) as session:
            return list(
                session.exec(select(GraphEvent).order_by(GraphEvent.ingested_at)).all()
            )

    def get_since(self, since: datetime) -> list[GraphEvent]:
        # Strict ``>``: ingested_at 單調且唯一,cursor 邊界事件已交付過,不需重撈。
        # 正規化 cursor 為 tz-aware UTC —— 呼叫端傳 naive 時與 store 存的 aware 直接比較
        # 會 silent 走錯邊界(SQLite 字面字串比較),先轉齊避免漏撈/重撈。
        since = _as_utc(since)
        with Session(self.engine) as session:
            return list(
                session.exec(
                    select(GraphEvent)
                    .where(GraphEvent.ingested_at > since)
                    .order_by(GraphEvent.ingested_at)
                ).all()
            )

    def query(
        self,
        *,
        link_id: str | None = None,
        notebook_id: str | None = None,
        event_type: str | None = None,
        source: str | None = None,
        synthetic: bool | None = None,
    ) -> list[GraphEvent]:
        """研究篩選。``synthetic=None`` 全部 / ``True`` 只合成 / ``False`` 只真實。"""
        with Session(self.engine) as session:
            stmt = select(GraphEvent)
            if link_id is not None:
                stmt = stmt.where(GraphEvent.link_id == link_id)
            if notebook_id is not None:
                stmt = stmt.where(GraphEvent.notebook_id == notebook_id)
            if event_type is not None:
                stmt = stmt.where(GraphEvent.event_type == str(event_type))
            if source is not None:
                stmt = stmt.where(GraphEvent.source == str(source))
            if synthetic is not None:
                stmt = stmt.where(GraphEvent.is_synthetic == synthetic)
            return list(session.exec(stmt.order_by(GraphEvent.ingested_at)).all())

    def close(self) -> None:
        if self.engine is not None:
            self.engine.dispose()
            self.engine = None


class GraphSnapshot(SQLModel, table=True):
    """One full-graph checkpoint for a notebook at a point in time.

    ``links_json`` 是該時點整檔 link 的序列化。配 ``GraphEvent`` diff,可從最近 snapshot
    起套後續事件重建任意時間點;也是 event log 被截斷時的安全網。
    """

    snapshot_id: str = SQLField(primary_key=True)
    notebook_id: str = SQLField(index=True)
    taken_at: datetime = SQLField(index=True)
    link_count: int = SQLField(default=0)
    links_json: str = SQLField(default="[]")
    is_synthetic: bool = SQLField(default=False, index=True)


@dataclass(frozen=True)
class GraphSnapshotView:
    """讀回的 snapshot,``links`` 已反序列化為 list[dict]。"""

    snapshot_id: str
    notebook_id: str
    taken_at: datetime
    link_count: int
    links: list[dict]
    is_synthetic: bool


class GraphSnapshotStore:
    """SQLite-backed per-user graph snapshot store(與 GraphEventStore 共用 graph_events.db)。"""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(f"sqlite:///{self.path.absolute()}")
        _install_serializable_sqlite(self.engine)
        GraphSnapshot.metadata.create_all(
            self.engine, tables=[GraphSnapshot.__table__], checkfirst=True
        )

    def save(
        self,
        notebook_id: str,
        links: list[dict],
        *,
        is_synthetic: bool,
        taken_at: datetime | None = None,
    ) -> str:
        snapshot_id = uuid.uuid4().hex
        with Session(self.engine) as session:
            session.add(
                GraphSnapshot(
                    snapshot_id=snapshot_id,
                    notebook_id=notebook_id,
                    taken_at=_as_utc(taken_at) if taken_at else _now(),
                    link_count=len(links),
                    links_json=json.dumps(links, default=str),
                    is_synthetic=is_synthetic,
                )
            )
            session.commit()
        return snapshot_id

    def _view(self, row: GraphSnapshot) -> GraphSnapshotView:
        return GraphSnapshotView(
            snapshot_id=row.snapshot_id,
            notebook_id=row.notebook_id,
            taken_at=row.taken_at,
            link_count=row.link_count,
            links=json.loads(row.links_json),
            is_synthetic=row.is_synthetic,
        )

    def latest(self, notebook_id: str) -> GraphSnapshotView | None:
        with Session(self.engine) as session:
            row = session.exec(
                select(GraphSnapshot)
                .where(GraphSnapshot.notebook_id == notebook_id)
                # 次要排序 snapshot_id 打破同 taken_at 平手,讓 "latest" 確定(批量
                # 同時戳寫入時不致非確定回任一筆)。
                .order_by(
                    GraphSnapshot.taken_at.desc(),  # type: ignore[attr-defined]
                    GraphSnapshot.snapshot_id.desc(),  # type: ignore[attr-defined]
                )
            ).first()
            return self._view(row) if row is not None else None

    def all(self, *, notebook_id: str | None = None) -> list[GraphSnapshotView]:
        with Session(self.engine) as session:
            stmt = select(GraphSnapshot)
            if notebook_id is not None:
                stmt = stmt.where(GraphSnapshot.notebook_id == notebook_id)
            rows = session.exec(stmt.order_by(GraphSnapshot.taken_at)).all()
            return [self._view(r) for r in rows]

    def close(self) -> None:
        if self.engine is not None:
            self.engine.dispose()
            self.engine = None
