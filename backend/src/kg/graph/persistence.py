"""Disk persistence helpers for the graph store.

Provides the ``_PersistenceMixin`` which encapsulates atomic JSON writes,
in-memory -> serialisable snapshot conversion, and per-file serialised
flush helpers. Disk I/O always happens *outside* the in-memory lock.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import CandidatePair, GraphLink


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
        self._flush_pending_judge(sorted(self._pending_judge))
