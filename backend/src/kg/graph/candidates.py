"""Candidate pair and pending-judge operations for the graph store."""

from __future__ import annotations

import threading

from .models import CandidatePair


class _CandidatesMixin:
    """Candidate pair + pending-judge operations for :class:`GraphStore`."""

    # Attributes provided by GraphStore -- declared for type checkers.
    _lock: threading.Lock
    _candidates: list[CandidatePair]
    _candidate_set: set[tuple[str, str]]
    _known_candidate_pairs: set[tuple[str, str]]
    _candidates_pop_lock: threading.Lock
    _pending_judge: set[str]
    _known_pending_judge: set[str]
    _pending_judge_pop_lock: threading.Lock

    # Helpers supplied by other mixins / GraphStore.
    def _has_link_unlocked(self, id_a: str, id_b: str) -> bool: ...  # noqa: D102
    def _candidates_to_serializable(self) -> list[dict]: ...  # noqa: D102
    def _flush_candidates(self, snapshot: list[dict]) -> None: ...  # noqa: D102
    def _flush_pending_judge(self, snapshot: list[str]) -> None: ...  # noqa: D102
    def _rebuild_candidate_set(self) -> None: ...  # noqa: D102

    @staticmethod
    def _normalize_pair(a: str, b: str) -> tuple[str, str]: ...  # noqa: D102

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
            self._known_candidate_pairs.add(norm)
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
                self._known_candidate_pairs.add(norm)
                added += 1
            snapshot = self._candidates_to_serializable() if added else None
        if snapshot is not None:
            self._flush_candidates(snapshot)
        return added

    def pop_candidates(self) -> list[CandidatePair]:
        """Get and clear all pending candidates.

        Flush-before-clear, mirroring :meth:`pop_pending_judge`:
        ``_candidates_pop_lock`` is held for the whole pop so two concurrent
        pops cannot return the same pairs twice. The popped pairs are captured
        under ``_lock``; the snapshot is the remainder, so an ``add_candidate``
        racing before the flush is preserved by the merge rather than dropped
        as a stale removal. Memory is mutated only after a successful flush,
        and only the popped pairs are removed.
        """
        with self._candidates_pop_lock:
            with self._lock:
                result = self._candidates[:]
                if not result:
                    return result
                popped_pairs = {
                    self._normalize_pair(c.from_id, c.to_id) for c in result
                }
                snapshot = [
                    c.model_dump(mode="json")
                    for c in self._candidates
                    if self._normalize_pair(c.from_id, c.to_id) not in popped_pairs
                ]
            self._flush_candidates(snapshot)
            with self._lock:
                self._candidates = [
                    c for c in self._candidates
                    if self._normalize_pair(c.from_id, c.to_id) not in popped_pairs
                ]
                self._rebuild_candidate_set()
        return result

    def requeue_candidates(self, candidates: list[CandidatePair]) -> None:
        """Push unprocessed candidates back onto the list."""
        with self._lock:
            for c in candidates:
                self._candidates.append(c)
                norm = self._normalize_pair(c.from_id, c.to_id)
                self._candidate_set.add(norm)
                self._known_candidate_pairs.add(norm)
            snapshot = self._candidates_to_serializable()
        self._flush_candidates(snapshot)

    def candidate_count(self) -> int:
        return len(self._candidates) + len(self._pending_judge)

    # ------------------------------------------------------------------
    # Pending Judge
    # ------------------------------------------------------------------

    def add_pending_judge(self, card_ids: list[str] | str) -> None:
        """Add card ID(s) to the pending judge set. Dedup by set semantics.

        Persist the prospective state before committing new IDs to memory. If
        the flush fails, the in-memory queue remains at its last durable state.
        The pop lock serializes this transaction with pops, which also flush
        outside ``_lock`` before committing their own state changes.
        """
        if isinstance(card_ids, str):
            card_ids = [card_ids]
        with self._pending_judge_pop_lock:
            with self._lock:
                new_ids = set(card_ids) - self._pending_judge
                if not new_ids:
                    return
                snapshot = sorted(self._pending_judge | new_ids)
            self._flush_pending_judge(snapshot)
            with self._lock:
                self._pending_judge.update(new_ids)
                # Register every successfully persisted id as managed by this
                # instance so a later merge honours a pop/removal instead of
                # resurrecting it from disk.
                self._known_pending_judge.update(new_ids)

    def pop_pending_judge(self) -> list[str]:
        """Get and clear all pending judge card IDs. Returns sorted list.

        Flush-before-clear: the post-pop snapshot is persisted to disk FIRST,
        and the in-memory set is mutated only if that flush succeeds. A flush
        failure (disk full, atomic-write error) propagates with memory and
        disk both still holding the old IDs — they never diverge, so a later
        reload cannot resurrect orphaned cards.

        Disk I/O runs *outside* ``_lock`` (the fcntl file lock would otherwise
        amplify cross-instance contention into the in-memory lock and stall
        readers). ``_pending_judge_pop_lock`` is held for the whole pop so two
        concurrent pops on the same instance cannot both observe the
        not-yet-removed IDs and return them twice (exactly-once). The popped
        set is captured under ``_lock``; the snapshot is ``_pending_judge``
        minus that set, so an ``add_pending_judge`` racing before the flush is
        preserved, not clobbered. After a successful flush the lock is re-taken
        and only the popped IDs are discarded — never a blanket ``clear()``.
        """
        with self._pending_judge_pop_lock:
            with self._lock:
                result = sorted(self._pending_judge)
                if not result:
                    return result
                popped = set(result)
                # Snapshot = state after this pop; includes any concurrent add.
                snapshot = sorted(self._pending_judge - popped)
            # Persist outside _lock. If this raises, memory is untouched → no loss.
            self._flush_pending_judge(snapshot)
            with self._lock:
                self._pending_judge.difference_update(popped)
        return result

    def remove_pending_judge_for(self, card_id: str) -> int:
        """Remove a specific card ID from pending judge. Returns 1 if removed, 0 otherwise."""
        with self._lock:
            if card_id not in self._pending_judge:
                return 0
            self._pending_judge.discard(card_id)
            snapshot = sorted(self._pending_judge)
        self._flush_pending_judge(snapshot)
        return 1

    def pending_judge_count(self) -> int:
        return len(self._pending_judge)

    # ------------------------------------------------------------------
    # Cleanup (candidate side)
    # ------------------------------------------------------------------

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
