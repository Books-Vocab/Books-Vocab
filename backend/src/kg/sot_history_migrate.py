"""sot_history_migrate.py — 一次性把單一用戶資料夾回填成合成 SoT 歷史帳本。

上線前用戶資料只有「當前態」:cards.db 存複習聚合(無逐筆事件)、graph_{nb}.json 存 link
終態(無變動歷史),而舊 review_events.db 多是 card_id NULL 的同步殘渣。本遷移:

1. **清舊垃圾** — 備份(只一次,保住真原始檔)後 wipe review_events.db。
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

import sqlite3
from contextlib import closing
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .demo_review_synth import CardReviewState, synthesize_review_events
from .graph.models import GraphLink
from .graph_event_log import GraphEventStore, GraphSnapshotStore
from .graph_history_synth import synthesize_graph_history_many
from .review_events import ReviewEventStore, pull_review_events, push_review_events

_REVIEW_DB = "review_events.db"
_GRAPH_DB = "graph_events.db"
_REVIEW_BAK = "review_events.db.premigration.bak"


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
        return []
    rows = raw if isinstance(raw, list) else list(raw.values()) if isinstance(raw, dict) else []
    links: list[GraphLink] = []
    for row in rows:
        try:
            links.append(GraphLink.model_validate(row))
        except Exception:  # noqa: BLE001 — 跳過畸形/退役 kind 的 link
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

    # 既有舊事件數(報告 purge 量)。dry-run 也照算供決策。
    review_db = user_dir / _REVIEW_DB
    if review_db.exists():
        try:
            existing = ReviewEventStore(review_db)
            old, _ = pull_review_events(since=None, event_store=existing)
            report.review_events_old_purged = len(old)
            existing.engine.dispose()
        except Exception:  # noqa: BLE001 — 損毀/非 db 舊檔仍要備份後 wipe,計 0 purged
            report.review_events_old_purged = 0

    if not apply:
        # dry-run:回報「會取幾張」初始 snapshot(尚無者才取)。
        if (user_dir / _GRAPH_DB).exists():
            probe = GraphSnapshotStore(user_dir / _GRAPH_DB)
            report.graph_snapshots_taken = sum(
                1 for nb in links_by_nb if probe.latest(nb) is None
            )
            probe.close()
        else:
            report.graph_snapshots_taken = len(links_by_nb)
        return report

    # ── 清舊垃圾(備份只一次,保住真原始檔)+ 灌合成複習史 ──────────────
    if review_db.exists():
        bak = user_dir / _REVIEW_BAK
        if not bak.exists():  # 二次遷移不可用合成 db 覆蓋原始備份
            bak.write_bytes(review_db.read_bytes())
            report.backups.append(bak)
        review_db.unlink()
    fresh_review = ReviewEventStore(review_db)
    push_review_events(synth_review, event_store=fresh_review)
    fresh_review.engine.dispose()

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
