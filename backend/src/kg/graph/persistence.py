"""Disk persistence helpers for the graph store.

Provides the ``_PersistenceMixin`` which encapsulates atomic JSON writes,
in-memory -> serialisable snapshot conversion, and per-file serialised
flush helpers. Disk I/O always happens *outside* the in-memory lock.

Cross-instance safety
---------------------
``_flush_links`` / ``_flush_blocked`` write *durable, user-facing* graph
state. A naive whole-file overwrite from an in-memory snapshot is a
lost-update bug: a second ``GraphStore`` instance (pipeline run / API
request / second worker) constructed with a stale view will erase links
added by the first. To prevent this, those two flushes run under an
``fcntl`` advisory file lock and *merge* with the current on-disk file
before writing:

- Links the instance has ever seen (``_known_link_ids``) are authoritative,
  so deletions still take effect.
- Links present on disk but unknown to the instance are preserved.
- Blocked pairs follow the same rule via ``_known_blocked_pairs``: a pair the
  instance unblocked is honoured (a naive union would resurrect it), while a
  pair blocked by another instance is preserved.

``_flush_candidates`` / ``_flush_pending_judge`` hold pre-judge state. It is
*not* pop-only: ``add_candidate`` / ``batch_add_candidates`` /
``requeue_candidates`` / ``add_pending_judge`` all *append* incrementally, so
a naive whole-file overwrite is the same lost-update bug as on links -- a
stale second instance erases a card another instance queued, and that card
is never judged. These two flushes therefore merge under the file lock just
like ``_flush_links``:

- ``_known_pending_judge`` / ``_known_candidate_pairs`` make ids/pairs this
  instance has ever held authoritative, so an ack/pop/removal still takes
  effect. A pending-judge pop is only a claim: claimed ids stay in the file
  until acked (``candidates.pop_pending_judge``). An ack only removes a
  row still carrying the enqueue generation it claimed (see
  ``_flush_pending_judge``), so a later enqueue by another instance survives.
- An id/pair present on disk but unknown to the instance (queued by another
  instance) is preserved instead of being clobbered.

Stale instances (#2086)
-----------------------
The rules above trust this instance's snapshot for every link / blocked pair
it holds. That is only sound while the file still is what this instance last
read or wrote. The API keeps one long-lived instance per notebook, and
``ops-edit`` / ``restore`` rewrite the same files from another process, so the
cached snapshot can hold a link that was since deleted or updated elsewhere.

Each instance therefore records the file signature (inode, mtime, size) of its
last sync, plus the ids/pairs it changed since then (``_pending_*``, keyed by
the snapshot sequence that carries the change). When a flush finds a different
signature -- or carries a snapshot taken before this instance re-synced -- it
replays only its own pending changes onto the current file, and the result is
adopted back into memory. A link deleted by another writer stays deleted, even
when this instance edited it concurrently. ``GraphStore.refresh_if_stale``
applies the same adoption on read so a foreign write also becomes visible, and
the single-link mutators call it first so they edit the other writer's row.
Adoption keeps the "was persisted before" fact of every pending link, so an
in-flight edit of a link the other writer deleted is never mistaken for a link
created here.

Known limit: replay is row-level last-writer-wins. If another process changes
the *same* link between a mutator's re-sync and its flush (a millisecond
window), this instance's whole row replaces the foreign one.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from .._fsutil import fsync_dir as _fsync_dir
from .filelock import path_write_lock
from .models import CandidatePair, GraphLink

logger = logging.getLogger(__name__)

# (st_ino, st_mtime_ns, st_size). Every writer replaces the file via
# tmp -> rename, so any foreign write yields a different signature.
DiskSignature = tuple[int, int, int]


class _LinkSnapshot(list[dict]):
    """Serializable link snapshot carrying its in-memory mutation order."""

    def __init__(self, rows: list[dict], sequence: int) -> None:
        super().__init__(rows)
        self.sequence = sequence


_GEN_ROW_KEY = "gen"


class _PendingSnapshot(list[str]):
    """Pending-judge snapshot carrying the generation bookkeeping of one transaction.

    ``gens`` holds the generations of ids this transaction enqueues (not yet
    committed to ``_judge_gen``, because memory is mutated only after the
    flush succeeds). ``acked`` names ids dropped by an ack, whose on-disk row
    is removed only if it is still the generation this instance claimed.
    """

    def __init__(
        self,
        ids: Iterable[str],
        gens: dict[str, str] | None = None,
        acked: Iterable[str] = (),
    ) -> None:
        super().__init__(ids)
        self.gens = dict(gens or {})
        self.acked = frozenset(acked)


def _split_pending_rows(rows: list) -> tuple[list[str], dict[str, str]]:
    """Split a pending-judge file into its id rows and ``{id: generation}`` row."""
    ids: list[str] = []
    gens: dict[str, str] = {}
    for row in rows:
        if isinstance(row, str):
            ids.append(row)
        elif isinstance(row, dict) and isinstance(row.get(_GEN_ROW_KEY), dict):
            gens.update({k: v for k, v in row[_GEN_ROW_KEY].items() if isinstance(k, str) and isinstance(v, str)})
    return ids, gens


class _BlockedSnapshot(list[list[str]]):
    """Serializable blocked-pair snapshot carrying its in-memory mutation order."""

    def __init__(self, rows: list[list[str]], sequence: int) -> None:
        super().__init__(rows)
        self.sequence = sequence


def _covered_pending[K](pending: dict[K, int], sequence: int | None) -> dict[K, int]:
    """Pending changes already reflected in the snapshot taken at ``sequence``."""
    return {key: seq for key, seq in pending.items() if sequence is None or seq <= sequence}


def _clear_pending[K](pending: dict[K, int], covered: dict[K, int]) -> None:
    """Drop persisted changes, keeping keys re-touched after the snapshot."""
    for key, seq in covered.items():
        if pending.get(key) == seq:
            del pending[key]


class _PersistenceMixin:
    """Atomic write + snapshot + flush helpers for :class:`GraphStore`."""

    # Attributes provided by GraphStore.__init__ -- declared for type checkers.
    links_path: Path
    candidates_path: Path
    blocked_path: Path | None
    pending_judge_path: Path | None
    _lock: threading.Lock
    _links: dict[str, GraphLink]
    _candidates: list[CandidatePair]
    _blocked_pairs: set[tuple[str, str]]
    _pending_judge: set[str]
    _inflight_judge: set[str]
    _known_link_ids: set[str]
    _known_blocked_pairs: set[tuple[str, str]]
    _known_pending_judge: set[str]
    _judge_gen: dict[str, str | None]
    _known_candidate_pairs: set[tuple[str, str]]
    _links_snapshot_sequence: int
    _last_flushed_links_snapshot_sequence: int
    _blocked_snapshot_sequence: int
    _last_flushed_blocked_snapshot_sequence: int
    # Cross-process staleness tracking (#2086); see module docstring.
    _links_disk_sig: DiskSignature | None
    _blocked_disk_sig: DiskSignature | None
    _synced_link_ids: set[str]
    _pending_link_ids: dict[str, int]
    _pending_blocked_pairs: dict[tuple[str, str], int]
    _links_adopted_sequence: int
    _blocked_adopted_sequence: int
    _links_write_lock: threading.Lock
    _candidates_write_lock: threading.Lock
    _blocked_write_lock: threading.Lock
    _pending_judge_write_lock: threading.Lock

    # Helpers supplied by GraphStore.
    @staticmethod
    def _normalize_pair(a: str, b: str) -> tuple[str, str]: ...  # noqa: D102
    def _parse_link_rows(  # noqa: D102
        self, rows: list[Any]
    ) -> tuple[dict[str, GraphLink], set[tuple[str, str]], set[str], bool]: ...
    def _rebuild_index(self) -> None: ...  # noqa: D102

    @staticmethod
    def _disk_signature(path: Path | None) -> DiskSignature | None:
        """Identity of the file now at ``path``; ``None`` when it is absent."""
        if path is None:
            return None
        try:
            st = path.stat()
        except OSError:
            return None
        return (st.st_ino, st.st_mtime_ns, st.st_size)

    @staticmethod
    def _parse_blocked_rows(rows: list[Any]) -> set[tuple[str, str]]:
        return {tuple(row) for row in rows if isinstance(row, list) and len(row) == 2}  # type: ignore[misc]

    # Pending-change bookkeeping -- call inside _lock, right before taking the
    # snapshot that carries the change.
    def _touch_links(self, link_ids: Iterable[str]) -> None:
        sequence = getattr(self, "_links_snapshot_sequence", 0) + 1
        for link_id in link_ids:
            self._pending_link_ids[link_id] = sequence

    def _touch_blocked(self, pairs: Iterable[tuple[str, str]]) -> None:
        sequence = self._blocked_snapshot_sequence + 1
        for pair in pairs:
            self._pending_blocked_pairs[pair] = sequence

    # Adoption of another writer's state -- caller holds the file's write
    # locks; pending (not yet persisted) local changes are kept.
    def _usable_link_rows(self, rows: list[Any]) -> list[Any]:
        """Rows that parse; a malformed foreign row is skipped (it stays on disk)."""
        usable: list[Any] = []
        for row in rows:
            try:
                self._parse_link_rows([row])
            except (ValueError, KeyError, TypeError):
                logger.warning("graph: skipping unparseable link row in %s: %r", self.links_path, row)
                continue
            usable.append(row)
        return usable

    def _adopt_link_rows(self, rows: list[Any], sig: DiskSignature | None) -> None:
        disk_links = self._parse_link_rows(self._usable_link_rows(rows))[0]
        with self._lock:
            pending = self._pending_link_ids
            # A pending link that was persisted before keeps that fact: if the
            # other writer deleted it, an in-flight flush of our edit must not
            # mistake it for a link created here and write it back.
            previously_synced = self._synced_link_ids & pending.keys()
            for link_id in [lid for lid in self._links if lid not in pending and lid not in disk_links]:
                del self._links[link_id]
            for link_id, link in disk_links.items():
                if link_id in pending:
                    continue
                current = self._links.get(link_id)
                # Keep object identity for unchanged links: callers compare
                # ``self._links.get(id) is link`` after their own flush.
                if current is None or current.model_dump() != link.model_dump():
                    self._links[link_id] = link
            self._rebuild_index()
            # Snapshots taken before this point carry the pre-adoption view.
            self._links_adopted_sequence = getattr(self, "_links_snapshot_sequence", 0)
        self._links_disk_sig = sig
        self._synced_link_ids = {row["id"] for row in rows if isinstance(row, dict) and "id" in row} | previously_synced

    def _adopt_blocked_rows(self, rows: list[Any], sig: DiskSignature | None) -> None:
        disk_pairs = self._parse_blocked_rows(rows)
        with self._lock:
            pending = self._pending_blocked_pairs
            self._blocked_pairs = {p for p in disk_pairs if p not in pending} | {
                p for p in self._blocked_pairs if p in pending
            }
            self._known_blocked_pairs |= self._blocked_pairs
            self._blocked_adopted_sequence = self._blocked_snapshot_sequence
        self._blocked_disk_sig = sig

    @staticmethod
    def _atomic_json_write(path: Path, data: Any, *, indent: int | None = 2) -> None:
        """Atomic JSON write: tmp -> bak -> replace, fsynced before the rename.

        fsync of the tmp file (and best-effort of the parent directory) makes
        the bytes durable *before* the rename is observable. Without it an
        OS/power crash can persist the rename ahead of the data, surfacing a
        zero-length or torn primary file on next boot. The .bak still covers a
        torn write so recovery via _read_json_list stays possible.
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(json.dumps(data, indent=indent, ensure_ascii=False))
            f.flush()
            os.fsync(f.fileno())
        if path.exists():
            path.replace(path.with_suffix(".json.bak"))
        tmp.replace(path)
        # Persist the rename (directory entry) too, so the swap survives a crash.
        _fsync_dir(path.parent)

    @staticmethod
    def _try_read_json_list(path: Path) -> list | None:
        """Read a JSON array; ``[]`` when absent, ``None`` when present but unusable.

        A corrupt file falls back to its ``.bak`` sibling. ``None`` (the file and
        its backup both exist but neither parses) lets callers tell "unreadable"
        from "empty" -- adopting an unreadable file as an empty graph would
        silently drop every cached link (#2086).
        """
        found = False
        for candidate in (path, path.with_suffix(".json.bak")):
            if not candidate.exists():
                continue
            found = True
            try:
                data = json.loads(candidate.read_text())
                if isinstance(data, list):
                    return data
            except (json.JSONDecodeError, OSError, UnicodeDecodeError):
                logger.warning("graph: corrupt JSON at %s, trying fallback", candidate)
        return None if found else []

    @classmethod
    def _read_json_list(cls, path: Path) -> list:
        """Read a JSON array from disk, tolerating absence / corruption.

        Returns ``[]`` for a missing file. A corrupt file falls back to its
        ``.bak`` sibling; if that also fails, returns ``[]`` rather than
        raising, so a single bad write cannot wedge every future flush.
        """
        rows = cls._try_read_json_list(path)
        return [] if rows is None else rows

    # Snapshot helpers -- call inside lock, return serialisable data
    def _links_to_serializable(self) -> list[dict]:
        sequence = getattr(self, "_links_snapshot_sequence", 0) + 1
        self._links_snapshot_sequence = sequence
        return _LinkSnapshot([lk.model_dump(mode="json") for lk in self._links.values()], sequence)

    def _candidates_to_serializable(self) -> list[dict]:
        return [c.model_dump(mode="json") for c in self._candidates]

    def _blocked_to_serializable(self) -> list[list[str]]:
        sequence = self._blocked_snapshot_sequence + 1
        self._blocked_snapshot_sequence = sequence
        return _BlockedSnapshot([list(pair) for pair in self._blocked_pairs], sequence)

    # ------------------------------------------------------------------
    # Per-file serialised write helpers.
    #
    # Each acquires (a) the in-process file-level write lock and (b) the
    # cross-process fcntl advisory lock on the path. Every _flush_* helper
    # additionally re-reads + merges under that lock so a stale instance
    # cannot clobber another's durable changes.
    # ------------------------------------------------------------------

    def _flush_links(self, snapshot: list[dict]) -> None:
        """Persist links, merging with the current on-disk file.

        ``snapshot`` is this instance's full ``_links`` view. Under the file
        lock the on-disk file is re-read; any link unknown to this instance
        (``id`` not in ``_known_link_ids``) is preserved, while ids the
        instance manages -- including ones it deleted -- follow the snapshot.
        If another writer replaced the file since this instance last synced,
        only this instance's pending changes are replayed onto it instead
        (see module docstring, #2086).
        """
        with self._links_write_lock, path_write_lock(self.links_path):
            sequence = getattr(snapshot, "sequence", None)
            if sequence is not None and sequence < getattr(self, "_last_flushed_links_snapshot_sequence", 0):
                return
            disk_sig = self._disk_signature(self.links_path)
            read_rows = self._try_read_json_list(self.links_path)
            # An unreadable file has no foreign state to protect: regenerate it
            # from this instance's full view rather than replaying onto nothing.
            disk_rows = read_rows or []
            stale = read_rows is not None and (
                disk_sig != self._links_disk_sig or (sequence is not None and sequence <= self._links_adopted_sequence)
            )
            with self._lock:
                covered = _covered_pending(self._pending_link_ids, sequence)
            if stale:
                merged = self._replay_links_onto_disk(snapshot, disk_rows, covered)
            else:
                merged = self._merge_links_over_disk(snapshot, disk_rows)
            self._atomic_json_write(self.links_path, merged)
            if sequence is not None:
                self._last_flushed_links_snapshot_sequence = sequence
            new_sig = self._disk_signature(self.links_path)
            with self._lock:
                _clear_pending(self._pending_link_ids, covered)
            if stale:
                self._adopt_link_rows(merged, new_sig)
            else:
                self._links_disk_sig = new_sig
                self._synced_link_ids = {row["id"] for row in merged if isinstance(row, dict) and "id" in row}

    def _merge_links_over_disk(self, snapshot: list[dict], disk_rows: list[Any]) -> list[dict]:
        """File unchanged since our last sync: the snapshot is authoritative."""
        snapshot_ids = {row["id"] for row in snapshot}
        merged = list(snapshot)
        for row in disk_rows:
            if not isinstance(row, dict):
                continue
            rid = row.get("id")
            if rid is None or rid in snapshot_ids:
                continue
            if rid in self._known_link_ids:
                # This instance knew this link and dropped it -> honour delete.
                continue
            # Foreign link added by another instance: preserve it, but do
            # NOT register it as managed by us -- otherwise our next flush
            # (whose snapshot lacks it) would treat it as a deletion.
            merged.append(row)
        return merged

    def _replay_links_onto_disk(
        self, snapshot: list[dict], disk_rows: list[Any], covered: dict[str, int]
    ) -> list[dict]:
        """File changed under us: the disk is authoritative except for ``covered``."""
        snapshot_by_id = {row["id"]: row for row in snapshot}
        merged: list[dict] = []
        seen: set[str] = set()
        for row in disk_rows:
            if not isinstance(row, dict):
                continue
            rid = row.get("id")
            if rid is None or rid in seen:
                continue
            seen.add(rid)
            if rid not in covered:
                merged.append(row)  # another writer's version wins over our stale copy
            elif rid in snapshot_by_id:
                merged.append(snapshot_by_id[rid])  # our own edit
            # else: deleted by this instance
        for rid, row in snapshot_by_id.items():
            if rid in seen:
                continue
            if rid in covered and rid not in self._synced_link_ids:
                merged.append(row)  # created here, not persisted yet
            # else: deleted by another writer -- that wins over our stale or
            # concurrently edited copy (the delete also blocked the pair).
        return merged

    def _flush_blocked(self, snapshot: list[list[str]]) -> None:
        """Persist blocked pairs, merging with the current on-disk file.

        ``snapshot`` is this instance's full ``_blocked_pairs`` view. Under the
        file lock the on-disk file is re-read; any pair unknown to this instance
        (not in ``_known_blocked_pairs``) is preserved, while pairs the instance
        manages -- including ones it unblocked -- follow the snapshot. A naive
        union would resurrect a pair the user explicitly unblocked. If another
        writer replaced the file since this instance last synced, only this
        instance's pending changes are replayed onto it (#2086).
        """
        if self.blocked_path is None:
            return
        with self._blocked_write_lock, path_write_lock(self.blocked_path):
            sequence = getattr(snapshot, "sequence", None)
            # A newer snapshot already reached disk; flushing this older one
            # would treat the newer pairs as unblocked and erase them.
            if sequence is not None and sequence < getattr(self, "_last_flushed_blocked_snapshot_sequence", 0):
                return
            disk_sig = self._disk_signature(self.blocked_path)
            read_rows = self._try_read_json_list(self.blocked_path)
            disk_pairs = self._parse_blocked_rows(read_rows or [])
            snapshot_pairs: set[tuple[str, str]] = {tuple(p) for p in snapshot}  # type: ignore[misc]
            # Unreadable file: regenerate from our full view (see _flush_links).
            stale = read_rows is not None and (
                disk_sig != self._blocked_disk_sig
                or (sequence is not None and sequence <= self._blocked_adopted_sequence)
            )
            with self._lock:
                covered = _covered_pending(self._pending_blocked_pairs, sequence)
            if stale:
                # Disk wins except for pairs this instance blocked/unblocked.
                merged = {p for p in disk_pairs if p not in covered} | {p for p in snapshot_pairs if p in covered}
            else:
                merged = set(snapshot_pairs)
                # A pair this instance knew and dropped is an unblock; a pair it
                # never knew was blocked by another instance and is preserved
                # (not registered as ours, or our next flush would unblock it).
                merged |= {p for p in disk_pairs if p not in self._known_blocked_pairs}
            rows = [list(p) for p in merged]
            self._atomic_json_write(self.blocked_path, rows, indent=None)
            if sequence is not None:
                self._last_flushed_blocked_snapshot_sequence = sequence
            new_sig = self._disk_signature(self.blocked_path)
            with self._lock:
                _clear_pending(self._pending_blocked_pairs, covered)
            if stale:
                self._adopt_blocked_rows(rows, new_sig)
            else:
                self._blocked_disk_sig = new_sig

    def _flush_candidates(self, snapshot: list[dict]) -> None:
        """Persist candidate pairs, merging with the current on-disk file.

        ``snapshot`` is this instance's full ``_candidates`` view. Under the
        file lock the on-disk file is re-read; any candidate whose normalised
        pair is unknown to this instance (not in ``_known_candidate_pairs``)
        is preserved, while pairs the instance manages -- including ones it
        popped or removed -- follow the snapshot.
        """
        with self._candidates_write_lock, path_write_lock(self.candidates_path):
            snapshot_pairs = {self._normalize_pair(row["from_id"], row["to_id"]) for row in snapshot}
            merged = list(snapshot)
            for row in self._read_json_list(self.candidates_path):
                from_id, to_id = row.get("from_id"), row.get("to_id")
                if from_id is None or to_id is None:
                    continue
                pair = self._normalize_pair(from_id, to_id)
                if pair in snapshot_pairs:
                    continue
                if pair in self._known_candidate_pairs:
                    # This instance knew this pair and dropped it (pop /
                    # remove / migrate) -> honour the removal.
                    continue
                # Foreign candidate queued by another instance: preserve it,
                # but do NOT register it as managed by us -- otherwise our
                # next flush (snapshot lacks it) would treat it as a removal.
                merged.append(row)
            self._atomic_json_write(self.candidates_path, merged)

    def _flush_pending_judge(self, snapshot: list[str]) -> None:
        """Persist pending-judge ids, merging with the current on-disk file.

        ``snapshot`` is this instance's full durable view: queued
        (``_pending_judge``) plus claimed-but-unsettled (``_inflight_judge``)
        ids. Under the file lock the on-disk file is re-read; any id unknown to
        this instance (not in ``_known_pending_judge``) is preserved, while ids
        the instance manages -- including ones it acked or removed -- follow
        the snapshot.

        Enqueue generations make an ack ownership-aware. Every enqueue stamps
        its id with a fresh token (``_judge_gen``); a claim is "this id under
        the generation I hold". A snapshot built by an ack
        (:class:`_PendingSnapshot` with ``acked``) drops an on-disk id only if
        its generation is still the one this instance claimed. A different
        generation means another instance enqueued the id again after the
        claim -- a fresh judgement request this ack knows nothing about -- so
        the row is kept and handed back to the "foreign" side (forgotten in
        ``_known_pending_judge``) so no later flush of ours drops it either.

        On disk the ids stay a plain list of strings (old readers and the
        pre-generation code keep working); the generations ride in one trailing
        ``{"gen": {id: token}}`` row that old code ignores. An id without a
        generation (a file from before this field existed, or rewritten by old
        code) is generation ``None``: "claimed before any later enqueue".
        """
        if self.pending_judge_path is None:
            return
        with self._pending_judge_write_lock, path_write_lock(self.pending_judge_path):
            fresh = getattr(snapshot, "gens", {})
            acked = getattr(snapshot, "acked", frozenset())
            disk_ids, disk_gens = _split_pending_rows(self._read_json_list(self.pending_judge_path))
            merged = set(snapshot)
            gens = {rid: g for rid in merged if (g := fresh.get(rid, self._judge_gen.get(rid))) is not None}
            forgotten: set[str] = set()
            for rid in disk_ids:
                if rid in merged:
                    continue
                if rid in self._known_pending_judge:
                    if rid not in acked or disk_gens.get(rid) == self._judge_gen.get(rid):
                        # This instance knew this id and dropped it -> honour it.
                        continue
                    # Enqueued again by someone else after our claim: keep it.
                    forgotten.add(rid)
                # Foreign id queued by another instance: preserve it, but do
                # NOT register it as managed by us.
                merged.add(rid)
                if (g := disk_gens.get(rid)) is not None:
                    gens[rid] = g
            rows: list[Any] = sorted(merged)
            if gens:
                rows.append({_GEN_ROW_KEY: gens})
            self._atomic_json_write(self.pending_judge_path, rows, indent=None)
            self._known_pending_judge -= forgotten

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

    def _save_pending_judge(self) -> None:
        if self.pending_judge_path is None:
            return
        self._flush_pending_judge(sorted(self._pending_judge | self._inflight_judge))
