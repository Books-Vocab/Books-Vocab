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

Entries live in a resolved store as `.json` and NOT as `.md` on purpose:
`ops/docs_lint.sh:216` scans every `docs/**/*.md` and demands a
`<!-- doc-meta -->` block with a reachable `verified_against`. Storing 59
ledger rows as markdown would manufacture 59 doc-meta liabilities. Keeping them
as `.json` costs nothing and needs no carve-out in the lint tool. The historical
`docs/runbook/backlog/` path remains the compatibility default;
`KG_BACKLOG_STORE` selects an independent store outside the code checkout.

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
import contextlib
import datetime
import hashlib
import inspect
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# The checkout whose history this ledger's `fixed_by` shas name. Separate from
# ROOT because ROOT is also the anchor for file layout and help text, and only
# this one is a question about git.
GIT_REPO = ROOT
sys.path.insert(0, str(Path(__file__).resolve().parent))
import backlog_store as _backlog_store  # noqa: E402

DEFAULT_STORE = _backlog_store.resolve_store(ROOT)
DEFAULT_VIEW = _backlog_store.default_view(DEFAULT_STORE, ROOT)
_STORE_LOCK_STATE = threading.local()
_ENTRY_LOCK_STATE = threading.local()

from lib import dispatch_preflight  # noqa: E402
from lib.lock_wait import LockUnavailable, exclusive_lock  # noqa: E402
from lib.streaming_command import run_streamed_command  # noqa: E402
import backlog_acceptance as _backlog_acceptance  # noqa: E402
import backlog_mutations as _backlog_mutations  # noqa: E402
import backlog_verification as _backlog_verification  # noqa: E402
import backlog_reanchor as _backlog_reanchor  # noqa: E402
import backlog_wave as _backlog_wave  # noqa: E402
import backlog_contract as _backlog_contract  # noqa: E402
import backlog_view as _backlog_view  # noqa: E402
import backlog_legacy as _backlog_legacy  # noqa: E402
import backlog_query as _backlog_query  # noqa: E402
from kg_board.scope import coerce_scope, scope_problems, scope_status  # noqa: E402

# Stdlib-only, like the rest of this file: `ops/lib/streaming_command.py` imports
# nothing outside the standard library, so the sandboxed `uv run --no-project`
# the cutover gate uses to run these tests can still load it.

SCHEMA = "kg.backlog.entry.v1"

ACCEPTANCE_TIMEOUT_SECONDS = _backlog_acceptance.ACCEPTANCE_TIMEOUT_SECONDS
AUDIT_TIMEOUT_SECONDS = _backlog_acceptance.AUDIT_TIMEOUT_SECONDS
AUDIT_POPULATION = _backlog_acceptance.AUDIT_POPULATION
AUDIT_CAVEAT = _backlog_acceptance.AUDIT_CAVEAT
_SHELL_CANNOT_RUN = _backlog_acceptance._SHELL_CANNOT_RUN
_AUDIT_UNRUNNABLE = _backlog_acceptance._AUDIT_UNRUNNABLE

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
# `in-progress` is GONE, and it is derived now — see `held_tickets()`.
#
# It never had any mechanical behaviour of its own: every rule in
# `_check_traceability` that named `triaged` named `in-progress` too, in the same
# set. Two status values, one set of obligations.
#
# What killed it is that the claim plane made the same fact available for real. The
# worktree ledger records which worktree holds which ticket and when it claimed it,
# so "somebody is working on this" is DERIVABLE — and a stored copy of a derivable
# fact is a copy that drifts. Measured at the moment this landed: the store had
# exactly one `in-progress` entry (IMP-20260805-953840) and the ledger's only active
# claim was on a completely different ticket. Nothing reconciled them, and nothing
# ever would have: `cmd_resolve` changes the ledger record and never looks at the
# entry, so an abandoned worktree leaves its ticket `in-progress` forever.
STATUSES = ("open", "triaged", "contract-blocked", "fixed", "wont-fix")

# Accepted on READ so old entries and old branches still load, refused on WRITE.
# A hard removal would make every pre-existing `in-progress` entry unloadable, which
# turns a cleanup into an outage; `validate` names it and says where to go instead.
RETIRED_STATUSES = {"in-progress": "triaged"}

# What the LEGACY PARSER will recognise as a status. Wider than STATUSES on purpose:
# `_anchors_ok` uses the closed vocabularies to tell a data row from prose, and the
# frozen 8-column fixture is historical text that still contains retired values.
# Narrowing it turned three real rows into `malformed-row` findings — entries that
# would have disappeared on import, which is precisely the loss the migration's
# fidelity gate exists to catch. `import_legacy` maps them forward on the way in.
PARSEABLE_STATUSES = tuple(STATUSES) + tuple(RETIRED_STATUSES)

# The only status a staged closure can carry, and not a default the caller may
# override — see `_cmd_stage`. A wave exists because the landing commit does not
# exist yet, and `fixed` is the one status that needs a landing commit.
STAGED_STATUS = "fixed"

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

# The two fields written for a HUMAN, and the only two in this schema whose
# reader is not an agent.
#
#   brief -> one sentence, plain language: what is broken / missing, and who
#            feels it. Not how to fix it, and no filenames, line numbers or
#            acronyms — those are `detail`'s job and they are what makes `detail`
#            unreadable to the person doing the sorting.
#   scope -> a structured file claim: `files[]` names each expected path and
#            marks it `add` or `modify`. Legacy prose stays readable but is not
#            treated as a known file range by the delivery progress board.
#
# Why they cannot be derived from what already exists: the phone board renders
# the first 400 characters of `detail`, which is technical prose addressed to
# whoever will execute the entry. The three actions that surface offers — pin,
# reorder, defer — each need "is this worth doing first", and none of them need
# "which line changes". With 122 unresolved entries the board's write surface
# existed and was functionally inert.
#
# And `fix_site` cannot double as either: it is a CODE ANCHOR
# (`ops/docs_lint.sh:180`) for the executor. Different reader, different register,
# different precision. A field serving two readers serves the louder one.
BRIEF_FIELDS = ("brief", "scope")

# Grooming stamped on or after this date must carry a human-facing brief.
# Everything groomed before it stays legal — see _check_groom() for why the
# ratchet is keyed on the date and not on a list of ids.
BRIEF_REQUIRED_SINCE = "2026-08-09"

# Scope was redefined after the brief rule had already grandfathered several
# grooming waves.  The current store's newest grooming stamp is 2026-08-17;
# start the stored-data ratchet the following day so validation does not rewrite
# existing backfill debt as an unrelated gate failure.  New grooming acts are
# stricter than this grandfather window: _check_groom_write() rejects legacy
# Scope immediately, regardless of the date supplied by the caller.
SCOPE_REQUIRED_SINCE = "2026-08-18"

# Fields that only make sense for an app-usage report. An IMP entry carrying a
# `surface` means someone filed an app problem into the tooling stream.
APP_ONLY_FIELDS = ("surface", "repro", "build")

# Structured results of a re-verification sweep, extracted from the resolution
# stamp. Optional on every entry; see extract_verdict_fields().
VERDICT_FIELDS = ("verified_at", "verdict", "cost", "fix_site", "duplicate_of",
                  # Who checked, and with what. A verdict nobody can attribute
                  # cannot be judged, and one with no command attached cannot be
                  # re-run — which is the difference between a re-verification
                  # and a ritual (IMP-20260805-2834b2).
                  "verified_by", "verified_evidence")

# The one structured, machine-checkable answer to "what made this stop being
# true". `resolution` stays authoritative as PROSE, but prose can only be read
# by position heuristics, and the heuristic is measurably wrong.
#
# The number depends on how generously you match, so both ends are stated with
# their rule (an unqualified count here was the first thing a review caught, and
# it was wrong): under the MOST generous rule anyone could defend — any sha
# anywhere in the resolution, 6-char prefixes, matching any element of fixed_by
# — position-0 is right for at most **47 of 63**; under strict first-vs-first it
# is 45. Either way 3 of the 63 carry no sha in the resolution at all. And one
# of the entries the heuristic scores as CORRECT (IMP-0063) is an *incidental*
# hash the text mentions for an unrelated reason, which is reachable from main
# and therefore invisible to any reachability check. A field that only ever
# holds landing commits cannot be satisfied by a sha that wandered in.
# The second form, and the reason it is a SEPARATE field rather than a wider
# `fixed_by`: the sha rules are right. They are what lets `reanchor` follow a
# landing commit through the rebase inside `cutover`, and widening them to accept
# `external:butler/kg-board` would cost that for every entry to serve a few.
#
# What they carry is an unstated premise — that every entry's fix lands in THIS
# git repository — and that premise is already false. Two entries in the live
# store have a `fix_site` under `~/butler/kg-board/`, and `~/butler` deliberately
# does not use git (Syncthing since 2026-06-16). There is no sha there and there
# never will be one, so `IMP-20260808-47f7b4` sat finished, self-tested and
# unclosable: `--status fixed` alone gave `fixed-without-fixed-by`, and
# `--fixed-by external:butler/kg-board` gave `fixed-by-not-a-sha`.
#
# The shape is `acceptance_manual`'s, deliberately and exactly: when the
# machine-checkable form of a claim does not exist, the answer is not to relax
# the check but to DECLARE the exception in a field somebody can count
# (`list --fixed-elsewhere`). Free text, and the help says what it owes — where
# the fix lives and how to re-derive it — because an unauditable escape hatch is
# the loophole this field is shaped to avoid being.
TRACE_FIELDS = ("fixed_by", "fixed_elsewhere")

# A relation is not a cached status: it is the directed edge "this entry waits
# on that entry".  Whether the edge currently withholds work is derived from the
# target's live status, so there is no second `blocked` truth to drift.
RELATION_FIELDS = ("blocked_by",)

# One number, two doors. `reanchor` used to search 2000 commits from the CLI and
# 800 from a direct call, because the parser and the function signature each
# carried their own literal. That matters more here than it looks: a miss inside
# the window and a miss because the window ended are DIFFERENT answers, and this
# command reports which one it got — so the window being a different size
# depending on how you got in made the report unreadable.
DEFAULT_SEARCH_DEPTH = 2000

# Shape only. The first cut of this required at least one a-f digit, to stop
# `20260805` (a date) reading as a sha — and immediately produced a FALSE
# NEGATIVE on `339918579`, a real commit in this repo that happens to be all
# decimal. The character class cannot answer "is this a commit"; only the object
# database can, which is what commit_state is for. A date therefore lands in
# `fixed-by-unresolvable`, which is both true and actionable. Keep the guard
# dumb and let the discriminator be the thing that actually knows.
_SHA_RE = re.compile(r"^[0-9a-f]{7,40}$")

# Frontmatter anchors are intentionally narrower than arbitrary YAML.  A
# single-line sha is the only value the repair can prove; values such as
# ``frozen`` or a human label are left untouched rather than guessed.
_DOC_VERIFIED_AGAINST_RE = re.compile(
    r"^\s*verified_against:\s*([0-9a-fA-F]{7,40})\s*$", re.MULTILINE
)

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
GROOM_FIELDS = ("plan", "acceptance", "groomed_at", "groomed_by",
                "groomed_against",
                # The executable half of `acceptance`. See ACCEPTANCE_PROOF below.
                "acceptance_cmd", "acceptance_expect_rc", "acceptance_manual",
                # Optional fast feedback for a worker. This is deliberately not
                # an acceptance proof: closure still runs `acceptance_cmd`.
                "acceptance_cmd_static")

# A warning threshold, not a closure gate. The current main has moved 256 commits
# since the oldest active grooming wave, so a smaller default would turn the
# whole existing queue into noise; callers can narrow it for a deliberate audit.
GROOMED_AGAINST_MAX_COMMITS = 500

# Claiming the badge requires all of these to be non-empty. `fix_site` is in the
# list and not in GROOM_FIELDS because it predates this and is shared with the
# verdict stamp: a plan that cannot name where to change is not a plan.
GROOM_REQUIRES = ("plan", "acceptance", "fix_site")

# Exactly one of these, and the requirement is the whole point.
#
# `acceptance` is prose, and it was WRITE-ONLY: `GROOM_REQUIRES` checked it was
# non-empty and no line of code ever read it again. Measured across the 17 entries
# that were both groomed and closed, under the most generous rule anyone could
# defend (any shared 4+ character token between the acceptance and the closure
# text), at most 9 showed any overlap — and token overlap is not evidence a command
# was run, so the real mechanism count was zero. That is exactly the "reason field
# nobody reads" failure this module's own comments warn about, arrived at from the
# inside: the guard protected the badge's PRECONDITION (non-emptiness) and left its
# CONTENT unguarded.
#
#   acceptance_cmd + acceptance_expect_rc -> `anchor --commit` RUNS it before
#       writing, and refuses the whole wave if the exit code disagrees. Machine-
#       checked, so `fixed` finally means something a machine confirmed rather
#       than "a commit exists".
#   acceptance_manual -> a stated reason no command can express this. NOT a
#       loophole: it is countable (`list --acceptance-manual`) and `anchor` reports
#       how many closures in the wave rested on it, so the unverifiable set surfaces
#       at the moment of closing instead of in an audit nobody runs.
#
# Two scalar fields rather than one dict because `MUTABLE_FIELDS` ↔ argparse is a
# BIDIRECTIONAL invariant here (every field has a flag, every flag reaches a field,
# asserted by test). A dict field would need JSON in argv or a second flag that maps
# to no field, and either one breaks that.
#
# `expect_rc` is not decoration: measured on the real store, IMP-20260805-afc14b's
# acceptance is an INVERTED detector — "exit 1 = the phenomenon this entry describes
# still holds". Demanding rc 0 would grade it backwards.
ACCEPTANCE_PROOF = ("acceptance_cmd", "acceptance_manual")

# A static subset is a worker feedback loop, not a second closure criterion.
# It is intentionally bounded more tightly than the full acceptance command so
# a child cannot accidentally turn this path back into a toolchain queue.
STATIC_ACCEPTANCE_TIMEOUT_SECONDS = _backlog_acceptance.STATIC_ACCEPTANCE_TIMEOUT_SECONDS

# The declared exception for `audit-criteria`, and the third field in this module
# shaped like `acceptance_manual` / `fixed_elsewhere` for the same reason.
#
# `audit-criteria` runs an UNRESOLVED entry's own criterion and reports the green
# ones as suspects, because an entry that says the defect is still there should
# have a red criterion today. Some criteria are green by design and always will
# be: a negative assertion ("this construct no longer appears anywhere") is green
# from the moment it is written, and stays green until somebody reintroduces the
# thing. Those entries would sit in the suspect list forever, and a list with
# permanent residents is a list people stop reading.
#
# So the answer is not a cleverer classifier — no static reading of the command
# can tell a by-design green from a lying one — but a DECLARATION with a reason,
# countable via `list --acceptance-green-expected` and printed in the sweep's own
# `exempt` bucket. Free text, because the only thing that makes an exemption
# auditable is the sentence saying why.
ACCEPTANCE_GREEN_EXPECTED = "acceptance_green_expected"
AUDIT_FIELDS = (ACCEPTANCE_GREEN_EXPECTED,)


def _acceptance_deps() -> _backlog_acceptance.AcceptanceDeps:
    """Build the acceptance seam while preserving façade monkeypatch points."""
    return _backlog_acceptance.AcceptanceDeps(
        root=ROOT,
        run_streamed_command=run_streamed_command,
        check_acceptance_cmd=_check_acceptance_cmd,
        list_entries=list_entries,
        worst_first_key=_worst_first_key,
        acceptance_timeout_seconds=ACCEPTANCE_TIMEOUT_SECONDS,
        static_acceptance_timeout_seconds=STATIC_ACCEPTANCE_TIMEOUT_SECONDS,
        execute_criterion=_execute_criterion,
        trace_failed_clause=_trace_failed_clause,
        run_acceptance=_run_acceptance,
    )

# Grooming stamped on or after this date must carry one. Everything groomed before
# it stays legal — 49 entries, measured, of which 39 have an acceptance that already
# looks like a runnable command, 5 need a simulator or a device, and 5 are prose
# that no command expresses. Turning all 49 red on the day the rule lands would make
# the rule the thing to route around.
ACCEPTANCE_PROOF_SINCE = "2026-08-08"

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
    "CONTRACT-BLOCKED",
)
_DUPLICATE_VERDICT_PREFIX = "DUPLICATE-OF-"

# A groom stamp says HOW a ticket might be fixed.  A contract stamp answers the
# cheaper question that must come first: is this ticket safe to hand to a worker?
# These are scalar fields so the CLI, JSON store and show/update reachability
# invariants remain the same as the rest of the lifecycle.
CONTRACT_STATUSES = ("ready", "blocked")
CONTRACT_BASELINES = ("red", "no-op", "unknown")
CONTRACT_FIELDS = (
    "contract_status", "contract_baseline", "contract_checked_at",
    "contract_checked_by", "contract_evidence",
)
# Existing queue data is grandfathered; every new grooming act must carry the
# contract stamp so stale rows do not turn this guard into a repository-wide
# outage on the day it lands.
CONTRACT_REQUIRED_SINCE = "2026-08-10"

# An entry id must be usable as a bare filename. Unvalidated, `--date 2026/08/05`
# writes <store>/IMP-2026/08/05-<hash>.json — a real subdirectory that
# store.glob("*.json") never sees, so `list` and `validate` both report an empty,
# healthy store while the entry sits on disk. `--id ../escaped` writes outside
# the store entirely. Both returned rc=0 before this guard.
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_LEGACY_ENTRY_ID_RE = re.compile(r"^IMP-\d{4}$")
_MODERN_ENTRY_ID_RE = re.compile(r"^(?:APP|IMP)-\d{8}-[0-9a-f]{6}$")


class BacklogError(Exception):
    """Raised for usage errors that should exit 64 rather than traceback."""


class EntryNotFound(BacklogError, KeyError):
    """A store lookup for an id that is not there.

    Its own type, rather than the bare `KeyError` this used to be, so `main` can
    answer it once for every subcommand. Only `show` and `update` had remembered
    to catch it locally; `verify` had not, and a per-command handler is a rule
    that every future command has to be told about.

    It must NOT be as wide as `except KeyError` around a command body: that
    would also swallow a genuine dict-lookup bug inside the command and report
    it as "no such entry" — a defect dressed as a tidy message.

    The two bases each do one job:
      - KeyError, because three tests and `import_legacy`'s carry-forward path
        already read it that way and none of them wanted this rename. (`render`
        has no such handler — it does not call `load_entry` at all.)
      - BacklogError, which is NOT what routes it today — `main` catches this
        type by name, ahead of the BacklogError clause, to answer 1 instead of
        64. It is the fallback: delete that specific clause and the refusal
        still arrives as a refusal rather than a traceback.
    """

    def __str__(self) -> str:  # KeyError's own would repr the id and name nothing
        # `main` renders this into an f-string on the ERROR path. A __str__ that
        # can raise there turns a refusal into a traceback from inside the
        # traceback-avoidance machinery, so it must not index args blindly.
        return f"no such entry: {self.args[0] if self.args else '<unknown>'}"


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

# Migration-only provenance for a dated historical id whose original digest
# predates the current content-derived-id contract.  Storing the digest of the
# imported payload makes the exception exact: validation can distinguish the
# historical pair from a later edit trying to reuse the same id.
HISTORICAL_ID_DIGEST = "historical_id_digest"
IDENTITY_AUDIT_FIELDS = (HISTORICAL_ID_DIGEST,)


def _matches_imported_historical_identity(
    *, entry_id: object, stream: object, date: object
) -> bool:
    """Whether a dated id could have come from the legacy IMP importer.

    The legacy 8-column parser deliberately skips APP rows.  Its only dated
    ids therefore have the modern IMP shape and repeat the row's stream/date;
    accepting anything wider would turn ``historical=True`` into an arbitrary
    identity bypass rather than a migration exception.
    """
    return (
        isinstance(entry_id, str)
        and isinstance(date, str)
        and stream == "IMP"
        and _MODERN_ENTRY_ID_RE.fullmatch(entry_id) is not None
        and entry_id.startswith(f"IMP-{date.replace('-', '')}-")
    )


def entry_path(store: Path, entry_id: str) -> Path:
    return _backlog_store.entry_path(store, entry_id)


# ---------------------------------------------------------------------------
# serialisation
# ---------------------------------------------------------------------------

def _dumps(payload: dict) -> str:
    return _backlog_store.dumps(payload)


@contextlib.contextmanager
def _view_lock():
    """Serialize the whole read-store → render → write-view cycle.

    Entry files are disjoint paths, so filing is concurrency-safe by construction.
    The generated view is not: every mutation now refreshes it, and that refresh is
    a read-modify-write of ONE shared file. Measured with the window widened on
    purpose (a 3s gap between the render and the write, so a process that read
    early writes late):

      * two concurrent `update --commit` on DIFFERENT entries — both entry files
        end up correct, and the view keeps the slow writer's snapshot: the fast
        writer's change is simply gone. `render --check` then exits 1, so the loss
        is caught, but by whoever runs the docs gate next rather than by whoever
        caused it. That is precisely the shape this module keeps filing entries
        about.
      * concurrent `add` did NOT lose rows (17/17, 32/32, 64/64) — but only because
        the entry-loss guard refuses a write that would delete ids. That guard
        watches the id SET, and an `update` does not change the id set, so it is
        structurally blind to the case above. Passing one test and failing the
        other from the same race is the tell.

    An advisory flock on a sidecar under `.cache/` (gitignored; NOT beside the view,
    where an untracked `*.md.lock` would show up in `git status` and could be swept
    into someone's commit). The kernel drops it when the fd closes, so a crashed
    holder leaves nothing behind. Never fatal: a lock we cannot take is not a reason
    to fail a mutation that has already landed, so the refresh proceeds unlocked
    rather than not at all — the pre-existing behaviour, no worse than before.
    """
    with _backlog_store.view_lock(ROOT) as acquired:
        if not acquired:
            print("backlog: view lock unavailable; refreshing unserialized", file=sys.stderr)
        yield


def _write_atomic(path: Path, text: str) -> None:
    """Write via a temp file + os.replace so a crash cannot publish a partial
    entry. Callers rely on this: a truncated JSON entry would make the whole
    store unreadable to `render`, and the failure would surface far from the
    write that caused it.

    The temp name is UNIQUE per call, not the fixed `.{name}.tmp` it used to be.
    A fixed name is only safe while nothing writes the same path twice at once,
    and that stopped being true the moment mutations began refreshing the view:
    two concurrent writers raced, the first `os.replace` moved the shared temp
    away, and the second died on `FileNotFoundError` — a crash inside the helper
    whose entire job is to make writing not crash."""
    _backlog_store.write_atomic(path, text)


@contextlib.contextmanager
def _entry_lock(path: Path):
    """Serialize one entry mutation with every writer for its store.

    Atomic replacement prevents partial JSON; it does not make the preceding
    exists/read/compare decision atomic.  Two agents filing the same observation in
    one checkout therefore need one critical section if ``written`` is to describe
    this invocation rather than an earlier snapshot.  Supersede adds a second
    destination and must serialize with ordinary add/update/verify/anchor writers,
    so the lock order is store then entry.  The sidecars belong in the gitignored
    worktree cache, keyed by the absolute store/path, so they never become backlog
    data.  Same-thread re-entry skips duplicate file descriptors; other threads
    still wait on the OS-level entry lock.
    """
    path = Path(path)
    key = path.resolve()
    held = getattr(_ENTRY_LOCK_STATE, "held", None)
    if held is None:
        held = {}
        _ENTRY_LOCK_STATE.held = held
    depth = held.get(key, 0)
    if depth:
        held[key] = depth + 1
        try:
            with _store_lock(path.parent):
                yield
        finally:
            if depth == 1:
                held.pop(key, None)
            else:
                held[key] = depth
        return

    try:
        with _store_lock(path.parent):
            with _backlog_store.entry_lock(ROOT, path):
                held[key] = 1
                try:
                    yield
                finally:
                    held.pop(key, None)
    except _backlog_store.EntryLockUnavailable as exc:
        raise BacklogError(f"{exc}; nothing was written") from exc


@contextlib.contextmanager
def _entry_acceptance_lock(path: Path):
    """Lock one entry while acceptance runs without freezing the whole store.

    A closure criterion is arbitrary shell code and may itself exercise backlog
    tooling. Holding ``_store_lock`` while running it deadlocks as soon as the
    criterion takes the normal store lock (campaign admission exposed this exact
    cycle). The final mutation still re-enters ``_entry_lock`` after acceptance;
    this narrower lock prevents a competing writer from changing the same entry
    during the probe without serialising unrelated entries.
    """
    path = Path(path)
    try:
        with _backlog_store.entry_lock(ROOT, path):
            yield
    except _backlog_store.EntryLockUnavailable as exc:
        raise BacklogError(f"{exc}; nothing was written") from exc


@contextlib.contextmanager
def _store_lock(store: Path):
    """Serialize a multi-entry read-modify-write transaction for one store.

    The ordinary entry lock is deliberately keyed to one destination path, which
    is enough for ``add`` and ``update``.  ``supersede`` publishes a replacement
    and retires its source, so two entry locks would still leave a window where a
    second caller can observe or create only half of the transition.  The lock
    lives under the worktree cache rather than beside the tracked store.
    """
    store = Path(store).resolve()
    held = getattr(_STORE_LOCK_STATE, "held", None)
    if held is None:
        held = {}
        _STORE_LOCK_STATE.held = held
    depth = held.get(store, 0)
    if depth:
        held[store] = depth + 1
        try:
            yield
        finally:
            if depth == 1:
                held.pop(store, None)
            else:
                held[store] = depth
        return

    key = hashlib.sha256(str(store).encode("utf-8")).hexdigest()
    lock_path = ROOT / ".cache" / "backlog_store_locks" / f"{key}.lock"
    try:
        with exclusive_lock(lock_path, label=f"backlog-store:{store}"):
            held[store] = 1
            try:
                yield
            finally:
                held.pop(store, None)
    except LockUnavailable as exc:
        raise BacklogError(f"store lock unavailable for {store}: {exc}") from exc


def _claim_ledger_path() -> Path:
    """Return the canonical per-machine worktree claim ledger path."""
    return _queue_anchor() / ".cache" / "worktree_registry.json"


@contextlib.contextmanager
def _claim_lock():
    """Serialize a claim snapshot with the registry's ledger writers."""
    ledger = _claim_ledger_path().resolve()
    lock_path = ledger.with_name(ledger.name + ".lock")
    try:
        with exclusive_lock(lock_path, label=f"worktree-ledger:{ledger.name}"):
            yield
    except LockUnavailable as exc:
        raise BacklogError(f"claim ledger lock unavailable for {ledger}: {exc}") from exc


@contextlib.contextmanager
def _supersede_locks(store: Path):
    """Hold store and claim locks in the one order shared by all writers."""
    with _store_lock(store):
        with _claim_lock():
            yield


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
    status = payload.get("status")
    if status in RETIRED_STATUSES:
        # Named separately from `bad-status`, because "you used a value that never
        # existed" and "you used a value that was retired, and here is what replaced
        # it" are different problems with different fixes. A generic bad-status here
        # would send the reader hunting for a typo.
        problems.append({"kind": "retired-status", "value": status,
                         "use_instead": RETIRED_STATUSES[status],
                         "why": "who is working on this is derived from the worktree "
                                "claim ledger now — a stored copy drifts"})
    elif status not in STATUSES:
        problems.append({"kind": "bad-status", "value": status})

    contract_status = payload.get("contract_status")
    if contract_status is not None and contract_status not in CONTRACT_STATUSES:
        problems.append({"kind": "bad-contract-status", "value": contract_status})
    contract_baseline = payload.get("contract_baseline")
    if contract_baseline is not None and contract_baseline not in CONTRACT_BASELINES:
        problems.append({"kind": "bad-contract-baseline", "value": contract_baseline})
    contract_present = [field for field in CONTRACT_FIELDS
                        if payload.get(field) is not None]
    if contract_present and len(contract_present) != len(CONTRACT_FIELDS):
        problems.append({"kind": "incomplete-contract-evidence",
                         "present": contract_present,
                         "missing": [f for f in CONTRACT_FIELDS if f not in contract_present]})

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

    # DOUBLE-sided, exactly like _check_groom: any part of the verification stamp
    # appearing obliges the date. The first cut triggered on `verdict` alone, and
    # a lone `--verified-at n/a` then walked through every net at once — validate
    # passed it (no verdict), `--unverified` skipped it (field non-empty), and
    # `--stale` skipped it (unparseable date). One flag removed an entry from the
    # whole mechanism. That is the shape this rule exists to close, arriving from
    # the other direction: not forgetting to fill it, filling half of it.
    if (verdict or payload.get("verified_at") or payload.get("verified_by")
            or payload.get("verified_evidence")) \
            and not _real_date(payload.get("verified_at")):
        problems.append({"kind": "verdict-without-date",
                         "value": payload.get("verified_at")})

    return problems


def _check_status_obligations(payload: dict) -> list[dict]:
    """What a status owes that needs NEITHER a sha NOR a repository to check.

    Split out of `_check_traceability`, and the split is the whole fix for
    IMP-20260808-f2bcc1. These three rules lived inside that function, mentioning
    no commit and needing no object database, so every caller that turned
    traceability off to forgive the SHA rules turned them off too — collateral,
    not intent. `_cmd_stage`'s own comment says so in as many words ("the
    exclusion is WIDER than the one rule that forces it").

    The measured cost of that: `add --status triaged` wrote entries `validate`
    immediately rejects, five of them in one session, and the thing that reported
    it was the cutover gate of a LATER, unrelated branch.

    Which statuses owe what:

      * `open` claims nothing but "filed". It is an honest state and owes
        nothing — requiring a plan there would have turned 40 entries red the day
        it landed, and the only way to clear those is to invent plans for work
        nobody has triaged.
      * `triaged` claims someone looked and decided, so it owes a next action.
      * `wont-fix` claims a decision, which is a reason, not a hash.
      * `fixed` owes traceability, which is the other function's subject.
    """
    problems: list[dict] = []
    status = payload.get("status")

    if status == "triaged" and not _next_action(payload):
        problems.append({"kind": "no-next-action", "status": status})

    if status == "contract-blocked":
        if payload.get("contract_status") != "blocked":
            problems.append({"kind": "contract-blocked-without-contract-status"})
        if not str(payload.get("contract_evidence") or "").strip():
            problems.append({"kind": "contract-blocked-without-evidence"})

    if status == "wont-fix":
        reason = str(payload.get("resolution") or "").strip()
        if not reason:
            problems.append({"kind": "wont-fix-without-reason"})
        elif _SHA_RE.match(reason):
            # A decision not to fix is an argument. A bare hash is the shape of
            # an entry that was closed by reflex.
            problems.append({"kind": "wont-fix-reason-is-a-sha", "value": reason})

    return problems


def _check_traceability(payload: dict, commit_state) -> list[dict]:
    """Hold a CLOSED entry to the audit trail it claims.

    `fixed` claims the defect is gone. That claim is only auditable if it names
    where the fix landed, and there are exactly two forms it can take — see
    TRACE_FIELDS:

      * `fixed_by`, a list of commits in THIS repo, each of which must still be
        reachable. Machine-followable: `reanchor` re-points them after a rebase.
      * `fixed_elsewhere`, free text, for a fix that landed somewhere with no
        shas at all. Not machine-followable, which is why it is COUNTABLE
        instead (`list --fixed-elsewhere`).

    Exactly one. Neither is a closure with no audit trail; both is two
    contradictory claims about the same fix, and the reader has no way to tell
    which one the closer meant — the same defect
    `groom-claim-with-conflicting-acceptance-proof` names one field family over.

    Everything that does NOT need a sha or a repo is in
    `_check_status_obligations`, because callers switch this function off to
    forgive the sha rules and used to lose those by accident.

    `commit_state` is injected so this stays a pure function of its inputs: the
    unit tests must not need a git repo, and the one caller that does have one
    builds the real resolver once and caches it.
    """
    problems: list[dict] = []
    status = payload.get("status")
    fixed_by = payload.get("fixed_by") or []
    elsewhere = str(payload.get("fixed_elsewhere") or "").strip()

    if not isinstance(fixed_by, list) or any(not isinstance(s, str) for s in fixed_by):
        return [{"kind": "fixed-by-not-a-list", "value": fixed_by}]

    if status in ("fixed", "wont-fix"):
        # `wont-fix` used to fall through both branches, so flipping the status
        # made a broken sha vanish from the verdict — a repair anyone hunting a
        # green gate would find, and the sha is no less broken for it. Only the
        # REQUIREMENT to carry one is specific to `fixed`; validating the ones
        # actually present is not.
        if status == "fixed" and not fixed_by and not elsewhere:
            # Kind name kept as-is although two fields now satisfy it: it is
            # referenced by `_merged_and_validated`'s repair hint and by tests,
            # and renaming a refusal to widen it is how a hint stops firing. What
            # it accepts is carried in the problem itself, so `--json` says so.
            problems.append({"kind": "fixed-without-fixed-by",
                             "accepted": list(TRACE_FIELDS)})
        elif status == "fixed" and fixed_by and elsewhere:
            problems.append({"kind": "fixed-with-conflicting-traceability",
                             "present": list(TRACE_FIELDS)})
        # The sha rules apply to shas. An entry that DECLARES its fix has none is
        # not exempt from scrutiny — it is scrutinised by being countable — and
        # running them anyway on the conflicting case would bury the conflict
        # under complaints about the field that should not be there.
        #
        # `and status == "fixed"` is load-bearing, not defensive. The two
        # exactly-one-of rules above are gated on `fixed`, so without it a
        # `wont-fix` carrying BOTH a broken sha and this field got neither finding:
        # no conflict (wrong status) and no sha check (skipped) — validated clean.
        # Reachable from the CLI in one call on any entry with an orphaned sha,
        # which is the state `reanchor` exists for. That is the same
        # flip-the-status-and-the-broken-sha-disappears defect the comment eight
        # lines up records having already paid for once, re-entered through the new
        # field. Skipping is a property of the CLOSURE this field describes, and
        # only `fixed` is that closure.
        for sha in ([] if (elsewhere and status == "fixed") else fixed_by):
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
            elif state == "ambiguous":
                problems.append({"kind": "fixed-by-ambiguous-prefix", "sha": sha})
            elif state == "wrong-type":
                problems.append({"kind": "fixed-by-not-a-commit-object", "sha": sha})
            elif state == "not-a-sha":
                problems.append({"kind": "fixed-by-not-a-sha", "sha": sha})
            elif state == "unknown":
                # No object anywhere. IMP-0005 carried `813356b1`, which exists
                # in no odb — not an orphan, a hash somebody wrote down wrong.
                # Telling that reader to run `reanchor` sends them hunting a
                # rebase that never happened.
                problems.append({"kind": "fixed-by-unresolvable", "sha": sha})
    elif status in ("open", "triaged", "contract-blocked"):
        if fixed_by:
            # An unfinished entry pointing at a landing commit is the status
            # lying about itself, and it is the shape that lets closed work look
            # open forever.
            problems.append({"kind": "fixed-by-on-unfinished-entry", "shas": fixed_by})
        if elsewhere:
            # Same defect through the new door. Without this the second form
            # would be a way to write "this is fixed" while the status keeps
            # saying it is not, which is precisely what the rule above refuses.
            problems.append({"kind": "fixed-elsewhere-on-unfinished-entry",
                             "value": elsewhere})

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
    groomed_against = str(payload.get("groomed_against") or "").strip()
    problems: list[dict] = []
    if groomed_against and not _SHA_RE.fullmatch(groomed_against):
        problems.append({"kind": "groom-claim-bad-against",
                         "value": payload.get("groomed_against")})

    if not (payload.get("groomed_by") or payload.get("groomed_at")):
        return problems  # not claimed — nothing to hold it to

    for field in GROOM_REQUIRES:
        if not str(payload.get(field, "")).strip():
            problems.append({"kind": f"groom-claim-without-{field}", "field": field})
    if not str(payload.get("groomed_by", "")).strip():
        # Anonymous grooming cannot be audited or re-run; naming the mechanism
        # is what lets a later reader judge how much the badge is worth.
        problems.append({"kind": "groom-claim-without-groomer"})
    if not _real_date(payload.get("groomed_at")):
        # Without a date the explicit `list --ungroomed --groom-stale-days N`
        # audit cannot classify the badge; ordinary `--ungroomed` remains a
        # deliberate, non-expiring queue rather than silently changing policy.
        problems.append({"kind": "groom-claim-bad-date", "value": payload.get("groomed_at")})

    # Exactly one proof of acceptance — see ACCEPTANCE_PROOF.
    #
    # Grandfathered by DATE rather than by a baseline file of ids, and the choice is
    # load-bearing: `groomed_at` is written at groom time, so re-grooming an old
    # entry stamps today's date and the rule binds it. An id baseline would forgive
    # that entry forever, which is the opposite of what a ratchet is for. It also
    # needs no second file to keep in step with the store.
    proofs = [f for f in ACCEPTANCE_PROOF if str(payload.get(f, "")).strip()]
    groomed_at = str(payload.get("groomed_at", ""))
    binds = _DATE_RE.match(groomed_at) and groomed_at >= ACCEPTANCE_PROOF_SINCE
    if not proofs and binds:
        problems.append({"kind": "groom-claim-without-acceptance-proof",
                         "expected": list(ACCEPTANCE_PROOF),
                         "since": ACCEPTANCE_PROOF_SINCE})
    elif len(proofs) > 1:
        # Both is not "extra safe", it is two different claims about the same
        # question: one says a machine settles this, the other says nothing can.
        # Unlike the missing-proof branch above, this is an internal contradiction,
        # not a new obligation, so it has no date cutoff. Existing data contains no
        # such pair; retaining the unconditional rule preserves that distinction.
        problems.append({"kind": "groom-claim-with-conflicting-acceptance-proof",
                         "present": proofs,
                         "expected": list(ACCEPTANCE_PROOF),
                         "since": None})

    # Grooming now means "worked out AND explained". The badge already required
    # the work (GROOM_REQUIRES); these require it to be sayable to the person who
    # decides whether it happens first, and that is a genuinely different artifact
    # — `plan` is addressed to a small model, `brief` to someone holding a phone.
    #
    # NOT added to GROOM_REQUIRES, deliberately: that list has no grandfather
    # clause, so all 133 already-groomed entries lacking them would go red the
    # moment this landed, and a rule that reds the store on arrival is a rule
    # people route around rather than satisfy.
    #
    # Ratcheted by DATE for the reason ACCEPTANCE_PROOF_SINCE gives — `groomed_at`
    # is stamped at groom time, so re-grooming an old entry writes today's date and
    # the rule binds it with no list to maintain, whereas an id whitelist would
    # forgive that entry forever.
    #
    # BRIEF_REQUIRED_SINCE is deliberately NOT the day this landed, and that is a
    # measurement rather than a preference: the 2026-08-08 grooming wave had
    # already stamped 96 entries by the time this rule was written, so `>= today`
    # would have turned 95 of them red (all but this ticket, whose prose this
    # very commit writes) and taken `validate` — this feature's own
    # acceptance command — down with them. The rule therefore starts one day ahead
    # of the newest stamp in the store. The cost is one day in which grooming can
    # still be filed without plain language; the alternative was exempting that
    # wave by id, which is the whitelist this design exists to avoid.
    # `test_the_cutoff_forgives_every_groom_stamp_already_in_the_shipped_store`
    # asserts the relationship instead of trusting this paragraph.
    #
    # The debt this leaves is not invisible: `list --missing-brief` counts an
    # absent brief OR a Scope that is still legacy prose/otherwise unknown.
    if _DATE_RE.match(groomed_at) and groomed_at >= BRIEF_REQUIRED_SINCE:
        if not str(payload.get("brief", "")).strip():
            problems.append({"kind": "groom-claim-without-brief", "field": "brief",
                             "since": BRIEF_REQUIRED_SINCE})
    if _DATE_RE.match(groomed_at) and groomed_at >= SCOPE_REQUIRED_SINCE:
        if scope_status(payload.get("scope")) != "known":
            problems.append({"kind": "groom-claim-without-scope", "field": "scope",
                             "since": SCOPE_REQUIRED_SINCE})

    problems.extend(_check_acceptance_cmd(payload))
    return problems


def _check_groom_write(changes: dict, updated: dict) -> list[dict]:
    """Plain language is required whenever the badge is STAMPED, date irrelevant.

    The date ratchets in `_check_groom` grandfather DATA — the shipped store
    contains groomed entries with a missing brief and legacy Scope, and reddening
    them would make the rule the thing to route around. But they cannot grandfather
    ACTS: a new groom write must carry both a human brief and a structured Scope,
    even if `--groomed-at <old date>` is supplied.

    So the two questions are separated by WHERE they are asked. `validate` judges
    stored data and forgives what predates the rule; this runs at the moment
    someone claims or refreshes the badge, which is happening now and is held to
    today's standard.

    Keyed on the CHANGE SET, not on the merged entry, and that is the whole
    correctness argument: 133 stored entries are groomed and have no plain
    language, so a gate reading `updated` alone would freeze every edit to them —
    `--status`, `--resolution`, `verify`, `anchor` — none of which are grooming.
    Only stamping the badge trips this.
    """
    # `is not None`, matching the merge loop three lines above in
    # `_merged_and_validated` rather than testing key presence. They disagreed:
    # `update_entry(id, severity="high", groomed_at=None)` is skipped by the merge
    # and writes no groom stamp, but presence-keying still refused it. Unreachable
    # from the CLI today (`_cmd_update` filters None first) — and "two callers
    # disagreed about what counts as a change" is the exact defect the enclosing
    # function's docstring exists to record.
    if not any(changes.get(field) is not None
               for field in ("groomed_at", "groomed_by")):
        return []
    problems = []
    if not str(updated.get("brief", "")).strip():
        problems.append({"kind": "groom-claim-without-brief", "field": "brief", "at": "write"})
    if scope_status(updated.get("scope")) != "known":
        scope_kind = (
            "groom-claim-without-scope"
            if not str(updated.get("scope", "")).strip()
            else "groom-claim-with-unknown-scope"
        )
        problems.append({"kind": scope_kind, "field": "scope", "at": "write"})
    return problems


def _check_acceptance_cmd(payload: dict) -> list[dict]:
    """Shape of the executable acceptance. Checked wherever it appears, groomed or not.

    `expect_rc` is validated even when it is the default, because `anchor` compares
    against it and a string `"0"` from a hand-edited entry would never equal the int
    the subprocess returns — a mismatch that would refuse every wave carrying that
    entry, blaming the fix rather than the field.
    """
    problems: list[dict] = []
    cmd = payload.get("acceptance_cmd")
    static_cmd = payload.get("acceptance_cmd_static")
    rc = payload.get("acceptance_expect_rc")

    if str(cmd or "").strip():
        # An unparseable command is not a criterion. Stored without this check, it
        # runs at anchor time and exits 2 — which reads as "the defect is back" and
        # sends whoever is closing the entry to debug the FIX. Measured twice while
        # transcribing agent output into the store: a dropped closing quote and a
        # mangled `&&` both landed silently and only surfaced when the whole batch
        # was re-run and reconciled against the numbers the agents had reported.
        #
        # `bash -n` parses without executing, so this is free and side-effect-free.
        # It is a SYNTAX floor, not a semantic one: it cannot tell whether the
        # command measures the right thing, only that a shell can read it.
        try:
            probe = subprocess.run(["bash", "-n", "-c", str(cmd)],
                                   capture_output=True, text=True, timeout=15)
            if probe.returncode != 0:
                problems.append({"kind": "acceptance-cmd-does-not-parse",
                                 "detail": probe.stderr.strip()[:300]})
        except (OSError, subprocess.SubprocessError):
            # No bash, or it would not run. Do NOT invent a verdict from that —
            # a guard that turns "could not check" into "clean" is the shape this
            # module keeps filing entries about.
            problems.append({"kind": "acceptance-cmd-unparsed",
                             "detail": "bash unavailable; syntax not checked"})
    # No "blank cmd" rule. The first cut had one, distinguishing `None` from `""` —
    # a distinction this schema does not make ANYWHERE (`plan`, `acceptance`,
    # `fix_site` all use `""` for absent, and `update` clears a field by writing
    # `""`). It fired on every legitimately cleared field. "You claimed grooming
    # without a proof" is the real failure and `_check_groom` already owns it.
    if rc is not None:
        if isinstance(rc, bool) or not isinstance(rc, int):
            # `bool` is an `int` in Python and `True == 1`, so a JSON `true` would
            # silently mean "expect exit 1". Rejected by name rather than coerced.
            problems.append({"kind": "acceptance-expect-rc-not-an-int", "value": rc})
        elif not 0 <= rc <= 255:
            problems.append({"kind": "acceptance-expect-rc-out-of-range", "value": rc})
    if rc is not None and not str(cmd or "").strip():
        # An expectation with nothing to expect it of. Nothing would ever read it.
        problems.append({"kind": "acceptance-expect-rc-without-cmd", "value": rc})
    if str(static_cmd or "").strip():
        # A static subset without a full criterion would be a second proof with
        # no closure counterpart. Keep the field useful for workers while making
        # it impossible to accidentally turn it into a weaker fixed gate.
        if not str(cmd or "").strip():
            problems.append({"kind": "acceptance-static-without-cmd"})
        try:
            probe = subprocess.run(["bash", "-n", "-c", str(static_cmd)],
                                   capture_output=True, text=True, timeout=15)
            if probe.returncode != 0:
                problems.append({"kind": "acceptance-static-cmd-does-not-parse",
                                 "detail": probe.stderr.strip()[:300]})
        except (OSError, subprocess.SubprocessError):
            problems.append({"kind": "acceptance-static-cmd-unparsed",
                             "detail": "bash unavailable; syntax not checked"})
    if str(payload.get(ACCEPTANCE_GREEN_EXPECTED) or "").strip() \
            and not str(cmd or "").strip():
        # Same defect as the rule above, one field over: an exemption from running
        # a command exempts nothing when there is no command. It would sit in the
        # store looking like a considered decision and be read by nobody —
        # `audit-criteria` never reaches an entry with no `acceptance_cmd`, so the
        # bucket it claims a place in cannot contain it.
        #
        # Reached from `_check_groom`, i.e. on entries carrying a groom badge —
        # which is exactly `audit-criteria`'s population, so the rule binds
        # wherever the field can do anything at all.
        problems.append({"kind": "acceptance-green-expected-without-cmd"})
    return problems


def _contract_site_paths(fix_site: str) -> list[str]:
    return _backlog_contract.site_paths(fix_site)


def _contract_command_paths(command: str) -> list[str]:
    return _backlog_contract.command_paths(command)


def contract_preflight(payload: dict, *, repo: Path | None = None) -> list[dict]:
    return _backlog_contract.preflight(
        payload,
        repo=repo,
        default_root=ROOT,
        required_since=CONTRACT_REQUIRED_SINCE,
        contract_fields=CONTRACT_FIELDS,
        contract_statuses=CONTRACT_STATUSES,
        contract_baselines=CONTRACT_BASELINES,
    )


SELECTOR_PROBE_TIMEOUT_SECONDS = 60


def _pytest_selector_probe(cmd: str) -> list[str] | None:
    return _backlog_contract.pytest_selector_probe(cmd)


def _pytest_collected_count(output: str) -> int | None:
    return _backlog_contract.pytest_collected_count(output)


def _report_pytest_selector_count(entry_id: str, cmd: str) -> None:
    _backlog_contract.report_pytest_selector_count(
        entry_id,
        cmd,
        runner=run_streamed_command,
        root=ROOT,
        timeout_seconds=SELECTOR_PROBE_TIMEOUT_SECONDS,
        selector_probe=_pytest_selector_probe,
        count_parser=_pytest_collected_count,
    )


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

    payload_id = payload.get("id")
    digest_inputs = DIGEST_FIELDS
    if isinstance(payload_id, str) and not _LEGACY_ENTRY_ID_RE.fullmatch(payload_id) \
            and all(isinstance(payload.get(field), str) for field in digest_inputs):
        expected_id = make_entry_id(**{
            field: payload[field] for field in DIGEST_FIELDS
        })
        historical_digest = payload.get(HISTORICAL_ID_DIGEST)
        historical_identity_matches = _matches_imported_historical_identity(
            entry_id=payload_id,
            stream=payload.get("stream"),
            date=payload.get("date"),
        )
        if payload_id != expected_id and (
            historical_digest != expected_id or not historical_identity_matches
        ):
            problems.append({
                "kind": "id-content-drift",
                "id": payload_id,
                "expected_id": expected_id,
            })
        elif payload_id == expected_id and historical_digest is not None:
            problems.append({
                "kind": "stale-historical-id-digest",
                "id": payload_id,
                "historical_id_digest": historical_digest,
            })
    elif payload.get(HISTORICAL_ID_DIGEST) is not None:
        problems.append({
            "kind": "stale-historical-id-digest",
            "id": payload_id,
            "historical_id_digest": payload.get(HISTORICAL_ID_DIGEST),
        })

    problems.extend(_check_vocabulary(payload))

    if payload.get("stream") == "IMP":
        for field in APP_ONLY_FIELDS:
            # Presence, not truthiness: `update --surface ""` used to slip an
            # empty APP-only key onto an IMP entry and still validate clean,
            # because "" is falsy. `add` never produces that shape (it skips
            # empty values), so nothing in the store relies on the looser test.
            if field in payload:
                problems.append({"kind": "app-field-on-imp-entry", "field": field})

    problems.extend(scope_problems(payload.get("scope")))
    problems.extend(_check_groom(payload))
    # UNCONDITIONAL, and that is the fix for IMP-20260808-f2bcc1. `check_traceability`
    # exists to forgive rules that need a repository; these need none, and riding
    # along inside that switch is how `add --status triaged` came to write entries
    # `validate` rejects. Measured before turning it on: 0 of the 141 rows in the
    # frozen 8-column fixture and 0 of the live entries are affected, so the ratchet
    # lands green rather than reddening the store on arrival.
    problems.extend(_check_status_obligations(payload))
    if check_traceability:
        problems.extend(_check_traceability(payload, commit_state))

    return problems


def _blocking_ids(payload: dict) -> list[str]:
    """Return a well-shaped blocking edge list; malformed values validate red."""
    value = payload.get("blocked_by")
    if value is None:
        return []
    return value if isinstance(value, list) else []


def _check_blocking_graph(payloads: list[tuple[str, dict]]) -> list[dict]:
    """Validate cross-entry blocking edges without treating legal edges as errors."""
    ids = {payload.get("id") for _, payload in payloads}
    paths = {payload.get("id"): path for path, payload in payloads}
    graph: dict[str, list[str]] = {}
    problems: list[dict] = []

    for path, payload in payloads:
        entry_id = payload.get("id")
        value = payload.get("blocked_by")
        if value is not None and (
            not isinstance(value, list)
            or any(not isinstance(blocker, str) for blocker in value)
        ):
            problems.append({"kind": "blocked-by-invalid", "id": entry_id,
                             "path": path})
            graph[entry_id] = []
            continue
        blockers = list(dict.fromkeys(value or []))
        graph[entry_id] = blockers
        for blocker in blockers:
            if blocker == entry_id:
                problems.append({"kind": "blocked-by-self", "id": entry_id,
                                 "blocked_by": blocker, "path": path})
            elif blocker not in ids:
                problems.append({"kind": "blocked-by-unknown-id", "id": entry_id,
                                 "blocked_by": blocker, "path": path})

    # DFS only over known, non-self edges. Report each cycle once even though a
    # cycle is encountered from every node in it.
    state: dict[str, int] = {}
    reported: set[tuple[str, ...]] = set()

    def visit(node: str, stack: list[str]) -> None:
        state[node] = 1
        stack.append(node)
        for blocker in graph.get(node, []):
            if blocker not in graph or blocker == node:
                continue
            if state.get(blocker, 0) == 1:
                cycle = stack[stack.index(blocker):] + [blocker]
                key = tuple(sorted(set(cycle)))
                if key not in reported:
                    reported.add(key)
                    problems.append({"kind": "blocked-by-cycle", "id": node,
                                     "cycle": cycle, "path": paths.get(node)})
            elif state.get(blocker, 0) == 0:
                visit(blocker, stack)
        stack.pop()
        state[node] = 2

    for entry_id in graph:
        if state.get(entry_id, 0) == 0:
            visit(entry_id, [])
    return problems


def _git(*args: str, repo: Path | None = None) -> subprocess.CompletedProcess:
    # The repo is a PARAMETER, defaulting to ROOT — never the caller's cwd. The
    # shas in this ledger name commits in the checkout the ledger lives in, and
    # no other repo can answer for them. Inheriting cwd made one command
    # fail-open outside a repo and false-red inside a foreign one; it was also
    # the only way tests could aim the resolver at a fixture repo, which is why
    # the fix is an argument rather than a hard-coded ROOT.
    return subprocess.run(["git", *args], cwd=repo or GIT_REPO, capture_output=True, text=True)


def _main_commit(repo: Path | None = None) -> str | None:
    """Return the checkout's local main tip, or None when no such ref exists."""
    result = _git("rev-parse", "--verify", "--quiet", "main^{commit}", repo=repo)
    sha = result.stdout.strip()
    return sha if result.returncode == 0 and _SHA_RE.fullmatch(sha) else None


def _groomed_against_warning(
    entry: dict, *, max_commits: int = GROOMED_AGAINST_MAX_COMMITS,
    repo: Path | None = None, main_sha: str | None = None,
) -> dict | None:
    """Describe a grooming snapshot that is materially behind local main.

    This deliberately reports only a measurable ancestry distance. An absent or
    unresolvable base is grandfathered/silent: the warning is a prompt to re-check
    prose, not a second validation gate that would manufacture a new queue.
    """
    against = str(entry.get("groomed_against") or "").strip()
    if not against or not _SHA_RE.fullmatch(against):
        return None
    main_sha = main_sha or _main_commit(repo)
    if main_sha is None:
        return None
    result = _git("rev-list", "--count", f"{against}..{main_sha}", repo=repo)
    if result.returncode != 0:
        return None
    try:
        commits_behind = int(result.stdout.strip())
    except ValueError:
        return None
    if commits_behind <= max_commits:
        return None
    return {
        "id": entry.get("id"),
        "groomed_against": against,
        "commits_behind": commits_behind,
        "threshold": max_commits,
    }


def _groomed_against_warnings(
    entries: list[dict], *, max_commits: int = GROOMED_AGAINST_MAX_COMMITS,
    repo: Path | None = None,
) -> list[dict]:
    main_sha = _main_commit(repo)
    if main_sha is None:
        return []
    return [warning for entry in entries
            if (warning := _groomed_against_warning(
                entry, max_commits=max_commits, repo=repo, main_sha=main_sha))]


def make_commit_state(repo: Path | None = None):
    """Resolve a fixed-by value to its object identity, or None outside a repo.

    `ok` means reachable from HEAD **or** from `main`. Neither alone works:

      * HEAD alone is right at gate time — the fix is committed on the worktree
        branch and has not been cut over — but stops meaning anything after.
      * `main` alone rejects that same legitimate sha on every cutover, and a
        gate that reds on the normal path is one that gets switched off. This is
        the failure the P2/P3 pairing was supposed to avoid, so it is designed
        against rather than discovered later.

    The resolver distinguishes `unknown` (no object), `not-a-sha` (a ref name
    resolved to a commit), `wrong-type` (an existing tree/blob), and
    `ambiguous` (a short prefix names multiple objects). A ref is not an
    acceptable identity even when Git can resolve it today: the ref can move
    after the ledger records it.

    Returns None (rather than a function that always says `ok`) when there is no
    repo, so the caller can say the check did not run instead of printing a
    clean bill of health it never earned.
    """
    if _git("rev-parse", "--git-dir", repo=repo).returncode != 0:
        return None
    has_main = _git("rev-parse", "--verify", "--quiet", "main^{commit}", repo=repo).returncode == 0
    cache: dict[str, str] = {}

    def state(sha: str) -> str:
        if sha in cache:
            return cache[sha]

        # `rev-parse --verify <sha>^{commit}` collapses three different cases:
        # an absent object, a tree/blob, and a ref name that peels to a commit.
        # Ask Git the questions in an order that preserves those distinctions.
        disambiguated = _git("rev-parse", f"--disambiguate={sha}", repo=repo)
        object_matches = [
            line.strip() for line in disambiguated.stdout.splitlines()
            if re.fullmatch(r"[0-9a-f]{40}", line.strip())
        ]
        if len(object_matches) > 1:
            result = "ambiguous"
        else:
            resolved = _git("rev-parse", "--verify", "--quiet", sha, repo=repo)
            object_sha = resolved.stdout.strip()
            if resolved.returncode != 0 or not object_sha:
                result = "unknown"
            else:
                object_type = _git("cat-file", "-t", object_sha, repo=repo)
                if object_type.returncode != 0:
                    result = "unknown"
                elif object_type.stdout.strip() != "commit":
                    # Annotated tags resolve to a tag object through the raw
                    # ref, but peel successfully through `^{commit}`. They
                    # are still moving refs, whereas a tree/blob sha cannot
                    # peel to a commit and is genuinely the wrong object.
                    peeled = _git(
                        "rev-parse", "--verify", "--quiet", f"{sha}^{{commit}}",
                        repo=repo,
                    )
                    result = "not-a-sha" if peeled.returncode == 0 else "wrong-type"
                elif _SHA_RE.match(sha) and not object_sha.startswith(sha):
                    # A branch or tag name can be all lowercase hex and pass
                    # `_SHA_RE`; only the resolved object identity can expose
                    # that it was a moving ref rather than the recorded sha.
                    result = "not-a-sha"
                elif _git("merge-base", "--is-ancestor", object_sha, "HEAD", repo=repo).returncode == 0:
                    result = "ok"
                elif has_main and _git("merge-base", "--is-ancestor", object_sha, "main", repo=repo).returncode == 0:
                    result = "ok"
                else:
                    result = "orphan"
        cache[sha] = result
        return result

    return state


def validate_store(store: Path, *, repo: Path | None = None,
                   commit_state=..., ) -> list[dict]:
    store = Path(store)
    if commit_state is ...:
        commit_state = make_commit_state(repo)
    problems: list[dict] = []
    if not store.exists():
        # A typo'd --store used to report "0 problems, exit 0" — a green gate
        # pointed at nothing. Absence is a finding, not a clean bill of health.
        return [{"kind": "store-missing", "path": str(store)}]

    if commit_state is None:
        # Same rule one level up: the resolver says None when it could not be
        # built, and reading that as "every sha is fine" is the clean bill it
        # explicitly refused to sign. Name the gap instead of inheriting it.
        problems.append({"kind": "commit-state-unavailable",
                         "repo": str(repo or GIT_REPO)})

    # `glob("*.json")` is deliberately non-recursive: a legal entry under
    # `<store>/archive` is invisible to validate, ratchet, list, and render.
    # The orchestrator deliberately routes only top-level entries to avoid a
    # vacuous pass, while coverage is only a warning; assert the flat-store
    # invariant here so the two choices cannot silently hide a nested entry.
    for path in sorted(store.iterdir()):
        if not path.is_file() or path.suffix != ".json":
            problems.append({"kind": "stray-path", "path": str(path)})

    payloads: list[tuple[str, dict]] = []
    for path in sorted(store.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            problems.append({"kind": "unparseable", "path": str(path), "error": str(exc)})
            continue
        if not isinstance(payload, dict):
            problems.append({"kind": "unparseable", "path": str(path), "error": "not an object"})
            continue
        payloads.append((str(path), payload))
        for problem in validate_entry(payload, entry_id=path.stem,
                                      commit_state=commit_state):
            if problem["kind"] in {"fixed-by-orphaned", "fixed-by-unresolvable"}:
                problem = {**problem, "repo": str(repo or GIT_REPO)}
            problems.append({**problem, "path": str(path)})

    for problem in _check_blocking_graph(payloads):
        problems.append({k: v for k, v in problem.items() if k != "path"}
                        | {"path": problem.get("path")})

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
    brief: str | None = None,
    scope: str | dict | None = None,
    surface: str | None = None,
    repro: str | None = None,
    build: str | None = None,
    entry_id: str | None = None,
    verdict_fields: dict | None = None,
    extra: dict | None = None,
    overwrite: bool = False,
    historical: bool = False,
    _gate: bool = False,
    _outcome: dict | None = None,
    commit: bool = True,
) -> dict:
    """Compose one entry and, by default, create its file.

    Deliberately NOT dry-run-by-default, unlike the mutation subcommands.
    Creating a new file is additive and trivially reversible with git, and
    forcing two calls to file one issue is precisely the kind of friction that
    makes agents route around a tool. The exception is stated in `--help` rather
    than left for the next caller to discover — IMP-0040 is that lesson.  The CLI
    passes ``commit=False`` both for an explicit preview and for `add --stage`;
    the latter records the composed payload on the shared queue before a later
    `anchor` writes it. Internal importers keep the historical immediate-write
    default.
    """
    scope = coerce_scope(scope)
    if _gate and status == "fixed":
        # `import --commit` writes with overwrite=True, so a legacy table row can
        # flip a LIVE, groomed entry to `fixed` over a criterion that fails today.
        # Reproduced: an entry with `acceptance_cmd: "false"` was closed by a
        # one-row table, rc=0, silent. Gated against the STORED criterion — a
        # legacy row that creates a new entry has none and grades `unproven`, which
        # is what the historical import honestly is.
        try:
            stored = load_entry(store, entry_id) if entry_id else {}
        except (EntryNotFound, OSError, ValueError):
            stored = {}
        _gate_closure(stored or {"id": entry_id or "(new entry)"},
                      {"status": status}, commit=commit)

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
    for field, value in (("brief", brief), ("scope", scope),
                         ("surface", surface), ("repro", repro), ("build", build)):
        # Truthiness, not `is not None`: an empty string is the absence this
        # schema already represents by omission, and writing `"brief": ""` would
        # make `list --missing-brief` report the same entry as both present and
        # empty depending on which test it used.
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

    derived_id = make_entry_id(**{
        field: payload[field] for field in DIGEST_FIELDS
    })
    historical_id_mismatch = (
        entry_id is not None
        and not _LEGACY_ENTRY_ID_RE.fullmatch(entry_id)
        and entry_id != derived_id
    )
    historical_identity_matches = _matches_imported_historical_identity(
        entry_id=entry_id,
        stream=payload["stream"],
        date=payload["date"],
    )
    if entry_id is not None and not _LEGACY_ENTRY_ID_RE.fullmatch(entry_id):
        if not overwrite or (
            historical_id_mismatch
            and not (historical and historical_identity_matches)
        ):
            raise ValueError(
                "explicit id is reserved for migration of legacy IMP-#### entries; "
                "new IDs are derived from stream/date/source/detail"
            )

    payload["id"] = entry_id or derived_id
    if not _SAFE_ID_RE.match(payload["id"]):
        raise ValueError(f"unusable entry id (must be a bare filename): {payload['id']!r}")
    if historical_id_mismatch:
        payload[HISTORICAL_ID_DIGEST] = derived_id
    else:
        # A rerun carries every non-table field forward.  Drop obsolete
        # provenance if a corrected historical row now matches its digest.
        payload.pop(HISTORICAL_ID_DIGEST, None)

    # Creation does not owe TRACEABILITY. `import` exists to represent HISTORY,
    # and history is full of `fixed` rows whose landing commit was never written
    # down — refusing them here would mean the only way to migrate the ledger is
    # to first solve the audit problem the ledger was migrated to expose.
    # `update` is the interactive path and does enforce it (see
    # _merged_and_validated), and `validate` enforces it over the whole store,
    # so nothing filed this way escapes the gate — it just is not refused at the
    # moment of writing, when the caller may genuinely not know the answer yet.
    #
    # It DOES owe the status obligations, which this switch used to suppress as
    # collateral (see `_check_status_obligations`). The CLI defaults to an
    # immediate additive write but also exposes an explicit dry-run; both paths
    # must reject the same invalid payload before any write. The per-kind
    # question that makes the refusal safe is answered in the test named
    # `test_add_is_silent_on_an_ordinary_new_open_entry`: an ordinary new `open`
    # entry has no plan, no acceptance and no landing commit, and this check must
    # be SILENT on it, or the repair is a tool nobody can file with.
    problems = validate_entry(payload, entry_id=payload["id"], check_traceability=False)
    if payload.get("groomed_by") or payload.get("groomed_at"):
        problems.extend(_check_groom_write(payload, payload))
    if historical and problems:
        # `import` is the ONE caller that represents rows written before these rules
        # existed, and the legacy table really does contain `triaged` rows whose
        # resolution cell is the empty marker `—`. Refusing them here does not
        # improve the ledger: `import_legacy` records a `rejected-row` and carries
        # on, so the entry is LOST — a migration turned into data loss, caught by
        # `test_rerun_picks_up_edits_made_between_runs` while this landed.
        #
        # The forgiven set is derived by RE-RUNNING the same function on the same
        # payload rather than listed as kinds, so it can never forgive something
        # that check did not actually say about this entry, and a rule added there
        # needs no edit here. `validate` still names these over the whole store —
        # this forgives the moment of writing, not the finding.
        forgiven = {p["kind"] for p in _check_status_obligations(payload)}
        problems = [p for p in problems if p["kind"] not in forgiven]
    if problems:
        # Name the repair. `no-next-action` is the one kind a caller meets by
        # reaching for a flag that looked legal, so it gets the route out. A hint
        # pointing at a second dead end is worse than none.
        hint = ""
        bad_category = next(
            (p for p in problems if p["kind"] == "bad-category"), None
        )
        if bad_category is not None:
            allowed = ", ".join(CATEGORIES[stream])
            other_stream = next(
                other for other in STREAMS if other != stream
                and bad_category["value"] in CATEGORIES[other]
            ) if any(
                bad_category["value"] in CATEGORIES[other]
                for other in STREAMS if other != stream
            ) else None
            ownership = f" ({bad_category['value']} is {other_stream}-only)" \
                if other_stream else ""
            hint = (
                f"\n  invalid category {bad_category['value']!r} for stream {stream}"
                f" — allowed: {allowed}{ownership}"
            )
        elif any(p["kind"] == "no-next-action" for p in problems):
            hint = (
                "\n  `--status triaged` claims the next step is decided, so the entry "
                "owes one. Two ways out:\n"
                "    file it as `--status open` (the default — drop the flag) and "
                "groom it later with `update <id> --plan ...`\n"
                "    or say the next step now: --resolution '— <下一步>'"
            )
        elif any(p["kind"] == "wont-fix-without-reason" for p in problems):
            hint = ("\n  a decision not to fix is an argument: "
                    "--resolution '<why this will not be done>'")
        raise ValueError(f"invalid entry: {problems}{hint}")

    path = entry_path(store, payload["id"])
    lock = _entry_lock(path) if commit else contextlib.nullcontext()
    with lock:
        if path.exists() and not overwrite:
            existing = json.loads(path.read_text(encoding="utf-8"))
            if existing == payload:
                if _outcome is not None:
                    _outcome["written"] = False
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

        if commit:
            _write_atomic(path, _dumps(payload))
        if _outcome is not None:
            # Set inside the same critical section that made the write decision;
            # it is an observed outcome, not a TOCTOU inference.
            _outcome["written"] = commit
    return payload


# `detail` and `source` are NOT here: they are digest inputs (make_entry_id), so
# editing them decouples the id from the content it is derived from. Nothing
# recomputes the digest, so the drift is permanent and invisible — and then
# re-filing the original wording re-mints the same id and overwrites the triaged
# entry. A reworded problem statement is a different entry; file it, don't
# mutate this one.
MUTABLE_FIELDS = (
    ("status", "severity", "resolution", "category")
    + BRIEF_FIELDS
    + APP_ONLY_FIELDS
    + VERDICT_FIELDS
    + GROOM_FIELDS
    + AUDIT_FIELDS
    + TRACE_FIELDS
    + RELATION_FIELDS
    + CONTRACT_FIELDS
)


def _splice_before(fields: tuple[str, ...], anchor: str,
                   extra: tuple[str, ...]) -> tuple[str, ...]:
    """Insert `extra` immediately before `anchor`, or die loudly at import.

    `.index` rather than a second hand-written ordering: if `detail` is ever
    renamed, this raises while the module loads instead of silently appending the
    human-facing fields to the end, where the whole point of them — being read
    BEFORE the 400 characters of prose they summarise — is quietly lost.
    """
    i = fields.index(anchor)
    return fields[:i] + extra + fields[i:]

# What `show` prints, in order. A named constant rather than the same four groups
# concatenated a second time inside `_cmd_show`, because that hand-copy is exactly
# how `fixed_by` came to be stored, validated and invisible: TRACE_FIELDS was added
# to MUTABLE_FIELDS and not to the reader. The rule is that this is the WHOLE
# schema, never a curated subset, and
# `test_show_can_print_every_field_update_can_write` asserts it instead of trusting
# this sentence.
#
# `brief` / `scope` are spliced in AHEAD of `detail` rather than appended: they
# are the one-line answers, and printing them below the prose they summarise puts
# them where the reader who needs them has already stopped reading.
SHOW_FIELD_ORDER = (
    _splice_before(REQUIRED_FIELDS, "detail", BRIEF_FIELDS)
    + APP_ONLY_FIELDS + VERDICT_FIELDS + GROOM_FIELDS + AUDIT_FIELDS + TRACE_FIELDS
    + RELATION_FIELDS + CONTRACT_FIELDS + IDENTITY_AUDIT_FIELDS
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
REFUSED_UPDATE_FIELDS = tuple(DIGEST_FIELDS)

# Which free-text dests each subcommand refuses outright, so `_resolve_file_twins`
# does not read a file whose value has no destination.
REFUSED_BY_COMMAND: dict[str, tuple[str, ...]] = {"update": REFUSED_UPDATE_FIELDS}

# A source is safe to re-file only before any verification or closure evidence
# has attached to it.  ``fix_site`` and the other verdict fields are included on
# purpose: they are populated by the verification/audit surface as well as by
# grooming, and supersede must not guess which meaning a pre-existing reference
# had.  Conservative refusal preserves the old record instead of risking an
# audit trail that silently points at the wrong immutable payload.
SUPERSEDE_REFERENCE_FIELDS = tuple(dict.fromkeys((*TRACE_FIELDS, *VERDICT_FIELDS)))

# Free text, i.e. fields whose value is prose an agent composes rather than a
# token from a fixed vocabulary. Every one of these gets a `--<flag>-file` twin,
# because argv is not a safe channel for prose: a backtick inside a double-quoted
# shell string is command substitution, so the text is rewritten BEFORE this
# process sees it and nothing — not the store, not git — records that anything was
# removed. Three occurrences in one day: a sentence lost from a `detail`, a phrase
# lost from a commit message, and a dropped closing quote that stored an
# unparseable acceptance command.
#
# No in-tool detection is possible and none is attempted: by the time argv arrives
# the information is already gone, so any "was this mangled?" check would be a
# guess. The only fix is a channel the shell does not touch.
FILE_TWIN_FIELDS = (
    "source", "detail", "resolution", "plan", "acceptance", "acceptance_cmd",
    "acceptance_cmd_static",
    "acceptance_manual", "repro", "evidence", "verified_evidence", "fix_site",
    # The sentence that makes an audit exemption auditable — prose, and prose
    # about a shell command, so it is the likeliest field in the schema to carry
    # a backtick.
    ACCEPTANCE_GREEN_EXPECTED,
    # A path plus the command that re-derives the fix, i.e. exactly the two
    # things a shell rewrites: `~` and backticks.
    "fixed_elsewhere",
    # Written by a human in prose, in Chinese, and quoting the thing that is
    # broken — which is exactly the text most likely to carry a backtick.
    *BRIEF_FIELDS,
    # Contract evidence is a re-runnable command/result receipt, not a fixed
    # vocabulary token; preserve the shell-safe file channel for it as well.
    "contract_checked_at", "contract_checked_by", "contract_evidence",
)

def _repair_hints(problems: list[dict], entry_id: str) -> list[str]:
    """Return actionable repair guidance for validation problems."""
    # Name the repair, not just the defect. An orphaned `fixed_by` blocks
    # every unrelated edit to that entry — `update <id> --severity high`
    # fails with a message about a sha the caller never touched — and the
    # two ways out are not guessable. `reanchor` is listed first because it
    # is usually right, and second because it is NOT always: when the rebase
    # resolved a conflict differently the patch-id differs and reanchor will
    # correctly refuse to guess (IMP-0062), leaving the explicit form.
    hints = []
    if any(p["kind"] == "fixed-by-orphaned" for p in problems):
        hints.append(
            f"  a rebase orphaned it -> ops/backlog.py reanchor {entry_id} --commit\n"
            f"  reanchor cannot map it -> pass the right sha: "
            f"ops/backlog.py update {entry_id} --fixed-by <sha> --commit"
        )
    if any(p["kind"] == "fixed-by-unresolvable" for p in problems):
        hints.append(
            f"  這顆 sha 在任何 odb 都不存在（不是 rebase 孤兒，reanchor 對它無效）"
            f"-> 查出正確的落地 sha 後：ops/backlog.py update {entry_id} "
            "--fixed-by <sha> --commit"
        )
    if any(p["kind"] == "fixed-by-ambiguous-prefix" for p in problems):
        hints.append(
            "  fixed_by is an ambiguous short prefix -> use a longer or full "
            "40-character commit sha; do not run reanchor"
        )
    if any(p["kind"] == "fixed-by-not-a-commit-object" for p in problems):
        hints.append(
            "  fixed_by names an existing non-commit object -> replace it "
            "with the commit sha, not a tree or blob sha"
        )
    if any(p["kind"] == "fixed-by-not-a-sha" for p in problems):
        hints.append(
            "  fixed_by resolved as a moving ref name -> pass the full or "
            "unambiguous commit sha, not a branch or tag name"
        )
    if any(p["kind"] == "fixed-without-fixed-by" for p in problems):
        hints.append(
            f"  closing it -> ops/backlog.py update {entry_id} --status fixed "
            f"--fixed-by <sha>... --commit (fill it AFTER the fix lands)\n"
            f"  the fix is NOT in this repo (e.g. ~/butler, which has no git) -> "
            f"--fixed-elsewhere '<where it lives + how to re-derive it>' instead; "
            f"exactly one of the two, and the declared set is countable with "
            f"`list --fixed-elsewhere`"
        )
    if any(p["kind"] == "fixed-with-conflicting-traceability" for p in problems):
        hints.append(
            f"  drop one: `--fixed-by` says the fix is a commit in this repo, "
            f"`--fixed-elsewhere` says it is not. Clear the wrong one with "
            f"`update {entry_id} --fixed-elsewhere '' --commit` (or re-set "
            f"--fixed-by alone)"
        )
    if any(p["kind"] == "groom-claim-with-conflicting-acceptance-proof"
           for p in problems):
        hints.append(
            "  choose exactly one acceptance proof: `--acceptance-cmd` means a "
            "command can decide the criterion; `--acceptance-manual` means no "
            "command can. Keep `--acceptance-cmd` when the criterion is expressible "
            "as a command; otherwise keep `--acceptance-manual`. This conflict has "
            f"no date cutoff; clear the other proof with `update {entry_id} "
            "--acceptance-manual '' --commit` (keep the command) or "
            f"`update {entry_id} --acceptance-cmd '' --commit` (keep the manual proof)"
        )
    # These two are the ONLY kinds whose repair is fully determined, so they
    # are the last ones that should arrive as a bare defect name. Written as
    # the flags to add rather than "write a brief", because the thing the
    # caller has to produce is prose and the hint has to say what it is FOR.
    missing_prose = [p["field"] for p in problems
                     if p["kind"] in {f"groom-claim-without-{f}" for f in BRIEF_FIELDS}]
    if missing_prose:
        # Phrased as flags to ADD to the command you just ran, deliberately NOT
        # as a standalone runnable line. The neighbouring hints can be pasted
        # verbatim and will FAIL (`<sha>` cannot pass _SHA_RE), which is what
        # makes them safe to write that way. These two cannot: the fields take
        # free prose, so a pasted `--brief '<…>'` SUCCEEDS and stores the
        # placeholder — the caller walks away believing the entry is groomed.
        # That is precisely the "it believes it followed the tool" failure this
        # change was filed against, and it would have been reintroduced by the
        # hint that fixes it.
        hints.append(
            "  add to the command you just ran: "
            + " ".join(f"--{f} '<一句話>'" for f in missing_prose) + "\n"
            f"  brief = 白話「壞了什麼、誰有感」(禁檔名/行號/縮寫); "
            f"scope = JSON 檔案清單（每個 path 標 add 或 modify）；舊文字只會被看板標成 Scope 未知。"
        )
    if any(p["kind"] == "groom-claim-with-unknown-scope" for p in problems):
        hints.append(
            "  scope 不能再用說明文字：改成 JSON 檔案清單，格式為 "
            "files[] JSON（每個 item 有 path 與 operation）；"
            "每個 path 只能標 add 或 modify。"
        )
    return hints


def _merged_and_validated(payload: dict, changes: dict, entry_id: str,
                          *, check_traceability: bool = True,
                          clear_fields: tuple[str, ...] = ()) -> dict:
    """The single predicate both `update_entry` and the CLI dry-run run through.

    Two copies of this used to exist and the dry-run copy omitted the
    unknown-field check, so a preview could print a clean diff and the identical
    command with --commit could exit 64.
    """
    changes = dict(changes)
    if "scope" in changes:
        changes["scope"] = coerce_scope(changes["scope"])
    unknown = [field for field in changes if field not in MUTABLE_FIELDS]
    unknown.extend(field for field in clear_fields if field not in MUTABLE_FIELDS)
    if unknown:
        raise ValueError(f"unknown field(s): {unknown}; mutable: {sorted(MUTABLE_FIELDS)}")

    before_status = payload.get("status")
    after_status = changes.get("status", before_status)
    if (before_status in ("fixed", "wont-fix")
            and after_status not in ("fixed", "wont-fix")):
        raise BacklogError(
            f"{entry_id} is closed (status={before_status}); a normal mutation "
            "cannot reopen it. A recurrence is a new `add` with its observed "
            "date/source so the previous closure remains an honest audit trail"
        )

    updated = dict(payload)
    for field in clear_fields:
        updated.pop(field, None)
    for field, value in changes.items():
        if value is None:
            continue
        updated[field] = value

    # The real resolver, not the permissive default: refusing a bad sha at write
    # time is the difference between one caller seeing an error and every later
    # `validate` run seeing a defect it cannot attribute to anyone.
    problems = validate_entry(updated, entry_id=entry_id,
                              commit_state=make_commit_state(),
                              check_traceability=check_traceability)
    problems.extend(_check_groom_write(changes, updated))
    # Two gates ask the same question of a groom stamp from different angles, so
    # once the date binds BOTH fire and the caller sees each missing field twice.
    # Four problems for two defects reads as a bigger mess than it is, and the
    # duplicate is not even distinguishable at a glance (only the `since`/`at`
    # key differs).
    #
    # Keyed on the DISCRIMINATORS, not on `kind` alone. `kind` alone is wrong and
    # measurably so: three kinds are emitted once per item — `app-field-on-imp-entry`
    # and `missing-field` per field, and the `fixed-by-*` family per sha (`--fixed-by`
    # is nargs="+") — so collapsing by kind made the tool report the first item,
    # get it fixed, and refuse again with the next. Dripping defects one at a time
    # is the failure this function's own "name the repair" comment is about, and
    # the two problems that ARE duplicates share kind AND field, differing only in
    # `since`/`at`, so they still collapse.
    seen: set = set()
    problems = [p for p in problems
                if not ((key := (p["kind"], p.get("field"), p.get("sha"))) in seen
                        or seen.add(key))]
    if problems:
        hints = _repair_hints(problems, entry_id)
        raise ValueError("invalid update: " + repr(problems)
                         + ("\n" + "\n".join(hints) if hints else ""))
    return updated


def update_entry(store: Path, entry_id: str, *, _clear_fields: tuple[str, ...] = (),
                 _lock_held: bool = False, **changes) -> dict:
    """Change fields on an existing entry, in place, keeping its id.

    The id digest deliberately covers only the fields that identify WHICH
    problem this is, so triaging never moves an entry: if it did, every
    cross-reference would rot and the store would grow a fresh file per status
    change.

    Unknown field names are refused rather than stored. A typo that silently
    created a field nobody reads is the quiet half of the drift this store
    exists to remove.
    """
    if not _lock_held:
        with _entry_lock(entry_path(store, entry_id)):
            return update_entry(
                store, entry_id, _clear_fields=_clear_fields,
                _lock_held=True, **changes
            )

    payload = load_entry(store, entry_id)
    # Validate BEFORE writing, so a rejected update leaves the file exactly as
    # it was rather than half-applied.
    updated = _merged_and_validated(
        payload, changes, entry_id, clear_fields=_clear_fields
    )
    _write_atomic(entry_path(store, entry_id), _dumps(updated))
    return updated


def _restore_atomic_bytes(path: Path, content: bytes) -> None:
    """Restore a file byte-for-byte through a temporary atomic replacement."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        mode = path.stat().st_mode & 0o7777
    except OSError:
        umask = os.umask(0)
        os.umask(umask)
        mode = 0o666 & ~umask

    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.rollback.", suffix=".tmp", dir=str(path.parent)
    )
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


def _supersede_present_references(entry: dict) -> list[str]:
    return [
        field for field in SUPERSEDE_REFERENCE_FIELDS
        if entry.get(field) not in (None, "", [], {})
    ]


def _supersede_transaction(
    store: Path,
    source_id: str,
    *,
    stream: str | None = None,
    date: str | None = None,
    source: str | None = None,
    detail: str | None = None,
    commit: bool,
) -> dict:
    """Plan or atomically commit a corrected replacement for one open entry."""
    if not _SAFE_ID_RE.fullmatch(source_id or ""):
        raise BacklogError(f"invalid source id: {source_id!r}")

    store = Path(store)
    with _supersede_locks(store):
        source_path = entry_path(store, source_id)
        original = load_entry(store, source_id)

        if original.get("status") != "open":
            raise BacklogError(
                f"{source_id} can be superseded only while status=open; "
                f"current status={original.get('status')!r}"
            )

        claims = held_tickets()
        if source_id in claims:
            claim = claims[source_id]
            raise BacklogError(
                f"{source_id} is claimed by {claim.get('branch')} at "
                f"{claim.get('path') or '(unknown path)'}; supersede requires an unclaimed source"
            )

        references = _supersede_present_references(original)
        if references:
            raise BacklogError(
                f"{source_id} has audit references ({', '.join(references)}); "
                "supersede refuses a source with fixed or verification evidence"
            )

        source_problems = validate_entry(
            original, entry_id=source_id, check_traceability=False
        )
        if source_problems:
            raise BacklogError(
                f"{source_id} source entry is not complete; supersede refused: "
                f"{source_problems}"
            )

        identity = {
            "stream": stream if stream is not None else original["stream"],
            "date": date if date is not None else original["date"],
            "source": source if source is not None else original["source"],
            "detail": detail if detail is not None else original["detail"],
        }
        if not isinstance(identity["date"], str) or not _DATE_RE.fullmatch(
            identity["date"]
        ):
            raise BacklogError(
                f"date must be YYYY-MM-DD, got {identity['date']!r}"
            )
        replacement_id = make_entry_id(**identity)
        if not _SAFE_ID_RE.fullmatch(replacement_id):
            raise BacklogError(
                f"unusable replacement id (must be a bare filename): {replacement_id!r}"
            )
        if replacement_id == source_id:
            raise BacklogError(
                "supersede needs a corrected immutable field; the replacement id "
                "would be identical to the source id"
            )

        replacement_path = entry_path(store, replacement_id)
        if replacement_path.exists():
            raise BacklogError(
                f"replacement id {replacement_id} already exists; refusing a duplicate"
            )

        replacement = dict(original)
        replacement.update(identity)
        replacement["id"] = replacement_id
        replacement["status"] = "open"
        replacement["resolution"] = ""

        original_resolution = str(original.get("resolution") or "").strip()
        retirement_reason = f"superseded by {replacement_id}"
        if original_resolution:
            retirement_reason += f"; previous resolution retained: {original_resolution}"
        retired = dict(original)
        retired["status"] = "wont-fix"
        retired["resolution"] = retirement_reason

        for label, payload, entry_id in (
            ("replacement", replacement, replacement_id),
            ("retired source", retired, source_id),
        ):
            problems = validate_entry(
                payload, entry_id=entry_id, check_traceability=False
            )
            if problems:
                raise BacklogError(
                    f"supersede would create an invalid {label}: {problems}"
                )

        result = {
            "schema": "kg.backlog.supersede.v1",
            "mode": "commit" if commit else "dry-run",
            "written": False,
            "source_id": source_id,
            "replacement_id": replacement_id,
            "source": retired,
            "entry": replacement,
        }
        if not commit:
            return result

        original_bytes = source_path.read_bytes()
        try:
            _write_atomic(replacement_path, _dumps(replacement))
            _write_atomic(source_path, _dumps(retired))
        except Exception as exc:
            rollback_errors: list[str] = []
            if replacement_path.exists():
                try:
                    replacement_path.unlink()
                except OSError as rollback_exc:
                    rollback_errors.append(
                        f"remove replacement: {rollback_exc}"
                    )
            try:
                _restore_atomic_bytes(source_path, original_bytes)
            except OSError as rollback_exc:
                rollback_errors.append(f"restore source: {rollback_exc}")
            suffix = (
                f"; rollback errors: {'; '.join(rollback_errors)}"
                if rollback_errors else "; both files restored"
            )
            raise BacklogError(
                f"supersede publish failed: {exc}{suffix}"
            ) from exc

        result["written"] = True
        return result


def load_entry(store: Path, entry_id: str) -> dict:
    path = entry_path(store, entry_id)
    if not path.exists():
        raise EntryNotFound(entry_id)
    return json.loads(path.read_text(encoding="utf-8"))


def _iter_entries(store: Path):
    yield from _backlog_query.iter_entries(store)


def _sort_key(payload: dict) -> tuple:
    return _backlog_query.sort_key(payload)


def entry_sort_key_by_id(store: Path):
    """Return a key function over entry ids, matching `list_entries` order."""
    return _backlog_query.entry_sort_key_by_id(
        store,
        iter_entries_fn=_iter_entries,
        sort_key_fn=_sort_key,
    )


def list_entries(
    store: Path,
    *,
    status: str | None = None,
    stream: str | None = None,
    severity: str | None = None,
    category: str | None = None,
    groomed: bool = False,
    ungroomed: bool = False,
    groom_stale_days: int | None = None,
    include_closed: bool = False,
    acceptance_manual: bool = False,
    acceptance_green_expected: bool = False,
    fixed_elsewhere: bool = False,
    missing_brief: bool = False,
    grep: str | None = None,
    dispatch: bool = False,
    held: dict | None = None,
    repo: Path | None = None,
) -> list[dict]:
    deps = _backlog_query.QueryDeps(
        backlog_error=BacklogError,
        iter_entries_fn=_iter_entries,
        sort_key_fn=_sort_key,
        brief_fields=BRIEF_FIELDS,
        acceptance_green_expected=ACCEPTANCE_GREEN_EXPECTED,
        date_re=_DATE_RE,
        today=_today,
        days_before=_days_before,
        held_tickets=held_tickets,
        blocking_ids=_blocking_ids,
        contract_preflight=contract_preflight,
        worst_first_key=_worst_first_key,
        scope_status_fn=scope_status,
    )
    return _backlog_query.list_entries(
        store,
        deps=deps,
        status=status,
        stream=stream,
        severity=severity,
        category=category,
        groomed=groomed,
        ungroomed=ungroomed,
        groom_stale_days=groom_stale_days,
        include_closed=include_closed,
        acceptance_manual=acceptance_manual,
        acceptance_green_expected=acceptance_green_expected,
        fixed_elsewhere=fixed_elsewhere,
        missing_brief=missing_brief,
        grep=grep,
        dispatch=dispatch,
        held=held,
        repo=repo,
    )


_ID_IN_SUBJECT_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:IMP|APP)-(?:\d{4}|\d{8}-[0-9a-f]{6})(?![A-Za-z0-9])"
)
_LIKELY_FILING_COMMIT_RE = re.compile(
    r"^docs:\s*.*(?:立案|補回|登記|\bfile\b)", re.IGNORECASE
)


def _zombie_commit_lines(
    *, repo: Path | None = None, search_depth: int = DEFAULT_SEARCH_DEPTH,
) -> list[str]:
    """Read a bounded synthetic-friendly commit stream for zombie inspection."""
    if search_depth < 1:
        raise BacklogError("--zombie-search-depth must be at least 1")
    result = _git(
        "log", "main", f"--max-count={search_depth}",
        "--format=%H%x01%s", repo=repo,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or "main history unavailable"
        raise BacklogError(f"cannot inspect main commit history: {detail}")
    return [line for line in result.stdout.splitlines() if line.strip()]


def zombie_suspects(
    store: Path,
    *,
    commit_lines: list[str | tuple[str, str]] | None = None,
    repo: Path | None = None,
    search_depth: int = DEFAULT_SEARCH_DEPTH,
) -> list[dict]:
    """List unresolved entries named by recent commits as review candidates.

    A commit mention is deliberately weaker than an acceptance result: this
    function never changes a ticket's status. ``commit_lines`` is an explicit
    seam for synthetic tests and offline callers; the CLI reads the bounded
    ``main`` history when it is omitted.
    """
    unresolved = {
        str(entry.get("id")): entry
        for entry in _iter_entries(store)
        if entry.get("status") not in ("fixed", "wont-fix")
    }
    lines = (commit_lines if commit_lines is not None else
             _zombie_commit_lines(repo=repo, search_depth=search_depth))
    rows: list[dict] = []
    for line in lines:
        if isinstance(line, (tuple, list)) and len(line) == 2:
            sha, subject = (str(line[0]), str(line[1]))
        else:
            sha, separator, subject = str(line).partition("\x01")
            if not separator:
                continue
        if not subject.strip():
            continue
        for entry_id in dict.fromkeys(_ID_IN_SUBJECT_RE.findall(subject)):
            entry = unresolved.get(entry_id)
            if entry is None:
                continue
            classification = (
                "likely-filing" if _LIKELY_FILING_COMMIT_RE.search(subject)
                else "suspect"
            )
            rows.append({
                "id": entry_id,
                "status": entry.get("status"),
                "brief": str(entry.get("brief") or ""),
                "commit": {"sha": sha, "subject": subject},
                "classification": classification,
            })
    return rows


def _worst_first_key(payload: dict) -> tuple:
    """The order a queue is taken from the TOP of: severity descending, then oldest.

    ONE definition, two readers — `dispatch` above and `audit-criteria`'s `--limit`,
    whose help promises "same order as `dispatch`". It was written out twice before
    this, byte-identically, which is the copy `_severity_rank`'s own docstring says
    this module has already paid for twice: nothing goes red when two hand-written
    copies of an ordering drift, the two commands simply stop agreeing about what
    "worst" means and the `--limit` help quietly becomes false.

    `audit-criteria` cannot reach this through `list_entries(dispatch=True)`: that
    queue also excludes CLAIMED tickets, and a ticket somebody is holding is exactly
    as likely to carry a lying criterion as an unclaimed one.
    """
    return (-_severity_rank(payload), _sort_key(payload))


def _severity_rank(payload: dict) -> int:
    """Position in SEVERITIES, read off the vocabulary rather than restated.

    A hand-written {"high": 2, ...} map is a second copy of a closed vocabulary,
    and this module has already paid twice for the second copy drifting.
    """
    try:
        return SEVERITIES.index(str(payload.get("severity")))
    except ValueError:
        return -1  # outside the vocabulary: last, and `validate` names it


# Closed WITHOUT an attributable verification. This is the ratchet key, and the
# choice of key is the whole design:
#
#   * keyed on every entry -> `add` would red the gate, because a freshly filed
#     entry legitimately has no verification. Punishing filing is how a ledger
#     stops being filed.
#   * keyed on CLOSED entries -> `add` cannot move it, and closure is precisely
#     when the audit trail starts to rot (the branch gets deleted, the sha gets
#     rebased). Every broken audit trail found in the 2026-08-06 sweep was on a
#     closed entry.
#
# The baseline is a SET OF IDS, not a count. `ops/tests/test_lint_baselines.sh`
# already paid for that lesson: `|baseline| <= |current|` holds while membership
# churns, so a stale key becomes a permanent re-offence slot.
def closed_without_verification(store: Path) -> list[str]:
    out = []
    for payload in _iter_entries(store):
        if payload.get("status") not in ("fixed", "wont-fix"):
            continue
        # All four, not just date+name: with only the first two, `update
        # --verified-at X --verified-by Y` cleared this gate while leaving no
        # verdict and no evidence — the two fields `verify` exists to bundle,
        # applied piecemeal through the door next to it.
        if not all(str(payload.get(f) or "").strip()
                   for f in ("verified_at", "verified_by", "verdict", "verified_evidence")):
            out.append(str(payload.get(id_field := "id")))
    return sorted(out)


def _baseline_path() -> Path:
    # ROOT-anchored like DEFAULT_STORE, and for the same reason: the baseline and
    # the ledger it forgives must name the same checkout. A cwd-relative default
    # let a foreign (larger) baseline pre-forgive everything and read green.
    # `ROOT / x` returns x unchanged when x is absolute, so one expression gives
    # both halves: absolute overrides as given, relative ones against the repo
    # root — matching the KG_INJECTION_BASELINE contract in tech_index.md rather
    # than inventing a second, opposite rule for the neighbouring env var.
    override = os.environ.get("KG_BACKLOG_BASELINE")
    if override:
        return ROOT / override
    return ROOT / "ops" / "backlog_closed_unverified_baseline.txt"


def _id_drift_baseline_path(store: Path) -> Path | None:
    override = os.environ.get("KG_BACKLOG_ID_DRIFT_BASELINE")
    if override:
        return ROOT / override
    try:
        if Path(store).resolve() == DEFAULT_STORE.resolve():
            return ROOT / "ops" / "backlog_id_drift_baseline.txt"
    except OSError:
        pass
    return None


def _read_id_drift_baseline(path: Path) -> tuple[dict[str, str], list[dict]]:
    if not path.exists():
        return {}, []
    pairs: dict[str, str] = {}
    problems: list[dict] = []
    for line_number, raw in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        columns = line.split()
        if len(columns) != 2:
            problems.append({
                "kind": "invalid-id-content-drift-baseline",
                "line": line_number,
                "value": raw,
                "reason": "expected exactly: <observed-id> <current-expected-id>",
            })
            continue
        observed_id, expected_id = columns
        if not (_MODERN_ENTRY_ID_RE.fullmatch(observed_id)
                and _MODERN_ENTRY_ID_RE.fullmatch(expected_id)):
            problems.append({
                "kind": "invalid-id-content-drift-baseline",
                "line": line_number,
                "value": raw,
                "reason": "both columns must be modern content-derived ids",
            })
            continue
        if observed_id in pairs:
            problems.append({
                "kind": "invalid-id-content-drift-baseline",
                "line": line_number,
                "id": observed_id,
                "reason": "duplicate observed id",
            })
            continue
        pairs[observed_id] = expected_id
    return pairs, problems


def _read_baseline(path: Path) -> set[str]:
    if not path.exists():
        return set()
    return {ln.strip() for ln in path.read_text(encoding="utf-8").splitlines()
            if ln.strip() and not ln.lstrip().startswith("#")}


def select_entries(
    store: Path,
    *,
    unverified: bool = False,
    stale_days: int | None = None,
    groom_stale_days: int | None = None,
    today: str | None = None,
    **filters,
) -> list[dict]:
    """The re-verification queue: what has never been checked, and what has aged.

    Two questions, deliberately not merged. `unverified` is "nobody has ever
    re-derived this from current code"; `stale_days` is "somebody did, N days
    ago". Collapsing them would let running the staleness query read as full
    coverage while the never-looked-at set sits outside both answers — and
    today that set is the larger one by far (99 of 159, of which 42 are
    `fixed`).

    No status filter is applied by default, and that is the point. The 2026-08-05
    sweep covered unfinished entries only, and an audit trail rots *after*
    closure: the branch gets deleted, the sha gets rebased. Every one of the
    four broken audit trails found the next day was on a `fixed` entry.
    """
    return _backlog_query.select_entries(
        store,
        list_entries_fn=list_entries,
        date_re=_DATE_RE,
        days_before=_days_before,
        today=_today,
        backlog_error=BacklogError,
        unverified=unverified,
        stale_days=stale_days,
        groom_stale_days=groom_stale_days,
        today_value=today,
        **filters,
    )


def _today() -> str:
    return datetime.date.today().isoformat()


def _days_before(day: str, days: int) -> str:
    return (datetime.date.fromisoformat(day) - datetime.timedelta(days=days)).isoformat()


def _real_date(value) -> bool:
    r"""A date on the calendar, not a string shaped like one.

    `^\d{4}-\d{2}-\d{2}$` accepts `2026-13-45`, `9999-99-99` and `0000-00-00`,
    all measured landing in the store through `--at`. The last two break the rule
    they were checked by: `verdict-without-date` exists because a verdict with no
    date can never go stale, and `9999-99-99` is a verdict that never goes stale
    while satisfying the check. Future dates are refused for the same reason —
    a verification claimed for next year is not a verification.
    """
    text = str(value or "")
    if not _DATE_RE.match(text):
        return False
    try:
        return datetime.date.fromisoformat(text) <= datetime.date.today()
    except ValueError:
        return False


# ---------------------------------------------------------------------------
# legacy table import
# ---------------------------------------------------------------------------

LEGACY_COLUMNS = _backlog_legacy.LEGACY_COLUMNS

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
VIEW_IMP_COLUMNS = _backlog_view.VIEW_IMP_COLUMNS

_ID_RE = _backlog_legacy.ID_RE

_EMPTY_CELL = _backlog_legacy.EMPTY_CELL


def _split_row_raw(line: str) -> list[str]:
    return _backlog_legacy.split_row_raw(line)


def _clean(cell: str) -> str:
    return _backlog_legacy.clean(cell)


def _anchors_ok(cells: list[str]) -> bool:
    return _backlog_legacy._anchors_ok(
        cells,
        categories=CATEGORIES,
        severities=SEVERITIES,
        parseable_statuses=PARSEABLE_STATUSES,
    )


def _app_anchors_ok(cells: list[str]) -> bool:
    return _backlog_legacy._app_anchors_ok(
        cells,
        app_columns=APP_COLUMNS,
        categories=CATEGORIES,
        severities=SEVERITIES,
        parseable_statuses=PARSEABLE_STATUSES,
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
    return _backlog_legacy.parse_legacy_table(
        text,
        categories=CATEGORIES,
        severities=SEVERITIES,
        parseable_statuses=PARSEABLE_STATUSES,
        app_columns=APP_COLUMNS,
        split_row_raw_fn=_split_row_raw,
        clean_fn=_clean,
        id_re=_ID_RE,
        empty_cell=_EMPTY_CELL,
        anchors_ok_fn=_anchors_ok,
        app_anchors_ok_fn=_app_anchors_ok,
    )


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
_STAMP_HEAD_RE = _backlog_legacy.STAMP_HEAD_RE
_VERDICT_TOKEN_RE = _backlog_legacy.VERDICT_TOKEN_RE

# `成本 S–M` uses an EN DASH. Splitting on `-` would report `S` and silently
# halve the estimate.
_COST_RE = _backlog_legacy.COST_RE
_COST_PRESENT_RE = re.compile(r"成本")
_FIX_SITE_RE = _backlog_legacy.FIX_SITE_RE
_FIX_SITE_HEAD_RE = _backlog_legacy.FIX_SITE_HEAD_RE
# A fix site has to look like one. IMP-0021's stamp yields `:738-741` — a bare
# line range whose filename lives in another column — and `見上一列` passes a
# purely syntactic backtick check too. Both become paths that readers trust.
_FIX_SITE_SHAPE_RE = _backlog_legacy.FIX_SITE_SHAPE_RE


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
    return _backlog_legacy.extract_verdict_fields(
        resolution,
        verdicts=VERDICTS,
        duplicate_prefix=_DUPLICATE_VERDICT_PREFIX,
    )


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
    return _backlog_legacy.import_legacy(
        text,
        store,
        parse_table=parse_legacy_table,
        extract_fields=extract_verdict_fields,
        load_entry=load_entry,
        add_entry=add_entry,
        retired_statuses=RETIRED_STATUSES,
        historical_id_digest=HISTORICAL_ID_DIGEST,
    )


# ---------------------------------------------------------------------------
# generated view
# ---------------------------------------------------------------------------

# `tier: runbook` and not `tier: generated`: `generated` is a registry *kind*
# (docs/registry.yml), while the frontmatter `tier` is checked against
# docs_lint.sh's VALID_TIERS, which has no such value. The precedent was
# docs/snapshot/ios_baseline.md — tier: snapshot in the doc, kind: generated in
# the registry — until IMP-20260808-b63206 moved that artifact out of version
# control too; the registry now declares no `kind: generated` entry at all.
_VIEW_HEADER = """<!-- doc-meta
tier: runbook
authority: generated
update_trigger: machine-generated
scope:
  - {store_label}
verified_against: {verified_against}
-->
# 改善 Backlog（kaizen ledger）

> ⚠️ **GENERATED — 不要手改這個檔。** 內容由 `ops/backlog.py render` 從
> `{store_label}/*.json` 產生，手改會被下一次 render 覆蓋。
> 要改請用 `ops/backlog.py update <id>`；要新增用 `ops/backlog.py add`。

> 自我提升迴圈的登記處。**SoT 是 `{store_label}`**，本檔是它的 render。所有「工具 / CLI / 文檔 / 架構」摩擦（`IMP-*`）與
> 「app 實際使用」問題（`APP-*`）的 open 問題單一登記處。
> 原則見**鐵律9**（摩擦優先修工具）、分級見 `kg-router`「Tool Friction」、
> 表態見 `kg-receipt`「Tooling Debt」——本文**不複述**，只負責**持久化、追蹤、收斂**。

## 為什麼是一筆一檔

receipt 裡的 tooling debt 會隨 transcript 蒸發。本 ledger 讓每個 raised 問題
**進 git、可回溯、有 owner、追到 resolved**。

存成 `{store_label}/<id>.json`（一筆一檔）而非單一表格，是因為單一表格
在多 agent 並發下必然衝突：每次 append 都打同一段行區，而流水號 id 跨 worktree
必撞（檔案在 merge 前彼此看不見）。IMP-0017 自己記著已經撞過兩次。

## Entry schema

- `status`：{statuses}（`wont-fix` 須在 resolution 附理由）
- `category`：IMP 為 {imp_categories}；APP 為 {app_categories}
- `severity`：{severities}
- `resolution`：解決的敘述，或 wont-fix 理由。**可回溯的權威欄是下面的 `fixed_by`，不是這欄的散文**
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
- **驗證歸屬**：`verified_by`（誰檢查的）/ `verified_evidence`（跑了什麼命令）。用
  `ops/backlog.py verify <id> --verdict <V> --by <誰> --evidence '<命令>'` 一次寫齊，
  不要用 `update` 拆成幾個各自可能被忘記的旗標。
- **在工作樹裡結案的走 `stage`，不走 `verify`**：`verify --commit` 會當場寫 store 並重生
  這份 view，那是並行分支唯一會真的衝突的檔。改用
  `ops/backlog.py stage <id> --verdict <V> --by <誰> --evidence '<命令>'`——旗標與 `verify`
  相同，但只 append 進 gitignored 的波次佇列。`cutover` 落地後蓋上真正的 sha，波次結束由
  **一個人**跑 `ops/backlog.py anchor --commit` 把整波寫進 store。`stage` 恆等於
  `status=fixed`（沒有旗標可改）：佇列存在的理由是落地 commit 此刻還不存在，而只有 `fixed`
  需要落地 commit；`wont-fix` 要的是理由不是 hash，當場用 `update` 寫即可。卡住整波的壞列
  用 `ops/backlog.py unstage <id> --commit` 取下。佇列 `list --unverified`（沒有可歸屬
  驗證的，**不濾 status**）與 `list --stale --stale-days N`（驗過但已老），兩者互斥。
  **結案（fixed / wont-fix）而無可歸屬驗證會被 `validate --baseline-check` 擋**，
  存量記在 `ops/backlog_closed_unverified_baseline.txt`，只能降不能升
- **梳理戳記**（`plan` / `acceptance` / `groomed_at` / `groomed_by`）：與上面的重新取證欄位
  回答**不同問題**——`verdict` 答「這問題還在嗎」，梳理戳記答「**修法想清楚了嗎**」。
  兩者曾被同一次 sweep 寫進同一組欄位，於是「哪些已經被深度論證過」無法從資料回答，
  這組欄位就是為此而存在。`plan` 的標準是**小模型照著就能執行、不需要再自行推導**；
  這條標準是散文、無法機器驗，但它的**前提可以**：宣告 `groomed_by` 就必須同時有
  `plan`、`acceptance`、`fix_site`，否則 `validate` 直接紅。
  查未梳理的佇列用 `ops/backlog.py list --ungroomed`
- **`brief` / `scope`（寫給不同讀者的兩欄）**：`brief` = 一句白話「壞了什麼、誰有感」；
  `scope` = `{{"files":[{{"path":"ops/x.py","operation":"modify"}}]}}` 的實際檔案清單，
  每個檔案明確標 `add` 或 `modify`。舊票的 Scope 文字仍可讀，但看板會標為 Scope 未知，
  不會從 `fix_site` 或散文猜檔案。存在理由：矩陣要讓人與 agent 直接看見哪些檔案被 active
  佔用，以及 queued ticket 是否與 active 重疊；`fix_site` 仍是 executor 的程式錨點。
  **蓋或更新 groom 戳記時當場就要求這兩欄**（`_check_groom_write`，與日期無關）；
  `validate` 對**既有資料**分開 grandfather：`brief` 以 `BRIEF_REQUIRED_SINCE`
  為界，structured Scope 以 `SCOPE_REQUIRED_SINCE` 為界，因為 Scope 的重新定義晚於
  brief 規則且 store 內已有 legacy Scope。缺這兩欄的未結案 entry 用
  `ops/backlog.py list --missing-brief` 數（**回填佇列，不是 dispatch 佇列**）
- **`acceptance` 不再是唯寫欄位**（IMP-20260808-9f3838）。它曾經只被檢查「非空」，
  此後沒有任何一行程式再讀它——那正是本檔註解警告過兩次的「沒人讀的理由欄位」，
  只是這次發生在守衛自己身上。2026-08-08 起，宣告梳理必須**恰好**帶其中一個：
  - `acceptance_cmd` ＋ `acceptance_expect_rc`（預設 0）：`anchor --commit` 在寫入
    store **之前實際執行它**，exit code 不符就拒絕整波。`expect_rc` 不是裝飾——store
    裡有反向偵測器（「exit 1 ＝ 問題還在」），逼它回 0 會把判決做反。
  - `acceptance_manual`：說明為什麼沒有命令能表達。**不是逃生門**，是可計數的宣告：
    `list --acceptance-manual` 查得到，`anchor` 的 payload 也會回報本波有幾筆靠它。
  兩個都填是拒絕的——那是對同一個問題的兩個矛盾主張。此日期之前梳理的一律沿用
  （grandfathered by date：`groomed_at` 是梳理當下寫的，所以重新梳理會蓋上新日期而
  受規則約束；用 id baseline 反而會永久赦免那一筆）。
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
    return _backlog_view.cell(value)


def _render_table(entries: list[dict], columns: tuple[str, ...]) -> str:
    return _backlog_view.render_table(
        entries,
        columns,
        cell_fn=_cell,
        empty_cell=_EMPTY_CELL,
    )


# SUPERSEDED 2026-08-05 by IMP-20260805-355016. This used to read "the rendered
# table deliberately stays at the legacy 8 columns... a cosmetic column is not
# worth trading reversibility for". Reversibility was abandoned by executive
# ruling: it was already half-broken (the APP half never imported —
# IMP-20260805-f4ec99 measured rc=2) and the importer's only input is a file this
# module produced. The IMP table now renders `VIEW_IMP_COLUMNS` (12). The reason
# this note stays rather than being deleted: the old rule read as settled policy,
# so its absence has to be visible to whoever comes looking for it.

APP_COLUMNS = _backlog_view.APP_COLUMNS


def view_entry_ids(text: str) -> set[str]:
    return _backlog_view.view_entry_ids(
        text,
        split_row_raw_fn=_split_row_raw,
        clean_fn=_clean,
        id_re=_ID_RE,
    )


def render_view(store: Path, *, verified_against: str) -> str:
    """Render the human-readable view of the store. Deterministic."""
    view_header = _VIEW_HEADER.replace(
        "{store_label}",
        "external-backlog-store"
        if _backlog_store.is_external_store(store, ROOT)
        else "docs-runbook-backlog",
    )
    return _backlog_view.render_view(
        store,
        verified_against=verified_against,
        list_entries=list_entries,
        view_header=view_header,
        imp_intro=_IMP_INTRO,
        app_intro=_APP_INTRO,
        categories=CATEGORIES,
        statuses=STATUSES,
        severities=SEVERITIES,
        verdicts=VERDICTS,
        cell_fn=_cell,
        empty_cell=_EMPTY_CELL,
    )


def view_counts(store: Path) -> dict[str, int]:
    return _backlog_view.view_counts(store, list_entries=list_entries)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _store_help_path() -> str:
    """The default store, shown relative to the repo when it is inside it.

    `relative_to` RAISES for a path outside ROOT, and it is called while BUILDING
    THE PARSER — so a default store anywhere else does not produce an odd help
    string, it produces a ValueError before argv is even looked at. Reached whenever
    DEFAULT_STORE is redirected (tests do it; so would anyone pointing the tool at a
    second ledger). Help text is not a good reason for a crash."""
    try:
        return str(DEFAULT_STORE.relative_to(ROOT))
    except ValueError:
        return str(DEFAULT_STORE)


def store_for_repo(repo: Path) -> Path:
    """Return the store that belongs to ``repo`` under the current configuration.

    The real checkout may select an external store through ``KG_BACKLOG_STORE``.
    Scratch repositories used by the orchestrator tests still need their own
    canonical relative store; otherwise one process would accidentally make a
    fixture claim against the developer's configured ledger.
    """
    repo = Path(repo).expanduser().resolve()
    root = Path(ROOT).expanduser().resolve()
    if repo == root:
        return Path(DEFAULT_STORE).expanduser().resolve()
    return repo / _backlog_store.LEGACY_STORE_RELATIVE


def store_descriptor(store: Path, root: Path | None = None) -> dict[str, object]:
    """Expose store provenance without making callers import a private seam."""
    return _backlog_store.store_descriptor(store, root or ROOT)


def _add_store_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--store",
        type=Path,
        default=DEFAULT_STORE,
        help=f"entry directory (default: {_store_help_path()})",
    )


def _nonnegative_int(value: str) -> int:
    try:
        number = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a non-negative integer") from exc
    if number < 0:
        raise argparse.ArgumentTypeError("must be a non-negative integer")
    return number


def _add_list_filters(parser: argparse.ArgumentParser, *, dispatch_flag: bool) -> None:
    """Every read filter, on whichever door asked for it.

    `list --dispatch` and `dispatch` are ONE implementation reached two ways, and
    this function is what makes that structural rather than a promise. A second
    hand-written flag block behind the noun would drift, and the drift would be
    invisible from the outside: both doors would keep returning *a* list, and the
    caller who typed the noun would simply be unable to express a question the
    flag can. `test_every_list_filter_is_reachable_from_the_dispatch_door` asserts
    the two option sets differ by exactly `--dispatch`.

    `dispatch_flag` is the one asymmetry: on the `dispatch` subcommand the queue
    is the command, so a `--dispatch` flag there would be a flag that can only be
    redundant or contradictory.
    """
    _add_store_arg(parser)
    parser.add_argument("--status", choices=STATUSES)
    parser.add_argument("--stream", choices=STREAMS)
    parser.add_argument("--severity", choices=SEVERITIES)
    parser.add_argument("--category")
    parser.add_argument(
        "--ungroomed",
        action="store_true",
        help="only entries nobody has worked out a fix plan for (the groom queue). "
             "Closed entries are excluded because nobody will ever groom them; "
             "add --include-closed to widen this population. "
             "NOTE this store knows nothing about who is WORKING on an entry: that "
             "lives in the worktree ledger (`ops/worktree_registry.py list`, columns "
             "`backlog` / `claimed`). This flag alone is NOT a dispatch queue — it "
             "will hand out ids another agent already holds; ask the `dispatch` "
             "subcommand (or `list --dispatch`) instead. Named as the subcommand "
             "and not as `--dispatch`, because this same help is printed by "
             "`dispatch --help`, where that flag does not exist",
    )
    parser.add_argument(
        "--include-closed", dest="include_closed", action="store_true",
        help="with --ungroomed, include fixed and wont-fix entries too; by default "
             "closed entries are excluded because nobody will ever groom them",
    )
    parser.add_argument(
        "--groom-stale-days", type=int, default=None, metavar="N",
        help="with --ungroomed, also requeue groomed entries whose groomed_at is "
             "older than N days; opt-in only (suggested audit window: 90 days; "
             "default: disabled)",
    )
    parser.add_argument(
        "--groomed", action="store_true", help="only entries carrying a groom stamp"
    )
    parser.add_argument(
        "--held", action="store_true",
        help="only tickets a worktree on THIS MACHINE currently claims (derived from "
             "the worktree ledger; there is no stored in-progress status any more)"
    )
    if dispatch_flag:
        parser.add_argument(
            "--dispatch", action="store_true",
            help="WHAT TO TAKE NEXT — the intersection of five clauses: groomed "
                 "(`groomed_by` set, which `validate` guarantees implies "
                 "plan/acceptance/fix_site) AND unresolved (status is not fixed or "
                 "wont-fix) AND unclaimed (no worktree on this machine holds it) "
                 "AND unblocked (no unresolved `blocked_by` edge) AND "
                 "contract-ready (preflight passed with a red baseline). "
                 "Sorted worst-first, then oldest-first. Two things it CANNOT see, "
                 "both printed with the result: the claim ledger is per-machine, so "
                 "across machines this queue is OPTIMISTIC; and board deferrals live "
                 "outside this repo, so a snoozed entry is still offered. Identical "
                 "to the `dispatch` subcommand",
        )
    parser.add_argument(
        "--acceptance-manual", dest="acceptance_manual", action="store_true",
        help="only entries that DECLARE no command can prove their acceptance — the "
             "set `anchor` cannot machine-check, kept countable on purpose"
    )
    parser.add_argument(
        "--acceptance-green-expected", dest="acceptance_green_expected",
        action="store_true",
        help="only entries that DECLARE their criterion is green by design — the "
             "set `audit-criteria` skips rather than reports as suspect. Countable "
             "for the same reason as --acceptance-manual: a skip nobody can list "
             "is a check nobody can argue with"
    )
    parser.add_argument(
        "--fixed-elsewhere", dest="fixed_elsewhere", action="store_true",
        help="only entries closed against a fix that landed OUTSIDE this repo (no "
             "sha to follow, so the audit trail is prose). The other declared "
             "exception, countable for the same reason as --acceptance-manual"
    )
    parser.add_argument(
        "--missing-brief", dest="missing_brief", action="store_true",
        help="the BACKFILL queue: unresolved entries with no --brief or no known "
             "structured --scope, "
             "i.e. the ones the phone board can only show 400 characters of agent "
             "prose for. NOT a dispatch queue — most of these already carry a full "
             "plan and what they need written is a sentence, not a fix. Closed "
             "entries are excluded because they never reach the board",
    )
    parser.add_argument(
        "--unverified", action="store_true",
        help="only entries nobody has ever re-derived from current code. NOT filtered "
             "by status on purpose: an audit trail rots after closure, and 42 of the "
             "99 unverified entries today are already `fixed`",
    )
    parser.add_argument(
        "--stale", action="store_true",
        help="only entries verified longer ago than --stale-days. Distinct from "
             "--unverified: never-checked is not the same finding as checked-and-aged",
    )
    parser.add_argument("--stale-days", type=int, default=30, metavar="N")
    parser.add_argument(
        "--groomed-against-max-commits", type=_nonnegative_int,
        default=GROOMED_AGAINST_MAX_COMMITS, metavar="N",
        help=f"warn when groomed_against is more than N commits behind local main "
             f"(default {GROOMED_AGAINST_MAX_COMMITS}; warning only)",
    )
    parser.add_argument(
        "--grep", metavar="PATTERN",
        help="only entries whose detail/resolution/plan/fix_site match this regex "
             "(case-insensitive). THE FIRST THING TO RUN BEFORE FILING OR FIXING "
             "ANYTHING: 170+ entries in, `is this already filed?` had no answer in "
             "this tool, and the cost was a groomed spec rebuilt from scratch. "
             "ANDs with every filter above, so `--grep X --status open` is the "
             "narrow question worth asking",
    )
    parser.add_argument(
        "--zombie-suspects", action="store_true",
        help="read recent main commits and list unresolved tickets they mention "
             "as review candidates; this never changes ticket status",
    )
    parser.add_argument(
        "--zombie-search-depth", type=int, default=None, metavar="N",
        help=f"number of main commits to inspect for --zombie-suspects "
             f"(default {DEFAULT_SEARCH_DEPTH})",
    )
    parser.add_argument("--json", action="store_true")


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

    p_add = sub.add_parser(
        "add",
        help="file a new entry (lands immediately, previews, or parks with --stage)",
        description=(
            "File a new entry. Unlike overwrite-style mutations, this command "
            "WRITES IMMEDIATELY by default so an observed problem is not lost. "
            "Use --dry-run to preview without writing, or --stage to park the "
            "entry until its branch lands; --commit explicitly spells the fast "
            "default."
        ),
    )
    _add_store_arg(p_add)
    p_add.add_argument(
        "--queue", type=Path, default=None,
        help="staged-add queue (default: <primary>/.cache/backlog_anchor_queue.jsonl; "
             "only valid with --stage)",
    )
    p_add.add_argument("--stream", choices=STREAMS, required=True)
    p_add.add_argument("--date", required=True, help="YYYY-MM-DD")
    p_add.add_argument("--source", required=True, help="where this was noticed")
    p_add.add_argument("--category", required=True, help=f"IMP: {CATEGORIES['IMP']} APP: {CATEGORIES['APP']}")
    p_add.add_argument("--severity", choices=SEVERITIES, required=True)
    p_add.add_argument("--status", choices=STATUSES, default="open")
    p_add.add_argument("--detail", required=True)
    p_add.add_argument("--resolution", default="")
    # Offered on `add` as well as `update`, unlike the groom flags next to them.
    # Grooming is a separate act because a badge you can self-apply while filing
    # costs nothing; saying in one plain sentence what you just noticed costs the
    # filer nothing to be honest about and is the only text the board can show.
    # A groom stamp needs both fields anyway, so making the filer wait for a
    # second command would only delay the writing, not improve it.
    p_add.add_argument(
        "--brief",
        help="ONE plain sentence for a human deciding what to work on next: what "
             "is broken or missing and who feels it. No filenames, line numbers or "
             "acronyms — that is --detail's job. REQUIRED whenever a groom badge "
             "is stamped, at ANY date (`update --groomed-by ...` is refused "
             f"without it); `validate` additionally holds stored grooming dated "
             f"{BRIEF_REQUIRED_SINCE} or later for brief; "
             f"{SCOPE_REQUIRED_SINCE} or later for structured Scope",
    )
    p_add.add_argument(
        "--scope",
        help="JSON file claim: {files:[{path,operation}]} with operation add|modify; "
             "legacy prose remains readable but appears as Scope unknown on the board. "
             "NOT --fix-site: that is the executor's code anchor",
    )
    p_add.add_argument("--surface", help="APP only: reader/vocabulary/notebook/...")
    p_add.add_argument("--repro", help="APP only: how to reproduce")
    p_add.add_argument("--build", help="APP only: build the problem was seen on")
    p_add.add_argument("--id", dest="entry_id", help="explicit id (migration of legacy IMP-#### only)")
    # Mirror the executable grooming fields so a caller who already knows the
    # repair can file and groom in one validated write. File twins are derived
    # below from the same parser actions, avoiding a second hand-written list.
    p_add.add_argument("--plan", help="how to fix it, concrete enough to execute")
    p_add.add_argument("--acceptance", help="red-then-green acceptance prose")
    p_add.add_argument("--acceptance-cmd", dest="acceptance_cmd",
                       help="machine-checkable acceptance command")
    p_add.add_argument("--acceptance-cmd-static", dest="acceptance_cmd_static",
                       help="optional bounded worker feedback command")
    p_add.add_argument("--acceptance-expect-rc", dest="acceptance_expect_rc", type=int,
                       help="expected exit code for --acceptance-cmd")
    p_add.add_argument("--acceptance-manual", dest="acceptance_manual",
                       help="why no command can express acceptance")
    p_add.add_argument("--acceptance-green-expected", dest="acceptance_green_expected",
                       help="why this command is expected green before implementation")
    p_add.add_argument("--fix-site", dest="fix_site", help="primary code/document anchor")
    p_add.add_argument("--groomed-by", dest="groomed_by", help="grooming actor")
    p_add.add_argument("--groomed-at", dest="groomed_at", help="YYYY-MM-DD")
    p_add.add_argument("--groomed-against", dest="groomed_against",
                       help="main commit checked by the grooming plan")
    p_add.add_argument("--contract-status", choices=CONTRACT_STATUSES)
    p_add.add_argument("--contract-baseline", choices=CONTRACT_BASELINES)
    p_add.add_argument("--contract-checked-at")
    p_add.add_argument("--contract-checked-by")
    p_add.add_argument("--contract-evidence")
    add_mode = p_add.add_mutually_exclusive_group()
    add_mode.add_argument(
        "--dry-run", action="store_true",
        help="validate and print the would-be entry without creating its JSON file",
    )
    add_mode.add_argument(
        "--commit", action="store_true",
        help="explicitly select the default immediate-write mode; useful when a "
             "generic mutation runner always spells its write intent",
    )
    add_mode.add_argument(
        "--stage", action="store_true",
        help="validate and queue the new entry without writing the store; "
             "`anchor --commit` materializes it after the branch lands",
    )
    p_add.add_argument("--json", action="store_true")
    p_lifecycle = sub.add_parser(
        "lifecycle",
        help="explain the ticket state machine, actor boundaries and common paths",
        description=(
            "Read-only contract for a ticket from filing to terminal disposition. "
            "Use --json when an agent or another tool needs the same model."
        ),
    )
    p_lifecycle.add_argument("--json", action="store_true")

    p_list = sub.add_parser(
        "list",
        help="list entries and report staged queue work pending anchor",
        description="list entries and report staged queue work pending anchor",
    )
    _add_list_filters(p_list, dispatch_flag=True)

    # The SAME flags, the same handler, one implementation — see `_add_list_filters`.
    # It exists because the operating constitution nominalises this queue ("take one
    # from `dispatch`"), and an agent that has read the constitution types the noun:
    # the first command of the 2026-08-08 dogfood batch was `backlog.py dispatch
    # --json`, answered with `invalid choice`. A second hand-written queue behind
    # the noun would drift from the flag and the drift would be invisible, because
    # both doors would keep returning *a* list.
    p_dispatch = sub.add_parser(
        "dispatch",
        help="what to take next: groomed AND unresolved AND unclaimed AND unblocked "
             "AND contract-ready, worst first "
             "(identical to `list --dispatch`; accepts every `list` filter)",
    )
    _add_list_filters(p_dispatch, dispatch_flag=False)

    p_stage = sub.add_parser(
        "stage",
        help="park a closure on the wave queue INSTEAD of writing the store "
             "(the entry is validated now; the store is touched once per wave by "
             "`anchor`). Use this from a hunter's worktree",
    )
    p_stage.add_argument("id")
    _add_store_arg(p_stage)
    p_stage.add_argument("--queue", type=Path, default=None,
                         help="queue file (default: <primary>/.cache/"
                              "backlog_anchor_queue.jsonl — gitignored, shared by "
                              "every worktree of this repo)")
    p_stage.add_argument("--verdict", required=True,
                         help=f"one of {', '.join(VERDICTS)} or DUPLICATE-OF-<id>")
    p_stage.add_argument("--by", required=True,
                         help="what did the checking, e.g. agent:ops-engineer")
    p_stage.add_argument("--evidence", required=True,
                         help="the command YOU ran. It travels with the row: an "
                              "integrator inventing it at wave end is writing the "
                              "reason field nobody checked")
    p_stage.add_argument("--at", help="YYYY-MM-DD (default: today)")
    p_stage.add_argument("--replace", action="store_true",
                         help="overwrite an existing staged row for this id "
                              "(default: refuse, so one hunter cannot silently "
                              "replace another's evidence)")
    p_stage.add_argument("--json", action="store_true")

    p_unstage = sub.add_parser(
        "unstage",
        help="take one row back off the wave queue (DRY-RUN by default). The escape "
             "hatch for `anchor`'s all-or-nothing refusal — without it the only way "
             "past a bad row is hand-editing the queue file",
    )
    p_unstage.add_argument("id")
    p_unstage.add_argument("--queue", type=Path, default=None)
    p_unstage.add_argument("--commit", action="store_true")
    p_unstage.add_argument("--json", action="store_true")

    p_anchor = sub.add_parser(
        "anchor",
        help="replay the wave's staged closures into the store, all or nothing "
             "(DRY-RUN by default, --commit to land). Rows whose branch has not "
             "landed are reported and left queued; staged adds are materialized "
             "when their landing sha is present",
    )
    _add_store_arg(p_anchor)
    p_anchor.add_argument("--queue", type=Path, default=None)
    p_anchor.add_argument(
        "--branches", nargs="+", default=None, metavar="BRANCH",
        help="only materialize rows stamped by these branches; leaves other "
             "Delivery Teams' queued closures untouched",
    )
    p_anchor.add_argument("--commit", action="store_true")
    p_anchor.add_argument("--json", action="store_true")

    p_verify = sub.add_parser(
        "verify",
        help="record a re-verification: verdict + date + verifier + evidence, as one act "
             "(DRY-RUN by default, --commit to land)",
    )
    p_verify.add_argument("id")
    _add_store_arg(p_verify)
    p_verify.add_argument("--verdict",
                          help=f"one of {', '.join(VERDICTS)} or DUPLICATE-OF-<id>")
    p_verify.add_argument("--by",
                          help="what did the checking, e.g. agent:platform-steward")
    p_verify.add_argument("--evidence",
                          help="the command you ran; a verdict nobody can re-run is a claim. "
                               "REQUIRED: optional evidence in an 'atomic' act means evidence "
                               "is not in the atom, and omitting it left the PREVIOUS "
                               "verifier's command attached to the new verdict")
    p_verify.add_argument(
        "--static-only", action="store_true",
        help="run the stored acceptance_cmd_static feedback command only; read-only, "
             f"bounded to {STATIC_ACCEPTANCE_TIMEOUT_SECONDS:g}s, and never a closure proof",
    )
    p_verify.add_argument("--at", help="YYYY-MM-DD (default: today)")
    p_verify.add_argument("--status", choices=STATUSES,
                          help="change status in the same act, when the check changed the answer")
    # `--status fixed` without this is a dead end: the traceability rule refuses
    # a `fixed` entry with no landing commit, so the natural closing act
    # (`verify … --status fixed`) failed with an error about a flag this
    # subcommand did not have. Hit while closing this very batch.
    p_verify.add_argument("--fixed-by", dest="fixed_by", nargs="+", metavar="SHA",
                          help="required alongside --status fixed; the commits that landed the fix")
    # The same dead end, one field over. `--fixed-by` was added here because
    # `verify --status fixed` — this subcommand's own help calls it "the natural
    # closing act" — failed on a flag the subcommand did not have. An entry whose
    # fix has no sha would hit that identical wall unless the second form is
    # reachable from the same door.
    p_verify.add_argument("--fixed-elsewhere", dest="fixed_elsewhere",
                          help="alternative to --fixed-by alongside --status fixed, for "
                               "a fix that landed outside this repo; exactly one of the two")
    p_verify.add_argument("--contract-status", choices=CONTRACT_STATUSES)
    p_verify.add_argument("--contract-baseline", choices=CONTRACT_BASELINES)
    p_verify.add_argument("--contract-checked-at")
    p_verify.add_argument("--contract-checked-by")
    p_verify.add_argument("--contract-evidence")
    p_verify.add_argument("--commit", action="store_true")
    p_verify.add_argument("--json", action="store_true")

    p_audit = sub.add_parser(
        "audit-criteria",
        help="RUN the acceptance_cmd of every groomed, unresolved entry and report "
             "the ones that are already GREEN (read-only; EXECUTES stored commands)",
        description=(
            "An unresolved entry says its defect is still there, so its "
            "`acceptance_cmd` — the command that says what 'gone' looks like — "
            "should be RED today. This runs them and reports the green ones.\n\n"
            "WHAT THIS EXECUTES: `acceptance_cmd` is free text an agent wrote into "
            "the ledger. Some of these run pytest suites, start containers, open a "
            "simulator or call the network. Every selected entry's command is "
            "executed under `bash -c` at the repo root, exactly as the closing gate "
            "would run it. NO attempt is made to judge statically which commands are "
            "safe — that cannot be done, and a tool that pretended to would be "
            "selling reassurance. So a bare invocation is REFUSED: narrow it with "
            "--filter / --limit, look first with --dry-run, or say --all.\n\n"
            "When a selected criterion exits with an unexpected code, the criterion "
            "is executed twice: the second run uses `bash -x`, and the report names "
            "the last traced `failing_clause`. This is deliberate and can repeat "
            "side effects.\n\n"
            "It writes nothing TO THE STORE: there is no --commit and no write path. "
            "What the criteria themselves do to your machine is their own business, "
            "which is what the paragraph above is about."),
    )
    _add_store_arg(p_audit)
    p_audit.add_argument(
        "--dry-run", dest="dry_run", action="store_true",
        help="list what WOULD run, in order, and execute nothing. The sibling of "
             "`anchor`'s dry run and there for the same reason: these commands have "
             "real side effects, so reading them first is the only way to consent to "
             "them. The output says so — an empty `green` under --dry-run means "
             "nothing was measured, not that nothing is wrong")
    p_audit.add_argument(
        "--all", action="store_true",
        help="run every entry in the population, however many that is. The explicit "
             "opt-in the bare form refuses; contradicts --filter / --limit, which "
             "already narrow")
    p_audit.add_argument(
        "--filter", metavar="PATTERN",
        help="only entries whose id OR acceptance_cmd matches this regex "
             "(case-insensitive, matched against each separately). THE flag to "
             "reach for before a full sweep: it is what decides which stored "
             "commands run on your machine")
    p_audit.add_argument(
        "--limit", type=int, metavar="N",
        help="run at most N criteria, worst-first (same order as `dispatch`). The "
             "ids left unrun are NAMED in the output — a truncated sweep whose gaps "
             "are invisible reads as a clean bill of health")
    p_audit.add_argument(
        "--timeout-seconds", dest="timeout_seconds", type=float,
        default=AUDIT_TIMEOUT_SECONDS, metavar="N",
        help=f"per-criterion budget (default {AUDIT_TIMEOUT_SECONDS:g}s; the closing "
             f"gate allows {ACCEPTANCE_TIMEOUT_SECONDS}s for the one command a human "
             f"is waiting on, and this runs every entry's). A criterion that needs "
             f"longer is reported as `timeout`, never as green or red")
    p_audit.add_argument("--json", action="store_true")

    p_show = sub.add_parser("show", help="show one entry")
    _add_store_arg(p_show)
    p_show.add_argument("id")
    p_show.add_argument(
        "--groomed-against-max-commits", type=_nonnegative_int,
        default=GROOMED_AGAINST_MAX_COMMITS, metavar="N",
        help=f"warn when groomed_against is more than N commits behind local main "
             f"(default {GROOMED_AGAINST_MAX_COMMITS}; warning only)",
    )
    p_show.add_argument("--json", action="store_true")

    p_preflight = sub.add_parser(
        "preflight",
        help="compile one ticket's claim readiness without writing state",
        description=(
            "Read-only dispatch compiler. It classifies a ticket before a worktree "
            "claim; acceptance execution requires the explicit --probe-acceptance."
        ),
    )
    _add_store_arg(p_preflight)
    p_preflight.add_argument("id")
    p_preflight.add_argument(
        "--state", type=Path, default=None,
        help="explicit registry ledger for overlap checks (default: repository ledger)",
    )
    p_preflight.add_argument(
        "--probe-acceptance", action="store_true",
        help="explicitly run the ticket acceptance command (bounded; never writes state)",
    )
    p_preflight.add_argument("--json", action="store_true")

    p_validate = sub.add_parser(
        "validate",
        help="schema-check every entry and report staged queue work pending anchor",
        description="schema-check every entry and report staged queue work pending anchor",
    )
    # Enforcing and re-baselining are opposite acts, and `--baseline` returned
    # early — so passing both ran neither check, exited 0, and widened the
    # watermark. Same treatment as the three sister lints, and as this file's
    # own --unverified/--stale pair: a quiet empty result reads like a pass.
    p_baseline = p_validate.add_mutually_exclusive_group()
    p_baseline.add_argument(
        "--baseline-check", dest="baseline_check", action="store_true",
        help="also refuse NEW entries closed with no attributable verification "
             "(verified_at + verified_by + verdict + evidence), measured "
             "against the baseline set")
    p_baseline.add_argument(
        "--baseline", action="store_true",
        help="rewrite the baseline set from today's store, then exit "
             "(cannot be combined with --baseline-check)")
    _add_store_arg(p_validate)
    p_validate.add_argument("--json", action="store_true")

    p_groom = sub.add_parser(
        "groom",
        help="turn one unresolved report into executable, dispatchable work "
             "(DRY-RUN by default, --commit to land)",
        description=(
            "Work out HOW an unresolved report will be fixed, as one atomic act. "
            "This sets status=triaged plus brief/scope/plan/acceptance/fix_site "
            "and the groom stamp; a committed result can enter `dispatch` if it "
            "is also unclaimed, unblocked, and contract-ready. This is NOT `verify`: verify asks "
            "whether the reported claim is still true and is optional unless the "
            "claim is stale or uncertain. Groom asks whether the ticket is "
            "executable and is required before dispatch. Closed tickets stay "
            "closed; a recurrence is a new `add`. DRY-RUN by default."
        ),
    )
    _add_store_arg(p_groom)
    p_groom.add_argument("id")
    p_groom.add_argument(
        "--brief", required=True,
        help="one plain sentence: what is broken or missing and who feels it",
    )
    p_groom.add_argument(
        "--scope", required=True,
        help="JSON file claim {files:[{path,operation}]} with add|modify; "
             "not the code anchor (use --scope-file for shell-safe JSON)",
    )
    p_groom.add_argument(
        "--plan", required=True,
        help="steps concrete enough for a small model to execute without re-deriving",
    )
    p_groom.add_argument(
        "--acceptance", required=True,
        help="prose describing the red-then-green success condition",
    )
    p_groom.add_argument(
        "--acceptance-cmd", dest="acceptance_cmd",
        help="machine-checkable command used by the closure gate; exactly one of "
             "this and --acceptance-manual is required",
    )
    p_groom.add_argument(
        "--acceptance-cmd-static", dest="acceptance_cmd_static",
        help="optional bounded, toolchain-free command for worker feedback; "
             "never substitutes for the full closure command",
    )
    p_groom.add_argument(
        "--acceptance-expect-rc", dest="acceptance_expect_rc", type=int,
        help="exit code --acceptance-cmd must return (default 0)",
    )
    p_groom.add_argument(
        "--acceptance-manual", dest="acceptance_manual",
        help="why no command can express acceptance; exactly one of this and "
             "--acceptance-cmd is required and remains countable",
    )
    p_groom.add_argument(
        "--acceptance-green-expected", dest="acceptance_green_expected",
        help="why the command is expected to be green before implementation; "
             "requires --acceptance-cmd and remains countable",
    )
    p_groom.add_argument(
        "--fix-site", dest="fix_site", required=True,
        help="primary code/document anchor the executor should inspect first",
    )
    p_groom.add_argument(
        "--by", dest="groomed_by", required=True,
        help="who worked out the ticket, e.g. agent:platform-steward",
    )
    p_groom.add_argument(
        "--at", dest="groomed_at",
        help="YYYY-MM-DD (default: today)",
    )
    p_groom.add_argument(
        "--against", dest="groomed_against",
        help="local-main commit the plan was checked against (default: current local main)",
    )
    p_groom.add_argument("--commit", action="store_true")
    p_groom.add_argument("--json", action="store_true")

    p_update = sub.add_parser(
        "update",
        help="change fields on an existing entry (DRY-RUN by default, --commit to land)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Acceptance contract for grooming:\n"
            f"  From {ACCEPTANCE_PROOF_SINCE} onward, provide exactly one of the "
            f"stored proof fields {ACCEPTANCE_PROOF[0]} or {ACCEPTANCE_PROOF[1]} "
            "when stamping a groom badge; both is a conflict and neither is a "
            "missing proof.\n"
            "  acceptance_cmd is checked with `bash -n` when written, then run "
            f"with `bash -c` from the repo root at close time (up to "
            f"{ACCEPTANCE_TIMEOUT_SECONDS} seconds for this one command).\n"
            "  `--acceptance-expect-rc` supports INVERTED detectors whose non-zero "
            f"exit is the pass; audit-criteria uses a separate "
            f"{AUDIT_TIMEOUT_SECONDS}-second per-criterion budget."
        ),
    )
    _add_store_arg(p_update)
    p_update.add_argument("id")
    p_update.add_argument("--status", choices=STATUSES)
    p_update.add_argument("--severity", choices=SEVERITIES)
    p_update.add_argument("--category")
    p_update.add_argument("--resolution")
    p_update.add_argument(
        "--brief",
        help="ONE plain sentence for a human deciding what to work on next: what is "
             "broken or missing and who feels it. No filenames, line numbers or "
             "acronyms. REQUIRED whenever this call stamps or refreshes a groom "
             "badge, at ANY date — `--groomed-at 2026-01-01` does not get you out "
             f"of it; `validate` additionally holds stored grooming dated "
             f"{BRIEF_REQUIRED_SINCE} or later for brief; "
             f"{SCOPE_REQUIRED_SINCE} or later for structured Scope",
    )
    p_update.add_argument(
        "--scope",
        help="JSON file claim {files:[{path,operation}]} with add|modify; legacy prose "
             "remains readable but is Scope unknown on the board. NOT --fix-site. "
             "Any call that stamps a groom badge still needs a non-empty Scope",
    )
    for digest_field in DIGEST_FIELDS:
        p_update.add_argument(
            f"--{digest_field.replace('_', '-')}", dest=digest_field,
            help="REFUSED: a digest input. Corrections go in --resolution; a "
            "reworded problem is a new entry (`add`). Kept on the parser so the "
            "attempt gets an answer instead of 'unrecognized arguments'",
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
    p_update.add_argument("--acceptance", help="prose: what red-then-green looks like")
    p_update.add_argument(
        "--acceptance-cmd", dest="acceptance_cmd",
        help="the command `anchor --commit` ACTUALLY RUNS before closing this entry. "
             "This is the field that makes `fixed` mean something a machine checked; "
            "`--acceptance` alone is prose nothing reads. See `update --help` epilog "
            "for the complete acceptance contract")
    p_update.add_argument(
        "--acceptance-cmd-static", dest="acceptance_cmd_static",
        help="optional bounded, toolchain-free command for worker feedback; "
             "never substitutes for the full closure command",
    )
    p_update.add_argument(
        "--acceptance-expect-rc", dest="acceptance_expect_rc", type=int,
        help="exit code --acceptance-cmd must produce (default 0). Not decoration: "
             "some entries carry an INVERTED detector where non-zero is the pass")
    p_update.add_argument(
        "--acceptance-manual", dest="acceptance_manual",
        help="why no command can express this entry's acceptance. Mutually exclusive "
             "with --acceptance-cmd; provide exactly one. Countable, not a loophole: "
             "`list --acceptance-manual` and `anchor` both report the set")
    p_update.add_argument(
        "--acceptance-green-expected", dest="acceptance_green_expected",
        help="why THIS criterion is green even though the entry is unresolved — a "
             "negative assertion, a detector for something not yet reintroduced. "
             "Takes the entry out of `audit-criteria`'s suspect list and puts it in "
             "the `exempt` bucket with this sentence attached. Requires an "
             "--acceptance-cmd to exempt; countable via "
             "`list --acceptance-green-expected`, like --acceptance-manual")
    p_update.add_argument("--groomed-at", dest="groomed_at", help="YYYY-MM-DD")
    p_update.add_argument(
        "--groomed-by", dest="groomed_by", help="what did the grooming, e.g. workflow:groom@v1"
    )
    p_update.add_argument(
        "--groomed-against", dest="groomed_against",
        help="main commit SHA the grooming plan was checked against; when omitted "
             "while refreshing a groom stamp, the current local main tip is recorded",
    )
    # Reachable from `update` as well as `verify`, because the bidirectional
    # invariant (every mutable field has a flag) has no escape hatch — an
    # exemption list is how a field becomes unreachable without anyone noticing.
    # `verify` is the ergonomic path that sets the whole stamp at once.
    p_update.add_argument("--verified-by", dest="verified_by",
                          help="what did the checking; prefer `verify` which sets the whole stamp")
    p_update.add_argument("--verified-evidence", dest="verified_evidence",
                          help="the command behind the verdict")
    p_update.add_argument("--contract-status", choices=CONTRACT_STATUSES)
    p_update.add_argument("--contract-baseline", choices=CONTRACT_BASELINES)
    p_update.add_argument("--contract-checked-at")
    p_update.add_argument("--contract-checked-by")
    p_update.add_argument("--contract-evidence")
    p_update.add_argument(
        "--fixed-by", dest="fixed_by", nargs="+", metavar="SHA",
        help="commit(s) that made the defect stop being true; required by status=fixed. "
             "Fill it AFTER the fix lands — see reanchor if a rebase orphans one",
    )
    p_update.add_argument(
        "--blocked-by", dest="blocked_by", nargs="*", metavar="ID",
        help="ticket id(s) that must be fixed before this ticket is dispatched; "
             "pass the flag with no ids to clear the edge",
    )
    p_update.add_argument(
        "--fixed-elsewhere", dest="fixed_elsewhere",
        help="the OTHER form of traceability, for a fix that landed where there are "
             "no shas (e.g. ~/butler, which is Syncthing-synced and not a git repo). "
             "EXACTLY ONE of this and --fixed-by; say WHERE the fix lives and HOW to "
             "re-derive it, because nothing can follow this one mechanically. Not a "
             "loophole — countable via `list --fixed-elsewhere`, exactly like "
             "--acceptance-manual",
    )
    p_update.add_argument("--commit", action="store_true")
    p_update.add_argument("--json", action="store_true")

    p_supersede = sub.add_parser(
        "supersede",
        help="re-file a corrected immutable payload and retire the open source "
             "(DRY-RUN by default, --commit to land)",
        description=(
            "Replace a damaged open entry without deleting its audit trail. "
            "The source must be unclaimed and carry no fixed or verification "
            "reference. The replacement id is derived from stream/date/source/detail; "
            "both files are published under one store lock."
        ),
    )
    _add_store_arg(p_supersede)
    p_supersede.add_argument("id")
    p_supersede.add_argument("--stream", choices=STREAMS,
                             help="corrected stream (default: source stream)")
    p_supersede.add_argument("--date",
                             help="corrected observed date (default: source date)")
    p_supersede.add_argument("--source",
                             help="corrected source text (default: source value)")
    p_supersede.add_argument("--detail",
                             help="corrected detail text (default: source value)")
    supersede_mode = p_supersede.add_mutually_exclusive_group()
    supersede_mode.add_argument(
        "--dry-run", action="store_true",
        help="validate and show both resulting entries without writing either file",
    )
    supersede_mode.add_argument(
        "--commit", action="store_true",
        help="publish the replacement and retire the source atomically",
    )
    p_supersede.add_argument("--json", action="store_true")

    p_reanchor = sub.add_parser(
        "reanchor",
        help="re-point orphaned fixed_by shas at their post-rebase equivalents "
             "(DRY-RUN by default, --commit to land)",
    )
    p_reanchor.add_argument("ids", nargs="*", help="entry ids; default = every entry with an orphan")
    p_reanchor.add_argument("--store", type=Path, default=DEFAULT_STORE)
    p_reanchor.add_argument(
        "--search-depth", type=int, default=DEFAULT_SEARCH_DEPTH,
        help=f"how many commits back from HEAD and main to scan for a patch-id match (default {DEFAULT_SEARCH_DEPTH}; the frame falls back to HEAD-only when main is unavailable, and the result reports whether the window was exhausted). "
             "The bound is REPORTED, never silent: a miss inside the window and a miss "
             "because the window ended are different answers",
    )
    p_reanchor.add_argument(
        "--docs", action="store_true",
        help="also reanchor orphaned verified_against values in docs/**/*.md",
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
    p_render.add_argument(
        "--out", type=Path, default=None,
        help="rendered view path (default: beside an external store, or the legacy repo view)",
    )
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

    _add_file_twins(parser)
    return parser


def _subcommands(parser: argparse.ArgumentParser) -> dict:
    return parser._subparsers._group_actions[0].choices


def _add_file_twins(parser: argparse.ArgumentParser) -> None:
    """Give every free-text flag a `--<flag>-file` twin, derived not hand-listed.

    Walks the parser instead of carrying a table of (subcommand, flag) pairs. A
    second list is a second thing to forget, and this module has been bitten by
    exactly that twice: `update`'s change map was hand-written until it drifted
    from MUTABLE_FIELDS, and half the mutable fields had no `update` flag at all
    because nobody re-read both lists together. Here the twin cannot go missing —
    the flag's own presence is what creates it.

    A twin can satisfy a requirement, so a required base flag stops being required
    to argparse and the "exactly one of them" rule moves to `_resolve_file_twins`.
    The requiredness itself is remembered, not dropped.
    """
    twins: dict[str, list[tuple[str, str, bool]]] = {}
    for name, sub in _subcommands(parser).items():
        for action in list(sub._actions):
            if action.dest not in FILE_TWIN_FIELDS or not action.option_strings:
                continue
            if action.nargs == 0:
                # `list --acceptance-manual` is a store_true FILTER that happens to
                # share a dest with a free-text field. Giving it a twin manufactured
                # a flag that can never succeed: its default is `False`, which
                # `is not None`, so the mutual-exclusion branch fired on every call —
                # and `list --help` advertised it with four lines about backticks.
                continue
            long_flags = [o for o in action.option_strings if o.startswith("--")]
            if not long_flags:
                continue
            flag = max(long_flags, key=len)
            sub.add_argument(
                f"{flag}-file", dest=f"{action.dest}_file", metavar="PATH",
                help=f"read {flag}'s value from a file, verbatim (trailing newline "
                     f"dropped). Use this whenever the text may contain a backtick, "
                     f"$ or backslash: argv passes through your shell first, and a "
                     f"backtick there is command substitution — the text is edited "
                     f"before this tool can see it, silently")
            twins.setdefault(name, []).append((action.dest, flag, action.required))
            action.required = False
    parser._kg_file_twins = twins


def _resolve_file_twins(parser: argparse.ArgumentParser, args) -> None:
    """Fold each `--X-file` into `--X`; semantic refusals use the common envelope."""
    for dest, flag, required in getattr(parser, "_kg_file_twins", {}).get(args.command, ()):
        path = getattr(args, f"{dest}_file", None)
        inline = getattr(args, dest, None)
        if path is not None and inline is not None:
            # Not "last one wins" and not "the file wins": either would produce a
            # write whose content is not the content the caller believes they
            # supplied, which is the exact defect the twin exists to remove.
            raise BacklogError(
                f"{flag} and {flag}-file are mutually exclusive — pass the text "
                "or the path, not both; nothing was written"
            )
        if path is not None:
            if dest in REFUSED_BY_COMMAND.get(args.command, ()):
                # The handler refuses this field outright, so reading the file first
                # would report a true statement about the wrong problem: measured,
                # `update --detail-file /no/such/path` blamed the missing file when
                # `detail` can never be written by `update` at all. Mark it present
                # and let the handler's own named refusal fire.
                setattr(args, dest, f"<{flag}-file>")
                continue
            try:
                text = Path(path).read_text(encoding="utf-8")
            except OSError as exc:
                raise BacklogError(
                    f"{flag}-file: {exc}; nothing was written"
                ) from exc
            # Only TRAILING NEWLINES go. Every editor adds one and nobody means it;
            # everything else — interior blank lines, trailing spaces — is delivered
            # as written, which is the entire point of this channel.
            setattr(args, dest, text.rstrip("\n"))
        elif required and inline is None:
            # argparse's own job, kept as argparse's own exit code (2): a missing
            # required flag is a malformed command line, not a refused act.
            _subcommands(parser)[args.command].error(
                f"one of {flag} / {flag}-file is required")
def _lifecycle_contract() -> dict:
    """One machine-readable model for help text, skills and automation."""
    return {
        "schema": "kg.backlog.lifecycle.v1",
        "terminal_statuses": ["fixed", "wont-fix"],
        "dispatch_requirements": list(DISPATCH_CLAUSES),
        "contract_statuses": list(CONTRACT_STATUSES),
        "contract_baselines": list(CONTRACT_BASELINES),
        "contract_blocked": {
            "status": "contract-blocked",
            "verdict": "CONTRACT-BLOCKED",
            "required_fields": ["contract_status", "contract_evidence"],
            "meaning": "the ticket contract is not executable and must not be dispatched",
        },
        "contract_preflight": {
            "guard": "contract_preflight",
            "required_fields": list(CONTRACT_FIELDS),
            "dispatch_values": {"contract_status": "ready", "contract_baseline": "red"},
            "rejects": [
                "fix-site-missing", "acceptance-dependency-missing",
                "contract-baseline-not-red", "contract-evidence-missing",
                "contract-check-metadata-missing",
            ],
        },
        "invariants": [
            "verify checks whether a claim is true; groom makes a ticket executable",
            "verification is orthogonal and never a dispatch prerequisite",
            "dispatch means groomed AND unresolved AND unclaimed AND unblocked AND contract-ready",
            "ownership lives in the worktree registry, never in a stored in-progress status",
            "closed tickets stay closed; recurrence is a new filed occurrence",
        ],
        "acts": [
            {
                "id": "add", "actor": "recorder", "command": "backlog.py add",
                "meaning": "preserve an observed problem as status=open after deduplication",
                "writes_store": True, "write_mode": "immediate-default",
                "required_for_dispatch": True,
            },
            {
                "id": "verify", "actor": "verifier", "command": "backlog.py verify",
                "meaning": "re-derive whether the claim is still true and attach rerunnable evidence",
                "writes_store": True, "write_mode": "dry-run-default",
                "required_for_dispatch": False,
            },
            {
                "id": "groom", "actor": "groomer", "command": "backlog.py groom",
                "meaning": "atomically set triaged plus brief/scope/plan/acceptance/fix_site",
                "writes_store": True, "write_mode": "dry-run-default",
                "required_for_dispatch": True,
            },
            {
                "id": "supersede", "actor": "recorder",
                "command": "backlog.py supersede <id>",
                "meaning": "re-file a corrected immutable payload and retire the eligible source as wont-fix without deleting its audit trail",
                "writes_store": True, "write_mode": "dry-run-default",
                "required_for_dispatch": False,
            },
            {
                "id": "dispatch", "actor": "worker", "command": "backlog.py dispatch",
                "meaning": "read the worst-first takeable queue",
                "writes_store": False, "write_mode": "read-only",
                "required_for_dispatch": False,
                "held_scope": DISPATCH_HELD_SCOPE,
                "snooze_scope": DISPATCH_SNOOZE_SCOPE,
            },
            {
                "id": "claim", "actor": "worker",
                "command": "worktree_orchestrate.py open --backlog <id>",
                "meaning": "claim exclusively in the local worktree registry and begin work",
                "writes_store": False, "write_mode": "registry-write",
                "required_for_dispatch": False,
            },
            {
                "id": "close", "actor": "worker-or-integrator",
                "command": "verify/update or stage/anchor",
                "meaning": "prove the authored acceptance and preserve landing traceability",
                "writes_store": True, "write_mode": "explicit",
                "required_for_dispatch": False,
                "branches": ["single", "wave", "decline"],
                "branch_commands": {
                    "single": "verify --status fixed --fixed-by/--fixed-elsewhere --commit",
                    "wave": "stage -> cutover/resolve stamps landing -> anchor --commit",
                    "decline": "verify the disposition, then update --status wont-fix --resolution <reason> --commit",
                },
            },
        ],
        "scenarios": [
            {
                "id": "fresh-report",
                "path": "dedupe -> add -> groom -> dispatch -> claim -> implement -> close",
            },
            {
                "id": "uncertain-or-stale",
                "path": "verify first; groom only if the claim survives re-verification",
            },
            {
                "id": "reporter-also-verifies",
                "path": "the recorder may also verify when they actually ran rerunnable evidence; roles may share an actor but stamps stay separate",
            },
            {
                "id": "duplicate",
                "path": "verify DUPLICATE-OF-<id> -> update --duplicate-of <id> --status wont-fix with the canonical id and reason",
            },
            {
                "id": "manual-acceptance",
                "path": "groom --acceptance-manual <why>; the exception remains explicitly countable",
            },
            {
                "id": "batch-wave",
                "path": "workers stage evidence; the integrator lands once and anchor closes the wave atomically",
            },
            {
                "id": "recurrence",
                "path": "do not reopen through groom; dedupe and add a new occurrence with its observed date/source so identity is distinct",
            },
            {
                "id": "corrected-filing",
                "path": "supersede an open, unclaimed, unreferenced source with corrected immutable content; keep the source as wont-fix with replacement provenance",
            },
        ],
    }


def _cmd_lifecycle(args) -> int:
    contract = _lifecycle_contract()
    if args.json:
        print(json.dumps(contract, ensure_ascii=False))
        return 0

    print("Ticket lifecycle (roles may share an actor; acts and evidence stay separate):")
    for act in contract["acts"]:
        required = ("required before dispatch" if act["required_for_dispatch"]
                    else "not a dispatch precondition")
        print(f"  {act['id']:<8} {act['actor']:<20} {required}: {act['meaning']}")
    print("Terminal: fixed (proved + traced) / wont-fix (reasoned decline).")
    print("Common scenarios:")
    for scenario in contract["scenarios"]:
        print(f"  {scenario['id']}: {scenario['path']}")
    return 0


def _cmd_add(args) -> int:
    groom_fields = (
        "brief", "scope", "plan", "acceptance", "acceptance_cmd",
        "acceptance_cmd_static", "acceptance_expect_rc", "acceptance_manual",
        "acceptance_green_expected", "fix_site", "groomed_by", "groomed_at",
        "groomed_against", "contract_status", "contract_baseline",
        "contract_checked_at", "contract_checked_by", "contract_evidence",
    )
    # `brief`/`scope` are useful on a plain open filing too; only the executable
    # plan/acceptance/fix or groom/contract stamps opt into the atomic triaged path.
    grooming_trigger_fields = tuple(field for field in groom_fields
                                     if field not in {"brief", "scope"})
    groom_requested = any(getattr(args, field, None) is not None
                          for field in grooming_trigger_fields)
    if args.status != "open" and not (groom_requested and args.status == "triaged"):
        raise BacklogError(
            f"`add` starts a ticket at status=open, not {args.status!r}. "
            "Work out an unresolved ticket with `groom`; close an existing ticket "
            "through `verify --status fixed` / `update --status wont-fix`; ingest "
            "historical terminal rows with `import`"
        )

    groom_extra = {}
    if groom_requested:
        missing = [field for field in
                   ("brief", "scope", "plan", "acceptance", "fix_site", "groomed_by")
                   if not str(getattr(args, field, None) or "").strip()]
        proofs = [field for field in ("acceptance_cmd", "acceptance_manual")
                  if str(getattr(args, field, None) or "").strip()]
        if len(proofs) != 1:
            missing.append("exactly one of --acceptance-cmd/--acceptance-manual")
        args.groomed_at = args.groomed_at or _today()
        if args.groomed_at >= CONTRACT_REQUIRED_SINCE:
            for field in ("contract_status", "contract_baseline",
                          "contract_checked_at", "contract_checked_by",
                          "contract_evidence"):
                if not str(getattr(args, field, None) or "").strip():
                    missing.append(field)
        if missing:
            raise BacklogError(
                "complete add grooming requires: " + ", ".join(missing)
            )
        args.status = "triaged"
        args.groomed_against = args.groomed_against or _main_commit()
        groom_extra = {
            field: getattr(args, field, None)
            for field in groom_fields
            if getattr(args, field, None) not in (None, "")
        }

    if args.queue is not None and not args.stage:
        raise BacklogError("--queue is only valid with `add --stage`")

    commit = not args.dry_run and not args.stage
    outcome: dict = {}
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
        brief=args.brief,
        scope=args.scope,
        surface=args.surface,
        repro=args.repro,
        build=args.build,
        entry_id=args.entry_id,
        extra=groom_extra,
        _outcome=outcome,
        commit=commit,
    )
    claimability = _add_claimability(entry, args.store)
    if args.stage:
        row, queue = _stage_add(args, entry)
        if args.json:
            print(json.dumps({"schema": "kg.backlog.add.v1", "mode": "staged",
                              "written": False, "entry": entry,
                              **claimability,
                              "staged": row, "queue": str(queue)},
                             ensure_ascii=False))
        else:
            print(f"[staged] {entry['id']} [{entry['stream']}/{entry['category']}/"
                  f"{entry['severity']}]\n"
                  f"  queued in {queue} — materializes when the wave runs "
                  f"`./ops/backlog.py anchor --commit`")
        return 0

    mode = "commit" if commit else "dry-run"
    written = bool(outcome["written"])
    if args.json:
        print(json.dumps({"schema": "kg.backlog.add.v1", "mode": mode,
                          "written": written, "entry": entry, **claimability},
                         ensure_ascii=False))
    else:
        print(f"{entry['id']}  [{entry['stream']}/{entry['category']}/{entry['severity']}]")
        print(f"  mode={mode}; written={str(written).lower()}; {entry['detail'][:120]}")
        if commit and not written:
            print("  nothing written; an identical entry already exists")
        elif not commit:
            print("  nothing written; rerun without --dry-run (or pass --commit) to file it")
        if claimability["claimable"]:
            print("  claimable=true; this ticket is in the dispatch queue")
        else:
            missing = ", ".join(claimability["missing"]) or "contract/blocked-by checks"
            print(f"  not in the dispatch queue; missing {missing}")
    return 0


def _add_claimability(entry: dict, store: Path) -> dict:
    """Report the same prerequisites dispatch applies, without claiming anything."""
    missing: list[str] = []
    for field in ("plan", "acceptance", "fix_site", "groomed_by"):
        if not str(entry.get(field) or "").strip():
            missing.append(field)
    if not any(str(entry.get(field) or "").strip()
               for field in ("acceptance_cmd", "acceptance_manual")):
        missing.append("acceptance_cmd_or_manual")
    # Plain open filings are intentionally not contract-checked: they are
    # discoverable board entries, not claims that someone has groomed them.
    contract_claimed = (entry.get("status") == "triaged"
                        or bool(entry.get("groomed_at"))
                        or any(entry.get(field) is not None for field in CONTRACT_FIELDS))
    if contract_claimed:
        for problem in contract_preflight(entry, repo=owning_repo_for_store(store)):
            field = problem.get("field")
            if field:
                missing.append(str(field))
            elif problem.get("kind") == "contract-baseline-not-red":
                missing.append("contract_baseline")
            elif problem.get("kind") == "contract-evidence-missing":
                reason = str(problem.get("reason") or "")
                missing.append("contract_status" if "contract_status" in reason
                               else "contract_evidence")
            elif problem.get("kind") == "acceptance-dependency-missing":
                missing.append("acceptance_cmd_dependency")
            elif problem.get("kind") == "fix-site-missing":
                missing.append("fix_site_dependency")
    return {"claimable": not missing, "missing": list(dict.fromkeys(missing))}


def _closure_changes(*, verdict: str, by: str, evidence: str, at: str | None,
                     status: str | None, fixed_by: list[str] | None,
                     fixed_elsewhere: str | None = None,
                     contract_status: str | None = None,
                     contract_baseline: str | None = None,
                     contract_checked_at: str | None = None,
                     contract_checked_by: str | None = None,
                     contract_evidence: str | None = None) -> dict:
    """The field set that records a re-verification. ONE construction, three doors.

    `verify` writes it now; `stage` validates it on a hunter's branch and parks it;
    `anchor` replays it at wave end. Built here rather than in each, because three
    copies of "what a closure consists of" is three chances for the queue to accept
    something the store would reject — and the queue's rejection would land on the
    integrator closing a batch, not on the hunter who wrote it.
    """
    if not evidence.strip():
        # `required=True` proves the flag was typed, not that it carries a command.
        # An empty string satisfied the ratchet and left the queue.
        raise BacklogError("--evidence must name what you ran; an empty string is not evidence")
    changes = {
        "verdict": verdict,
        "verified_at": at or _today(),
        "verified_by": by,
        # Unconditional. When this was `if evidence:` the field simply kept its old
        # value, so a second verifier's CONFIRMED-FIXED carried the first verifier's
        # command — evidence that re-runs to the wrong verdict, which is worse than
        # none because it looks like it has some.
        "verified_evidence": evidence,
    }
    if status:
        changes["status"] = status
    if fixed_by:
        changes["fixed_by"] = fixed_by
    if fixed_elsewhere:
        # Never set by `stage`/`anchor`: a wave exists precisely because a LANDING
        # COMMIT is coming, and this field says there will never be one. It reaches
        # the store through `verify` and `update` only.
        changes["fixed_elsewhere"] = fixed_elsewhere
    contract_values = {
        "contract_status": contract_status,
        "contract_baseline": contract_baseline,
        "contract_checked_at": contract_checked_at,
        "contract_checked_by": contract_checked_by,
        "contract_evidence": contract_evidence,
    }
    changes.update({field: value for field, value in contract_values.items()
                    if value is not None})
    return changes


def _wave_deps() -> _backlog_wave.WaveDeps:
    """Build wave-queue callbacks while preserving façade monkeypatch points."""
    return _backlog_wave.WaveDeps(
        root=ROOT,
        error_type=BacklogError,
        git=_git,
        current_branch=_current_branch,
        queue_anchor=_queue_anchor,
        queue_path=_queue_path,
        queue_lock=_queue_lock,
        read_queue=read_queue,
        write_queue=write_queue,
        entry_path=entry_path,
        entry_lock=_entry_lock,
        load_entry=load_entry,
        closure_changes=_closure_changes,
        merged_and_validated=_merged_and_validated,
        write_atomic=_write_atomic,
        staged_status=STAGED_STATUS,
    )


def _current_branch() -> str:
    return _backlog_wave.current_branch(deps=_wave_deps())


def _queue_anchor() -> Path:
    return _backlog_wave.queue_anchor(deps=_wave_deps())


def held_tickets(anchor: Path | None = None) -> dict[str, dict]:
    return _backlog_wave.held_tickets(anchor, deps=_wave_deps())


def _queue_path(explicit: Path | None = None) -> Path:
    return _backlog_wave.queue_path(explicit, deps=_wave_deps())


def _queue_lock(queue: Path):
    return _backlog_wave.queue_lock(queue, deps=_wave_deps())


def read_queue(path: Path) -> list[dict]:
    return _backlog_wave.read_queue(path, deps=_wave_deps())


def write_queue(path: Path, rows: list[dict]) -> None:
    return _backlog_wave.write_queue(path, rows, deps=_wave_deps())


def _pending_queue_summary(queue: Path | None = None) -> dict:
    return _backlog_wave.pending_queue_summary(queue, deps=_wave_deps())


def _stage_add(args, entry: dict) -> tuple[dict, Path]:
    return _backlog_wave.stage_add(args, entry, deps=_wave_deps())


def _cmd_stage(args) -> int:
    return _backlog_wave.cmd_stage(args, deps=_wave_deps())


def _cmd_unstage(args) -> int:
    return _backlog_wave.cmd_unstage(args, deps=_wave_deps())


def _anchor_deps() -> _backlog_wave.AnchorDeps:
    """Build anchor callbacks while preserving façade monkeypatch points."""
    return _backlog_wave.AnchorDeps(
        error_type=BacklogError,
        staged_status=STAGED_STATUS,
        queue_path=_queue_path,
        queue_lock=_queue_lock,
        read_queue=read_queue,
        write_queue=write_queue,
        entry_path=entry_path,
        entry_lock=_entry_lock,
        load_entry=load_entry,
        validate_entry=validate_entry,
        closure_changes=_closure_changes,
        merged_and_validated=_merged_and_validated,
        acceptance_gate=_acceptance_gate,
        acceptance_refusal=_acceptance_refusal,
        write_atomic=_write_atomic,
        dumps=_dumps,
    )


def _cmd_anchor(args) -> int:
    return _backlog_wave.cmd_anchor(args, deps=_anchor_deps())


def _execute_criterion(entry_id: str, cmd: str, timeout_seconds: float,
                       progress_prefix: str) -> tuple[int | None, str, float]:
    return _backlog_acceptance.execute_criterion(
        entry_id,
        cmd,
        timeout_seconds,
        progress_prefix,
        deps=_backlog_acceptance.AcceptanceDeps(
            root=ROOT,
            run_streamed_command=run_streamed_command,
        ),
    )


def _trace_failed_clause(entry_id: str, cmd: str, timeout_seconds: float,
                         progress_prefix: str) -> str:
    return _backlog_acceptance.trace_failed_clause(
        entry_id,
        cmd,
        timeout_seconds,
        progress_prefix,
        deps=_backlog_acceptance.AcceptanceDeps(
            root=ROOT,
            run_streamed_command=run_streamed_command,
        ),
    )


def _run_acceptance(entry_id: str, cmd: str, expect_rc: int) -> dict:
    return _backlog_acceptance.run_acceptance(
        entry_id,
        cmd,
        expect_rc,
        deps=_acceptance_deps(),
    )


def _run_static_acceptance(entry_id: str, cmd: str) -> dict:
    return _backlog_acceptance.run_static_acceptance(
        entry_id,
        cmd,
        deps=_acceptance_deps(),
    )


def _acceptance_gate(entry: dict, commit: bool) -> dict:
    return _backlog_acceptance.acceptance_gate(
        entry,
        commit,
        deps=_acceptance_deps(),
    )


def _acceptance_refusal(result: dict) -> str:
    return _backlog_acceptance.acceptance_refusal(result)


# ---------------------------------------------------------------------------
# audit-criteria — run the criteria of entries that say they are NOT fixed
#
# The gate above asks a criterion "is the defect gone?" at the moment somebody
# closes an entry. This asks the same criterion the same question while the entry
# is still OPEN, where the expected answer is no. A yes has two readings and both
# are bad: the entry is already fixed and will be dispatched again (a zombie), or
# the criterion does not test what its prose claims — and that one is worse,
# because `_acceptance_gate` runs this exact command at closing time and would let
# the closure through. Confirmed case at the top of section 28 of the tests.
# ---------------------------------------------------------------------------

# Per entry, and DERIVED from the gate's budget rather than restated: the comment
# below argues about the ratio, so the ratio is what the code should contain. The
# gate runs ONE command with a human waiting on that one answer; this runs every
# unresolved entry's command in series — 81 of them today — so the gate's budget
# would put a 20-hour ceiling on a sweep somebody is supposed to run before triage.
# The cost of the smaller number is named rather than hidden: a criterion that needs
# longer lands in `timeout`, which is a reported bucket and not a verdict.
def _looks_like_pytest_command(cmd: str) -> bool:
    return _backlog_acceptance.looks_like_pytest_command(cmd)


def _criterion_unrunnable_reason(cmd: str, rc: int) -> str | None:
    return _backlog_acceptance.criterion_unrunnable_reason(cmd, rc)

def _audit_population(store: Path) -> list[dict]:
    return _backlog_acceptance.audit_population(store, deps=_acceptance_deps())


def _audit_row(entry: dict, **extra) -> dict:
    return _backlog_acceptance.audit_row(entry, **extra)


def _audit_unrunnable(entry: dict) -> str | None:
    return _backlog_acceptance.audit_unrunnable(entry, deps=_acceptance_deps())


def _audit_one(entry: dict, timeout_seconds: float) -> tuple[str, dict]:
    return _backlog_acceptance.audit_one(
        entry,
        timeout_seconds,
        deps=_acceptance_deps(),
    )


def _cmd_audit_criteria(args) -> int:
    if args.limit is not None and args.limit < 1:
        raise BacklogError("--limit must be at least 1")
    if args.timeout_seconds <= 0:
        raise BacklogError("--timeout-seconds must be positive")
    if args.all and (args.filter or args.limit is not None):
        # `--filter` alone already runs every match, so `--all` beside either of
        # them is not "extra" — it is a second, contradictory statement about the
        # same question. Refused by name rather than silently letting one win.
        raise BacklogError(
            "--all means NO narrowing, so it contradicts --filter / --limit. "
            "`--filter` on its own already runs every entry it matches.")
    try:
        pattern = re.compile(args.filter, re.IGNORECASE) if args.filter else None
    except re.error as exc:
        # Same reason as `--grep`: an unguarded compile turns a typo'd bracket into
        # a traceback about `sre_parse`, a true statement about the wrong subject.
        raise BacklogError(f"--filter 不是合法的正規表示式: {exc}") from exc

    entries = _audit_population(args.store)
    if not (args.filter or args.limit is not None or args.all or args.dry_run):
        # A bare invocation would execute every stored command on this machine, and
        # the store's own contents are the argument: today's population includes a
        # `curl` at another host, an `ios_ops.sh catalog` that drives a simulator,
        # and several infra probes. None of that is inferable from the flag list, so
        # the default is a REFUSAL that names the size and the four ways forward
        # rather than a sweep somebody did not know they were starting.
        raise BacklogError(
            f"refusing to run all {len(entries)} stored commands without being asked "
            f"to. This subcommand EXECUTES `acceptance_cmd` out of the ledger, and "
            f"some of those open a simulator, start containers or call the network.\n"
            f"  see what would run:  ./ops/backlog.py audit-criteria --dry-run\n"
            f"  pick some:           ./ops/backlog.py audit-criteria --filter <regex>\n"
            f"  take the worst N:    ./ops/backlog.py audit-criteria --limit 10\n"
            f"  yes, run everything: ./ops/backlog.py audit-criteria --all")
    if pattern is not None:
        # Two subjects, searched SEPARATELY rather than joined: an id and a command
        # concatenated would let a pattern match across the seam, which is how
        # `--grep` first shipped a phrase no field contained.
        entries = [p for p in entries
                   if pattern.search(str(p.get("id") or ""))
                   or pattern.search(str(p.get("acceptance_cmd") or ""))]
    selected = len(entries)

    buckets: dict[str, list[dict]] = {k: [] for k in
                                      ("green", "red", "error", "timeout",
                                       "exempt", "manual", "unproven")}
    runnable: list[dict] = []
    for entry in entries:
        cmd = str(entry.get("acceptance_cmd") or "").strip()
        exemption = str(entry.get(ACCEPTANCE_GREEN_EXPECTED) or "").strip()
        manual = str(entry.get("acceptance_manual") or "").strip()
        unrunnable = _audit_unrunnable(entry) if cmd else None
        if not cmd:
            buckets["manual" if manual else "unproven"].append(
                _audit_row(entry, **({"reason": manual} if manual else {})))
        elif exemption:
            # Listed, NOT run. The bucket is a set of declarations and saying so is
            # what stops it being read as a measurement — and this command executes
            # free text, so declining to run what somebody has already declared
            # uninformative is the cheap half of the safety argument too.
            buckets["exempt"].append(
                _audit_row(entry, cmd=cmd, reason=exemption, ran=False))
        elif unrunnable:
            # Decided HERE rather than inside the run loop, so `--limit N` means N
            # executions: a slice taken before this check spends its slots on
            # commands that were never going to run.
            buckets["error"].append(
                _audit_row(entry, cmd=cmd,
                           expect_rc=int(entry.get("acceptance_expect_rc") or 0),
                           rc=None, reason=unrunnable, elapsed_s=0.0,
                           output_tail="", failing_clause=""))
        else:
            runnable.append(entry)

    skipped = [p["id"] for p in runnable[args.limit:]] if args.limit is not None else []
    runnable = runnable[:args.limit] if args.limit is not None else runnable

    total = len(runnable)
    if not args.dry_run:
        for index, entry in enumerate(runnable, start=1):
            bucket, row = _audit_one(entry, args.timeout_seconds)
            buckets[bucket].append(row)
            # Position in the sweep, which `run_streamed_command` cannot know.
            # Without it a 30-minute run gives the operator no way to tell "slow"
            # from "stuck".
            print(f"[backlog][audit] {index}/{total} entry={entry['id']} "
                  f"bucket={bucket}", file=sys.stderr, flush=True)

    payload = {
        "schema": "kg.backlog.audit-criteria.v1",
        "population": AUDIT_POPULATION,
        "caveat": AUDIT_CAVEAT,
        "timeout_seconds": args.timeout_seconds,
        "selected": selected,
        # UNCONDITIONAL, both values. A dry run's empty `green` is byte-identical to
        # a clean sweep's, so a machine reader with no flag to look at would read
        # "nothing suspicious" off a run that measured nothing.
        "dry_run": bool(args.dry_run),
        "ran": 0 if args.dry_run else total,
        "would_run": [_audit_row(p, cmd=str(p.get("acceptance_cmd") or "").strip())
                      for p in runnable] if args.dry_run else [],
        # NAMED, not counted. A truncated sweep whose gaps are a number reads as a
        # clean bill of health for entries nobody looked at.
        "skipped_by_limit": skipped,
        **buckets,
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False))
        return 0

    if args.dry_run:
        print(f"would run {total} command(s), in this order:")
        for index, entry in enumerate(runnable, start=1):
            print(f"  {index:>3}. {entry['id']:<24} "
                  f"{str(entry.get('acceptance_cmd') or '')[:110]}")
    for name in ("green", "error", "timeout", "red", "exempt", "manual", "unproven"):
        rows = buckets[name]
        print(f"\n{name} ({len(rows)})")
        for row in rows:
            extra = row.get("reason") or f"rc={row.get('rc')} expected={row.get('expect_rc')}"
            print(f"  {row['id']:<24} {extra:<34} {row['detail'][:60]}")
            if row.get("failing_clause"):
                print(f"    failing_clause: {row['failing_clause']}")
    print(f"\n{selected} selected ({AUDIT_POPULATION}), "
          f"{0 if args.dry_run else total} run"
          + (" (DRY RUN — nothing was executed, so every bucket above is empty for "
             "that reason and not for a clean one)" if args.dry_run else "")
          + (f", {len(skipped)} left unrun by --limit: {', '.join(skipped)}"
             if skipped else ""))
    print(f"  {AUDIT_CAVEAT}")
    # Exit 0 even with suspects. This is a report a human triages, and a report that
    # reds somebody's shell is a report that acquires a `|| true`.
    return 0


def _gate_closure(entry: dict, changes: dict, commit: bool) -> dict | None:
    """Run the acceptance gate iff this write is an act of closing.

    Keyed on `status` appearing in the changes and landing on `fixed`, not on the
    resulting entry being fixed. Otherwise every later correction to a closed entry
    — a reworded resolution, a `fixed_by` re-pointed after a rebase — would re-run a
    full pytest suite, and `reanchor`'s repair loop would become unusable.
    """
    if changes.get("status") != "fixed":
        return None
    if str(changes.get("acceptance_cmd") or "").strip():
        # Rewriting the criterion in the same act that closes on it makes the gate
        # satisfiable by its own input: measured, `update <id> --status fixed
        # --acceptance-cmd true` replaced a red criterion, ran the replacement, and
        # the store recorded the closure as machine-proved. Two acts, in this order,
        # or none.
        raise BacklogError(
            "refusing to close and rewrite the acceptance in one act: the gate would "
            "be checking the command you supplied with the closure, not the one the "
            "entry stood on.\n"
            "  change the criterion first:  ./ops/backlog.py update <id> "
            "--acceptance-cmd '<cmd>' --commit\n"
            "  then close:                  ./ops/backlog.py update <id> --status "
            "fixed --fixed-by <sha> --commit")
    # `entry`, NOT `{**entry, **changes}` — the criterion is whatever was already
    # stored. HONEST NOTE: with the refusal above in place these two readings are no
    # longer distinguishable from outside (the refusal removes the only call in which
    # `changes` can carry an `acceptance_cmd`), so swapping this line back does not
    # red the suite. The refusal is the load-bearing guard; this line is written the
    # correct way round so that a future caller passing a criterion in `changes`
    # cannot resurrect the hole by removing one guard.
    result = _acceptance_gate(entry, commit)
    if result["kind"] == "failed":
        raise BacklogError(_acceptance_refusal(result))
    return result


def _verification_deps() -> _backlog_verification.VerificationDeps:
    """Build verification callbacks while preserving façade monkeypatch points."""
    return _backlog_verification.VerificationDeps(
        load_entry=load_entry,
        closure_changes=_closure_changes,
        merged_and_validated=_merged_and_validated,
        gate_closure=_gate_closure,
        check_acceptance_cmd=_check_acceptance_cmd,
        run_static_acceptance=_run_static_acceptance,
        entry_path=entry_path,
        write_atomic=_write_atomic,
        dumps=_dumps,
        error_type=BacklogError,
        entry_lock=_entry_lock,
        acceptance_lock=_entry_acceptance_lock,
        static_command=lambda verify_args: _cmd_verify_static(verify_args),
    )


def _cmd_verify_static(args) -> int:
    """Compatibility façade for the extracted static verification command."""
    return _backlog_verification.cmd_verify_static(
        args, deps=_verification_deps()
    )


def _cmd_verify(args, *, _lock_held: bool = False) -> int:
    """Compatibility façade for the extracted verification command."""
    return _backlog_verification.cmd_verify(
        args, deps=_verification_deps(), lock_held=_lock_held
    )


# What the dispatch queue is, and — the half that matters — what it cannot see.
# Both blind spots are structural, neither is fixable here, and a queue that does
# not say so is worse than one that does: the caller has no other way to learn it,
# and the failure it produces (taking a ticket somebody already holds, or one the
# board deferred) looks like the caller's mistake.
#
# `snooze` deliberately stays out of scope rather than being read from a hard-coded
# path: the overlay lives outside this repo AND outside `~/butler`, and a tool that
# reaches into a machine-local path to answer a question it advertises would be
# right on one machine and silently wrong everywhere else. If it is ever wired in,
# it goes through an explicit `--overlay PATH`.
DISPATCH_CLAUSES = ("groomed", "unresolved", "unclaimed", "unblocked", "contract-ready")
DISPATCH_HELD_SCOPE = (
    "claims are derived from THIS machine's worktree ledger (gitignored, "
    "per-machine). Another machine's claims are invisible, so across machines this "
    "queue is OPTIMISTIC — it can offer an id somebody is already holding."
)
DISPATCH_SNOOZE_SCOPE = (
    "board deferrals are NOT applied: snooze lives in the board's overlay "
    "(~/kg-board-state/overlay.json), outside this repo on purpose, so a snoozed "
    "entry is still offered here."
)


def owning_repo_for_store(store: Path) -> Path:
    """Resolve the checkout that owns a canonical ``docs/runbook/backlog`` store."""
    path = Path(store).resolve()
    if path.parts[-3:] == ("docs", "runbook", "backlog"):
        return path.parents[2]
    # Legacy/tests may use a scratch store with no repository-shaped parent. Keep
    # the historical root for those rows; canonical external stores use the branch
    # above and therefore receive their own dependency context.
    return ROOT


def _withheld_blocked(store: Path, candidates: list[dict], held: dict) -> list[dict]:
    """Describe entries removed only by the derived `unblocked` clause."""
    open_ids = {p.get("id") for p in _iter_entries(store)
                if p.get("status") not in ("fixed", "wont-fix")}
    withheld = []
    for payload in candidates:
        if (str(payload.get("groomed_by") or "").strip()
                and payload.get("status") not in ("fixed", "wont-fix")
                and payload.get("id") not in held):
            waiting_on = [blocker for blocker in _blocking_ids(payload)
                          if blocker in open_ids]
            if waiting_on:
                withheld.append({"id": payload.get("id"), "waiting_on": waiting_on})
    return sorted(withheld, key=lambda row: row["id"])


def _withheld_contract(
    store: Path,
    candidates: list[dict],
    held: dict,
    blocked_ids: set[str],
) -> list[dict]:
    """Expose the canonical preflight partition beside the dispatch queue.

    The board must not recreate ``contract_preflight`` from a subset of fields.
    Keep this read-only compiler beside the existing blocked metadata so every
    consumer can distinguish contract debt from the canonical grooming queue.
    """
    repo = owning_repo_for_store(store)
    withheld = []
    for payload in candidates:
        ticket_id = str(payload.get("id") or "")
        if (not str(payload.get("groomed_by") or "").strip()
                or payload.get("status") in ("fixed", "wont-fix")
                or ticket_id in held
                or ticket_id in blocked_ids):
            continue
        problems = contract_preflight(payload, repo=repo)
        if problems:
            withheld.append({"id": ticket_id, "problems": problems})
    return sorted(withheld, key=lambda row: row["id"])


def _groomed_against_warning_line(warning: dict) -> str:
    return (
        f"⚠ groomed_against stale: {warning['id']} snapshot is "
        f"{warning['commits_behind']} commits behind main "
        f"(threshold {warning['threshold']}); re-check the plan before starting."
    )


def _cmd_list(args) -> int:
    if getattr(args, "zombie_suspects", False):
        filters = (
            "status", "stream", "severity", "category", "ungroomed",
            "include_closed", "groomed", "held", "dispatch", "acceptance_manual",
            "acceptance_green_expected", "fixed_elsewhere", "missing_brief",
            "unverified", "stale", "groom_stale_days", "grep",
        )
        if any(
            (getattr(args, name, None) is not None
             if name == "groom_stale_days"
             else bool(getattr(args, name, None)))
            for name in filters
        ):
            raise BacklogError(
                "--zombie-suspects is a standalone query; drop the other list "
                "filters and keep only --store/--json/--zombie-search-depth"
            )
        effective_depth = (args.zombie_search_depth
                           if args.zombie_search_depth is not None
                           else DEFAULT_SEARCH_DEPTH)
        rows = zombie_suspects(
            args.store,
            repo=owning_repo_for_store(args.store),
            search_depth=effective_depth,
        )
        if args.json:
            print(json.dumps({
                "schema": "kg.backlog.zombie-suspects.v1",
                "entries": rows,
                "search_depth": effective_depth,
                "candidate_only": True,
            }, ensure_ascii=False))
            return 0
        for row in rows:
            print(
                f"{row['id']:<24} {row['status']:<10} "
                f"[{row['classification']}] {row['brief']}"
            )
            print(f"  commit {row['commit']['sha']} {row['commit']['subject']}")
        print(
            f"\n{len(rows)} zombie-suspect candidate(s); mentions are not "
            "acceptance evidence and no status was changed."
        )
        return 0

    if getattr(args, "zombie_search_depth", None) is not None:
        raise BacklogError(
            "--zombie-search-depth only applies with --zombie-suspects"
        )

    dispatch = getattr(args, "dispatch", False) or args.command == "dispatch"
    # DERIVED, never stored — see `held_tickets()`. The stored `in-progress` this
    # replaces had no writer on the release path, so it could only ever accumulate.
    # Read ONCE and threaded into the filter, so the column and the queue cannot
    # disagree about a claim taken between two reads.
    held = held_tickets()
    if dispatch and getattr(args, "held", False):
        # Empty by construction — dispatch is exactly the UNCLAIMED set. Refused
        # here rather than in `list_entries` because `--held` is a CLI-level filter
        # that never reaches it. See the sibling refusals there.
        raise BacklogError(
            "--held and --dispatch are empty by construction: --dispatch only ever "
            "contains UNCLAIMED entries. Drop one — `--dispatch` for what to take "
            "next, `--held` on its own to see who is on what.")

    selection = {
        "unverified": getattr(args, "unverified", False),
        "stale_days": args.stale_days if getattr(args, "stale", False) else None,
        "status": args.status,
        "stream": args.stream,
        "severity": args.severity,
        "category": args.category,
        "groomed": args.groomed,
        "ungroomed": args.ungroomed,
        "groom_stale_days": getattr(args, "groom_stale_days", None),
        "include_closed": getattr(args, "include_closed", False),
        "acceptance_manual": args.acceptance_manual,
        "acceptance_green_expected": getattr(args, "acceptance_green_expected", False),
        "fixed_elsewhere": getattr(args, "fixed_elsewhere", False),
        "missing_brief": getattr(args, "missing_brief", False),
        "grep": getattr(args, "grep", None),
        "dispatch": dispatch,
        "held": held,
        "repo": owning_repo_for_store(args.store),
    }
    entries = select_entries(args.store, **selection)
    withheld_blocked = []
    withheld_contract = []
    if dispatch:
        unfiltered = {**selection, "dispatch": False}
        candidates = select_entries(args.store, **unfiltered)
        withheld_blocked = _withheld_blocked(args.store, candidates, held)
        withheld_contract = _withheld_contract(
            args.store,
            candidates,
            held,
            {row["id"] for row in withheld_blocked},
        )
    if getattr(args, "held", False):
        entries = [e for e in entries if e["id"] in held]
    groomed_against_warnings = _groomed_against_warnings(
        entries, max_commits=args.groomed_against_max_commits,
    )
    staged_queue = _pending_queue_summary()

    if args.json:
        print(json.dumps({"schema": "kg.backlog.list.v1", "entries": entries,
                          # Alongside the entries rather than merged into them: it is
                          # a fact about THIS machine's worktrees, not about the
                          # ledger, and folding it into the entry would let a caller
                          # persist it back as if the store owned it.
                          "held": held, "held_scope": "this machine's worktrees only",
                          **({"dispatch": {"clauses": list(DISPATCH_CLAUSES),
                                           "held_scope": DISPATCH_HELD_SCOPE,
                                           "snooze_scope": DISPATCH_SNOOZE_SCOPE,
                                           "withheld_blocked": withheld_blocked,
                                           "withheld_contract": withheld_contract}}
                           if dispatch else {}),
                          "groomed_against_warnings": groomed_against_warnings,
                          "staged_queue": staged_queue,
                          },
                         ensure_ascii=False))
        return 0
    for entry in entries:
        claim = held.get(entry["id"])
        mark = f"[{claim['branch']}]" if claim else ""
        print(
            f"{entry['id']:<24} {entry['status']:<10} {entry['severity']:<5} "
            f"{entry['category']:<12} {mark:<26} {entry['detail'][:50]}"
        )
    for warning in groomed_against_warnings:
        print(_groomed_against_warning_line(warning))
    if dispatch:
        print(f"\n{len(entries)} takeable ({' AND '.join(DISPATCH_CLAUSES)}), "
              f"worst first. Claim one with "
              f"`./ops/worktree_orchestrate.py open --backlog <id>`.")
        print(f"  scope: {DISPATCH_HELD_SCOPE}")
        print(f"  scope: {DISPATCH_SNOOZE_SCOPE}")
        for withheld in withheld_blocked:
            waiting_on = ", ".join(withheld["waiting_on"])
            print(f"  withheld (blocked): {withheld['id']} waiting on {waiting_on}")
        for withheld in withheld_contract:
            kinds = ", ".join(sorted({str(problem.get("kind")) for problem in withheld["problems"]}))
            print(f"  withheld (contract): {withheld['id']} {kinds}")
        return 0
    queue_note = (
        f"{staged_queue.get('staged_adds', 0)} staged add(s) pending anchor in "
        f"{staged_queue['queue']}"
        if "error" not in staged_queue
        else f"staged queue unreadable: {staged_queue['error']}"
    )
    print(f"\n{len(entries)} entries; {len(held)} ticket(s) claimed by a worktree "
          f"ON THIS MACHINE (the ledger is per-machine — elsewhere this column is "
          f"empty even when someone is working); {queue_note}")
    return 0


def _cmd_show(args) -> int:
    entry = load_entry(args.store, args.id)  # EntryNotFound -> refusal in main()
    # The one question an agent about to pick this up actually has, and the reason
    # it is answered HERE rather than stored on the entry: `show` is where somebody
    # decides to start, and a claim read at that moment is current by construction.
    claim = held_tickets().get(args.id)
    groomed_against_warning = _groomed_against_warning(
        entry, max_commits=args.groomed_against_max_commits,
    )
    if args.json:
        print(json.dumps({"schema": "kg.backlog.show.v1", "entry": entry,
                          "held": claim,
                          "held_scope": "this machine's worktrees only",
                          **({"groomed_against_warning": groomed_against_warning}
                             if groomed_against_warning else {})},
                         ensure_ascii=False))
        return 0
    if claim:
        print(f"⚠ claimed by {claim['branch']} since {claim['claimed_at']} "
              f"({claim['path']}) — this machine's ledger only\n")
    if groomed_against_warning:
        print(_groomed_against_warning_line(groomed_against_warning))
    for field in SHOW_FIELD_ORDER:
        if field in entry and field != "schema":
            print(f"{field:<12} {entry[field]}")
    return 0


def _preflight_active_files(
    repo: Path, *, exclude_ticket: str | None = None, state_path: Path | None = None,
) -> set[str]:
    """Read active worktree diffs for the read-only preflight command."""
    try:
        import worktree_registry as registry
        state = registry.load_state(state_path or registry.default_state_path())
    except (ImportError, OSError, ValueError, KeyError) as exc:
        raise RuntimeError(f"active registry unreadable: {exc}") from exc
    changed: set[str] = set()
    for record in state.get("records") or []:
        if not isinstance(record, dict) or record.get("status") != registry.STATUS_ACTIVE:
            continue
        if exclude_ticket and exclude_ticket in (record.get("backlog") or []):
            continue
        worktree = Path(str(record.get("path") or ""))
        if not worktree.is_dir():
            raise RuntimeError(f"active worktree missing: {worktree}")
        for command in (
            ("diff", "--name-only"),
            ("diff", "--name-only", "--cached"),
            ("ls-files", "--others", "--exclude-standard"),
        ):
            probe = _git(*command, repo=worktree)
            if probe.returncode != 0:
                raise RuntimeError(f"active worktree probe failed: {worktree} ({command!r})")
            changed.update(line.strip() for line in probe.stdout.splitlines() if line.strip())
        branch = str(record.get("branch") or "")
        base = str(record.get("base") or "main")
        if branch:
            probe = _git("diff", "--name-only", f"{base}...{branch}", repo=repo)
            if probe.returncode != 0:
                raise RuntimeError(f"active branch probe failed: {branch}")
            changed.update(line.strip() for line in probe.stdout.splitlines() if line.strip())
    return changed


def _cmd_preflight(args) -> int:
    """Compile a ticket's claim readiness without writing any control-plane state."""
    entry = load_entry(args.store, args.id)
    repo = owning_repo_for_store(args.store)
    unresolved = {
        str(candidate.get("id")) for candidate in _iter_entries(args.store)
        if candidate.get("status") not in ("fixed", "wont-fix")
    }
    contract = contract_preflight(entry, repo=repo)
    try:
        active_files = _preflight_active_files(
            repo, exclude_ticket=args.id, state_path=args.state,
        )
    except RuntimeError as exc:
        contract.append({"kind": "preflight-read-failed", "reason": str(exc)})
        active_files = set()
    result = dispatch_preflight.compile_static(
        entry,
        repo=repo,
        contract_problems=contract,
        unresolved_blockers=[
            blocker for blocker in _blocking_ids(entry) if blocker in unresolved
        ],
        active_files=active_files,
    )
    if args.probe_acceptance:
        command = str(entry.get("acceptance_cmd") or "").strip()
        if not command:
            raise BacklogError("--probe-acceptance requires acceptance_cmd")
        outcome = _run_acceptance(
            entry.get("id", args.id), command,
            int(entry.get("acceptance_expect_rc") or 0),
        )
        result = dispatch_preflight.with_probe(
            result,
            returncode=outcome["rc"] if outcome["rc"] is not None else 124,
            expected_returncode=outcome["expect_rc"],
            stderr=outcome.get("output_tail", ""),
        )
    payload = result.to_dict()
    if args.json:
        print(json.dumps(payload, ensure_ascii=False))
    else:
        print(f"{payload['ticket_id']}: {payload['classification']}")
        for problem in payload["problems"]:
            print(f"  {problem}")
        for hint in payload["repair_hints"]:
            print(f"  repair: {hint}")
    return 0 if result.ok else 1


def _patch_id(rev: str, repo: Path | None = None) -> str | None:
    """Compatibility façade for the extracted patch-id helper."""
    return _backlog_reanchor.patch_id(rev, repo, deps=_reanchor_deps())


def _reanchor_deps() -> _backlog_reanchor.ReanchorDeps:
    """Build reanchor callbacks while preserving façade monkeypatch points."""
    return _backlog_reanchor.ReanchorDeps(
        default_repo=GIT_REPO,
        sha_pattern=_SHA_RE,
        doc_anchor_pattern=_DOC_VERIFIED_AGAINST_RE,
        git=_git,
        patch_id_runner=_backlog_reanchor._default_patch_id_runner,
        make_commit_state=make_commit_state,
        iter_entries=_iter_entries,
        entry_path=entry_path,
        update_entry=update_entry,
        write_atomic=_write_atomic,
        reanchor_store=lambda *args, **kwargs: reanchor_store(*args, **kwargs),
        error_type=BacklogError,
    )


def reanchor_store(store: Path, ids: list[str] | None = None, *,
                   search_depth: int = DEFAULT_SEARCH_DEPTH,
                   repo: Path | None = None, docs: bool = False) -> dict:
    """Compatibility façade for the extracted reanchor planner."""
    return _backlog_reanchor.reanchor_store(
        store, ids, search_depth=search_depth, repo=repo, docs=docs,
        deps=_reanchor_deps(),
    )


def _cmd_reanchor(args) -> int:
    """Compatibility façade for the extracted reanchor transaction."""
    return _backlog_reanchor.cmd_reanchor(args, deps=_reanchor_deps())


def _cmd_validate(args) -> int:
    problems = validate_store(args.store, repo=getattr(args, "repo", None))
    staged_queue = _pending_queue_summary()

    current = closed_without_verification(args.store)
    if getattr(args, "baseline", False):
        # Regenerating a watermark from a store whose schema never validated
        # bakes today's breakage into the forgiven set. Measured in a non-git
        # tree: `commit-state-unavailable` was raised and then discarded by the
        # `return 0` below, so the ratchet re-cut itself in exactly the state
        # the new signal exists to refuse.
        blocking = [p for p in problems
                    if p.get("kind") != "closed-without-verification-above-baseline"]
        if blocking:
            for problem in blocking:
                print(f"ERROR {problem.get('path', '')} — {problem['kind']} {problem}")
            print(f"refusing to rewrite the baseline over {len(blocking)} unresolved problem(s)")
            return 2
        _baseline_path().write_text(
            "# entries closed with no attributable verification (verified_at + verified_by).\n"
            "# Ratchet: this set may shrink, never grow. Regenerate with\n"
            "#   ./ops/backlog.py validate --baseline\n"
            + "\n".join(current) + "\n", encoding="utf-8")
        print(f"wrote {_baseline_path()} ({len(current)} entries)")
        return 0
    if getattr(args, "baseline_check", False):
        id_drift_path = _id_drift_baseline_path(Path(args.store))
        id_drift_pairs, baseline_problems = (
            _read_id_drift_baseline(id_drift_path)
            if id_drift_path is not None else ({}, [])
        )
        problems.extend(baseline_problems)
        drift_by_id = {
            str(problem.get("id")): str(problem.get("expected_id"))
            for problem in problems
            if problem.get("kind") == "id-content-drift"
        }
        exact_pairs = set(id_drift_pairs.items())
        problems = [
            problem for problem in problems
            if problem.get("kind") != "id-content-drift"
            or (str(problem.get("id")), str(problem.get("expected_id")))
            not in exact_pairs
        ]
        for entry_id, expected_id in sorted(id_drift_pairs.items()):
            if drift_by_id.get(entry_id) != expected_id:
                problems.append({
                    "kind": "stale-id-content-drift-baseline",
                    "id": entry_id,
                    "expected_id": expected_id,
                    "current_expected_id": drift_by_id.get(entry_id),
                    "path": str(Path(args.store) / f"{entry_id}.json"),
                })
        allowed = _read_baseline(_baseline_path())
        for entry_id in current:
            if entry_id not in allowed:
                # Closing without verifying is the act this blocks. The debt that
                # already exists is grandfathered by the baseline file — the same
                # trade `ops/i18n_lint.sh --baseline-check` makes, and the reason
                # "the only alternative is 60 red entries" was never true.
                problems.append({"kind": "closed-without-verification-above-baseline",
                                 "id": entry_id, "path": str(Path(args.store) / f"{entry_id}.json")})
    if args.json:
        print(
            json.dumps(
                # Queue state is local scratch, not a validation problem, but its
                # count is part of the command's discoverability contract.
                {"schema": "kg.backlog.validate.v1", "problems": problems,
                 "ok": not problems, "staged_queue": staged_queue},
                ensure_ascii=False,
            )
        )
    else:
        for problem in problems:
            print(f"ERROR {problem.get('path', '')} — {problem['kind']} {problem}")
        if "error" in staged_queue:
            queue_note = f"staged queue unreadable: {staged_queue['error']}"
        else:
            queue_note = (f"{staged_queue['staged_adds']} staged add(s) pending anchor "
                          f"in {staged_queue['queue']}")
        print(f"{len(problems)} problems; {queue_note}")
    return 2 if problems else 0


def _mutation_deps() -> _backlog_mutations.MutationDeps:
    """Build mutation callbacks while preserving façade monkeypatch points."""
    return _backlog_mutations.MutationDeps(
        root=ROOT,
        load_entry=load_entry,
        merged_and_validated=_merged_and_validated,
        gate_closure=_gate_closure,
        update_entry=update_entry,
        mutable_fields=MUTABLE_FIELDS,
        refused_update_fields=REFUSED_UPDATE_FIELDS,
        digest_fields=DIGEST_FIELDS,
        error_type=BacklogError,
        entry_path=entry_path,
        entry_lock=_entry_lock,
        acceptance_lock=_entry_acceptance_lock,
        held_tickets=held_tickets,
        main_commit=_main_commit,
        git=_git,
        today=_today,
        report_pytest_selector_count=_report_pytest_selector_count,
        update_command=lambda update_args, lock_held=False: _cmd_update(
            update_args, _lock_held=lock_held
        ),
    )


def _cmd_groom(args, *, _lock_held: bool = False) -> int:
    """Compatibility façade for the extracted grooming command."""
    return _backlog_mutations.cmd_groom(
        args, deps=_mutation_deps(), lock_held=_lock_held
    )


def _cmd_update(args, *, _lock_held: bool = False) -> int:
    """Compatibility façade for the extracted mutation command."""
    return _backlog_mutations.cmd_update(
        args, deps=_mutation_deps(), lock_held=_lock_held
    )


def _cmd_supersede(args) -> int:
    result = _supersede_transaction(
        args.store,
        args.id,
        stream=args.stream,
        date=args.date,
        source=args.source,
        detail=args.detail,
        commit=args.commit,
    )
    if args.json:
        print(json.dumps(result, ensure_ascii=False))
    else:
        print(
            f"[{result['mode']}] {result['source_id']} -> "
            f"{result['replacement_id']}; written={str(result['written']).lower()}"
        )
        if not result["written"]:
            print("  nothing written; pass --commit to land")
    return 0


def _doc_anchor() -> str:
    """Resolve `verified_against` for the generated view.

    Anchored on the merge-base with **origin/main**, not on HEAD and not on
    local main. Three separate ways to get this wrong, all of them silent, all
    of them hit here:

      * HEAD — rewriting the branch's commits or squash-merging orphans every
        sha the branch minted, and docs_lint then
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

    docs_lint's FIRST layer checks reachability from HEAD, which every one of
    those wrong answers satisfies. Since IMP-20260805-9bb2d2 it also has a
    second layer that checks reachability from $ORIGIN_REF (default
    origin/main) — but that one is a WARN carrying the token
    `origin-unreachable`, deliberately not an ERROR, because a worktree
    anchoring at its own pre-cutover commit is a legitimate state. So the
    downstream reader now REPORTS the mistake; it does not BLOCK it, and this
    function still has to get the answer right on its own. The candidates
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

    Nothing else is normalized away: every table row is downstream of
    docs/runbook/backlog/*.json and stays inside the comparison. (The view used
    to end in two aggregate counter lines; `render_view` says why they are gone.)
    """
    if not text.startswith("<!-- doc-meta"):
        return text
    _, sep, rest = text.partition("\n-->\n")
    return rest if sep else text


def _cmd_render(args) -> int:
    """Produce the human-readable view — ON DEMAND, and only when asked.

    Nothing calls this implicitly any more. The view is gitignored: it is a local
    convenience for a person who wants the whole ledger in one file, not an artifact
    the repo carries. Machines read the store (`list --json` / `show`), which is why
    removing the automatic refresh cost no reader anything.

    Still wrapped in the lock, and it is cheap now that it runs once per explicit
    request rather than once per mutation: `--commit` is a read-store → render →
    read-outgoing → write-view cycle, and two people rendering at once could still
    tear the file. `--check` takes it too — without it, it renders at one instant and
    compares against a view read at another, and can report STALE about a state that
    never existed.

    Deliberately a wrapper rather than a `with` inside the body: `_view_lock` is a
    plain flock on a fresh fd, so it is NOT re-entrant — a nested acquire from this
    same process would hang with nothing to kill. Keeping the acquire at exactly one
    place per entry point is what makes that impossible rather than unlikely.
    """
    with _view_lock():
        return _cmd_render_unlocked(args)


def _cmd_render_unlocked(args) -> int:
    if args.out is None:
        try:
            same_as_default = Path(args.store).expanduser().resolve() == Path(DEFAULT_STORE).resolve()
        except OSError:
            same_as_default = False
        if _backlog_store.is_external_store(args.store, ROOT):
            args.out = _backlog_store.default_view(args.store, ROOT)
        else:
            args.out = DEFAULT_VIEW if same_as_default else _backlog_store.default_view(args.store, ROOT)
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
                    "  lost IMP rows      -> not recoverable from this rendered view; "
                    "restore each entry from git: git checkout <sha> -- "
                    "docs/runbook/backlog/<id>.json"
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
            counts = view_counts(args.store)
            # The two numbers the view's footer used to carry. Reported, not
            # committed: a count belongs where it costs nothing, and inside a
            # version-controlled artifact it costs a merge conflict per branch.
            print(f"wrote {args.out} ({size} bytes, verified_against={verified})")
            print(f"  {counts['imp']} IMP + {counts['app']} APP entries; "
                  f"groom: {counts['groomed']}/{counts['unresolved']} unresolved have "
                  f"a fix plan (`list --ungroomed` for the rest)")
    else:
        sys.stdout.write(text)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    handlers = {
        "add": _cmd_add,
        "lifecycle": _cmd_lifecycle,
        "list": _cmd_list,
        # The SAME handler, not a wrapper around it: two entry points into one
        # implementation is the contract this subcommand exists to keep.
        "dispatch": _cmd_list,
        "audit-criteria": _cmd_audit_criteria,
        "show": _cmd_show,
        "preflight": _cmd_preflight,
        "validate": _cmd_validate,
        "groom": _cmd_groom,
        "update": _cmd_update,
        "supersede": _cmd_supersede,
        "import": _cmd_import,
        "render": _cmd_render,
        "reanchor": _cmd_reanchor,
        "verify": _cmd_verify,
        "stage": _cmd_stage,
        "unstage": _cmd_unstage,
        "anchor": _cmd_anchor,
    }
    try:
        _resolve_file_twins(parser, args)
        return handlers[args.command](args)
    except (BacklogError, ValueError) as exc:
        # `--json` is a machine channel, and a channel that turns into prose exactly
        # when the answer is "no" is worst where it matters most: refusals are what an
        # automated caller meets most often. Measured before this: a bad --verdict
        # printed prose to stderr and nothing to stdout, so json.load() raised
        # JSONDecodeError instead of yielding a readable refusal.
        #
        # ONE envelope for both codes. The two used to be written out separately and
        # were byte-identical apart from the return — the same hand-copied-second-time
        # shape this module criticises everywhere else, and nothing would have gone
        # red if they drifted.
        failure_context = {}
        if args.command == "add":
            mode = ("staged" if getattr(args, "stage", False)
                    else "dry-run" if getattr(args, "dry_run", False)
                    else "commit")
            failure_context = {"mode": mode, "written": False}
            print(f"ERROR [mode={mode}; written=false] {exc}", file=sys.stderr)
        elif args.command == "supersede":
            mode = "commit" if getattr(args, "commit", False) else "dry-run"
            failure_context = {
                "mode": mode,
                "written": False,
                "source_id": getattr(args, "id", None),
            }
            print(f"ERROR [mode={mode}; written=false] {exc}", file=sys.stderr)
        else:
            print(f"ERROR {exc}", file=sys.stderr)
        if getattr(args, "json", False):
            print(json.dumps({"schema": f"kg.backlog.{args.command}.v1", "ok": False,
                              "error": str(exc), "command": args.command,
                              **failure_context},
                             ensure_ascii=False))
        # The codes this CLI actually uses are 0 / 1 / 2 / 64 (argparse adds its own
        # 2 for a malformed command line):
        #   1  — the call was fine, the answer is no. `render --check` STALE, and an
        #        id that is not in the store.
        #   2  — `validate` / `import` / `render` found problems.
        #   64 — this invocation cannot be carried out: a bad flag combination, a
        #        verdict outside the vocabulary, no field to change, AND the
        #        preconditions `reanchor` needs (a git repo, a resolvable HEAD).
        #        That last group is why "malformed call" is the wrong summary.
        # `test_show_cli_reports_a_missing_entry` pins the 1.
        return 1 if isinstance(exc, EntryNotFound) else 64


if __name__ == "__main__":
    sys.exit(main())
