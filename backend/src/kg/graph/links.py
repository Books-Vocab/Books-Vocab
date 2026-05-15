"""Link CRUD operations for the graph store."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from typing import Any

from .models import GraphLink, LinkKind


class _LinksMixin:
    """Link create / query / mutate / block operations for :class:`GraphStore`."""

    # Attributes provided by GraphStore -- declared for type checkers.
    _lock: threading.Lock
    _links: dict[str, GraphLink]
    _blocked_pairs: set[tuple[str, str]]
    _from_index: dict[str, set[str]]
    _to_index: dict[str, set[str]]

    # Helpers supplied by other mixins / GraphStore.
    def _index_link(self, link: GraphLink) -> None: ...  # noqa: D102
    def _unindex_link(self, link: GraphLink) -> None: ...  # noqa: D102
    def _links_to_serializable(self) -> list[dict]: ...  # noqa: D102
    def _blocked_to_serializable(self) -> list[list[str]]: ...  # noqa: D102
    def _flush_links(self, snapshot: list[dict]) -> None: ...  # noqa: D102
    def _flush_blocked(self, snapshot: list[list[str]]) -> None: ...  # noqa: D102

    @staticmethod
    def _normalize_pair(a: str, b: str) -> tuple[str, str]: ...  # noqa: D102

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
