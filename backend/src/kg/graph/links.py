"""Link CRUD operations for the graph store."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from .filelock import path_write_lock
from .models import GraphLink, LinkKind


class _LinksMixin:
    """Link create / query / mutate / block operations for :class:`GraphStore`."""

    # Attributes provided by GraphStore -- declared for type checkers.
    _lock: threading.Lock
    _links: dict[str, GraphLink]
    _blocked_pairs: set[tuple[str, str]]
    _known_blocked_pairs: set[tuple[str, str]]
    _from_index: dict[str, set[str]]
    _to_index: dict[str, set[str]]
    links_path: Path
    _known_link_ids: set[str]
    _links_write_lock: threading.Lock

    # Helpers supplied by other mixins / GraphStore.
    def _index_link(self, link: GraphLink) -> None: ...  # noqa: D102
    def _unindex_link(self, link: GraphLink) -> None: ...  # noqa: D102
    def _links_to_serializable(self) -> list[dict]: ...  # noqa: D102
    def _read_json_list(self, path: Path) -> list[Any]: ...  # noqa: D102
    @staticmethod
    def _atomic_json_write(path: Path, data: Any, *, indent: int | None = 2) -> None: ...  # noqa: D102
    def _blocked_to_serializable(self) -> list[list[str]]: ...  # noqa: D102
    def _flush_links(self, snapshot: list[dict]) -> None: ...  # noqa: D102
    def _flush_blocked(self, snapshot: list[list[str]]) -> None: ...  # noqa: D102
    def _emit_graph_event(self, event_type: str, **kw: Any) -> None: ...  # noqa: D102
    def _build_graph_event_draft(self, event_type: str, **kw: Any) -> Any: ...  # noqa: D102
    def _emit_graph_events(self, drafts: list[Any]) -> None: ...  # noqa: D102

    @staticmethod
    def _normalize_pair(a: str, b: str) -> tuple[str, str]: ...  # noqa: D102

    # ------------------------------------------------------------------
    # Links
    # ------------------------------------------------------------------

    def _find_persisted_link_for_pair(
        self,
        rows: list[Any],
        from_id: str,
        to_id: str,
    ) -> GraphLink | None:
        """Find an active/hidden link for a pair in a freshly-read disk snapshot."""
        for row in rows:
            if not isinstance(row, dict) or row.get("status", "active") not in ("active", "hidden"):
                continue
            row_from, row_to = row.get("from_id"), row.get("to_id")
            if not ((row_from == from_id and row_to == to_id) or (row_from == to_id and row_to == from_id)):
                continue
            try:
                return GraphLink.model_validate(row)
            except (TypeError, ValueError):
                # Match _load's tolerant handling: a malformed row cannot make
                # a valid add_link request fail its semantic uniqueness check.
                continue
        return None

    def _persist_new_link(self, link: GraphLink, snapshot: list[dict]) -> GraphLink | None:
        """Persist a new link while atomically re-checking semantic pair uniqueness.

        ``_flush_links`` protects file writes and merges foreign IDs, but it
        cannot prevent two independent instances from both creating different
        IDs for the same pair. Re-read and merge under the same file lock so a
        second instance returns the first durable link instead of appending a
        duplicate.
        """
        with self._links_write_lock, path_write_lock(self.links_path):
            sequence = getattr(snapshot, "sequence", None)
            if sequence is not None and sequence < getattr(self, "_last_flushed_links_snapshot_sequence", 0):
                return None

            disk_rows = self._read_json_list(self.links_path)
            existing = self._find_persisted_link_for_pair(disk_rows, link.from_id, link.to_id)
            if existing is not None and existing.id != link.id:
                with self._lock:
                    managed = self._links.pop(link.id, None)
                    if managed is not None:
                        self._unindex_link(managed)
                    self._known_link_ids.discard(link.id)
                return existing

            snapshot_ids = {row["id"] for row in snapshot}
            merged = list(snapshot)
            for row in disk_rows:
                if not isinstance(row, dict):
                    merged.append(row)
                    continue
                row_id = row.get("id")
                if row_id is None or row_id in snapshot_ids:
                    continue
                if row_id in self._known_link_ids:
                    continue
                merged.append(row)
            self._atomic_json_write(self.links_path, merged)
            if sequence is not None:
                self._last_flushed_links_snapshot_sequence = sequence
        return None

    def add_link(
        self,
        from_id: str,
        to_id: str,
        kind: LinkKind,
        confidence: float,
        reason: str,
        *,
        source: str = "auto",
    ) -> GraphLink:
        """Create and store a new link. Idempotent per pair across store instances.

        The sole caller (create_manual_link) does check-then-act: it reads
        find_link_between == None, runs a multi-second LLM call without holding
        _lock, then calls add_link. Two concurrent manual-link requests for the
        same pair therefore both reach add_link. Re-checking inside _lock closes
        the same-instance gap; _persist_new_link re-reads under the cross-process
        file lock so an already-persisted (active/hidden) pair returns the
        existing link instead of inserting a duplicate.
        """
        if from_id == to_id:
            raise ValueError("cannot link a card to itself")
        if not 0.0 <= confidence <= 1.0:
            raise ValueError("confidence must be between 0.0 and 1.0")
        link = GraphLink(
            from_id=from_id,
            to_id=to_id,
            kind=kind,
            confidence=confidence,
            reason=reason,
        )
        with self._lock:
            existing = self._find_link_between_unlocked(from_id, to_id)
            if existing is not None:
                return existing
            self._links[link.id] = link
            self._index_link(link)
            snapshot = self._links_to_serializable()
        existing = self._persist_new_link(link, snapshot)
        if existing is not None:
            return existing
        self._emit_graph_event(
            "link_added",
            link_id=link.id,
            from_id=from_id,
            to_id=to_id,
            links_snapshot=snapshot,
            kind=str(kind),
            source=source,
            confidence_before=None,
            confidence_after=confidence,
            status_before=None,
            status_after="active",
            reason=reason,
        )
        return link

    def batch_add_links(
        self,
        links: list[tuple[str, str, LinkKind, float, str]],
        *,
        source: str = "auto",
    ) -> list[GraphLink]:
        """Create multiple links with a single disk write. Returns created links."""
        created: list[GraphLink] = []
        with self._lock:
            for from_id, to_id, kind, confidence, reason in links:
                if from_id == to_id:
                    raise ValueError("cannot link a card to itself")
                if not 0.0 <= confidence <= 1.0:
                    raise ValueError("confidence must be between 0.0 and 1.0")
                if self._has_link_unlocked(from_id, to_id):
                    continue
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
            self._emit_graph_events(
                [
                    self._build_graph_event_draft(
                        "link_added",
                        link_id=lk.id,
                        from_id=lk.from_id,
                        to_id=lk.to_id,
                        kind=str(lk.kind),
                        source=source,
                        confidence_before=None,
                        confidence_after=lk.confidence,
                        status_before=None,
                        status_after="active",
                        reason=lk.reason,
                    )
                    for lk in created
                ],
                links_snapshot=snapshot,
            )
        return created

    def get_links_for(self, card_id: str) -> list[GraphLink]:
        """Get all active and hidden links involving a card."""
        # Lock: the index sets and _links are mutated by concurrent writers on the
        # same cached instance; reading them lock-free risks a KeyError when a
        # link was just hard-deleted between the index read and the dict lookup.
        with self._lock:
            link_ids = self._from_index.get(card_id, set()) | self._to_index.get(card_id, set())
            return [
                self._links[lid]
                for lid in link_ids
                if lid in self._links and self._links[lid].status in ("active", "hidden")
            ]

    def _has_link_unlocked(self, id_a: str, id_b: str) -> bool:
        """Check link existence without acquiring the lock (internal use)."""
        if self._normalize_pair(id_a, id_b) in self._blocked_pairs:
            return True
        candidates = self._from_index.get(id_a, set()) | self._to_index.get(id_a, set())
        for lid in candidates:
            lk = self._links.get(lid)
            if lk is None or lk.status not in ("active", "hidden"):
                continue
            if (lk.from_id == id_a and lk.to_id == id_b) or (lk.from_id == id_b and lk.to_id == id_a):
                return True
        return False

    def has_link(self, id_a: str, id_b: str) -> bool:
        """Check if a link exists between two cards (active or rejected counts)."""
        # _has_link_unlocked is the lock-free variant for internal callers that
        # already hold _lock; the public entry point must take the lock itself.
        with self._lock:
            return self._has_link_unlocked(id_a, id_b)

    def _find_link_between_unlocked(self, id_a: str, id_b: str) -> GraphLink | None:
        """Lock-free find of an active/hidden link for a pair (internal use).

        Callers must already hold _lock. The public find_link_between takes the
        lock; add_link reuses this while holding the lock to dedup in-place.
        """
        candidates = self._from_index.get(id_a, set()) | self._to_index.get(id_a, set())
        for lid in candidates:
            lk = self._links.get(lid)
            if lk is None or lk.status not in ("active", "hidden"):
                continue
            if (lk.from_id == id_a and lk.to_id == id_b) or (lk.from_id == id_b and lk.to_id == id_a):
                return lk
        return None

    def find_link_between(self, id_a: str, id_b: str) -> GraphLink | None:
        """Find active or hidden link between two cards (bidirectional). Returns None for deprecated/absent."""
        with self._lock:
            return self._find_link_between_unlocked(id_a, id_b)

    def get_link(self, link_id: str) -> GraphLink | None:
        """Return a link by ID, or None if not found."""
        # Take _lock to read _links: concurrent writers mutate the dict on the
        # same cached instance, so this mirrors get_links_for/find_link_between
        # rather than reading lock-free. All public callers (vocab_graph_ops)
        # invoke this outside _lock, so acquiring it here cannot deadlock.
        with self._lock:
            return self._links.get(link_id)

    def update_link(self, link_id: str, *, source: str = "auto", **attrs: Any) -> GraphLink:
        """Update attributes of an existing link and persist."""
        ALLOWED = {"status", "kind", "confidence", "reason"}
        with self._lock:
            lk = self._links.get(link_id)
            if lk is None:
                raise KeyError(link_id)
            conf_before, status_before = lk.confidence, lk.status
            for key, value in attrs.items():
                if key not in ALLOWED:
                    raise ValueError(f"Cannot update attribute: {key}")
                setattr(lk, key, value)
            conf_after, status_after = lk.confidence, lk.status
            reason_after = lk.reason
            from_id, to_id, kind = lk.from_id, lk.to_id, str(lk.kind)
            snapshot = self._links_to_serializable()
        self._flush_links(snapshot)
        self._emit_graph_event(
            "link_updated",
            link_id=link_id,
            from_id=from_id,
            to_id=to_id,
            kind=kind,
            links_snapshot=snapshot,
            source=source,
            confidence_before=conf_before,
            confidence_after=conf_after,
            status_before=status_before,
            status_after=status_after,
            reason=reason_after,
        )
        return lk

    def hide_link(self, link_id: str, *, source: str = "auto") -> None:
        """Set link status to hidden. Raises KeyError if not found."""
        with self._lock:
            lk = self._links.get(link_id)
            if lk is None:
                raise KeyError(link_id)
            status_before = lk.status
            lk.status = "hidden"
            from_id, to_id, kind, conf = lk.from_id, lk.to_id, str(lk.kind), lk.confidence
            snapshot = self._links_to_serializable()
        self._flush_links(snapshot)
        self._emit_graph_event(
            "link_hidden",
            link_id=link_id,
            from_id=from_id,
            to_id=to_id,
            kind=kind,
            links_snapshot=snapshot,
            source=source,
            confidence_before=conf,
            confidence_after=conf,
            status_before=status_before,
            status_after="hidden",
        )

    def unhide_link(self, link_id: str, *, source: str = "auto") -> None:
        """Set link status back to active. Raises KeyError if not found."""
        with self._lock:
            lk = self._links.get(link_id)
            if lk is None:
                raise KeyError(link_id)
            status_before = lk.status
            lk.status = "active"
            from_id, to_id, kind, conf = lk.from_id, lk.to_id, str(lk.kind), lk.confidence
            snapshot = self._links_to_serializable()
        self._flush_links(snapshot)
        self._emit_graph_event(
            "link_unhidden",
            link_id=link_id,
            from_id=from_id,
            to_id=to_id,
            kind=kind,
            links_snapshot=snapshot,
            source=source,
            confidence_before=conf,
            confidence_after=conf,
            status_before=status_before,
            status_after="active",
        )

    def hard_delete_link(self, link_id: str, *, source: str = "auto") -> tuple[str, str]:
        """Delete a link and add the pair to blocked list. Returns (from_id, to_id)."""
        with self._lock:
            lk = self._links.get(link_id)
            if lk is None:
                raise KeyError(link_id)
            from_id, to_id = lk.from_id, lk.to_id
            kind, conf, status_before = str(lk.kind), lk.confidence, lk.status
            self._unindex_link(lk)
            del self._links[link_id]
            pair = self._normalize_pair(from_id, to_id)
            self._blocked_pairs.add(pair)
            # Register so a later _flush_blocked merge treats this pair as
            # managed by this instance (a subsequent unblock is honoured).
            self._known_blocked_pairs.add(pair)
            links_snapshot = self._links_to_serializable()
            blocked_snapshot = self._blocked_to_serializable()
        self._flush_links(links_snapshot)
        self._flush_blocked(blocked_snapshot)
        self._emit_graph_event(
            "link_deleted",
            link_id=link_id,
            from_id=from_id,
            to_id=to_id,
            kind=kind,
            links_snapshot=links_snapshot,
            source=source,
            confidence_before=conf,
            confidence_after=None,
            status_before=status_before,
            status_after=None,
        )
        return (from_id, to_id)

    def is_blocked(self, from_id: str, to_id: str) -> bool:
        """Check if a pair is blocked."""
        return self._normalize_pair(from_id, to_id) in self._blocked_pairs

    def remove_blocked_pairs_for(self, card_id: str) -> None:
        """Remove all blocked pairs involving a card."""
        with self._lock:
            self._blocked_pairs = {pair for pair in self._blocked_pairs if card_id not in pair}
            snapshot = self._blocked_to_serializable()
        self._flush_blocked(snapshot)

    def unblock_pair(self, from_id: str, to_id: str) -> None:
        """Remove a specific blocked pair."""
        with self._lock:
            self._blocked_pairs.discard(self._normalize_pair(from_id, to_id))
            snapshot = self._blocked_to_serializable()
        self._flush_blocked(snapshot)

    def all_links(self) -> list[GraphLink]:
        # Return a snapshot list taken under the lock, not a lazy view: iterating
        # _links.values() while a writer inserts raises "dictionary changed size
        # during iteration".
        with self._lock:
            return list(self._links.values())

    def link_count(self) -> int:
        with self._lock:
            return sum(1 for lk in self._links.values() if lk.status == "active")
