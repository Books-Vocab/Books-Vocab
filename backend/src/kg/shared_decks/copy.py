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
  only at the last moment; any mid-copy failure compensates (hard-deletes the
  partial notebook + cards) and re-raises — no half-product survives even an
  uncaught crash (the copy_log is written last, so a retry re-copies cleanly).
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
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from ..cards import CardStore
from ..exceptions import ConflictError, NotFoundError
from ..notebook import NotebookStore
from .store import SharedDeckStore

_LOGGER = logging.getLogger(__name__)

_DEFAULT_TITLE = "Untitled Deck"


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

        # Reveal the barrier — the notebook becomes visible only now.
        notebook_store.materialize(nb.id)
    except Exception:
        _compensate(card_store, notebook_store, user_dir, nb.id)
        raise

    # Commit idempotency LAST. If a concurrent request with the same key won the
    # race, roll our copy back and replay to theirs (never two notebooks).
    if not shared_store.record_copy(copier_id, idempotency_key, deck.id, version, nb.id):
        _compensate(card_store, notebook_store, user_dir, nb.id)
        winner = shared_store.get_copy_log(copier_id, idempotency_key)
        if winner is not None:
            return _replay(shared_store, notebook_store, card_store, winner, deck.id)
        # Extremely unlikely (row vanished between conflict and re-read); surface
        # it rather than pretend success.
        raise ConflictError("deck copy idempotency conflict could not be resolved")

    shared_store.increment_download_count(deck.id)
    return CopyOutcome(
        notebook_id=nb.id, notebook_name=unique_name, deck_id=deck.id,
        source_version=version, card_count=created, already_copied=False,
    )


__all__ = ["CopyOutcome", "copy_shared_deck"]
