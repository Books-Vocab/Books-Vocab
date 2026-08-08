#!/usr/bin/env python3
"""Official-deck governance CLI — git-SoT spec → the global shared-decks catalog.

Mirrors the ``build_demo`` pattern (SoT → emit → ``--check`` drift gate): each
official deck is a git-committed ``kg.official_deck.v1`` spec under this
directory. The emitter seeds it into ``data_dir/shared_decks.db`` and stamps the
server-authoritative axes (``source='official'`` / ``owner_id=NULL`` /
``visibility='official'``), which live in :func:`SharedDeckStore.publish_official`
and therefore cannot be forged from a spec (§5.2 badge invariant).

Interface (dry-run default, ``--commit`` to land, U6 approval-gated):

    build_official.py emit  <spec.json> [--commit] [--json]
    build_official.py check [<spec.json>] [--json]     # round-trip PR gate

Canonical invocation is the script form, run via uv from the backend venv:

    (cd backend && uv run python ../ops/official_decks/build_official.py check --json)

``emit`` without ``--commit`` validates the spec and prints the plan with zero
disk writes. ``--commit`` snapshots the whole data-dir (``backup_world``) BEFORE
writing (§3.5), then upserts idempotently. ``check`` emits each committed spec
into a throwaway sandbox, projects it back, and asserts the projection equals the
spec-as-written — a spec that cannot be faithfully stored (colliding cards under
the guid UNIQUE) drifts and exits 1. Whole-directory ``check`` additionally
asserts that the set it validated equals the set git will ship (see
:func:`untracked_specs` / :func:`missing_specs`): the working tree is what this
tool can read, but the index is what deploys, and a deck that exists in only one
of them used to reach production silently. The independent pre-deploy
prod-parity check (§5.3 b) is intentionally NOT implemented here — see README.

The emitter reuses the store's ``canonical_card`` / ``deck_content_hash`` so guid
and content-hash logic have a single authority in the backend package.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from kg.ops_edit_shared import append_audit, backup_world
from kg.shared_decks.store import (
    SharedDeckStore,
    canonical_card,
    deck_content_hash,
)
from kg.text_utils import normalize_nfc

_HERE = Path(__file__).resolve().parent
SPEC_SCHEMA = "kg.official_deck.v1"
_DECK_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_BACKUP_LABEL = "shared-decks-official"
# Coarse category enum (README-documented). Empty/None allowed (uncategorized).
_CATEGORIES = frozenset({"language", "exam", "phrase", "custom"})


class SpecError(ValueError):
    """A committed spec is malformed. Message is operator-facing."""


class GitIndexUnavailable(RuntimeError):
    """git could not tell us what the index carries. Message is operator-facing.

    Raised rather than returning an empty set, because "I cannot see the index"
    and "the index is clean" are precisely the two states the git-index gate
    below exists to keep apart. Collapsing them would rebuild the bug."""


# ── spec validation / normalization (camelCase spec → snake_case store) ──

def _normalize(spec: dict) -> dict:
    if not isinstance(spec, dict):
        raise SpecError("spec must be a JSON object")
    schema = spec.get("schema")
    if schema != SPEC_SCHEMA:
        raise SpecError(f"schema must be {SPEC_SCHEMA!r}, got {schema!r}")
    deck_id = spec.get("deckId")
    if not isinstance(deck_id, str) or not _DECK_ID_RE.match(deck_id):
        raise SpecError(f"deckId must match ^[A-Za-z0-9_-]{{1,64}}$, got {deck_id!r}")
    title = spec.get("title")
    if not isinstance(title, str) or not title.strip():
        raise SpecError("title must be a non-empty string")
    raw_cards = spec.get("cards")
    if not isinstance(raw_cards, list) or not raw_cards:
        raise SpecError("cards must be a non-empty list")
    tags = spec.get("tags") or []
    if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
        raise SpecError("tags must be a list of strings")
    category = _opt_str(spec.get("category"))
    if category is not None and category not in _CATEGORIES:
        raise SpecError(f"category must be one of {sorted(_CATEGORIES)} or null, got {category!r}")
    cards = [_normalize_card(c, i) for i, c in enumerate(raw_cards)]
    _assert_copyable(cards)
    # NOTE: source / ownerId / visibility / status are deliberately NOT read —
    # they are server-authoritative in publish_official. A spec cannot inject them.
    return {
        "deck_id": deck_id,
        "title": title,
        "description": _opt_str(spec.get("description")),
        "category": category,
        "language_pair": _opt_str(spec.get("languagePair")),
        "tags": [str(t) for t in tags],
        "color": _opt_str(spec.get("color")),
        "cover_pattern": _opt_str(spec.get("coverPattern")),
        "cards": cards,
    }


def _nocase_key(content: str) -> str:
    """The copier's per-notebook uniqueness key: NFC-normalized content compared
    COLLATE NOCASE. SQLite NOCASE folds ONLY ASCII A-Z, so fold exactly that —
    ``str.lower()`` would over-fold non-ASCII and flag pairs NOCASE keeps apart."""
    return "".join(ch.lower() if "A" <= ch <= "Z" else ch for ch in normalize_nfc(content))


def _assert_copyable(cards: list[dict]) -> None:
    """Reject a deck the copier cannot store 1:1.

    A private ``Card`` enforces ``UNIQUE(content COLLATE NOCASE, notebook_id)``,
    so two cards whose content matches case-insensitively — even when distinct by
    pos/mode/meaning (a homograph like ``Lead`` n. vs ``lead`` v.) — collapse
    into ONE row on copy → ``copy_shared_deck``'s count-equality fails → every
    copy 409s. ``shared_deck_card`` tolerates the pair (distinct content_guid),
    so the collision is invisible to publish AND the round-trip check; it must be
    caught here, at curation. Cards sharing a content_guid are deduped first
    (they collapse to one ``shared_deck_card`` and never reach the copier as
    two — mirrors ``publish_official``), so exact duplicates are NOT false-flagged."""
    by_guid: dict[str, dict] = {}
    for card in cards:
        by_guid.setdefault(canonical_card(card)["content_guid"], card)
    buckets: dict[str, list[dict]] = {}
    for card in by_guid.values():
        buckets.setdefault(_nocase_key(card["content"]), []).append(card)
    collisions = [group for group in buckets.values() if len(group) > 1]
    if collisions:
        surfaces = "; ".join(
            f"{c['content']!r} (pos={c['pos']!r}, mode={c['mode']!r})"
            for group in collisions for c in group
        )
        raise SpecError(
            "cards collide under the copier's case-insensitive uniqueness "
            "(content COLLATE NOCASE) — a copy would drop cards and 409. "
            f"Colliding surfaces: {surfaces}"
        )


def _normalize_card(card: dict, index: int) -> dict:
    if not isinstance(card, dict):
        raise SpecError(f"card[{index}] must be an object")
    content = card.get("content")
    if not isinstance(content, str) or not content.strip():
        raise SpecError(f"card[{index}].content must be a non-empty string")
    meaning = card.get("meaning")
    if not isinstance(meaning, str) or not meaning.strip():
        raise SpecError(f"card[{index}].meaning must be a non-empty string")
    difficulty = card.get("difficulty")
    # bool is an int subclass — reject it explicitly so `true` isn't stored as 1.0.
    if difficulty is not None and (isinstance(difficulty, bool) or not isinstance(difficulty, (int, float))):
        raise SpecError(f"card[{index}].difficulty must be a number or null, got {difficulty!r}")
    return {
        "content": content,
        "pos": _opt_str(card.get("pos")),
        "meaning": meaning,
        "examples": _str_list(card.get("examples"), f"card[{index}].examples"),
        "collocations": _str_list(card.get("collocations"), f"card[{index}].collocations"),
        "note": _opt_str(card.get("note")),
        "difficulty": difficulty,
        "mode": _opt_str(card.get("mode")) or "recognition",
        "root_form": _opt_str(card.get("rootForm")),
        "inflections": _str_list(card.get("inflections"), f"card[{index}].inflections"),
    }


def _opt_str(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise SpecError(f"expected string or null, got {value!r}")
    return value


def _str_list(value: object, label: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise SpecError(f"{label} must be a list of strings")
    return list(value)


def _store_kwargs(deck: dict) -> dict:
    return {
        "deck_id": deck["deck_id"],
        "title": deck["title"],
        "cards": deck["cards"],
        "description": deck["description"],
        "category": deck["category"],
        "language_pair": deck["language_pair"],
        "tags": deck["tags"],
        "color": deck["color"],
        "cover_pattern": deck["cover_pattern"],
    }


# ── emit ────────────────────────────────────────────────────────────────

def emit(
    spec: dict, *, check: bool = False, commit: bool = False,
    data_dir: Path | None = None,
) -> dict:
    """Emit one official-deck spec. See module docstring for the three modes."""
    deck = _normalize(spec)
    if check:
        return _check_roundtrip(deck)

    distinct = {canonical_card(c)["content_guid"] for c in deck["cards"]}
    content_hash = deck_content_hash(deck["cards"])
    if not commit:
        return {
            "mode": "dry-run", "committed": False, "deckId": deck["deck_id"],
            "title": deck["title"], "cardCount": len(distinct),
            "contentHash": content_hash,
            "hint": "add --commit to write (approval-gated, U6)",
        }

    if data_dir is None:
        from kg.ops_shared import data_dir as _resolve
        data_dir = _resolve()
    data_dir = Path(data_dir)
    # Snapshot the whole data-dir BEFORE any write (§3.5 global-store backup).
    backup = backup_world(data_dir, label=_BACKUP_LABEL)
    store = SharedDeckStore(data_dir / "shared_decks.db")
    try:
        result = store.publish_official(**_store_kwargs(deck))
        verified = _verify(store, deck["deck_id"], result)
    finally:
        store.close()
    # Audit trail: who injected which official deck, when (traceability of a
    # production write — mirrors EditContext's append_audit for ops_edit).
    append_audit(data_dir, {
        "schema": "kg.official_deck_injection.v1",
        "deckId": deck["deck_id"], "action": result["action"],
        "version": result["version"], "contentHash": result["contentHash"],
        "backup": str(backup),
    })
    return {
        # ``dataDir`` is surfaced so an operator sees WHERE the write landed —
        # when KG_DATA_DIR is unset this resolves to the live dev data dir, not
        # a throwaway sandbox.
        "mode": "commit", "committed": True, "dataDir": str(data_dir),
        "backup": str(backup), "result": result, "verified": verified,
    }


def _verify(store: SharedDeckStore, deck_id: str, result: dict) -> dict:
    deck = store.get(deck_id)  # discoverable read: official decks always pass
    ok = deck is not None and deck.card_count == result["cardCount"]
    return {
        "ok": bool(ok),
        "browsable": deck is not None,
        "cardCount": deck.card_count if deck else 0,
        "version": deck.current_version if deck else 0,
    }


# ── --check: round-trip self-consistency (sandbox PR gate) ──────────────

def _check_roundtrip(deck: dict) -> dict:
    expected = {"meta": _expected_meta(deck),
                "cards": _sorted_cards(canonical_card(c) for c in deck["cards"])}
    with tempfile.TemporaryDirectory() as tmp:
        store = SharedDeckStore(Path(tmp) / "shared_decks.db")
        try:
            store.publish_official(**_store_kwargs(deck))
            actual = _project_from_store(store, deck["deck_id"])
        finally:
            store.close()
    drift = expected != actual
    out = {"mode": "check", "deckId": deck["deck_id"], "drift": drift}
    if drift:
        out["diff"] = {
            "expectedCards": len(expected["cards"]),
            "actualCards": len(actual["cards"]),
            "metaEqual": expected["meta"] == actual["meta"],
        }
    return out


def _project_from_store(store: SharedDeckStore, deck_id: str) -> dict:
    row = store.get(deck_id)
    cards = _read_all_cards(store, deck_id, row.current_version)
    return {
        "meta": {
            "deckId": row.id, "title": row.title, "description": row.description,
            "category": row.category, "languagePair": row.language_pair,
            "tags": list(row.tags or []), "color": row.color,
            "coverPattern": row.cover_pattern,
        },
        "cards": _sorted_cards(_card_row_canonical(c) for c in cards),
    }


def _read_all_cards(store: SharedDeckStore, deck_id: str, version: int) -> list:
    out: list = []
    after = None
    while True:
        page = store.page_cards(deck_id, version=version, limit=500, after=after)
        if not page:
            break
        out.extend(page)
        if len(page) < 500:
            break
        after = page[-1].id
    return out


def _card_row_canonical(card) -> dict:
    return canonical_card({
        "content": card.content, "pos": card.pos, "meaning": card.meaning,
        "examples": card.examples, "collocations": card.collocations,
        "note": card.note, "difficulty": card.difficulty, "mode": card.mode,
        "root_form": card.root_form, "inflections": card.inflections,
    })


def _sorted_cards(cards) -> list[dict]:
    return sorted(cards, key=lambda c: c["content_guid"])


def _expected_meta(deck: dict) -> dict:
    return {
        "deckId": deck["deck_id"], "title": deck["title"],
        "description": deck["description"], "category": deck["category"],
        "languagePair": deck["language_pair"], "tags": list(deck["tags"]),
        "color": deck["color"], "coverPattern": deck["cover_pattern"],
    }


# ── discovery + CLI ──────────────────────────────────────────────────────

def discover_specs() -> list[str]:
    """Absolute paths of every spec file ON DISK in this directory, sorted.

    Reference frame: the working tree, NOT git. Alone this is the wrong frame
    for a ship gate — a spec the curator forgot to ``git add`` is present here
    and absent from everything that deploys, so a check built only on this set
    goes green on a deck that will not exist in production. ``check`` therefore
    pairs it with :func:`untracked_specs` / :func:`missing_specs`."""
    return sorted(str(p) for p in _HERE.glob("*.json"))


def _indexed_spec_names() -> set[str]:
    """Spec filenames the git index carries for this directory.

    The index is the closest readable proxy for what ships, and the only frame
    that works *before* a new deck's first commit — a brand-new spec is in no
    commit yet, so HEAD cannot answer the question this gate asks. It is not
    the same thing as the commit: a pathspec commit (``git commit -o <other
    paths>``) can leave a staged spec out of the tree. So the gate proves the
    spec is STAGED, which is as close as a pre-commit check can get; confirming
    it actually landed (``git show --stat HEAD``) stays the curator's job.

    ``-z`` because git otherwise C-quotes non-ASCII names; the ``"/" not in``
    filter keeps the depth identical to ``discover_specs``' non-recursive glob,
    so a nested file cannot masquerade as a missing top-level spec."""
    try:
        proc = subprocess.run(
            ["git", "ls-files", "-z", "--", "."],
            cwd=str(_HERE), capture_output=True, text=True,
        )
    except OSError as exc:  # git absent, or _HERE is not a directory
        raise GitIndexUnavailable(f"could not run git in {_HERE}: {exc}") from exc
    if proc.returncode != 0:  # not a git tree, or path outside the repo
        raise GitIndexUnavailable(
            f"git ls-files failed in {_HERE} (rc={proc.returncode}): "
            f"{proc.stderr.strip() or '<no stderr>'}"
        )
    return {
        name for name in proc.stdout.split("\0")
        if name.endswith(".json") and "/" not in name
    }


def spec_index_drift() -> dict[str, list[str]]:
    """Both ways the validated set can diverge from the shipped one, from ONE
    index snapshot — so the two directions cannot disagree about what git said.

    Note this derives untracked-ness by SUBTRACTING the index from the disk
    rather than asking git to list untracked files. ``git ls-files --others
    --exclude-standard`` is blind to anything a ``.gitignore`` matches, and an
    ignored spec is exactly as absent from production as a forgotten one."""
    indexed = _indexed_spec_names()
    on_disk = discover_specs()
    on_disk_names = {Path(p).name for p in on_disk}
    return {
        "untracked": sorted(p for p in on_disk if Path(p).name not in indexed),
        "missing": sorted(str(_HERE / name) for name in indexed
                          if name not in on_disk_names),
    }


def untracked_specs() -> list[str]:
    """Specs on disk that the git index does not carry, sorted.

    These are the silent ones: they validate green right here and are simply
    absent from the deployed tree. Curator forgot ``git add`` — or a
    ``.gitignore`` pattern swallowed the file."""
    return spec_index_drift()["untracked"]


def missing_specs() -> list[str]:
    """Specs the git index carries but that are absent from disk, sorted.

    The mirror hole: ``rm`` without ``git rm`` leaves the spec in the index (so
    a commit of unrelated files still ships it) while the filesystem walk stops
    seeing it — a deck that reaches production having been validated by
    nothing."""
    return spec_index_drift()["missing"]


def _load(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _build_parser() -> argparse.ArgumentParser:
    parent = argparse.ArgumentParser(add_help=False)
    parent.add_argument("--json", action="store_true", help="machine-readable output")
    parser = argparse.ArgumentParser(
        prog="build_official.py",
        description="Official-deck governance: git-SoT spec → shared-decks catalog.",
        parents=[parent],
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_emit = sub.add_parser("emit", parents=[parent], help="emit one spec (dry-run default)")
    p_emit.add_argument("spec", help="path to a kg.official_deck.v1 spec file")
    p_emit.add_argument("--commit", action="store_true",
                        help="write to shared_decks.db (approval-gated, U6)")

    p_check = sub.add_parser("check", parents=[parent],
                             help="round-trip self-consistency gate; exit 1 on drift")
    p_check.add_argument("spec", nargs="?", default=None,
                         help="one spec (default: all committed specs)")
    return parser


def _print(payload: dict, *, json_mode: bool) -> None:
    if json_mode:
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        return
    mode = payload.get("mode", "")
    print(f"[{mode}]")
    for k, v in payload.items():
        if k == "mode":
            continue
        print(f"  {k}: {v}")


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    json_mode = bool(getattr(args, "json", False))
    try:
        if args.cmd == "emit":
            env_dir = os.getenv("KG_DATA_DIR")
            res = emit(
                _load(args.spec), commit=args.commit,
                data_dir=Path(env_dir) if env_dir else None,
            )
            _print(res, json_mode=json_mode)
            if res.get("mode") == "commit" and not res["verified"]["ok"]:
                return 1
            return 0

        # check
        if args.spec:
            # A single named spec never enumerates the directory, so it has
            # nothing to say about the index. Report that as UNCHECKED, not as
            # an empty untracked list — a false clean is the bug, not the fix.
            paths = [args.spec]
            untracked: list[str] = []
            missing: list[str] = []
            git_index: dict = {
                "checked": False,
                "reason": "single-spec check does not enumerate the directory",
            }
        else:
            paths = discover_specs()
            drift = spec_index_drift()  # one index snapshot, both directions
            untracked = drift["untracked"]
            missing = drift["missing"]
            git_index = {"checked": True, **drift}

        results = []
        drift_any = False
        for path in paths:
            r = emit(_load(path), check=True)
            r["spec"] = str(path)
            results.append(r)
            drift_any = drift_any or r["drift"]
        _print({"mode": "check", "drift": drift_any, "gitIndex": git_index,
                "specs": results}, json_mode=json_mode)
        if not json_mode:
            for path in untracked:
                print(f"  ✗ on disk but NOT in the git index — this deck will not "
                      f"ship; `git add` it: {path}")
            for path in missing:
                print(f"  ✗ in the git index but NOT on disk — it ships unvalidated; "
                      f"`git rm` it or restore the file: {path}")
        return 1 if (drift_any or untracked or missing) else 0
    except SpecError as exc:
        _print({"mode": "error", "error": str(exc)}, json_mode=json_mode)
        return 1
    except GitIndexUnavailable as exc:
        _print({"mode": "error", "error": f"git index unreadable: {exc}"},
               json_mode=json_mode)
        return 1
    except FileNotFoundError as exc:
        _print({"mode": "error", "error": f"spec not found: {exc}"}, json_mode=json_mode)
        return 1


if __name__ == "__main__":
    sys.exit(main())
