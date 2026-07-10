"""Server-side copy of a shared deck into a copier's private Notebook (Phase 2).

Clones the official deck's **content plane** into fresh Cards in the copier's
``user_dir`` — never SRS, never an LLM call. Every load-bearing guardrail lives
here so the router stays a thin adapter:

* **new Notebook**: ``is_default`` forced false (model default), name made
  unique against the copier's active notebooks (the world-export duplicate-name
  trap), provenance (``source_shared_deck_id`` + ``source_version``) stamped.
* **RAW card copy**: verbatim content fields via ``CardStore.add_shared_copy``,
  model-default SRS, freshly-minted ids, **strictly-monotonic ``updated_at``**
  (§4.4 — a timestamp tie lets a keyset page boundary silently drop cards on
  sync-down), and ``source_shared_card_guid`` = the source card's ``content_guid``.
* **idempotency**: ``shared_deck_copy_log(copier_id, idempotency_key)`` UNIQUE —
  a transport retry replays to the same notebook, never a duplicate.
* **materialization barrier + compensating rollback**: cards.db / notebooks.db
  have no cross-file transaction, so the notebook is staged HIDDEN and revealed
  only after the idempotency log commits. Any pre-commit failure compensates
  (hard-deletes the partial notebook + cards) and re-raises. The copy_log is the
  point of no return: written BEFORE reveal, so a crash in the reveal window
  self-heals — the retry finds the log and _replay reveals the still-hidden
  notebook, never minting a duplicate.
* **count-equality**: copied distinct cards == source snapshot, else fail-loud
  (a NOCASE/NFC collapse under the card table's per-notebook uniqueness — e.g. a
  homograph pair distinct only by pos/meaning — must not silently drop a card).
* **graph links remap seam**: an official ``shared_deck_card`` is a pure content
  plane with ZERO inter-card links (§2), so remap is a structural no-op today;
  the old→new id map is still built so a future link-carrying schema flows
  through :func:`_remap_graph_links` unchanged. We do NOT synthesize links.
* **download_count**: atomic SQL increment (never Python get-then-set).
"""
from __future__ import annotations

import json
import logging
import threading
from collections import OrderedDict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from ..cards import CardStore
from ..exceptions import ConflictError, NotFoundError
from ..notebook import NotebookStore
from .store import SharedDeck, SharedDeckStore

_LOGGER = logging.getLogger(__name__)

_DEFAULT_TITLE = "Untitled Deck"

# Per-user copy serialization (see _user_copy_lock). LRU-bounded so a burst of
# distinct users cannot leak locks without limit — mirrors deps._USER_LOCKS.
_USER_COPY_LOCKS: OrderedDict[str, threading.Lock] = OrderedDict()
_USER_COPY_LOCKS_MUTEX = threading.Lock()
_MAX_USER_COPY_LOCKS = 500


def _user_copy_lock(user_dir: Path) -> threading.Lock:
    """Per-user serialization lock for the copy critical section.

    ``deps.get_user_lock`` is an ``asyncio.Lock`` serving the async pipeline; it
    cannot serialize the copy handler, which is a SYNC endpoint running in
    anyio's threadpool (concurrent same-user copies land on different threads).
    This is the faithful threading translation of that same per-user pattern:
    an LRU-bounded, mutex-guarded registry keyed by the user's dir (the mutated
    resource). ``move_to_end`` on access keeps an in-flight lock recently-used
    so it is never the eviction victim while still held.
    """
    key = str(Path(user_dir).resolve())
    with _USER_COPY_LOCKS_MUTEX:
        lock = _USER_COPY_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _USER_COPY_LOCKS[key] = lock
            while len(_USER_COPY_LOCKS) > _MAX_USER_COPY_LOCKS:
                _USER_COPY_LOCKS.popitem(last=False)
        else:
            _USER_COPY_LOCKS.move_to_end(key)
        return lock


@dataclass(frozen=True)
class CopyOutcome:
    notebook_id: str
    notebook_name: str
    deck_id: str
    source_version: int
    card_count: int
    already_copied: bool


def _unique_notebook_name(notebook_store: NotebookStore, base: str) -> str:
    """Disambiguate ``base`` against the copier's ACTIVE notebook names.

    world-export fails loud on two same-named active notebooks (its name→id map
    can't tell them apart), so a second copy of the same deck must not reuse the
    title verbatim. The staged copy notebook is created hidden, so it never
    collides with itself here.
    """
    existing = {nb.name for nb in notebook_store.all()}
    if base not in existing:
        return base
    n = 2
    while f"{base} ({n})" in existing:
        n += 1
    return f"{base} ({n})"


def _remap_graph_links(
    user_dir: Path,
    notebook_id: str,
    *,
    source_links: Sequence[dict],
    id_map: dict[str, str],
) -> None:
    """Remap old→new card ids for any inter-card links the source deck carries,
    persisting ``graph_<nb>.json``.

    Official shared decks carry ZERO links (the ``shared_deck_card`` table is a
    pure content plane, §2), so ``source_links`` is always empty here and this is
    a structural no-op — no graph file is written. The seam exists so a future
    link-carrying deck schema flows through unchanged; DO NOT synthesize links
    for a link-less deck.
    """
    if not source_links:
        return
    remapped = [
        {**lk, "from_id": id_map[lk["from_id"]], "to_id": id_map[lk["to_id"]]}
        for lk in source_links
        if lk.get("from_id") in id_map and lk.get("to_id") in id_map
    ]
    if remapped:
        (user_dir / f"graph_{notebook_id}.json").write_text(
            json.dumps(remapped, ensure_ascii=False), encoding="utf-8"
        )


def _compensate(
    card_store: CardStore,
    notebook_store: NotebookStore,
    user_dir: Path,
    notebook_id: str,
) -> None:
    """Best-effort teardown of a partially-materialized copy. Runs on any failure
    before the copy_log is committed; swallows secondary errors so the original
    fault propagates."""
    try:
        card_store.hard_delete_by_notebook(notebook_id)
    except Exception:  # noqa: BLE001 — compensation must not mask the root fault
        _LOGGER.warning("copy compensation: card cleanup failed for %s", notebook_id, exc_info=True)
    try:
        notebook_store.hard_delete(notebook_id)
    except Exception:  # noqa: BLE001
        _LOGGER.warning("copy compensation: notebook cleanup failed for %s", notebook_id, exc_info=True)
    try:
        (user_dir / f"graph_{notebook_id}.json").unlink(missing_ok=True)
    except OSError:
        _LOGGER.warning("copy compensation: graph cleanup failed for %s", notebook_id, exc_info=True)


def _replay(
    shared_store: SharedDeckStore,
    notebook_store: NotebookStore,
    card_store: CardStore,
    log,
    deck_id: str,
) -> CopyOutcome:
    # Defensive re-materialize: if a prior copy crashed in the window between
    # record_copy (committed) and materialize, the notebook is still hidden. The
    # retry that lands here reveals it — self-healing, and a no-op once visible.
    notebook_store.materialize(log.result_notebook_id)
    nb = notebook_store.get(log.result_notebook_id)
    return CopyOutcome(
        notebook_id=log.result_notebook_id,
        notebook_name=nb.name if nb is not None else "",
        deck_id=deck_id,
        source_version=log.source_version,
        card_count=card_store.count(notebook_id=log.result_notebook_id),
        already_copied=True,
    )


def copy_shared_deck(
    *,
    shared_store: SharedDeckStore,
    card_store: CardStore,
    notebook_store: NotebookStore,
    user_dir: Path,
    deck_id: str,
    copier_id: str,
    idempotency_key: str,
    notebook_name: str | None = None,
    now: datetime | None = None,
    _on_card: Callable[[int], None] | None = None,
) -> CopyOutcome:
    """Copy an official/public deck into the copier's private notebook.

    ``_on_card(i)`` is an internal test hook fired after each card insert; a test
    raises from it to exercise the mid-copy compensation path.
    """
    now = now or datetime.now(UTC)

    deck = shared_store.get(deck_id)
    if deck is None:  # not discoverable → 404 (never leak hidden decks)
        raise NotFoundError("Deck", deck_id)

    # Serialize per-user copies (see _user_copy_lock): the copy handler is a SYNC
    # FastAPI endpoint, so two concurrent same-user copies run on separate
    # threadpool threads. Without this lock they would both read the pre-create
    # notebook snapshot, compute the SAME unique name, and both INSERT → two
    # same-named active notebooks → world-export's name→id map collapses (§2 name
    # uniqueness is mandatory). Held through materialize so the second copy sees
    # the first's committed notebook and disambiguates to "X (2)".
    with _user_copy_lock(user_dir):
        return _copy_locked(
            shared_store=shared_store, card_store=card_store,
            notebook_store=notebook_store, user_dir=user_dir, deck=deck,
            copier_id=copier_id, idempotency_key=idempotency_key,
            notebook_name=notebook_name, now=now, _on_card=_on_card,
        )


def _copy_locked(
    *,
    shared_store: SharedDeckStore,
    card_store: CardStore,
    notebook_store: NotebookStore,
    user_dir: Path,
    deck: SharedDeck,
    copier_id: str,
    idempotency_key: str,
    notebook_name: str | None,
    now: datetime,
    _on_card: Callable[[int], None] | None,
) -> CopyOutcome:
    """The per-user-serialized body of :func:`copy_shared_deck`, executed while
    holding the per-user copy lock. ``deck`` is the already-resolved discoverable
    deck; every user-dir mutation (name-compute → create → card copy →
    record_copy → materialize) happens here so a concurrent same-user copy is
    fully queued behind it."""
    # Idempotent replay: a prior copy with this key short-circuits (no new work,
    # no second download count) — transport-retry safety.
    prior = shared_store.get_copy_log(copier_id, idempotency_key)
    if prior is not None:
        return _replay(shared_store, notebook_store, card_store, prior, deck.id)

    version = deck.current_version
    src_cards = shared_store.all_cards(deck.id, version=version)
    source_count = len(src_cards)

    base_name = (notebook_name or "").strip() or (deck.title or "").strip() or _DEFAULT_TITLE
    unique_name = _unique_notebook_name(notebook_store, base_name)

    # Stage the notebook HIDDEN (barrier) with provenance; revealed only after
    # every card lands + count-equality holds.
    nb = notebook_store.create(
        name=unique_name, color=deck.color, cover_pattern=deck.cover_pattern,
        source_shared_deck_id=deck.id, source_version=version, is_deleted=True,
    )

    id_map: dict[str, str] = {}
    created = 0
    try:
        for i, sc in enumerate(src_cards):
            card, was_created = card_store.add_shared_copy(
                content=sc.content, meaning=sc.meaning, pos=sc.pos,
                examples=sc.examples, collocations=sc.collocations, note=sc.note,
                difficulty=sc.difficulty, mode=sc.mode, root_form=sc.root_form,
                inflections=sc.inflections, notebook_id=nb.id,
                # strictly-monotonic, distinct per card (§4.4 tie defense)
                updated_at=now + timedelta(milliseconds=i),
                source_shared_card_guid=sc.content_guid,
            )
            id_map[sc.content_guid] = card.id
            if was_created:
                created += 1
            if _on_card is not None:
                _on_card(i)

        if created != source_count:
            # A NOCASE/NFC collapse merged two source cards into one row — fail
            # loud rather than hand back a lossy deck.
            raise ConflictError(
                f"deck copy card-count mismatch: materialized {created} of "
                f"{source_count} (content collision under per-notebook uniqueness)"
            )

        # No-op for official decks (zero links); seam kept honest for the future.
        _remap_graph_links(user_dir, nb.id, source_links=(), id_map=id_map)
    except Exception:
        # Everything above is pre-commit: no copy_log points at this notebook yet,
        # so compensation can safely erase the whole partial copy.
        _compensate(card_store, notebook_store, user_dir, nb.id)
        raise

    # ── point of no return ─────────────────────────────────────────
    # Commit the idempotency log BEFORE revealing the notebook. If a concurrent
    # request with the same key won the race, roll OUR copy back and replay to
    # theirs (never two notebooks). Ordering matters: were the notebook revealed
    # first, a crash before record_copy would leave a visible copy with no log →
    # a retry would mint a SECOND notebook (the duplicate idempotency exists to
    # prevent). With the log first, a crash before materialize self-heals — the
    # retry finds the log and _replay reveals the still-hidden notebook.
    if not shared_store.record_copy(copier_id, idempotency_key, deck.id, version, nb.id):
        _compensate(card_store, notebook_store, user_dir, nb.id)
        winner = shared_store.get_copy_log(copier_id, idempotency_key)
        if winner is not None:
            return _replay(shared_store, notebook_store, card_store, winner, deck.id)
        # Extremely unlikely (row vanished between conflict and re-read); surface
        # it rather than pretend success.
        raise ConflictError("deck copy idempotency conflict could not be resolved")

    # Post-commit finalizers — best-effort, never compensated (rolling back after
    # the idempotency log is committed would strand its pointer). A crash here is
    # recovered by the next retry via _replay.
    notebook_store.materialize(nb.id)
    shared_store.increment_download_count(deck.id)
    return CopyOutcome(
        notebook_id=nb.id, notebook_name=unique_name, deck_id=deck.id,
        source_version=version, card_count=created, already_copied=False,
    )


__all__ = ["CopyOutcome", "copy_shared_deck"]
