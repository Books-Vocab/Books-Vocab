"""Startup reaper for orphaned staged shared-deck copies (#2269).

A copy stages its notebook hidden (``is_staged``) and compensates on any
in-process failure. A hard crash between staging and compensation (or between
the cards landing and ``record_copy``) leaves a staged notebook with committed
cards and no ``shared_deck_copy_log`` row — invisible but never cleaned. This
sweep compensates those: cards tombstoned, notebook row and graph file removed.

A staged notebook WITH a copy_log row is a committed copy awaiting reveal; the
retry's ``_replay`` self-heals it, so it is left alone, as is anything younger
than ``older_than`` (a live copy may still be running).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

from ..cards import CardStore
from ..notebook import NotebookStore
from .copy import compensate_staged_copy
from .store import SharedDeckStore

_LOGGER = logging.getLogger(__name__)

DEFAULT_STALE_AFTER = timedelta(minutes=10)


def reap_stale_staged_copies(data_root: Path, *, older_than: timedelta = DEFAULT_STALE_AFTER) -> int:
    """Compensate stale, un-logged staged notebooks under ``data_root``.
    Returns the number of notebooks reaped. Per-user failures are logged and
    skipped so one bad user dir cannot block startup."""
    users_dir = data_root / "users"
    if not users_dir.is_dir():
        return 0
    cutoff = datetime.now(UTC) - older_than
    shared = SharedDeckStore(data_root / "shared_decks.db")
    reaped = 0
    try:
        for user_dir in sorted(p for p in users_dir.iterdir() if (p / "notebooks.db").is_file()):
            notebooks = NotebookStore(user_dir / "notebooks.db")
            cards = None
            try:
                for notebook_id in notebooks.staged_older_than(cutoff):
                    if shared.has_copy_log_for_notebook(notebook_id):
                        continue
                    if cards is None:
                        cards = CardStore(user_dir / "cards.db")
                    compensate_staged_copy(cards, notebooks, user_dir, notebook_id)
                    reaped += 1
            except Exception:  # noqa: BLE001 — never block startup on one user
                _LOGGER.warning("staged copy reaper failed for %s", user_dir.name, exc_info=True)
            finally:
                notebooks.close()
                if cards is not None:
                    cards.close()
    finally:
        shared.close()
    return reaped
