"""sot_history_migrate.py — 一次性把單一用戶資料夾回填成合成 SoT 歷史帳本。

上線前用戶資料只有「當前態」:cards.db 存複習聚合(無逐筆事件)、graph_{nb}.json 存 link
終態(無變動歷史),而舊 review_events.db 多是 card_id NULL 的同步殘渣。本遷移:

1. **清舊垃圾** — 備份(只一次,保住真原始檔)後**就地**刪 card_id IS NULL 的同步殘渣
   (不整檔 wipe、不 unlink):re-run 不銷毀上線後 iOS 推入的真實事件,也不孤兒化 server
   開啟中的 inode。損毀/非 db 檔才 unlink 重建。
2. **灌合成複習史** — 從 cards.db 每張有複習的卡確定式展開逐筆事件
   (:func:`demo_review_synth.synthesize_review_events`,is_synthetic=True)。
3. **灌合成圖譜史** — 每個 notebook 的 graph_{nb}.json 終態 link 展開生命史
   (:func:`graph_history_synth.synthesize_graph_history_many`,is_synthetic=True)。

dry-run 預設(只報告不寫);apply 才動檔。確定式 + 冪等(event_id 去重 + 備份只建一次 +
複習史 wipe-then-replant 結果不隨重跑膨脹)。圖譜「初始 snapshot」屬 Phase 6(snapshot
寫入器)範疇,此處只回填事件。

注意:這是 ops 一次性腳本路徑,非請求熱路徑;不經 service_factories 快取,直接開檔。
"""

from __future__ import annotations

import logging
import sqlite3
import sys
from collections.abc import Iterable
from contextlib import closing
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

_SQLITE_MAGIC = b"SQLite format 3\x00"

from .demo_review_synth import CardReviewState, synthesize_review_events
from .graph.models import GraphLink
from .graph_event_log import GraphEventStore, GraphSnapshotStore
from .graph_history_synth import synthesize_graph_history_many
from .review_events import ReviewEventStore, push_review_events

_REVIEW_DB = "review_events.db"
_GRAPH_DB = "graph_events.db"
_REVIEW_BAK = "review_events.db.premigration.bak"
_MIGRATED_MARKER = ".sot_history_migrated"  # 存在 = 首次遷移已跑,re-run 不再 purge card_id NULL
logger = logging.getLogger("kg.sot_history_migrate")


@dataclass
class MigrationReport:
    user_dir: Path
    dry_run: bool
    notebooks: list[str] = field(default_factory=list)
    review_events_synthesized: int = 0
    review_events_old_purged: int = 0
    graph_events_synthesized: int = 0
    graph_snapshots_taken: int = 0
    backups: list[Path] = field(default_factory=list)


def _parse_ts(raw: str | None) -> datetime | None:
    """cards.db 存 naive 'YYYY-MM-DD HH:MM:SS.ffffff' 或 ISO;None 直通。
    下游 demo_review_synth._as_utc 會把 naive 視為 UTC。"""
    if raw is None or raw == "":
        return None
    return datetime.fromisoformat(raw)


def _load_review_states(cards_db: Path) -> list[CardReviewState]:
    """從 cards.db 投影出有複習的卡(review_count>0 且有 last_reviewed_at)。

    含 is_deleted 卡 —— 已刪卡的複習史仍是研究料(學習軌跡不因刪卡而消失)。
    """
    if not cards_db.exists():
        return []
    states: list[CardReviewState] = []
    with closing(sqlite3.connect(cards_db)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """SELECT id, content, notebook_id, review_count, lapse_count,
                      review_streak, last_review_feedback, last_reviewed_at,
                      created_at, review_interval_hours
               FROM card WHERE review_count > 0 AND last_reviewed_at IS NOT NULL"""
        ).fetchall()
    for r in rows:
        created = _parse_ts(r["created_at"])
        if created is None:
            continue  # 無建卡時間無法錨定時間窗,跳過
        states.append(
            CardReviewState(
                card_id=r["id"],
                content=r["content"] or "",
                notebook_id=r["notebook_id"] or "default",
                review_count=int(r["review_count"] or 0),
                lapse_count=int(r["lapse_count"] or 0),
                review_streak=int(r["review_streak"] or 0),
                last_review_feedback=int(
                    r["last_review_feedback"] if r["last_review_feedback"] is not None else -1
                ),
                last_reviewed_at=_parse_ts(r["last_reviewed_at"]),
                created_at=created,
                review_interval_hours=float(r["review_interval_hours"] or 12.0),
            )
        )
    return states


def _load_links(graph_path: Path) -> list[GraphLink]:
    import json

    try:
        raw = json.loads(graph_path.read_text())
    except (OSError, json.JSONDecodeError, ValueError):
        logger.warning("Failed to load graph links from %s", graph_path, exc_info=True)
        return []
    rows = raw if isinstance(raw, list) else list(raw.values()) if isinstance(raw, dict) else []
    links: list[GraphLink] = []
    for row in rows:
        try:
            links.append(GraphLink.model_validate(row))
        except Exception as exc:  # noqa: BLE001 — 跳過畸形/退役 kind 的 link
            logger.debug("Skipping malformed migration link row from %s: %s", graph_path, exc)
            continue
    return links


def _discover_notebooks(user_dir: Path, cards_db: Path) -> list[str]:
    nbs: set[str] = set()
    if cards_db.exists():
        with closing(sqlite3.connect(cards_db)) as conn:
            for (nb,) in conn.execute("SELECT DISTINCT notebook_id FROM card").fetchall():
                nbs.add(nb or "default")
    for p in user_dir.glob("graph_*.json"):
        nbs.add(p.stem[len("graph_"):])
    return sorted(nbs)


def _is_sqlite_file(path: Path) -> bool:
    try:
        with path.open("rb") as f:
            return f.read(16) == _SQLITE_MAGIC
    except OSError:
        logger.warning("Failed to read sqlite signature from %s", path, exc_info=True)
        return False


def _count_review_junk(review_db: Path) -> int:
    """唯讀計「待清垃圾」數 = card_id IS NULL 的同步殘渣。**不**開 ReviewEventStore —— 其
    __init__ 會 ALTER TABLE / CREATE INDEX / backfill,在 dry-run 會改動原始檔。改走唯讀
    連線純 SELECT。只算 card_id NULL:真實事件(card_id 有值)與合成事件不在 purge 範圍。"""
    if not review_db.exists() or not _is_sqlite_file(review_db):
        return 0
    try:
        with closing(sqlite3.connect(f"file:{review_db}?mode=ro", uri=True)) as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM reviewevent WHERE card_id IS NULL"
            ).fetchone()
            return int(row[0]) if row else 0
    except sqlite3.Error:
        logger.warning("Failed to count review junk in %s", review_db, exc_info=True)
        return 0


def _purge_review_junk(review_db: Path) -> None:
    """就地刪除 card_id IS NULL 的同步殘渣(不 unlink → 不孤兒化 server 開啟中的 inode,
    且絕不碰真實/合成事件)。表不存在或損毀則忽略(下游 fresh store 仍會重建)。"""
    try:
        with closing(sqlite3.connect(review_db)) as conn:
            conn.execute("DELETE FROM reviewevent WHERE card_id IS NULL")
            conn.commit()
    except sqlite3.Error:
        logger.warning("Failed to purge review junk in %s", review_db, exc_info=True)
        print(
            f"[sot_history_migrate] unable to purge review junk from {review_db} (continuing)",
            file=sys.stderr,
        )


def _notebooks_without_snapshot_ro(graph_db: Path, notebooks: Iterable[str]) -> int:
    """唯讀計「尚無初始 snapshot」的 notebook 數(dry-run 報告用)。不建檔、不改 schema。"""
    nbs = list(notebooks)
    if not graph_db.exists() or not _is_sqlite_file(graph_db):
        return len(nbs)
    try:
        with closing(sqlite3.connect(f"file:{graph_db}?mode=ro", uri=True)) as conn:
            has_table = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='graphsnapshot'"
            ).fetchone()
            if not has_table:
                return len(nbs)
            return sum(
                1 for nb in nbs
                if conn.execute(
                    "SELECT 1 FROM graphsnapshot WHERE notebook_id=? LIMIT 1", (nb,)
                ).fetchone() is None
            )
    except sqlite3.Error:
        logger.warning("Failed to query graph snapshot presence in %s", graph_db, exc_info=True)
        return len(nbs)


def _checkpoint_wal(db: Path) -> None:
    """備份前把 WAL 併回主檔,使單檔 read_bytes 備份完整(不漏 -wal 內未 checkpoint 的列)。
    僅對有效 sqlite 檔嘗試;失敗忽略(備份退回原樣)。"""
    if not _is_sqlite_file(db):
        return
    try:
        with closing(sqlite3.connect(db)) as conn:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    except sqlite3.Error:
        logger.warning("Failed to checkpoint WAL for %s", db, exc_info=True)
        print(
            f"[sot_history_migrate] failed wal checkpoint for {db} (continuing)",
            file=sys.stderr,
        )


def migrate_user(user_dir: Path, *, apply: bool) -> MigrationReport:
    """回填單一用戶的合成 SoT 歷史。``apply=False`` 只報告不寫。"""
    user_dir = Path(user_dir)
    cards_db = user_dir / "cards.db"
    report = MigrationReport(user_dir=user_dir, dry_run=not apply)
    report.notebooks = _discover_notebooks(user_dir, cards_db)

    # ── 複習史 ───────────────────────────────────────────────────────────
    states = _load_review_states(cards_db)
    synth_review = [e for s in states for e in synthesize_review_events(s)]
    report.review_events_synthesized = len(synth_review)

    # ── 圖譜史 ───────────────────────────────────────────────────────────
    graph_drafts = []
    links_by_nb: dict[str, list[GraphLink]] = {}
    for nb in report.notebooks:
        graph_path = user_dir / f"graph_{nb}.json"
        if not graph_path.exists():
            continue
        links = _load_links(graph_path)
        links_by_nb[nb] = links
        graph_drafts.extend(synthesize_graph_history_many(links, notebook_id=nb))
    report.graph_events_synthesized = len(graph_drafts)

    # purge 僅限「首次遷移」(marker 未建)。card_id NULL 是 purge 的唯一信號,但它在上線後也
    # 可能命中 word-only fallback 的真實複習(正是本 PR 別處在修的 nil-card-id 類);故只在
    # 上線前的首次遷移清(此時 card_id NULL 必為同步殘渣),之後 re-run 絕不再 purge。
    review_db = user_dir / _REVIEW_DB
    marker = user_dir / _MIGRATED_MARKER
    will_purge = not marker.exists()
    report.review_events_old_purged = _count_review_junk(review_db) if will_purge else 0

    if not apply:
        # dry-run:唯讀回報「會取幾張」初始 snapshot(尚無者才取),不建檔/不改 schema。
        report.graph_snapshots_taken = _notebooks_without_snapshot_ro(
            user_dir / _GRAPH_DB, links_by_nb.keys()
        )
        return report

    # ── 清舊垃圾(就地、只刪 card_id NULL 殘渣,且僅首次遷移)+ 灌合成複習史 ─────────
    # 不整檔 wipe:wipe 會(a)在二次遷移銷毀上線後 iOS 推入的真實事件,(b)unlink 孤兒化 server
    # 開啟中的 inode。改為就地只刪垃圾,真實/合成事件永遠保留,合成靠 event_id 去重補上。
    if will_purge and review_db.exists():
        bak = user_dir / _REVIEW_BAK
        if not bak.exists():
            _checkpoint_wal(review_db)  # 併 WAL,使單檔備份完整
            bak.write_bytes(review_db.read_bytes())
            report.backups.append(bak)
        if _is_sqlite_file(review_db):
            _purge_review_junk(review_db)  # 就地刪垃圾,保留 inode 與真實事件
        else:
            review_db.unlink()  # 非 db 垃圾檔(損毀殘留),直接移除重建
    fresh_review = ReviewEventStore(review_db)
    push_review_events(synth_review, event_store=fresh_review)
    fresh_review.engine.dispose()
    if will_purge:
        marker.write_text("")  # 標記已遷移:後續 re-run 不再 purge card_id NULL

    # ── 灌合成圖譜史(event_id 去重 → 冪等,毋須 wipe)──────────────────
    graph_store = GraphEventStore(user_dir / _GRAPH_DB)
    graph_store.insert_many(graph_drafts)
    graph_store.close()

    # ── 初始合成 snapshot(每 notebook 一張終態整檔 checkpoint)──────────
    # 配 diff 事件即可重建任意時間點;is_synthetic=True 標記為遷移當下的合成基準。
    snap_store = GraphSnapshotStore(user_dir / _GRAPH_DB)
    for nb, links in links_by_nb.items():
        if snap_store.latest(nb) is not None:
            continue  # 已有 snapshot(遷移已跑過)→ 不重複堆疊,保冪等
        snap_store.save(
            nb, [lk.model_dump(mode="json") for lk in links], is_synthetic=True
        )
        report.graph_snapshots_taken += 1
    snap_store.close()

    return report
