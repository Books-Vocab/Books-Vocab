#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# ///
"""Worktree orchestrator (P3): the primitive CLI that carries an intent from a fresh
session all the way to cutover into `main`, without re-implementing any gate.

It is the thin conductor above two existing layers:
  * P1 ops/lib/worktree_state.py  — pure worktree/branch health verdicts.
  * P2 ops/worktree_registry.py    — the birth→resolution ledger + orphan sentinel.
This module NEVER re-implements containment, classification or the sweep; it CALLS
worktree_registry (in-process) for register / resolve / sweep, and it EDITS nothing
about how a gate decides pass/fail — the `gate` subcommand only *routes* changed
files to the project's existing gate tools (ios_ops.sh / verify_design_system.sh /
docs_lint.sh / pytest) and aggregates their verdicts.

Architecture (mirrors worktree_registry.py / the retired converge_board.py — three layers):
  IO layer      git + subprocess to the real gate tools. Side-effecting steps
                (worktree add, rebase, push, worktree remove, branch -D) are gated
                behind --commit; dry-run is the default for every mutation.
  pure layer    the two pieces of judgement this tool owns, both unit-tested:
                  classify_intent(text)        -> "debug" | "feat" | "research"
                  plan_gates(changed_files)    -> [gate spec, ...]   (impact routing)
                  aggregate_verdict(results)   -> "pass" | "warn" | "block"
                No git, no clock, no IO — same discipline as P1.
  render layer  human text / --json (schema kg.worktree.orchestrate.v1, and the gate
                subcommand emits kg.worktree.gate.v1).

Subcommands (the API a driving agent / the worktree-flow skill calls):
  preflight  fetch origin + `worktree_registry sweep --exclude-current` (clear crash
             residue; dry-run default, --commit executes). Safe from ANY worktree —
             --exclude-current means a preflight never proposes clearing itself.
TOPOLOGY — local-main-centric, three planes. Local `main` is the trunk: worktrees fork
from it and cutover fast-forwards it OFFLINE (develop plane). `sync` mirrors local main
to origin/main as a zero-side-effect backup (backup plane) — the reconciler does NOT
watch origin/main. `deploy` advances origin/prod (release plane) — the felix reconciler
watches origin/prod and turns a backend delta into a health-gated production rollout.
So local main runs ahead of origin/main (backed up) and origin/prod (released) by however
many cutovers have landed; deploy is the ONE deliberate production touch.

  open       git worktree add (.claude/worktrees/<slug>, branch = <type>/<slug> where
             type is classify_intent(intent)) forked from LOCAL `main` (offline) +
             registry register (born-registered).
  adopt      register an ALREADY-existing worktree (bootstrap fallback: a bare
             `git worktree add` needs none of this tooling — adopt afterwards from
             inside). Registers the worktree ROOT; ledger + freeze lock anchor on the
             TARGET's git-common-dir, never the process cwd.
  gate       IMPACT-BASED verification. Diffs the worktree against its base (local
             `main`), routes each touched surface to its existing gate tool, runs them,
             aggregates a pass/warn/block verdict, and RECORDS it (keyed by worktree +
             HEAD sha) so cutover can require a fresh pass. Runs the gates EXPLICITLY —
             the .githooks pre-commit is best-effort only and must not be relied on.
  cutover    require a fresh NON-BLOCK gate verdict (verdict in {pass, warn} AND
             recorded HEAD == current HEAD) → rebase worktree onto local `main` → ff
             the primary checkout's local `main` to it (serialized by a lock; the
             primary must be on main + tracked-clean, since a ff updates its files).
             OFFLINE — no push, no deploy. A `warn` is advisory: it LANDS ("landed with
             warnings") — the driving agent owns a warn's disposition, so the tool must
             not hard-refuse it; only `block` (and a stale/absent verdict) refuses.
             dry-run default.
  resolve    landed-floor (refuse to force-discard a branch not yet in base, unless
             --force) → registry resolve <branch> merged → git worktree remove +
             branch -D (local, and origin if present) + drop the gate-record cache →
             ledger closed, no residue.
  sync       BACKUP plane: mirror the local trunk to origin/main (local→origin) — a
             zero-side-effect backup. Distinct from sync-main (origin→local). The
             reconciler watches origin/prod, not origin/main, so this has no production
             effect. Guarded ff push, dry-run default.
  deploy     RELEASE plane: advance origin/prod to the local trunk — the ONE deliberate
             production touch. Guarded ff push (primary on main, origin/prod a strict
             ancestor of local, never a force); noop when already advanced; surfaces the
             backend files in range (a backend delta makes the felix reconciler run a
             health-gated rollout with auto-rollback — deploy does not re-run that gate).
             dry-run default.
  sync-main  guarded LOSSLESS ff of the PRIMARY checkout's local main to origin/main
             (three-green: tracked-clean + on main with no merge/rebase in flight +
             strictly behind). In the local-centric model local main normally runs
             AHEAD of origin, so on the dev machine this is a noop; it earns its keep on
             the felix deploy clone (whose main tracks origin) and after a fresh clone.
             A diverged main is never auto-merged — land unique commits via cutover.
             dry-run default.
  freeze     stop-the-world surgery lock (on --reason / off / status). While frozen,
             open/adopt/cutover/sync-main/sync/deploy refuse; draining steps (resolve, sweep,
             preflight, gate) stay allowed so the flow can be quiesced for repo
             surgery (history rewrite, gc, shared hooks/config).

Exit codes: 0 ok | 64 usage error | 1 blocked (gate block / cutover refused / partial).
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import subprocess
import sys
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any, Callable

# Reuse P2 in-process — never re-implement register / resolve / sweep / state paths.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import worktree_registry as wr  # noqa: E402

SCHEMA = "kg.worktree.orchestrate.v1"
GATE_SCHEMA = "kg.worktree.gate.v1"
FREEZE_SCHEMA = "kg.worktree.freeze.v1"
EXIT_OK = 0
EXIT_USAGE = 64
EXIT_BLOCK = 1

# Local-main-centric topology: local `main` is the trunk. Worktrees fork from it and
# cutover fast-forwards it OFFLINE — origin is only a deploy target (`deploy` pushes
# local main to origin, which the felix reconciler turns into a production rollout).
BASE_DEFAULT = "main"
SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
# git's canonical empty-tree object — diff base for a first-ever publish (all files new)
EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"

# The design-system impact surface: the EXACT pattern the pre-commit hook uses
# (.githooks/pre-commit DS_PATTERN). Reused verbatim so orchestrator routing and the
# hook can never disagree about what a "design-system change" is.
DS_RE = re.compile(
    r"^(design-system/"
    r"|ops/(gen_web_tokens|gen_figma_sets|token_drift_check|component_fidelity_check|verify_design_system)\.(py|sh)"
    r"|ios/BooksAndVocab/(Models|UIComponents)/"
    r"|backend/static/kg-(tokens|components)\.css)"
)


# ============================================================================
# PURE layer — the only judgement this tool owns. No git, no clock, no IO.
# ============================================================================
_DEBUG_KW = ("bug", "crash", "fix", "hang", "regression", "broken", "stutter",
             "flaky", "leak", "debug", "root cause", "root-cause")
# Research is signalled by a LEADING verb (research the ..., investigate ...): a
# substring match is too greedy — "the explore tab" / "the analytics screen" are
# feature nouns, not research intents.
_RESEARCH_VERBS = frozenset({"research", "investigate", "audit", "explore", "analyze",
                             "analyse", "survey", "study", "understand", "compare",
                             "evaluate", "assess", "map", "review"})
# Politeness / pronoun filler that can precede a LEADING imperative verb ("please
# investigate …", "can you research …") — transparent to the verb check.
_LEADING_FILLER = frozenset({"please", "can", "could", "you", "lets", "let's", "let",
                             "us", "we", "i", "to", "help", "me", "do"})
# Articles introduce a NOUN phrase, NOT an imperative — deliberately NOT filler. A
# phrase whose first meaningful token is an article ("the explore tab") is a feature
# noun, so the research-verb check must never see through it (nit4).
_ARTICLES = frozenset({"the", "a", "an"})


def classify_intent(text: str) -> str:
    """Map a free-text intent to a branch type: debug | research | feat.

    Precedence: a fix/bug intent is `debug` even when phrased as "investigate … and
    fix it" (a debug keyword anywhere dominates). Otherwise a `research` intent is one
    whose LEADING imperative verb is a research verb (research/investigate/audit/…),
    ignoring politeness filler. A bare noun-phrase — one that opens with an article
    (the/a/an) after any filler — is `feat` even when it CONTAINS a research noun
    ("the explore tab", "the audit log"): an article marks a noun, not an imperative.
    Everything else is `feat`."""
    t = f" {text.lower()} "
    if any(k in t for k in _DEBUG_KW):
        return "debug"          # a fix intent dominates ("investigate … and fix it")
    for word in re.findall(r"[a-z']+", text.lower()):
        if word in _LEADING_FILLER:
            continue
        if word in _ARTICLES:
            return "feat"        # bare noun-phrase, no leading imperative verb (nit4)
        return "research" if word in _RESEARCH_VERBS else "feat"
    return "feat"


def branch_for(intent_text: str, slug: str) -> str:
    """Branch name = <type>/<slug>, type derived from the intent text."""
    return f"{classify_intent(intent_text)}/{slug}"


def _is_ui_path(p: str) -> bool:
    """A swift path whose change plausibly affects UI/navigation/accessibility — the
    signal to add the UI-scoped iOS test on top of the unit scope."""
    base = p.rsplit("/", 1)[-1]
    return (
        base.endswith("View.swift")
        or "/UIComponents/" in p
        or "/UI/" in p
        or "UITests" in p
        or base.endswith("Screen.swift")
    )


def _is_backend_test(p: str) -> bool:
    base = p.rsplit("/", 1)[-1]
    return base.startswith("test_") or base.endswith("_test.py")


def _is_ops_test(p: str) -> bool:
    return p.startswith("ops/tests/") and p.rsplit("/", 1)[-1].startswith("test_")


def _shell(name: str, category: str, cmd: list[str], level: str,
           cwd: str | None = None) -> dict[str, Any]:
    return {"name": name, "category": category, "kind": "shell",
            "cmd": cmd, "level": level, "cwd": cwd}


def _internal(name: str, category: str, level: str, **extra: Any) -> dict[str, Any]:
    g = {"name": name, "category": category, "kind": "internal", "level": level}
    g.update(extra)
    return g


def plan_gates(changed_files: list[str],
               ops_test_exists: Callable[[str], bool] | None = None) -> list[dict[str, Any]]:
    """Route changed files to the project's EXISTING gate tools. This is the one real
    judgement the orchestrator owns; it never decides pass/fail itself.

      ios/**            -> ios_ops.sh build  AND  build --catalyst (sim green != Catalyst
                           green) + quality impact (swift) + test --unit. If UITest
                           classes changed, also test --ui --file <class> per changed
                           UITest (impacted-scope, --dataset marketing_demo) — NOT the
                           whole --ui suite, which false-blocks on unrelated flaky tests.
      design-system/**  -> verify_design_system.sh   (tokens / generated CSS / Models /
      | tokens | *.css     UIComponents — the pre-commit DS_PATTERN, verbatim).
      docs/**.md        -> docs_lint.sh --files + conflict-marker scan + verified_against
                           reachability.
      backend/**.py     -> targeted pytest on the changed TEST files; a src-only change
                           with no targeted test is a WARN advisory (never the full
                           suite — it carries known pre-existing false failures).
      ops/**.py         -> targeted pytest via the pinned uv sandbox (`uv run
                           --no-project --python 3.13 --with pytest` — never touching
                           backend/uv.lock): a changed ops/tests/test_*.py runs itself;
                           a changed src file runs its ops/tests/test_<basename>. EVERY
                           target must pass `ops_test_exists` (a deleted test file is
                           in the diff too — a gone path would make pytest exit 4);
                           any changed ops .py that resolves to no existing test falls
                           back to the whole ops/tests suite (which subsumes the
                           targeted files, and which sandbox-unsafe tests must dep-guard
                           with a skip — see test_demo_ios_spec_emitter). ops/*.sh have
                           no pytest counterpart and select nothing here.
                           `ops_test_exists` is injected by cmd_gate (anchored at the
                           WORKTREE, so a test added in the same diff is seen); the pure
                           default (None) cannot prove existence -> whole-suite fallback.

    Levels: `block` fails the verdict; `warn` is ADVISORY — it degrades the aggregate
    to `warn` but does NOT block cutover (a warn LANDS "with warnings"; its disposition
    belongs to the driving agent). Informational gates (backend-src-only advisory,
    verified_against reachability) are `warn` so they surface without blocking. A
    neutral file selects nothing."""
    gates: list[dict[str, Any]] = []

    ios = [p for p in changed_files if p.startswith("ios/")]
    ds = [p for p in changed_files if DS_RE.search(p)]
    docs = [p for p in changed_files if p.startswith("docs/") and p.endswith(".md")]
    backend = [p for p in changed_files if p.startswith("backend/") and p.endswith(".py")]

    if ios:
        gates.append(_shell("ios-build", "ios", ["ops/ios_ops.sh", "build"], "block"))
        gates.append(_shell("ios-build-catalyst", "ios",
                            ["ops/ios_ops.sh", "build", "--catalyst"], "block"))
        swift = [p for p in ios if p.endswith(".swift")]
        if swift:
            gates.append(_shell("ios-quality-impact", "ios",
                                ["ops/ios_ops.sh", "quality", "impact", "--files",
                                 *swift, "--json"], "warn"))
        gates.append(_shell("ios-test-unit", "ios",
                            ["ops/ios_ops.sh", "test", "--unit"], "block"))
        if any(_is_ui_path(p) for p in ios):
            # Impacted-scope UI gate: run only the UI *test classes* that changed
            # in this diff — NOT the whole --ui suite. The full suite as a block
            # gate false-blocks every iOS cutover on unrelated, pre-existing/flaky
            # UI tests (UI flakiness is well documented here), and costs ~tens of
            # minutes. This mirrors ios-quality-impact's --files scoping.
            # ios_test.sh --ui requires a UI World dataset (the SoT for UI runs);
            # the committed default world is marketing_demo. Filter to *Tests.swift
            # so page-object/helper files (e.g. AppPage.swift) are excluded.
            # A UI-source change with no changed UITest is covered by build +
            # unit + quality-impact; a full-suite run here would just reintroduce
            # the flaky false-block.
            ui_test_classes = sorted({
                p.rsplit("/", 1)[-1].removesuffix(".swift")
                for p in ios
                if "UITests/" in p and p.endswith("Tests.swift")
            })
            for cls in ui_test_classes:
                gates.append(_shell(f"ios-test-ui:{cls}", "ios",
                                    ["ops/ios_ops.sh", "test", "--ui",
                                     "--dataset", "marketing_demo", "--file", cls], "block"))

    if ds:
        gates.append(_shell("design-system", "design-system",
                            ["ops/verify_design_system.sh"], "block"))

    if docs:
        gates.append(_shell("docs-lint", "docs",
                            ["ops/docs_lint.sh", "--files", *docs], "block"))
        gates.append(_internal("docs-conflict-markers", "docs", "block", files=docs))
        gates.append(_internal("docs-verified-against", "docs", "warn", files=docs))

    if backend:
        tests = [p for p in backend if _is_backend_test(p)]
        if tests:
            rel = [p[len("backend/"):] for p in tests]
            gates.append(_shell("backend-pytest", "backend",
                                ["uv", "run", "pytest", "-q", *rel], "block", cwd="backend"))
        else:
            gates.append(_internal("backend-tests-advisory", "backend", "warn",
                                   note="backend src changed but no targeted test in the diff — "
                                        "run the relevant tests manually (the full suite carries "
                                        "known pre-existing false failures)", files=backend))

    ops_py = [p for p in changed_files if p.startswith("ops/") and p.endswith(".py")]
    if ops_py:
        exists = ops_test_exists or (lambda rel: False)
        targets: set[str] = set()
        fallback = False
        for p in ops_py:
            # a changed test file must ALSO prove existence: a DELETED test is in
            # the diff too, and passing a gone path to pytest exits 4 -> false block
            candidate = p if _is_ops_test(p) else f"ops/tests/test_{p.rsplit('/', 1)[-1]}"
            if exists(candidate):
                targets.add(candidate)
            else:
                fallback = True
        # the whole-suite fallback subsumes every targeted file
        selected = ["ops/tests"] if fallback else sorted(targets)
        gates.append(_shell("ops-pytest", "ops",
                            ["uv", "run", "--no-project", "--python", "3.13",
                             "--with", "pytest", "pytest", "-q", *selected], "block"))

    return gates


def aggregate_verdict(results: list[dict[str, Any]]) -> str:
    """block if any gate blocked; else warn if any warned; else pass (incl. empty)."""
    statuses = {r.get("status") for r in results}
    if "block" in statuses:
        return "block"
    if "warn" in statuses:
        return "warn"
    return "pass"


# ============================================================================
# IO layer — git + subprocess to the real gate tools.
# ============================================================================
def _git(args: list[str], cwd: Path | str | None = None) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            ["git", *args], cwd=str(cwd) if cwd else None,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
    except (FileNotFoundError, NotADirectoryError) as exc:
        # cwd can legitimately vanish mid-teardown (resolve removes the worktree the
        # caller stands in); a captured failure beats an unhandled traceback.
        return 127, f"cwd unavailable: {exc}"
    out = proc.stdout.strip()
    if proc.returncode != 0 and proc.stderr.strip():
        out = (out + "\n" + proc.stderr.strip()).strip()
    return proc.returncode, out


def primary_root() -> Path:
    """The MAIN working tree's root (dirname of the git common dir). Stable no matter
    which linked worktree the process stands in — the only safe anchor for open's
    worktree placement and for teardown commands that may remove the caller's own cwd
    (resolve from inside the target worktree)."""
    return wr.common_anchor()


def _norm(p: str) -> str:
    return os.path.realpath(os.path.abspath(p))


def _fetch(quiet: bool = True) -> tuple[int, str]:
    return _git(["fetch", "origin", "--prune"])


def _main_advance_lock(primary: Path):
    """Serialize local-`main` fast-forwards so two concurrent cutovers cannot race:
    without it both would rebase onto main@X and the second's ff-only would fail (or
    worse, interleave). Reuses the registry's reviewed flock primitive on a sidecar
    beside the ledger (`.cache/`, gitignored, one per repo)."""
    return wr._ledger_lock(primary / ".cache" / "kg-main-advance")


_C_ESCAPES = {"n": 0x0A, "t": 0x09, "r": 0x0D, "a": 0x07, "b": 0x08,
              "f": 0x0C, "v": 0x0B, "\\": 0x5C, '"': 0x22}


def _c_unquote(p: str) -> str:
    """Undo git's C-style path quoting (core.quotePath): a path with spaces or
    non-ASCII bytes arrives as `"..."` with `\\`-escapes and 3-digit octal UTF-8
    byte sequences. Unwrapped paths pass through untouched."""
    if not (len(p) >= 2 and p.startswith('"') and p.endswith('"')):
        return p
    body, out, i = p[1:-1], bytearray(), 0
    while i < len(body):
        c = body[i]
        if c == "\\" and i + 1 < len(body):
            if body[i + 1] in "01234567":
                j = i + 2
                while j < min(i + 4, len(body)) and body[j] in "01234567":
                    j += 1
                out.append(int(body[i + 1:j], 8) & 0xFF)
                i = j
                continue
            out.append(_C_ESCAPES.get(body[i + 1], ord(body[i + 1])))
            i += 2
            continue
        out.extend(c.encode("utf-8"))
        i += 1
    return out.decode("utf-8", errors="replace")


def _porcelain_paths(out: str) -> list[str]:
    """Pathnames from `git status --porcelain` output (renames report the new side),
    C-unquoted to real paths. No fixed-offset slicing: `_git` strips its output,
    which can eat the first line's leading status column — split the 1-2 char XY
    field off instead."""
    paths: list[str] = []
    for ln in out.splitlines():
        ln = ln.lstrip()
        if not ln or " " not in ln:
            continue
        p = ln.split(" ", 1)[1].lstrip()
        if " -> " in p:
            p = p.split(" -> ", 1)[1]
        paths.append(_c_unquote(p))
    return paths


def _primary_ff_ready(primary: Path, local: str) -> tuple[str, dict[str, Any]] | None:
    """Refusal `(reason, extra-json-fields)` (or None) for advancing the primary
    checkout's local `main` by a fast-forward. `main` is checked out in the primary,
    so a ff updates its working tree — it must be on `local`, tracked-clean, with no
    merge/rebase in flight. Same guard family as sync-main, in the local-integration
    direction. Every reason names its next step: with multiple sessions sharing the
    repo a refusal is a coordination event, not a dead end."""
    cur = _current_branch(str(primary))
    if cur != local:
        where = "a detached HEAD" if cur is None else f"{cur!r}"
        return (f"primary checkout is on {where}, not {local!r} — cutover advances "
                f"the local trunk under its own checkout; put the primary back on "
                f"{local!r} (its tenant may be mid-task — coordinate, don't force), "
                f"then re-run cutover", {})
    rc, _ = _git(["rev-parse", "-q", "--verify", "MERGE_HEAD"], cwd=primary)
    if rc == 0:
        return ("a merge is in progress in the primary checkout — let its tenant "
                "conclude it (commit or `git merge --abort`), then re-run cutover", {})
    for probe in ("rebase-merge", "rebase-apply"):
        rc, p = _git(["rev-parse", "--path-format=absolute", "--git-path", probe],
                     cwd=primary)
        if rc == 0 and p and Path(p).exists():
            return ("a rebase is in progress in the primary checkout — let its tenant "
                    "conclude it (`git rebase --continue`/`--abort`), then re-run "
                    "cutover", {})
    rc, out = _git(["status", "--porcelain", "--untracked-files=no"], cwd=primary)
    if rc != 0:
        return (f"cannot read primary status: {out[:200]} — inspect the primary "
                f"checkout by hand, then re-run cutover", {})
    if out.strip():
        files = _porcelain_paths(out)
        shown = ", ".join(files[:10])
        if len(files) > 10:
            shown += f" … and {len(files) - 10} more"
        return (
            "primary working tree is dirty (tracked changes) — a ff updates the "
            f"checked-out files\n  dirty: {shown}\n"
            "  likely another session is working in the primary. Options: (a) use "
            "the session-mgmt MCP — list_sessions to find running sessions on this "
            "repo, send_message to ask the tenant to commit; (b) if the leftovers "
            "are yours, commit them or evacuate them to a worktree. The gate verdict "
            "is bound to the worktree HEAD and stays valid — once the primary is "
            "clean, just re-run cutover", {"dirty_files": files})
    return None


def _changed_vs_base(worktree: str, base: str) -> list[str]:
    """Committed files the worktree's HEAD changed relative to base (merge-base diff:
    `git diff --name-only base...HEAD`). This is what a cutover would land."""
    rc, out = _git(["diff", "--name-only", f"{base}...HEAD"], cwd=worktree)
    if rc != 0:
        # base unresolved (e.g. no origin/main locally) — fall back to two-dot.
        rc, out = _git(["diff", "--name-only", f"{base}..HEAD"], cwd=worktree)
    return [ln for ln in out.splitlines() if ln]


def _head_sha(worktree: str) -> str:
    _, out = _git(["rev-parse", "HEAD"], cwd=worktree)
    return out


def _current_branch(worktree: str) -> str | None:
    rc, out = _git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=worktree)
    return out if rc == 0 and out != "HEAD" else None


def _remote_branch_exists(name: str) -> bool:
    rc, out = _git(["ls-remote", "--heads", "origin", name])
    return rc == 0 and bool(out.strip())


# ---- registry (P2) in-process, JSON captured ------------------------------
def _registry(argv: list[str]) -> tuple[int, dict[str, Any] | None]:
    """Call worktree_registry.main in-process; capture its --json stdout if present."""
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = wr.main(argv)
    text = buf.getvalue().strip()
    payload: dict[str, Any] | None = None
    if "--json" in argv and text:
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            payload = None
    return rc, payload


def _state_arg(state: str | None) -> list[str]:
    return ["--state", state] if state else []


def _freeze_path(state: str | None) -> Path:
    """The stop-the-world surgery lock, beside the ledger (same anchoring as the
    gate-record cache) so every worktree sees the one lock."""
    base_dir = Path(state).resolve().parent if state else wr.default_state_path().parent
    return base_dir / "worktree_freeze.json"


def _frozen(state: str | None) -> dict[str, Any] | None:
    """The freeze payload if the flow is frozen, else None. An unreadable lock file
    still counts as frozen — fail closed during surgery."""
    p = _freeze_path(state)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text())
    except (OSError, json.JSONDecodeError):
        return {"reason": f"unreadable freeze file at {p}", "frozen_at": None}
    if not isinstance(data, dict):  # valid JSON but not ours — still fail closed
        return {"reason": f"malformed freeze file at {p}", "frozen_at": None}
    return data


def _freeze_guard(state: str | None, step: str, as_json: bool) -> int | None:
    """EXIT_BLOCK if frozen (birth/landing steps only — draining steps like resolve
    and sweep stay allowed so quiescing for surgery is possible), else None."""
    frz = _frozen(state)
    if frz is None:
        return None
    _emit({"schema": SCHEMA, "step": step, "error": "frozen",
           "reason": frz.get("reason"), "frozen_at": frz.get("frozen_at")}, as_json,
          f"✗ {step} refused: worktree flow is FROZEN — {frz.get('reason')} "
          f"(since {frz.get('frozen_at')}); run `freeze off` to resume")
    return EXIT_BLOCK


def _gate_record_path(state: str | None, worktree: str) -> Path:
    """Where a gate verdict is recorded so cutover can read it — a per-machine cache
    beside the registry ledger, keyed by the worktree's normalized path."""
    if state:
        base_dir = Path(state).resolve().parent
    else:
        base_dir = wr.default_state_path().parent
    key = hashlib.sha256(_norm(worktree).encode()).hexdigest()[:16]
    return base_dir / "worktree_gates" / f"{key}.json"


# ---- internal gate runners -------------------------------------------------
def _run_conflict_markers(worktree: str, files: list[str]) -> dict[str, Any]:
    hits = []
    for rel in files:
        fp = Path(worktree) / rel
        if not fp.exists():
            continue
        try:
            for i, line in enumerate(fp.read_text(errors="replace").splitlines(), 1):
                if line.startswith("<<<<<<<") or line.startswith(">>>>>>>") \
                        or line.rstrip() == "=======":
                    hits.append(f"{rel}:{i}")
        except OSError:
            continue
    if hits:
        return {"status": "block", "rc": 1,
                "summary": f"conflict markers in {len(hits)} location(s): {', '.join(hits[:5])}"}
    return {"status": "pass", "rc": 0, "summary": "no conflict markers"}


_VA_RE = re.compile(r"^\s*verified_against:\s*([0-9a-fA-F]{7,40})\s*$", re.MULTILINE)


def _run_verified_against(worktree: str, files: list[str]) -> dict[str, Any]:
    bad = []
    checked = 0
    for rel in files:
        fp = Path(worktree) / rel
        if not fp.exists():
            continue
        m = _VA_RE.search(fp.read_text(errors="replace"))
        if not m:
            continue
        checked += 1
        sha = m.group(1)
        rc, _ = _git(["rev-parse", "--verify", "--quiet", f"{sha}^{{commit}}"], cwd=worktree)
        if rc != 0:
            bad.append(f"{rel} -> {sha}")
    if bad:
        return {"status": "warn", "rc": 1,
                "summary": f"verified_against unreachable for {len(bad)} doc(s): {', '.join(bad[:5])}"}
    return {"status": "pass", "rc": 0, "summary": f"verified_against reachable ({checked} checked)"}


def _run_gate(spec: dict[str, Any], worktree: str) -> dict[str, Any]:
    """Execute ONE planned gate against the worktree and return a result record."""
    name, level = spec["name"], spec["level"]
    result = {"name": name, "category": spec["category"], "level": level}
    if spec["kind"] == "internal":
        if name == "docs-conflict-markers":
            result.update(_run_conflict_markers(worktree, spec["files"]))
        elif name == "docs-verified-against":
            result.update(_run_verified_against(worktree, spec["files"]))
        else:  # advisory-only gate (e.g. backend-tests-advisory)
            result.update({"status": "warn", "rc": 0, "summary": spec.get("note", "advisory")})
        return result

    # shell gate — run the real tool. cwd is the worktree (or a subdir like backend).
    cwd = Path(worktree) / spec["cwd"] if spec.get("cwd") else Path(worktree)
    proc = subprocess.run(spec["cmd"], cwd=str(cwd),
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    tail = "\n".join(proc.stdout.splitlines()[-3:]) if proc.stdout else ""
    if proc.returncode == 0:
        status = "pass"
    else:
        status = "block" if level == "block" else "warn"
    result.update({"status": status, "rc": proc.returncode,
                   "summary": f"exit {proc.returncode}" + (f": {tail}" if tail else "")})
    return result


# ============================================================================
# render helpers
# ============================================================================
def _emit(payload: dict[str, Any], as_json: bool, human: str) -> None:
    if as_json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print(human)


# ============================================================================
# subcommands
# ============================================================================
def cmd_preflight(args: argparse.Namespace) -> int:
    """fetch origin + registry sweep --exclude-current (clear crash residue)."""
    frc, fout = _fetch()
    sweep_argv = ["sweep", "--no-fetch", "--exclude-current", "--json",
                  *_state_arg(args.state)]
    if args.commit:
        sweep_argv.append("--commit")
    src, sweep = _registry(sweep_argv)
    payload = {
        "schema": SCHEMA, "step": "preflight",
        "fetch": {"ok": frc == 0, "detail": fout[:200]},
        "mode": "committed" if args.commit else "dry-run",
        "sweep": sweep or {},
        "sweep_rc": src,
    }
    n_clear = len((sweep or {}).get("clear", []))
    human = (f"# preflight ({'committed' if args.commit else 'dry-run'})\n"
             f"  fetch: {'ok' if frc == 0 else 'FAILED — ' + fout[:120]}\n"
             f"  sweep: {n_clear} clearable, "
             f"{len((sweep or {}).get('stale_entries', []))} stale ledger entry(ies)\n"
             + ("" if args.commit else "  (dry-run — re-run with --commit to reclaim)"))
    _emit(payload, args.json, human)
    return EXIT_OK if (frc == 0 or args.allow_offline) and src == EXIT_OK else EXIT_BLOCK


def cmd_open(args: argparse.Namespace) -> int:
    """git worktree add + registry register (born-registered)."""
    blocked = _freeze_guard(args.state, "open", args.json)
    if blocked is not None:
        return blocked
    if not SLUG_RE.match(args.slug):
        _emit({"schema": SCHEMA, "step": "open", "error": "slug must be kebab-case "
               "([a-z0-9] words joined by '-')", "slug": args.slug}, args.json,
              f"✗ slug {args.slug!r} must be kebab-case ([a-z0-9] joined by '-')")
        return EXIT_USAGE

    branch = branch_for(args.intent, args.slug)
    root = primary_root()
    path = root / ".claude" / "worktrees" / args.slug
    base = args.base

    # local-centric: fork from the LOCAL trunk (default `main`) — offline, no fetch.
    # origin is a deploy target, not the fork point.
    if path.exists():
        _emit({"schema": SCHEMA, "step": "open", "error": "worktree path exists",
               "path": str(path)}, args.json, f"✗ worktree path already exists: {path}")
        return EXIT_USAGE
    rc, out = _git(["worktree", "add", "-b", branch, str(path), base], cwd=root)
    if rc != 0:
        _emit({"schema": SCHEMA, "step": "open", "error": "worktree add failed",
               "detail": out}, args.json, f"✗ git worktree add failed:\n{out}")
        return EXIT_BLOCK

    reg_rc, _ = _registry(["register", *_state_arg(args.state), "--path", str(path),
                           "--branch", branch, "--intent", args.intent, "--base", base])
    payload = {"schema": SCHEMA, "step": "open", "branch": branch, "path": str(path),
               "base": base, "intent": args.intent, "registered": reg_rc == EXIT_OK}
    human = (f"✓ opened worktree [{branch}] (base {base})\n"
             f"  path: {path}\n"
             f"  {'registered in ledger' if reg_rc == EXIT_OK else '⚠ ledger register failed'}")
    _emit(payload, args.json, human)
    return EXIT_OK


def cmd_adopt(args: argparse.Namespace) -> int:
    """Register an ALREADY-existing worktree in the ledger. This is the bootstrap
    fallback: a bare `git worktree add` is a git primitive that needs none of this
    tooling, so when the invoking checkout predates the orchestrator (stale primary),
    open the worktree by hand and adopt it from inside. Delegates to the registry's
    idempotent upsert — adopting twice refreshes, never duplicates.

    Everything anchors on the TARGET, never the process cwd: the path registered is
    the worktree's toplevel (a subdir invocation adopts the root), and the default
    ledger + freeze lock derive from the target's git-common-dir (invoking from a
    foreign cwd cannot write a stray ledger the flow never reads)."""
    worktree = _norm(args.worktree or os.getcwd())
    if not Path(worktree).is_dir():
        _emit({"schema": SCHEMA, "step": "adopt", "error": "worktree not found",
               "worktree": worktree}, args.json, f"✗ worktree not found: {worktree}")
        return EXIT_USAGE

    rc, top = _git(["rev-parse", "--path-format=absolute", "--show-toplevel"],
                   cwd=worktree)
    rc2, common = _git(["rev-parse", "--path-format=absolute", "--git-common-dir"],
                       cwd=worktree)
    if rc != 0 or rc2 != 0 or not top:
        _emit({"schema": SCHEMA, "step": "adopt", "error": "not a git worktree",
               "worktree": worktree}, args.json, f"✗ not a git worktree: {worktree}")
        return EXIT_USAGE
    worktree = _norm(top)

    rc, gitdir = _git(["rev-parse", "--path-format=absolute", "--git-dir"], cwd=worktree)
    if rc != 0 or _norm(gitdir) == _norm(common):
        _emit({"schema": SCHEMA, "step": "adopt", "error": "refusing the primary "
               "working tree (main-first invariant)", "worktree": worktree}, args.json,
              f"✗ {worktree} is the primary working tree — adopt only linked worktrees")
        return EXIT_USAGE

    state = args.state or str(Path(_norm(common)).parent / ".cache"
                              / "worktree_registry.json")
    blocked = _freeze_guard(state, "adopt", args.json)
    if blocked is not None:
        return blocked

    branch = _current_branch(worktree)
    if not branch:
        _emit({"schema": SCHEMA, "step": "adopt", "error": "detached HEAD — the ledger "
               "tracks branches", "worktree": worktree}, args.json,
              f"✗ {worktree} is detached — check out a branch before adopting")
        return EXIT_USAGE

    # open gets --base validation for free from `git worktree add`; adopt checks it
    # itself rather than recording an unresolvable ref in the ledger.
    rc, _ = _git(["rev-parse", "--verify", "-q", f"{args.base}^{{commit}}"],
                 cwd=worktree)
    if rc != 0:
        _emit({"schema": SCHEMA, "step": "adopt", "error": "base does not resolve",
               "base": args.base}, args.json,
              f"✗ --base {args.base!r} does not resolve in the target repo")
        return EXIT_USAGE

    reg_rc, _ = _registry(["register", "--state", state, "--path", worktree,
                           "--branch", branch, "--intent", args.intent, "--base", args.base])
    ok = reg_rc == EXIT_OK
    payload = {"schema": SCHEMA, "step": "adopt", "branch": branch, "worktree": worktree,
               "base": args.base, "intent": args.intent, "ledger": state,
               "registered": ok}
    human = (f"{'✓ adopted' if ok else '✗ adopt could NOT register'} worktree "
             f"[{branch}] (base {args.base})\n"
             f"  path: {worktree}\n"
             f"  ledger: {state}" + ("" if ok else "  — register failed"))
    _emit(payload, args.json, human)
    return EXIT_OK if ok else EXIT_BLOCK


def cmd_freeze(args: argparse.Namespace) -> int:
    """Stop-the-world surgery lock. `on` refuses new births/landings/publishes (open,
    adopt, cutover, sync-main, deploy) until `off`; draining steps (resolve, sweep,
    preflight, gate) stay allowed so the flow can be quiesced for repo surgery (history
    rewrite, gc, shared-config changes)."""
    lock = _freeze_path(args.state)

    if args.action == "status":
        frz = _frozen(args.state)
        payload = {"schema": FREEZE_SCHEMA, "action": "status", "frozen": frz is not None}
        if frz:
            payload.update({"reason": frz.get("reason"), "frozen_at": frz.get("frozen_at")})
        human = (f"# freeze: FROZEN — {frz.get('reason')} (since {frz.get('frozen_at')})"
                 if frz else "# freeze: not frozen")
        _emit(payload, args.json, human)
        return EXIT_OK

    if args.action == "on":
        if not args.reason:
            _emit({"schema": FREEZE_SCHEMA, "action": "on", "error": "`on` requires "
                   "--reason"}, args.json, "✗ freeze on requires --reason")
            return EXIT_USAGE
        existing = _frozen(args.state)
        if existing is not None and not args.force:
            _emit({"schema": FREEZE_SCHEMA, "action": "on", "error": "already frozen",
                   "reason": existing.get("reason"),
                   "frozen_at": existing.get("frozen_at")}, args.json,
                  f"✗ already frozen — {existing.get('reason')} (since "
                  f"{existing.get('frozen_at')}); --force to overwrite")
            return EXIT_BLOCK
        _, now_iso = wr.resolve_now(None)
        payload = {"schema": FREEZE_SCHEMA, "reason": args.reason, "frozen_at": now_iso}
        lock.parent.mkdir(parents=True, exist_ok=True)
        data = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
        if args.force:
            lock.write_text(data)
        else:
            try:  # O_EXCL closes the check-then-write race between two sessions
                fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                raced = _frozen(args.state) or {}
                _emit({"schema": FREEZE_SCHEMA, "action": "on", "error": "already "
                       "frozen", "reason": raced.get("reason"),
                       "frozen_at": raced.get("frozen_at")}, args.json,
                      f"✗ already frozen — {raced.get('reason')}; --force to overwrite")
                return EXIT_BLOCK
            with os.fdopen(fd, "w") as fh:
                fh.write(data)
        _emit({**payload, "action": "on"}, args.json,
              f"✓ frozen — {args.reason}\n  lock: {lock}")
        return EXIT_OK

    # off — idempotent
    was = lock.exists()
    try:
        lock.unlink()
    except FileNotFoundError:
        pass
    _emit({"schema": FREEZE_SCHEMA, "action": "off", "was_frozen": was}, args.json,
          "✓ thawed" if was else "✓ already thawed (no-op)")
    return EXIT_OK


def cmd_sync_main(args: argparse.Namespace) -> int:
    """Guarded fast-forward of the PRIMARY checkout's local main to origin/main.

    The historical 'never ff the user's local main' rule guards against LOSSY moves;
    this primitive makes the threat model precise and only performs the provably
    lossless one: tracked-clean primary, checked out on main, no merge/rebase in
    flight, local strictly behind origin (ancestor check) — three-green or refuse.
    A diverged main is NEVER merged or rebased here; land unique commits via cutover.
    Dry-run by default."""
    blocked = _freeze_guard(args.state, "sync-main", args.json)
    if blocked is not None:
        return blocked

    base = args.base
    if not base.startswith("origin/"):
        _emit({"schema": SCHEMA, "step": "sync-main", "error": "base must be an "
               "origin/* ref", "base": base}, args.json,
              f"✗ base must be an origin/* ref, got {base!r}")
        return EXIT_USAGE
    local = base.split("/", 1)[1]
    primary = primary_root()

    def _refuse(reason: str) -> int:
        _emit({"schema": SCHEMA, "step": "sync-main", "verdict": "refused",
               "reason": reason, "primary": str(primary)}, args.json,
              f"✗ sync-main refused: {reason}")
        return EXIT_BLOCK

    cur = _current_branch(str(primary))
    if cur != local:
        where = "a detached HEAD" if cur is None else f"{cur!r}"
        return _refuse(f"primary checkout is on {where}, not {local!r} — sync-main "
                       "only ever moves the base branch under the base checkout")
    rc, _ = _git(["rev-parse", "-q", "--verify", "MERGE_HEAD"], cwd=primary)
    if rc == 0:
        return _refuse("a merge is in progress in the primary checkout")
    for probe in ("rebase-merge", "rebase-apply"):
        rc, p = _git(["rev-parse", "--path-format=absolute", "--git-path", probe],
                     cwd=primary)
        if rc == 0 and p and Path(p).exists():
            return _refuse("a rebase is in progress in the primary checkout")
    rc, out = _git(["status", "--porcelain", "--untracked-files=no"], cwd=primary)
    if rc != 0:
        return _refuse(f"cannot read primary status: {out[:200]}")
    if out.strip():
        return _refuse("primary working tree is dirty (tracked changes) — a ff moves "
                       "checked-out files; commit/evacuate or restore first")

    frc, fout = _fetch()
    if frc != 0:
        # syncing to a stale origin snapshot would report a false "noop"/"ff" —
        # verification precedes claim, so an unreachable origin refuses outright.
        return _refuse(f"fetch failed — cannot trust the local {base} snapshot: "
                       f"{fout[:200]}")
    # fully-qualified refs: a stray tag named `main` must never shadow the branch
    local_ref = f"refs/heads/{local}"
    base_ref = f"refs/remotes/{base}"
    rc, local_sha = _git(["rev-parse", local_ref], cwd=primary)
    rc2, base_sha = _git(["rev-parse", base_ref], cwd=primary)
    if rc != 0 or rc2 != 0:
        return _refuse(f"cannot resolve {local_ref!r}/{base_ref!r}")
    if local_sha == base_sha:
        _emit({"schema": SCHEMA, "step": "sync-main", "verdict": "noop",
               "sha": local_sha[:9], "primary": str(primary)}, args.json,
              f"# sync-main: noop — {local} already at {local_sha[:9]}")
        return EXIT_OK
    rc, _ = _git(["merge-base", "--is-ancestor", local_ref, base_ref], cwd=primary)
    if rc != 0:
        return _refuse(f"local {local} has commits {base} lacks — never auto-merged; "
                       "land them via cutover (or resolve the divergence by hand)")
    _, count = _git(["rev-list", "--count", f"{local_ref}..{base_ref}"], cwd=primary)

    if not args.commit:
        _emit({"schema": SCHEMA, "step": "sync-main", "verdict": "dry-run",
               "from": local_sha[:9], "to": base_sha[:9], "commits": int(count or 0),
               "primary": str(primary)}, args.json,
              (f"# sync-main (dry-run)\n  would ff {local}: {local_sha[:9]} -> "
               f"{base_sha[:9]} ({count} commit(s))\n  (--commit to execute)"))
        return EXIT_OK

    rc, out = _git(["merge", "--ff-only", base_ref], cwd=primary)
    if rc != 0:
        return _refuse(f"git merge --ff-only failed: {out[:300]}")
    rc, now_sha = _git(["rev-parse", local_ref], cwd=primary)
    if rc != 0 or now_sha != base_sha:
        return _refuse(f"post-ff verification failed: {local} is at "
                       f"{now_sha[:9] if rc == 0 else '?'}, expected {base_sha[:9]}")
    _emit({"schema": SCHEMA, "step": "sync-main", "verdict": "ff",
           "from": local_sha[:9], "to": base_sha[:9], "commits": int(count or 0),
           "primary": str(primary)}, args.json,
          f"✓ sync-main: ff {local} {local_sha[:9]} -> {base_sha[:9]} ({count} commit(s))")
    return EXIT_OK


def _backend_paths_in_range(primary: Path, lo: str, hi: str) -> list[str]:
    """Changed files under backend/ across lo..hi (informational: which deploy would
    trigger the felix reconciler's production rollout). The authoritative path filter
    lives in kg_reconcile.sh; this is a heads-up, not a gate. This `backend/` prefix is
    a SUPERSET of the reconciler's narrower regex (which excludes backend/docs, data,
    VERSION, uv.lock, …) — so it can only OVER-warn ("rollout coming" when the
    reconciler will no-op), never under-warn a real rollout."""
    rc, out = _git(["diff", "--name-only", f"{lo}..{hi}"], cwd=primary)
    if rc != 0:
        return []
    return [ln for ln in out.splitlines() if ln.startswith("backend/")]


def _guarded_advance(*, src_branch: str, dest_branch: str, production: bool, step: str,
                     commit: bool, as_json: bool, state: str | None) -> int:
    """Guarded fast-forward publish of local `src_branch` to `origin/dest_branch`.

    The shared engine behind the two trunk-publish verbs of the three-plane model:
      * `sync`   (backup plane): main → origin/main — a zero-side-effect mirror. The
        reconciler does NOT watch origin/main, so this is pure backup.
      * `deploy` (release plane): main → origin/prod — the felix reconciler watches
        origin/prod and turns a backend delta into a health-gated production rollout
        (its own auto-rollback). This is the ONE deliberate production touch.
    Refuse unless the primary is checked out on `src_branch` with origin/`dest_branch`
    a strict ANCESTOR of local (a clean ff — never a force); noop when already at the
    same sha; first publish when origin/`dest_branch` is absent. dry-run default. When
    `production`, surface the backend files coming in range so the operator knows a
    rollout will fire."""
    blocked = _freeze_guard(state, step, as_json)
    if blocked is not None:
        return blocked

    primary = primary_root()

    def _refuse(reason: str) -> int:
        _emit({"schema": SCHEMA, "step": step, "verdict": "refused",
               "reason": reason, "primary": str(primary)}, as_json,
              f"✗ {step} refused: {reason}")
        return EXIT_BLOCK

    cur = _current_branch(str(primary))
    if cur != src_branch:
        where = "a detached HEAD" if cur is None else f"{cur!r}"
        return _refuse(f"primary checkout is on {where}, not {src_branch!r} — {step} "
                       f"publishes the local trunk")

    frc, fout = _fetch()
    if frc != 0:
        return _refuse(f"fetch failed — cannot compare against origin: {fout[:200]}")
    src_ref = f"refs/heads/{src_branch}"
    upstream = f"origin/{dest_branch}"
    rc, local_sha = _git(["rev-parse", src_ref], cwd=primary)
    rc2, up_sha = _git(["rev-parse", upstream], cwd=primary)
    if rc != 0:
        return _refuse(f"cannot resolve local {src_branch!r}")
    if rc2 != 0:
        up_sha = ""  # origin has no such branch yet — first publish
    if up_sha and local_sha == up_sha:
        _emit({"schema": SCHEMA, "step": step, "verdict": "noop",
               "sha": local_sha[:9], "primary": str(primary)}, as_json,
              f"# {step}: noop — origin/{dest_branch} already at {local_sha[:9]}")
        return EXIT_OK
    if up_sha:
        anc, _ = _git(["merge-base", "--is-ancestor", upstream, src_ref], cwd=primary)
        if anc != 0:
            return _refuse(f"origin/{dest_branch} has commits local {src_branch!r} lacks "
                           f"— reconcile first (sync-main / pull); {step} never force-pushes")
    backend = (_backend_paths_in_range(primary, upstream if up_sha else EMPTY_TREE, src_ref)
               if production else [])
    _, count = _git(["rev-list", "--count",
                     (f"{upstream}..{src_ref}" if up_sha else src_ref)], cwd=primary)
    if production:
        rollout = ("a PRODUCTION rollout (backend changed)" if backend
                   else "no rollout (no backend change)")
    else:
        rollout = "no production effect (backup mirror)"

    if not commit:
        payload: dict[str, Any] = {"schema": SCHEMA, "step": step, "verdict": "dry-run",
                                   "from": up_sha[:9] if up_sha else None, "to": local_sha[:9],
                                   "commits": int(count or 0), "primary": str(primary)}
        if production:
            payload["backend_files"] = backend
            payload["would_roll_out"] = bool(backend)
        _emit(payload, as_json,
              (f"# {step} (dry-run)\n  would push {src_branch} {local_sha[:9]} -> "
               f"origin/{dest_branch} ({count} commit(s)) → {rollout}\n"
               + (f"  backend files: {', '.join(backend[:8])}"
                  f"{' …' if len(backend) > 8 else ''}\n" if backend else "")
               + "  (--commit to publish)"))
        return EXIT_OK

    prc, pout = _git(["push", "origin", f"{src_ref}:{dest_branch}"], cwd=primary)
    if prc != 0:
        return _refuse(f"git push failed: {pout[:300]}")
    # verify against origin's ACTUAL ref (ls-remote), not the local remote-tracking ref
    # git just wrote — an independent confirmation that the publish really took.
    rc, ls = _git(["ls-remote", "origin", dest_branch], cwd=primary)
    now = ls.split()[0] if rc == 0 and ls.strip() else ""
    if now != local_sha:
        return _refuse(f"post-push verification failed: origin/{dest_branch} is at "
                       f"{now[:9] if now else '?'}, expected {local_sha[:9]}")
    payload = {"schema": SCHEMA, "step": step, "verdict": "pushed",
               "to": local_sha[:9], "commits": int(count or 0), "primary": str(primary)}
    if production:
        payload["backend_files"] = backend
        payload["rolled_out"] = bool(backend)
    _emit(payload, as_json,
          (f"✓ {step}: pushed {src_branch} -> origin/{dest_branch} {local_sha[:9]} "
           f"({count} commit(s)) → {rollout}\n"
           + ("  the felix reconciler will build + health-gate + auto-rollback; "
              "watch its verdict or wordnexus.lol version" if (production and backend)
              else ("  no reconciler rollout (origin advanced, backend unchanged)" if production
                    else "  backup only — the reconciler does not watch this ref"))))
    return EXIT_OK


def _dest_from_upstream(upstream: str, step: str, as_json: bool) -> str | None:
    """origin/<branch> → <branch>; emit a usage error and return None otherwise."""
    if not upstream.startswith("origin/"):
        _emit({"schema": SCHEMA, "step": step, "error": "upstream must be an origin/* ref",
               "upstream": upstream}, as_json,
              f"✗ upstream must be an origin/* ref, got {upstream!r}")
        return None
    return upstream.split("/", 1)[1]


def cmd_sync(args: argparse.Namespace) -> int:
    """Backup plane: mirror the local trunk to origin/main (local→origin) — the
    zero-side-effect backup. Distinct from `sync-main` (origin→local, catch a stale
    checkout up). The reconciler watches origin/prod, not origin/main, so this push
    has no production effect."""
    dest = _dest_from_upstream(args.upstream, "sync", args.json)
    if dest is None:
        return EXIT_USAGE
    return _guarded_advance(src_branch=BASE_DEFAULT, dest_branch=dest, production=False,
                            step="sync", commit=args.commit, as_json=args.json, state=args.state)


def cmd_deploy(args: argparse.Namespace) -> int:
    """Release plane: advance origin/prod to the local trunk — the ONE deliberate
    production touch. The felix reconciler (watching origin/prod) turns a backend delta
    into a health-gated rollout with its own auto-rollback. Guarded ff push, dry-run
    default; surfaces the backend files in range so a rollout is never a surprise."""
    dest = _dest_from_upstream(args.upstream, "deploy", args.json)
    if dest is None:
        return EXIT_USAGE
    return _guarded_advance(src_branch=BASE_DEFAULT, dest_branch=dest, production=True,
                            step="deploy", commit=args.commit, as_json=args.json, state=args.state)


def cmd_gate(args: argparse.Namespace) -> int:
    """Impact-based verification: route changed files to the existing gate tools, run
    them, aggregate a verdict, and record it for cutover."""
    worktree = _norm(args.worktree)
    if not Path(worktree).is_dir():
        _emit({"schema": GATE_SCHEMA, "error": "worktree not found", "worktree": worktree},
              args.json, f"✗ worktree not found: {worktree}")
        return EXIT_USAGE

    changed = _changed_vs_base(worktree, args.base)
    # anchor test-existence at the WORKTREE so a test file added in this very diff
    # is seen (the primary checkout may not have it yet)
    plan = plan_gates(changed,
                      ops_test_exists=lambda rel: (Path(worktree) / rel).is_file())
    results: list[dict[str, Any]] = []
    if not args.plan_only:
        for spec in plan:
            results.append(_run_gate(spec, worktree))
    verdict = aggregate_verdict(results) if not args.plan_only else "planned"

    head = _head_sha(worktree)
    record = {"schema": GATE_SCHEMA, "worktree": worktree, "base": args.base,
              "head_sha": head, "changed_files": changed,
              "plan": [{"name": g["name"], "level": g["level"], "category": g["category"],
                        "cmd": g.get("cmd")} for g in plan],
              "gates": results, "verdict": verdict}
    if not args.plan_only:
        rec_path = _gate_record_path(args.state, worktree)
        rec_path.parent.mkdir(parents=True, exist_ok=True)
        rec_path.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n")

    lines = [f"# gate {verdict.upper()}  ({len(changed)} changed file(s), "
             f"{len(plan)} gate(s))"]
    for r in results:
        mark = {"pass": "✓", "warn": "⚠", "block": "✗"}.get(r["status"], "?")
        lines.append(f"  {mark} {r['name']} [{r['status']}] — {r.get('summary','')}")
    if not plan:
        lines.append("  (no impact-based gates selected for these changes)")
    _emit(record, args.json, "\n".join(lines))
    if args.plan_only:
        return EXIT_OK
    return EXIT_OK if verdict in ("pass", "warn") else EXIT_BLOCK


def cmd_cutover(args: argparse.Namespace) -> int:
    """Require a fresh non-block gate verdict, then integrate the worktree into the
    LOCAL trunk: rebase onto local `main` and fast-forward the primary checkout's
    `main` to it — OFFLINE, no push, no deploy. (Publishing to origin, and thereby
    production, is the separate `deploy` step.) A `warn` verdict LANDS ("landed with
    warnings" — its disposition belongs to the driving agent); only `block` (and a
    stale/absent verdict) refuses."""
    blocked = _freeze_guard(args.state, "cutover", args.json)
    if blocked is not None:
        return blocked
    worktree = _norm(args.worktree)
    if not Path(worktree).is_dir():
        _emit({"schema": SCHEMA, "step": "cutover", "error": "worktree not found",
               "landed": False}, args.json, f"✗ worktree not found: {worktree}")
        return EXIT_USAGE

    rec_path = _gate_record_path(args.state, worktree)
    head = _head_sha(worktree)
    refuse: str | None = None
    verdict: str | None = None
    warnings: list[str] = []
    if not rec_path.exists():
        refuse = "no gate verdict on record — run `gate` first"
    else:
        rec = json.loads(rec_path.read_text())
        verdict = rec.get("verdict")
        if rec.get("head_sha") != head:
            refuse = ("gate verdict is stale (recorded HEAD "
                      f"{str(rec.get('head_sha'))[:8]} != current {head[:8]}) — re-run `gate`")
        elif verdict == "block":
            refuse = "gate verdict is 'block' — fix the blocking gate(s) and re-run `gate`"
        elif verdict not in ("pass", "warn"):
            refuse = f"gate verdict is {verdict!r}, not pass/warn — run `gate` first"
        elif verdict == "warn":
            # a warn LANDS; surface which gates warned so the record is explicit.
            warnings = [g.get("name") for g in rec.get("gates", [])
                        if g.get("status") == "warn"]
    if refuse:
        _emit({"schema": SCHEMA, "step": "cutover", "error": refuse, "landed": False,
               "worktree": worktree}, args.json, f"✗ cutover refused: {refuse}")
        return EXIT_BLOCK

    local = args.base.split("/", 1)[1] if "/" in args.base else args.base
    primary = primary_root()
    wt_branch = _current_branch(worktree)
    warn_line = (f"\n  landed with warnings: {', '.join(warnings)}" if warnings else "")
    if wt_branch is None:
        _emit({"schema": SCHEMA, "step": "cutover", "error": "worktree is on a detached "
               "HEAD — nothing to integrate", "landed": False, "worktree": worktree},
              args.json, "✗ cutover refused: worktree is on a detached HEAD")
        return EXIT_USAGE

    if not args.commit:
        payload = {"schema": SCHEMA, "step": "cutover", "mode": "dry-run", "landed": False,
                   "branch": wt_branch, "target": local, "verdict": verdict,
                   "warnings": warnings}
        _emit(payload, args.json,
              f"# cutover (dry-run)\n  would rebase {wt_branch} onto {local}, then "
              f"ff local {local} to it (offline — no push, no deploy){warn_line}\n"
              f"  (--commit to land)")
        return EXIT_OK

    # Serialize the trunk advance; rebase onto the CURRENT local trunk INSIDE the lock
    # so a peer cutover that just advanced it is picked up (not raced past).
    with _main_advance_lock(primary):
        guard = _primary_ff_ready(primary, local)
        if guard:
            reason, extra = guard
            _emit({"schema": SCHEMA, "step": "cutover", "error": reason, "landed": False,
                   "primary": str(primary), **extra}, args.json,
                  f"✗ cutover refused: {reason}")
            return EXIT_BLOCK
        rrc, rout = _git(["rebase", local], cwd=worktree)
        if rrc != 0:
            _git(["rebase", "--abort"], cwd=worktree)
            _emit({"schema": SCHEMA, "step": "cutover", "error": "rebase failed (aborted)",
                   "detail": rout, "landed": False}, args.json,
                  f"✗ rebase onto {local} failed (aborted):\n{rout}")
            return EXIT_BLOCK
        sha = _head_sha(worktree)
        # advance the local trunk by a ff-only merge IN the primary (main lives there).
        mrc, mout = _git(["merge", "--ff-only", wt_branch], cwd=primary)
        if mrc != 0:
            _emit({"schema": SCHEMA, "step": "cutover", "error": f"ff of {local} failed: "
                   f"{mout[:200]}", "landed": False}, args.json,
                  f"✗ ff of local {local} failed:\n{mout}")
            return EXIT_BLOCK
        vrc, now = _git(["rev-parse", local], cwd=primary)
        if vrc != 0 or now != sha:
            _emit({"schema": SCHEMA, "step": "cutover", "error": "post-ff verification "
                   f"failed: {local} is at {now[:8] if vrc == 0 else '?'}, expected "
                   f"{sha[:8]}", "landed": False}, args.json, "✗ post-ff verification failed")
            return EXIT_BLOCK

    payload = {"schema": SCHEMA, "step": "cutover", "mode": "committed", "landed": True,
               "sha": sha, "target": local, "branch": wt_branch, "verdict": verdict,
               "warnings": warnings}
    _emit(payload, args.json,
          f"✓ cutover: ff local {local} -> {sha[:8]} (offline; run `deploy` to "
          f"publish){warn_line}")
    return EXIT_OK


def cmd_resolve(args: argparse.Namespace) -> int:
    """Landed-floor guard, then registry resolve merged → worktree remove + branch -D
    (local + remote) + drop the gate-record cache."""
    worktree = _norm(args.worktree)
    branch = args.branch or (_current_branch(worktree) if Path(worktree).is_dir() else None)
    if not branch:
        _emit({"schema": SCHEMA, "step": "resolve", "error": "cannot determine branch "
               "(pass --branch, or point --worktree at a live worktree)"}, args.json,
              "✗ cannot determine branch — pass --branch or a live --worktree")
        return EXIT_USAGE

    # nit2 LANDED FLOOR: resolve is a force-discard (worktree remove --force + branch -D).
    # Called out of order (before cutover) it would vaporize unlanded work. Refuse a
    # branch whose net change is NOT already in base — using the registry's tree-diff
    # containment (never git cherry; same authority the sweep trusts). --force overrides.
    if not args.force:
        _fetch()  # base may have advanced; compare against the fresh tip
        if not wr.landed_in_base(args.base, branch):
            reason = (f"branch {branch!r} is not landed in {args.base} (tree-diff) — "
                      "resolve would force-discard unlanded work; run `cutover` first "
                      "or pass --force")
            _emit({"schema": SCHEMA, "step": "resolve", "error": "refused",
                   "reason": reason, "branch": branch, "landed": False}, args.json,
                  f"✗ resolve refused: {reason}")
            return EXIT_BLOCK

    # teardown MUST run from the primary root: step 1 removes the target worktree,
    # which may be the very directory this process was invoked from. For the same
    # reason the gate-cache path is resolved NOW — its default-state branch derives
    # the ledger anchor from the process cwd, which teardown may be about to remove.
    root = primary_root()
    gate_cache = _gate_record_path(args.state, worktree)
    steps: list[dict[str, Any]] = []

    def _plan(label: str, gargs: list[str], cwd: Path) -> None:
        steps.append({"label": label, "cmd": "git " + " ".join(gargs),
                      "gargs": gargs, "cwd": str(cwd)})

    if Path(worktree).is_dir():
        _plan("remove worktree", ["worktree", "remove", "--force", worktree], root)
    _plan("delete local branch", ["branch", "-D", branch], root)
    if _remote_branch_exists(branch):
        _plan("delete remote branch", ["push", "origin", "--delete", branch], root)

    if not args.commit:
        payload = {"schema": SCHEMA, "step": "resolve", "mode": "dry-run", "branch": branch,
                   "plan": [{"label": s["label"], "cmd": s["cmd"]} for s in steps]}
        human = ("# resolve (dry-run) — ledger -> merged, then:\n"
                 + "\n".join(f"  {s['cmd']}   # {s['label']}" for s in steps)
                 + "\n  (--commit to execute)")
        _emit(payload, args.json, human)
        return EXIT_OK

    # ledger closure first (idempotent even if the git teardown partially failed before).
    _registry(["resolve", *_state_arg(args.state), "--branch", branch, "--status", "merged"])
    results = []
    failures = 0
    for s in steps:
        rc, out = _git(s["gargs"], cwd=Path(s["cwd"]))
        results.append({"label": s["label"], "cmd": s["cmd"], "ok": rc == 0,
                        "detail": out[:200] if rc != 0 else ""})
        if rc != 0:
            failures += 1

    # nit3 ZERO RESIDUE: also drop this worktree's gate-record cache (the per-machine
    # verdict file gate wrote beside the ledger). Otherwise a stale verdict lingers
    # after the worktree it described is gone. (Path was resolved pre-teardown.)
    gate_cache_removed = False
    if gate_cache.exists():
        try:
            gate_cache.unlink()
            gate_cache_removed = True
        except OSError:
            pass

    payload = {"schema": SCHEMA, "step": "resolve", "mode": "committed", "branch": branch,
               "resolved": "merged", "executed": results, "failures": failures,
               "gate_cache_removed": gate_cache_removed}
    human = ["# resolve (committed): ledger -> merged"]
    for r in results:
        human.append(f"  {'✓' if r['ok'] else '✗'} {r['cmd']}   # {r['label']}")
    if gate_cache_removed:
        human.append("  ✓ dropped gate-record cache")
    _emit(payload, args.json, "\n".join(human))
    return EXIT_OK if failures == 0 else EXIT_BLOCK


# ============================================================================
# argparse
# ============================================================================
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="worktree_orchestrate.py",
        description=("Worktree orchestrator (P3) — carry an intent from a fresh session "
                     "to cutover into main. Conducts P1/P2 + the existing gate tools; "
                     "re-implements no gate. See the module docstring for the loop."),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = p.add_subparsers(dest="cmd")

    def add_common(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("--state", default=None,
                        help="registry ledger path (default: shared <git-common-dir>/.cache)")
        sp.add_argument("--json", action="store_true", help="emit JSON")

    def add_base(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("--base", default=BASE_DEFAULT,
                        help=f"baseline ref (default: {BASE_DEFAULT})")

    pf = sub.add_parser("preflight", help="fetch + registry sweep --exclude-current "
                        "(clear crash residue; dry-run default)")
    add_common(pf)
    pf.add_argument("--commit", action="store_true", help="execute sweep clearance")
    pf.add_argument("--allow-offline", action="store_true",
                    help="do not fail preflight when the fetch cannot reach origin")
    pf.set_defaults(func=cmd_preflight)

    op = sub.add_parser("open", help="git worktree add + registry register")
    add_common(op)
    add_base(op)
    op.add_argument("--intent", required=True, help="free-text intent (drives branch type)")
    op.add_argument("--slug", required=True, help="kebab-case slug for branch + path")
    op.set_defaults(func=cmd_open)

    ad = sub.add_parser("adopt", help="register an ALREADY-existing worktree in the "
                        "ledger (bootstrap fallback: bare `git worktree add` needs no "
                        "tooling — adopt afterwards from inside the checkout)")
    add_common(ad)
    add_base(ad)
    ad.add_argument("--worktree", default=None, help="worktree path (default: cwd; "
                    "a subdir resolves to its worktree root)")
    ad.add_argument("--intent", required=True,
                    help="why this worktree exists (recorded in the ledger)")
    ad.set_defaults(func=cmd_adopt)

    sm = sub.add_parser("sync-main", help="guarded ff of the PRIMARY checkout's local "
                        "main to origin/main — refuses unless tracked-clean, on main, "
                        "no merge/rebase in flight, and strictly behind (lossless by "
                        "construction; dry-run default)")
    add_common(sm)
    # sync-main is intrinsically origin→local, so its base is origin/* regardless of
    # the local-centric BASE_DEFAULT the other primitives use.
    sm.add_argument("--base", default="origin/main",
                    help="upstream ref to catch local main up to (default: origin/main)")
    sm.add_argument("--commit", action="store_true",
                    help="execute the ff (default: dry-run)")
    sm.set_defaults(func=cmd_sync_main)

    sy = sub.add_parser("sync", help="backup plane: mirror the local trunk to "
                        "origin/main (local→origin) — a zero-side-effect backup. "
                        "Distinct from sync-main (origin→local). The reconciler watches "
                        "origin/prod, not origin/main, so this has no production effect "
                        "(guarded ff, dry-run default)")
    add_common(sy)
    sy.add_argument("--upstream", default="origin/main",
                    help="origin ref to mirror to (default: origin/main)")
    sy.add_argument("--commit", action="store_true",
                    help="execute the push (default: dry-run)")
    sy.set_defaults(func=cmd_sync)

    dp = sub.add_parser("deploy", help="release plane: advance origin/prod to the local "
                        "trunk (the one deliberate production touch) — guarded ff push; "
                        "the felix reconciler (watching origin/prod) turns a backend "
                        "delta into a health-gated rollout (dry-run default)")
    add_common(dp)
    dp.add_argument("--upstream", default="origin/prod",
                    help="origin ref to publish to (default: origin/prod)")
    dp.add_argument("--commit", action="store_true",
                    help="execute the push (default: dry-run)")
    dp.set_defaults(func=cmd_deploy)

    fz = sub.add_parser("freeze", help="stop-the-world surgery lock: `on` refuses new "
                        "births/landings/publishes (open/adopt/cutover/sync-main/"
                        "sync/deploy) until `off`; draining steps (resolve/sweep/"
                        "preflight/gate) stay allowed")
    add_common(fz)
    fz.add_argument("action", choices=["on", "off", "status"])
    fz.add_argument("--reason", default=None,
                    help="why the flow is frozen (required for `on`)")
    fz.add_argument("--force", action="store_true",
                    help="overwrite an existing freeze (default: refuse, surface it)")
    fz.set_defaults(func=cmd_freeze)

    ga = sub.add_parser("gate", help="impact-based verification; route changed files to "
                        "the existing gate tools + aggregate a verdict")
    add_common(ga)
    add_base(ga)
    ga.add_argument("--worktree", required=True, help="worktree path to gate")
    ga.add_argument("--plan-only", action="store_true",
                    help="print the selected gate plan without running anything")
    ga.set_defaults(func=cmd_gate)

    co = sub.add_parser("cutover", help="require a fresh gate pass, rebase onto local "
                        "trunk, ff the primary's local main to it — offline, no deploy "
                        "(dry-run default)")
    add_common(co)
    add_base(co)
    co.add_argument("--worktree", required=True, help="worktree path to cut over")
    co.add_argument("--commit", action="store_true",
                    help="land the ff into local main (default: dry-run)")
    co.set_defaults(func=cmd_cutover)

    rs = sub.add_parser("resolve", help="landed-floor + ledger -> merged + worktree "
                        "remove + branch -D (local/remote) + drop gate cache — no "
                        "residue (dry-run default)")
    add_common(rs)
    add_base(rs)
    rs.add_argument("--worktree", required=True, help="worktree path to resolve")
    rs.add_argument("--branch", default=None,
                    help="branch to resolve (default: the worktree's checked-out branch)")
    rs.add_argument("--force", action="store_true",
                    help="override the landed-floor (tear down even if the branch's work "
                         "is NOT yet in base — accepts the loss of unlanded work)")
    rs.add_argument("--commit", action="store_true", help="execute teardown (default: dry-run)")
    rs.set_defaults(func=cmd_resolve)

    return p


def main(argv: list[str] | None = None) -> int:
    tokens = list(argv) if argv is not None else sys.argv[1:]
    parser = build_parser()
    args = parser.parse_args(tokens)
    if not getattr(args, "func", None):
        parser.print_help()
        return EXIT_USAGE
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
