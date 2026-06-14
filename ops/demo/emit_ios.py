"""Emitter: demo SoT -> iOS UI World FixtureDatasetDocument.

Phase B implementation. Mirrors the Phase-A mapping contract below, byte-for-byte
deterministic so `--check` is a true drift gate.

OUTPUT PATH(S)
  ops/demo/generated/ios_fixture_dataset.json   (FixtureDatasetDocument JSON)

INJECTION SEAM (no Swift logic change to the loader)
  The fixture JSON is injected into the running app via the env var
  KG_FIXTURE_DATASET_B64 (base64 of the JSON file's bytes) — see
  ios/BooksAndVocab/Support/Fixtures/Core/FixtureDatasetStore.swift
  This emitter writes the *plaintext* JSON; the UITest harness base64s it into the
  env var via the existing seam:
      ./ops/ios_test.sh --ui --dataset-file ops/demo/generated/ios_fixture_dataset.json ...
  ios_test.sh base64-encodes the file into the runner's KG_FIXTURE_DATASET_B64, and
  UITestAppLaunch.swift (UITestLaunchConfiguration.launchEnvironment) already forwards
  that var into the app process. emit() also prints the ready-to-export base64 when
  commit so it can be exported directly without the shell helper.

SCHEMA NOTE
  The Phase-A skeleton planned schema "kg.fixture_dataset.v1". The Swift SoT
  (FixtureDatasetStore.decode + RepoFixtureDatasetsContractTests) is authoritative.
  Repo UI Worlds now use "kg.fixture.dataset.v2", which adds the top-level
  asset manifest. This generated demo world has no file-backed assets yet, so it
  emits an empty manifest instead of omitting the domain.

DOCUMENT SHAPE  (FixtureDatasetDocument top-level keys — exact, see Swift struct)
  schema       <- "kg.fixture.dataset.v2"
  datasetID    <- "demo-" + identity.user_id
  assets       <- empty asset manifest (no file-backed demo assets yet)
  auth         <- signedIn/guest login state from demo identity
  entitlements <- free/pro subscription states
  settings     <- {}   (no settings fixtures derived from SoT yet)
  bookshelf    <- {}   (no bookshelf fixtures derived from SoT yet)
  todayReview  <- { "front": TodayReviewSessionSeed }  (see TODAY REVIEW mapping)
  notebook     <- { "populated": NotebookFixtureSeed } (see NOTEBOOK mapping)
  podcast      <- {}   (no podcast fixtures derived from SoT yet)
  runtimePodcast <- {} (no runtime podcast fixtures derived from SoT yet)
  reader       <- {}   (no reader fixtures derived from SoT yet)
  vocabulary   <- {}   (no runtime vocabulary fixtures derived from SoT yet)
  reviewDeck   <- {}   (no review-deck fixtures derived from SoT yet)

  Keyed decoding silently ignores unknown top-level keys; emit() MUST NOT add keys
  outside FixtureDatasetDocument.knownTopLevelKeys, and the domain sub-keys must be
  declared fixture IDs (NotebookFixtureID / TodayReviewFixtureID).

NOTEBOOK MAPPING  (SoT dataset -> NotebookFixtureSeed, keyed under "populated")
  notebook["populated"] = { "notebooks": [ NotebookSeed... ] }, one NotebookSeed per
  dataset notebook (declared order), each:
    NotebookSeed.remoteId    <- slug(notebook.name)        (NAME = stable join key)
    NotebookSeed.name        <- notebook.name
    NotebookSeed.isDefault   <- (index == 0)               (first notebook is default)
    NotebookSeed.sortOrder   <- index
    NotebookSeed.entries     <- [ NotebookEntrySeed for each card with notebook == name ]
      NotebookEntrySeed.word           <- card.content
      NotebookEntrySeed.translation    <- card.meaning
      NotebookEntrySeed.context        <- first card.examples entry, markup stripped
      NotebookEntrySeed.explanation    <- card.note          (if present)
      NotebookEntrySeed.partOfSpeech   <- card.pos           (keep dot, iOS displays raw)
      NotebookEntrySeed.bookTitle      <- card.source.title  (if source present)
      NotebookEntrySeed.chapterTitle   <- card.source.chapter (if source present)

TODAY REVIEW MAPPING  (SoT dataset -> TodayReviewSessionSeed, keyed under "front")
  todayReview["front"] is a single session seeded from the cards whose
  review.state == "due" (the actual review queue), in dataset order:
    currentCard      <- TodayReviewCardSeed from the 1st due card
    nextCard         <- TodayReviewCardSeed from the 2nd due card (or null)
    revealStage      <- "front"
    progressText     <- "1 / <due-count>"
    remainingCount   <- due-count
    forgotCount/rememberedCount/*FeedbackTrigger <- 0
    canShuffle       <- (due-count > 1); canGoPrevious <- false; canGoNext <- (due-count > 1)
    isAutoPlaying/isAutoPlayPaused <- false; autoplayProgress <- 0.0
    autoplaySpeed    <- "normal"; autoplaySoundEnabled <- true; showFirstRunHint <- false
  TodayReviewCardSeed per due card:
    word          <- card.content
    translation   <- card.meaning
    context       <- first card.examples entry, markup stripped ("" if none)
    explanation   <- card.note (null if absent)
    partOfSpeech  <- card.pos
    bookTitle     <- card.source.title ("" if no source)
    chapterTitle  <- card.source.chapter (null if absent)
    dateAdded     <- dataset.review_anchor (ISO8601 string; decoder accepts it)
    difficultyTier<- bucketed from card.difficulty (>=5 "hard", >=4 "medium", else "easy")
    reviewMode    <- "recognition" (card.mode default)
    reviewExamples<- card.examples with markup stripped
    rootForm      <- null; inflections <- []
    graphLinksByKind <- {} (today-review link rollup deferred)

CHECK MODE
  Re-emit the UI World file in memory, byte-compare against the committed artifact,
  return a drift verdict (exit 1 on drift via build_demo.py). Date strings use
  review_anchor so output is deterministic.

slug(name): lower-case, non-alphanumerics -> "-", collapse repeats, trim "-".
markup stripped: remove the **emphasis** markers (keep inner text).
"""

from __future__ import annotations

import base64
import json
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sot import DemoSoT

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parent.parent  # ops/demo -> ops -> repo root

GENERATED_DIR = _HERE / "generated"
FIXTURE_JSON_PATH = GENERATED_DIR / "ios_fixture_dataset.json"

FIXTURE_SCHEMA = "kg.fixture.dataset.v2"
NOTEBOOK_FIXTURE_KEY = "populated"  # NotebookFixtureID.populated
TODAY_REVIEW_FIXTURE_KEY = "front"  # TodayReviewFixtureID.front

# **emphasis** markers used in SoT example sentences; stripped for display seeds.
_EMPHASIS_RE = re.compile(r"\*\*(.+?)\*\*")
_SLUG_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")


def _strip_markup(text: str) -> str:
    """Remove **emphasis** markers, keep inner text."""
    return _EMPHASIS_RE.sub(r"\1", text)


def _slug(name: str) -> str:
    """lower-case, non-alphanumerics -> '-', collapse repeats, trim '-'."""
    return _SLUG_NON_ALNUM_RE.sub("-", name.lower()).strip("-")


def _first_example(card: dict[str, Any]) -> str:
    examples = card.get("examples") or []
    if examples:
        return _strip_markup(str(examples[0]))
    return ""


def _difficulty_tier(card: dict[str, Any]) -> str:
    diff = card.get("difficulty")
    try:
        value = float(diff)
    except (TypeError, ValueError):
        return "easy"
    if value >= 5.0:
        return "hard"
    if value >= 4.0:
        return "medium"
    return "easy"


def _notebook_entry_seed(card: dict[str, Any]) -> dict[str, Any]:
    """NotebookEntrySeed (Swift field order)."""
    source = card.get("source") or {}
    return {
        "word": card["content"],
        "translation": card["meaning"],
        "context": _first_example(card),
        "explanation": card.get("note"),
        "partOfSpeech": card.get("pos"),
        "bookTitle": source.get("title"),
        "chapterTitle": source.get("chapter"),
    }


def _notebook_seed(
    notebook: dict[str, Any], index: int, cards: list[dict[str, Any]]
) -> dict[str, Any]:
    name = notebook["name"]
    entries = [
        _notebook_entry_seed(card)
        for card in cards
        if card.get("notebook") == name
    ]
    return {
        "remoteId": _slug(name),
        "name": name,
        "isDefault": index == 0,
        "sortOrder": index,
        "entries": entries,
    }


def _today_review_card_seed(card: dict[str, Any], review_anchor: str) -> dict[str, Any]:
    """TodayReviewCardSeed (Swift field order)."""
    source = card.get("source") or {}
    return {
        "word": card["content"],
        "translation": card["meaning"],
        "context": _first_example(card),
        "explanation": card.get("note"),
        "partOfSpeech": card.get("pos"),
        "bookTitle": source.get("title", ""),
        "chapterTitle": source.get("chapter"),
        "dateAdded": review_anchor,
        "difficultyTier": _difficulty_tier(card),
        "reviewMode": "recognition",
        "reviewExamples": [
            _strip_markup(str(ex)) for ex in (card.get("examples") or [])
        ],
        "rootForm": None,
        "inflections": [],
        "graphLinksByKind": {},
    }


def _today_review_session_seed(
    due_cards: list[dict[str, Any]], review_anchor: str
) -> dict[str, Any]:
    """TodayReviewSessionSeed (Swift field order)."""
    due_count = len(due_cards)
    current = (
        _today_review_card_seed(due_cards[0], review_anchor) if due_count >= 1 else None
    )
    nxt = (
        _today_review_card_seed(due_cards[1], review_anchor) if due_count >= 2 else None
    )
    return {
        "progressText": f"1 / {due_count}",
        "currentCard": current,
        "nextCard": nxt,
        "revealStage": "front",
        "canShuffle": due_count > 1,
        "canGoPrevious": False,
        "canGoNext": due_count > 1,
        "remainingCount": due_count,
        "forgotCount": 0,
        "rememberedCount": 0,
        "rememberedFeedbackTrigger": 0,
        "forgotFeedbackTrigger": 0,
        "isAutoPlaying": False,
        "isAutoPlayPaused": False,
        "autoplayProgress": 0.0,
        "autoplaySpeed": "normal",
        "autoplaySoundEnabled": True,
        "showFirstRunHint": False,
    }


def _build_fixture_document(sot: DemoSoT) -> dict[str, Any]:
    dataset = sot.dataset
    identity = sot.identity
    notebooks = dataset["notebooks"]
    cards = dataset["cards"]
    review_anchor = dataset["review_anchor"]

    notebook_seeds = [
        _notebook_seed(nb, i, cards) for i, nb in enumerate(notebooks)
    ]
    due_cards = [
        c
        for c in cards
        if isinstance(c.get("review"), dict) and c["review"].get("state") == "due"
    ]

    return {
        "schema": FIXTURE_SCHEMA,
        "datasetID": f"demo-{identity['user_id']}",
        "assets": {
            "books": {},
            "audio": {},
            "subtitles": {},
            "text": {},
            "images": {},
        },
        "auth": {
            "signedIn": {
                "isLoggedIn": True,
                "userId": identity["user_id"],
                "token": identity["access_token"],
                "displayName": identity["display_name"],
                "email": identity["email"],
                "provider": identity["provider"],
                "providerUserId": identity["provider_user_id"],
            },
            "guest": {
                "isLoggedIn": False,
                "userId": None,
                "token": None,
                "displayName": None,
                "email": None,
                "provider": None,
                "providerUserId": None,
            },
        },
        "entitlements": {
            "pro": {"pro": _subscription_status(active=True)},
            "free": {"pro": _subscription_status(active=False)},
        },
        "settings": {},
        "bookshelf": {},
        "todayReview": {
            TODAY_REVIEW_FIXTURE_KEY: _today_review_session_seed(due_cards, review_anchor)
        },
        "notebook": {NOTEBOOK_FIXTURE_KEY: {"notebooks": notebook_seeds}},
        "podcast": {},
        "runtimePodcast": {},
        "reader": {},
        "vocabulary": {},
        "reviewDeck": {},
    }


def _subscription_status(*, active: bool) -> dict[str, Any]:
    return {
        "is_active": active,
        "product_id": "com.wordnexus.pro.monthly",
        "plan_name": "Books & Vocab Pro",
        "price_display": "NT$90 / month",
        "status": "active" if active else "inactive",
        "is_trial": False,
        "trial_days": 7,
        "will_renew": active,
        "expires_at": "2099-12-31T23:59:59Z" if active else None,
        "source": "app_store",
        "last_synced_at": "2026-06-10T00:00:00Z",
    }


def _json_bytes(payload: dict[str, Any]) -> bytes:
    """Deterministic JSON: 2-space indent, UTF-8, no key reordering, trailing NL."""
    return (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _artifacts(sot: DemoSoT) -> list[tuple[Path, bytes]]:
    document = _build_fixture_document(sot)
    return [(FIXTURE_JSON_PATH, _json_bytes(document))]


def _rel(path: Path) -> str:
    try:
        return str(path.relative_to(_REPO_ROOT))
    except ValueError:
        return str(path)


def emit(sot: DemoSoT, *, check: bool = False, commit: bool = False) -> dict:
    """Emit the iOS UI World FixtureDatasetDocument JSON from the SoT.

    Args:
        sot: validated DemoSoT bundle (identity + dataset).
        check: re-emit in memory and byte-compare against the committed
            artifact(s); return a drift report instead of writing.
        commit: write the generated file(s) to disk (and print the base64 the
            harness exports as KG_FIXTURE_DATASET_B64). When False (and check
            False), dry-run returning the planned output paths.

    Returns:
        A dict describing the action (paths written / drift verdict / base64).
    """
    artifacts = _artifacts(sot)

    if check:
        drifted: list[dict[str, Any]] = []
        missing: list[str] = []
        for path, expected in artifacts:
            if not path.exists():
                missing.append(_rel(path))
                drifted.append({"path": _rel(path), "reason": "missing"})
                continue
            actual = path.read_bytes()
            if actual != expected:
                drifted.append(
                    {
                        "path": _rel(path),
                        "reason": "content-mismatch",
                        "committed_bytes": len(actual),
                        "fresh_bytes": len(expected),
                    }
                )
        return {
            "action": "check",
            "drift": bool(drifted),
            "drifted": drifted,
            "missing": missing,
            "checked": [_rel(p) for p, _ in artifacts],
        }

    if commit:
        written: list[str] = []
        for path, content in artifacts:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            written.append(_rel(path))
        fixture_b64 = base64.b64encode(artifacts[0][1]).decode("ascii")
        return {
            "action": "commit",
            "drift": False,
            "written": written,
            "datasetID": json.loads(artifacts[0][1])["datasetID"],
            "fixture_dataset_b64": fixture_b64,
            "inject_hint": (
                "export KG_FIXTURE_DATASET_B64=<fixture_dataset_b64>  # or: "
                "./ops/ios_test.sh --ui --dataset-file "
                f"{_rel(FIXTURE_JSON_PATH)} ..."
            ),
        }

    # dry-run
    return {
        "action": "dry-run",
        "drift": False,
        "planned_paths": [_rel(p) for p, _ in artifacts],
        "datasetID": json.loads(artifacts[0][1])["datasetID"],
    }
