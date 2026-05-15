"""JSON-based graph storage: the :class:`GraphStore` facade."""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

from .candidates import _CandidatesMixin
from .links import _LinksMixin
from .models import CandidatePair, GraphLink
from .persistence import _PersistenceMixin

logger = logging.getLogger(__name__)


class GraphStore(_PersistenceMixin, _LinksMixin, _CandidatesMixin):
    """JSON-based graph storage.

    Locking strategy (fine-grained):
    - The lock protects in-memory state only (_links, _candidates, _candidate_set,
      _from_index, _to_index, _blocked_pairs).
    - Disk I/O (_atomic_json_write) always happens *outside* the lock to avoid
      blocking readers during slow fsync operations.
    - Pattern for every write method:
        1. Acquire lock -> mutate memory -> take snapshot -> release lock
        2. Call _atomic_json_write(snapshot) -- no lock held
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
    ) -> None:
        self.links_path = links_path
        self.candidates_path = candidates_path
        self.blocked_path = blocked_path
        self.pending_judge_path = pending_judge_path
        self._lock = threading.Lock()
        # Per-file write locks: serialise concurrent _atomic_json_write calls
        # so that tmp->bak->replace sequence is always consistent on disk.
        self._links_write_lock = threading.Lock()
        self._candidates_write_lock = threading.Lock()
        self._blocked_write_lock = threading.Lock()
        self._pending_judge_write_lock = threading.Lock()
        self._links: dict[str, GraphLink] = {}
        self._candidates: list[CandidatePair] = []
        self._candidate_set: set[tuple[str, str]] = set()  # normalised pairs
        self._blocked_pairs: set[tuple[str, str]] = set()
        self._pending_judge: set[str] = set()
        self._from_index: dict[str, set[str]] = {}  # card_id -> set of link_ids
        self._to_index: dict[str, set[str]] = {}    # card_id -> set of link_ids
        self._load()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _index_link(self, link: GraphLink) -> None:
        self._from_index.setdefault(link.from_id, set()).add(link.id)
        self._to_index.setdefault(link.to_id, set()).add(link.id)

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

    # Link kinds removed from the enum; silently drop on load.
    _RETIRED_KINDS: set[str] = {"confusable"}

    @staticmethod
    def _normalize_pair(a: str, b: str) -> tuple[str, str]:
        return tuple(sorted([a, b]))  # type: ignore[return-value]

    def _load(self) -> None:
        if self.blocked_path and self.blocked_path.exists():
            data = json.loads(self.blocked_path.read_text())
            self._blocked_pairs = {tuple(pair) for pair in data}  # type: ignore[misc]
        if self.links_path.exists():
            data = json.loads(self.links_path.read_text())
            dirty = False
            for lk in data:
                if lk.get("kind") in self._RETIRED_KINDS:
                    dirty = True
                    continue
                # Migrate rejected -> blocked
                if lk.get("status") == "rejected":
                    dirty = True
                    self._blocked_pairs.add(
                        self._normalize_pair(lk["from_id"], lk["to_id"])
                    )
                    continue
                link = GraphLink.model_validate(lk)
                self._links[link.id] = link
            if dirty:
                self._save_links()
                self._save_blocked()
        if self.candidates_path.exists():
            data = json.loads(self.candidates_path.read_text())
            self._candidates = [CandidatePair.model_validate(c) for c in data]
        # Load pending_judge
        if self.pending_judge_path and self.pending_judge_path.exists():
            pj_data = json.loads(self.pending_judge_path.read_text())
            if isinstance(pj_data, list):
                self._pending_judge = {x for x in pj_data if isinstance(x, str)}
            else:
                logger.warning("Invalid pending_judge format, resetting: %s", type(pj_data).__name__)
                self._pending_judge = set()
        # Migrate old candidates -> pending_judge (only when pending_judge_path is set)
        if self.pending_judge_path and self._candidates:
            migrated_ids = {c.from_id for c in self._candidates}
            self._pending_judge.update(migrated_ids)
            self._candidates.clear()
            self._candidate_set.clear()
            self._save_candidates()
            self._save_pending_judge()
        self._rebuild_index()
        self._rebuild_candidate_set()

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def deprecate_links_for(self, card_id: str) -> int:
        """Deprecate all active links involving a card. Returns count of deprecated links."""
        with self._lock:
            link_ids = self._from_index.get(card_id, set()) | self._to_index.get(card_id, set())
            count = 0
            for lid in list(link_ids):
                lk = self._links.get(lid)
                if lk and lk.status == "active":
                    lk.status = "deprecated"
                    count += 1
            snapshot = self._links_to_serializable() if count else None
        if snapshot is not None:
            self._flush_links(snapshot)
        return count

    def restore_links_for(self, card_id: str, cards_store) -> int:
        """Restore deprecated links for a card, only if the other end is alive."""
        with self._lock:
            link_ids = self._from_index.get(card_id, set()) | self._to_index.get(card_id, set())
            count = 0
            for lid in list(link_ids):
                lk = self._links.get(lid)
                if lk and lk.status == "deprecated":
                    other_id = lk.to_id if lk.from_id == card_id else lk.from_id
                    other_card = cards_store.get(other_id)
                    if other_card and not other_card.is_deleted and not other_card.is_archived:
                        lk.status = "active"
                        count += 1
            snapshot = self._links_to_serializable() if count else None
        if snapshot is not None:
            self._flush_links(snapshot)
        return count

    def cleanup_for_card(self, card_id: str, *, remove_blocked: bool = False) -> dict:
        """Deprecate links + remove candidates + remove pending_judge (+ blocked pairs if deleting)."""
        dep_count = self.deprecate_links_for(card_id)
        cand_count = self.remove_candidates_for(card_id)
        pj_count = self.remove_pending_judge_for(card_id)
        if remove_blocked:
            self.remove_blocked_pairs_for(card_id)
        return {"deprecated": dep_count, "candidates_removed": cand_count, "pending_judge_removed": pj_count}
