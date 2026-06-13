"""Emitter: demo SoT -> iOS FixtureDatasetDocument + identity constants.

STUB (Phase A). The mapping contract below is authoritative; the Phase-B filler
implements `emit()` against it with zero further design decisions.

OUTPUT PATH(S)
  ops/demo/generated/ios_fixture_dataset.json   (FixtureDatasetDocument JSON)
  ops/demo/generated/ios_identity.json          (identity constants for the app)

  The fixture JSON is injected into the running app via the env var
  KG_FIXTURE_DATASET_B64 (base64 of the JSON file's bytes) — see
  ios/BooksAndVocab/Support/Fixtures/Core/FixtureDatasetStore.swift
  (loadSource(): env KG_FIXTURE_DATASET_B64 first, then /tmp/kg-fixture-dataset.json).
  This emitter writes the *plaintext* JSON; the launcher / test harness base64s
  it into the env var. emit() also prints the ready-to-export base64 when commit.

DOCUMENT SHAPE  (FixtureDatasetDocument top-level keys — exact, see Swift struct)
  schema       <- "kg.fixture_dataset.v1"   (string)
  datasetID    <- "demo-" + identity.user_id
  settings     <- {}   (Phase A: no settings fixtures derived from SoT yet)
  bookshelf    <- {}   (Phase A: no bookshelf fixtures derived from SoT yet)
  todayReview  <- { "demo": TodayReviewSessionSeed }  (see TODAY REVIEW mapping)
  notebook     <- { "demo": NotebookFixtureSeed }     (see NOTEBOOK mapping)
  podcast      <- {}   (Phase A: no podcast fixtures derived from SoT yet)

  Unknown top-level keys are silently ignored by keyed decoding; emit() MUST NOT
  add keys outside FixtureDatasetDocument.knownTopLevelKeys.

NOTEBOOK MAPPING  (SoT dataset -> NotebookFixtureSeed)
  notebook["demo"] = { "notebooks": [ NotebookSeed... ] }, one NotebookSeed per
  dataset notebook (declared order), each:
    NotebookSeed.remoteId    <- slug(notebook.name)        (NAME = stable join key)
    NotebookSeed.name        <- notebook.name
    NotebookSeed.isDefault   <- (index == 0)               (first notebook is default)
    NotebookSeed.sortOrder   <- index
    NotebookSeed.entries     <- [ NotebookEntrySeed for each card with notebook == name ]
      NotebookEntrySeed.word           <- card.content
      NotebookEntrySeed.translation    <- card.meaning
      NotebookEntrySeed.partOfSpeech   <- card.pos          (keep dot, iOS displays raw)
      NotebookEntrySeed.bookTitle      <- card.source.title   (if source present)
      NotebookEntrySeed.chapterTitle   <- card.source.chapter (if source present)
      NotebookEntrySeed.context        <- first card.examples entry, **markup stripped**
      NotebookEntrySeed.explanation    <- card.note          (if present)

TODAY REVIEW MAPPING  (SoT dataset -> TodayReviewSessionSeed)
  todayReview["demo"] is a single session seeded from the cards whose
  review.state == "due" (the actual review queue), in dataset order:
    currentCard      <- TodayReviewCardSeed from the 1st due card
    nextCard         <- TodayReviewCardSeed from the 2nd due card (or null)
    revealStage      <- .front
    progressText     <- "1 / <due-count>"
    remainingCount   <- due-count
    forgotCount/rememberedCount/*FeedbackTrigger <- 0
    canShuffle       <- (due-count > 1); canGoPrevious <- false; canGoNext <- (due-count > 1)
    isAutoPlaying/isAutoPlayPaused <- false; autoplayProgress <- 0.0
    autoplaySpeed    <- default; autoplaySoundEnabled <- true; showFirstRunHint <- false
  TodayReviewCardSeed per due card:
    word          <- card.content
    translation   <- card.meaning
    context       <- first card.examples entry, **markup stripped** ("" if none)
    explanation   <- card.note
    partOfSpeech  <- card.pos
    bookTitle     <- card.source.title ("" if no source)
    chapterTitle  <- card.source.chapter
    dateAdded     <- dataset.review_anchor (ISO8601; decoder accepts ISO string)
    difficultyTier<- bucketed from card.difficulty (e.g. >=5 "hard", >=4 "medium", else "easy")
    reviewMode    <- .recognition (card.mode default)
    reviewExamples<- card.examples with markup stripped
    rootForm      <- null; inflections <- []
    graphLinksByKind <- {} (Phase A: today-review link rollup deferred)

IDENTITY CONSTANTS  (ops/demo/generated/ios_identity.json)
  { "userId": identity.user_id, "email": identity.email,
    "displayName": identity.display_name, "provider": identity.provider,
    "providerUserId": identity.provider_user_id, "accessToken": identity.access_token }

CHECK MODE
  Re-emit both files in memory, byte-compare against the committed artifacts,
  return a drift verdict (exit 1 on drift). Date strings use review_anchor so
  output is deterministic.

slug(name): lower-case, non-alphanumerics -> "-", collapse repeats, trim "-".
**markup stripped**: remove the **word** emphasis markers (keep inner text).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .sot import DemoSoT


def emit(sot: DemoSoT, *, check: bool = False, commit: bool = False) -> dict:
    """Emit the iOS FixtureDatasetDocument JSON + identity constants from the SoT.

    Args:
        sot: validated DemoSoT bundle (identity + dataset).
        check: re-emit in memory and byte-compare against the committed
            artifact(s); return a drift report instead of writing.
        commit: write the generated file(s) to disk (and print the base64 the
            harness exports as KG_FIXTURE_DATASET_B64). When False (and check
            False), dry-run returning the planned output paths.

    Returns:
        A dict describing the action (paths written / drift verdict / base64).

    Raises:
        NotImplementedError: Phase A stub. See module docstring for the exact
            FixtureDatasetDocument mapping the Phase-B implementation must honor.
    """
    raise NotImplementedError(
        "emit_ios.emit is a Phase-A stub; see module docstring for the SoT->iOS fixture mapping"
    )
