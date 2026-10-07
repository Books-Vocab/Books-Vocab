"""Candidate pair and pending-judge operations for the graph store."""

from __future__ import annotations

import threading
from collections import Counter
from collections.abc import Iterable
from pathlib import Path

from .models import CandidatePair

# Process-local registry of pending-judge ids claimed by ``pop_pending_judge``
# and not yet settled (acked or handed back), keyed by the resolved pending
# file path (``GraphStore._claims_key``).
#
# A claim never leaves the durable file, so a process that dies mid-judge just
# leaves its claims as queued work for the next process. Within one process,
# though, a second ``GraphStore`` on the same file (store-cache eviction while
# a judge run still holds the first instance) must not load a live claim as
# queued work and judge it twice, so ``GraphStore._load`` subtracts this
# registry. Counted so two instances claiming the same id cannot release each
# other's claim. ``_CLAIMS_LOCK`` is always the innermost lock taken.
_CLAIMS_LOCK = threading.Lock()
_CLAIMS: dict[Path, Counter[str]] = {}


def claimed_pending_judge(key: Path | None) -> set[str]:
    """Ids of the pending file ``key`` claimed by a live judge run in this process."""
    if key is None:
        return set()
    with _CLAIMS_LOCK:
        return set(_CLAIMS.get(key, ()))


def _register_claims(key: Path | None, card_ids: Iterable[str]) -> None:
    if key is None:
        return
    with _CLAIMS_LOCK:
        _CLAIMS.setdefault(key, Counter()).update(card_ids)


def _release_claims(key: Path | None, card_ids: Iterable[str]) -> None:
    if key is None:
        return
    with _CLAIMS_LOCK:
        claims = _CLAIMS.get(key)
        if claims is None:
            return
        for card_id in card_ids:
            if claims[card_id] <= 1:
                claims.pop(card_id, None)
            else:
                claims[card_id] -= 1
        if not claims:
            del _CLAIMS[key]


class _CandidatesMixin:
    """Candidate pair + pending-judge operations for :class:`GraphStore`."""

    # Attributes provided by GraphStore -- declared for type checkers.
    _lock: threading.Lock
    _candidates: list[CandidatePair]
    _candidate_set: set[tuple[str, str]]
    _known_candidate_pairs: set[tuple[str, str]]
    _candidates_pop_lock: threading.Lock
    _claims_key: Path | None
    _pending_judge: set[str]
    _inflight_judge: set[str]
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
                popped_pairs = {self._normalize_pair(c.from_id, c.to_id) for c in result}
                snapshot = [
                    c.model_dump(mode="json")
                    for c in self._candidates
                    if self._normalize_pair(c.from_id, c.to_id) not in popped_pairs
                ]
            self._flush_candidates(snapshot)
            with self._lock:
                self._candidates = [
                    c for c in self._candidates if self._normalize_pair(c.from_id, c.to_id) not in popped_pairs
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

    # The durable pending file holds queued ∪ claimed ids. Every flush below
    # persists that union (computed under ``_lock``, flushed outside it) and
    # mutates memory only after the flush succeeds, so memory and disk never
    # diverge. ``_pending_judge_pop_lock`` serialises these transactions.

    def add_pending_judge(self, card_ids: list[str] | str) -> None:
        """Queue card ID(s) for judging. Dedup by set semantics.

        Also the hand-back for claimed ids: a claimed id passed here leaves
        the claim and is queued again for the next pop. A claimed id is
        already durable, so a pure hand-back needs no disk write and cannot
        fail on I/O. Genuinely new ids are persisted before they enter memory;
        if that flush fails, memory stays at its last durable state.
        """
        if isinstance(card_ids, str):
            card_ids = [card_ids]
        with self._pending_judge_pop_lock:
            with self._lock:
                new_ids = set(card_ids) - self._pending_judge
                if not new_ids:
                    return
                handed_back = new_ids & self._inflight_judge
                needs_flush = bool(new_ids - handed_back)
                snapshot = sorted(self._pending_judge | self._inflight_judge | new_ids)
            if needs_flush:
                self._flush_pending_judge(snapshot)
            with self._lock:
                self._inflight_judge.difference_update(handed_back)
                self._pending_judge.update(new_ids)
                # Register every durable id as managed by this instance so a
                # later merge honours an ack/removal instead of resurrecting
                # it from disk.
                self._known_pending_judge.update(new_ids)
                _release_claims(self._claims_key, handed_back)

    def pop_pending_judge(self) -> list[str]:
        """Claim every queued pending-judge ID. Returns sorted list.

        A claim, not a delete (#2084): the IDs move from the queued set to
        ``_inflight_judge`` in memory only and stay in the durable pending
        file until the caller settles each one — ``ack_pending_judge`` once
        its links are persisted, or ``add_pending_judge`` to hand it back. A
        process killed mid-judge (deploy SIGKILL, OOM) therefore leaves them
        as queued work for the next process's fresh store. No disk I/O
        happens here, so a pop cannot fail half-way.

        ``_lock`` makes concurrent pops hand each ID to exactly one caller;
        the claim is registered process-wide before ``_lock`` is released so
        a store constructed meanwhile cannot load it as queued work.
        """
        with self._pending_judge_pop_lock:
            with self._lock:
                result = sorted(self._pending_judge)
                if not result:
                    return result
                self._pending_judge.difference_update(result)
                self._inflight_judge.update(result)
                _register_claims(self._claims_key, result)
        return result

    def ack_pending_judge(self, card_ids: list[str] | str) -> None:
        """Settle claimed IDs whose judge work is durable (links persisted).

        Removes them from the durable pending file. IDs this store has not
        claimed (never popped, handed back, or re-queued since the pop) are
        ignored, so a card re-added while its old judgement was in flight
        stays queued for a fresh judgement. If the flush fails the claim stays
        in memory and on disk.
        """
        if isinstance(card_ids, str):
            card_ids = [card_ids]
        with self._pending_judge_pop_lock:
            with self._lock:
                done = set(card_ids) & self._inflight_judge
                if not done:
                    return
                snapshot = sorted(self._pending_judge | (self._inflight_judge - done))
            self._flush_pending_judge(snapshot)
            with self._lock:
                self._inflight_judge.difference_update(done)
                _release_claims(self._claims_key, done)

    def remove_pending_judge_for(self, card_id: str) -> int:
        """Remove a card ID from pending judge, queued or claimed. Returns 1 if removed, 0 otherwise."""
        with self._pending_judge_pop_lock:
            with self._lock:
                if card_id not in self._pending_judge and card_id not in self._inflight_judge:
                    return 0
                snapshot = sorted((self._pending_judge | self._inflight_judge) - {card_id})
            self._flush_pending_judge(snapshot)
            with self._lock:
                self._pending_judge.discard(card_id)
                if card_id in self._inflight_judge:
                    self._inflight_judge.discard(card_id)
                    _release_claims(self._claims_key, [card_id])
        return 1

    def pending_judge_count(self) -> int:
        """Queued IDs only; claimed IDs belong to the judge run holding them."""
        return len(self._pending_judge)

    # ------------------------------------------------------------------
    # Cleanup (candidate side)
    # ------------------------------------------------------------------

    def remove_candidates_for(self, card_id: str) -> int:
        """Remove all pending candidates involving a card. Returns count removed."""
        with self._lock:
            before = len(self._candidates)
            self._candidates = [c for c in self._candidates if c.from_id != card_id and c.to_id != card_id]
            removed = before - len(self._candidates)
            if removed:
                self._rebuild_candidate_set()
            snapshot = self._candidates_to_serializable() if removed else None
        if snapshot is not None:
            self._flush_candidates(snapshot)
        return removed
