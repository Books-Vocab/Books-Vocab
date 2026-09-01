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
  instance has ever held authoritative, so a pop/removal still takes effect.
- An id/pair present on disk but unknown to the instance (queued by another
  instance) is preserved instead of being clobbered.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Any

from .._fsutil import fsync_dir as _fsync_dir
from .filelock import path_write_lock
from .models import CandidatePair, GraphLink

logger = logging.getLogger(__name__)


class _LinkSnapshot(list[dict]):
    """Serializable link snapshot carrying its in-memory mutation order."""

    def __init__(self, rows: list[dict], sequence: int) -> None:
        super().__init__(rows)
        self.sequence = sequence


class _PersistenceMixin:
    """Atomic write + snapshot + flush helpers for :class:`GraphStore`."""

    # Attributes provided by GraphStore.__init__ -- declared for type checkers.
    links_path: Path
    candidates_path: Path
    blocked_path: Path | None
    pending_judge_path: Path | None
    _links: dict[str, GraphLink]
    _candidates: list[CandidatePair]
    _blocked_pairs: set[tuple[str, str]]
    _pending_judge: set[str]
    _known_link_ids: set[str]
    _known_blocked_pairs: set[tuple[str, str]]
    _known_pending_judge: set[str]
    _known_candidate_pairs: set[tuple[str, str]]
    _links_snapshot_sequence: int
    _last_flushed_links_snapshot_sequence: int
    _links_write_lock: threading.Lock
    _candidates_write_lock: threading.Lock
    _blocked_write_lock: threading.Lock
    _pending_judge_write_lock: threading.Lock

    # Helper supplied by GraphStore.
    @staticmethod
    def _normalize_pair(a: str, b: str) -> tuple[str, str]: ...  # noqa: D102

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
    def _read_json_list(path: Path) -> list:
        """Read a JSON array from disk, tolerating absence / corruption.

        Returns ``[]`` for a missing file. A corrupt file falls back to its
        ``.bak`` sibling; if that also fails, returns ``[]`` rather than
        raising, so a single bad write cannot wedge every future flush.
        """
        for candidate in (path, path.with_suffix(".json.bak")):
            if not candidate.exists():
                continue
            try:
                data = json.loads(candidate.read_text())
                if isinstance(data, list):
                    return data
            except (json.JSONDecodeError, OSError, UnicodeDecodeError):
                logger.warning("graph: corrupt JSON at %s, trying fallback", candidate)
        return []

    # Snapshot helpers -- call inside lock, return serialisable data
    def _links_to_serializable(self) -> list[dict]:
        sequence = getattr(self, "_links_snapshot_sequence", 0) + 1
        self._links_snapshot_sequence = sequence
        return _LinkSnapshot([lk.model_dump(mode="json") for lk in self._links.values()], sequence)

    def _candidates_to_serializable(self) -> list[dict]:
        return [c.model_dump(mode="json") for c in self._candidates]

    def _blocked_to_serializable(self) -> list[list[str]]:
        return [list(pair) for pair in self._blocked_pairs]

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
        """
        with self._links_write_lock, path_write_lock(self.links_path):
            sequence = getattr(snapshot, "sequence", None)
            if sequence is not None and sequence < getattr(self, "_last_flushed_links_snapshot_sequence", 0):
                return
            snapshot_ids = {row["id"] for row in snapshot}
            merged = list(snapshot)
            for row in self._read_json_list(self.links_path):
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
            self._atomic_json_write(self.links_path, merged)
            if sequence is not None:
                self._last_flushed_links_snapshot_sequence = sequence

    def _flush_blocked(self, snapshot: list[list[str]]) -> None:
        """Persist blocked pairs, merging with the current on-disk file.

        ``snapshot`` is this instance's full ``_blocked_pairs`` view. Under the
        file lock the on-disk file is re-read; any pair unknown to this instance
        (not in ``_known_blocked_pairs``) is preserved, while pairs the instance
        manages -- including ones it unblocked -- follow the snapshot. A naive
        union would resurrect a pair the user explicitly unblocked.
        """
        if self.blocked_path is None:
            return
        with self._blocked_write_lock, path_write_lock(self.blocked_path):
            merged: set[tuple[str, str]] = {tuple(p) for p in snapshot}  # type: ignore[misc]
            for row in self._read_json_list(self.blocked_path):
                if not (isinstance(row, list) and len(row) == 2):
                    continue
                pair: tuple[str, str] = tuple(row)  # type: ignore[assignment]
                if pair in merged:
                    continue
                if pair in self._known_blocked_pairs:
                    # This instance knew this pair and dropped it -> honour unblock.
                    continue
                # Foreign pair blocked by another instance: preserve it, but do
                # NOT register it as managed by us -- otherwise our next flush
                # (whose snapshot lacks it) would treat it as an unblock.
                merged.add(pair)
            self._atomic_json_write(self.blocked_path, [list(p) for p in merged], indent=None)

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

        ``snapshot`` is this instance's full ``_pending_judge`` view. Under the
        file lock the on-disk file is re-read; any id unknown to this instance
        (not in ``_known_pending_judge``) is preserved, while ids the instance
        manages -- including ones it popped or removed -- follow the snapshot.
        """
        if self.pending_judge_path is None:
            return
        with self._pending_judge_write_lock, path_write_lock(self.pending_judge_path):
            merged = set(snapshot)
            for rid in self._read_json_list(self.pending_judge_path):
                if not isinstance(rid, str) or rid in merged:
                    continue
                if rid in self._known_pending_judge:
                    # This instance knew this id and dropped it -> honour it.
                    continue
                # Foreign id queued by another instance: preserve it, but do
                # NOT register it as managed by us.
                merged.add(rid)
            self._atomic_json_write(self.pending_judge_path, sorted(merged), indent=None)

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
        self._flush_pending_judge(sorted(self._pending_judge))
