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

  open       registry register (= CLAIM) FIRST, then git worktree add
             (.claude/worktrees/<slug>, branch = <type>/<slug> where type is
             classify_intent(intent)) forked from LOCAL `main` (offline). The order
             matters: with `--backlog ID...` the register can REFUSE because another
             active record holds that ticket, and a loser must not be left holding a
             branch and a directory. A failed `worktree add` hands the claim back.
  adopt      register an ALREADY-existing worktree (bootstrap fallback: a bare
             `git worktree add` needs none of this tooling — adopt afterwards from
             inside). Registers the worktree ROOT; ledger + freeze lock anchor on the
             TARGET's git-common-dir, never the process cwd. Takes `--backlog ID...`
             too — a gate an adjacent entry point walks around is not a gate.
             Both forward the flag ONLY when it was given: `--backlog` with no ids
             parses to [] (not None), which is the registry's "give up the claim"
             branch, so forwarding it unconditionally released live claims.
  gate       IMPACT-BASED verification. Diffs the worktree against its base (local
             `main`), routes each touched surface to its existing gate tool, runs them,
             aggregates a pass/warn/block verdict, and RECORDS it (keyed by worktree +
             HEAD sha) so cutover can require a fresh pass. Runs the gates EXPLICITLY —
             the .githooks pre-commit is best-effort only and must not be relied on.
  land       take a FIFO turn, then run catchup -> gate -> cutover under it.
             The verb for converging SEVERAL worktrees: measured on a clone,
             ten lanes driving catchup/gate/cutover by hand landed 2 of 10
             (the trunk is single and the ff linear, so the first lander
             staled everyone else, and the recovery raced identically);
             through `land` the same ten landed 10 of 10 in 10 gate runs.
             Advisory: it only guarantees one pass if every lander uses it.
  integrate  the BATCH verb: fork one integration worktree off the local trunk,
             cherry-pick N branches into it in order, stop by NAME on a conflict
             (`--continue` after resolving, `--abort` to discard), and run the
             EXISTING `gate` ONCE on the merged result. It answers the one question
             per-branch gates structurally cannot: are these N pieces of work green
             TOGETHER. Measured 2026-08-06 on an eleven-branch batch — review of the
             integrated tree found five blocking defects, each green under its own
             branch's gate. Adds no pass/fail of its own: the verdict is `gate`'s and
             landing stays `cutover`'s (which already refuses a block verdict, so
             that rule keeps living in exactly one place). cherry-pick rather than
             merge, so a branch cannot smuggle in commits nobody named. dry-run
             default.
  catchup    the step `gate` and `cutover` BOTH send you to when the trunk moved
             under the branch: rebase the worktree onto local `main`. A CLEAN rebase
             — any conflict aborts and comes back to you. It is a verb rather than a
             sentence because a refusal that says "go run `git rebase main`" is a
             routing decision pointed at raw git; the verb keeps the remedy inside
             the flow (and inside `land`). It once auto-resolved conflicts confined
             to a generated file by re-running its generator; that apparatus went
             away with the file (IMP-20260807-b9526c) — see `_rebase_onto`, which is
             the authority on what this actually does. HEAD moves, so `gate` must be
             re-run afterwards. dry-run default.
  cutover    require a fresh NON-BLOCK gate verdict (verdict in {pass, warn} AND
             recorded HEAD == current HEAD) → rebase worktree onto local `main` → ff
             the primary checkout's local `main` to it (serialized by a lock; the
             primary must be on main + tracked-clean, since a ff updates its files)
             → POST-LANDING REPAIR inside the same lock: the rebase ran after the
             gate and rewrote branch shas, so ledger `fixed_by` values only become
             correct at landing time; `backlog.py reanchor --commit` + `render
             --commit` + `validate --baseline-check` run here and commit what they
             produce (`Review-Exempt: machine-repair`, a path-checked token). Local
             main's tip is therefore `trunk_tip`, which may differ from the gated
             `sha`. OFFLINE — no push, no deploy. A `warn` is advisory: it LANDS ("landed with
             warnings") — the driving agent owns a warn's disposition, so the tool must
             not hard-refuse it; only `block` (and a stale/absent verdict) refuses.
             dry-run default.
  resolve    target identity FIRST (the branch comes from `git worktree list
             --porcelain`, never from a `rev-parse` that would walk up into the
             enclosing checkout; base/trunk/other-worktree branches and the primary
             are refused outright) → landed-floor (refuse to force-discard a branch
             not yet in base, unless --force) → registry resolve <branch> merged →
             git worktree remove (preceded by a streamed `rm -rf` when the entry is
             prunable, i.e. an earlier teardown was interrupted) + branch -D (local,
             and origin if present) + drop the gate-record cache → ledger closed, no
             residue. Fail-fast: a failed critical step aborts the rest.
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
             open/adopt/catchup/integrate/cutover/sync-main/sync/deploy refuse (every
             step that gives birth, rewrites history or advances a ref); draining
             steps (resolve, sweep, preflight, gate) stay allowed so the flow can be
             quiesced for repo surgery (history rewrite, gc, shared hooks/config).

Exit codes: 0 ok | 64 usage error | 1 blocked (gate block / cutover refused /
            open refused because a backlog ticket is already claimed / partial).
"""

from __future__ import annotations

import argparse
import errno
import hashlib
import io
import json
import os
import re
import shutil
import shlex
import subprocess
import sys
import time
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

# Reuse P2 in-process — never re-implement register / resolve / sweep / state paths.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import worktree_registry as wr  # noqa: E402
from lib.provenance import logical_tool_path, sha256_file  # noqa: E402
from lib.streaming_command import run_streamed_command  # noqa: E402

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


_LIVE_ONLY_UITEST_CLASSES = {"LiveDemoAccessUITests"}


# Shell tools whose test is named after what it exercises rather than after the file.
# Convention (`ops/X.sh` -> `ops/tests/test_X.sh` or `ops/test_X.sh`) resolves most of
# them; this is the remainder.
#
# Every entry below was traced to a line that RUNS the script, not one that mentions it.
# That distinction is the whole risk here, and inference from names is bad at it: of the
# nine entries first written, two were false — test_ios_cache_evict.sh covers
# lib/ios_cache_evict.sh rather than ios_clean_derived_data.sh, and test_release.sh only
# `[[ -f ]]`-checks release_changelog.sh and greps release.sh for a mention of it, so a
# release_changelog.sh gutted to `exit 0` would have passed a BLOCK gate.
#
# The contract test is a necessary condition, not a sufficient one: it requires the
# target to exist, to mention the script, and to be unreachable by convention — the
# release_changelog entry satisfied all three while covering nothing. Proving coverage
# mechanically means mutating the script and requiring the target to go red; filed as
# IMP-0055 rather than bolted on here.
OPS_SHELL_TEST_ALIASES: dict[str, str] = {
    "ops/devops_kg_safe.sh": "ops/tests/test_devops_safe_lightsail_guard.sh",
    "ops/install_lldb_forensics.sh": "ops/tests/test_lldb_crash_forensics.sh",
    "ops/ios_test.sh": "ops/test_ios_test_discovery.sh",
    "ops/ios_build.sh": "ops/test_ios_ops.sh",
    "ops/ios_archive.sh": "ops/test_ios_ops.sh",
    "ops/release_bump.sh": "ops/test_release.sh",
    "ops/review_flip_probe.sh": "ops/tests/test_review_probe.sh",
    # test_script_help.sh EXECUTES it (its full-width section delegates there), which
    # is the standard this table demands. `ops-shell-scan` also runs the script on
    # every .sh diff, but that is the scanner doing its job, not a test of it.
    "ops/shell_scan.sh": "ops/tests/test_script_help.sh",
}

# Test scripts that must NOT be routed as a block gate, each with the reason. A gate
# that can only ever be red is as harmful as one that can only be green, in the other
# direction: it blocks everyone and the only visible way past it is to leave the process
# (IMP-0039). Naming them here keeps them in the `ops-shell-untested` advisory, which
# says so out loud, instead of silently arming a gate nobody can pass.
OPS_SHELL_UNROUTABLE_TESTS: dict[str, str] = {
    "ops/test_ops.sh": "the aggregate runner — it invokes every group, including the "
                       "ones excluded from CI for needing local assets, so its colour is "
                       "a property of the machine rather than of the change. Duration is "
                       "the reason that holds everywhere: many minutes",
}


def _ops_shell_test_candidates(rel: str) -> list[str]:
    """Test files that could cover a changed shell script, most specific first."""
    base = rel.rsplit("/", 1)[-1]
    if rel in OPS_SHELL_UNROUTABLE_TESTS:
        return []
    if base.startswith("test_"):
        return [rel]  # a changed test script is its own gate (path-exact — no collision)
    alias = OPS_SHELL_TEST_ALIASES.get(rel)
    # The basename convention only holds inside `ops/` and at the repo root. Once the
    # routing filter widened past those (IMP-0057), `lab/podcast/start.sh` would resolve
    # to `ops/test_start.sh` — the candidate for the ROOT `start.sh` — and be reported
    # covered by a test that never executes a line of it. Elsewhere: named alias only.
    if not (rel.startswith("ops/") or "/" not in rel):
        return [alias] if alias else []
    return [c for c in (f"ops/tests/test_{base}", f"ops/test_{base}", alias) if c]


# Data-plane control files (yml/yaml) that own an executable contract, and the tools
# that assert it. Until 2026-08-05 a yml selected NOTHING, which was defensible while
# `ops/ui_quality_plane.yml` merely LISTED mechanisms — but IMP-0041 moved the argv the
# UI quality gate executes into that file, so a typo there now silently shrinks what the
# gate runs, and `docs/registry.yml` decides which docs are linted at all. Both are
# reachable only through a tool; neither is reachable through `docs/**.md` or `ops/**.py`.
#
# There is deliberately no universal syntax floor here, unlike `bash -n` for shell: no
# YAML parser ships with the stdlib, and this orchestrator is zero-dependency on purpose
# (it has to run in the bootstrap case where the checkout predates the toolchain).
# Hand-rolling a parser to gate on would make the verdict a property of that parser.
# Unowned yml is therefore NAMED in a warn, not silently swallowed.
BACKLOG_STORE_DIR = "docs/runbook/backlog/"

RESOLVED_STATUSES = ("fixed", "wont-fix")


def _refuse_unclaimable(root: Path, wanted: list[str], args, step: str,
                        branch: str) -> int | None:
    """The claim gate, shared by `open` and `adopt`. EXIT_BLOCK or None.

    ONE implementation because `adopt` is the bootstrap path into the SAME ledger:
    a gate an adjacent entry point walks around is not a gate, and the ledger's
    "at most one worktree per ticket" would hold only for the worktrees that
    happened to be born through `open`. That argument is already written on the
    `adopt --backlog` parser for the conflict check; it applies unchanged here.

    Runs BEFORE the claim, never after: a refusal that has already taken the ticket
    has to hand it back, and the hand-back is exactly the step that fails when
    something else has gone wrong.
    """
    blockers = _unclaimable(root / BACKLOG_STORE_DIR, wanted)
    if getattr(args, "allow_ungroomed", False):
        # Downgrades ONLY `ungroomed`. A typo and an already-closed ticket stay
        # refusals: neither has an honest reading in which the agent should proceed.
        waived = [p for p in blockers if p["kind"] == "ungroomed"]
        blockers = [p for p in blockers if p["kind"] != "ungroomed"]
        if waived:
            # Named, not silent — the escape hatch has to be as countable in the log
            # as `acceptance_manual` is in the store.
            print(f"[worktree][claim] WARNING taking ungroomed ticket(s) as an "
                  f"investigation: {', '.join(p['id'] for p in waived)}",
                  file=sys.stderr, flush=True)
    if not blockers:
        return None
    _emit({"schema": SCHEMA, "step": step, "error": "ticket not claimable",
           "branch": branch, "backlog": wanted, "problems": blockers},
          args.json,
          "\u2717 cannot claim:\n" + "\n".join(
              f"  {p['id']} \u2014 {p['kind']}\n    {p['repair']}" for p in blockers))
    return EXIT_BLOCK


def _unclaimable(store_dir: Path, ids: list[str]) -> list[dict]:
    """Which of these tickets must not be handed to an agent, and why.

    `worktree_registry` checks only the SHAPE of a `--backlog` id, and that is the
    right call there — it deliberately does not depend on `backlog.py`. But the
    orchestrator knows where the store is, so the check it can make is the one that
    matters, and until now nobody made it. Measured: `open --backlog IMP-typo`
    claimed a ticket that does not exist (the ledger then held an id nobody could
    ever close), and `open --backlog <ungroomed>` handed an agent a ticket carrying
    no plan, no acceptance and no fix site — which is precisely what grooming exists
    to prevent. Both exited 0.

    Reads the JSON directly rather than shelling out to `backlog.py list --json`:
    this runs on the claim path, before a worktree exists, and the bootstrap case
    requires the orchestrator to work when the rest of the toolchain does not. The
    predicate is `groomed_by`, the same badge `list --ungroomed` uses — the store's
    own definition, not a second one invented here.

    An unreadable entry is `not-in-store`, NOT a pass: "could not check" turning
    into "fine" is the shape this repo keeps filing entries about.
    """
    problems: list[dict] = []
    for entry_id in ids:
        path = Path(store_dir) / f"{entry_id}.json"
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            problems.append({
                "id": entry_id, "kind": "not-in-store",
                "repair": f"check the id — `ops/backlog.py list --json` lists what "
                          f"exists; nothing named {entry_id} is in {store_dir}"})
            continue
        if payload.get("status") in RESOLVED_STATUSES:
            problems.append({
                "id": entry_id, "kind": "already-resolved",
                "status": payload.get("status"),
                "repair": f"`ops/backlog.py show {entry_id}` — this one is already "
                          f"{payload.get('status')}; reopen it with `update "
                          f"{entry_id} --status open --commit` if that is wrong"})
        elif not str(payload.get("groomed_by") or "").strip():
            problems.append({
                "id": entry_id, "kind": "ungroomed",
                # The flag list is the whole value of this hint, so it has to track
                # what `validate` actually demands. `--brief`/`--scope` joined that
                # set on BRIEF_REQUIRED_SINCE; a repair line that omits them teaches
                # a command whose result is refused, which is worse than no hint —
                # the agent believes it followed the tool.
                "repair": f"groom it first: `ops/backlog.py update {entry_id} --plan "
                          f"… --acceptance … --fix-site … --acceptance-cmd … "
                          f"--brief … --scope … "
                          f"--groomed-at <today> --groomed-by <you> --commit` "
                          f"(--brief/--scope are one plain sentence each, written "
                          f"for whoever SORTS the board, not for you: what breaks "
                          f"and who feels it, and how big the change is). "
                          f"To take it as an INVESTIGATION rather than a fix, pass "
                          f"--allow-ungroomed. "
                          # Two different needs, so two different exits, and the
                          # second one used to be missing. Everything above answers
                          # "I need THIS ticket" — it hands back a grooming chore to
                          # a caller who may not have wanted this ticket at all, only
                          # A ticket. The common way to arrive here is picking an id
                          # off a list that does not distinguish claimable from not,
                          # and for that caller the cheapest correct move is to take
                          # a different one. Named, not called: this refusal runs on
                          # the claim path before any worktree exists, where the
                          # orchestrator must keep working even when the rest of the
                          # toolchain does not (see this function's docstring).
                          f"If you did not need THIS ticket specifically, "
                          f"`ops/backlog.py dispatch` lists the ones that are "
                          f"already groomed, unresolved and unclaimed — i.e. the "
                          f"ones you can take right now without grooming anything"})
    return problems

DATA_PLANE_OWNERS: dict[str, tuple[list[str], ...]] = {
    "ops/ui_quality_plane.yml": (
        ["ops/ui_quality_plane.py", "validate"],
        ["ops/tests/test_ui_quality_plane.sh"],
    ),
    "docs/registry.yml": (
        ["ops/docs_lint.sh", "--registry"],
    ),
}


# Paths that legitimately select no gate, each with the reason. Deny-by-default:
# anything matching neither a gate nor a rule here shows up as `uncovered`.
# Kept as a module constant beside plan_gates (not a new yml) because it is the
# complement of the same hand-written routing judgement, guarded by the same
# contract tests. Rules are path patterns, never file enumerations, so a new file
# under an already-declared tree needs no edit.
NEUTRAL_RULES: tuple[tuple[str, str], ...] = (
    ("backups/", "本機備份產物，不影響任何 runtime 或 build"),
    ("frozen/", "凍結快照，依定義不再變更行為"),
    ("promotion/", "行銷素材產物，由 catalog/App Review 平面自行驗證"),
    (".claude/", "agent skill / worktree 工作區文本，由 docs registry 涵蓋"),
    ("README.md", "根層 prose，無機械 gate"),
    (".gitignore", "不影響 runtime 或 build 行為"),
)


# shell gate 掃全 repo 的 *.sh，減去這份具名排除清單。frozen/ 是刻意冷凍的快照：
# 掛上 gate 只會讓 ops-shell-untested advisory 永遠列著 7 個沒人打算補測試的檔，
# 而 advisory 一旦長期有雜訊就沒人看——比沒有 advisory 更糟。排除必須具名。
#
# `.claude/` 刻意不在此列，即使 NEUTRAL_RULES 也有一條同名的樹：那條的理由是
# 「agent skill 文本，由 docs registry 涵蓋」，對 `.claude/skills/app-debug/
# find-polluter.sh` 這支可執行腳本不成立（同 IMP-0054 打掉的那批假理由）。
SHELL_GATE_EXCLUDED_TREES: tuple[tuple[str, str], ...] = (
    ("frozen/", "凍結快照，依定義不再變更行為"),
)


def _neutral_rule(rel: str) -> str | None:
    """The declared reason this path may select no gate, or None. Shared with the yml
    router so a tree that is already neutral is not re-adopted and warned about twice."""
    return next((pat for pat, _ in NEUTRAL_RULES
                 if rel == pat or rel.startswith(pat)), None)


def _coverage(changed_files: list[str], covered: set[str]) -> dict[str, Any]:
    """Split every changed file into covered / neutral / uncovered.

    The point is visibility, not blocking: a routing hole must be nameable at
    the moment it happens. `aggregate_verdict([])` returns pass for an empty
    plan — correct for a pure function — so the fix is to make an empty plan
    structurally impossible rather than to change what a verdict means.
    """
    neutral: list[list[str]] = []
    uncovered: list[str] = []
    for rel in changed_files:
        if rel in covered:
            continue
        rule = _neutral_rule(rel)
        if rule is not None:
            neutral.append([rel, rule])
        else:
            uncovered.append(rel)
    return {"covered": sorted(covered), "neutral": neutral, "uncovered": uncovered}


def plan_gates(changed_files: list[str],
               ops_test_exists: Callable[[str], bool] | None = None,
               base: str | None = None) -> list[dict[str, Any]]:
    """Route changed files to the project's EXISTING gate tools. This is the one real
    judgement the orchestrator owns; it never decides pass/fail itself.

      ios/**            -> ios_ops.sh build  AND  build --catalyst (sim green != Catalyst
                           green) + quality impact (swift) + test --unit. If UITest
                           classes changed, also test --ui --file <class> per changed
                           UITest (impacted-scope, --dataset marketing_demo) — NOT the
                           whole --ui suite, which false-blocks on unrelated flaky tests.
                           A live-only exact-device class cannot truthfully execute in
                           that fixture simulator route: compile it as Release iphoneos
                           and emit a runtime-evidence advisory instead.
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
                           with a skip — see test_demo_ios_spec_emitter).
      **.sh             -> every tracked shell script MINUS SHELL_GATE_EXCLUDED_TREES
                           (`frozen/`): a syntax floor on each — the interpreter read
                           from its shebang, an unrecognised one SKIPPED and named
                           rather than guessed at — which is the only check covering
                           the ~1/3 with no test, plus the test that resolves for each.
                           The `ops/tests/test_<base>` / `ops/test_<base>` convention
                           applies only inside `ops/` and at the repo root, where
                           basenames are unique; anywhere else only an explicit
                           OPS_SHELL_TEST_ALIASES entry counts, because a shared
                           basename would report coverage by a test that never runs
                           the script. The remainder is named in a warn advisory
                           rather than left anonymous.
                           `ops_test_exists` is injected by cmd_gate (anchored at the
                           WORKTREE, so a test added in the same diff is seen); the pure
                           default (None) cannot prove existence -> whole-suite fallback.
      **.yml | **.yaml  -> the tool that asserts it, per DATA_PLANE_OWNERS (ui_quality
                           _plane.yml -> its validate + its test; registry.yml ->
                           docs_lint.sh --registry). No universal syntax floor exists
                           the way `bash -n` does, so anything with no owner is NAMED in
                           a warn. Files under a NEUTRAL_RULES tree stay neutral.

    Levels: `block` fails the verdict; `warn` is ADVISORY — it degrades the aggregate
    to `warn` but does NOT block cutover (a warn LANDS "with warnings"; its disposition
    belongs to the driving agent). Informational gates (backend-src-only advisory,
    verified_against reachability) are `warn` so they surface without blocking. A
    neutral file selects nothing."""
    gates: list[dict[str, Any]] = []

    # Iron law 4's mechanical half. review_audit only checks that each commit
    # carries a `Reviewed-by:` or a whitelisted `Review-Exempt:` trailer — it
    # cannot judge review quality, and the trailer is agent-authored. Its value
    # is making the ABSENCE visible at the moment code lands: receipts ran at
    # 100% over 07-13..07-17 and had decayed to 0% by 08-03 with nothing to
    # notice. Scoped to this worktree's own commits, so it is amendable in
    # seconds and cannot block on unrelated history.
    # `ops_test_exists` is the module's worktree-anchored path probe
    # (`(worktree / rel).is_file()`); synthetic fixture repos have no ops/ tree.
    # test_gate_plan_real_repo_plans_review_receipts pins that the real repo does
    # get this gate, so "file vanished" cannot silently drop it.
    if base and (ops_test_exists is None or ops_test_exists("ops/review_audit.sh")):
        gates.append(_shell("review-receipts", "meta",
                            ["ops/review_audit.sh", "--rev-range", f"{base}..HEAD"],
                            "block"))

    ios = [p for p in changed_files if p.startswith("ios/")]
    ds = [p for p in changed_files if DS_RE.search(p)]
    docs = [p for p in changed_files if p.startswith("docs/") and p.endswith(".md")]
    backend = [p for p in changed_files if p.startswith("backend/") and p.endswith(".py")]

    if ios:
        # Static lints first: ~21s against minutes of xcodebuild, and a red here
        # is far cheaper to act on than a red after two builds and a unit suite.
        #
        # This replaces `ios_ops.sh quality impact`, which sat at warn level and
        # could not fail by construction: it routes to ui_quality_plane's
        # PLANNER, whose every return is 0. It printed which lints would apply to
        # the changed files and reported pass — the plan mistaken for the check.
        # cutover is offline and never pushes, so it is the only gate on this
        # path; CI cannot cover for it.
        gates.append(_shell("ui-quality-fast", "ios",
                            ["ops/ui_quality_gate.sh", "--tier", "fast",
                             "--execute", "--all-mechanisms"], "block"))
        gates.append(_shell("ios-build", "ios", ["ops/ios_ops.sh", "build"], "block"))
        gates.append(_shell("ios-build-catalyst", "ios",
                            ["ops/ios_ops.sh", "build", "--catalyst"], "block"))
        swift = [p for p in ios if p.endswith(".swift")]
        if swift:
            # Kept, but honestly named and honestly scoped: this reports the
            # SLOW mechanisms the diff touches that cutover deliberately does
            # not run (visual regression, catalog snapshots, UI flows). It is
            # advisory because it is a cost/coverage trade, not a check.
            gates.append(_internal("ui-quality-slow-pending", "ios", "warn",
                                   note="slow UI mechanisms triggered by this diff were not "
                                        "executed by cutover — run ops/ui_quality_gate.sh "
                                        "--tier slow --execute-slow if this change needs them",
                                   files=swift))
        # `--lease` claims a pool simulator for the run and releases it on exit.
        # Without it these runs contend for the single default device ("iPhone 17
        # Pro Max"), whose lock has a 600s ceiling — with several worktrees under
        # gate at once that ceiling is reached routinely, and the timeout surfaces
        # as rc=1, i.e. indistinguishable from a real test failure. A cutover gate
        # that turns red because a *neighbour* was testing is worse than a slow
        # one: it trains the operator to disbelieve the gate.
        gates.append(_shell("ios-test-unit", "ios",
                            ["ops/ios_ops.sh", "test", "--unit", "--lease"], "block"))
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
            live_only_classes = sorted(set(ui_test_classes) & _LIVE_ONLY_UITEST_CLASSES)
            for cls in sorted(set(ui_test_classes) - _LIVE_ONLY_UITEST_CLASSES):
                gates.append(_shell(f"ios-test-ui:{cls}", "ios",
                                    ["ops/ios_ops.sh", "test", "--ui", "--lease",
                                     "--dataset", "marketing_demo", "--file", cls], "block"))
            if live_only_classes:
                gates.append(_shell(
                    "ios-live-demo-uitest-compile", "ios",
                    ["ops/ios_ops.sh", "test", "--ui", "--configuration", "Release",
                     "--destination", "generic/platform=iOS", "--prepare-cache", "--json"],
                    "block",
                ))
                gates.append(_internal(
                    "ios-live-demo-runtime-advisory", "ios", "warn",
                    note=("live-only UITest compiled for Release iphoneos; runtime was "
                          "intentionally not executed with simulator/fixture evidence — "
                          "App Review submission still requires app_review_evidence.py "
                          "demo-run exact-device evidence"),
                    files=[
                        f"ios/BooksAndVocabUITests/{cls}.swift"
                        for cls in live_only_classes
                    ],
                ))

    if ds:
        gates.append(_shell("design-system", "design-system",
                            ["ops/verify_design_system.sh"], "block"))

    if docs:
        # All three of these gates READ the file. A doc DELETED in this diff is still
        # a changed path, and handing it to `docs_lint --files` makes it exit 2 with
        # "--files 路徑不存在" — so **any commit that removes a doc is blocked**, by an
        # error phrased as if the caller mistyped a path. Measured on the commit that
        # removed the generated ledger view (IMP-20260807-b9526c).
        #
        # Not silently dropped: the removal is named in its own advisory, the same way
        # `ops-shell-untested` and `data-plane-unowned` name what they could not cover.
        # A gate list that quietly shrinks reads as "everything was checked".
        present = ops_test_exists or (lambda rel: True)
        docs_live = [p for p in docs if present(p)]
        docs_removed = [p for p in docs if p not in docs_live]
        if docs_live:
            gates.append(_shell("docs-lint", "docs",
                                ["ops/docs_lint.sh", "--files", *docs_live], "block"))
            gates.append(_internal("docs-conflict-markers", "docs", "block", files=docs_live))
            gates.append(_internal("docs-verified-against", "docs", "warn", files=docs_live))
        if docs_removed:
            gates.append(_internal("docs-removed", "docs", "warn", files=docs_removed))

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

    # Before 2026-08-04 a changed shell script selected NOTHING: `ops/devops_kg_safe.sh`
    # is iron law 7's enforcement point and `ops/release.sh` is the only path to
    # production, and both landed on nothing but the commit-trailer audit (IMP-0051).
    # Three layers, because no single one covers the whole surface: a universal syntax
    # floor (needs only bash, so no machine skips it), the script's own test where one
    # resolves, and a named advisory for the rest — an enumerated hole beats an
    # anonymous one.
    # Repo-root scripts count too. The original `ops/`-prefixed filter quietly excluded
    # `devops.sh` — the production deploy command, and the single shell script in the
    # tree with the highest blast radius (IMP-0052).
    # And the same defect one directory further out: `ops/` + root still missed 12
    # tracked scripts, one of which (`backend/view_logs.sh`) already had a test
    # watching it (IMP-0057). The routing surface is now every tracked `*.sh` MINUS
    # SHELL_GATE_EXCLUDED_TREES — a named exclusion instead of an anonymous hole.
    ops_sh = [p for p in changed_files
              if p.endswith(".sh")
              and not p.startswith(tuple(pat for pat, _ in SHELL_GATE_EXCLUDED_TREES))]
    if ops_sh:
        gates.append(_internal("ops-shell-syntax", "ops", "block", files=ops_sh))
        # The cross-file layer (IMP-20260808-3bbfa2). The two layers below are
        # per-script by construction — `bash -n` on each changed file, and each
        # file's own test — so a check that is ABOUT the whole tree belongs to no
        # single script and was therefore reachable from no diff at all. The
        # full-width-punctuation guard lived in that hole since 2026-08-04: correct,
        # positively controlled, and never once executed by a gate.
        #
        # ONE instance regardless of how many .sh changed: it scans the whole repo,
        # so per-file instances would be N identical runs. Block, because the thing
        # it catches is fatal at runtime on the error path — where the script's job
        # is to explain a failure and it instead dies mid-sentence.
        gates.append(_shell("ops-shell-scan", "ops", ["ops/shell_scan.sh"], "block"))
        exists = ops_test_exists or (lambda rel: False)
        sh_targets: set[str] = set()
        untested: list[str] = []
        for p in ops_sh:
            # existence is proven against the WORKTREE: a test added in this same diff
            # is visible, and one deleted in it is not handed back to the runner
            hit = next((c for c in _ops_shell_test_candidates(p) if exists(c)), None)
            if hit:
                sh_targets.add(hit)
            else:
                untested.append(p)
        for t in sorted(sh_targets):
            gates.append(_shell(f"ops-shell:{t.rsplit('/', 1)[-1]}", "ops", [t], "block"))
        if untested:
            why = ", ".join(
                f"{p} ({OPS_SHELL_UNROUTABLE_TESTS[p]})" if p in OPS_SHELL_UNROUTABLE_TESTS
                else p
                for p in untested)
            gates.append(_internal(
                "ops-shell-untested", "ops", "warn",
                note=f"no test runs for {why} — syntax is the only gate they get",
                files=untested))

    # yml/yaml control files. Neutral trees (promotion/, frozen/) are excluded up front:
    # they already have a declared reason to select nothing, and re-adopting them would
    # grow a warn on every marketing-manifest edit — a warn that always fires is a warn
    # nobody reads.
    # Lint watermarks. Five of these are checked in and, before this route
    # existed, changing ANY of them selected nothing but review-receipts —
    # so the debt ceiling could be raised, or a stale key left to rot into a
    # permanent re-offence slot, and the cutover gate stayed green. A ratchet
    # whose watermark is not itself gated is a ratchet in name only.
    # `test_lint_baselines.sh` already enumerates every checked-in baseline and
    # fails on one it does not cover, so a single owner routes all of them and
    # every future one — a pattern, not a file list (same rule NEUTRAL_RULES states).
    baselines = [p for p in changed_files
                 if re.fullmatch(r"ops/[a-z0-9_]+_baseline\.txt", p)]
    if baselines:
        gates.append(_shell("data-plane:ops/tests/test_lint_baselines.sh", "data",
                            ["ops/tests/test_lint_baselines.sh"], "block"))

    data_yml = [p for p in changed_files
                if p.endswith((".yml", ".yaml")) and _neutral_rule(p) is None]
    if data_yml:
        # `None` (no probe injected) means assume-present, matching review-receipts
        # above; the ops_sh default is the opposite because there a missing test is a
        # meaningful verdict rather than a missing prerequisite.
        present = ops_test_exists or (lambda rel: True)
        planned_cmds = [g["cmd"] for g in gates if g.get("cmd")]
        unowned: list[str] = []
        deleted: list[str] = []
        for p in data_yml:
            owners = DATA_PLANE_OWNERS.get(p)
            if not owners:
                unowned.append(p)
                continue
            if not present(p):
                # deleted in this diff: running its validator is a false red. But
                # skipping silently while still counting the file as covered would make
                # `coverage` say "every changed file is routed" about a file nothing
                # looked at — the exact anonymous hole this router exists to close.
                deleted.append(p)
                continue
            for cmd in owners:
                if cmd in planned_cmds:
                    continue  # the shell router already selected this exact run
                planned_cmds.append(cmd)
                # Named by TOOL PATH, not basename: the name is the key for the plan
                # JSON, the result lookup and the history journal, and two owners whose
                # tools differ only by directory would otherwise overwrite each other's
                # verdict while the plan still read complete.
                gates.append(_shell(f"data-plane:{cmd[0]}", "data", list(cmd), "block"))
        if unowned:
            gates.append(_internal(
                "data-plane-unowned", "data", "warn",
                note=("no tool asserts " + ", ".join(unowned)
                      + " — declare one in DATA_PLANE_OWNERS or accept that a typo "
                        "in it lands unchallenged"),
                files=unowned))
        if deleted:
            gates.append(_internal(
                "data-plane-deleted", "data", "warn",
                note=("deleted in this diff, so its owner tool was NOT run: "
                      + ", ".join(deleted)
                      + " — check by hand that nothing still reads it"),
                files=deleted))

    # The kaizen ledger. One file per entry under a fixed directory, so the route
    # keys on that directory rather than on `.json` under docs/ — a `.json` route
    # would hand unrelated data files to a validator that knows nothing about them
    # and pass vacuously, which is the failure this router exists to prevent.
    #
    # `validate` reads the WHOLE store, not just the changed entries: it is a
    # store-level invariant check, so a deleted entry needs no special case (unlike
    # DATA_PLANE_OWNERS above, where each file has its own validator and a deletion
    # would be a false red).
    #
    # Why this route did not exist until now (IMP-20260805-9a51e9): `validate` has
    # had ZERO automatic callers since it was written — not CI, not any ops/*.sh,
    # not this file. Its only mention outside its own tests is a prose instruction
    # in .claude/agents/platform-steward.md, so it ran only when an agent happened
    # to read that line. Meanwhile the generated VIEW is machine-checked (registry
    # `check:` -> render --check). The tool guaranteed the table matched the store
    # and guaranteed nothing about whether the store was true.
    # Top level only: `validate_store` globs `*.json` non-recursively, so a nested
    # path would be routed, counted as covered, and never actually read — a vacuous
    # pass one directory deeper than the one this route guards.
    backlog_entries = [p for p in changed_files
                       if p.startswith(BACKLOG_STORE_DIR)
                       and p.endswith(".json")
                       and "/" not in p[len(BACKLOG_STORE_DIR):]]
    # Keyed on the VALIDATOR too, not just the data. Otherwise the checker can change
    # without anyone running it against real entries: a commit touching only
    # ops/backlog.py passes ops-pytest on its own fixtures, cuts over green, and can
    # leave the whole store invalid — after which the next unrelated agent to edit any
    # entry eats problems they did not cause, which is how a gate earns a reputation
    # for false alarms and gets muted. IMP-20260805-9a51e9 schedules exactly this: its
    # plan states the real store must go to 7 problems the moment its checks land.
    if backlog_entries or "ops/backlog.py" in changed_files:
        # `--baseline-check` turns the ratchet on: schema problems AND any entry
        # newly closed with no attributable verification. Without it the queue
        # (`list --unverified`) has zero automatic callers, which is the whole
        # difference between a mechanism and a ritual — and `validate` was
        # already on this rail, so the queue rides for free.
        gates.append(_shell("backlog-validate", "data",
                            ["ops/backlog.py", "validate", "--baseline-check"], "block"))
    if backlog_entries:
        # `validate` answers "is each entry well-formed"; it says NOTHING about whether
        # the generated view still matches the store. Mutating the store stales the
        # view, and that is the most-hit trap in this repo today. Without this, a
        # store-only diff would report "every changed file is routed" while the one
        # thing that actually breaks in that diff shape goes unwatched — strictly worse
        # than before this route existed, when `coverage` at least NAMED the file.
        # registry `check:` for runbook.improvement_backlog is `render --check`.
        registry_cmd = ["ops/docs_lint.sh", "--registry"]
        if registry_cmd not in [g["cmd"] for g in gates if g.get("cmd")]:
            gates.append(_shell(f"data-plane:{registry_cmd[0]}", "data",
                                registry_cmd, "block"))

    covered: set[str] = set()
    for bucket in (ios, ds, docs, backend, ops_py, ops_sh, data_yml, backlog_entries, baselines):
        covered.update(bucket)
    cov = _coverage(changed_files, covered)
    note = "every changed file is routed to a gate or declared neutral"
    if cov["uncovered"]:
        note = ("no gate and no neutral rule covers: "
                + ", ".join(cov["uncovered"][:5])
                + (" …" if len(cov["uncovered"]) > 5 else ""))
    # Always planned, so `plan` is never empty and aggregate_verdict's
    # "pass (incl. empty)" branch is unreachable from cmd_gate.
    gates.append(_internal("coverage", "meta", "warn", note=note, **cov))
    return gates


def aggregate_verdict(results: list[dict[str, Any]]) -> str:
    """block if any gate blocked; else warn if any warned OR was inconclusive; else pass
    (incl. empty).

    `inconclusive` folds to WARN, and both of the other two folds would be wrong.
    `block` would kill a session's work for someone else's tag surgery — the red was
    real but not the branch's (IMP-20260805-4ec901). `pass` would be a claim nobody
    made: the gate never produced an attributable answer. `warn` is what this module
    already means by "degraded, named, disposition belongs to the driving agent", which
    is exactly the situation.
    """
    statuses = {r.get("status") for r in results}
    if "block" in statuses:
        return "block"
    if "warn" in statuses or "inconclusive" in statuses:
        return "warn"
    return "pass"


# ============================================================================
# IO layer — git + subprocess to the real gate tools.
# ============================================================================
def _git(args: list[str], cwd: Path | str | None = None) -> tuple[int, str]:
    """Run a bounded, parsed-output git probe expected to finish quickly.

    Potentially long or side-effecting git operations must use ``_git_mutation`` so
    the operator sees start/spawned/heartbeat/done progress on stderr.
    """
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


def _noninteractive_env() -> dict[str, str]:
    """The parent environment with every door to an interactive prompt shut.

    `git -c core.editor=true` is NOT enough, and the difference is measurable: git
    resolves `GIT_EDITOR` FIRST, so with `GIT_EDITOR=vim` a `rebase --continue`
    launches the editor and blocks on a pipe nobody reads — forever, since these
    runs carry no timeout. On the `cutover` path that happens INSIDE the trunk lock,
    so one operator's editor preference freezes every cutover in the repo. Measured
    with `GIT_EDITOR` pointed at a 25s sleep: `elapsed=25.6s` — the editor really ran.

    This machine happens to have `GIT_EDITOR=true`, which is exactly why the bug was
    invisible here: the tests were green on the environment, not on the code.
    """
    env = dict(os.environ)
    env["GIT_EDITOR"] = "true"
    env["GIT_SEQUENCE_EDITOR"] = "true"
    env["GIT_TERMINAL_PROMPT"] = "0"
    return env


def _git_mutation(
    args: list[str],
    *,
    cwd: Path | str,
    label: str,
    heartbeat_interval: float = 20.0,
    capture_limit: int = 64 * 1024,
) -> tuple[int, str]:
    """Run a potentially long git operation with machine-output-safe progress.

    ``label`` is a caller-owned semantic identifier. The raw argv is deliberately
    never printed because git remotes and refspecs may contain credentials.
    """
    try:
        proc = run_streamed_command(
            ["git", *args],
            cwd=cwd,
            label_key="mutation",
            label=label,
            progress_prefix="[worktree][mutation]",
            heartbeat_interval=heartbeat_interval,
            capture_limit=capture_limit,
            merge_stderr=False,
            env=_noninteractive_env(),
        )
    except (FileNotFoundError, NotADirectoryError) as exc:
        return 127, f"cwd unavailable: {exc}"
    out = (proc.stdout or "").strip()
    stderr = (proc.stderr or "").strip()
    if proc.returncode != 0 and stderr:
        out = (out + "\n" + stderr).strip()
    return proc.returncode, out


def _rmtree_streamed(path: str) -> tuple[int, str]:
    """Remove a directory tree under the same visible-progress contract as every
    other long operation (iron law 5).

    Deliberately NOT `shutil.rmtree`: the tree this removes is a worktree's, and in
    the incident that meant 19 GB of iOS DerivedData taking minutes. An in-process
    rmtree emits nothing for that whole window — exactly the silence the heartbeat
    contract forbids, and the silence that got the original run killed by a caller
    timeout, which is what manufactured the ambiguous state in the first place."""
    try:
        proc = run_streamed_command(
            ["rm", "-rf", "--", path],
            cwd=primary_root(),
            label_key="mutation",
            label="resolve-remove-leftover-directory",
            progress_prefix="[worktree][mutation]",
            heartbeat_interval=20.0,
            capture_limit=64 * 1024,
            merge_stderr=False,
        )
    except (FileNotFoundError, NotADirectoryError) as exc:
        return 127, f"cwd unavailable: {exc}"
    stderr = (proc.stderr or "").strip()
    return proc.returncode, stderr


def primary_root() -> Path:
    """The MAIN working tree's root (dirname of the git common dir). Stable no matter
    which linked worktree the process stands in — the only safe anchor for open's
    worktree placement and for teardown commands that may remove the caller's own cwd
    (resolve from inside the target worktree)."""
    return wr.common_anchor()


def _tag_snapshot(anchor: Path | str) -> str | None:
    """Every tag ref visible from `anchor`, or None when it could not be read.

    A linked worktree shares `refs/` with the primary — measured, not assumed:
    `git rev-parse --path-format=absolute --git-path refs/tags` returns a byte-identical
    path from both (drop that flag and the primary answers relatively while the worktree
    answers absolutely — two strings, one file), so a
    `release.sh` run over there is immediately visible to a child gate running here.
    That is how a gate's colour stops being a property of the branch and becomes a
    property of the machine (IMP-20260805-4ec901, same family as the device-lock case).

    Anchored at the tree being gated rather than at `primary_root()`: identical answer
    for the reason above, one fewer git spawn (`primary_root` shells out to
    `rev-parse --git-common-dir` first), and independent of where this process happens
    to stand.

    None means UNMEASURED and the caller must read it as "cannot tell", never as
    "changed": a probe that fails must not manufacture inconclusives out of real reds.
    """
    try:
        rc, out = _git(["for-each-ref", "--format=%(objectname) %(refname)", "refs/tags"],
                       cwd=anchor)
    except Exception:  # noqa: BLE001 — this is instrumentation; it may not fail a gate
        return None
    return out if rc == 0 else None


def _tag_delta(before: str | None, after: str | None) -> int:
    """How many tag refs appeared or disappeared between two snapshots. 0 when either
    side is unmeasured (see `_tag_snapshot`) — a retagged name counts as 2, which is
    literally what happened: one removed, one added."""
    if before is None or after is None:
        return 0
    return len(set(before.splitlines()) ^ set(after.splitlines()))


def _norm(p: str) -> str:
    return os.path.realpath(os.path.abspath(p))


def _fetch(quiet: bool = True) -> tuple[int, str]:
    return _git_mutation(
        ["fetch", "origin", "--prune"], cwd=primary_root(), label="fetch-origin",
    )


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
    `git diff --name-only base...HEAD`). This is the PATCH a cutover would land — which
    equals the TREE the gates execute against only while the base is already contained
    in HEAD; `_base_containment` is what makes that precondition true."""
    rc, out = _git(["diff", "--name-only", f"{base}...HEAD"], cwd=worktree)
    if rc != 0:
        # base unresolved (e.g. no origin/main locally) — fall back to two-dot.
        rc, out = _git(["diff", "--name-only", f"{base}..HEAD"], cwd=worktree)
    return [ln for ln in out.splitlines() if ln]


def _local_trunk(base: str) -> str:
    """The LOCAL branch a cutover rebases onto. `--base` may be spelled `origin/main`,
    but the ref a cutover actually integrates against is always the local trunk. gate
    and cutover must measure containment against the SAME ref, or the check drifts
    away from the thing it protects."""
    return base.split("/", 1)[1] if "/" in base else base


def _base_containment(worktree: str, base: str) -> dict[str, Any] | None:
    """None when `base`'s tip is already an ancestor of the worktree HEAD — i.e. the
    tree that was gated IS the tree a cutover lands, because the rebase is then a
    no-op. Otherwise the drift, MEASURED: how many commits, and which files base
    gained since the fork point.

    The missing half of iron law 2's machine enforcement (IMP-20260806-945e01).
    `head_sha` binds a verdict to the code the gate READ; nothing bound it to the code
    it lands ALONGSIDE. A branch behind base passes the stale-HEAD check BY
    CONSTRUCTION — the HEAD did not move, only the base did — and cutover then rebases
    onto a tree the gate never saw."""
    rc, _ = _git(["merge-base", "--is-ancestor", base, "HEAD"], cwd=worktree)
    if rc == 0:
        return None
    _, tip = _git(["rev-parse", base], cwd=worktree)
    if rc != 1:
        # 128 = unresolvable ref / unreadable repo. NOT the same as "behind": report
        # the inability to verify rather than inventing a count, and still refuse —
        # "cannot check" must never render as "checked and fine".
        return {"base_ref": base, "base_sha": tip, "behind_commits": None,
                "base_changed_files": [], "containment_error": f"git rc={rc}"}
    _, n = _git(["rev-list", "--count", f"HEAD..{base}"], cwd=worktree)
    _, files = _git(["diff", "--name-only", f"HEAD...{base}"], cwd=worktree)
    return {"base_ref": base, "base_sha": tip,
            "behind_commits": int(n) if n.isdigit() else None,
            "base_changed_files": [ln for ln in files.splitlines() if ln]}


def _behind_base_refusal(worktree: str, trunk: str, drift: dict[str, Any]) -> str:
    if drift.get("containment_error"):
        return (f"cannot verify that {trunk} is contained in the worktree HEAD "
                f"({drift['containment_error']}) — refusing rather than binding a "
                f"verdict to a tree that may not be the one that lands")
    return (f"worktree is behind {trunk} ({drift['behind_commits']} commit(s), "
            f"{len(drift['base_changed_files'])} file(s) changed on {trunk} since the "
            f"fork) — cutover rebases onto {trunk} first, so the gated tree is NOT the "
            f"tree that lands. Run `{worktree}/ops/worktree_orchestrate.py catchup "
            f"--worktree {worktree} --commit`, then re-run `gate`")


def _head_sha(worktree: str) -> str:
    _, out = _git(["rev-parse", "HEAD"], cwd=worktree)
    return out


def _current_branch(worktree: str) -> str | None:
    rc, out = _git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=worktree)
    return out if rc == 0 and out != "HEAD" else None


def _worktree_entry(worktree: str) -> dict[str, Any] | None:
    """This path's `git worktree list --porcelain` record, or None if git does not
    list it as a worktree at all.

    This is the ONLY admissible path→branch answer for teardown. `_current_branch`
    is not: git's repository discovery WALKS UP from its cwd, so a directory whose
    `.git` has been removed — an interrupted `worktree remove`, whose first act is
    to unlink that file — answers with the ENCLOSING checkout's branch. Worktrees
    live at <repo>/.claude/worktrees/<slug>, so the enclosing checkout is the
    primary and the answer is `main`. The worktree list has no such fallback: it
    still names the real branch and flags the entry `prunable`."""
    target = _norm(worktree)
    for w in wr._worktrees():
        if _norm(w["path"]) == target:
            return w
    return None


def _remote_branch_exists(name: str) -> bool:
    rc, out = _git_mutation(
        ["ls-remote", "--heads", "origin", name],
        cwd=primary_root(),
        label="remote-branch-probe",
    )
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


def _registry_mutation(
    argv: list[str],
    *,
    cwd: Path | str,
    label: str,
    heartbeat_interval: float = 20.0,
) -> tuple[int, dict[str, Any] | None]:
    """Run a registry action whose commit path may perform long git teardown.

    stdout remains the registry's single JSON document; progress and registry
    diagnostics are captured separately so the orchestrator's own JSON is pure.
    """
    proc = run_streamed_command(
        [sys.executable, str(Path(__file__).resolve().with_name("worktree_registry.py")),
         *argv],
        cwd=cwd,
        label_key="mutation",
        label=label,
        progress_prefix="[worktree][mutation]",
        heartbeat_interval=heartbeat_interval,
        capture_limit=64 * 1024,
        merge_stderr=False,
    )
    text = (proc.stdout or "").strip()
    payload: dict[str, Any] | None = None
    if "--json" in argv and text:
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            payload = None
    diagnostic = (proc.stderr or "").strip()
    if proc.returncode != 0:
        # Preserve the old route's visible failure evidence without writing it to
        # parent stdout. The child argv is never echoed, and the bounded runner has
        # already capped this stream; keep a smaller tail in the structured result.
        safe_tail = diagnostic[-2000:]
        if payload is None:
            payload = {"error": "registry mutation failed"}
        if safe_tail:
            payload["detail"] = safe_tail
    return proc.returncode, payload


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


def _gate_log_path(record_path: Path, gate_name: str) -> Path:
    """Where a FAILED gate's captured output is kept — beside its verdict record.

    One file per (worktree, gate), named off the record so the pair is obvious on
    disk and `resolve` can strike both with one glob. Gate names carry `:` and `/`
    (`ops-shell:test_devops.sh`, `data-plane:ops/tests/test_lint_baselines.sh`), so
    anything outside a conservative set folds to `_`: this is a filename, not an
    identifier, and the record next to it holds the exact name.
    """
    slug = re.sub(r"[^A-Za-z0-9._-]", "_", gate_name)
    return record_path.parent / f"{record_path.stem}.{slug}.log"


# Lines worth lifting out of a failed gate's output. Deliberately broad: these gates
# are a zoo — shell harnesses printing `✗`, pytest, TAP producers, bash's own
# `error:` — and a marker set narrow enough to look tidy is one that goes silent for
# whichever tool nobody had in mind. A false positive costs one line of noise; a miss
# costs the re-run this whole mechanism exists to remove.
GATE_FAILURE_MARKERS = ("✗", "FAIL", "AssertionError", "not ok", "error:")
GATE_MAX_FAILURE_LINES = 20

# The log is now the artefact an operator opens, so the capture has to be able to
# hold a whole harness run rather than just enough to describe one. Still bounded:
# `run_streamed_command` keeps the LAST N bytes per stream, and an unbounded capture
# would make a chatty gate a memory incident.
GATE_CAPTURE_LIMIT = 1024 * 1024


def _gate_failure_lines(output: str) -> list[str]:
    """The lines of a failed gate's output that name what failed."""
    hits = [ln.rstrip() for ln in output.splitlines()
            if any(m in ln for m in GATE_FAILURE_MARKERS)]
    return hits[:GATE_MAX_FAILURE_LINES]


def _gate_history_path(state: str | None) -> Path:
    """Append-only behavioural log of gate outcomes, beside the per-worktree verdicts.

    The verdict file is one file per LIVE worktree, overwritten each run and struck on
    resolve — by design, and correct for its job (cutover needs the current verdict, not
    a museum). But it means nothing in the system can answer "has this gate EVER gone
    green", which is the only question that separates a broken check from a broken
    change. `ios-build-catalyst` could not go green on this machine for two months and
    blocked every iOS cutover; each individual red looked like an ordinary failure.
    """
    return _gate_record_path(state, "").parent / "history.jsonl"


def _append_gate_history(state: str | None, worktree: str, head: str,
                         orch: dict[str, Any],
                         results: list[dict[str, Any]]) -> str | None:
    """One compact JSONL line per gate result. NEVER fails the caller — a gate that
    refused because its own bookkeeping broke would be a fresh way to turn a green
    change red. (Same hard rule as ops/lib/ios_run_metrics.sh.)

    Returns the error string instead, so the caller can SAY that journaling is broken: a
    permanently unwritable journal and a fresh clone otherwise look identical (both
    "no history"), and a detector that can die with zero signal is the very disease
    this journal exists to catch.
    """
    try:
        path = _gate_history_path(state)
        path.parent.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        wt_key = hashlib.sha256(_norm(worktree).encode()).hexdigest()[:16]
        with path.open("a", encoding="utf-8") as fh:
            for r in results:
                fh.write(json.dumps({
                    "ts": ts,
                    "gate": r["name"],
                    # colon-suffixed gates (ios-test-ui:<Class>) are per-diff instances
                    # of ONE check; capability lives at the base name.
                    "base_name": r["name"].split(":")[0],
                    "status": r.get("status"),
                    "rc": r.get("rc"),
                    "level": r.get("level"),
                    # False only for gates that never started (spawn failure). A row
                    # for a check that did not run must not be usable as evidence
                    # about whether that check can pass.
                    "executed": r.get("executed", True),
                    "head8": head[:8],
                    "orch8": orch["sha256"][:8],
                    "wt": wt_key,
                }, ensure_ascii=False) + "\n")
    except Exception as exc:  # noqa: BLE001 — bookkeeping is never load-bearing
        return f"{type(exc).__name__}: {exc}"
    return None


def gate_history_rows(state: str | None) -> list[dict[str, Any]]:
    """Every parseable row of the journal.

    A malformed line skips ITSELF, never the whole file. The journal is append-only and
    never rotated, so one truncated write (disk full, SIGKILL mid-flush) would otherwise
    disable every reader of it permanently and silently — the exact failure shape the
    journal exists to find.
    """
    path = _gate_history_path(state)
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def gate_history_verdicts(state: str | None, base_names: list[str],
                          min_attempts: int = 3,
                          min_heads: int = 2) -> dict[str, dict[str, Any]]:
    """Per capability: `proven` (recorded green at least once), `never-green` (tried
    enough times, never once green) or `unproven` (too little history to say).

    THE reader. `ops/tests/test_gate_can_fail.sh` calls this instead of parsing the
    journal itself: two readers of one file are two chances to disagree, and they did
    exactly that — the shell copy counted rows for gates that never started, which the
    python side skips, so the same row could read "never green" in one place and "no
    data" in the other.

    "Never green, ever" rather than "not green lately" on purpose: someone iterating on
    a genuinely broken build reds the same gate repeatedly, and a recency rule would cry
    wolf at them.

    Only `level == "block"` rows count. The level is what makes a red consequential; a
    gate promoted from advisory to block would otherwise inherit the whole streak it
    accumulated while nobody was obliged to act on it, and trip on its first real block.
    """
    rows = gate_history_rows(state)
    out: dict[str, dict[str, Any]] = {}
    for name in base_names:
        mine = [r for r in rows
                if r.get("base_name") == name
                and r.get("level") == "block"
                # `executed is False` = the gate never started (spawn failure): not
                # evidence in either direction. An ABSENT key is a row written before
                # the field existed, i.e. a real run.
                and r.get("executed") is not False
                # Same reasoning one step further out: an `inconclusive` row DID run,
                # but its colour was contaminated by refs moving under it, so it says
                # nothing about whether the gate can pass. Without this it would count
                # as an attempt and never as a green — inflating the streak until the
                # next genuine red arrived carrying "no green ever recorded", which is
                # the wrong hypothesis to hand someone (IMP-20260805-4ec901).
                and r.get("status") != "inconclusive"]
        greens = [r for r in mine if r.get("status") == "pass"]
        heads = {r.get("head8") for r in mine}
        if greens:
            verdict = "proven"
        elif len(mine) >= min_attempts and len(heads) >= min_heads:
            verdict = "never-green"
        else:
            verdict = "unproven"
        out[name] = {"verdict": verdict, "attempts": len(mine), "heads": len(heads),
                     "worktrees": len({r.get("wt") for r in mine}),
                     "last_green": greens[-1].get("ts") if greens else None}
    return out


def _never_green(state: str | None, base_name: str,
                 min_attempts: int = 3, min_heads: int = 2) -> dict[str, int] | None:
    """{attempts, heads, worktrees} when this gate has never been recorded green and has
    been tried enough times to mean something; None otherwise. Bookkeeping, so it
    swallows its own failures — a broken journal must not turn a green change red."""
    try:
        v = gate_history_verdicts(state, [base_name], min_attempts, min_heads)[base_name]
    except Exception:  # noqa: BLE001
        return None
    if v["verdict"] != "never-green":
        return None
    return {"attempts": v["attempts"], "heads": v["heads"], "worktrees": v["worktrees"]}


def _orchestrator_identity(worktree: str) -> dict[str, Any]:
    """WHO produced this verdict.

    `_run_gate` executes every shell gate with the worktree as cwd, so the TOOLS being
    routed to come from the worktree. `plan_gates` — the routing itself — comes from
    whichever copy of this file the shell resolved from the caller's cwd. Those two can
    be different commits: running `gate` from the primary checkout against a branch that
    changed the routing silently plans the OLD rule set and records it in a shape
    indistinguishable from the new one.

    A content hash, not a git commit: a commit id would attribute an uncommitted edit to
    the committed version, and an uncommitted edit is precisely when this matters.

    Three states, deliberately distinct — collapsing any two reopens the bypass:
      * no ops/ tree at all (synthetic fixtures, any non-kg checkout) -> None, "cannot
        compare". This must NOT masquerade as a mismatch or every such caller is refused
        for a question that was never asked.
      * present and readable -> True/False on the digests.
      * present but UNREADABLE -> False, fail closed. Reporting it as None would let the
        guard wave it through, which is the same silent bypass with a new trigger.
    """
    running = Path(__file__).resolve()
    wt_copy = Path(worktree) / "ops" / "worktree_orchestrate.py"
    wt_sha: str | None = None
    wt_error: str | None = None
    if wt_copy.is_file():
        try:
            wt_sha = sha256_file(wt_copy)
        except OSError as exc:
            wt_error = f"{type(exc).__name__}: {exc}"
    running_sha = sha256_file(running)
    if wt_error is not None:
        matches: bool | None = False
        source = "unreadable"
    elif wt_sha is None:
        matches = None
        source = "invoked"
    else:
        matches = wt_sha == running_sha
        source = "worktree" if matches else "invoked"
    return {
        "path": logical_tool_path(running),
        "resolved": str(running),
        "sha256": running_sha,
        "source": source,
        "worktree_copy_sha256": wt_sha,
        "worktree_copy_error": wt_error,
        "matches_worktree_copy": matches,
    }


def _orch_token(record: dict[str, Any]) -> str:
    """The one rendering of orchestrator identity, read back OUT of the record so the
    human report and the receipt line cannot drift from the JSON that cutover reads.
    Carries the source, not just the digest: a bare digest looks identical whether the
    worktree agreed, had nothing to compare, or could not be read."""
    o = record["orchestrator"]
    return f"{o['sha256'][:8]} ({o['source']})"


def _orchestrator_guard(orch: dict[str, Any], worktree: str, step: str, schema: str,
                        as_json: bool) -> int | None:
    """EXIT_USAGE when the running orchestrator is NOT the worktree's own copy.

    Narrow by construction: `matches_worktree_copy` is False only when the branch
    actually modified this tool. A byte-identical copy plans an identical set of gates,
    so refusing there would be friction with no safety gain — and friction is what
    teaches people to route around a gate. `None` (no ops/ tree to compare against)
    is "cannot compare", never "mismatch".
    """
    if orch["matches_worktree_copy"] is not False:
        return None
    remedy = f"{worktree}/ops/worktree_orchestrate.py"
    if orch.get("worktree_copy_error"):
        what = (f"the worktree's own orchestrator at {remedy} could not be read "
                f"({orch['worktree_copy_error']}), so this plan cannot be shown to come "
                f"from the tree that is landing")
    else:
        what = (f"this orchestrator ({orch['sha256'][:8]}, {orch['resolved']}) is not the "
                f"one in the worktree ({orch['worktree_copy_sha256'][:8]}, {remedy})")
    reason = (
        f"{what}. The gate TOOLS run from the worktree, so the routing must come from "
        f"there too — otherwise the plan is a different generation from the tools it "
        f"plans. Re-run as: {remedy}"
    )
    _emit({"schema": schema, "step": step, "error": "orchestrator mismatch",
           "reason": reason, "orchestrator": orch}, as_json,
          f"✗ {step} refused: {reason}")
    return EXIT_USAGE


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


_SYNTAX_CHECKABLE_SHELLS = ("bash", "sh", "zsh")


def _shell_syntax_interpreter(fp: Path) -> str | None:
    """The interpreter to run `-n` under, or None when it is not one we can check.

    No shebang means bash. That default is load-bearing, not a fallback: six tracked
    `ops/lib/*.sh` are sourced rather than executed and carry no shebang, and treating
    "unknown" as "skip" would silently demote them from having a syntax floor to having
    none — a widening of the gate that reads like a hardening of it.
    """
    try:
        with fp.open(encoding="utf-8", errors="replace") as fh:
            first = fh.readline()
    except OSError:
        return "bash"  # unreadable here means bash reports it, not that we look away
    if not first.startswith("#!"):
        return "bash"
    # `#!/usr/bin/env bash`, `#!/bin/bash`, `#!/bin/bash -e` — the interpreter is the
    # last token that is not a flag.
    words = [w for w in first[2:].split() if not w.startswith("-")]
    if not words:
        return "bash"
    name = words[-1].rsplit("/", 1)[-1]
    if name not in _SYNTAX_CHECKABLE_SHELLS:
        return None
    # Recognised is not the same as available: the name is resolved through PATH, and
    # `zsh` is absent from GitHub's ubuntu runner by default. Letting it fall through
    # would raise inside `subprocess.run` and land in `bad` — a BLOCK about the SCRIPT
    # stating a fact about the MACHINE, the very substitution this function exists to
    # refuse. Absent interpreter is UNCHECKABLE, which is the `skipped` list's meaning.
    return name if shutil.which(name) else None


def _run_shell_syntax(worktree: str, files: list[str]) -> dict[str, Any]:
    """A syntax floor on every changed shell script. The floor exists because it is the
    only check that applies to ALL of them: roughly a third of ops/*.sh has no test of
    its own, and before IMP-0051 a shell change selected no gate whatsoever.

    The interpreter comes from the shebang. `bash -n` on a script that is not bash is a
    false red — indistinguishable from a real one at the gate — so a shebang we do not
    recognise is SKIPPED and NAMED in the summary rather than guessed at: an enumerated
    hole beats an anonymous one. Today every tracked `*.sh` is bash or shebang-less, so
    this changes no verdict; it is the guard for the first one that is not."""
    bad: list[str] = []
    skipped: list[str] = []
    # Counted, never inferred from `len(files)`. That list also holds the ones deleted
    # in this same diff, so the old summary reported "3 shell script(s) parse" for a run
    # that invoked bash zero times — a green whose number was simply untrue.
    checked = 0
    for rel in files:
        fp = Path(worktree) / rel
        if not fp.is_file():
            continue  # deleted in this diff; routing to it would be a red for no reason
        interpreter = _shell_syntax_interpreter(fp)
        if interpreter is None:
            skipped.append(rel)
            continue
        try:
            proc = subprocess.run([interpreter, "-n", str(fp)], capture_output=True,
                                  text=True, timeout=30)
        except (OSError, subprocess.SubprocessError) as exc:
            bad.append(f"{rel}: {type(exc).__name__}")
            continue
        checked += 1
        if proc.returncode != 0:
            first = next((ln for ln in proc.stderr.splitlines() if ln.strip()), "")
            bad.append(f"{rel}: {first.strip()}")
    if bad:
        return {"status": "block", "rc": 1,
                "summary": f"{len(bad)} shell script(s) do not parse: " + "; ".join(bad[:3])}
    if skipped:
        return {"status": "pass", "rc": 0,
                "summary": (f"{checked} shell script(s) parse; "
                            f"{len(skipped)} skipped (interpreter not available or not "
                            f"recognised): " + ", ".join(skipped))}
    return {"status": "pass", "rc": 0, "summary": f"{checked} shell script(s) parse"}

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


def _run_streamed_command(
    command: list[str],
    *,
    cwd: Path | str,
    gate_name: str,
    heartbeat_interval: float = 20.0,
    capture_limit: int = 64 * 1024,
) -> tuple[int, str]:
    completed = run_streamed_command(
        command,
        cwd=cwd,
        label_key="gate",
        label=gate_name,
        progress_prefix="[worktree][gate]",
        heartbeat_interval=heartbeat_interval,
        capture_limit=capture_limit,
        merge_stderr=True,
    )
    return completed.returncode, completed.stdout


def _failed_gate_summary(returncode: int, output: str, tail: str,
                         log_path: Path | None) -> str:
    """What a blocked operator actually reads: named failures, then the tail, then
    where the rest of it is.

    The tail alone WAS the entire summary until 2026-08-08, and it is kept — for many
    gates the tail is the failure. What it could not do is carry a name that had
    scrolled past it, and three lines is exactly what a shell harness's closing
    frame costs, so the name was always the thing that got dropped.
    """
    lines = [f"exit {returncode}"]
    hits = _gate_failure_lines(output)
    if hits:
        lines.append(f"  failure-marked lines ({len(hits)} shown):")
        lines.extend(f"    {h}" for h in hits)
    else:
        # Said out loud rather than quietly degrading to the old shape. "This summary
        # looks thin" and "this gate prints no marker the scanner knows" are different
        # problems with different fixes, and only the second one is the tool's.
        lines.append("  no failure-marked lines found (scanned for "
                     f"{', '.join(GATE_FAILURE_MARKERS)})")
    if tail:
        lines.append("  tail:")
        lines.extend(f"    {ln}" for ln in tail.splitlines())
    if log_path is not None:
        lines.append(f"  full output: {log_path}")
    return "\n".join(lines)


def _write_gate_log(log_path: Path, spec: dict[str, Any], cwd: Path,
                    returncode: int, output: str) -> str | None:
    """Persist a failed gate's captured output. Returns an error string, never raises.

    Bookkeeping is never load-bearing: a gate that reddened because its own log could
    not be written would be a fresh way to turn a green change red (same hard rule as
    `_append_gate_history`). The header exists so the file explains itself to whoever
    opens it hours later without the summary in front of them.
    """
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(
            f"# gate: {spec['name']}\n"
            f"# cmd: {' '.join(spec.get('cmd') or [])}\n"
            f"# cwd: {cwd}\n"
            f"# rc: {returncode}\n"
            f"# capture: merged stdout+stderr, last {GATE_CAPTURE_LIMIT} bytes\n"
            f"# ---\n" + output,
            encoding="utf-8")
    except OSError as exc:
        return f"{type(exc).__name__}: {exc}"
    return None


def _run_gate(spec: dict[str, Any], worktree: str, *,
              record_path: Path | None = None) -> dict[str, Any]:
    """Execute ONE planned gate against the worktree and return a result record.

    `record_path` is this worktree's verdict-record path; a failed gate's captured
    output is written beside it and pointed at from the summary. Optional because the
    log is an enhancement and not a precondition — without it the gate still runs and
    still reports, it just has nowhere to put the long form.
    """
    name, level = spec["name"], spec["level"]
    result = {"name": name, "category": spec["category"], "level": level}
    if spec["kind"] == "internal":
        if name == "docs-conflict-markers":
            result.update(_run_conflict_markers(worktree, spec["files"]))
        elif name == "coverage":
            # Bookkeeping, not policing: pass when every changed file is routed
            # or declared, warn (never block) when something is unrouted. A
            # permanently-warn gate would desensitise the warn signal, and a
            # blocking one would force an exemption list — which is itself the
            # next thing to rot.
            unc = spec.get("uncovered") or []
            result.update({
                "status": "warn" if unc else "pass", "rc": 0,
                "summary": (f"{len(unc)} changed file(s) covered by no gate: "
                            + ", ".join(unc[:5]))
                           if unc else
                           (f"{len(spec.get('covered') or [])} covered, "
                            f"{len(spec.get('neutral') or [])} neutral, 0 uncovered"),
            })
        elif name == "ops-shell-syntax":
            result.update(_run_shell_syntax(worktree, spec["files"]))
        elif name == "docs-verified-against":
            result.update(_run_verified_against(worktree, spec["files"]))
        else:  # advisory-only gate (e.g. backend-tests-advisory)
            result.update({"status": "warn", "rc": 0, "summary": spec.get("note", "advisory")})
        return result

    # shell gate — run the real tool. cwd is the worktree (or a subdir like backend).
    cwd = Path(worktree) / spec["cwd"] if spec.get("cwd") else Path(worktree)
    log_path = _gate_log_path(record_path, name) if record_path is not None else None
    # Struck BEFORE the run, not after: a log left by an earlier red describes a
    # failure that may already be fixed, and nothing on disk marks it stale. Doing it
    # here rather than on success means every exit from this function — including the
    # spawn-failure return below — leaves no log that this run did not write.
    if log_path is not None and log_path.exists():
        try:
            log_path.unlink()
        except OSError:
            pass
    # Bracket the run with a refs probe. Some ops tests read repo-global tag state, and
    # `refs/` is SHARED with the primary — so a `release.sh` running over there while
    # this gate runs can turn it red for a reason that has nothing to do with the
    # branch. Measured 2026-08-05: `ops/test_ios_ops.sh` at 371 passed / 1 failed inside
    # a batch gate, 371 green and exit 0 when rerun alone.
    tags_before = _tag_snapshot(worktree)
    try:
        returncode, output = _run_streamed_command(
            spec["cmd"], cwd=cwd, gate_name=name, capture_limit=GATE_CAPTURE_LIMIT,
        )
    except OSError as exc:
        # The router and the tools it routes to can be different generations
        # (IMP-0045): a branch that deleted a script leaves a stale router still
        # pointing at it. Letting this escape aborts the WHOLE run — every other
        # gate's result is discarded and the operator gets a traceback naming
        # subprocess.py rather than a gate.
        #
        # But OSError covers two very different stories and only one of them is
        # about the tool. ENOENT/EACCES/ENOTDIR mean this really cannot be run —
        # and `exc.filename` says WHICH path, because with spec["cwd"] set it is
        # the missing directory, not the command. Everything else (EMFILE, ENOMEM,
        # EAGAIN: a machine that cannot fork right now) says nothing about the tool
        # at all, and claiming it does is iron law 3 inverted — an operator told
        # "gate tool not runnable: ops/ios_ops.sh" goes hunting a stale router
        # while the real problem is fd exhaustion in a sibling worktree.
        if exc.errno in (errno.ENOENT, errno.EACCES, errno.ENOTDIR):
            summary = (f"gate tool not runnable: cmd={spec['cmd'][0]} cwd={cwd} — "
                       f"{type(exc).__name__} on {exc.filename or 'unknown path'}")
        else:
            summary = (f"gate could not be spawned (errno {exc.errno}): "
                       f"cmd={spec['cmd'][0]} — {type(exc).__name__}: {exc}")
        # `executed: False` is not cosmetic. Without it these rows enter the journal
        # as ordinary block attempts, and `_never_green` — which reads level and
        # status, never rc — counts three of them as evidence that the gate can
        # never pass. The next genuine red then arrives carrying "no green ever
        # recorded", steering the reader away from their own bug. rc alone cannot
        # carry this: a tool that RAN and exited 127 is a real red.
        return {**result, "status": "block" if level == "block" else "warn", "rc": 127,
                "executed": False, "summary": summary}
    tail = "\n".join(output.splitlines()[-3:]) if output else ""
    if returncode == 0:
        # Green needs no attribution, so the second probe is not taken at all on this
        # path. Refs moving under a gate that PASSED changes nothing anyone would act
        # on, and calling it inconclusive would degrade the verdict of a run that
        # produced exactly the answer it was asked for. It also keeps the common case
        # at one `git for-each-ref` (~140ms here) instead of two.
        result.update({"status": "pass", "rc": returncode,
                       "summary": f"exit {returncode}" + (f": {tail}" if tail else "")})
        return result
    tags_after = _tag_snapshot(worktree)

    status = "block" if level == "block" else "warn"
    log_error = None
    if log_path is not None:
        log_error = _write_gate_log(log_path, spec, cwd, returncode, output)
    summary = _failed_gate_summary(returncode, output, tail,
                                   None if log_error else log_path)
    if log_error:
        # Never silent: an unwritable log and a gate that simply had nothing to say
        # otherwise look identical, and the reader would go looking for a file that
        # was never there.
        summary += f"\n  ! output log not written ({log_error})"
    refs_changed = _tag_delta(tags_before, tags_after)
    if tags_before is None or tags_after is None:
        # Fail-safe, but never silent. The red stands — an unreadable probe is no reason
        # to downgrade anything — yet "could not measure" must not look identical to
        # "measured, nothing moved", which is the same rule `history_error`,
        # `log_error` and `executed: False` each exist to enforce. A probe that goes
        # permanently blind on some machine would otherwise reinstate this whole bug
        # with zero signal.
        result["refs_probe"] = "unmeasured"
        summary += ("\n  ! refs probe unmeasured — cannot tell whether concurrent tag "
                    "surgery contaminated this result")
    if refs_changed:
        # Not `block`: the measurement was taken while someone else moved refs under
        # it, so charging this red to the branch kills work over a machine-state
        # artefact. Not `pass` either — nothing here established the gate would have
        # been green. The rc is kept verbatim; the point is attribution, not amnesia.
        status = "inconclusive"
        result["refs_changed"] = True
        summary = (f"refs changed during this gate ({refs_changed} tag(s) "
                   f"added/removed); rc={returncode} is not attributable to the "
                   f"branch — re-run this gate once the tag surgery is done\n{summary}")
    result.update({"status": status, "rc": returncode, "summary": summary})
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
    if args.commit:
        src, sweep = _registry_mutation(
            sweep_argv, cwd=primary_root(), label="preflight-sweep",
        )
    else:
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
    """registry register (= claim) + git worktree add — in that order.

    The order is the point. `git worktree add` used to run first and the register
    afterwards, with its exit code read only to choose a sentence to print before
    an unconditional `return EXIT_OK`. Under a claim that is the worst possible
    shape: the agent that LOST a ticket got a branch, a directory and a success
    code, plus a warning line nothing is obliged to read.

    Registering first makes the ledger the gate. The cost is a window where a
    record can exist for a worktree that does not — so a failed `add` hands the
    claim straight back rather than stranding the ticket on a path that is not
    there.
    """
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
    wanted = list(args.backlog or [])
    # `--backlog` is forwarded ONLY when it was given. Passing it unconditionally
    # looked harmless and was not: with no ids, the argv is `["--backlog", "--json"]`
    # and argparse's nargs="*" resolves that to `[]`, NOT to None — which is the
    # "replace the claim" branch. Measured end-to-end: `open --backlog IMP-0001`
    # then a plain `adopt` on a LIVE worktree left `backlog: []`, `claimed_at: None`,
    # and a second agent could immediately take the ticket. The registry's
    # "omit = leave alone" rule was unreachable through the only two callers that
    # exist, so the invariant this whole change adds was broken by the change itself.
    if _refuse_unclaimable(root, wanted, args, "open", branch) is not None:
        return EXIT_BLOCK

    claim_argv = ["--backlog", *wanted] if args.backlog is not None else []
    reg_rc, reg_payload = _registry(
        ["register", *_state_arg(args.state), "--path", str(path), "--branch", branch,
         "--intent", args.intent, "--base", base, *claim_argv, "--json"])
    if reg_rc != EXIT_OK:
        conflicts = (reg_payload or {}).get("conflicts", [])
        held = ", ".join(
            f"{','.join(c.get('backlog') or [])} by [{c.get('branch')}] at {c.get('path')}"
            for c in conflicts) or (reg_payload or {}).get("reason", "register refused")
        _emit({"schema": SCHEMA, "step": "open", "error": "claim refused",
               "branch": branch, "backlog": wanted, "conflicts": conflicts,
               "registry_rc": reg_rc}, args.json,
              f"✗ cannot open [{branch}] — {held}")
        # EXIT_BLOCK, not EXIT_OK-with-a-warning: losing a race is a refusal, and
        # the exit code is the only part of this a caller's `&&` can see.
        return EXIT_BLOCK

    rc, out = _git_mutation(
        ["worktree", "add", "-b", branch, str(path), base],
        cwd=root,
        label="open-worktree-add",
    )
    if rc != 0:
        # Hand the claim back. `preflight --commit` does eventually reclaim it (its
        # sweep strikes the record, and measured: the ticket becomes claimable again
        # right after), and even the dry-run lists it under `stale_entries` — so this
        # is not the only recovery. It is the immediate one: without it the ticket
        # stays held by a record whose path does not exist until somebody happens to
        # run preflight WITH --commit, which is not the default.
        rel_rc, _ = _registry(["resolve", *_state_arg(args.state), "--branch", branch,
                               "--status", "abandoned"])
        _emit({"schema": SCHEMA, "step": "open", "error": "worktree add failed",
               "detail": out, "backlog": wanted, "claim_released": rel_rc == EXIT_OK},
              args.json,
              f"✗ git worktree add failed:\n{out}\n"
              f"  {'claim released' if rel_rc == EXIT_OK else '⚠ COULD NOT release the claim — run: '
                 f'ops/worktree_registry.py resolve --branch {branch} --status abandoned'}")
        return EXIT_BLOCK

    payload = {"schema": SCHEMA, "step": "open", "branch": branch, "path": str(path),
               "base": base, "intent": args.intent, "backlog": wanted, "registered": True}
    human = (f"✓ opened worktree [{branch}] (base {base})\n"
             f"  path: {path}\n"
             f"  registered in ledger"
             + (f" — holding {', '.join(wanted)}" if wanted else ""))
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

    wanted = list(args.backlog or [])
    if _refuse_unclaimable(Path(primary_root()), wanted, args, "adopt",
                           branch) is not None:
        return EXIT_BLOCK
    claim_argv = ["--backlog", *wanted] if args.backlog is not None else []  # see cmd_open
    reg_rc, reg_payload = _registry(
        ["register", "--state", state, "--path", worktree, "--branch", branch,
         "--intent", args.intent, "--base", args.base, *claim_argv, "--json"])
    ok = reg_rc == EXIT_OK
    conflicts = (reg_payload or {}).get("conflicts", [])
    # Same sentence `open` builds. The registry's own human line never reaches the
    # operator here: `_registry` is called with --json, so the refusal went out as
    # JSON and the text path printed only "register failed" — a losing agent read
    # that and had no next move.
    held = ", ".join(
        f"{','.join(c.get('backlog') or [])} held by [{c.get('branch')}] at {c.get('path')}"
        for c in conflicts)
    payload = {"schema": SCHEMA, "step": "adopt", "branch": branch, "worktree": worktree,
               "base": args.base, "intent": args.intent, "ledger": state,
               "backlog": wanted, "conflicts": conflicts, "registered": ok}
    human = (f"{'✓ adopted' if ok else '✗ adopt could NOT register'} worktree "
             f"[{branch}] (base {args.base})\n"
             f"  path: {worktree}\n"
             f"  ledger: {state}"
             + ("" if ok else f"  — {held or 'register failed'}"))
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

    rc, out = _git_mutation(
        ["merge", "--ff-only", base_ref],
        cwd=primary,
        label="sync-main-fast-forward",
    )
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

    prc, pout = _git_mutation(
        ["push", "origin", f"{src_ref}:{dest_branch}"],
        cwd=primary,
        label=f"{step}-push",
    )
    if prc != 0:
        return _refuse(f"git push failed: {pout[:300]}")
    # verify against origin's ACTUAL ref (ls-remote), not the local remote-tracking ref
    # git just wrote — an independent confirmation that the publish really took.
    rc, ls = _git_mutation(
        ["ls-remote", "origin", dest_branch],
        cwd=primary,
        label=f"{step}-verify-remote",
    )
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


def _interrupted_operation(worktree: str | Path) -> str | None:
    """`"rebase"` / `"merge"` / `"cherry-pick"` when one is in flight here, else None.

    Reads the marker paths git itself uses, via `rev-parse --git-path` so it works in a
    linked worktree (where they live under `.git/worktrees/<name>/`, not the common
    dir). Checking `git status` output instead would make this depend on porcelain
    wording; checking for unmerged paths alone would miss a conflict-free rebase that
    was interrupted, which is equally incoherent to diff against.
    """
    for name, marker in (("rebase", "rebase-merge"), ("rebase", "rebase-apply"),
                         ("merge", "MERGE_HEAD"), ("cherry-pick", "CHERRY_PICK_HEAD")):
        rc, path = _git(["rev-parse", "--git-path", marker], cwd=worktree)
        if rc == 0 and path.strip():
            candidate = Path(path.strip())
            if not candidate.is_absolute():
                candidate = Path(worktree) / candidate
            if candidate.exists():
                return name
    return None


def cmd_gate(args: argparse.Namespace) -> int:
    """Impact-based verification: route changed files to the existing gate tools, run
    them, aggregate a verdict, and record it for cutover."""
    worktree = _norm(args.worktree)
    if not Path(worktree).is_dir():
        _emit({"schema": GATE_SCHEMA, "error": "worktree not found", "worktree": worktree},
              args.json, f"✗ worktree not found: {worktree}")
        return EXIT_USAGE

    orch = _orchestrator_identity(worktree)
    mismatch = _orchestrator_guard(orch, worktree, "gate", GATE_SCHEMA, args.json)
    if mismatch is not None:
        return mismatch

    interrupted = _interrupted_operation(worktree)
    if interrupted is not None and not args.plan_only:
        # A tree with a rebase/merge in flight has no coherent diff against the trunk,
        # and `git diff` on it reports the PARTIAL state. Measured: mid-rebase with one
        # unmerged path, `_changed_vs_base` returned [] — so `plan_gates` routed nothing,
        # `aggregate_verdict([])` returned "pass", and the run recorded a fresh green
        # verdict bound to that HEAD. A gate that greenlights a conflicted tree is worse
        # than one that fails: cutover's whole freshness contract rests on this verdict.
        #
        # Empty-diff alone is NOT the signal to refuse on — a branch whose work is
        # already contained in the trunk legitimately has nothing to gate. The state of
        # the operation is.
        _emit({"schema": GATE_SCHEMA, "step": "gate",
               "error": f"a {interrupted} is in progress in this worktree — finish or "
                        f"abort it before gating. A tree mid-operation has no coherent "
                        f"diff against the trunk, so the verdict would be recorded over "
                        f"a partial state",
               "worktree": worktree, "interrupted": interrupted}, args.json,
              f"✗ gate refused: a {interrupted} is in progress in {worktree}\n"
              f"  finish it (`git -C {worktree} {interrupted} --continue`) or abandon it "
              f"(`--abort`), then re-run gate")
        return EXIT_BLOCK

    if not args.plan_only:
        # Cheap half of the base binding: refuse before spending a gate run (an iOS gate
        # is tens of minutes) on a tree that cannot land as-gated. `--plan-only` runs
        # nothing and records nothing, so it stays usable as the preview the message
        # below points at.
        trunk = _local_trunk(args.base)
        drift = _base_containment(worktree, trunk)
        if drift is not None:
            msg = (f"{_behind_base_refusal(worktree, trunk, drift)} — gating this tree "
                   f"would bind a verdict to code cutover will not land. `--plan-only` "
                   f"still previews the routing")
            _emit({"schema": GATE_SCHEMA, "step": "gate", "error": msg,
                   "worktree": worktree, "base": args.base, **drift}, args.json,
                  f"✗ gate refused: {msg}")
            return EXIT_BLOCK

    changed = _changed_vs_base(worktree, args.base)
    # anchor test-existence at the WORKTREE so a test file added in this very diff
    # is seen (the primary checkout may not have it yet)
    plan = plan_gates(changed,
                      ops_test_exists=lambda rel: (Path(worktree) / rel).is_file(),
                      base=args.base)
    results: list[dict[str, Any]] = []
    rec_path = _gate_record_path(args.state, worktree)
    if not args.plan_only:
        for spec in plan:
            results.append(_run_gate(spec, worktree, record_path=rec_path))
    verdict = aggregate_verdict(results) if not args.plan_only else "planned"

    head = _head_sha(worktree)
    if not args.plan_only:
        # History FIRST, so the never-green check below sees this run too: "never green
        # in N attempts" is only honest if N includes the red being reported.
        history_error = _append_gate_history(args.state, worktree, head, orch, results)
        for r in results:
            if r.get("status") != "block":
                continue
            streak = _never_green(args.state, r["name"].split(":")[0])
            if streak is None:
                continue
            # Said at the moment of blocking, where it can still change what the reader
            # does. Deliberately a HYPOTHESIS, not a verdict: an empty journal is every
            # gate's starting state, so three reds while fixing a genuinely broken build
            # look identical to a structurally-red gate. Asserting "the gate is at fault"
            # would hand the reader a root cause the data cannot support (iron law 3).
            # What the data does support is: nothing here has ever seen this gate pass.
            r["never_green"] = streak
            r["summary"] = (
                f"{r.get('summary', '')} (no green ever recorded for this gate on this "
                f"machine: {streak['attempts']} block attempt(s) across "
                f"{streak['heads']} HEAD(s) / {streak['worktrees']} worktree(s) — worth "
                f"checking whether it can pass at all before treating this as your bug)")

    record = {"schema": GATE_SCHEMA, "worktree": worktree, "base": args.base,
              "head_sha": head, "orchestrator": orch, "changed_files": changed,
              "plan": [{"name": g["name"], "level": g["level"], "category": g["category"],
                        "cmd": g.get("cmd")} for g in plan],
              "gates": results, "verdict": verdict}
    if not args.plan_only:
        # Non-blocking, but never silent: a permanently unwritable journal must not be
        # indistinguishable from a machine that simply has no history yet.
        record["history_error"] = history_error
        rec_path.parent.mkdir(parents=True, exist_ok=True)
        rec_path.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n")

    if getattr(args, "receipt_line", False):
        # A receipt line the agent PASTES rather than recalls. Structured
        # receipt fields that an agent types from memory are exactly as
        # trustworthy as prose — a fabricated 64-hex digest is no harder to
        # produce than "tests passed", and it removes the tonal tells that make
        # prose lies detectable. This line cannot be produced without having run
        # the gate, and the reader can `cat` the record path to check it.
        counts = {}
        for r in results:
            counts[r["status"]] = counts.get(r["status"], 0) + 1
        breakdown = " ".join(f"{k}={v}" for k, v in sorted(counts.items()))
        print(f"gate={verdict} record={_gate_record_path(args.state, worktree)} "
              f"head={head[:8]} orch={_orch_token(record)} gates={len(plan)} {breakdown}")
        return EXIT_OK if verdict in ("pass", "warn") else EXIT_BLOCK

    lines = [f"# gate {verdict.upper()}  ({len(changed)} changed file(s), "
             f"{len(plan)} gate(s))  orchestrator={_orch_token(record)}"]
    for r in results:
        mark = {"pass": "✓", "warn": "⚠", "block": "✗",
                "inconclusive": "~"}.get(r["status"], "?")
        lines.append(f"  {mark} {r['name']} [{r['status']}] — {r.get('summary','')}")
    if not plan:
        lines.append("  (no impact-based gates selected for these changes)")
    if record.get("history_error"):
        lines.append(f"  ! gate history not written ({record['history_error']}) — "
                     f"never-green detection is blind until this is fixed")
    _emit(record, args.json, "\n".join(lines))
    if args.plan_only:
        return EXIT_OK
    return EXIT_OK if verdict in ("pass", "warn") else EXIT_BLOCK


def cmd_cutover(args: argparse.Namespace) -> int:
    """Require a fresh non-block gate verdict, then integrate the worktree into the
    LOCAL trunk: rebase onto local `main` and fast-forward the primary checkout's
    `main` to it — OFFLINE, no push, no deploy. (Publishing to origin, and thereby
    production, is the separate `deploy` step.) A `warn` verdict LANDS ("landed with
    warnings" — its disposition belongs to the driving agent); `block`, a stale/absent
    verdict, and a verdict containing an `inconclusive` gate all refuse."""
    blocked = _freeze_guard(args.state, "cutover", args.json)
    if blocked is not None:
        return blocked
    worktree = _norm(args.worktree)
    if not Path(worktree).is_dir():
        _emit({"schema": SCHEMA, "step": "cutover", "error": "worktree not found",
               "landed": False}, args.json, f"✗ worktree not found: {worktree}")
        return EXIT_USAGE

    orch = _orchestrator_identity(worktree)
    mismatch = _orchestrator_guard(orch, worktree, "cutover", SCHEMA, args.json)
    if mismatch is not None:
        return mismatch

    local = _local_trunk(args.base)
    rec_path = _gate_record_path(args.state, worktree)
    head = _head_sha(worktree)
    refuse: str | None = None
    refuse_extra: dict[str, Any] = {}
    verdict: str | None = None
    gated_head: str | None = None
    warnings: list[str] = []
    if not rec_path.exists():
        refuse = "no gate verdict on record — run `gate` first"
    else:
        rec = json.loads(rec_path.read_text())
        verdict = rec.get("verdict")
        gated_head = rec.get("head_sha")
        rec_orch = (rec.get("orchestrator") or {}).get("sha256")
        wt_orch = orch["worktree_copy_sha256"]
        if rec.get("head_sha") != head:
            refuse = ("gate verdict is stale (recorded HEAD "
                      f"{str(rec.get('head_sha'))[:8]} != current {head[:8]}) — re-run `gate`")
        elif wt_orch is not None and rec_orch != wt_orch:
            # Same family as the stale-HEAD refusal: a verdict is usable only if it is
            # bound BOTH to the code it judged and to the judge. head_sha alone cannot
            # see this — the wrong orchestrator run at the SAME HEAD matches on head.
            refuse = ("gate verdict came from a different orchestrator "
                      f"({str(rec_orch)[:8]} != worktree's {wt_orch[:8]}) — re-run `gate` "
                      f"with {worktree}/ops/worktree_orchestrate.py")
        elif verdict == "block":
            refuse = "gate verdict is 'block' — fix the blocking gate(s) and re-run `gate`"
        elif verdict not in ("pass", "warn"):
            refuse = f"gate verdict is {verdict!r}, not pass/warn — run `gate` first"
        elif unattributed := [g.get("name") for g in rec.get("gates", [])
                              if g.get("status") == "inconclusive"]:
            # An inconclusive gate folds the VERDICT to warn, and a warn LANDS — so
            # without this the fold quietly turns "this red could not be attributed"
            # into "shipped with a note", which is the disarm direction. It is reachable
            # with no tag surgery at all: every concurrent preflight/catchup/sync/deploy
            # runs `git fetch --prune`, which imports origin's new tags and moves the
            # snapshot under a gate that never reads tags.
            #
            # The gate's own summary already said "re-run this gate"; nothing made that
            # happen. Refusing costs one gate re-run and makes the instruction real.
            refuse = (f"{len(unattributed)} gate(s) came back inconclusive — their red "
                      f"was measured while refs moved underneath, so it is attributable "
                      f"to neither this branch nor the tools: "
                      f"{', '.join(str(n) for n in unattributed[:5])}. Re-run `gate` "
                      f"once the tag surgery is finished")
        elif verdict == "warn":
            # a warn LANDS; surface which gates warned so the record is explicit.
            # `inconclusive` folds INTO this verdict, so it has to be named here too —
            # otherwise the only gate that degraded the run would be the one gate the
            # landing record does not mention.
            warnings = [g.get("name") for g in rec.get("gates", [])
                        if g.get("status") in ("warn", "inconclusive")]
    if not refuse:
        # Ordering is deliberate: the stale-HEAD / wrong-orchestrator / block refusals
        # still win when they apply — they are the more specific diagnosis. This one
        # sits in the SHARED chain, so it is visible in dry-run as well as --commit.
        # The helper's failure key is `containment_error`, not `error`, so **spreading
        # it cannot clobber the refusal prose.
        drift = _base_containment(worktree, local)
        if drift is not None:
            refuse_extra = drift
            refuse = _behind_base_refusal(worktree, local, drift)
    if refuse:
        _emit({"schema": SCHEMA, "step": "cutover", "error": refuse, "landed": False,
               "worktree": worktree, **refuse_extra}, args.json,
              f"✗ cutover refused: {refuse}")
        return EXIT_BLOCK

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
        # Normally a no-op: the shared refusal chain above already sent a behind
        # branch to `catchup`. It can still move, because that check runs OUTSIDE
        # this lock and a peer cutover may have advanced the trunk since.
        rrc, rout = _rebase_onto(worktree, local, "cutover-rebase")
        if rrc != 0:
            _git_mutation(
                ["rebase", "--abort"], cwd=worktree, label="cutover-rebase-abort",
            )
            _emit({"schema": SCHEMA, "step": "cutover", "error": "rebase failed (aborted)",
                   "detail": rout, "landed": False},
                  args.json,
                  f"✗ rebase onto {local} failed (aborted):\n{rout}")
            return EXIT_BLOCK
        sha = _head_sha(worktree)
        if gated_head is not None and sha != gated_head:
            # Terminal invariant, and the only one a race cannot dodge: the containment
            # check above runs OUTSIDE this lock, so a peer cutover can advance the trunk
            # in between — and the rebase is deliberately taken against the CURRENT trunk.
            # Whatever the cause, a rebase that moved HEAD produced a tree no gate ever
            # judged. Refuse BEFORE the trunk advances; nothing has landed. The worktree
            # is left rebased (that is the remedy anyway) and its verdict is now honestly
            # stale, so the next cutover refuses on head_sha until `gate` is re-run.
            msg = (f"the rebase onto {local} moved HEAD ({gated_head[:8]} -> {sha[:8]}) "
                   f"— the trunk advanced after the verdict was checked, so the tree "
                   f"that would land is not the tree that was gated. The worktree is "
                   f"now rebased: re-run `gate`, then `cutover`")
            _emit({"schema": SCHEMA, "step": "cutover", "error": msg, "landed": False,
                   "worktree": worktree, "gated_sha": gated_head, "rebased_sha": sha,
                   "target": local}, args.json,
                  f"✗ cutover refused: {msg}")
            return EXIT_BLOCK
        # advance the local trunk by a ff-only merge IN the primary (main lives there).
        mrc, mout = _git_mutation(
            ["merge", "--ff-only", wt_branch],
            cwd=primary,
            label="cutover-fast-forward",
        )
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

        # INSIDE the lock, deliberately. The repair reads and rewrites the same
        # trunk-owned files the ff just moved, so it belongs to the same critical
        # section. Measured outside it, 4 runs out of 4: two concurrent repairs
        # raced in `_write_atomic` and one died with FileNotFoundError, leaving
        # the primary dirty — and a dirty primary is what every later `cutover`
        # refuses on. The lock is also what makes the rollback below safe: nobody
        # else can have dirtied these paths since `_primary_ff_ready` passed.
        repair = _post_landing_repair(primary)
        staged_closures = _stamp_anchor_queue(primary, wt_branch, sha)

    trunk_tip = _head_sha(primary) if repair.get("committed") else sha
    payload = {"schema": SCHEMA, "step": "cutover", "mode": "committed", "landed": True,
               "sha": sha, "trunk_tip": trunk_tip, "target": local, "branch": wt_branch,
               "verdict": verdict, "warnings": warnings, "repair": repair,
               "staged_closures": staged_closures}
    repair_line = ""
    if repair.get("committed"):
        # Human-readable callers were told nothing at all about the repair, which
        # made a landing that added TWO commits to the trunk print as one.
        repair_line = f"\n  + ledger repair committed ({trunk_tip[:8]})"
    if not repair.get("ok", True):
        repair_line = f"\n  ! ledger repair FAILED: {repair.get('error', '?')}"
    if staged_closures:
        repair_line += (f"\n  staged closures stamped: {', '.join(staged_closures)}"
                        f" — land them with `./ops/backlog.py anchor --commit`")
    _emit(payload, args.json,
          f"✓ cutover: ff local {local} -> {sha[:8]} (offline; run `deploy` to "
          f"publish){warn_line}{repair_line}")
    return EXIT_OK


def _tool_mutation(argv: list[str], *, cwd: Path | str, label: str) -> tuple[int, str]:
    """Same visible-progress contract as `_git_mutation`, for a repo tool rather than
    git. Routed through the shared runner rather than a silent `capture_output` for
    the reason in `ops/lib/streaming_command.py`: an orchestrator subprocess that can
    take seconds must not be invisible."""
    try:
        proc = run_streamed_command(
            argv,
            cwd=cwd,
            label_key="mutation",
            label=label,
            progress_prefix="[worktree][mutation]",
            heartbeat_interval=20.0,
            capture_limit=64 * 1024,
            merge_stderr=True,
        )
    except OSError as exc:
        return 1, str(exc)
    return proc.returncode, (proc.stdout or "")


# The store, and only the store. The generated view left version control (its own
# entry, IMP-20260807-b9526c): it is produced on demand by `backlog.py render` and
# is gitignored, so there is no longer a tracked derived file for the trunk to
# repair, for a rebase to conflict on, or for a review exemption to be scoped to.
LEDGER_PATHS = ("docs/runbook/backlog",)
# A flat backstop, NOT "one per replayed commit" — the loop cannot see how many
# commits are being replayed, and a bound that claims to be derived from something
# it never reads is worse than an admitted constant. Its only job is to stop a loop
# that has stopped making progress; a rebase replaying more than this many
# conflicting commits is a situation for a human either way.
_MAX_REBASE_STEPS = 100


def _rebase_onto(worktree: str | Path, trunk: str, label: str) -> tuple[int, str]:
    """`git rebase <trunk>`. Returns (rc, output); rc != 0 means the caller aborts.

    Deliberately does NOT abort here — the two callers want different things after a
    failure (cutover aborts and refuses; catchup aborts and explains).

    It used to carry a conflict resolver: the rebase would conflict on the 280KB
    GENERATED ledger view (measured on a clone of the real repo, 3 to 6 branches out
    of ten in a single round), and since that file is a pure function of the store,
    "what should it say" had one right answer and no judgement in it — so the helper
    re-ran the generator and continued. That whole apparatus is gone with the file:
    the view is no longer tracked (IMP-20260807-b9526c), so a rebase cannot conflict
    on it. What remains is what should always have been true — a conflict here is a
    real decision, and it goes to a human.
    """
    return _git_mutation(["rebase", trunk], cwd=worktree, label=label)


def _ticket_is_abandoned(path: Path) -> bool:
    """Is this ticket's owner gone? Answered by the kernel, not by a pid.

    The owner holds an exclusive flock on its OWN ticket file for the whole time
    it is queued, so "abandoned" is simply "the flock is free" — and a flock is
    released by the kernel when the holder dies, which is the entire reason the
    registry uses one. An earlier version asked `os.kill(pid, 0)` instead. That
    was wrong twice over: pids are recycled, so a crashed lane's ticket could be
    kept alive forever by an unrelated process that inherited its number, which
    reintroduces one level down the exact "a file is not a lock" deadlock this
    eviction exists to prevent; and `kill(2)` treats non-positive pids as
    broadcasts (0 = the caller's process group, -1 = every reachable process),
    both of which SUCCEED, so a corrupt ticket carrying 0 read as permanently
    alive. The flock answers both without a special case.

    Failing to open or lock for any other reason returns False — an abandoned
    ticket that we merely could not read must not be evicted out from under a
    live owner. Callers hold `_land_lock`, so no live owner can enqueue mid-probe.
    """
    try:
        fd = os.open(path, os.O_RDWR)
    except OSError:
        return False
    try:
        wr.fcntl.flock(fd, wr.fcntl.LOCK_EX | wr.fcntl.LOCK_NB)
    except OSError:
        return False            # somebody holds it: the owner is alive
    else:
        wr.fcntl.flock(fd, wr.fcntl.LOCK_UN)
        return True
    finally:
        os.close(fd)


def _land_queue_dir(primary: Path) -> Path:
    return primary / ".cache" / "kg-land-queue"


def _land_lock(primary: Path):
    return wr._ledger_lock(_land_queue_dir(primary) / "seq")


def _land_tickets(qdir: Path) -> list[tuple[int, dict]]:
    """Live tickets, lowest sequence first.

    A ticket whose owner died is DELETED here, not skipped. Skipping would be the
    cheaper read, but the dead ticket would keep its place at the head forever and
    every later lane would wait behind a process that no longer exists — a queue
    that deadlocks on a crash is worse than no queue at all. Callers must hold
    `_land_lock`, since this mutates.
    """
    out: list[tuple[int, dict]] = []
    if not qdir.is_dir():
        return out
    for path in sorted(qdir.glob("*.json")):
        try:
            seq = int(path.stem)
            rec = json.loads(path.read_text())
        except (ValueError, OSError, json.JSONDecodeError):
            path.unlink(missing_ok=True)
            continue
        if _ticket_is_abandoned(path):
            path.unlink(missing_ok=True)
            continue
        out.append((seq, rec))
    out.sort(key=lambda t: t[0])
    return out


def _land_enqueue(primary: Path, worktree: str) -> tuple[int, int]:
    """Take a ticket and hold it. Returns (seq, fd).

    The fd is the ticket: the caller must keep it open for as long as it is
    queued, because the flock on it is what proves the lane is still alive. Close
    it — deliberately, or by dying — and the next `_land_tickets` sweep evicts the
    ticket. `pid` is still recorded, but only so a human reading the queue can see
    who is in it; nothing decides liveness from it.
    """
    qdir = _land_queue_dir(primary)
    qdir.mkdir(parents=True, exist_ok=True)
    with _land_lock(primary):
        live = _land_tickets(qdir)
        seq = (live[-1][0] + 1) if live else 1
        path = qdir / f"{seq:012d}.json"
        fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o644)
        wr.fcntl.flock(fd, wr.fcntl.LOCK_EX | wr.fcntl.LOCK_NB)
        os.write(fd, json.dumps(
            {"pid": os.getpid(), "worktree": worktree}).encode())
        os.fsync(fd)
    return seq, fd


def _land_position(primary: Path, seq: int) -> tuple[int, dict | None]:
    """(position, ticket-ahead-of-us). 0 means it is our turn; -1 means our own
    ticket is gone, which can only happen if something evicted us."""
    with _land_lock(primary):
        live = _land_tickets(_land_queue_dir(primary))
    seqs = [s for s, _ in live]
    if seq not in seqs:
        return (-1, None)
    pos = seqs.index(seq)
    return (pos, live[0][1] if pos > 0 else None)


def _land_release(primary: Path, seq: int, fd: int | None = None) -> None:
    with _land_lock(primary):
        (_land_queue_dir(primary) / f"{seq:012d}.json").unlink(missing_ok=True)
    if fd is not None:
        try:
            os.close(fd)          # drops the flock; a dead lane gets this for free
        except OSError:
            pass


def _land_step(func, **kw) -> tuple[int, dict]:
    """Run one orchestrator subcommand in-process and capture its payload.

    In-process rather than a subprocess so the gate verdict is produced by exactly
    this orchestrator — `cutover` compares the judge's identity, and re-execing a
    different copy of the file is the failure that check exists to catch. stdout is
    captured because each step emits its own JSON envelope and `land` emits one of
    its own; two JSON documents on one stream is the pollution this repo already
    forbids operators from creating.
    """
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = func(argparse.Namespace(**kw))
    raw = buf.getvalue()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        payload = {"raw": raw[-2000:]}
    return rc, payload


def cmd_land(args) -> int:
    """Drive one worktree all the way onto the local trunk, taking a fair turn.

    Measured on a clone of this repo, ten concurrent worktrees each running the
    documented catchup/gate/cutover sequence: TWO landed. The other eight were
    refused with "worktree is behind main" — five at cutover, three before their
    gate would even run — because the trunk is single and the ff is linear, so
    whichever lane lands first makes every other lane stale. The remedy each
    refusal names (catch up, then gate again) races exactly the same way, so the
    recovery convoys instead of converging. At N=3 the same run landed 3 of 3 but
    still spent 6 gate runs to do it.

    Nothing there was unsafe: no ungated tree landed, the primary stayed clean, the
    ledger stayed consistent. The invariant held. What was missing was a verb whose
    meaning is "get me landed", so `land` is that verb.

    It works by widening the critical section. `cutover` serializes only the ff,
    which is enough to keep two lanes from interleaving but not enough to keep a
    lane's verdict fresh: the trunk can move between the gate and the lock. `land`
    holds the turn across catchup -> gate -> cutover, so the tree that is gated is
    the tree that lands, first try. N lanes cost N gate runs.

    Turns are FIFO rather than an flock because an flock is not fair, and the lane
    that loses a repeated race is the one with the slowest gate — in a mixed batch
    that is the iOS lane, i.e. the one that can least afford to run again.
    """
    blocked = _freeze_guard(args.state, "land", args.json)
    if blocked is not None:
        return blocked
    worktree = _norm(args.worktree)
    if not Path(worktree).is_dir():
        _emit({"schema": SCHEMA, "step": "land", "mode": "refused",
               "error": f"no such worktree: {worktree}"},
              args.json, f"✗ no such worktree: {worktree}")
        return EXIT_BLOCK
    primary = primary_root()

    if not args.commit:
        with _land_lock(primary):
            live = _land_tickets(_land_queue_dir(primary))
        _emit({"schema": SCHEMA, "step": "land", "mode": "dry-run", "landed": False,
               "worktree": worktree, "queue_depth": len(live),
               "would_run": ["catchup --commit", "gate", "cutover --commit"],
               "note": "takes a FIFO turn first; the whole sequence runs under it"},
              args.json,
              f"[dry-run] land {worktree}: queue depth {len(live)}; would take a turn "
              f"then run catchup --commit -> gate -> cutover --commit")
        return EXIT_OK

    seq, ticket_fd = _land_enqueue(primary, worktree)
    started = time.monotonic()
    common = {"state": args.state, "json": True, "base": args.base,
              "worktree": worktree}
    try:
        waited = 0.0
        last_beat = 0.0
        # The timeout measures LACK OF PROGRESS, not total wait. Total wait is the
        # wrong quantity: `land` holds the turn across the whole gate, so lane N
        # legitimately waits (N-1) x gate. With an iOS gate at "tens of minutes"
        # (cmd_gate's own words) a healthy lane 4 in a ten-lane batch would blow a
        # total-wait budget and be told a "stuck peer" was to blame — the tool
        # diagnosing a working queue as a broken one, in exactly the mixed batch
        # this verb was written for. A queue that keeps moving is healthy however
        # long your turn takes to arrive; a queue whose head has not changed is
        # not.
        last_pos = None
        progressed_at = time.monotonic()
        while True:
            pos, ahead = _land_position(primary, seq)
            if pos == -1:
                _emit({"schema": SCHEMA, "step": "land", "mode": "refused",
                       "error": "our queue ticket disappeared — the flock on it was "
                                "seen free, so this lane was judged dead; re-run "
                                "`land`",
                       "landed": False, "worktree": worktree},
                      args.json, "✗ land refused: queue ticket disappeared")
                return EXIT_BLOCK
            if pos == 0:
                break
            now = time.monotonic()
            waited = now - started
            if pos != last_pos:
                last_pos = pos
                progressed_at = now
            stalled = now - progressed_at
            if stalled >= args.queue_timeout:
                _emit({"schema": SCHEMA, "step": "land", "mode": "refused",
                       "error": f"the landing queue has not moved for {stalled:.0f}s "
                                f"(still position {pos} after waiting {waited:.0f}s) "
                                f"— the lane holding the turn is not making progress",
                       "landed": False, "position": pos, "ahead": ahead,
                       "stalled_s": round(stalled, 1),
                       "waited_s": round(waited, 1), "worktree": worktree},
                      args.json,
                      f"✗ land refused: queue stalled at position {pos} for "
                      f"{stalled:.0f}s")
                return EXIT_BLOCK
            if waited - last_beat >= 20:
                last_beat = waited
                print(f"[worktree][land] phase=waiting elapsed={waited:.0f}s "
                      f"position={pos} stalled={stalled:.0f}s "
                      f"aheadPid={(ahead or {}).get('pid')} alive=true",
                      file=sys.stderr, flush=True)
            time.sleep(0.4)

        # The CHEAP half of the primary-clean contract, asked before anything
        # expensive has been spent. `cutover` asks the same question again
        # immediately before the ff, and THAT one is the load-bearing check —
        # DO NOT DELETE IT as redundant. The two are at different moments and
        # answer different questions: this one asks "is the primary already dirty
        # right now", cutover's asks "is it still clean now that the gate has
        # finished". Measured 2026-08-08: a primary that was clean at the start was
        # dirtied DURING a 574s gate by the operator's own backlog closures, so an
        # implementation that trusted this answer across the gate would ff over a
        # tenant's uncommitted work.
        #
        # Same helper, not a second copy of the judgement: a duplicated rule is one
        # that drifts, and this one decides whether someone else's working tree gets
        # overwritten.
        guard = _primary_ff_ready(primary, _local_trunk(args.base))
        if guard is not None:
            reason, extra = guard
            _emit({"schema": SCHEMA, "step": "land", "mode": "refused",
                   "error": reason, "landed": False, "worktree": worktree,
                   "primary": str(primary), "refused_before": "gate", **extra},
                  args.json, f"✗ land refused before gate: {reason}")
            return EXIT_BLOCK

        steps: list[dict] = []
        crc, cpay = _land_step(cmd_catchup, commit=True, **common)
        steps.append({"step": "catchup", "rc": crc, "payload": cpay})
        if crc != EXIT_OK:
            _emit({"schema": SCHEMA, "step": "land", "mode": "refused",
                   "error": "catchup refused; the branch could not be brought onto "
                            "the trunk", "landed": False, "steps": steps,
                   "worktree": worktree},
                  args.json, "✗ land refused at catchup")
            return EXIT_BLOCK

        grc, gpay = _land_step(cmd_gate, receipt_line=False, plan_only=False, **common)
        steps.append({"step": "gate", "rc": grc, "verdict": gpay.get("verdict"),
                      "payload": gpay})
        if gpay.get("verdict") not in ("pass", "warn"):
            _emit({"schema": SCHEMA, "step": "land", "mode": "refused",
                   "error": f"gate verdict is {gpay.get('verdict')!r} — fix the "
                            f"blocking gate(s), then run `land` again",
                   "landed": False, "steps": steps, "worktree": worktree},
                  args.json,
                  f"✗ land refused: gate verdict {gpay.get('verdict')!r}")
            return EXIT_BLOCK

        orc, opay = _land_step(cmd_cutover, commit=True, **common)
        steps.append({"step": "cutover", "rc": orc, "payload": opay})
        landed = bool(opay.get("landed"))
        # Two independent reports of the same fact. They can only disagree if the
        # payload did not parse (`_land_step` degrades it to {"raw": ...}, and a
        # missing "landed" then reads as False) — which would have `land` announce
        # a refusal AFTER the trunk already moved. Say so loudly instead of
        # picking whichever one is more comforting.
        if landed != (orc == EXIT_OK):
            payload_disagrees = (
                f"cutover exit code ({orc}) and its payload (landed={landed!r}) "
                f"disagree — trust neither; inspect local {args.base} before doing "
                f"anything else")
            _emit({"schema": SCHEMA, "step": "land", "mode": "refused",
                   "error": payload_disagrees, "landed": None,
                   "cutover_rc": orc, "cutover_payload": opay,
                   "worktree": worktree, "steps": steps},
                  args.json, f"✗ land: {payload_disagrees}")
            return EXIT_BLOCK
        total = time.monotonic() - started
        _emit({"schema": SCHEMA, "step": "land",
               "mode": "committed" if landed else "refused",
               "landed": landed, "worktree": worktree, "queue_seq": seq,
               "waited_for_turn_s": round(waited, 1),
               "elapsed_s": round(total, 1), "gate_runs": 1,
               "verdict": gpay.get("verdict"), "sha": opay.get("sha"),
               "warnings": opay.get("warnings", []), "steps": steps},
              args.json,
              (f"✓ landed {worktree} ({gpay.get('verdict')}) in {total:.0f}s "
               f"after waiting {waited:.0f}s for its turn"
               if landed else
               f"✗ land refused at cutover: {opay.get('error')}"))
        return EXIT_OK if landed else EXIT_BLOCK
    finally:
        _land_release(primary, seq, ticket_fd)


# ============================================================================
# integrate — N branches, ONE gate
# ============================================================================
INTEGRATE_SCHEMA = "kg.worktree.integrate.v1"


def _integrate_state_path(state: str | None, slug: str) -> Path:
    """Where an in-flight integration is parked between invocations.

    A conflict SUSPENDS the run — the operator leaves the process to resolve files by
    hand — so the queue has to survive on disk or `--continue` cannot know what is left
    to pick. Same anchoring as the gate-record cache (beside the ledger, per-machine,
    gitignored): an integration is a local act, and nothing outside this machine has
    any use for its half-finished state.
    """
    base_dir = Path(state).resolve().parent if state else wr.default_state_path().parent
    return base_dir / "worktree_integrations" / f"{slug}.json"


def _integrate_save(path: Path, st: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(st, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8")


def _unmerged_paths(worktree: str) -> list[str]:
    """The files git is waiting on. `--diff-filter=U` is git's own name for the state,
    rather than a reading of porcelain wording, and the paths are C-unquoted for the
    same reason `_porcelain_paths` unquotes: a conflict in a path with non-ASCII bytes
    must still be NAMED, and this repo's docs tree is full of them."""
    rc, out = _git(["diff", "--name-only", "--diff-filter=U"], cwd=worktree)
    if rc != 0:
        return []
    return [_c_unquote(ln) for ln in out.splitlines() if ln]


def _branch_pick_list(repo: Path, trunk: str,
                      branch: str) -> tuple[list[dict[str, Any]], list[str], str | None]:
    """(commits to pick, merge commits found, refusal). Oldest first.

    Merge commits are returned SEPARATELY rather than filtered away. `rev-list
    --no-merges` would drop them silently, and a batch verb whose whole reason for
    existing is "no piece of work goes missing" must not itself be the thing that
    loses one.
    """
    rc, _ = _git(["rev-parse", "--verify", "-q", f"{branch}^{{commit}}"], cwd=repo)
    if rc != 0:
        return [], [], f"{branch!r} does not resolve to a commit in this repo"
    rc, out = _git(["log", "--reverse", "--no-merges", "--format=%H%x1f%s",
                    f"{trunk}..{branch}"], cwd=repo)
    if rc != 0:
        return [], [], f"cannot list {trunk}..{branch}: {out[:200]}"
    commits: list[dict[str, Any]] = []
    for ln in out.splitlines():
        if "\x1f" not in ln:
            continue
        sha, subject = ln.split("\x1f", 1)
        commits.append({"branch": branch, "sha": sha, "subject": subject})
    _, mout = _git(["rev-list", "--merges", f"{trunk}..{branch}"], cwd=repo)
    return commits, [ln for ln in mout.splitlines() if ln], None


def cmd_integrate(args) -> int:
    """Converge N branches into ONE gated tree: fork off the local trunk, cherry-pick
    each branch's commits in order, stop by NAME on a conflict, and run the EXISTING
    `gate` once on the result.

    The question it answers cannot be asked any other way. Each branch's own gate
    proves "my change is green on the main I forked from"; the batch needs "these N
    changes are green TOGETHER", and that tree does not exist until they are merged.
    Measured 2026-08-06 on an eleven-branch batch: review of the integrated tree found
    five blocking defects, every one of them green under its own branch's gate.

    It adds NO judgement of its own — deliberately, because a second opinion about
    pass/fail is a second place for the rules to drift:
      * the verdict comes from `cmd_gate`, run in-process so the judge's identity is
        the one `cutover` will check;
      * `integrate` never lands. `cutover` already refuses a block verdict, so "only
        a non-block result may land" keeps living in exactly one place. Re-deciding
        it here would mean two implementations of the one rule that protects the trunk.
    The exit code propagates the gate's verdict; it does not form one.

    cherry-pick, not merge: a merge makes each source branch's whole ancestry an
    ancestor of the result, which resurrects whatever those branches happened to be
    carrying (measured on the same batch — two branches each held another session's
    discarded commit). Picking is per-commit, so every commit that arrives is one
    somebody named.
    """
    blocked = _freeze_guard(args.state, "integrate", args.json)
    if blocked is not None:
        return blocked
    if not SLUG_RE.match(args.slug or ""):
        _emit({"schema": INTEGRATE_SCHEMA, "step": "integrate", "slug": args.slug,
               "error": "slug must be kebab-case ([a-z0-9] words joined by '-')"},
              args.json,
              f"✗ slug {args.slug!r} must be kebab-case ([a-z0-9] joined by '-')")
        return EXIT_USAGE
    if args.cont and args.abort:
        _emit({"schema": INTEGRATE_SCHEMA, "step": "integrate",
               "error": "--continue and --abort ask for opposite things — pick one"},
              args.json, "✗ integrate: --continue and --abort are mutually exclusive")
        return EXIT_USAGE

    spath = _integrate_state_path(args.state, args.slug)
    if args.abort:
        return _integrate_abort(args, spath)
    if args.cont:
        return _integrate_continue(args, spath)
    return _integrate_start(args, spath)


def _integrate_start(args, spath: Path) -> int:
    trunk = _local_trunk(args.base)
    primary = primary_root()
    if not args.branches:
        _emit({"schema": INTEGRATE_SCHEMA, "step": "integrate",
               "error": "no --branches given — an integration of nothing is not a "
                        "shorter integration, it is a different mistake"},
              args.json, "✗ integrate: --branches <b1> <b2> … is required")
        return EXIT_USAGE
    if spath.exists():
        try:
            live = json.loads(spath.read_text())
        except (OSError, json.JSONDecodeError):
            live = {}
        msg = (f"an integration named {args.slug!r} is already in flight "
               f"(worktree {live.get('worktree')}, {len(live.get('queue') or [])} "
               f"commit(s) still queued) — resume it with `--continue --commit` after "
               f"resolving, or discard it with `--abort --commit`. Starting over on "
               f"top of it would strand a half-picked tree nothing points at")
        _emit({"schema": INTEGRATE_SCHEMA, "step": "integrate", "error": msg,
               "slug": args.slug, "state_file": str(spath),
               "worktree": live.get("worktree")}, args.json,
              f"✗ integrate refused: {msg}")
        return EXIT_USAGE

    plan: list[dict[str, Any]] = []
    problems: list[str] = []
    for branch in args.branches:
        commits, merges, err = _branch_pick_list(primary, trunk, branch)
        if err:
            problems.append(err)
            continue
        if merges:
            problems.append(
                f"{branch!r} carries {len(merges)} merge commit(s) "
                f"({', '.join(s[:8] for s in merges)}) in {trunk}..{branch} — a "
                f"cherry-pick applies ONE parent's diff, so a merge has no unambiguous "
                f"patch to take; flatten the branch (`catchup`/rebase) first")
            continue
        if not commits:
            problems.append(
                f"{branch!r} has no commits in {trunk}..{branch} — nothing to "
                f"integrate. Either it already landed, or you meant a different branch; "
                f"accepting it silently would report a batch as integrated that this "
                f"branch contributed nothing to")
            continue
        plan.append({"branch": branch, "commits": commits})
    # Stacked branches (feat/b forked from feat/a) put feat/a's commits inside
    # `main..feat/b` too, so naming both branches queues those commits TWICE. The
    # second pick is then an empty cherry-pick, which stops the run with no unmerged
    # paths and a diagnosis about conflict resolution — pointing at the wrong thing.
    # Refusing by name here costs one pass over the plan, and it is the same
    # principle as the merge-commit refusal: silently queueing a commit twice is the
    # mirror image of silently dropping one.
    seen: dict[str, list[str]] = {}
    for entry in plan:
        for commit in entry["commits"]:
            seen.setdefault(commit["sha"], []).append(entry["branch"])
    for sha, owners in seen.items():
        if len(owners) > 1:
            problems.append(
                f"commit {sha[:8]} is in {trunk}..<branch> for more than one of the "
                f"branches given ({', '.join(owners)}) — they are stacked, so naming "
                f"both queues the same commit twice and the second pick lands as an "
                f"empty cherry-pick. Name only the tip branch, or rebase them apart")
    if problems:
        _emit({"schema": INTEGRATE_SCHEMA, "step": "integrate", "slug": args.slug,
               "error": "one or more branches cannot be integrated as given",
               "problems": problems, "trunk": trunk}, args.json,
              "✗ integrate refused:\n" + "\n".join(f"  {p}" for p in problems))
        return EXIT_USAGE

    total = sum(len(p["commits"]) for p in plan)
    if not args.commit:
        _emit({"schema": INTEGRATE_SCHEMA, "step": "integrate", "mode": "dry-run",
               "slug": args.slug, "trunk": trunk, "branches": list(args.branches),
               "plan": plan, "commits": total,
               "would_run": [f"open --slug {args.slug}",
                             f"cherry-pick x{total}", "gate"]},
              args.json,
              f"# integrate (dry-run)\n"
              f"  would fork `{args.slug}` off local {trunk}, cherry-pick {total} "
              f"commit(s) from {len(plan)} branch(es), then run ONE gate:\n"
              + "\n".join(
                  f"    {p['branch']}\n" + "\n".join(
                      f"      {c['sha'][:8]} {c['subject']}" for c in p["commits"])
                  for p in plan)
              + "\n  (--commit to execute; nothing lands — `cutover` still does that)")
        return EXIT_OK

    intent = f"integrate a batch of {len(plan)} branch(es) into {trunk}"
    # The intent text deliberately omits the branch NAMES: `classify_intent` reads it
    # to pick the branch type, and a source branch called `debug/fix-crash` would flip
    # this worktree's own type to `debug`. The full list lives in the payload and in
    # the state file, where nothing parses it for meaning.
    orc, opay = _land_step(cmd_open, state=args.state, json=True, base=args.base,
                           slug=args.slug, intent=intent, backlog=None,
                           allow_ungroomed=False)
    if orc != EXIT_OK:
        _emit({"schema": INTEGRATE_SCHEMA, "step": "integrate", "slug": args.slug,
               "error": "could not open the integration worktree", "open": opay},
              args.json,
              f"✗ integrate: could not open the integration worktree — "
              f"{opay.get('error', opay)}")
        return EXIT_BLOCK

    st = {
        "schema": INTEGRATE_SCHEMA, "slug": args.slug, "base": args.base,
        "trunk": trunk, "worktree": opay["path"], "branch": opay["branch"],
        "branches": list(args.branches),
        "queue": [c for p in plan for c in p["commits"]],
        "planned_total": total,
        "picked": [], "skipped": [],
        "opened_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    _integrate_save(spath, st)
    return _integrate_drive(args, spath, st)


def _integrate_drive(args, spath: Path, st: dict[str, Any]) -> int:
    """Pick what is left, then gate once. The loop is resumable because every step
    writes the queue back before the next pick can fail."""
    wt = st["worktree"]
    while st["queue"]:
        item = st["queue"][0]
        head_before = _head_sha(wt)
        print(f"[worktree][integrate] phase=pick branch={item['branch']} "
              f"sha={item['sha'][:8]} remaining={len(st['queue'])}",
              file=sys.stderr, flush=True)
        rc, out = _git_mutation(["cherry-pick", item["sha"]], cwd=wt,
                                label=f"integrate-cherry-pick:{item['branch']}")
        if rc != 0:
            conflicts = _unmerged_paths(wt)
            st["stopped"] = {**item, "head_before": head_before,
                             "detail": out[-2000:]}
            _integrate_save(spath, st)
            head = (f"cherry-pick of {item['sha'][:8]} from {item['branch']!r} "
                    f"stopped")
            if conflicts:
                why = (f"{head} on {len(conflicts)} conflicting file(s). Resolve them "
                       f"in {wt}, `git -C {wt} add <paths>`, then re-run with "
                       f"`--continue --commit`")
            else:
                # No unmerged paths and still a failure: an empty pick, a hook, a
                # broken index. Saying "conflicts: []" here would be the tool
                # inventing a diagnosis; hand over git's own words instead.
                why = (f"{head} with no unmerged paths — git said:\n{out[-800:]}\n"
                       f"  resolve it in {wt} by hand (`git -C {wt} cherry-pick "
                       f"--skip` is the usual answer to an empty pick), then "
                       f"`--continue --commit`; or discard with `--abort --commit`")
            _emit({"schema": INTEGRATE_SCHEMA, "step": "integrate", "mode": "stopped",
                   "slug": st["slug"], "worktree": wt, "branch": st["branch"],
                   "error": why, "conflicts": conflicts, "stopped": st["stopped"],
                   "picked": st["picked"], "remaining": st["queue"],
                   "state_file": str(spath)},
                  args.json, f"✗ integrate stopped: {why}")
            return EXIT_BLOCK
        st["picked"].append({**item, "new_sha": _head_sha(wt)})
        st["queue"] = st["queue"][1:]
        st.pop("stopped", None)
        _integrate_save(spath, st)
    return _integrate_gate(args, spath, st)


def _integrate_gate(args, spath: Path, st: dict[str, Any]) -> int:
    """ONE gate, on the integrated tree, produced by THIS orchestrator.

    In-process for the same reason `land` does it: `cutover` compares the judge's
    identity against the worktree's own copy, so re-execing a different copy is the
    failure that check exists to catch."""
    wt = st["worktree"]
    # Before spending a gate — and before WRITING a verdict cutover will trust —
    # check that the tree about to be judged is the batch that was asked for. Every
    # commit leaves the queue into exactly one of `picked` / `skipped`, so the sum is
    # an invariant of this tool's own bookkeeping, not a judgement about the code
    # (the hard boundary is "do not re-decide pass/fail", and this decides neither).
    # It is worth stating because the failure it catches is invisible: a batch that
    # lost a branch's work still gates GREEN, and green is exactly what cutover is
    # waiting for. Same family as cutover's `gated_sha == rebased_sha` terminal check.
    # Refusing here means no verdict is recorded at all, so cutover then refuses with
    # "no gate verdict on record" rather than landing a short batch.
    planned = st.get("planned_total")
    accounted = len(st["picked"]) + len(st.get("skipped", []))
    if planned is not None and accounted != planned:
        msg = (f"integration bookkeeping does not add up: {planned} commit(s) were "
               f"planned but {accounted} are accounted for "
               f"({len(st['picked'])} picked + {len(st.get('skipped', []))} skipped) "
               f"— refusing to gate, because a batch that quietly lost a branch's "
               f"work gates GREEN and green is what `cutover` waits for. Inspect "
               f"{wt} and the state file, then `--abort --commit` and start over")
        _emit({"schema": INTEGRATE_SCHEMA, "step": "integrate", "mode": "refused",
               "slug": st["slug"], "worktree": wt, "error": msg,
               "planned_total": planned, "accounted": accounted,
               "picked": st["picked"], "skipped": st.get("skipped", []),
               "remaining": st["queue"]}, args.json,
              f"✗ integrate refused: {msg}")
        return EXIT_BLOCK

    grc, gpay = _land_step(cmd_gate, state=args.state, json=True, base=args.base,
                           worktree=wt, receipt_line=False, plan_only=False)
    verdict = gpay.get("verdict")
    if verdict is None:
        # `gate` REFUSED rather than judged (mid-operation tree, orchestrator
        # mismatch, base moved under us) — its payload carries `error` and no
        # `verdict`. Falling through would report "gate verdict: None" and then tell
        # the reader to "fix the blocking gate(s)", which is advice for a different
        # problem entirely; the actual reason is right there in gate's own payload
        # and must be the thing that reaches the operator.
        why = gpay.get("error") or f"gate produced no verdict (rc={grc})"
        _emit({"schema": INTEGRATE_SCHEMA, "step": "integrate", "mode": "refused",
               "slug": st["slug"], "worktree": wt, "head_sha": _head_sha(wt),
               "error": f"the gate refused to judge this tree: {why}",
               "gate_rc": grc, "gate_payload": gpay}, args.json,
              f"✗ integrate: the gate refused to judge {wt}:\n  {why}")
        return grc
    head = _head_sha(wt)
    st["gate"] = {
        "verdict": verdict, "rc": grc, "head_sha": gpay.get("head_sha"),
        "record": str(_gate_record_path(args.state, wt)),
        "gates": [{"name": g.get("name"), "status": g.get("status"),
                   "summary": g.get("summary")}
                  for g in (gpay.get("gates") or [])
                  if g.get("status") in ("block", "warn", "inconclusive")],
    }
    _integrate_save(spath, st)
    next_step = (f"{wt}/ops/worktree_orchestrate.py cutover --worktree {wt} --commit"
                 if verdict in ("pass", "warn")
                 else f"fix the blocking gate(s), then re-run `gate` in {wt}")
    payload = {
        "schema": INTEGRATE_SCHEMA, "step": "integrate", "mode": "committed",
        "slug": st["slug"], "worktree": wt, "branch": st["branch"],
        "trunk": st["trunk"], "branches": st["branches"],
        "picked": st["picked"], "skipped": st.get("skipped", []),
        "head_sha": head, "gate": st["gate"], "gate_runs": 1,
        "verdict": verdict, "landed": False, "next_step": next_step,
        "state_cleared": True,
    }
    # The queue is drained and the gate has spoken, so there is nothing left to
    # `--continue`; keeping the file made a FINISHED integration answer the next
    # `integrate --slug <same>` with "already in flight … resume it with --continue
    # after resolving", which is false in three ways at once. It is also the residue
    # `resolve` does not know how to strike, against a module docstring that promises
    # none. A crashed run still leaves one — that case is caught by --continue's
    # "the integration worktree is gone" refusal, which names --abort.
    spath.unlink(missing_ok=True)
    lines = [f"# integrate {args.slug}: {len(st['picked'])} commit(s) from "
             f"{len(st['branches'])} branch(es) -> {head[:8]}",
             f"  gate verdict: {verdict}  (record {st['gate']['record']})"]
    for g in st["gate"]["gates"]:
        lines.append(f"  {'✗' if g['status'] == 'block' else '⚠'} {g['name']} — "
                     f"{g.get('summary', '')}")
    if st.get("skipped"):
        lines.append("  skipped (produced no commit): "
                     + ", ".join(f"{c['sha'][:8]} ({c['branch']})"
                                 for c in st["skipped"]))
    lines.append("  NOT landed — integrate gates, cutover lands:")
    lines.append(f"    {next_step}")
    _emit(payload, args.json, "\n".join(lines))
    # `grc` IS the gate's verdict expressed as an exit code. Recomputing it here from
    # the verdict string was a second copy of the one judgement this command is not
    # allowed to own — and it lost information: gate's EXIT_USAGE(64) came out as
    # EXIT_BLOCK(1), so a caller could not tell "I invoked it wrong" from "it refused".
    return grc


def _integrate_load(args, spath: Path, verb: str) -> dict[str, Any] | int:
    if not spath.exists():
        msg = (f"no integration named {args.slug!r} is in flight (nothing at {spath}) "
               f"— start one with `integrate --slug {args.slug} --branches <b1> <b2> … "
               f"--commit`")
        _emit({"schema": INTEGRATE_SCHEMA, "step": "integrate", "slug": args.slug,
               "error": msg, "state_file": str(spath)}, args.json,
              f"✗ integrate --{verb} refused: {msg}")
        return EXIT_USAGE
    try:
        return json.loads(spath.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        _emit({"schema": INTEGRATE_SCHEMA, "step": "integrate", "slug": args.slug,
               "error": f"integration state at {spath} is unreadable ({exc}) — "
                        f"inspect the worktree by hand; delete the file only once you "
                        f"know what is already picked"}, args.json,
              f"✗ integrate --{verb} refused: unreadable state at {spath}")
        return EXIT_BLOCK


def _integrate_continue(args, spath: Path) -> int:
    st = _integrate_load(args, spath, "continue")
    if isinstance(st, int):
        return st
    wt = st["worktree"]
    if not Path(wt).is_dir():
        _emit({"schema": INTEGRATE_SCHEMA, "step": "integrate", "slug": args.slug,
               "error": f"the integration worktree is gone ({wt}) — nothing to "
                        f"continue; discard the state with `--abort --commit`"},
              args.json, f"✗ integrate --continue refused: {wt} is gone")
        return EXIT_BLOCK

    here = _current_branch(wt)
    if here != st.get("branch"):
        # Cheap, and it guards the same thing F1 does from the other side: the state
        # file says which branch this integration is assembling, and everything after
        # this point (the picks, the verdict, the sha cutover will land) is about
        # whatever branch is actually checked out. A worktree someone moved is not a
        # worktree this integration can speak for.
        _emit({"schema": INTEGRATE_SCHEMA, "step": "integrate", "mode": "refused",
               "slug": args.slug, "worktree": wt, "expected_branch": st.get("branch"),
               "actual_branch": here,
               "error": f"{wt} is on {here!r}, but this integration is assembling "
                        f"{st.get('branch')!r} — check the branch back out, or "
                        f"`--abort --commit` and start over"}, args.json,
              f"✗ integrate --continue refused: {wt} is on {here!r}, not "
              f"{st.get('branch')!r}")
        return EXIT_BLOCK

    unmerged = _unmerged_paths(wt)
    if unmerged:
        msg = (f"{len(unmerged)} file(s) are still unmerged — resolve them and "
               f"`git -C {wt} add <paths>` before continuing")
        _emit({"schema": INTEGRATE_SCHEMA, "step": "integrate", "mode": "stopped",
               "slug": args.slug, "worktree": wt, "error": msg,
               "conflicts": unmerged, "remaining": st["queue"]}, args.json,
              f"✗ integrate --continue refused: {msg}\n"
              + "\n".join(f"    {p}" for p in unmerged))
        return EXIT_BLOCK

    if not args.commit:
        _emit({"schema": INTEGRATE_SCHEMA, "step": "integrate", "mode": "dry-run",
               "slug": args.slug, "worktree": wt, "picked": st["picked"],
               "remaining": st["queue"], "stopped": st.get("stopped")}, args.json,
              f"# integrate --continue (dry-run)\n"
              f"  would conclude the stopped pick and apply {len(st['queue'])} "
              f"remaining commit(s), then run ONE gate\n  (--commit to execute)")
        return EXIT_OK

    op = _interrupted_operation(wt)
    if op == "cherry-pick":
        rc, out = _git_mutation(["cherry-pick", "--continue"], cwd=wt,
                                label="integrate-cherry-pick-continue")
        if rc != 0:
            _emit({"schema": INTEGRATE_SCHEMA, "step": "integrate", "mode": "stopped",
                   "slug": args.slug, "worktree": wt,
                   "error": f"`git cherry-pick --continue` failed:\n{out[-800:]}\n"
                            f"  fix it in {wt} (an empty pick wants `git -C {wt} "
                            f"cherry-pick --skip`), then re-run --continue; or "
                            f"`--abort --commit`",
                   "detail": out[-2000:]}, args.json,
                  f"✗ integrate --continue: cherry-pick --continue failed:\n{out}")
            return EXIT_BLOCK
    elif op is not None:
        _emit({"schema": INTEGRATE_SCHEMA, "step": "integrate", "slug": args.slug,
               "worktree": wt, "interrupted": op,
               "error": f"a {op} is in progress in {wt} — conclude or abort it before "
                        f"continuing the integration"}, args.json,
              f"✗ integrate --continue refused: a {op} is in progress in {wt}")
        return EXIT_BLOCK

    stopped = st.get("stopped")
    if stopped:
        # Whether the stopped pick produced a commit is answered by the HEAD, not by
        # what we hope the operator did: `--skip`, an empty resolution, or a manual
        # `cherry-pick --continue` all leave the same absence of CHERRY_PICK_HEAD, and
        # only the sha distinguishes "it landed" from "it did not".
        entry = {k: stopped[k] for k in ("branch", "sha", "subject")}
        if _head_sha(wt) != stopped.get("head_before"):
            st["picked"].append({**entry, "new_sha": _head_sha(wt)})
        else:
            st.setdefault("skipped", []).append(entry)
        st["queue"] = st["queue"][1:]
        st.pop("stopped", None)
        _integrate_save(spath, st)
    return _integrate_drive(args, spath, st)


def _integrate_abort(args, spath: Path) -> int:
    """Abandon an in-flight integration: undo the suspended pick and drop the state.

    It deliberately does NOT remove the worktree. Teardown is `resolve`'s job and only
    `resolve` consults the landed-floor; a verb that both abandons work and deletes the
    tree holding it is one keystroke away from discarding a resolution somebody spent
    an hour on."""
    st = _integrate_load(args, spath, "abort")
    if isinstance(st, int):
        return st
    wt = st["worktree"]
    op = _interrupted_operation(wt) if Path(wt).is_dir() else None
    teardown = (f"ops/worktree_orchestrate.py resolve --worktree {wt} --force "
                f"--commit  (--force because nothing here landed)")
    if not args.commit:
        _emit({"schema": INTEGRATE_SCHEMA, "step": "integrate", "mode": "dry-run",
               "slug": args.slug, "worktree": wt, "interrupted": op,
               "picked": st["picked"], "remaining": st["queue"],
               "next_step": teardown}, args.json,
              f"# integrate --abort (dry-run)\n"
              f"  would abort the in-flight {op or 'nothing'} in {wt} and forget the "
              f"integration state\n"
              f"  the worktree SURVIVES ({len(st['picked'])} commit(s) already picked) "
              f"— tear it down with:\n    {teardown}\n  (--commit to execute)")
        return EXIT_OK
    if op == "cherry-pick":
        rc, out = _git_mutation(["cherry-pick", "--abort"], cwd=wt,
                                label="integrate-cherry-pick-abort")
        if rc != 0:
            _emit({"schema": INTEGRATE_SCHEMA, "step": "integrate", "slug": args.slug,
                   "worktree": wt, "error": f"`git cherry-pick --abort` failed:\n{out}"
                                            f"\n  the state file is KEPT so nothing is "
                                            f"lost; fix the worktree by hand",
                   "detail": out[-2000:]}, args.json,
                  f"✗ integrate --abort failed:\n{out}")
            return EXIT_BLOCK
    spath.unlink(missing_ok=True)
    _emit({"schema": INTEGRATE_SCHEMA, "step": "integrate", "mode": "committed",
           "slug": args.slug, "worktree": wt, "aborted": op,
           "picked": st["picked"], "abandoned": st["queue"],
           "worktree_removed": False, "next_step": teardown}, args.json,
          f"✓ integrate --abort: {op or 'nothing'} aborted, integration state "
          f"forgotten\n  worktree kept ({len(st['picked'])} picked commit(s)) — "
          f"tear it down with:\n    {teardown}")
    return EXIT_OK


def cmd_catchup(args) -> int:
    """Bring a worktree onto the current local trunk — the step `gate` and `cutover`
    both send you to when the trunk moved under the branch.

    It existed as a sentence before it existed as a command: both refusals used to
    say "run `git -C <path> rebase main`". Handing an agent raw git there is fine
    right up until the rebase conflicts — and what the agent then does is unbounded,
    which is why the remedy belongs to a verb the flow controls rather than to a
    sentence in an error message. The original argument was narrower (the rebase kept
    conflicting on a 280KB GENERATED ledger view, 3 to 6 branches out of ten in a
    single round, and that file had one right answer), and it no longer applies: the
    view left version control in IMP-20260807-b9526c and the resolver went with it.
    `_rebase_onto` is the authority on the behaviour; this is now a clean rebase and
    every conflict is a real decision that goes to a human.
    """
    # `freeze` is a stop-the-world lock for repo surgery — history rewrite, gc,
    # shared hooks. `catchup` REWRITES HISTORY (that is what a rebase is), so it
    # belongs on the blocked side with open/adopt/cutover/sync/deploy, not on the
    # draining side with resolve/sweep/gate. It was missed simply because it is the
    # newest primitive; a lock that a new verb can walk past is not a lock.
    blocked = _freeze_guard(args.state, "catchup", args.json)
    if blocked is not None:
        return blocked
    worktree = _norm(args.worktree)
    trunk = _local_trunk(args.base)
    if not Path(worktree).is_dir():
        _emit({"schema": SCHEMA, "step": "catchup", "mode": "refused",
               "error": f"no such worktree: {worktree}"},
              args.json, f"✗ no such worktree: {worktree}")
        return EXIT_BLOCK
    drift = _base_containment(worktree, trunk)
    if drift is None:
        # `mode` on every branch, including this one: it is the most common outcome
        # (agents run `catchup` speculatively), so a machine caller reading
        # payload["mode"] would KeyError precisely where nothing went wrong.
        _emit({"schema": SCHEMA, "step": "catchup", "mode": "noop", "worktree": worktree,
               "trunk": trunk, "behind": False, "rebased": False,
               "sha": _head_sha(worktree)}, args.json,
              f"✓ already on top of {trunk} — nothing to catch up to")
        return EXIT_OK
    if drift.get("containment_error"):
        _emit({"schema": SCHEMA, "step": "catchup", "mode": "refused",
               "error": _behind_base_refusal(worktree, trunk, drift), **drift},
              args.json, f"✗ catchup refused: {_behind_base_refusal(worktree, trunk, drift)}")
        return EXIT_BLOCK
    if not args.commit:
        _emit({"schema": SCHEMA, "step": "catchup", "mode": "dry-run", "rebased": False,
               "worktree": worktree, "trunk": trunk, "behind": True, **drift}, args.json,
              f"# catchup (dry-run)\n  {worktree} is {drift['behind_commits']} commit(s) "
              f"behind {trunk}; {len(drift['base_changed_files'])} file(s) changed there\n"
              f"  would rebase onto {trunk} (--commit); a conflict aborts and comes "
              f"back to you\n  then re-run `gate`")
        return EXIT_OK

    before = _head_sha(worktree)
    rc, out = _rebase_onto(worktree, trunk, "catchup-rebase")
    if rc != 0:
        _git_mutation(["rebase", "--abort"], cwd=worktree, label="catchup-rebase-abort")
        _emit({"schema": SCHEMA, "step": "catchup", "mode": "committed",
               "error": "rebase failed (aborted)", "detail": out, "rebased": False,
               "worktree": worktree, "trunk": trunk}, args.json,
              f"✗ rebase onto {trunk} failed (aborted):\n{out}")
        return EXIT_BLOCK
    sha = _head_sha(worktree)
    _emit({"schema": SCHEMA, "step": "catchup", "mode": "committed", "rebased": True,
           "worktree": worktree, "trunk": trunk,
           "sha": sha, "previous_sha": before}, args.json,
          f"✓ catchup: {worktree} rebased onto {trunk} ({before[:8]} -> {sha[:8]})"
          f"\n  HEAD moved, so any gate verdict is now stale — re-run `gate`")
    return EXIT_OK

_REPAIR_MESSAGE = (
    "ops: cutover 落地後重新推導 ledger 錨點\n\n"
    "rebase 在 gate 之後改寫了分支的 sha,所以 entry 的 fixed_by 在落地那一刻\n"
    "才指得到正確的 commit。這顆 commit 由 cutover 自己產生,內容全部是\n"
    "`backlog.py reanchor --commit` + `render --commit` 從既有資料重新推導的。\n\n"
    "Review-Exempt: machine-repair"
)


def _ledger_dirty(primary: Path) -> tuple[int, str]:
    """Tracked-only dirtiness of the ledger paths.

    `--untracked-files=no` on purpose, matching `_primary_ff_ready`: an untracked
    entry JSON in the primary is a LEGAL and common state (an agent filed one and
    has not committed it), and it does not block anybody's cutover. Counting it as
    dirt is what led the repair to sweep other people's unfinished work into a
    commit carrying a review exemption.
    """
    return _git(["status", "--porcelain", "--untracked-files=no", "--", *LEDGER_PATHS],
                cwd=primary)


def _repair_restore(primary: Path, out: dict[str, Any]) -> None:
    """Put the ledger paths back to HEAD after a failed repair, and VERIFY it.

    The one thing a failed repair must not do is leave the primary dirty: that is
    the exact condition `_primary_ff_ready` refuses on, so an abandoned repair does
    not fail one cutover, it fails EVERY later one — and it does so with a message
    pointing the next agent at "another session is working in the primary", which is
    not what happened. Measured before this existed: `render --commit` returned its
    own designed refusal (exit 2, entry-loss guard), the already-written `reanchor`
    edit was left behind, and the next cutover was blocked.

    `restored` is set from a RE-READ of git's status, not from the exit code of the
    restore command. The first version reported success from `checkout`'s rc while
    the tree was still dirty — `checkout HEAD -- <dir>` is a silent no-op for a path
    that is staged-new and absent from HEAD. Asserting the property instead of the
    command is the only version that cannot drift away from what it claims.

    `reset` then `checkout HEAD --` is belt AND braces, and measurably redundant
    today: with the reset first, the plain `checkout --` form restores from an index
    that already matches HEAD, so the two are equivalent — a mutation swapping them
    survives every test, correctly. The pair is kept because each covers the other's
    failure mode if a staging step ever returns to this function, and because the
    re-read below is what actually decides the verdict either way.

    Untracked files under these paths are deliberately NOT touched: they are someone
    else's unfinished work, and this function's job is to undo its own edits.
    """
    _git(["reset", "-q", "--", *LEDGER_PATHS], cwd=primary)
    _git(["checkout", "HEAD", "--", *LEDGER_PATHS], cwd=primary)
    rc, dirty = _ledger_dirty(primary)
    out["restored"] = rc == 0 and not dirty.strip()
    if not out["restored"]:
        out["error"] = (f"{out.get('error', '?')} | AND the primary could not be "
                        f"restored ({dirty.strip()[:200]}) — it is dirty and the next "
                        f"cutover will refuse until you clean docs/runbook by hand")


ANCHOR_QUEUE = ".cache/backlog_anchor_queue.jsonl"


def _anchor_queue(primary: Path) -> Path:
    return Path(primary) / ANCHOR_QUEUE


def _read_anchor_queue(primary: Path) -> list[dict[str, Any]]:
    path = _anchor_queue(primary)
    if not path.exists():
        return []
    try:
        return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines()
                if ln.strip()]
    except (OSError, json.JSONDecodeError):
        # Never fatal HERE: a landing that already happened must not be reported as
        # failed because this per-machine sidecar was unreadable.
        #
        # But be honest about what that costs. `backlog.py anchor` is the other
        # reader and it fails LOUD on the same file (BacklogError naming the line),
        # so an unreadable queue is silent through cutover and resolve and only
        # surfaces at wave end. The rows do not "stay unstamped and get reported" —
        # from here they are invisible, so nothing reports them at all. That is the
        # right direction for a step that has already moved the trunk and the wrong
        # one for a step that has not, which is why the two policies differ.
        return []


def _write_atomic(path: Path, body: str) -> None:
    """Same shape as `worktree_registry.save_state`: sibling temp then `os.replace`,
    so a crash mid-write cannot leave a half-line. Local rather than imported because
    that one also serializes the ledger's dict; this writes jsonl text."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(body, encoding="utf-8")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def _stamp_anchor_queue(primary: Path, branch: str, sha: str) -> list[str]:
    """Record which commit actually reached the trunk, for this branch's rows.

    A hunter stages its closure BEFORE the branch is rebased, so it cannot know
    which commit will carry the fix — writing the pre-rebase sha is precisely the
    orphaned `fixed_by` the reanchor repair exists to clean up afterwards. This is
    the first moment the answer exists.

    Called AFTER every post-ff refusal. `make_commit_state` accepts a sha reachable
    from HEAD *or* main, so a sha written by a cutover that was then refused would
    still validate when anchored from a worktree that has not been torn down — the
    entry would close against a commit on no trunk, and nothing downstream would
    complain. Placing this earlier looks harmless for exactly that reason.

    Under the queue lock, and the loss it prevents is worse here than at `stage`.
    Measured with the window widened (the method this repo's `_view_lock` docstring
    already uses), in BOTH orders — a concurrent `stage` straddling this write drops
    the stamp back to null, while cutover still reports `staged_closures: [IMP-…]`
    and prints it. By then the branch is in the trunk and `resolve` has torn the
    worktree down; this function only ever runs during that branch's cutover, so
    the sha is never re-derived. `anchor` then files the row under "its branch has
    not landed", which is false, and the only copy of the answer was in a payload
    nobody kept. So: same lock as `stage`, and `_write_atomic` rather than
    `write_text`, whose partial write would leave a truncated line that
    `_read_anchor_queue` swallows and `anchor` chokes on.
    """
    queue = _anchor_queue(primary)
    with wr._ledger_lock(queue):
        rows = _read_anchor_queue(primary)
        stamped = []
        for row in rows:
            if row.get("branch") == branch and not row.get("landed_sha"):
                row["landed_sha"] = sha
                stamped.append(row.get("id"))
        if stamped:
            try:
                _write_atomic(
                    queue,
                    "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
            except OSError:
                return []
        return stamped


def _post_landing_repair(primary: Path) -> dict[str, Any]:
    """Re-derive what the rebase invalidated, in the checkout that now holds it.

    `cutover` rebases the branch onto the current trunk and then fast-forwards. That
    rebase runs AFTER the gate — the last thing to check the tree runs before the last
    thing to change it — so `fixed_by` shas written on the branch are rewritten by the
    rebase and become `fixed-by-orphaned` (measured: validate 0 problems -> 1).
    `reanchor` maps them back by `git patch-id --stable`, and refuses to guess when it
    cannot. That is not repairable from the branch: the correct sha does not exist
    until the landing has happened.

    `render` follows because the store just changed. (It used to also be the fix for
    stale aggregate counters in the view; those are gone — `backlog.py:render_view`
    says why — so this is now the ordinary "re-derive the derived artifact" step.)

    Committed, not left in the tree: an uncommitted repair merely relocates the
    failure to the next `cutover`, which refuses on a dirty primary. And if any step
    fails, the tree is put BACK — see `_repair_restore`.

    It never fails the cutover. The landing already happened; reporting a repair
    problem loudly is honest, rolling back a completed ff is not.
    """
    tool = Path(primary) / "ops" / "backlog.py"
    out: dict[str, Any] = {"ran": False, "committed": False, "steps": [], "ok": True}
    if not tool.exists():
        out["reason"] = "no ledger tool in this checkout"
        return out
    out["ran"] = True
    # `reanchor` only. The rebase inside cutover rewrites the branch's commit shas,
    # which orphans any `fixed_by` recorded against them — that is a fact about the
    # STORE and survives the view's removal. The second step used to be `render`,
    # which now has no tracked file to keep in step.
    for sub, label in (("reanchor", "ledger-reanchor"),):
        rc, text = _tool_mutation([sys.executable, str(tool), sub, "--commit"],
                                  cwd=primary, label=label)
        out["steps"].append({"step": sub, "rc": rc})
        if rc != 0:
            out["ok"] = False
            out["error"] = f"{sub} exited {rc}: {text.strip()[:300]}"
            _repair_restore(primary, out)
            return out
    rc, dirty = _ledger_dirty(primary)
    if rc != 0:
        out["ok"] = False
        out["error"] = "could not read the primary's status after the repair"
        return out
    if not dirty.strip():
        return out
    # NO `git add`, and a pathspec on the commit. Both matter, and the reason is the
    # same: `git commit -- <paths>` takes the working-tree content of the TRACKED
    # files under those paths and nothing else. A `git add -- docs/runbook/backlog`
    # also stages untracked entry JSONs, which is precisely how a co-tenant's
    # uncommitted filing got swept into a commit whose message says "everything here
    # was re-derived by a tool" and whose trailer buys it past the review gate.
    # Measured: the repair commit contained COTENANT.json; without the add, it
    # contains only the file `reanchor` actually rewrote.
    crc, ctext = _git_mutation(["commit", "-m", _REPAIR_MESSAGE, "--", *LEDGER_PATHS],
                               cwd=primary, label="ledger-repair-commit")
    if crc != 0:
        out["ok"] = False
        out["error"] = f"repair commit failed: {ctext.strip()[:300]}"
        _repair_restore(primary, out)
        return out
    out["committed"] = True
    # The repair rewrote ledger data on the trunk and no gate has looked at the
    # result — the gate ran on the branch, before the rebase that made the repair
    # necessary. So the repair checks its own work; a mis-anchored `fixed_by` landing
    # silently would be handed to whichever branch cuts over next.
    vrc, vtext = _tool_mutation(
        [sys.executable, str(tool), "validate", "--baseline-check"],
        cwd=primary, label="ledger-validate")
    out["steps"].append({"step": "validate", "rc": vrc})
    if vrc != 0:
        out["ok"] = False
        out["error"] = ("the repair landed but `validate --baseline-check` is red on "
                        f"the result: {vtext.strip()[:300]}")
    return out


def _active_ledger_records(state: str | None, branch: str) -> list[dict[str, Any]]:
    """Active ledger records naming this BRANCH. Read-only — the write is still the
    registry's own `resolve`.

    Deliberately not "…or this path", unlike the registry's own resolve selector: the
    question a teardown asks is "does an authority vouch for deleting THIS BRANCH",
    and a record that merely proves the path is registered answers a different one.
    Matching on path lets a worktree's own registration vouch for deleting an
    unrelated branch named on the command line."""
    path = Path(state).resolve() if state else wr.default_state_path()
    try:
        data = wr.load_state(path)
    except (OSError, ValueError, json.JSONDecodeError):
        return []
    return [r for r in data.get("records", [])
            if r.get("status") == wr.STATUS_ACTIVE and r.get("branch") == branch]


def _ledger_branches_for_path(state: str | None, worktree: str) -> list[str]:
    """Every branch the ledger has ever recorded at this path, any status.

    Status-blind on purpose: this is a DERIVATION source of last resort, not an
    authorisation. It covers the states where git's admin entry is gone but the
    path is still real — `worktree remove` erroring partway drops the entry anyway,
    and any `git worktree prune` in the repo (including one issued for an unrelated
    worktree) removes it. Without this the operator's only recourse would be to
    hand-type --branch, which is the guess this change exists to eliminate."""
    path = Path(state).resolve() if state else wr.default_state_path()
    try:
        data = wr.load_state(path)
    except (OSError, ValueError, json.JSONDecodeError):
        return []
    target = _norm(worktree)
    seen: list[str] = []
    for r in data.get("records", []):
        if r.get("path") and _norm(r["path"]) == target and r.get("branch"):
            if r["branch"] not in seen:
                seen.append(r["branch"])
    return seen


def _protected_branches(base: str, target: str | None) -> tuple[str | None, set[str]]:
    """The registry's protected set, widened by terms that do NOT depend on `--base`.

    `wr.sweep_guards` derives everything from `--base` plus the primary's current
    checkout, so `--base origin/prod` while the primary sits on some other branch
    leaves `main` unprotected — and a resolve then deletes local `main` outright.
    Measured, not hypothesised. A floor that a caller-supplied flag can lower is not
    a floor, so three base-independent terms are added:

      * the local trunk (`BASE_DEFAULT`) — in this repo's local-main-centric topology
        deleting it is never a legitimate outcome, whatever `--base` says;
      * the remote's default branch, read from `origin/HEAD`;
      * every branch checked out in any OTHER worktree — which internalises a refusal
        we were previously outsourcing to git ("cannot delete branch used by worktree
        at …"). The target's own branch is excluded because removing its worktree
        first is exactly how a legitimate teardown frees it."""
    primary_path, protected = wr.sweep_guards(base)
    protected.add(BASE_DEFAULT)
    rc, ref = _git(["symbolic-ref", "--quiet", "refs/remotes/origin/HEAD"],
                   cwd=primary_root())
    if rc == 0 and ref:
        protected.add(ref.rsplit("/", 1)[-1])
    norm_target = _norm(target) if target else None
    for w in wr._worktrees():
        if w.get("branch") and _norm(w["path"]) != norm_target:
            protected.add(w["branch"])
    return primary_path, protected


def _rm_target_vetted(worktree: str, state: str | None) -> bool:
    """Whether this path may be handed to a recursive delete.

    `git worktree remove` validates before deleting — that validation is why the
    incident's re-run got rc=128 instead of destroying anything. A raw recursive
    delete has none, and git will list an ADOPTED worktree at an arbitrary path
    anywhere on the filesystem. So the target must either live under this repo's
    worktree root, or be a path the ledger itself recorded."""
    root = _norm(str(primary_root() / ".claude" / "worktrees"))
    if _norm(worktree).startswith(root + os.sep):
        return True
    return bool(_ledger_branches_for_path(state, worktree))


# Refusal codes, and the exit status each carries. Misuse ("you pointed me at the
# wrong thing") stays EXIT_USAGE; a safety refusal ("what you asked for is not a
# legitimate outcome") is EXIT_BLOCK. Emitted as `reason_code` beside the prose so a
# caller can switch on the decision instead of grepping a sentence that will be
# reworded.
RESOLVE_REFUSALS = {
    "not-a-worktree": EXIT_USAGE,
    "detached-head": EXIT_USAGE,
    "ambiguous-ledger": EXIT_USAGE,
    "protected-branch": EXIT_BLOCK,
    "primary-worktree": EXIT_BLOCK,
    "branch-contradicts-git": EXIT_BLOCK,
    "uncorroborated-branch": EXIT_BLOCK,
    "rm-target-unvetted": EXIT_BLOCK,
    "unsafe-step": EXIT_BLOCK,
}


def _resolve_target(worktree: str, explicit: str | None, base: str, state: str | None
                    ) -> tuple[str | None, dict[str, Any] | None, str | None, str | None]:
    """(branch, git worktree entry, refusal code, reason) — the single chokepoint
    every teardown target passes through. NEVER falls back to the invoking cwd's HEAD.

    The protected set comes from the registry's own `sweep_guards`, which already
    owns the invariant "the base branch and the primary worktree are never torn
    down". Sweep consulted it; resolve did not, which is how a mis-derived branch
    reached `branch -D main` and `push origin --delete main` with nothing but git's
    external refusals in the way (IMP-20260806-1359bd)."""
    entry = _worktree_entry(worktree)
    # git CONTRADICTING the caller is categorically worse than git having nothing to
    # say, and the two must not collapse into one condition. When they do, a ledger
    # record belonging to a DIFFERENT worktree can vouch for the branch named here:
    # `resolve --worktree <alpha> --branch <bravo's branch>` then tears down alpha
    # and deletes bravo's remote branch, with only git's "cannot delete branch used
    # by worktree at …" standing in the way of the local half. No ledger record from
    # elsewhere may override git's direct statement about THIS path.
    if entry is not None and explicit and entry.get("branch") \
            and entry["branch"] != explicit:
        return None, entry, "branch-contradicts-git", (
            f"git says {worktree} is on {entry['branch']!r}, not {explicit!r} — "
            "refusing to tear down one worktree while deleting another's branch. "
            "Drop --branch to target what git names.")
    branch = explicit
    if not branch:
        if entry is not None:
            if entry.get("detached") or not entry.get("branch"):
                return None, entry, "detached-head", (
                    f"{worktree} has a detached HEAD — there is no branch to resolve; "
                    "pass --branch to name one explicitly")
            branch = entry["branch"]
        else:
            # git no longer lists the path; fall back to what the ledger recorded FOR
            # THIS PATH. Never to `rev-parse`, whose answer here is the enclosing
            # checkout's branch.
            candidates = _ledger_branches_for_path(state, worktree)
            if len(candidates) == 1:
                branch = candidates[0]
            elif len(candidates) > 1:
                return None, None, "ambiguous-ledger", (
                    f"the ledger records more than one branch at {worktree} "
                    f"({', '.join(candidates)}) — pass --branch to disambiguate")
            else:
                return None, None, "not-a-worktree", (
                    f"{worktree} is not a git worktree and the ledger has never "
                    "recorded one there — refusing to guess its branch, because "
                    "asking a directory for its HEAD answers with the ENCLOSING "
                    "checkout's branch (the primary's, for anything under the repo). "
                    "Pass --branch to name the target explicitly.")

    primary_path, protected = _protected_branches(base, worktree)
    if primary_path is None:
        # A real repo always lists at least the primary worktree. An empty list means
        # the probe failed, and `sweep_guards` cannot distinguish that from "nothing
        # is protected" — so treat it as unknown and fail closed rather than tear
        # down against an empty protected set.
        return None, entry, "not-a-worktree", (
            "cannot enumerate this repository's worktrees — refusing to tear anything "
            "down while the protected set is unknown")
    if branch in protected:
        return None, entry, "protected-branch", (
            f"branch {branch!r} is protected — it is the base branch or the primary "
            "worktree's checked-out branch, and deleting it is never a resolve "
            "outcome (registry sweep_guards)")
    if _norm(worktree) == primary_path:
        return None, entry, "primary-worktree", (
            f"{worktree} is the PRIMARY worktree — removing it destroys the repository")
    return branch, entry, None, None


def _entry_is_closed(root: Path, entry_id: str) -> bool:
    """Is this ticket already resolved in the store? Plain file read, fail-open.

    The queue is NOT sufficient on its own, and this function is here because the
    guard it feeds false-positived on its first real teardown. The documented order
    is stage -> cutover -> resolve -> (wave end) anchor, and under that order the
    row is still queued when `resolve` looks. But anchoring BEFORE resolving is
    equally legitimate — and `anchor --commit` DRAINS the queue, so the row that
    proved the closure is gone by the time the guard runs. Measured: the very
    teardown that landed this guard reported its own correctly-closed ticket.

    A warning that fires on a normal path is a warning that gets switched off, and
    it would have taken the real signal with it.

    Read directly rather than through `backlog.py`: this module is deliberately
    dependency-free (the bootstrap paradox — it has to run in a checkout too old to
    have the rest of the toolchain), and it already treats the store as paths under
    `LEDGER_PATHS`. Fail-OPEN — an unreadable entry yields False, i.e. "still open",
    so the guard speaks up rather than going quiet on a file it could not check.
    """
    path = Path(root) / "docs" / "runbook" / "backlog" / f"{entry_id}.json"
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("status") in (
            "fixed", "wont-fix")
    except (OSError, json.JSONDecodeError, AttributeError):
        return False


def _claimed_tickets(state: str | None, branch: str) -> list[str]:
    """Tickets the ACTIVE ledger record for `branch` claims. Read-only, fail-soft.

    Goes through the registry's own `list --json` rather than reaching into the
    state file: the ledger's location is derived (git-common-dir anchored) and its
    schema belongs to that module. A second hand-rolled reader here is how the two
    drift — this repo has already paid for a hand-copied lock path that watched the
    wrong file and reported FREE unconditionally.
    """
    rc, out = _registry(["list", *_state_arg(state), "--json"])
    if rc != 0 or not isinstance(out, dict):
        return []
    for rec in out.get("records", []):
        if isinstance(rec, dict) and rec.get("branch") == branch \
                and rec.get("status") == "active":
            return [str(t) for t in (rec.get("backlog") or [])]
    return []


AUDIT_SEARCH_DEPTH = 2000


def _patch_id_index(ref: str, depth: int) -> dict[str, str]:
    """patch-id -> commit sha, for the last `depth` commits reachable from `ref`.

    One `git log -p | git patch-id` pass rather than two processes per commit:
    at depth 2000 the per-commit form takes minutes, and a check nobody is willing
    to wait for is a check that gets skipped.
    """
    proc = subprocess.run(
        f"git log -p --no-color --max-count={int(depth)} {shlex.quote(ref)} "
        f"| git patch-id --stable",
        shell=True, cwd=str(primary_root()), stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL, text=True)
    index: dict[str, str] = {}
    for line in proc.stdout.splitlines():
        parts = line.split()
        if len(parts) == 2:
            index.setdefault(parts[0], parts[1])
    return index


def _subject_file_index(ref: str, depth: int) -> dict[str, list[tuple[str, frozenset]]]:
    """subject -> [(sha, files)], the weaker match's raw material."""
    rc, out = _git(["log", f"--max-count={int(depth)}", "--name-only",
                    "--format=%x01%H%x00%s", ref])
    index: dict[str, list[tuple[str, frozenset]]] = {}
    if rc != 0:
        return index
    for block in out.split("\x01"):
        if not block.strip():
            continue
        head, _, body = block.partition("\n")
        sha, _, subject = head.partition("\x00")
        files = frozenset(ln for ln in body.splitlines() if ln.strip())
        index.setdefault(subject, []).append((sha, files))
    return index


def _commit_patch_id(sha: str) -> str | None:
    proc = subprocess.run(
        f"git show {shlex.quote(sha)} | git patch-id --stable", shell=True,
        cwd=str(primary_root()), stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL, text=True)
    parts = proc.stdout.split()
    return parts[0] if parts else None


def _audit_integrated(branch: str, base: str,
                      depth: int = AUDIT_SEARCH_DEPTH) -> dict:
    """Did every commit unique to `branch` reach `base`, and on what evidence?

    This is the three-step audit `.claude/skills/worktree-flow/SKILL.md` prescribes
    for a batch-integrated branch, executed by the tool instead of by a person.

    Why it is needed: `resolve`'s landed-floor asks "is this branch's net change in
    base", by tree-diff. After a batch integration the answer is legitimately NO —
    conflict resolution left base holding a NEWER version than the branch — and that
    is byte-for-byte indistinguishable from "this work never landed". Measured with
    `ops/worktree_loadtest.py --mode batch -n 10 --conflict shared`: **10 of 10**
    source branches refuse teardown. Every one of them needs the same audit, and all
    three of its steps are mechanical.

    Why not simply loosen the floor: a rule permissive enough to pass this case also
    passes work that never landed at all, and that refusal has already caught one
    commit dropped during an integration. So this is a SECOND door, and it reports
    which comparison opened it — a branch that got through on the weaker match is
    visible as such, rather than being indistinguishable from a strong one.

    Two comparisons, strongest first:

      patch-id      the same change under a different sha (a clean cherry-pick)
      subject+files the same message AND exactly the same set of paths — the case
                    where integration edited the content while merging. Subject
                    alone is NOT accepted: two commits can share a message and touch
                    unrelated files, which is the shape that would wave through a
                    branch nobody integrated.
    """
    rc, out = _git(["rev-list", "--reverse", f"{base}..{branch}"])
    if rc != 0:
        return {"ok": False, "error": f"cannot list {base}..{branch}", "commits": []}
    shas = [ln.strip() for ln in out.splitlines() if ln.strip()]
    if not shas:
        # Nothing unique to the branch: it is an ancestor of base. The floor would
        # not have refused, so getting here means the caller asked anyway.
        return {"ok": True, "commits": [], "base": base, "searched": 0}

    by_patch = _patch_id_index(base, depth)
    by_subject = _subject_file_index(base, depth)

    results = []
    for sha in shas:
        _, subject = _git(["log", "-1", "--format=%s", sha])
        subject = subject.strip()
        _, names = _git(["show", "--name-only", "--format=", sha])
        files = frozenset(ln.strip() for ln in names.splitlines() if ln.strip())
        match, matched = None, None
        pid = _commit_patch_id(sha)
        if pid and pid in by_patch:
            match, matched = "patch-id", by_patch[pid]
        else:
            for cand_sha, cand_files in by_subject.get(subject, []):
                if cand_files == files and files:
                    match, matched = "subject+files", cand_sha
                    break
        results.append({"sha": sha[:9], "subject": subject, "match": match,
                        "matched_sha": (matched or "")[:9] or None,
                        "files": sorted(files)[:8]})
    return {"ok": all(r["match"] for r in results), "commits": results,
            "base": base, "searched": min(depth, len(by_patch))}


def cmd_resolve(args: argparse.Namespace) -> int:
    """Landed-floor guard, then registry resolve merged → worktree remove + branch -D
    (local + remote) + drop the gate-record cache."""
    worktree = _norm(args.worktree)

    def _refuse(code: str, reason: str, **extra: Any) -> int:
        _emit({"schema": SCHEMA, "step": "resolve", "error": "refused",
               "reason_code": code, "reason": reason, "branch": extra.pop("branch", None),
               "worktree": worktree, **extra},
              args.json, f"✗ resolve refused [{code}]: {reason}")
        return RESOLVE_REFUSALS[code]

    branch, entry, code, reason = _resolve_target(worktree, args.branch, args.base,
                                                  args.state)
    if code:
        return _refuse(code, reason, branch=args.branch)

    # CORROBORATION: the target must be vouched for by at least one authority — git's
    # worktree list, or an active ledger record. In the incident neither named it:
    # the list did not map that path to `main`, and the ledger said "no active record
    # for branch=main" — which the tool PRINTED and then ignored. Requiring only ONE
    # of the two is deliberate: after an interrupted teardown the ledger is already
    # closed (it is struck before the git steps), so a ledger-AND rule would strand
    # every re-run, and the whole point of that re-run is to finish the job.
    #
    # Note this refusal deliberately does NOT tell the operator to run `adopt`: adopt
    # resolves its target through `--show-toplevel`, which for a .git-less directory
    # answers with the primary and makes adopt refuse. It is a dead end for exactly
    # the degraded worktrees that reach this line.
    corroborated_by_git = bool(entry and entry.get("branch") == branch)
    corroborated_by_ledger = bool(_active_ledger_records(args.state, branch)) or \
        branch in _ledger_branches_for_path(args.state, worktree)
    if not corroborated_by_git and not corroborated_by_ledger:
        return _refuse("uncorroborated-branch",
                       f"no authority vouches for branch {branch!r} at {worktree} — git "
                       "does not map that path to that branch and the ledger has never "
                       "recorded it there. Point --worktree at the real path, or drop "
                       "--branch and let git's worktree list name the target.",
                       branch=branch)

    # nit2 LANDED FLOOR: resolve is a force-discard (worktree remove --force + branch -D).
    # Called out of order (before cutover) it would vaporize unlanded work. Refuse a
    # branch whose net change is NOT already in base — using the registry's tree-diff
    # containment (never git cherry; same authority the sweep trusts). --force overrides.
    audit = None
    if not args.force:
        _fetch()  # base may have advanced; compare against the fresh tip
        if not wr.landed_in_base(args.base, branch):
            # SECOND EVIDENCE PATH, not a looser floor. After a batch integration
            # the tree-diff answer is legitimately "no" — conflict resolution left
            # base holding a NEWER version than the branch — and that is
            # indistinguishable from "never landed". Measured with
            # `ops/worktree_loadtest.py --mode batch -n 10 --conflict shared`:
            # 10 of 10 source branches land here. `--via-integration <ref>` runs
            # the audit the SKILL prescribes, mechanically, and reports what each
            # commit was matched on.
            if args.via_integration:
                audit = _audit_integrated(branch, args.via_integration)
                if not audit["ok"]:
                    missing = [c for c in audit["commits"] if not c["match"]]
                    reason = (
                        f"branch {branch!r} is not landed in {args.base} (tree-diff), "
                        f"and the integration audit against {args.via_integration!r} "
                        f"could not account for {len(missing)} of "
                        f"{len(audit['commits'])} commit(s): "
                        + "; ".join(f"{c['sha']} {c['subject']!r}" for c in missing[:5])
                        + ". Either they never landed, or the ref you named is not "
                        "the one that carried them.")
                    _emit({"schema": SCHEMA, "step": "resolve", "error": "refused",
                           "reason": reason, "branch": branch, "landed": False,
                           "audit": audit}, args.json,
                          f"✗ resolve refused: {reason}")
                    return EXIT_BLOCK
                weak = [c["sha"] for c in audit["commits"]
                        if c["match"] == "subject+files"]
                print(f"[worktree][audit] {branch}: "
                      f"{len(audit['commits'])} commit(s) accounted for in "
                      f"{args.via_integration}"
                      + (f"; {len(weak)} on the WEAKER subject+files match "
                         f"({', '.join(weak[:5])})" if weak else ""),
                      file=sys.stderr, flush=True)
            else:
                reason = (f"branch {branch!r} is not landed in {args.base} (tree-diff) "
                          "— resolve would force-discard unlanded work. If it was "
                          "batch-integrated (conflict resolution leaves base holding a "
                          "NEWER version, which reads identically to 'never landed'), "
                          f"prove it with `--via-integration {args.base}` and the tool "
                          "will audit every commit and say what it matched on. "
                          "Otherwise run `cutover` first, or pass --force.")
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

    def _plan(label: str, gargs: list[str], cwd: Path, *, critical: bool = False) -> None:
        steps.append({"label": label, "cmd": "git " + " ".join(gargs),
                      "progress_label": "resolve-" + label.replace(" ", "-"),
                      "gargs": gargs, "cwd": str(cwd), "critical": critical})

    # Teardown shape depends on whether git's administrative link is intact.
    #
    # A `prunable` entry is the fossil of an interrupted `worktree remove --force`:
    # that command unlinks the worktree's `.git` FIRST and only then rm's the tree,
    # so a caller timeout during a slow removal (19 GB of DerivedData, in the
    # incident) leaves the directory standing with a broken link. `worktree remove`
    # answers rc=128 on such an entry — but MEASURED: once the directory itself is
    # gone it succeeds again, rc=0, and removes only that one entry.
    #
    # That measurement is why there is no `git worktree prune` here. Prune has no
    # path filter: in a repo with two independently broken worktrees, one prune
    # reaps BOTH. Since concurrent sessions are this repo's normal mode, a routine
    # resolve would silently destroy a sibling session's only remaining path->branch
    # record — the very information whose loss caused this incident. `worktree
    # remove` addresses exactly one path, so the healthy and the degraded paths end
    # up on the same targeted command.
    #
    # ORDER IS THE RESILIENCE: the slow, resumable step (rm -rf) runs while the
    # admin entry still holds the path->branch mapping, and the cheap administrative
    # strike runs last. Reversed, an interruption in between would leave a directory
    # nothing can attribute to a branch.
    def _plan_rm() -> None:
        steps.append({"label": "remove leftover worktree directory",
                      "cmd": f"rm -rf {worktree}",
                      "progress_label": "resolve-remove-leftover-directory",
                      "rmtree": worktree, "critical": True})

    if entry is not None:
        if entry.get("prunable") and Path(worktree).is_dir():
            _plan_rm()
        _plan("remove worktree", ["worktree", "remove", "--force", worktree], root,
              critical=True)
    elif Path(worktree).is_dir():
        # git no longer lists the path — an errored `worktree remove` drops the admin
        # entry anyway, and any prune in the repo removes it — but the directory is
        # still on disk. `worktree remove` has nothing left to act on, so without this
        # branch resolve reported `failures: 0` and exited 0 while leaving the whole
        # tree behind: a silent false success, and 19 GB of it in the incident's shape.
        _plan_rm()

    if any(s.get("rmtree") for s in steps) and not _rm_target_vetted(worktree, args.state):
        return _refuse("rm-target-unvetted",
                       f"{worktree} is neither under this repo's worktree root nor a "
                       "path the ledger recorded — refusing to delete it recursively",
                       branch=branch)

    _plan("delete local branch", ["branch", "-D", branch], root)
    if _remote_branch_exists(branch):
        _plan("delete remote branch", ["push", "origin", "--delete", branch], root)

    # Belt-and-suspenders, same net the registry's sweep clearance runs: no planned
    # step may delete a protected branch or remove the primary worktree. _resolve_target
    # already makes that unrepresentable; this catches a future bug upstream of it.
    primary_path, protected = _protected_branches(args.base, worktree)
    unsafe = [s["cmd"] for s in steps if s.get("gargs")
              and wr._step_touches_protected(s["gargs"], primary_path, protected)]
    # the recursive delete carries no argv, so the registry predicate cannot see it
    unsafe += [s["cmd"] for s in steps if s.get("rmtree")
               and primary_path and _norm(s["rmtree"]) == primary_path]
    if unsafe:
        return _refuse("unsafe-step",
                       "planned a repository-destroying step — refusing: "
                       + "; ".join(unsafe), branch=branch, unsafe=unsafe)

    if not args.commit:
        payload = {"schema": SCHEMA, "step": "resolve", "mode": "dry-run", "branch": branch,
                   # what let this teardown through, when it was not the
                   # plain tree-diff floor. Absent means the floor passed.
                   **({"audit": audit} if audit else {}),
                   "plan": [{"label": s["label"], "cmd": s["cmd"]} for s in steps]}
        human = ("# resolve (dry-run) — ledger -> merged, then:\n"
                 + "\n".join(f"  {s['cmd']}   # {s['label']}" for s in steps)
                 + "\n  (--commit to execute)")
        _emit(payload, args.json, human)
        return EXIT_OK

    # ledger closure first (idempotent even if the git teardown partially failed before).
    # BEFORE the registry is struck. `resolve` closes the record ahead of the git
    # steps, and a closed record is exactly what `held_tickets`-style readers filter
    # out — so reading the claim afterwards would always answer "nothing was
    # claimed", i.e. a check that can only ever pass.
    claimed_at_teardown = _claimed_tickets(args.state, branch)
    _registry(["resolve", *_state_arg(args.state), "--branch", branch, "--status", "merged"])
    # FAIL-FAST on the steps later ones depend on. Half of the incident lived here:
    # `worktree remove --force` returned 128 and the loop went on to run `branch -D`
    # and `push origin --delete` anyway. Correct targeting makes those two harmless;
    # it does not make "keep going after a destructive step failed" correct. It also
    # matters for the new rm: if the directory removal fails, continuing would strike
    # the admin entry and leave a directory nothing can attribute to a branch — the
    # unrecoverable version of the state this whole change exists to make recoverable.
    results = []
    failures = 0
    aborted_after = None
    for s in steps:
        if s.get("rmtree"):
            rc, out = _rmtree_streamed(s["rmtree"])
        else:
            rc, out = _git_mutation(
                s["gargs"], cwd=Path(s["cwd"]), label=s["progress_label"],
            )
        ok = rc == 0
        results.append({"label": s["label"], "cmd": s["cmd"], "ok": ok,
                        "detail": out[:200] if not ok else ""})
        if not ok:
            failures += 1
            if s.get("critical"):
                aborted_after = s["label"]
                skipped = [t["label"] for t in steps[steps.index(s) + 1:]]
                results.append({"label": "aborted", "cmd": "", "ok": False,
                                "detail": f"skipped after a failed critical step: "
                                          f"{', '.join(skipped)}" if skipped else
                                          "no remaining steps"})
                break

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
    # ...and the failed-gate output logs sitting beside it (IMP-20260808-c47253).
    # Same residue rule as the verdict: a log describing a gate run on a worktree
    # that no longer exists can only mislead. The filename carries this worktree's
    # key, so the glob cannot reach a sibling session's logs.
    gate_logs_removed = 0
    for stale_log in sorted(gate_cache.parent.glob(f"{gate_cache.stem}.*.log")):
        try:
            stale_log.unlink()
            gate_logs_removed += 1
        except OSError:
            pass

    # Said out loud, and deliberately NOT blocking. The anchor queue is gitignored
    # and per-machine, so nothing downstream of this teardown can notice a closure
    # that landed but was never written into the store: not the gate, not docs lint,
    # and not any reader of the ledger — `backlog.py list`, `show` and the generated
    # view all read the STORE, where a staged-and-never-anchored entry simply looks
    # open, with no trace of the work that closed it. (No claim here about the
    # planned bounty board: it does not exist yet. The one board this repo ever had,
    # `converge_board.py`, is retired — see worktree_registry.py's header.)
    # Refusing would be worse: the closure HAS landed, the entry is merely not
    # closed yet, and a teardown that refuses strands the worktree instead of
    # fixing anything.
    # Stamped-but-not-yet-anchored is the NORMAL state here: the documented order is
    # stage -> cutover -> resolve per worktree, with one `anchor` at wave end. So this
    # is a handoff note, not a warning — the first draft printed `⚠ never anchored` on
    # every successful hunter, and `make_commit_state`'s own docstring is the argument
    # against that: "a gate that reds on the normal path is one that gets switched
    # off." What makes it worth printing at all is that this is the last moment the
    # worktree exists to say it: after teardown the row's only remaining trace is an
    # id in a gitignored file.
    pending_anchor = sorted({r.get("id") for r in _read_anchor_queue(root)
                             if r.get("branch") == branch and r.get("landed_sha")})

    # CLAIMED but never staged — a different question from `pending_anchor`, and the
    # one that actually loses tickets. `pending_anchor` asks "did someone who
    # remembered to close it finish the job"; this asks "did anyone remember at all".
    # Both report an empty list on the happy path, which is exactly why the second
    # one has to exist separately: an unclosed claim and a clean teardown were
    # indistinguishable.
    #
    # Measured, on this tool's own flagship task: `open --backlog IMP-20260807-b9526c`
    # claimed it, the work landed, `resolve` printed `pending_anchor: []`, the
    # worktree vanished, and the entry is still `open`. Five other tickets in the
    # same session closed correctly — every one of them FILED mid-work. The claim is
    # taken at the start and the closure happens at the end, and nothing carried the
    # obligation across those hours; teardown is the last moment anyone knows the
    # claim existed.
    #
    # WARN, not block, and the reason is that all three of these are legitimate:
    # investigating and deciding it needs no fix, splitting the work across branches,
    # and abandoning a claim on purpose. A block would make the honest cases fight
    # the tool, and `make_commit_state`'s docstring already paid for that lesson.
    staged_here = {r.get("id") for r in _read_anchor_queue(root)
                   if r.get("branch") == branch}
    claimed_open = sorted(t for t in claimed_at_teardown
                          if t not in staged_here and not _entry_is_closed(root, t))

    payload = {"schema": SCHEMA, "step": "resolve", "mode": "committed", "branch": branch,
                   # what let this teardown through, when it was not the
                   # plain tree-diff floor. Absent means the floor passed.
                   **({"audit": audit} if audit else {}),
               "resolved": "merged", "executed": results, "failures": failures,
               "aborted_after": aborted_after,
               "gate_cache_removed": gate_cache_removed,
               "gate_logs_removed": gate_logs_removed,
               "pending_anchor": pending_anchor,
               "claimed_without_closure": claimed_open}
    human = ["# resolve (committed): ledger -> merged"]
    for r in results:
        human.append(f"  {'✓' if r['ok'] else '✗'} {r['cmd']}   # {r['label']}")
    if gate_cache_removed:
        human.append("  ✓ dropped gate-record cache")
    if gate_logs_removed:
        human.append(f"  ✓ dropped {gate_logs_removed} failed-gate output log(s)")
    if pending_anchor:
        human.append(f"  · {len(pending_anchor)} closure(s) landed and awaiting the "
                     f"wave's anchor: {', '.join(pending_anchor)}")
        human.append("    run `./ops/backlog.py anchor --commit` once the wave is done")
    if claimed_open:
        # Louder than pending_anchor on purpose: that one is a reminder about work
        # already recorded, this one is the last chance to notice work that was
        # never recorded at all.
        human.append(f"  ⚠ {len(claimed_open)} claimed ticket(s) with NO staged "
                     f"closure: {', '.join(claimed_open)}")
        human.append("    if the work landed, it is still open — `./ops/backlog.py "
                     "stage <id> ...` before the branch is gone, or say why it stays "
                     "open with `update <id> --resolution ...`")
        human.append("    run: ./ops/backlog.py anchor --commit")
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
    op.add_argument(
        "--backlog", nargs="*", default=None, metavar="ID",
        help="backlog ticket ids to CLAIM for this worktree. The claim is taken "
             "before anything is created, so losing the race costs you nothing: "
             "no branch, no directory, and a non-zero exit. Refused when another "
             "ACTIVE ledger record already holds one of them; the claim is released "
             "by `resolve`/`sweep`, with no separate release step.",
    )
    op.add_argument(
        "--allow-ungroomed", action="store_true",
        help="take a ticket that has no plan/acceptance/fix-site — i.e. claim it as "
             "an INVESTIGATION rather than a fix. Named in a stderr warning so the "
             "exception is countable. Does NOT waive the other two refusals (an id "
             "that is not in the store, or one that is already fixed/wont-fix).",
    )
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
    # adopt takes claims too. A gate that an adjacent entry point walks around is
    # not a gate — adopt is the bootstrap path INTO the same ledger, so leaving it
    # claim-blind would make "at most one worktree per ticket" true only of the
    # worktrees that happened to be born through `open`.
    ad.add_argument(
        "--backlog", nargs="*", default=None, metavar="ID",
        help="backlog ticket ids to CLAIM (same rules as `open --backlog`)",
    )
    ad.add_argument(
        "--allow-ungroomed", action="store_true",
        help="take a ticket that has no plan/acceptance/fix-site — i.e. claim it as "
             "an INVESTIGATION rather than a fix. Named in a stderr warning so the "
             "exception is countable. Does NOT waive the other two refusals (an id "
             "that is not in the store, or one that is already fixed/wont-fix).",
    )
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
                        "births/landings/publishes (open/adopt/catchup/integrate/"
                        "cutover/sync-main/sync/deploy) until `off`; draining steps "
                        "(resolve/sweep/preflight/gate) stay allowed")
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
    ga.add_argument("--receipt-line", action="store_true",
                    help="emit one paste-ready receipt line instead of the report")
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

    cu = sub.add_parser("catchup", help="rebase the worktree onto the local trunk "
                        "(a clean rebase — any conflict aborts and comes back to "
                        "you); then re-run `gate` (dry-run default)")
    add_common(cu)
    add_base(cu)
    cu.add_argument("--worktree", required=True, help="worktree path to rebase")
    cu.add_argument("--commit", action="store_true",
                    help="perform the rebase (default: report the drift only)")
    cu.set_defaults(func=cmd_catchup)

    ln = sub.add_parser("land", help="take a fair FIFO turn, then run catchup -> gate "
                        "-> cutover under it; the verb for 'get me onto the trunk' "
                        "when several worktrees are converging (dry-run default)")
    add_common(ln)
    add_base(ln)
    ln.add_argument("--worktree", required=True, help="worktree path to land")
    ln.add_argument("--commit", action="store_true",
                    help="take the turn and land (default: report the queue only)")
    ln.add_argument("--queue-timeout", type=float, default=3600.0, metavar="S",
                    help="give up when the queue has not MOVED for S seconds "
                         "(default 3600). Deliberately not a total-wait budget: "
                         "holding the turn across the gate means lane N waits "
                         "(N-1) x gate, so a total-wait budget would fail healthy "
                         "lanes in exactly the long-gate batches this verb exists "
                         "for")
    ln.set_defaults(func=cmd_land)

    ig = sub.add_parser("integrate", help="batch verb: fork an integration worktree off "
                        "the local trunk, cherry-pick N branches into it in order, and "
                        "run ONE gate on the result — the only way to ask whether N "
                        "pieces of work are green TOGETHER. Gates, never lands "
                        "(dry-run default)")
    add_common(ig)
    add_base(ig)
    ig.add_argument("--slug", required=True,
                    help="kebab-case slug: names the integration worktree and branch, "
                         "AND identifies the integration for --continue / --abort")
    ig.add_argument("--branches", nargs="+", metavar="BRANCH", default=None,
                    help="source branches, cherry-picked IN THIS ORDER. Refused (by "
                         "name) if one does not resolve, carries a merge commit, or "
                         "has nothing to contribute")
    ig.add_argument("--continue", dest="cont", action="store_true",
                    help="resume a stopped integration: conclude the suspended pick "
                         "(stage the resolved files first), apply what is left, gate")
    ig.add_argument("--abort", action="store_true",
                    help="abort the in-flight cherry-pick and forget the integration "
                         "state. The WORKTREE survives — teardown is `resolve`, the "
                         "only step that consults the landed-floor")
    ig.add_argument("--commit", action="store_true",
                    help="execute (default: dry-run — which for a fresh integration "
                         "lists every commit that would be picked)")
    ig.set_defaults(func=cmd_integrate)

    rs = sub.add_parser("resolve", help="landed-floor + ledger -> merged + worktree "
                        "remove + branch -D (local/remote) + drop gate cache — no "
                        "residue (dry-run default)")
    add_common(rs)
    add_base(rs)
    rs.add_argument("--worktree", required=True, help="worktree path to resolve")
    rs.add_argument("--branch", default=None,
                    help="branch to resolve (default: the worktree's checked-out branch)")
    rs.add_argument(
        "--via-integration", dest="via_integration", metavar="REF", default=None,
        help="prove a batch-integrated branch landed: audit every commit unique to "
             "it against REF (usually `main`), accepting a patch-id match or an "
             "identical subject AND file set, and refusing by name if any commit is "
             "unaccounted for. This is a second evidence path, not --force: --force "
             "means 'I looked', this means 'the tool looked and here is what it "
             "matched on'.")
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
