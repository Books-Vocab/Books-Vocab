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
    """JSON-based graph storage."""

    def __init__(self, links_path: Path, candidates_path: Path, blocked_path: Path | None = None) -> None:
        self.links_path = links_path
        self.candidates_path = candidates_path
        self.blocked_path = blocked_path
        self._lock = threading.Lock()
        self._links: dict[str, GraphLink] = {}
        self._candidates: list[CandidatePair] = []
        self._blocked_pairs: set[tuple[str, str]] = set()
        self._from_index: dict[str, set[str]] = {}  # card_id → set of link_ids
        self._to_index: dict[str, set[str]] = {}    # card_id → set of link_ids
        self._load()

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
                # Migrate rejected → blocked
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
        self._rebuild_index()

    @staticmethod
    def _atomic_json_write(path: Path, data: Any, *, indent: int | None = 2) -> None:
        """Atomic JSON write: tmp → bak → replace."""
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=indent, ensure_ascii=False))
        if path.exists():
            path.replace(path.with_suffix(".json.bak"))
        tmp.replace(path)

    def _save_links(self) -> None:
        data = [lk.model_dump(mode="json") for lk in self._links.values()]
        self._atomic_json_write(self.links_path, data)

    def _save_candidates(self) -> None:
        data = [c.model_dump(mode="json") for c in self._candidates]
        self._atomic_json_write(self.candidates_path, data)

    def _save_blocked(self) -> None:
        if self.blocked_path is None:
            return
        data = [list(pair) for pair in self._blocked_pairs]
        self._atomic_json_write(self.blocked_path, data, indent=None)

    # --- Links ---

    def add_link(
        self,
        from_id: str,
        to_id: str,
        kind: LinkKind,
        confidence: float,
        reason: str,
    ) -> GraphLink:
        """Create and store a new link."""
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
            self._save_links()
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
            if created:
                self._save_links()
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
            self._save_links()
        return lk

    def hide_link(self, link_id: str) -> None:
        """Set link status to hidden. Raises KeyError if not found."""
        with self._lock:
            lk = self._links.get(link_id)
            if lk is None:
                raise KeyError(link_id)
            lk.status = "hidden"
            self._save_links()

    def unhide_link(self, link_id: str) -> None:
        """Set link status back to active. Raises KeyError if not found."""
        with self._lock:
            lk = self._links.get(link_id)
            if lk is None:
                raise KeyError(link_id)
            lk.status = "active"
            self._save_links()

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
            self._save_links()
            self._save_blocked()
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
            self._save_blocked()

    def unblock_pair(self, from_id: str, to_id: str) -> None:
        """Remove a specific blocked pair."""
        with self._lock:
            self._blocked_pairs.discard(self._normalize_pair(from_id, to_id))
            self._save_blocked()

    def all_links(self) -> Iterator[GraphLink]:
        yield from self._links.values()

    def link_count(self) -> int:
        return sum(1 for lk in self._links.values() if lk.status == "active")

    # --- Candidates ---

    def add_candidate(self, from_id: str, to_id: str, similarity: float) -> None:
        """Add a candidate pair for LLM judgement."""
        with self._lock:
            # Skip if already exists or link exists
            if self._has_link_unlocked(from_id, to_id):
                return
            for c in self._candidates:
                if (c.from_id == from_id and c.to_id == to_id) or (
                    c.from_id == to_id and c.to_id == from_id
                ):
                    return
            self._candidates.append(CandidatePair(from_id=from_id, to_id=to_id, similarity=similarity))
            self._save_candidates()

    def batch_add_candidates(self, items: list[tuple[str, str, float]]) -> int:
        """Add multiple candidate pairs with a single disk write. Returns count added."""
        with self._lock:
            # Build a set of existing pairs for O(1) lookup
            existing: set[tuple[str, str]] = set()
            for c in self._candidates:
                existing.add((c.from_id, c.to_id))
                existing.add((c.to_id, c.from_id))

            added = 0
            for from_id, to_id, similarity in items:
                if self.has_link(from_id, to_id):
                    continue
                if (from_id, to_id) in existing:
                    continue
                self._candidates.append(CandidatePair(from_id=from_id, to_id=to_id, similarity=similarity))
                existing.add((from_id, to_id))
                existing.add((to_id, from_id))
                added += 1

            if added:
                self._save_candidates()
            return added

    def pop_candidates(self) -> list[CandidatePair]:
        """Get and clear all pending candidates."""
        with self._lock:
            result = self._candidates[:]
            self._candidates.clear()
            self._save_candidates()
        return result

    def requeue_candidates(self, candidates: list[CandidatePair]) -> None:
        """Push unprocessed candidates back onto the list."""
        with self._lock:
            self._candidates.extend(candidates)
            self._save_candidates()

    def candidate_count(self) -> int:
        return len(self._candidates)

    # --- Cleanup ---

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
            if count:
                self._save_links()
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
            if count:
                self._save_links()
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
                self._save_candidates()
        return removed

    # --- Merge ---

    def merge_from(self, source: "GraphStore") -> None:
        """Merge all links and candidates from *source* into this store.

        - Links whose card pair already exists in target are skipped (no duplicates).
        - After merge, source is emptied and its files are saved (now empty).
        """
        # Acquire source lock first, then target lock (fixed order prevents deadlock).
        with source._lock:
            with self._lock:
                # Merge links
                for lk in list(source._links.values()):
                    if not self._has_link_unlocked(lk.from_id, lk.to_id):
                        self._links[lk.id] = lk
                        self._index_link(lk)

                # Merge candidates — skip pairs that already have a link or candidate in target
                existing_pairs: set[tuple[str, str]] = set()
                for c in self._candidates:
                    existing_pairs.add((c.from_id, c.to_id))
                    existing_pairs.add((c.to_id, c.from_id))

                for c in source._candidates:
                    if (c.from_id, c.to_id) not in existing_pairs and not self._has_link_unlocked(c.from_id, c.to_id):
                        self._candidates.append(c)
                        existing_pairs.add((c.from_id, c.to_id))
                        existing_pairs.add((c.to_id, c.from_id))

                # Merge blocked pairs
                self._blocked_pairs |= source._blocked_pairs

                self._save_links()
                self._save_candidates()
                self._save_blocked()

            # Clear source (still under source._lock, target lock released)
            source._links.clear()
            source._candidates.clear()
            source._rebuild_index()
            source._save_links()
            source._save_candidates()

    def cleanup_for_card(self, card_id: str, *, remove_blocked: bool = False) -> dict:
        """Deprecate links + remove candidates (+ blocked pairs if deleting)."""
        dep_count = self.deprecate_links_for(card_id)
        cand_count = self.remove_candidates_for(card_id)
        if remove_blocked:
            self.remove_blocked_pairs_for(card_id)
        return {"deprecated": dep_count, "candidates_removed": cand_count}
