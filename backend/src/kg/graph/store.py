"""JSON-based graph storage: the :class:`GraphStore` facade."""

from __future__ import annotations

import logging
import threading
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

from .candidates import _CandidatesMixin
from .lifecycle import _LifecycleMixin
from .links import _LinksMixin
from .models import CandidatePair, GraphLink
from .persistence import _PersistenceMixin

if TYPE_CHECKING:
    from ..graph_event_log import GraphEventDraft, GraphEventStore, GraphSnapshotStore

logger = logging.getLogger(__name__)


class GraphStore(_PersistenceMixin, _LinksMixin, _CandidatesMixin, _LifecycleMixin):
    """JSON-based graph storage.

    Locking strategy (fine-grained):
    - The lock protects in-memory state only (_links, _candidates, _candidate_set,
      _from_index, _to_index, _blocked_pairs).
    - Disk I/O (_atomic_json_write) always happens *outside* the lock to avoid
      blocking readers during slow fsync operations.
    - Pattern for every write method:
        1. Acquire lock -> mutate memory -> take snapshot -> release lock
        2. Call _atomic_json_write(snapshot) -- no lock held
    - pop_* methods release _lock during their flush, so a per-collection
      pop lock (_pending_judge_pop_lock / _candidates_pop_lock) serialises
      concurrent pops to keep exactly-once semantics. See __init__.
    - _candidate_set is a canonical set[tuple[str,str]] (normalised: smaller id
      first) kept in sync with _candidates for O(1) duplicate detection.

    Behaviour is composed from focused mixins: :class:`_PersistenceMixin`
    (disk I/O), :class:`_LinksMixin` (link CRUD + blocked pairs), and
    :class:`_CandidatesMixin` (candidate pairs + pending judge).
    """

    def __init__(
        self,
        links_path: Path,
        candidates_path: Path,
        blocked_path: Path | None = None,
        pending_judge_path: Path | None = None,
        *,
        event_store: GraphEventStore | None = None,
        event_store_provider: Callable[[], GraphEventStore] | None = None,
        snapshot_store: GraphSnapshotStore | None = None,
        snapshot_store_provider: Callable[[], GraphSnapshotStore] | None = None,
        event_notebook_id: str = "default",
    ) -> None:
        self.links_path = links_path
        self.candidates_path = candidates_path
        self.blocked_path = blocked_path
        self.pending_judge_path = pending_judge_path
        # Append-only 變動帳本(Phase 6)。None = 不記錄(既有用法 / 測試零影響)。
        # 每個 mutation 成功改檔後 emit 一筆 diff 事件,is_synthetic=False 區隔合成過去。
        # ``event_store_provider`` 優先(生產用):每次 emit 透過 service_factories 快取
        # 重新解析,避免長期持有被 LRU 逐出的 store 而靜默丟事件;``event_store`` 為直接注入
        # (測試用)。
        self._event_store = event_store
        self._event_store_provider = event_store_provider
        self._snapshot_store = snapshot_store
        self._snapshot_store_provider = snapshot_store_provider
        self._event_notebook_id = event_notebook_id
        self._lock = threading.Lock()
        # Per-file write locks: serialise concurrent _atomic_json_write calls
        # so that tmp->bak->replace sequence is always consistent on disk.
        self._links_write_lock = threading.Lock()
        self._candidates_write_lock = threading.Lock()
        self._blocked_write_lock = threading.Lock()
        self._pending_judge_write_lock = threading.Lock()
        # Pop serialisation locks: pop_* releases _lock during its (slow)
        # flush, so without this two concurrent pop_* calls on the SAME
        # instance could each observe the not-yet-removed items and return
        # them twice. These locks make pop atomic per item-set (exactly-once)
        # while keeping disk I/O off _lock. Distinct from _*_write_lock,
        # which _flush_* takes -- reusing it would deadlock (non-reentrant).
        self._pending_judge_pop_lock = threading.Lock()
        self._candidates_pop_lock = threading.Lock()
        self._links: dict[str, GraphLink] = {}
        # Every link id this instance has ever held (loaded or created). Used
        # by _flush_links to tell "deleted by me" (drop) from "added by another
        # instance" (preserve) when merging with the on-disk file.
        self._known_link_ids: set[str] = set()
        self._candidates: list[CandidatePair] = []
        self._candidate_set: set[tuple[str, str]] = set()  # normalised pairs
        # Every candidate pair this instance has ever held (loaded or added).
        # Mirrors _known_link_ids: lets _flush_candidates tell "removed/popped
        # by me" (drop) from "added by another instance" (preserve) on merge.
        self._known_candidate_pairs: set[tuple[str, str]] = set()
        self._blocked_pairs: set[tuple[str, str]] = set()
        # Every blocked pair this instance has ever held (loaded or blocked).
        # Mirrors _known_link_ids: lets _flush_blocked tell "unblocked by me"
        # (drop) from "blocked by another instance" (preserve) when merging.
        self._known_blocked_pairs: set[tuple[str, str]] = set()
        self._pending_judge: set[str] = set()
        # Every pending-judge id this instance has ever held. Mirrors
        # _known_link_ids: _flush_pending_judge uses it to tell "popped/removed
        # by me" (drop) from "added by another instance" (preserve) on merge.
        self._known_pending_judge: set[str] = set()
        self._from_index: dict[str, set[str]] = {}  # card_id -> set of link_ids
        self._to_index: dict[str, set[str]] = {}    # card_id -> set of link_ids
        self._load()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _index_link(self, link: GraphLink) -> None:
        self._from_index.setdefault(link.from_id, set()).add(link.id)
        self._to_index.setdefault(link.to_id, set()).add(link.id)
        # Register so a later _flush_links merge treats this id as managed
        # by this instance (a subsequent delete is honoured, not resurrected).
        self._known_link_ids.add(link.id)

    def _unindex_link(self, link: GraphLink) -> None:
        self._from_index.get(link.from_id, set()).discard(link.id)
        self._to_index.get(link.to_id, set()).discard(link.id)

    def _rebuild_index(self) -> None:
        self._from_index = {}
        self._to_index = {}
        for link in self._links.values():
            self._index_link(link)

    def _rebuild_candidate_set(self) -> None:
        self._candidate_set = {
            self._normalize_pair(c.from_id, c.to_id)
            for c in self._candidates
        }

    def _resolve_event_store(self) -> GraphEventStore | None:
        """取 live event_store。provider(生產)優先,每次重解析以避開 LRU 逐出後的死引用;
        否則用直接注入的 store(測試)。"""
        if self._event_store_provider is not None:
            return self._event_store_provider()
        return self._event_store

    def _resolve_snapshot_store(self) -> GraphSnapshotStore | None:
        if self._snapshot_store_provider is not None:
            return self._snapshot_store_provider()
        return self._snapshot_store

    def _build_graph_event_draft(
        self,
        event_type: str,
        *,
        link_id: str,
        from_id: str,
        to_id: str,
        kind: str,
        source: str,
        confidence_before: float | None = None,
        confidence_after: float | None = None,
        status_before: str | None = None,
        status_after: str | None = None,
        reason: str | None = None,
    ) -> GraphEventDraft:
        """組一筆真實(``is_synthetic=False``)變動事件草稿。``event_id`` 用 uuid4(真實事件
        非冪等重放,每筆新 id);``occurred_at`` 為 mutation 當下;``reason`` 記 link 當前理由
        (add=新、update=改後);status-only 轉移無「為何」依據,沿用合成史哲學留 None。"""
        from ..graph_event_log import GraphEventDraft

        return GraphEventDraft(
            event_id=uuid.uuid4().hex,
            event_type=event_type,
            link_id=link_id,
            from_id=from_id,
            to_id=to_id,
            kind=kind,
            confidence_before=confidence_before,
            confidence_after=confidence_after,
            reason=reason,
            status_before=status_before,
            status_after=status_after,
            source=source,
            notebook_id=self._event_notebook_id,
            occurred_at=datetime.now(UTC),
            is_synthetic=False,
        )

    def _emit_graph_events(
        self,
        drafts: list[GraphEventDraft],
        *,
        links_snapshot: list[dict] | None = None,
    ) -> None:
        """批次 append。必須在 _lock 外、改檔成功後呼叫。一筆 logical mutation(含 batch)
        只開一筆 insert_many 交易,避免逐 link 各取寫鎖。帳本是研究料,非寫入關鍵路徑:
        emit 失敗只記 log,絕不冒泡打斷圖譜寫入。"""
        if not drafts:
            return
        try:
            # provider() 解析也包進 try:provider 會開 SQLite(disk-full / corrupt /
            # 開檔錯誤皆可能拋),不可冒泡打斷圖譜寫入。
            store = self._resolve_event_store()
            if store is None:
                if links_snapshot is None:
                    return
            else:
                store.insert_many(drafts)
            if links_snapshot is not None:
                snap_store = self._resolve_snapshot_store()
                if snap_store is not None:
                    snap_store.maybe_save_periodic(self._event_notebook_id, links_snapshot)
        except Exception:  # noqa: BLE001 — 帳本失敗不得打斷圖譜寫入
            logger.warning(
                "graph event emit failed (%d drafts, first=%s)",
                len(drafts), drafts[0].event_type, exc_info=True,
            )

    def _emit_graph_event(
        self,
        event_type: str,
        *,
        links_snapshot: list[dict] | None = None,
        link_id: str,
        from_id: str,
        to_id: str,
        kind: str,
        source: str,
        confidence_before: float | None = None,
        confidence_after: float | None = None,
        status_before: str | None = None,
        status_after: str | None = None,
        reason: str | None = None,
    ) -> None:
        """單筆便利 emit(內部仍走 batch 路徑)。"""
        if self._event_store_provider is None and self._event_store is None:
            if self._snapshot_store_provider is None and self._snapshot_store is None:
                return
        self._emit_graph_events([
            self._build_graph_event_draft(
                event_type, link_id=link_id, from_id=from_id, to_id=to_id, kind=kind,
                source=source, confidence_before=confidence_before,
                confidence_after=confidence_after, status_before=status_before,
                status_after=status_after, reason=reason,
            )
        ], links_snapshot=links_snapshot)

    # Link kinds removed from the enum; silently drop on load.
    _RETIRED_KINDS: ClassVar[frozenset[str]] = frozenset({"confusable"})

    @staticmethod
    def _normalize_pair(a: str, b: str) -> tuple[str, str]:
        return tuple(sorted([a, b]))  # type: ignore[return-value]

    def _load(self) -> None:
        if self.blocked_path and self.blocked_path.exists():
            data = self._read_json_list(self.blocked_path)
            self._blocked_pairs = {tuple(pair) for pair in data}  # type: ignore[misc]
            self._known_blocked_pairs |= self._blocked_pairs
        if self.links_path.exists():
            data = self._read_json_list(self.links_path)
            dirty = False
            for lk in data:
                if lk.get("kind") in self._RETIRED_KINDS:
                    dirty = True
                    continue
                # Migrate rejected -> blocked
                if lk.get("status") == "rejected":
                    dirty = True
                    pair = self._normalize_pair(lk["from_id"], lk["to_id"])
                    self._blocked_pairs.add(pair)
                    self._known_blocked_pairs.add(pair)
                    continue
                link = GraphLink.model_validate(lk)
                self._links[link.id] = link
                self._known_link_ids.add(link.id)
            if dirty:
                self._save_links()
                self._save_blocked()
        if self.candidates_path.exists():
            data = self._read_json_list(self.candidates_path)
            self._candidates = [CandidatePair.model_validate(c) for c in data]
            for c in self._candidates:
                self._known_candidate_pairs.add(
                    self._normalize_pair(c.from_id, c.to_id)
                )
        # Load pending_judge
        if self.pending_judge_path and self.pending_judge_path.exists():
            pj_data = self._read_json_list(self.pending_judge_path)
            if isinstance(pj_data, list):
                self._pending_judge = {x for x in pj_data if isinstance(x, str)}
                self._known_pending_judge |= self._pending_judge
            else:
                logger.warning("Invalid pending_judge format, resetting: %s", type(pj_data).__name__)
                self._pending_judge = set()
        # Migrate old candidates -> pending_judge (only when pending_judge_path is set)
        if self.pending_judge_path and self._candidates:
            migrated_ids = {c.from_id for c in self._candidates}
            self._pending_judge.update(migrated_ids)
            self._known_pending_judge |= migrated_ids
            self._candidates.clear()
            self._candidate_set.clear()
            self._save_candidates()
            self._save_pending_judge()
        self._rebuild_index()
        self._rebuild_candidate_set()

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def deprecate_links_for(self, card_id: str, *, source: str = "auto") -> int:
        """Deprecate all active links involving a card. Returns count of deprecated links."""
        affected: list[GraphLink] = []
        with self._lock:
            link_ids = self._from_index.get(card_id, set()) | self._to_index.get(card_id, set())
            for lid in list(link_ids):
                lk = self._links.get(lid)
                if lk and lk.status == "active":
                    lk.status = "deprecated"
                    affected.append(lk.model_copy())
            snapshot = self._links_to_serializable() if affected else None
        if snapshot is not None:
            self._flush_links(snapshot)
            self._emit_graph_events([
                self._build_graph_event_draft(
                    "link_deprecated", link_id=lk.id, from_id=lk.from_id, to_id=lk.to_id,
                    kind=str(lk.kind), source=source, confidence_before=lk.confidence,
                    confidence_after=lk.confidence, status_before="active", status_after="deprecated",
                )
                for lk in affected
            ], links_snapshot=snapshot)
        return len(affected)

    def restore_links_for(self, card_id: str, cards_store, *, source: str = "auto") -> int:
        """Restore deprecated links for a card, only if the other end is alive."""
        affected: list[GraphLink] = []
        with self._lock:
            link_ids = self._from_index.get(card_id, set()) | self._to_index.get(card_id, set())
            for lid in list(link_ids):
                lk = self._links.get(lid)
                if lk and lk.status == "deprecated":
                    other_id = lk.to_id if lk.from_id == card_id else lk.from_id
                    other_card = cards_store.get(other_id)
                    if other_card and not other_card.is_deleted and not other_card.is_archived:
                        lk.status = "active"
                        affected.append(lk.model_copy())
            snapshot = self._links_to_serializable() if affected else None
        if snapshot is not None:
            self._flush_links(snapshot)
            self._emit_graph_events([
                self._build_graph_event_draft(
                    "link_restored", link_id=lk.id, from_id=lk.from_id, to_id=lk.to_id,
                    kind=str(lk.kind), source=source, confidence_before=lk.confidence,
                    confidence_after=lk.confidence, status_before="deprecated", status_after="active",
                )
                for lk in affected
            ], links_snapshot=snapshot)
        return len(affected)

    def cleanup_for_card(self, card_id: str, *, remove_blocked: bool = False, source: str = "auto") -> dict:
        """Deprecate links + remove candidates + remove pending_judge (+ blocked pairs if deleting)."""
        dep_count = self.deprecate_links_for(card_id, source=source)
        cand_count = self.remove_candidates_for(card_id)
        pj_count = self.remove_pending_judge_for(card_id)
        if remove_blocked:
            self.remove_blocked_pairs_for(card_id)
        return {"deprecated": dep_count, "candidates_removed": cand_count, "pending_judge_removed": pj_count}
