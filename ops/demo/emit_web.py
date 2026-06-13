"""Emitter: demo SoT -> web app generated seed modules.

STUB (Phase A). The mapping contract below is authoritative; the Phase-B filler
implements `emit()` against it with zero further design decisions.

OUTPUT PATH(S)
  web/src/data/seeds/account.generated.ts
  web/src/data/seeds/vocabulary.generated.ts
  (a single combined `*.generated.ts` per domain; the hand-authored
  account.seed.ts / vocabulary.seed.ts are SUPERSEDED — the generated files
  become the new import target via seeds/index.ts.)

  All generated files carry a `// @generated from ops/demo SoT — do not edit`
  banner; `check=True` re-emits to a string and byte-compares against the
  committed file, exit 1 on drift.

MAPPING  (SoT key  ->  web export)
  ACCOUNT  (from identity)
    ACCOUNT_SEED.userId          <- identity.user_id
    ACCOUNT_SEED.email           <- identity.email
    ACCOUNT_SEED.displayName     <- identity.display_name
    ACCOUNT_SEED.accessToken     <- identity.access_token
    ACCOUNT_SEED.linkedIds       <- [identity.provider_user_id]
    ACCOUNT_SEED.deletedDirs     <- ["/data/users/" + identity.user_id]
    SEED_NOW_ISO                 <- dataset.review_anchor   (single synthetic "now")

  NOTEBOOKS  (from dataset.notebooks, JOIN KEY = notebook NAME)
    For each dataset notebook (in declared order, sortOrder = index+1) plus the
    implicit "default" notebook (sortOrder 0, isDefault true):
      NotebookSeed.id            <- slug(name)            (stable id from NAME)
      NotebookSeed.name          <- notebook.name
      NotebookSeed.color         <- notebook.color
      NotebookSeed.coverPattern  <- notebook.cover_pattern
      NotebookSeed.cardCount     <- count of dataset.cards whose notebook == name
    The implicit default notebook is emitted only if any card targets "default"
    (this dataset puts every card in a named notebook, so default cardCount = 0;
    keep the default entry, isDefault true, for parity with the legacy shape).

  VOCAB CARDS  (from dataset.cards)
    VocabCardSeed.id             <- "card-" + (1-based index)
    VocabCardSeed.word           <- card.content
    VocabCardSeed.meaning        <- card.meaning
    VocabCardSeed.pos            <- strip-dot(card.pos)   ("n." -> "n", null -> null)
    VocabCardSeed.notebookId     <- slug(card.notebook)   (NAME -> same id as above)

  GRAPH LINKS  (from dataset.links)
    GraphLinkSeed.id             <- "link-" + (1-based index)
    GraphLinkSeed.fromId         <- id of the card whose content == link.from within link.notebook
    GraphLinkSeed.toId           <- id of the card whose content == link.to within link.notebook
    GraphLinkSeed.kind           <- link.kind
    GraphLinkSeed.confidence     <- link.confidence
    GraphLinkSeed.reason         <- link.reason
    GraphLinkSeed.hidden         <- false
    GraphLinkSeed.notebookId     <- slug(link.notebook)

  REVIEW EVENT LOG  (synthetic window params; anchored to review_anchor)
    REVIEW_EVENT_LOG_SEED.anchorIso   <- dataset.review_anchor
    REVIEW_EVENT_LOG_SEED.words       <- first N card.content (deterministic sample)
    REVIEW_EVENT_LOG_SEED.windowDays  <- 42 (preserve legacy default)
    (the deterministic 42-day generation stays in the web transformer.)

slug(name): lower-case, non-alphanumerics -> "-", collapse repeats, trim "-".
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .sot import DemoSoT


def emit(sot: DemoSoT, *, check: bool = False, commit: bool = False) -> dict:
    """Emit web generated seed modules from the demo SoT.

    Args:
        sot: validated DemoSoT bundle (identity + dataset).
        check: re-emit in memory and byte-compare against the committed
            artifact(s); return a drift report instead of writing.
        commit: write the generated file(s) to disk. When False (and check
            False), this is a dry-run that returns the planned output paths.

    Returns:
        A dict describing the action (paths written / drift verdict).

    Raises:
        NotImplementedError: Phase A stub. See module docstring for the exact
            mapping contract the Phase-B implementation must honor.
    """
    raise NotImplementedError(
        "emit_web.emit is a Phase-A stub; see module docstring for the SoT->web mapping"
    )
