"""JSON-based graph storage: the :class:`GraphStore` facade."""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import ClassVar

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

    # Link kinds removed from the enum; silently drop on load.
    _RETIRED_KINDS: ClassVar[frozenset[str]] = frozenset({"confusable"})

    @staticmethod
    def _normalize_pair(a: str, b: str) -> tuple[str, str]:
        return tuple(sorted([a, b]))  # type: ignore[return-value]

    def _load(self) -> None:
        if self.blocked_path and self.blocked_path.exists():
            data = json.loads(self.blocked_path.read_text())
            self._blocked_pairs = {tuple(pair) for pair in data}  # type: ignore[misc]
            self._known_blocked_pairs |= self._blocked_pairs
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
            data = json.loads(self.candidates_path.read_text())
            self._candidates = [CandidatePair.model_validate(c) for c in data]
            for c in self._candidates:
                self._known_candidate_pairs.add(
                    self._normalize_pair(c.from_id, c.to_id)
                )
        # Load pending_judge
        if self.pending_judge_path and self.pending_judge_path.exists():
            pj_data = json.loads(self.pending_judge_path.read_text())
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
