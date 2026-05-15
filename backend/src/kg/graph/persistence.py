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
- Blocked pairs are unioned with the on-disk set.

``_flush_candidates`` / ``_flush_pending_judge`` hold transient pre-judge
state (pop-style, cleared as a unit); they run under the same file lock so
the ``tmp -> bak -> replace`` rename is never interleaved across instances,
but they intentionally keep last-writer-wins semantics.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from .filelock import path_write_lock
from .models import CandidatePair, GraphLink

logger = logging.getLogger(__name__)


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
    _links_write_lock: Any
    _candidates_write_lock: Any
    _blocked_write_lock: Any
    _pending_judge_write_lock: Any

    @staticmethod
    def _atomic_json_write(path: Path, data: Any, *, indent: int | None = 2) -> None:
        """Atomic JSON write: tmp -> bak -> replace."""
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=indent, ensure_ascii=False))
        if path.exists():
            path.replace(path.with_suffix(".json.bak"))
        tmp.replace(path)

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
        return [lk.model_dump(mode="json") for lk in self._links.values()]

    def _candidates_to_serializable(self) -> list[dict]:
        return [c.model_dump(mode="json") for c in self._candidates]

    def _blocked_to_serializable(self) -> list[list[str]]:
        return [list(pair) for pair in self._blocked_pairs]

    # ------------------------------------------------------------------
    # Per-file serialised write helpers.
    #
    # Each acquires (a) the in-process file-level write lock and (b) the
    # cross-process fcntl advisory lock on the path. _flush_links and
    # _flush_blocked additionally re-read + merge under that lock so a
    # stale instance cannot clobber another's durable changes.
    # ------------------------------------------------------------------

    def _flush_links(self, snapshot: list[dict]) -> None:
        """Persist links, merging with the current on-disk file.

        ``snapshot`` is this instance's full ``_links`` view. Under the file
        lock the on-disk file is re-read; any link unknown to this instance
        (``id`` not in ``_known_link_ids``) is preserved, while ids the
        instance manages -- including ones it deleted -- follow the snapshot.
        """
        with self._links_write_lock, path_write_lock(self.links_path):
            snapshot_ids = {row["id"] for row in snapshot}
            merged = list(snapshot)
            for row in self._read_json_list(self.links_path):
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

    def _flush_blocked(self, snapshot: list[list[str]]) -> None:
        """Persist blocked pairs as the union of memory + on-disk state."""
        if self.blocked_path is None:
            return
        with self._blocked_write_lock, path_write_lock(self.blocked_path):
            merged: set[tuple[str, str]] = {tuple(p) for p in snapshot}  # type: ignore[misc]
            for row in self._read_json_list(self.blocked_path):
                if isinstance(row, list) and len(row) == 2:
                    merged.add(tuple(row))  # type: ignore[arg-type]
            self._atomic_json_write(
                self.blocked_path, [list(p) for p in merged], indent=None
            )

    def _flush_candidates(self, snapshot: list[dict]) -> None:
        """Persist candidate pairs (transient pre-judge state, last-writer-wins)."""
        with self._candidates_write_lock, path_write_lock(self.candidates_path):
            self._atomic_json_write(self.candidates_path, snapshot)

    def _flush_pending_judge(self, snapshot: list[str]) -> None:
        """Persist pending-judge ids (transient pre-judge state, last-writer-wins)."""
        if self.pending_judge_path is None:
            return
        with self._pending_judge_write_lock, path_write_lock(self.pending_judge_path):
            self._atomic_json_write(self.pending_judge_path, snapshot, indent=None)

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
