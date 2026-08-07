#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# ///
"""Backlog store — one file per entry, so N agents can file issues in parallel.

WHY THIS SHAPE
--------------
The predecessor was a single markdown table (`docs/runbook/improvement_backlog.md`).
It failed in three measured ways:

  * 54KB / 59 entries in one file. Filing one entry meant reading all of them;
    a plain read of it overflows a 25k-token budget.
  * Every append targets the same trailing region, so two worktrees appending
    concurrently conflict by construction.
  * Sequential ids collide. IMP-0017's own text records colliding twice with no
    parallelism at all. Across worktrees a counter cannot work even in
    principle — the entry files are invisible to each other until they merge,
    so both sides necessarily allocate the same next number.

So: one JSON file per entry, ids derived from content rather than allocated
from a counter. Two agents in two worktrees write disjoint paths and git merges
them with no conflict, which is the whole point.

Entries live under `docs/runbook/backlog/` as `.json` and NOT as `.md` on
purpose: `ops/docs_lint.sh:216` scans every `docs/**/*.md` and demands a
`<!-- doc-meta -->` block with a reachable `verified_against`. Storing 59
ledger rows as markdown would manufacture 59 doc-meta liabilities. Keeping them
as `.json` costs nothing and needs no carve-out in the lint tool.

JSON rather than YAML because there is no YAML dependency anywhere in `ops/`
(`docs_impact.py` and `ui_quality_plane.py` both hand-parse), and the
`ops/**.py` cutover gate runs tests under a sandbox `uv run --no-project --with
pytest` with no project dependencies available. Hand-rolling a YAML subset
parser to store a ledger whose own contents are largely "a tool lied to us"
would be a poor trade.

Note the serialisation here is the *readable* form (indent=2, sorted keys), not
the canonical hashing form used by `ops/app_review_gate.py` and friends. These
files are reviewed by humans and diffed by git; they are not hashed artifacts.
See IMP-0042 for the separate canonical-JSON consolidation.
"""

from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import re
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STORE = ROOT / "docs" / "runbook" / "backlog"
DEFAULT_VIEW = ROOT / "docs" / "runbook" / "improvement_backlog.md"

SCHEMA = "kg.backlog.entry.v1"

# Two streams, deliberately kept apart. IMP is harness/tooling friction owned by
# platform-steward; APP is what a user hits while actually using the app, owned
# by the ios/backend line departments. Mixing them makes platform-steward's
# triage queue unreadable, which is the reason for the split.
STREAMS = ("IMP", "APP")

CATEGORIES = {
    "IMP": ("tool", "cli", "doc", "arch"),
    "APP": ("ux", "correctness", "perf", "data", "content"),
}

SEVERITIES = ("low", "med", "high")
STATUSES = ("open", "triaged", "in-progress", "fixed", "wont-fix")

REQUIRED_FIELDS = (
    "schema",
    "id",
    "stream",
    "date",
    "source",
    "category",
    "severity",
    "status",
    "detail",
    "resolution",
)

# Fields that only make sense for an app-usage report. An IMP entry carrying a
# `surface` means someone filed an app problem into the tooling stream.
APP_ONLY_FIELDS = ("surface", "repro", "build")

# Structured results of a re-verification sweep, extracted from the resolution
# stamp. Optional on every entry; see extract_verdict_fields().
VERDICT_FIELDS = ("verified_at", "verdict", "cost", "fix_site", "duplicate_of")

# The one structured, machine-checkable answer to "what made this stop being
# true". `resolution` stays authoritative as PROSE, but prose can only be read
# by position heuristics, and the heuristic is measurably wrong: on this store,
# "the first sha in the resolution" was the landing commit for 49 of 63 fixed
# entries, and one of those 49 (IMP-0063) was an *incidental* hash the text
# mentions for an unrelated reason. A field that only ever holds landing commits
# cannot be satisfied by a sha that wandered into the paragraph.
TRACE_FIELDS = ("fixed_by",)

# Shape only. The first cut of this required at least one a-f digit, to stop
# `20260805` (a date) reading as a sha — and immediately produced a FALSE
# NEGATIVE on `339918579`, a real commit in this repo that happens to be all
# decimal. The character class cannot answer "is this a commit"; only the object
# database can, which is what commit_state is for. A date therefore lands in
# `fixed-by-unresolvable`, which is both true and actionable. Keep the guard
# dumb and let the discriminator be the thing that actually knows.
_SHA_RE = re.compile(r"^[0-9a-f]{7,40}$")

# The groom stamp. `verdict` answers "is this problem still real?"; these answer
# a different question the ledger could not express — "has anyone worked out HOW
# to fix it?" Both were being written by the same sweep into the same two
# fields, so the owner could not tell a re-checked claim from an investigated
# one, which is the whole reason this exists.
#
# `plan` is held to a stated bar: concrete enough that a small model can execute
# it without re-deriving anything. That bar is prose and cannot be machine-
# checked, but its PRECONDITIONS can — see _check_groom(). A badge whose
# preconditions nobody verifies decays into the "reason field nobody reads"
# failure this repo has already paid for twice.
GROOM_FIELDS = ("plan", "acceptance", "groomed_at", "groomed_by")

# Claiming the badge requires all of these to be non-empty. `fix_site` is in the
# list and not in GROOM_FIELDS because it predates this and is shared with the
# verdict stamp: a plan that cannot name where to change is not a plan.
GROOM_REQUIRES = ("plan", "acceptance", "fix_site")

# Closed vocabulary, same principle as stream/category/severity/status. Without
# it prose misfires land in the field unchallenged: `已於 2026-07-31 驗證 CI 綠`
# yields verdict "CI". `_anchors_ok` already gates rows on controlled
# vocabularies; this is the same rule applied where it was missing.
VERDICTS = (
    "CONFIRMED-OPEN",
    "PARTIAL",
    "MISSTATED",
    "ALREADY-FIXED",
    "OBSOLETE",
    # Added when the check below first ran over the store: three entries had
    # independently coined `CONFIRMED-FIXED` / `FIXED-ROOT-CAUSE` for an answer
    # the list could not express — "this entry is closed and I checked the
    # closure is genuine". That is not ALREADY-FIXED, which is about an OPEN
    # entry turning out to need no work. Three independent coinages of the same
    # missing word is a gap in the vocabulary, not three careless authors.
    "CONFIRMED-FIXED",
)
_DUPLICATE_VERDICT_PREFIX = "DUPLICATE-OF-"

# An entry id must be usable as a bare filename. Unvalidated, `--date 2026/08/05`
# writes <store>/IMP-2026/08/05-<hash>.json — a real subdirectory that
# store.glob("*.json") never sees, so `list` and `validate` both report an empty,
# healthy store while the entry sits on disk. `--id ../escaped` writes outside
# the store entirely. Both returned rc=0 before this guard.
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class BacklogError(Exception):
    """Raised for usage errors that should exit 64 rather than traceback."""


# ---------------------------------------------------------------------------
# ids
# ---------------------------------------------------------------------------

def make_entry_id(*, stream: str, date: str, source: str, detail: str) -> str:
    """Content-derived id: `<STREAM>-<YYYYMMDD>-<6 hex>`.

    Content-derived rather than random for one concrete reason: the importer
    that migrates the legacy table is re-runnable, and re-running it while the
    source file is still being edited must converge on the same ids rather than
    fork a second copy of every entry.

    The digest covers the fields that identify *which problem this is* —
    stream, date, source, detail. Mutable state (status, severity, resolution)
    is excluded so that triaging an entry never changes its id.
    """
    payload = "\x1f".join([stream, date, source, detail]).encode("utf-8")
    digest = hashlib.sha256(payload).hexdigest()[:6]
    return f"{stream}-{date.replace('-', '')}-{digest}"


# Read off the digest signature rather than restated as a literal: the one list
# that must never disagree with `make_entry_id` is the list of what it hashes.
DIGEST_FIELDS = tuple(inspect.signature(make_entry_id).parameters)


def entry_path(store: Path, entry_id: str) -> Path:
    return Path(store) / f"{entry_id}.json"


# ---------------------------------------------------------------------------
# serialisation
# ---------------------------------------------------------------------------

def _dumps(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _write_atomic(path: Path, text: str) -> None:
    """Write via a temp file + os.replace so a crash cannot publish a partial
    entry. Callers rely on this: a truncated JSON entry would make the whole
    store unreadable to `render`, and the failure would surface far from the
    write that caused it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


# ---------------------------------------------------------------------------
# validation
# ---------------------------------------------------------------------------

def _check_vocabulary(payload: dict) -> list[dict]:
    problems: list[dict] = []
    stream = payload.get("stream")

    if stream not in STREAMS:
        problems.append({"kind": "bad-stream", "value": stream})
    elif payload.get("category") not in CATEGORIES[stream]:
        # Only meaningful once the stream is known — the vocabularies differ.
        problems.append({"kind": "bad-category", "value": payload.get("category")})

    if payload.get("severity") not in SEVERITIES:
        problems.append({"kind": "bad-severity", "value": payload.get("severity")})
    if payload.get("status") not in STATUSES:
        problems.append({"kind": "bad-status", "value": payload.get("status")})

    # VERDICTS was declared a closed vocabulary but only ever enforced inside
    # extract_verdict_fields(), i.e. on the way IN from a resolution stamp.
    # Anything that set the field directly bypassed it: measured before this
    # landed, `update <id> --verdict TOTALLY-BOGUS --commit` exited 0, the value
    # landed in the file, and `validate` reported 0 problems. A vocabulary
    # nothing checks at rest is a comment.
    verdict = payload.get("verdict")
    if verdict and verdict not in VERDICTS and not str(verdict).startswith(
        _DUPLICATE_VERDICT_PREFIX
    ):
        problems.append({"kind": "bad-verdict", "value": verdict})

    return problems


def _check_traceability(payload: dict, commit_state) -> list[dict]:
    """Hold `status` to the evidence that status implies.

    Each status claims something different, so each gets its own rule:

      * `fixed` claims the defect is gone. That claim is only auditable if it
        names the commits, and only true if those commits are still reachable.
      * `open` claims nothing but "filed". It is an honest state and carries no
        obligation — see the next-action rule below.
      * `triaged` / `in-progress` claim someone looked, so they owe a next action.
      * `wont-fix` claims a decision, which is a reason, not a hash.

    `commit_state` is injected so this stays a pure function of its inputs: the
    unit tests must not need a git repo, and the one caller that does have one
    builds the real resolver once and caches it.
    """
    problems: list[dict] = []
    status = payload.get("status")
    fixed_by = payload.get("fixed_by") or []

    if not isinstance(fixed_by, list) or any(not isinstance(s, str) for s in fixed_by):
        return [{"kind": "fixed-by-not-a-list", "value": fixed_by}]

    if status == "fixed":
        if not fixed_by:
            problems.append({"kind": "fixed-without-fixed-by"})
        for sha in fixed_by:
            if not _SHA_RE.match(sha):
                problems.append({"kind": "fixed-by-not-a-sha", "sha": sha})
                continue
            state = commit_state(sha) if commit_state else "ok"
            if state == "orphan":
                # Mechanically repairable: the rebase inside cutover rewrote it,
                # and the rewritten commit is byte-identical often enough that
                # `reanchor` can find it by patch-id. Distinct from the next kind
                # because the repairs are different.
                problems.append({"kind": "fixed-by-orphaned", "sha": sha})
            elif state == "unknown":
                # No object anywhere. IMP-0005 carried `813356b1`, which exists
                # in no odb — not an orphan, a hash somebody wrote down wrong.
                # Telling that reader to run `reanchor` sends them hunting a
                # rebase that never happened.
                problems.append({"kind": "fixed-by-unresolvable", "sha": sha})
    elif status in ("open", "triaged", "in-progress"):
        if fixed_by:
            # An unfinished entry pointing at a landing commit is the status
            # lying about itself, and it is the shape that lets closed work look
            # open forever.
            problems.append({"kind": "fixed-by-on-unfinished-entry", "shas": fixed_by})

    if status in ("triaged", "in-progress") and not _next_action(payload):
        problems.append({"kind": "no-next-action", "status": status})

    if status == "wont-fix":
        reason = str(payload.get("resolution") or "").strip()
        if not reason:
            problems.append({"kind": "wont-fix-without-reason"})
        elif _SHA_RE.match(reason):
            # A decision not to fix is an argument. A bare hash is the shape of
            # an entry that was closed by reflex.
            problems.append({"kind": "wont-fix-reason-is-a-sha", "value": reason})

    return problems


def _next_action(payload: dict) -> bool:
    """Is there anything here telling the next reader what to do?

    Two accepted forms, because the ledger has two eras: `plan` (structured,
    current) and a resolution opening with an em-dash (the convention before
    `plan` existed). Deliberately NOT required of `open` entries — measured
    against the real store, requiring it there would have turned 40 entries red
    the day it landed, and the only way to clear those is to invent plans for
    work nobody has triaged. A fabricated plan is worse than an empty one.
    """
    if str(payload.get("plan") or "").strip():
        return True
    body = re.sub(r"^[—\-–]\s*", "", str(payload.get("resolution") or "").strip())
    return bool(body.strip(" ()（）"))


def _check_groom(payload: dict) -> list[dict]:
    """A groom claim must carry the work that makes it true.

    The badge is only useful if it cannot be applied cheaply: the queue it
    feeds (`list --ungroomed`) is exactly the set of entries nobody has worked
    out, so one entry wearing the badge without a plan quietly removes itself
    from the work queue while adding nothing.
    """
    if not (payload.get("groomed_by") or payload.get("groomed_at")):
        return []  # not claimed — nothing to hold it to

    problems: list[dict] = []
    for field in GROOM_REQUIRES:
        if not str(payload.get(field, "")).strip():
            problems.append({"kind": f"groom-claim-without-{field}", "field": field})
    if not str(payload.get("groomed_by", "")).strip():
        # Anonymous grooming cannot be audited or re-run; naming the mechanism
        # is what lets a later reader judge how much the badge is worth.
        problems.append({"kind": "groom-claim-without-groomer"})
    if not _DATE_RE.match(str(payload.get("groomed_at", ""))):
        # Without a date the badge cannot go stale, and a badge that never
        # expires is a claim about code that has since moved.
        problems.append({"kind": "groom-claim-bad-date", "value": payload.get("groomed_at")})
    return problems


def validate_entry(payload: dict, *, entry_id: str | None = None,
                   commit_state=None, check_traceability: bool = True) -> list[dict]:
    problems: list[dict] = []

    for field in REQUIRED_FIELDS:
        if field not in payload:
            problems.append({"kind": "missing-field", "field": field})

    if entry_id is not None and payload.get("id") != entry_id:
        # The filename is how every other entry refers to this one. If the two
        # drift, `show <id>` and the generated view disagree about what exists.
        problems.append(
            {
                "kind": "id-filename-drift",
                "filename_id": entry_id,
                "payload_id": payload.get("id"),
            }
        )

    problems.extend(_check_vocabulary(payload))

    if payload.get("stream") == "IMP":
        for field in APP_ONLY_FIELDS:
            # Presence, not truthiness: `update --surface ""` used to slip an
            # empty APP-only key onto an IMP entry and still validate clean,
            # because "" is falsy. `add` never produces that shape (it skips
            # empty values), so nothing in the store relies on the looser test.
            if field in payload:
                problems.append({"kind": "app-field-on-imp-entry", "field": field})

    problems.extend(_check_groom(payload))
    if check_traceability:
        problems.extend(_check_traceability(payload, commit_state))

    return problems


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], capture_output=True, text=True)


def make_commit_state():
    """Resolve a sha to `ok` / `orphan` / `unknown`, or None outside a repo.

    `ok` means reachable from HEAD **or** from `main`. Neither alone works:

      * HEAD alone is right at gate time — the fix is committed on the worktree
        branch and has not been cut over — but stops meaning anything after.
      * `main` alone rejects that same legitimate sha on every cutover, and a
        gate that reds on the normal path is one that gets switched off. This is
        the failure the P2/P3 pairing was supposed to avoid, so it is designed
        against rather than discovered later.

    Returns None (rather than a function that always says `ok`) when there is no
    repo, so the caller can say the check did not run instead of printing a
    clean bill of health it never earned.
    """
    if _git("rev-parse", "--git-dir").returncode != 0:
        return None
    has_main = _git("rev-parse", "--verify", "--quiet", "main^{commit}").returncode == 0
    cache: dict[str, str] = {}

    def state(sha: str) -> str:
        if sha in cache:
            return cache[sha]
        if _git("rev-parse", "--verify", "--quiet", f"{sha}^{{commit}}").returncode != 0:
            result = "unknown"
        elif _git("merge-base", "--is-ancestor", sha, "HEAD").returncode == 0:
            result = "ok"
        elif has_main and _git("merge-base", "--is-ancestor", sha, "main").returncode == 0:
            result = "ok"
        else:
            result = "orphan"
        cache[sha] = result
        return result

    return state


def validate_store(store: Path, *, commit_state=..., ) -> list[dict]:
    store = Path(store)
    if commit_state is ...:
        commit_state = make_commit_state()
    problems: list[dict] = []
    if not store.exists():
        # A typo'd --store used to report "0 problems, exit 0" — a green gate
        # pointed at nothing. Absence is a finding, not a clean bill of health.
        return [{"kind": "store-missing", "path": str(store)}]

    for path in sorted(store.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            problems.append({"kind": "unparseable", "path": str(path), "error": str(exc)})
            continue
        if not isinstance(payload, dict):
            problems.append({"kind": "unparseable", "path": str(path), "error": "not an object"})
            continue
        for problem in validate_entry(payload, entry_id=path.stem,
                                      commit_state=commit_state):
            problems.append({**problem, "path": str(path)})

    return problems


# ---------------------------------------------------------------------------
# store operations
# ---------------------------------------------------------------------------

def add_entry(
    store: Path,
    *,
    stream: str,
    date: str,
    source: str,
    category: str,
    severity: str,
    status: str,
    detail: str,
    resolution: str = "",
    surface: str | None = None,
    repro: str | None = None,
    build: str | None = None,
    entry_id: str | None = None,
    verdict_fields: dict | None = None,
    extra: dict | None = None,
    overwrite: bool = False,
) -> dict:
    """Create one entry file and return the entry.

    Deliberately NOT dry-run-by-default, unlike the mutation subcommands.
    Creating a new file is additive and trivially reversible with git, and
    forcing two calls to file one issue is precisely the kind of friction that
    makes agents route around a tool. The exception is stated in `--help` rather
    than left for the next caller to discover — IMP-0040 is that lesson.
    """
    payload = {
        "schema": SCHEMA,
        "stream": stream,
        "date": date,
        "source": source,
        "category": category,
        "severity": severity,
        "status": status,
        "detail": detail,
        "resolution": resolution,
    }
    for field, value in (("surface", surface), ("repro", repro), ("build", build)):
        if value:
            payload[field] = value
    for field, value in (verdict_fields or {}).items():
        if field not in VERDICT_FIELDS:
            raise ValueError(f"unknown verdict field: {field}")
        if value:
            payload[field] = value

    if not _DATE_RE.match(date or ""):
        raise ValueError(f"date must be YYYY-MM-DD, got {date!r}")

    # Fields the caller carried forward from an entry already on disk. Kept
    # deliberately generic: the previous version named the field families it
    # knew about, so every new family had to remember to add itself here — and
    # the groom stamp did not, which meant a re-import silently ate every plan
    # written by the grooming sweep. Whatever is already composed above wins;
    # everything else survives.
    for field, value in (extra or {}).items():
        if field not in payload and value not in (None, ""):
            payload[field] = value

    payload["id"] = entry_id or make_entry_id(
        stream=stream, date=date, source=source, detail=detail
    )
    if not _SAFE_ID_RE.match(payload["id"]):
        raise ValueError(f"unusable entry id (must be a bare filename): {payload['id']!r}")

    # Creation does not owe traceability. `import` exists to represent HISTORY,
    # and history is full of `fixed` rows whose landing commit was never written
    # down — refusing them here would mean the only way to migrate the ledger is
    # to first solve the audit problem the ledger was migrated to expose.
    # `update` is the interactive path and does enforce it (see
    # _merged_and_validated), and `validate` enforces it over the whole store,
    # so nothing filed this way escapes the gate — it just is not refused at the
    # moment of writing, when the caller may genuinely not know the answer yet.
    problems = validate_entry(payload, entry_id=payload["id"], check_traceability=False)
    if problems:
        raise ValueError(f"invalid entry: {problems}")

    path = entry_path(store, payload["id"])
    if path.exists() and not overwrite:
        existing = json.loads(path.read_text(encoding="utf-8"))
        if existing == payload:
            return payload  # genuinely idempotent: nothing to write
        # Silent clobber is the failure this refuses. Ids are content-derived,
        # so re-filing text that was later triaged re-mints the SAME id and
        # would reset status/resolution with no diff to notice and rc=0. Only
        # `import_legacy` passes overwrite=True, and it merges first.
        raise ValueError(
            f"{payload['id']} already exists with different content; "
            f"use `update` to change it (differing: "
            f"{sorted(k for k in set(existing) | set(payload) if existing.get(k) != payload.get(k))})"
        )

    _write_atomic(path, _dumps(payload))
    return payload


# `detail` and `source` are NOT here: they are digest inputs (make_entry_id), so
# editing them decouples the id from the content it is derived from. Nothing
# recomputes the digest, so the drift is permanent and invisible — and then
# re-filing the original wording re-mints the same id and overwrites the triaged
# entry. A reworded problem statement is a different entry; file it, don't
# mutate this one.
MUTABLE_FIELDS = (
    ("status", "severity", "resolution", "category")
    + APP_ONLY_FIELDS
    + VERDICT_FIELDS
    + GROOM_FIELDS
    + TRACE_FIELDS
)

# Digest fields the `update` parser still accepts — solely so that reaching for
# one gets a named refusal that says where the correction belongs.
#
# `--detail` used to be accepted and then dropped on the floor: `_cmd_update`
# derives its change set from MUTABLE_FIELDS, so the flag parsed, was never
# read, and the command exited 0 printing a changes dict that just omitted it.
# Three entries were filed for that one flag, and a groom plan built on it was
# rejected three times before anyone tested the flag itself.
#
# Deleting the flag would also stop the silence — argparse would say
# "unrecognized arguments" — but it would not say where a correction goes, and
# this is the flag people reach for when an entry's wording turns out wrong.
# The answer is `--resolution`, so the refusal has to be the thing that says it.
REFUSED_UPDATE_FIELDS = ("detail",)


def _merged_and_validated(payload: dict, changes: dict, entry_id: str) -> dict:
    """The single predicate both `update_entry` and the CLI dry-run run through.

    Two copies of this used to exist and the dry-run copy omitted the
    unknown-field check, so a preview could print a clean diff and the identical
    command with --commit could exit 64.
    """
    unknown = [field for field in changes if field not in MUTABLE_FIELDS]
    if unknown:
        raise ValueError(f"unknown field(s): {unknown}; mutable: {sorted(MUTABLE_FIELDS)}")

    updated = dict(payload)
    for field, value in changes.items():
        if value is None:
            continue
        updated[field] = value

    # The real resolver, not the permissive default: refusing a bad sha at write
    # time is the difference between one caller seeing an error and every later
    # `validate` run seeing a defect it cannot attribute to anyone.
    problems = validate_entry(updated, entry_id=entry_id, commit_state=make_commit_state())
    if problems:
        raise ValueError(f"invalid update: {problems}")
    return updated


def update_entry(store: Path, entry_id: str, **changes) -> dict:
    """Change fields on an existing entry, in place, keeping its id.

    The id digest deliberately covers only the fields that identify WHICH
    problem this is, so triaging never moves an entry: if it did, every
    cross-reference would rot and the store would grow a fresh file per status
    change.

    Unknown field names are refused rather than stored. A typo that silently
    created a field nobody reads is the quiet half of the drift this store
    exists to remove.
    """
    payload = load_entry(store, entry_id)
    # Validate BEFORE writing, so a rejected update leaves the file exactly as
    # it was rather than half-applied.
    updated = _merged_and_validated(payload, changes, entry_id)
    _write_atomic(entry_path(store, entry_id), _dumps(updated))
    return updated


def load_entry(store: Path, entry_id: str) -> dict:
    path = entry_path(store, entry_id)
    if not path.exists():
        raise KeyError(entry_id)
    return json.loads(path.read_text(encoding="utf-8"))


def _iter_entries(store: Path):
    store = Path(store)
    if not store.exists():
        return
    for path in sorted(store.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        if isinstance(payload, dict):
            yield payload


def _sort_key(payload: dict) -> tuple:
    # (date, id) rather than filesystem order, so the generated view is stable
    # across machines and reruns.
    return (str(payload.get("date", "")), str(payload.get("id", "")))


def entry_sort_key_by_id(store: Path):
    """Return a key function over entry ids, matching `list_entries` order."""
    index = {payload.get("id"): _sort_key(payload) for payload in _iter_entries(store)}
    return lambda entry_id: index.get(entry_id, ("", entry_id))


def list_entries(
    store: Path,
    *,
    status: str | None = None,
    stream: str | None = None,
    severity: str | None = None,
    category: str | None = None,
    groomed: bool = False,
    ungroomed: bool = False,
) -> list[dict]:
    if groomed and ungroomed:
        raise BacklogError("--groomed and --ungroomed are mutually exclusive")

    wanted = {
        "status": status,
        "stream": stream,
        "severity": severity,
        "category": category,
    }
    hits = [
        payload
        for payload in _iter_entries(store)
        if all(value is None or payload.get(field) == value for field, value in wanted.items())
    ]
    # The badge, not the date, is the predicate: validate_entry() refuses a
    # groomed_at without a groomer, so the two cannot disagree on a valid store.
    if groomed:
        hits = [payload for payload in hits if payload.get("groomed_by")]
    if ungroomed:
        hits = [payload for payload in hits if not payload.get("groomed_by")]
    return sorted(hits, key=_sort_key)


# ---------------------------------------------------------------------------
# legacy table import
# ---------------------------------------------------------------------------

LEGACY_COLUMNS = ("id", "date", "source", "category", "severity", "status", "detail", "resolution")

# What the VIEW renders. Superset of LEGACY_COLUMNS, which stays exactly as it is
# because `parse_legacy_table` still has to read historical 8-column files.
#
# The view used to be pinned at the legacy 8 so that the importer could read its own
# output back — "migration is reversible". The executive ruling of 2026-08-05
# (IMP-20260805-355016) abandoned that property: it was already half-broken, since the
# APP half of the render has never been importable (IMP-20260805-f4ec99 measured rc=2),
# and the importer's only input is a file this module produced. Reversibility stopped
# being worth paying for the moment the migration finished.
#
# `plan` / `acceptance` deliberately stay out: the largest plan in the real store is
# 57KB and a markdown table cell is not where that goes. The footer's groom counter
# answers "how many have a plan"; `show` and `--json` answer "what is it".
VIEW_IMP_COLUMNS = LEGACY_COLUMNS + ("verdict", "verified_at", "cost", "fix_site")

_ID_RE = re.compile(r"^(?:IMP|APP)-(?:\d{4}|\d{8}-[0-9a-f]{6})$")

_EMPTY_CELL = "—"


def _split_row_raw(line: str) -> list[str]:
    """Split a markdown table row on UNESCAPED pipes, WITHOUT cleaning cells.

    IMP-0023's detail contains a literal `\\|\\| true`. Splitting on a naive `|`
    tears that row into the wrong number of columns, which either drops the
    entry or shifts every field after it by one — silently, in both cases.

    Cells come back raw and both callers clean immediately. They used to be raw
    because `_recover_overflowing_row` had to rejoin them; that heuristic was
    removed with IMP-20260805-3df783. Kept raw anyway so the split stays a pure
    tokenizer — stripping here would silently eat the whitespace around an
    unescaped pipe (`` `|| true` `` -> `` `||true` ``) for every future caller.
    """
    parts = re.split(r"(?<!\\)\|", line.strip())
    if parts and not parts[0].strip():
        parts = parts[1:]
    if parts and not parts[-1].strip():
        parts = parts[:-1]
    return parts


def _clean(cell: str) -> str:
    return cell.strip().replace("\\|", "|")


def _anchors_ok(cells: list[str]) -> bool:
    """Do the three closed-vocabulary columns line up?

    This is what tells a data row from a header, a separator, or prose — and it
    is applied to EVERY row, not just overflowing ones. Restricting it to the
    overflow branch meant a row whose columns had shifted took the happy path
    with no check at all.
    """
    if len(cells) < len(LEGACY_COLUMNS):
        return False
    known_categories = {c for cats in CATEGORIES.values() for c in cats}
    return (
        cells[3] in known_categories
        and cells[4] in SEVERITIES
        and cells[5] in STATUSES
    )


def _app_anchors_ok(cells: list[str]) -> bool:
    """The APP table's version of `_anchors_ok`.

    Same idea, three columns to the right: the APP shape inserts `surface` at
    index 3, so its category/severity/status land on 4/5/6.
    """
    if len(cells) < len(APP_COLUMNS):
        return False
    return (
        cells[4] in CATEGORIES["APP"]
        and cells[5] in SEVERITIES
        and cells[6] in STATUSES
    )


def parse_legacy_table(text: str) -> tuple[list[dict], list[dict]]:
    """Parse a HISTORICAL 8-column ledger table.

    SCOPE, deliberately narrowed (IMP-20260805-3df783, executive ruling
    2026-08-05): this reads ledgers in the legacy 8-column format only. It does
    NOT read the current generated view — that renders 12 columns since
    IMP-20260805-355016 and is refused row-by-row with a named cause. It makes no
    promise about hand-written or externally-produced tables either; the previous
    contract implied it could rescue those, and the rescue heuristic
    (`_recover_overflowing_row`) has been retired because its only remaining input
    was a file it corrupted.

    Why narrowing was the right answer rather than hardening: `import` has zero
    automatic callers in this repo, the migration it existed for is finished
    (entries are one-file-per-entry under the store), and every input it will ever
    see again is a frozen historical file. A parser that promises to handle
    arbitrary markdown has to guess at ambiguous rows; one that reads a known
    format can refuse instead. Reading the view is `view_entry_ids`.

    Returns (rows, problems). A row that looks like data but cannot be read is
    REPORTED; it is never silently dropped. That distinction used to be carried
    by `_ID_RE` alone, which conflated "is this a data row" with "is this id
    well-formed" and therefore swallowed `**IMP-0009**`, `imp-0009`, `IMP-9` and
    `[IMP-0009](#anchor)` without a word — detail and all.

    Row identification is now the vocabulary anchor (category/severity/status),
    which is independent of the id, so a malformed id is a finding rather than a
    reason to look away.

    KNOWN LIMIT, stated rather than papered over: a row that is short by one
    column AND carries one unescaped `|` lands on exactly 8 cells with valid
    anchors, and is indistinguishable from a good row. The real IMP-0017 was
    caught only because `||` is two pipes (8 -> 10). An enumerated hole beats an
    anonymous one.

    APP-* rows are skipped rather than reported: the legacy table predates the
    APP stream, so an APP row can only come from the generated view's own second
    table, which has a different column set.
    """
    rows: list[dict] = []
    problems: list[dict] = []

    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line.startswith("|"):
            continue
        raw_cells = _split_row_raw(line)
        if not raw_cells:
            continue
        cells = [_clean(c) for c in raw_cells]

        looks_like_id = bool(_ID_RE.match(cells[0]))

        # Before the IMP anchor gate, not after it. `_anchors_ok` is IMP-shaped,
        # so an APP row — which carries three extra columns — can never satisfy
        # it; checking `APP-` afterwards made that skip unreachable and reported
        # every APP row as malformed. Still anchor-checked in its own shape, so
        # this stays a skip of rows we understand, not a blanket drop.
        if cells[0].startswith("APP-"):
            if not _app_anchors_ok(cells):
                problems.append(
                    {
                        "kind": "malformed-row",
                        "id": cells[0],
                        "line": lineno,
                        "columns": len(cells),
                        "expected": len(APP_COLUMNS),
                    }
                )
            continue

        if not _anchors_ok(cells):
            # Not a data row — unless its first cell claims to be one, in which
            # case the columns are shifted or the row is truncated.
            if looks_like_id:
                problems.append(
                    {
                        "kind": "malformed-row",
                        "id": cells[0],
                        "line": lineno,
                        "columns": len(cells),
                        "expected": len(LEGACY_COLUMNS),
                    }
                )
            continue

        if not looks_like_id:
            problems.append(
                {
                    "kind": "unrecognised-id",
                    "id": cells[0],
                    "line": lineno,
                    "note": "row has valid category/severity/status but its id is not an entry id",
                }
            )
            continue

        if len(cells) > len(LEGACY_COLUMNS):
            # Refuse, never repair. This used to call `_recover_overflowing_row`,
            # which rejoined an over-wide row by assuming the excess came from an
            # unescaped `|` inside `detail`. That assumption held only while the
            # view WAS the legacy 8 columns. Since IMP-20260805-355016 the view
            # renders 12, and the heuristic then produces a confidently wrong row:
            # measured, `detail` swallowed resolution/verdict/verified_at/cost and
            # `resolution` became the fix_site — and because a row came back,
            # `import_legacy` would have written that over a good entry.
            #
            # An over-wide row has TWO possible causes and the note must name both.
            # Assuming only "wrong era" misdiagnoses the one input this narrowed
            # contract still claims to serve: an unescaped `|` inside a cell of a
            # genuine 8-column ledger also lands here. Measured: 30 pre-migration
            # versions of the ledger contain exactly such a row (IMP-0017). It used
            # to import via the recovery heuristic; it is now refused, which is the
            # right call — but "read the store instead" is unactionable advice for
            # someone importing history, and the escape is a one-character fix.
            problems.append(
                {
                    "kind": "malformed-row",
                    "id": cells[0],
                    "line": lineno,
                    "columns": len(cells),
                    "expected": len(LEGACY_COLUMNS),
                    "note": "too many columns — two possible causes. (a) An "
                    "unescaped `|` inside a cell: escape it as `\\|` and re-run; "
                    "this is the historical hand-written case and it is fixable. "
                    "(b) A 12-column generated view: `import` reads the LEGACY "
                    "8-column table only, and the current view is deliberately NOT "
                    "importable (IMP-20260805-355016 / -3df783) — its entries are "
                    "one-file-per-entry under the store, read those instead.",
                }
            )
            continue

        row = dict(zip(LEGACY_COLUMNS, cells))
        if row["resolution"] == _EMPTY_CELL:
            row["resolution"] = ""
        rows.append(row)

    return rows, problems


# The stamp is the ADJACENCY `YYYY-MM-DD 驗證 <VERDICT>`, matched as one unit.
# Anchoring the date on `—(` lost IMP-0029, whose stamp opens with prose.
#
# The verdict token is checked against a CLOSED VOCABULARY rather than against
# punctuation that happens to follow it. The punctuation lookahead this replaces
# had two failures, both reachable in the existing corpus:
#   * `驗證 CONFIRMED-OPEN——說明` matched nothing AND reported nothing. `——`
#     already appears in this ledger (IMP-0021's `成本 S–M——M 的部分是…`), so
#     that shape was luck, not design.
#   * `DUPLICATE-OF-IMP-20260805-abc123` matched nothing, because ids minted by
#     this very module end in lowercase hex, which `[A-Z0-9-]` excludes — the
#     module was incompatible with its own id format.
_STAMP_HEAD_RE = re.compile(r"(\d{4}-\d{2}-\d{2})\s*驗證\s*")
_VERDICT_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9-]*")

# `成本 S–M` uses an EN DASH. Splitting on `-` would report `S` and silently
# halve the estimate.
_COST_RE = re.compile(r"成本\s*([SML](?:[–-][SML])?)")
_COST_PRESENT_RE = re.compile(r"成本")
_FIX_SITE_RE = re.compile(r"`([^`]+)`")
_FIX_SITE_HEAD_RE = re.compile(r"落點")
# A fix site has to look like one. IMP-0021's stamp yields `:738-741` — a bare
# line range whose filename lives in another column — and `見上一列` passes a
# purely syntactic backtick check too. Both become paths that readers trust.
_FIX_SITE_SHAPE_RE = re.compile(r"[/\\]|\.(py|sh|swift|yml|yaml|json|md|ts|js)\b|^\w[\w.-]*:\d")


def _single_or_miss(field: str, values: list[str], misses: list[dict]):
    """Take a value only when the text offers exactly one candidate.

    First-match-wins is how `決策成本 S,出貨成本 L` became cost `S` — the same
    direction of error as splitting `S–M` on the hyphen. 7 of the 10 real 落點
    cells name more than one site, and IMP-0057's second one is annotated
    必須同步 in the prose; dropping it without a word is the loss this module
    refuses everywhere else.
    """
    unique = list(dict.fromkeys(values))
    if len(unique) == 1:
        return unique[0]
    if len(unique) > 1:
        misses.append({"field": field, "reason": f"{len(unique)} candidates, ambiguous", "values": unique})
    return None


def extract_verdict_fields(resolution: str) -> tuple[dict, list[dict]]:
    """Pull the structured stamp out of a resolution cell.

    Returns (fields, misses). Extraction is ADDITIVE and LOSSLESS: `resolution`
    keeps the original text verbatim and stays authoritative, so anything this
    cannot read confidently costs an empty field and a NAMED report — never a
    lost sentence.

    `needs_test` is deliberately not extracted: the sweep recorded testing intent
    in free prose with no consistent encoding, and deriving a boolean from the
    presence of the word 測試 would be a proxy standing in for the property.
    """
    fields: dict = {}
    misses: list[dict] = []

    text = resolution or ""
    head = _STAMP_HEAD_RE.search(text)
    if not head:
        # No stamp: a plain commit hash (the majority) or prose using the word
        # 驗證. Neither is a miss, and reporting them buries the real ones.
        return fields, misses

    token_match = _VERDICT_TOKEN_RE.match(text, head.end())
    token = token_match.group(0).rstrip("-") if token_match else ""

    if token in VERDICTS:
        fields["verdict"] = token
    elif token.startswith(_DUPLICATE_VERDICT_PREFIX):
        target = token[len(_DUPLICATE_VERDICT_PREFIX):]
        if _ID_RE.match(target):
            fields["verdict"] = token
            fields["duplicate_of"] = target
        else:
            misses.append({"field": "verdict", "reason": f"duplicate target is not an entry id: {target!r}"})
    else:
        # Reachable and previously SILENT: dropping the old 驗證 keyword gate
        # killed the false positives and the true reports together.
        misses.append({"field": "verdict", "reason": f"unrecognised verdict token: {token!r}"})

    if "verdict" in fields:
        fields["verified_at"] = head.group(1)

    cost = _single_or_miss("cost", _COST_RE.findall(text), misses)
    if cost:
        fields["cost"] = cost
    elif _COST_PRESENT_RE.search(text) and not any(m["field"] == "cost" for m in misses):
        # `各 S` and `成本 高` both state a cost this pattern cannot read. The
        # previous version reported neither, so "24 of 25 have a cost" quietly
        # meant "24 readable + 1 written in a form we ignore".
        misses.append({"field": "cost", "reason": "成本 present but not in the S/M/L form"})

    fix_head = _FIX_SITE_HEAD_RE.search(text)
    if fix_head:
        candidates = [c for c in _FIX_SITE_RE.findall(text[fix_head.end():]) if _FIX_SITE_SHAPE_RE.search(c)]
        site = _single_or_miss("fix_site", candidates, misses)
        if site:
            fields["fix_site"] = site
        elif not candidates:
            misses.append({"field": "fix_site", "reason": "落點 present but no backticked path-shaped token"})

    return fields, misses


def import_legacy(text: str, store: Path) -> dict:
    """Import the legacy table into the store. Re-runnable and idempotent.

    Re-runnable is a hard requirement, not a nicety: the source table is still
    being edited by other sessions while this migration is in flight, so the
    real import runs last, against a file that moved underneath it. Ids are
    carried over verbatim — the table cross-references them in prose ("see
    IMP-0052"), and renumbering would break every one of those references.

    Entries already in the store that are absent from the table are left alone,
    so importing the IMP table never disturbs APP entries filed via `add`.
    """
    rows, problems = parse_legacy_table(text)
    imported = 0

    for row in rows:
        verdict_fields, misses = extract_verdict_fields(row["resolution"])
        for miss in misses:
            problems.append({"kind": "stamp-not-read", "id": row["id"], **miss})

        # Merge, don't rebuild. add_entry() composes a payload from scratch, so
        # a rerun used to silently erase every field set through `update` —
        # surface/repro/build and any hand-set verdict fields. The importer is
        # advertised as safe to rerun, which made that erasure worse than a
        # crash: the tool that says "rerun me freely" was the one discarding
        # work. Fields the legacy table owns are overwritten; everything else
        # is carried forward.
        try:
            carried = load_entry(store, row["id"])
        except KeyError:
            carried = {}
        # Everything the legacy table does NOT own survives the round trip.
        # Stating it as "not owned by the table" rather than as a list of field
        # names is the point: a list has to be maintained, and the two times it
        # was not, real work was erased with rc=0 and no report.
        legacy_owned = set(LEGACY_COLUMNS) | {"schema", "stream"}
        carried_extra = {k: v for k, v in carried.items() if k not in legacy_owned}

        try:
            add_entry(
                store,
                overwrite=True,
                extra=carried_extra,
                entry_id=row["id"],
                stream=row["id"].split("-", 1)[0],
                date=row["date"],
                source=row["source"],
                category=row["category"],
                severity=row["severity"],
                status=row["status"],
                detail=row["detail"],
                resolution=row["resolution"],
                verdict_fields=verdict_fields,
            )
        except ValueError as exc:
            # Record and keep going. Dying mid-import would leave a partial
            # store, which is worse than a complete store plus a problem list.
            problems.append({"kind": "rejected-row", "id": row["id"], "error": str(exc)})
            continue
        imported += 1

    return {"imported": imported, "problems": problems}


# ---------------------------------------------------------------------------
# generated view
# ---------------------------------------------------------------------------

# `tier: runbook` and not `tier: generated`: `generated` is a registry *kind*
# (docs/registry.yml), while the frontmatter `tier` is checked against
# docs_lint.sh's VALID_TIERS, which has no such value. The precedent is
# docs/snapshot/ios_baseline.md — tier: snapshot in the doc, kind: generated in
# the registry.
_VIEW_HEADER = """<!-- doc-meta
tier: runbook
authority: generated
update_trigger: machine-generated
scope:
  - docs/runbook/backlog/
verified_against: {verified_against}
-->
# 改善 Backlog（kaizen ledger）

> ⚠️ **GENERATED — 不要手改這個檔。** 內容由 `ops/backlog.py render` 從
> `docs/runbook/backlog/*.json` 產生，手改會被下一次 render 覆蓋。
> 要改請用 `ops/backlog.py update <id>`；要新增用 `ops/backlog.py add`。

> 自我提升迴圈的登記處。**SoT 是 `docs/runbook/backlog/`**，本檔是它的 render。所有「工具 / CLI / 文檔 / 架構」摩擦（`IMP-*`）與
> 「app 實際使用」問題（`APP-*`）的 open 問題單一登記處。
> 原則見**鐵律9**（摩擦優先修工具）、分級見 `kg-router`「Tool Friction」、
> 表態見 `kg-receipt`「Tooling Debt」——本文**不複述**，只負責**持久化、追蹤、收斂**。

## 為什麼是一筆一檔

receipt 裡的 tooling debt 會隨 transcript 蒸發。本 ledger 讓每個 raised 問題
**進 git、可回溯、有 owner、追到 resolved**。

存成 `docs/runbook/backlog/<id>.json`（一筆一檔）而非單一表格，是因為單一表格
在多 agent 並發下必然衝突：每次 append 都打同一段行區，而流水號 id 跨 worktree
必撞（檔案在 merge 前彼此看不見）。IMP-0017 自己記著已經撞過兩次。

## Entry schema

- `status`：{statuses}（`wont-fix` 須在 resolution 附理由）
- `category`：IMP 為 {imp_categories}；APP 為 {app_categories}
- `severity`：{severities}
- `resolution`：解決 commit hash，或 wont-fix 理由（這是「可回溯」的關鍵欄）
- 新 id 為 `<STREAM>-<YYYYMMDD>-<hash6>`，內容衍生、不用流水號；既有 `IMP-####` 沿用不改號
- **resolution hash 慣例**：**不得以分支名代替 hash**——分支刪掉之後那筆 resolution 就再也
  指不到任何東西。已經發生過兩次（IMP-0063、IMP-20260805-dd35f8），兩條分支今天都不存在了
- **孤兒 sha 的成因是 rebase**：`ops/worktree_orchestrate.py` 的 `cmd_cutover` 在 advance lock
  內先對分支跑 `git rebase <本地 main>`，**之後**才在主樹 `merge --ff-only`；ff 只是後半段，
  前半段把分支鑄的每個 sha 都改寫。分支已貼著本地 main 時 rebase 是 no-op、sha 得以保留，
  那是常態但**不是保證**。落地機制的完整語意見 `docs/sop/release.md`
- **可回溯的權威欄是 `fixed_by`（結構化），不是 resolution 的散文**：resolution 原文仍是權威
  敘述，但「哪幾顆 commit 讓這個缺陷不再成立」由 `fixed_by: [sha, …]` 回答，`validate` 驗它
- **重新取證欄位**（由 resolution 的 `—(YYYY-MM-DD 驗證 <VERDICT>…)` 戳記抽出，抽取為
  **附加且無損**，resolution 原文永遠是權威）：`verdict`（值域 {verdicts}，或
  `DUPLICATE-OF-<id>`）/ `verified_at` / `cost` / `fix_site` / `duplicate_of`。
  讀不出來的一律**具名回報**、不猜——`ops/backlog.py import` 會印 `stamp-not-read`
- **梳理戳記**（`plan` / `acceptance` / `groomed_at` / `groomed_by`）：與上面的重新取證欄位
  回答**不同問題**——`verdict` 答「這問題還在嗎」，梳理戳記答「**修法想清楚了嗎**」。
  兩者曾被同一次 sweep 寫進同一組欄位，於是「哪些已經被深度論證過」無法從資料回答，
  這組欄位就是為此而存在。`plan` 的標準是**小模型照著就能執行、不需要再自行推導**；
  這條標準是散文、無法機器驗，但它的**前提可以**：宣告 `groomed_by` 就必須同時有
  `plan`、`acceptance`（該紅轉綠的那條命令）與 `fix_site`，否則 `validate` 直接紅。
  查未梳理的佇列用 `ops/backlog.py list --ungroomed`
"""

_IMP_INTRO = """
## IMP — 工具 / CLI / 文檔 / 架構摩擦

owner = `platform-steward`。andon 規則見 `kg-receipt`「Tooling Debt」。
"""

_APP_INTRO = """
## APP — app 實際使用問題

owner = 對應 Line 部門（`ios-engineer` / `backend-engineer`）。
與 IMP 分流的理由：分類詞彙、owner、發現途徑都不同，混在同一條 queue 會讓
platform-steward 的 triage 失效。
"""


def _cell(value: str) -> str:
    """Make a value safe to sit inside a markdown table cell."""
    text = str(value or "")
    text = text.replace("\n", " ").replace("\r", " ")
    return text.replace("|", "\\|")


def _render_table(entries: list[dict], columns: tuple[str, ...]) -> str:
    head = "| " + " | ".join(columns) + " |\n"
    sep = "|" + "|".join("---" for _ in columns) + "|\n"
    body = ""
    for entry in entries:
        cells = [_cell(entry.get(col, "")) or _EMPTY_CELL for col in columns]
        body += "| " + " | ".join(cells) + " |\n"
    return head + sep + body


# SUPERSEDED 2026-08-05 by IMP-20260805-355016. This used to read "the rendered
# table deliberately stays at the legacy 8 columns... a cosmetic column is not
# worth trading reversibility for". Reversibility was abandoned by executive
# ruling: it was already half-broken (the APP half never imported —
# IMP-20260805-f4ec99 measured rc=2) and the importer's only input is a file this
# module produced. The IMP table now renders `VIEW_IMP_COLUMNS` (12). The reason
# this note stays rather than being deleted: the old rule read as settled policy,
# so its absence has to be visible to whoever comes looking for it.

APP_COLUMNS = (
    "id",
    "date",
    "source",
    "surface",
    "category",
    "severity",
    "status",
    "detail",
    "repro",
    "build",
    "resolution",
)


def view_entry_ids(text: str) -> set[str]:
    """Every entry id sitting in the FIRST cell of a table row of a view.

    Deliberately NOT `parse_legacy_table`, which is the obvious reuse and the
    wrong one: it skips every `APP-` row by design, so on the real ledger it
    reports 129 rows for 138 entries. A guard built on it would be blind to the
    whole APP stream — exactly half of what it is meant to protect. Only the id
    column is needed here, so this borrows `_split_row_raw` / `_clean` /
    `_ID_RE` and nothing else.

    The enumerated hole, stated rather than papered over: a first cell that
    does not match `_ID_RE` is not seen. That is the same set of rows
    `parse_legacy_table` reports as `unrecognised-id`.
    """
    ids: set[str] = set()
    for raw in text.splitlines():
        line = raw.strip()
        if not line.startswith("|"):
            continue
        cells = _split_row_raw(line)
        if not cells:
            continue
        first = _clean(cells[0])
        if _ID_RE.match(first):
            ids.add(first)
    return ids


def render_view(store: Path, *, verified_against: str) -> str:
    """Render the human-readable view of the store. Deterministic."""
    imp = list_entries(store, stream="IMP")
    app = list_entries(store, stream="APP")

    out = _VIEW_HEADER.format(
        verified_against=verified_against,
        # Interpolated, not restated: a hand-copied vocabulary in the doc that
        # documents the vocabulary is the drift this store was built to remove.
        imp_categories=" / ".join(f"`{c}`" for c in CATEGORIES["IMP"]),
        app_categories=" / ".join(f"`{c}`" for c in CATEGORIES["APP"]),
        statuses=" → ".join(f"`{s}`" for s in STATUSES),
        severities=" / ".join(f"`{s}`" for s in SEVERITIES),
        verdicts=" / ".join(f"`{v}`" for v in VERDICTS),
    )
    out += _IMP_INTRO + "\n" + _render_table(imp, VIEW_IMP_COLUMNS)
    out += _APP_INTRO + "\n" + _render_table(app, APP_COLUMNS)
    out += f"\n<!-- {len(imp)} IMP + {len(app)} APP entries -->\n"
    # Not a table column: `plan` is prose measured in tens of kilobytes. A count is
    # enough to notice the queue growing; `list --ungroomed` is where you act on it.
    open_entries = [e for e in imp + app if e.get("status") not in ("fixed", "wont-fix")]
    groomed = sum(1 for e in open_entries if e.get("groomed_by"))
    out += f"<!-- groom: {groomed}/{len(open_entries)} unresolved entries have a fix plan -->\n"
    return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _add_store_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--store",
        type=Path,
        default=DEFAULT_STORE,
        help=f"entry directory (default: {DEFAULT_STORE.relative_to(ROOT)})",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="backlog.py",
        description="Backlog store: one file per entry, safe for concurrent agents.",
        epilog=(
            "dry-run contract: `add` lands immediately (additive, git-reversible); "
            "mutations that overwrite existing entries are dry-run by default and "
            "need --commit."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_add = sub.add_parser("add", help="file a new entry (lands immediately)")
    _add_store_arg(p_add)
    p_add.add_argument("--stream", choices=STREAMS, required=True)
    p_add.add_argument("--date", required=True, help="YYYY-MM-DD")
    p_add.add_argument("--source", required=True, help="where this was noticed")
    p_add.add_argument("--category", required=True, help=f"IMP: {CATEGORIES['IMP']} APP: {CATEGORIES['APP']}")
    p_add.add_argument("--severity", choices=SEVERITIES, required=True)
    p_add.add_argument("--status", choices=STATUSES, default="open")
    p_add.add_argument("--detail", required=True)
    p_add.add_argument("--resolution", default="")
    p_add.add_argument("--surface", help="APP only: reader/vocabulary/notebook/...")
    p_add.add_argument("--repro", help="APP only: how to reproduce")
    p_add.add_argument("--build", help="APP only: build the problem was seen on")
    p_add.add_argument("--id", dest="entry_id", help="explicit id (migration of legacy IMP-#### only)")
    p_add.add_argument("--json", action="store_true")

    p_list = sub.add_parser("list", help="list entries")
    _add_store_arg(p_list)
    p_list.add_argument("--status", choices=STATUSES)
    p_list.add_argument("--stream", choices=STREAMS)
    p_list.add_argument("--severity", choices=SEVERITIES)
    p_list.add_argument("--category")
    p_list.add_argument(
        "--ungroomed",
        action="store_true",
        help="only entries nobody has worked out a fix plan for (the groom queue)",
    )
    p_list.add_argument(
        "--groomed", action="store_true", help="only entries carrying a groom stamp"
    )
    p_list.add_argument("--json", action="store_true")

    p_show = sub.add_parser("show", help="show one entry")
    _add_store_arg(p_show)
    p_show.add_argument("id")
    p_show.add_argument("--json", action="store_true")

    p_validate = sub.add_parser("validate", help="schema-check every entry")
    _add_store_arg(p_validate)
    p_validate.add_argument("--json", action="store_true")

    p_update = sub.add_parser(
        "update",
        help="change fields on an existing entry (DRY-RUN by default, --commit to land)",
    )
    _add_store_arg(p_update)
    p_update.add_argument("id")
    p_update.add_argument("--status", choices=STATUSES)
    p_update.add_argument("--severity", choices=SEVERITIES)
    p_update.add_argument("--category")
    p_update.add_argument("--resolution")
    p_update.add_argument(
        "--detail",
        help="REFUSED: a digest input. Corrections go in --resolution; a reworded "
        "problem is a new entry (`add`). Kept on the parser so the attempt gets "
        "an answer instead of 'unrecognized arguments'",
    )
    p_update.add_argument("--verdict")
    p_update.add_argument("--cost")
    p_update.add_argument("--fix-site", dest="fix_site")
    p_update.add_argument("--verified-at", dest="verified_at")
    # The other half of the same drift the refusal above fixes: these are in
    # MUTABLE_FIELDS and `add` offers them, but `update` never did — so an APP
    # entry filed without a repro could only get one by hand-editing the JSON,
    # which is the failure this store exists to remove. `duplicate_of` was
    # reachable only through the legacy importer's verdict parsing, so
    # `--verdict DUPLICATE-OF-<id>` set the verdict and left the field empty.
    p_update.add_argument("--surface", help="APP only: reader/vocabulary/notebook/...")
    p_update.add_argument("--repro", help="APP only: how to reproduce")
    p_update.add_argument("--build", help="APP only: build the problem was seen on")
    p_update.add_argument(
        "--duplicate-of",
        dest="duplicate_of",
        help="entry id this turned out to duplicate; pair with --verdict DUPLICATE-OF-<id>",
    )
    p_update.add_argument(
        "--plan",
        help="how to fix it, concrete enough for a small model to execute without re-deriving",
    )
    p_update.add_argument("--acceptance", help="the command that must go red before / green after")
    p_update.add_argument("--groomed-at", dest="groomed_at", help="YYYY-MM-DD")
    p_update.add_argument(
        "--groomed-by", dest="groomed_by", help="what did the grooming, e.g. workflow:groom@v1"
    )
    p_update.add_argument(
        "--fixed-by", dest="fixed_by", nargs="+", metavar="SHA",
        help="commit(s) that made the defect stop being true; required by status=fixed. "
             "Fill it AFTER the fix lands — see reanchor if a rebase orphans one",
    )
    p_update.add_argument("--commit", action="store_true")
    p_update.add_argument("--json", action="store_true")

    p_reanchor = sub.add_parser(
        "reanchor",
        help="re-point orphaned fixed_by shas at their post-rebase equivalents "
             "(DRY-RUN by default, --commit to land)",
    )
    p_reanchor.add_argument("ids", nargs="*", help="entry ids; default = every entry with an orphan")
    p_reanchor.add_argument("--store", type=Path, default=DEFAULT_STORE)
    p_reanchor.add_argument(
        "--search-depth", type=int, default=800,
        help="how many commits back from main to scan for a patch-id match (default 800). "
             "The bound is REPORTED, never silent: a miss inside the window and a miss "
             "because the window ended are different answers",
    )
    p_reanchor.add_argument("--commit", action="store_true")
    p_reanchor.add_argument("--json", action="store_true")

    p_import = sub.add_parser(
        "import",
        help="import a HISTORICAL 8-column ledger table into the store "
             "(re-runnable, idempotent; NOT the current view)",
        description="Reads the legacy 8-column ledger format only. The generated "
                    "view is wider and is deliberately not importable "
                    "(IMP-20260805-355016 / -3df783) — the store, not the view, is "
                    "the authority. `--from` is required: it used to default to the "
                    "generated view, which since the widening can only ever fail.",
    )
    _add_store_arg(p_import)
    p_import.add_argument("--from", dest="source_doc", type=Path, required=True,
                          help="path to a historical 8-column ledger table")
    p_import.add_argument("--commit", action="store_true", help="actually write (default: dry-run)")
    p_import.add_argument("--json", action="store_true")

    p_render = sub.add_parser("render", help="regenerate the human-readable view from the store")
    _add_store_arg(p_render)
    p_render.add_argument("--out", type=Path, default=DEFAULT_VIEW)
    p_render.add_argument(
        "--verified-against",
        help="commit sha for doc-meta (default: merge-base with origin/main — NOT HEAD; "
             "see _doc_anchor, a branch sha gets orphaned by rebase)",
    )
    p_render.add_argument("--commit", action="store_true", help="actually write (default: stdout)")
    p_render.add_argument(
        "--allow-drop",
        dest="allow_drop",
        nargs="+",
        metavar="ID",
        default=[],
        help="ids you accept deleting: render refuses to write a view that loses an "
             "entry the current --out has and the new render does not emit (the "
             "refusal names the COMPLETE set to pass here — on stderr, and as "
             "`would_drop` under --json; copy it as printed). Named, not a bare flag, "
             "so a bypass cannot be reached for without reading what it drops",
    )
    p_render.add_argument(
        "--check",
        action="store_true",
        help="compare the on-disk view against a fresh render; exit 1 if stale "
             "(wired into docs/registry.yml's `check:` for runbook.improvement_backlog)",
    )
    p_render.add_argument("--json", action="store_true")

    return parser


def _cmd_add(args) -> int:
    entry = add_entry(
        args.store,
        stream=args.stream,
        date=args.date,
        source=args.source,
        category=args.category,
        severity=args.severity,
        status=args.status,
        detail=args.detail,
        resolution=args.resolution,
        surface=args.surface,
        repro=args.repro,
        build=args.build,
        entry_id=args.entry_id,
    )
    if args.json:
        print(json.dumps({"schema": "kg.backlog.add.v1", "entry": entry}, ensure_ascii=False))
    else:
        print(f"{entry['id']}  [{entry['stream']}/{entry['category']}/{entry['severity']}]")
        print(f"  {entry['detail'][:120]}")
    return 0


def _cmd_list(args) -> int:
    entries = list_entries(
        args.store,
        status=args.status,
        stream=args.stream,
        severity=args.severity,
        category=args.category,
        groomed=args.groomed,
        ungroomed=args.ungroomed,
    )
    if args.json:
        print(json.dumps({"schema": "kg.backlog.list.v1", "entries": entries}, ensure_ascii=False))
        return 0
    for entry in entries:
        print(
            f"{entry['id']:<24} {entry['status']:<12} {entry['severity']:<5} "
            f"{entry['category']:<12} {entry['detail'][:70]}"
        )
    print(f"\n{len(entries)} entries")
    return 0


def _cmd_show(args) -> int:
    try:
        entry = load_entry(args.store, args.id)
    except KeyError:
        print(f"no such entry: {args.id}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps({"schema": "kg.backlog.show.v1", "entry": entry}, ensure_ascii=False))
        return 0
    for field in REQUIRED_FIELDS + APP_ONLY_FIELDS + VERDICT_FIELDS + GROOM_FIELDS:
        if field in entry and field != "schema":
            print(f"{field:<12} {entry[field]}")
    return 0


def _patch_id(rev: str) -> str | None:
    """`git patch-id --stable` of one commit, or None if it has no diff to hash."""
    show = _git("show", rev)
    if show.returncode != 0 or not show.stdout:
        return None
    proc = subprocess.run(
        ["git", "patch-id", "--stable"], input=show.stdout, capture_output=True, text=True
    )
    out = proc.stdout.split()
    return out[0] if out else None


def reanchor_store(store: Path, ids: list[str] | None = None, *, search_depth: int = 800) -> dict:
    """Map orphaned `fixed_by` shas onto their post-rebase equivalents on main.

    The mechanism is measured, not assumed: every orphan in this repo's audit
    was the *same change* rewritten by the rebase inside `cutover`, so
    `git patch-id --stable` matches it byte-for-byte against a reachable commit.

    Two deliberate refusals, both from the same rule — only move on proof:

      * no match inside the window: reported as unmatched, NOT guessed at. One
        real case (IMP-0062) had a whole-commit patch-id that differed because
        the rebase resolved a conflict differently; a fuzzy matcher would have
        silently picked a neighbour.
      * more than one match: ambiguous, so nothing moves.

    The search window is a bound, and a bound that is not reported reads as
    "searched everything". `searched` is in the result for that reason.
    """
    state = make_commit_state()
    if state is None:
        raise BacklogError("reanchor needs a git repository (no --git-dir found)")

    log = _git("rev-list", f"--max-count={search_depth}", "main")
    if log.returncode != 0:
        raise BacklogError("reanchor needs a resolvable `main`")
    candidates = log.stdout.split()

    by_patch: dict[str, list[str]] = {}
    for rev in candidates:
        pid = _patch_id(rev)
        if pid:
            by_patch.setdefault(pid, []).append(rev)

    plan: list[dict] = []
    for payload in _iter_entries(store):
        if ids and payload.get("id") not in ids:
            continue
        shas = payload.get("fixed_by") or []
        orphans = [s for s in shas if _SHA_RE.match(s) and state(s) == "orphan"]
        if not orphans:
            continue
        moves, unmatched = {}, []
        for sha in orphans:
            pid = _patch_id(sha)
            hits = by_patch.get(pid, []) if pid else []
            if len(hits) == 1:
                moves[sha] = hits[0][:9]
            else:
                unmatched.append({"sha": sha, "candidates": len(hits)})
        if moves or unmatched:
            plan.append({
                "id": payload["id"],
                "moves": moves,
                "unmatched": unmatched,
                "new_fixed_by": [moves.get(s, s) for s in shas],
            })
    return {"plan": plan, "searched": len(candidates), "search_depth": search_depth}


def _cmd_reanchor(args) -> int:
    result = reanchor_store(args.store, args.ids or None, search_depth=args.search_depth)
    landed = []
    if args.commit:
        for item in result["plan"]:
            if item["moves"]:
                update_entry(args.store, item["id"], fixed_by=item["new_fixed_by"])
                landed.append(item["id"])
    result["mode"] = "commit" if args.commit else "dry-run"
    result["landed"] = landed
    if args.json:
        print(json.dumps({"schema": "kg.backlog.reanchor.v1", **result}, ensure_ascii=False))
        return 0
    print(f"[{result['mode']}] scanned {result['searched']} commits on main "
          f"(--search-depth {result['search_depth']})")
    for item in result["plan"]:
        for old, new in item["moves"].items():
            print(f"  {item['id']}: {old} -> {new}")
        for miss in item["unmatched"]:
            print(f"  {item['id']}: {miss['sha']} UNMATCHED "
                  f"({miss['candidates']} patch-id candidates in window) — not guessed")
    if not result["plan"]:
        print("  no orphaned fixed_by shas")
    elif not args.commit:
        print("  (dry-run — pass --commit to land)")
    return 0


def _cmd_validate(args) -> int:
    problems = validate_store(args.store)
    if args.json:
        print(
            json.dumps(
                {"schema": "kg.backlog.validate.v1", "problems": problems, "ok": not problems},
                ensure_ascii=False,
            )
        )
    else:
        for problem in problems:
            print(f"ERROR {problem.get('path', '')} — {problem['kind']} {problem}")
        print(f"{len(problems)} problems")
    return 2 if problems else 0


def _cmd_update(args) -> int:
    # Derived from MUTABLE_FIELDS, not a second hand-written list. The previous
    # hand-written tuple happened to be a subset, so the dry-run path and the
    # commit path agreed by coincidence: adding one parser flag produced a clean
    # dry-run followed by an exit-64 --commit. That is IMP-0040's shape inside
    # the code that cites IMP-0040.
    refused = [f for f in REFUSED_UPDATE_FIELDS if getattr(args, f, None) is not None]
    if refused:
        # Before anything else, and covering the whole invocation: a command
        # that applied its mutable half and complained about the rest would
        # leave the caller guessing which half landed.
        flags = ", ".join(f"--{f}" for f in refused)
        # Mode-prefixed like every other output of this command: without it the
        # dry-run and --commit forms produced byte-identical text, so the reader
        # could not tell from the output which one they had just run.
        print(
            f"[{'commit' if args.commit else 'dry-run'}] "
            f"{flags} cannot be changed: {', '.join(DIGEST_FIELDS)} are the inputs "
            f"make_entry_id hashes, so editing one would decouple {args.id} from the "
            f"content its id is derived from.\n"
            f"  correcting the record  -> put the correction in --resolution\n"
            f"  a different problem    -> file it with `add`; a reworded problem "
            f"statement is a different entry\n"
            f"nothing was written.",
            file=sys.stderr,
        )
        return 64

    changes = {
        field: getattr(args, field, None)
        for field in MUTABLE_FIELDS
        if getattr(args, field, None) is not None
    }
    if not changes:
        print("nothing to change; pass at least one field", file=sys.stderr)
        return 64

    try:
        before = load_entry(args.store, args.id)
    except KeyError:
        print(f"no such entry: {args.id}", file=sys.stderr)
        return 1

    if args.commit:
        after = update_entry(args.store, args.id, **changes)
    else:
        # Same predicate as the real path — including the unknown-field check,
        # which the previous dry-run skipped.
        after = _merged_and_validated(before, changes, args.id)

    diff = {k: {"from": before.get(k, ""), "to": after[k]} for k in changes}
    if args.json:
        print(json.dumps(
            {"schema": "kg.backlog.update.v1",
             "mode": "commit" if args.commit else "dry-run",
             "id": args.id, "changes": diff}, ensure_ascii=False))
    else:
        print(f"[{'commit' if args.commit else 'dry-run'}] {args.id}")
        for field, change in diff.items():
            print(f"  {field}: {str(change['from'])[:60]!r} -> {str(change['to'])[:60]!r}")
        if not args.commit:
            print("  (dry-run — pass --commit to land)")
    return 0


def _doc_anchor() -> str:
    """Resolve `verified_against` for the generated view.

    Anchored on the merge-base with **origin/main**, not on HEAD and not on
    local main. Three separate ways to get this wrong, all of them silent, all
    of them hit here:

      * HEAD — rebasing (adding review trailers did exactly this) or
        squash-merging orphans every sha the branch minted, and docs_lint then
        rejects the file. That was the original bug.
      * `git merge-base --short` — no such flag. The first attempt at the fix
        raised CalledProcessError on every call and fell through to the next
        candidate, so the function kept doing the thing its docstring said it
        had stopped doing. A fix nobody verifies is a claim.
      * local main — this repo's topology is local-main-as-trunk, so local main
        runs AHEAD of origin (9 commits at the time of writing). An anchor
        reachable from local main but not from origin/main is *precisely*
        IMP-0038's definition: "錨點指向從未進入 origin 的 commit", which
        passes here only because the local object still exists and fails in CI.

    docs_lint checks reachability from HEAD, which every one of those wrong
    answers satisfies — so nothing downstream would catch it. The candidates
    below are ordered strongest-first and degradation is REPORTED on stderr
    rather than silent, because an enumerated hole beats an anonymous one.
    """
    candidates = (
        ("origin/main", ["git", "merge-base", "HEAD", "origin/main"]),
        ("main", ["git", "merge-base", "HEAD", "main"]),
        ("HEAD", ["git", "rev-parse", "HEAD"]),
    )
    for index, (label, argv) in enumerate(candidates):
        try:
            out = subprocess.run(argv, capture_output=True, text=True, check=True, cwd=ROOT)
        except (OSError, subprocess.CalledProcessError):
            continue
        value = out.stdout.strip()
        if not value:
            continue
        if index:
            print(
                f"backlog: doc anchor fell back to merge-base with {label}; "
                f"an anchor unreachable from origin/main is IMP-0038's shape",
                file=sys.stderr,
            )
        return value[:9]
    return "unknown"


def _cmd_import(args) -> int:
    text = args.source_doc.read_text(encoding="utf-8")

    if not args.commit:
        # Dry-run into a throwaway store so the reported counts come from the
        # real code path rather than a separate estimate that could disagree.
        with tempfile.TemporaryDirectory() as tmp:
            result = import_legacy(text, Path(tmp) / "backlog")
        result["mode"] = "dry-run"
    else:
        result = import_legacy(text, args.store)
        result["mode"] = "commit"

    result["source"] = str(args.source_doc)
    if args.json:
        print(json.dumps({"schema": "kg.backlog.import.v1", **result}, ensure_ascii=False))
    else:
        print(f"[{result['mode']}] imported {result['imported']} entries from {args.source_doc}")
        for problem in result["problems"]:
            print(f"  {problem['kind']}: {problem.get('id', '?')} — {problem.get('note', problem)}")
    # Recovered rows are advisory; only rows that could not be taken are a
    # failure, because those are entries that would vanish.
    lost = [p for p in result["problems"] if p["kind"] in ("malformed-row", "rejected-row")]
    return 2 if lost else 0


def _read_outgoing_view(path: Path) -> str | None:
    """The view about to be replaced, or None if there is nothing to replace.

    Raised as a BacklogError rather than let through: adding this read means
    `--out` can now fail to be read, and a UnicodeDecodeError is not something
    main()'s handler catches, so a caller who pointed --out at a non-view would
    get a traceback where they used to get a file.
    """
    if not path.exists():
        return None
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise BacklogError(
            f"cannot read the current {path} to check what a render would delete "
            f"({exc.__class__.__name__}); --out must point at a rendered view. "
            f"Nothing was written."
        ) from exc


def _strip_doc_meta(text: str) -> str:
    """Drop the leading `<!-- doc-meta ... -->` block, if present.

    This is what keeps `render --check` from being a CLOCK. The block carries
    `verified_against`, which `_doc_anchor()` resolves to the merge-base with
    **origin/main** — so it moves whenever origin/main moves, with no change to
    a single backlog entry. A whole-file compare would therefore turn red on
    other people's pushes and get switched off within a week.

    Nothing else is normalized away: every table row, the `<!-- N IMP + M APP
    entries -->` counter and the groom footer are all downstream of
    docs/runbook/backlog/*.json and stay inside the comparison.
    """
    if not text.startswith("<!-- doc-meta"):
        return text
    _, sep, rest = text.partition("\n-->\n")
    return rest if sep else text


def _cmd_render(args) -> int:
    verified = args.verified_against or _doc_anchor()
    text = render_view(args.store, verified_against=verified)

    if args.check:
        if args.commit:
            print("--check 與 --commit 互斥", file=sys.stderr)
            return 64
        if not args.out.exists():
            print(f"STALE {args.out} 不存在(跑: ./ops/backlog.py render --commit)")
            return 1
        on_disk = args.out.read_text(encoding="utf-8")
        if _strip_doc_meta(on_disk) != _strip_doc_meta(text):
            print(f"STALE {args.out} — 內容與 store 不一致(跑: ./ops/backlog.py render --commit)")
            return 1
        print(f"{args.out} is up to date.")
        return 0

    # Diffed against the text about to be WRITTEN, not against the store's id
    # set: what has to survive is the artifact. Comparing to the store would
    # wave through an entry that render_view itself failed to emit, and today
    # the two sets happen to agree, so that mistake would look correct.
    outgoing = _read_outgoing_view(args.out)
    dropped = (
        [] if outgoing is None else sorted(view_entry_ids(outgoing) - view_entry_ids(text))
    )
    authorised = set(args.allow_drop)
    unauthorised = [entry_id for entry_id in dropped if entry_id not in authorised]

    if dropped:
        # Both paths speak. The defect being fixed is silence, so `--allow-drop`
        # buys permission, not quiet.
        refusing = bool(unauthorised) and args.commit
        named = unauthorised if refusing else dropped
        lines = [
            f"{'REFUSED' if refusing else 'WARNING'}: {', '.join(named)} "
            f"{'appears' if len(named) == 1 else 'appear'} in {args.out} but not in "
            f"the store; writing deletes {'it' if len(named) == 1 else 'them'}."
        ]
        if refusing:
            # Routed by stream, because the two recovery routes are not
            # interchangeable: `import` parses the legacy IMP table and skips
            # every APP row, so offering it for an APP id would hand the caller
            # a command that exits 0 and restores nothing — this defect again,
            # one layer down.
            if any(entry_id.startswith("IMP-") for entry_id in named):
                lines.append(
                    f"  lost IMP rows      -> ops/backlog.py import --from {args.out} --commit"
                )
            if any(entry_id.startswith("APP-") for entry_id in named):
                lines.append(
                    "  lost APP rows      -> not recoverable that way (the importer reads "
                    "the IMP table only); re-file with `ops/backlog.py add`"
                )
            # `dropped`, not `named`: the header answers "what stopped this
            # run", the remedy answers "what do I type". Printing the remainder
            # here made the documented copy-paste workflow a closed loop —
            # authorising IMP then pasting the APP-only flag re-exposes IMP, and
            # round it goes. The flag is absolute, so it has to be complete.
            lines.append("  the loss is meant  -> --allow-drop " + " ".join(dropped))
            lines.append("nothing was written.")
        elif not args.commit:
            # A dry-run neither writes nor drops, whatever --allow-drop says, so
            # it must not report a deletion it is not performing.
            lines.append(
                "nothing was written (dry-run); --commit would "
                + ("drop them." if not unauthorised else "be refused unless --allow-drop names them.")
            )
        else:
            lines.append("dropping them as authorised by --allow-drop.")
        print("\n".join(lines), file=sys.stderr)

    if unauthorised and args.commit:
        # 2, not 64: 64 is this file's usage-error code (`_cmd_update`), while 2
        # is what `import` and `validate` return when data would be lost.
        if args.json:
            print(
                json.dumps(
                    {
                        "schema": "kg.backlog.render.v1",
                        "out": str(args.out),
                        "written": False,
                        # Three different questions, so three keys. `dropped`
                        # used to carry `unauthorised`, which made the payload
                        # contradict itself: nothing was deleted here at all.
                        "dropped": [],
                        "refused": unauthorised,
                        # The COMPLETE --allow-drop set, matching the stderr
                        # remedy line. Handing back only `refused` would walk a
                        # machine caller into the same loop a human had.
                        "would_drop": dropped,
                    },
                    ensure_ascii=False,
                )
            )
        return 2

    if args.commit:
        _write_atomic(args.out, text)
        # len(text) is CHARACTERS. This ledger is mostly CJK, where that
        # undercounts bytes by ~3x — the first render reported "35867 bytes" for
        # a 54724-byte file, which reads exactly like a third of the content
        # went missing. Report what the label claims.
        size = len(text.encode("utf-8"))
        if args.json:
            print(
                json.dumps(
                    {
                        "schema": "kg.backlog.render.v1",
                        "out": str(args.out),
                        "written": True,
                        "bytes": size,
                        "characters": len(text),
                        # Unconditional, including the empty list. Under `--json`
                        # stdout is the machine channel (plain `render` puts the
                        # view itself there instead), and an authorised
                        # deletion used to leave a payload byte-identical in
                        # shape to a clean render — the silence this whole entry
                        # is about, re-created one channel over. A key that
                        # appears only when it has news does not fix that: a
                        # reader with no reason to look for it never learns it
                        # exists. Always present, so `if payload["dropped"]` is
                        # a check a caller can actually write.
                        "dropped": dropped,
                    },
                    ensure_ascii=False,
                )
            )
        else:
            print(f"wrote {args.out} ({size} bytes, verified_against={verified})")
    else:
        sys.stdout.write(text)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    handlers = {
        "add": _cmd_add,
        "list": _cmd_list,
        "show": _cmd_show,
        "validate": _cmd_validate,
        "update": _cmd_update,
        "import": _cmd_import,
        "render": _cmd_render,
        "reanchor": _cmd_reanchor,
    }
    try:
        return handlers[args.command](args)
    except (BacklogError, ValueError) as exc:
        print(f"ERROR {exc}", file=sys.stderr)
        return 64


if __name__ == "__main__":
    sys.exit(main())
