"""Graph storage for card relationships."""

from __future__ import annotations

import json
import threading
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field


class LinkKind(StrEnum):
    """Types of relationships between cards."""

    CONTRASTS_WITH = "contrasts_with"
    SHARES_USAGE = "shares_usage"


LINK_LABELS: dict[LinkKind, str] = {
    LinkKind.CONTRASTS_WITH: "對比",
    LinkKind.SHARES_USAGE: "相關",
}


class GraphLink(BaseModel):
    """A relationship between two cards."""

    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    from_id: str
    to_id: str
    kind: LinkKind
    confidence: float
    reason: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    status: Literal["candidate", "active", "deprecated", "hidden"] = "active"


class CandidatePair(BaseModel):
    """A pending pair awaiting LLM judgement."""

    from_id: str
    to_id: str
    similarity: float  # embedding similarity score
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class GraphStore:
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
            self._pending_judge = set(pj_data)
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

    @staticmethod
    def _atomic_json_write(path: Path, data: Any, *, indent: int | None = 2) -> None:
        """Atomic JSON write: tmp -> bak -> replace."""
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=indent, ensure_ascii=False))
        if path.exists():
            path.replace(path.with_suffix(".json.bak"))
        tmp.replace(path)

    # Snapshot helpers -- call inside lock, return serialisable data
    def _links_to_serializable(self) -> list[dict]:
        return [lk.model_dump(mode="json") for lk in self._links.values()]

    def _candidates_to_serializable(self) -> list[dict]:
        return [c.model_dump(mode="json") for c in self._candidates]

    def _blocked_to_serializable(self) -> list[list[str]]:
        return [list(pair) for pair in self._blocked_pairs]

    # Per-file serialised write helpers.
    # These acquire the file-level write lock so concurrent threads writing to
    # the same file don't race on the tmp->bak->replace sequence.
    def _flush_links(self, snapshot: list[dict]) -> None:
        with self._links_write_lock:
            self._atomic_json_write(self.links_path, snapshot)

    def _flush_candidates(self, snapshot: list[dict]) -> None:
        with self._candidates_write_lock:
            self._atomic_json_write(self.candidates_path, snapshot)

    def _flush_blocked(self, snapshot: list[list[str]]) -> None:
        if self.blocked_path is None:
            return
        with self._blocked_write_lock:
            self._atomic_json_write(self.blocked_path, snapshot, indent=None)

    # These internal _save_* are still used from _load (dirty migration path)
    # where we are NOT inside a concurrent context yet.
    def _save_links(self) -> None:
        self._flush_links(self._links_to_serializable())

    def _save_candidates(self) -> None:
        self._flush_candidates(self._candidates_to_serializable())

    def _save_blocked(self) -> None:
        if self.blocked_path is None:
            return
        self._flush_blocked(self._blocked_to_serializable())

    def _flush_pending_judge(self, snapshot: list[str]) -> None:
        if self.pending_judge_path is None:
            return
        with self._pending_judge_write_lock:
            self._atomic_json_write(self.pending_judge_path, snapshot, indent=None)

    def _save_pending_judge(self) -> None:
        if self.pending_judge_path is None:
            return
        self._flush_pending_judge(list(self._pending_judge))

    # ------------------------------------------------------------------
    # Links
    # ------------------------------------------------------------------

    def add_link(
        self,
        from_id: str,
        to_id: str,
        kind: LinkKind,
        confidence: float,
        reason: str,
    ) -> GraphLink:
        """Create and store a new link. Disk write happens outside the lock."""
        link = GraphLink(
            from_id=from_id,
            to_id=to_id,
            kind=kind,
            confidence=confidence,
            reason=reason,
        )
        with self._lock:
            self._links[link.id] = link
            self._index_link(link)
            snapshot = self._links_to_serializable()
        self._flush_links(snapshot)
        return link

    def batch_add_links(
        self,
        links: list[tuple[str, str, "LinkKind", float, str]],
    ) -> list[GraphLink]:
        """Create multiple links with a single disk write. Returns created links."""
        created: list[GraphLink] = []
        with self._lock:
            for from_id, to_id, kind, confidence, reason in links:
                link = GraphLink(
                    from_id=from_id,
                    to_id=to_id,
                    kind=kind,
                    confidence=confidence,
                    reason=reason,
                )
                self._links[link.id] = link
                self._index_link(link)
                created.append(link)
            snapshot = self._links_to_serializable() if created else None
        if snapshot is not None:
            self._flush_links(snapshot)
        return created

    def get_links_for(self, card_id: str) -> list[GraphLink]:
        """Get all active and hidden links involving a card."""
        link_ids = self._from_index.get(card_id, set()) | self._to_index.get(card_id, set())
        return [self._links[lid] for lid in link_ids if self._links[lid].status in ("active", "hidden")]

    def _has_link_unlocked(self, id_a: str, id_b: str) -> bool:
        """Check link existence without acquiring the lock (internal use)."""
        if self._normalize_pair(id_a, id_b) in self._blocked_pairs:
            return True
        candidates = self._from_index.get(id_a, set()) | self._to_index.get(id_a, set())
        for lid in candidates:
            lk = self._links[lid]
            if lk.status not in ("active", "hidden"):
                continue
            if (lk.from_id == id_a and lk.to_id == id_b) or (
                lk.from_id == id_b and lk.to_id == id_a
            ):
                return True
        return False

    def has_link(self, id_a: str, id_b: str) -> bool:
        """Check if a link exists between two cards (active or rejected counts)."""
        return self._has_link_unlocked(id_a, id_b)

    def find_link_between(self, id_a: str, id_b: str) -> GraphLink | None:
        """Find active or hidden link between two cards (bidirectional). Returns None for deprecated/absent."""
        candidates = self._from_index.get(id_a, set()) | self._to_index.get(id_a, set())
        for lid in candidates:
            lk = self._links[lid]
            if lk.status not in ("active", "hidden"):
                continue
            if (lk.from_id == id_a and lk.to_id == id_b) or (
                lk.from_id == id_b and lk.to_id == id_a
            ):
                return lk
        return None

    def get_link(self, link_id: str) -> GraphLink | None:
        """Return a link by ID, or None if not found."""
        return self._links.get(link_id)

    def update_link(self, link_id: str, **attrs: Any) -> GraphLink:
        """Update attributes of an existing link and persist."""
        ALLOWED = {"status", "kind", "confidence", "reason"}
        with self._lock:
            lk = self._links.get(link_id)
            if lk is None:
                raise KeyError(link_id)
            for key, value in attrs.items():
                if key not in ALLOWED:
                    raise ValueError(f"Cannot update attribute: {key}")
                setattr(lk, key, value)
            snapshot = self._links_to_serializable()
        self._flush_links(snapshot)
        return lk

    def hide_link(self, link_id: str) -> None:
        """Set link status to hidden. Raises KeyError if not found."""
        with self._lock:
            lk = self._links.get(link_id)
            if lk is None:
                raise KeyError(link_id)
            lk.status = "hidden"
            snapshot = self._links_to_serializable()
        self._flush_links(snapshot)

    def unhide_link(self, link_id: str) -> None:
        """Set link status back to active. Raises KeyError if not found."""
        with self._lock:
            lk = self._links.get(link_id)
            if lk is None:
                raise KeyError(link_id)
            lk.status = "active"
            snapshot = self._links_to_serializable()
        self._flush_links(snapshot)

    def hard_delete_link(self, link_id: str) -> tuple[str, str]:
        """Delete a link and add the pair to blocked list. Returns (from_id, to_id)."""
        with self._lock:
            lk = self._links.get(link_id)
            if lk is None:
                raise KeyError(link_id)
            from_id, to_id = lk.from_id, lk.to_id
            self._unindex_link(lk)
            del self._links[link_id]
            self._blocked_pairs.add(self._normalize_pair(from_id, to_id))
            links_snapshot = self._links_to_serializable()
            blocked_snapshot = self._blocked_to_serializable()
        self._flush_links(links_snapshot)
        self._flush_blocked(blocked_snapshot)
        return (from_id, to_id)

    def is_blocked(self, from_id: str, to_id: str) -> bool:
        """Check if a pair is blocked."""
        return self._normalize_pair(from_id, to_id) in self._blocked_pairs

    def remove_blocked_pairs_for(self, card_id: str) -> None:
        """Remove all blocked pairs involving a card."""
        with self._lock:
            self._blocked_pairs = {
                pair for pair in self._blocked_pairs
                if card_id not in pair
            }
            snapshot = self._blocked_to_serializable()
        self._flush_blocked(snapshot)

    def unblock_pair(self, from_id: str, to_id: str) -> None:
        """Remove a specific blocked pair."""
        with self._lock:
            self._blocked_pairs.discard(self._normalize_pair(from_id, to_id))
            snapshot = self._blocked_to_serializable()
        self._flush_blocked(snapshot)

    def all_links(self) -> Iterator[GraphLink]:
        yield from self._links.values()

    def link_count(self) -> int:
        return sum(1 for lk in self._links.values() if lk.status == "active")

    # ------------------------------------------------------------------
    # Candidates
    # ------------------------------------------------------------------

    def add_candidate(self, from_id: str, to_id: str, similarity: float) -> None:
        """Add a candidate pair for LLM judgement.

        Uses _candidate_set for O(1) duplicate detection. Disk write outside lock.
        """
        norm = self._normalize_pair(from_id, to_id)
        with self._lock:
            # Skip if already exists or link exists
            if self._has_link_unlocked(from_id, to_id):
                return
            if norm in self._candidate_set:
                return
            self._candidates.append(CandidatePair(from_id=from_id, to_id=to_id, similarity=similarity))
            self._candidate_set.add(norm)
            snapshot = self._candidates_to_serializable()
        self._flush_candidates(snapshot)

    def batch_add_candidates(self, items: list[tuple[str, str, float]]) -> int:
        """Add multiple candidate pairs with a single disk write. Returns count added."""
        with self._lock:
            added = 0
            for from_id, to_id, similarity in items:
                if self._has_link_unlocked(from_id, to_id):
                    continue
                norm = self._normalize_pair(from_id, to_id)
                if norm in self._candidate_set:
                    continue
                self._candidates.append(CandidatePair(from_id=from_id, to_id=to_id, similarity=similarity))
                self._candidate_set.add(norm)
                added += 1
            snapshot = self._candidates_to_serializable() if added else None
        if snapshot is not None:
            self._flush_candidates(snapshot)
        return added

    def pop_candidates(self) -> list[CandidatePair]:
        """Get and clear all pending candidates."""
        with self._lock:
            result = self._candidates[:]
            self._candidates.clear()
            self._candidate_set.clear()
            snapshot = self._candidates_to_serializable()
        self._flush_candidates(snapshot)
        return result

    def requeue_candidates(self, candidates: list[CandidatePair]) -> None:
        """Push unprocessed candidates back onto the list."""
        with self._lock:
            for c in candidates:
                self._candidates.append(c)
                self._candidate_set.add(self._normalize_pair(c.from_id, c.to_id))
            snapshot = self._candidates_to_serializable()
        self._flush_candidates(snapshot)

    def candidate_count(self) -> int:
        return len(self._candidates) + len(self._pending_judge)

    # ------------------------------------------------------------------
    # Pending Judge
    # ------------------------------------------------------------------

    def add_pending_judge(self, card_ids: list[str] | str) -> None:
        """Add card ID(s) to the pending judge set. Dedup by set semantics."""
        if isinstance(card_ids, str):
            card_ids = [card_ids]
        with self._lock:
            before = len(self._pending_judge)
            self._pending_judge.update(card_ids)
            if len(self._pending_judge) == before:
                return
            snapshot = sorted(self._pending_judge)
        self._flush_pending_judge(snapshot)

    def pop_pending_judge(self) -> list[str]:
        """Get and clear all pending judge card IDs. Returns sorted list."""
        with self._lock:
            result = sorted(self._pending_judge)
            self._pending_judge.clear()
        self._flush_pending_judge([])
        return result

    def remove_pending_judge_for(self, card_id: str) -> int:
        """Remove a specific card ID from pending judge. Returns 1 if removed, 0 otherwise."""
        with self._lock:
            if card_id not in self._pending_judge:
                return 0
            self._pending_judge.discard(card_id)
            snapshot = list(self._pending_judge)
        self._flush_pending_judge(snapshot)
        return 1

    def pending_judge_count(self) -> int:
        return len(self._pending_judge)

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

    def remove_candidates_for(self, card_id: str) -> int:
        """Remove all pending candidates involving a card. Returns count removed."""
        with self._lock:
            before = len(self._candidates)
            self._candidates = [
                c for c in self._candidates
                if c.from_id != card_id and c.to_id != card_id
            ]
            removed = before - len(self._candidates)
            if removed:
                self._rebuild_candidate_set()
            snapshot = self._candidates_to_serializable() if removed else None
        if snapshot is not None:
            self._flush_candidates(snapshot)
        return removed

    def cleanup_for_card(self, card_id: str, *, remove_blocked: bool = False) -> dict:
        """Deprecate links + remove candidates + remove pending_judge (+ blocked pairs if deleting)."""
        dep_count = self.deprecate_links_for(card_id)
        cand_count = self.remove_candidates_for(card_id)
        pj_count = self.remove_pending_judge_for(card_id)
        if remove_blocked:
            self.remove_blocked_pairs_for(card_id)
        return {"deprecated": dep_count, "candidates_removed": cand_count, "pending_judge_removed": pj_count}
