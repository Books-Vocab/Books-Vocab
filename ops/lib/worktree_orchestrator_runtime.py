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
  IO layer      git + subprocess to the real gate tools. Landing-plane steps (rebase,
                push, worktree remove, branch -D) are gated behind --commit; open / adopt / freeze take effect at once and have no --commit.
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
Exit codes use the shared contract: 0=pass, 1=tool error, 2=block, 3=warn,
64=usage, and 75=infrastructure unavailable/claimed.

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
             EXISTING `gate` ONCE on the merged result (or `--no-gate` to hand back
             after picking so a later `--continue --commit` runs only that gate). It
             answers the one question
             per-branch gates structurally cannot: are these N pieces of work green
             TOGETHER. Measured 2026-08-06 on an eleven-branch batch — review of the
             integrated tree found five blocking defects, each green under its own
             branch's gate. Adds no pass/fail of its own: the verdict is `gate`'s and
             landing stays `cutover`'s (which already refuses a block verdict, so
             that rule keeps living in exactly one place). cherry-pick rather than
             merge, so a branch cannot smuggle in commits nobody named. dry-run
             default.
  close-wave  the Delivery Team Integrator verb: resume one named batch through
              integrate/append -> one fresh gate -> cutover -> source/integration
              resolve -> backlog anchor -> validate; with --sync it mirrors the
              exact landed primary tip to origin/main. Other teams may stay active;
              the same slug resumes after a named stop. It never deploys.
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
             produce. The repair commit is identified by its fixed subject, parent
             and exact changed paths. Local
             main's tip is therefore `trunk_tip`, which may differ from the gated
             `sha`. OFFLINE — no push, no deploy. A `warn` is advisory: it LANDS ("landed with
             warnings") — the driving agent owns a warn's disposition, so the tool must
             not hard-refuse it; `block`, a stale/absent verdict, and any
             `inconclusive` gate refuse.
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
             open/adopt/catchup/integrate/close-wave/cutover/sync-main/sync/deploy refuse (every
             step that gives birth, rewrites history or advances a ref); draining
             steps (resolve, sweep, preflight, gate) stay allowed so the flow can be
             quiesced for repo surgery (history rewrite, gc, shared hooks/config).

Exit codes: 0 ok | 64 usage error | 1 blocked (gate block / cutover refused /
            open refused because a backlog ticket is already claimed / partial).
"""

from __future__ import annotations

import argparse
import ast
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
import uuid
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

# Reuse P2 in-process — never re-implement register / resolve / sweep / state paths.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import worktree_registry as wr  # noqa: E402
import backlog as backlog_tool  # noqa: E402
import worktree_campaign as campaign  # noqa: E402
import worktree_gate as gate_logic  # noqa: E402
from lib.provenance import logical_tool_path, sha256_file  # noqa: E402
from lib.streaming_command import run_streamed_command  # noqa: E402
from lib import dispatch_preflight  # noqa: E402
from lib.exit_codes import EXIT_BLOCK, EXIT_OK, EXIT_TOOL_ERROR, EXIT_USAGE, EXIT_WARN  # noqa: E402
from lib import worktree_integration_status as integrate_status  # noqa: E402
from lib import worktree_orchestrator_planning as planning  # noqa: E402
from lib import worktree_orchestrator_core as orchestrator_core  # noqa: E402
from lib import worktree_orchestrator_delivery as orchestrator_delivery  # noqa: E402
from lib import worktree_orchestrator_lifecycle as orchestrator_lifecycle  # noqa: E402
from lib import worktree_orchestrator_gate as orchestrator_gate  # noqa: E402
from lib import worktree_orchestrator_commands as orchestrator_commands  # noqa: E402
from lib import worktree_orchestrator_claims as orchestrator_claims  # noqa: E402

# Keep the legacy runtime namespace stable while the pure planner lives in its own
# module.  The façade propagates monkeypatches across both namespaces.
for _planning_name, _planning_value in vars(planning).items():
    if not _planning_name.startswith("__") and _planning_name != "_COMPONENTS":
        globals()[_planning_name] = _planning_value
for _core_name, _core_value in vars(orchestrator_core).items():
    if not _core_name.startswith("__") and _core_name != "_COMPONENTS":
        globals()[_core_name] = _core_value
for _delivery_name, _delivery_value in vars(orchestrator_delivery).items():
    if not _delivery_name.startswith("__") and _delivery_name != "_COMPONENTS":
        globals()[_delivery_name] = _delivery_value
for _lifecycle_name, _lifecycle_value in vars(orchestrator_lifecycle).items():
    if not _lifecycle_name.startswith("__") and _lifecycle_name != "_COMPONENTS":
        globals()[_lifecycle_name] = _lifecycle_value
for _gate_name, _gate_value in vars(orchestrator_gate).items():
    if not _gate_name.startswith("__") and _gate_name != "_COMPONENTS":
        globals()[_gate_name] = _gate_value
for _commands_name, _commands_value in vars(orchestrator_commands).items():
    if not _commands_name.startswith("__") and _commands_name != "_COMPONENTS":
        globals()[_commands_name] = _commands_value
for _claims_name, _claims_value in vars(orchestrator_claims).items():
    if not _claims_name.startswith("__") and _claims_name != "_COMPONENTS":
        globals()[_claims_name] = _claims_value

SCHEMA = "kg.worktree.orchestrate.v1"
GATE_SCHEMA = "kg.worktree.gate.v1"
GATE_INPUT_SCHEMA = "kg.worktree.gate-input.v1"
GATE_PROGRESS_SCHEMA = "kg.worktree.gate-progress.v1"
FREEZE_SCHEMA = "kg.worktree.freeze.v1"
DELIVERY_SCHEMA = "kg.worktree.delivery.v1"
_INDEPENDENT_NO_TICKET_INTENT = "independent-no-ticket:"
# Local-main-centric topology: local `main` is the trunk. Worktrees fork from it and
# cutover fast-forwards it OFFLINE — origin is only a deploy target (`deploy` pushes
# local main to origin, which the felix reconciler turns into a production rollout).
BASE_DEFAULT = "main"
SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
WORKTREE_SCRATCH_REL = Path(".cache") / "agent-scratch"
# git's canonical empty-tree object — diff base for a first-ever publish (all files new)
EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"

# The design-system impact surface: the EXACT pattern the pre-commit hook uses
# (.githooks/pre-commit DS_PATTERN). Reused verbatim so orchestrator routing and the
# hook can never disagree about what a "design-system change" is.


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

    cr = sub.add_parser(
        "campaign-reserve",
        help="validate or atomically reserve a complete campaign manifest (dry-run default)",
    )
    add_common(cr)
    cr.add_argument("--request-file", required=True,
                     help="JSON file with schema kg.worktree.campaign.v1")
    cr.add_argument("--base-ref", default=BASE_DEFAULT,
                     help=f"local ref whose exact SHA must match request base (default: {BASE_DEFAULT})")
    cr.add_argument("--commit", action="store_true",
                     help="persist the manifest and registry reservation")
    cr.set_defaults(func=cmd_campaign_reserve)

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
        "--type", choices=("debug", "feat", "research"), default=None,
        help="explicit branch type; overrides the type inferred from --intent",
    )
    claim_mode = op.add_mutually_exclusive_group()
    claim_mode.add_argument(
        "--backlog", nargs="*", default=None, metavar="ID",
        help="backlog ticket ids to CLAIM for this worktree. The claim is taken "
             "before anything is created, so losing the race costs you nothing: "
             "no branch, no directory, and a non-zero exit. Refused when another "
             "ACTIVE ledger record already holds one of them; the claim is released "
             "by `resolve`/`sweep`, with no separate release step.",
    )
    claim_mode.add_argument(
        "--next-backlog", action="store_true",
        help="atomically take dispatch's current worst-first head and claim it for "
             "this worktree. Selection and claim share the registry lock, so two "
             "coordinators starting together receive different tickets instead of "
             "both selecting one id and making a loser retry. Only groomed, "
             "unresolved, unclaimed and unblocked entries are eligible.",
    )
    op.add_argument("--campaign", default=None,
                    help="campaign id whose reserved ticket set supplies --next-backlog")
    op.add_argument("--partition", default=None,
                    help="campaign partition to consume with --campaign --next-backlog")
    op.add_argument(
        "--allow-ungroomed", action="store_true",
        help="take a ticket that has no plan/acceptance/fix-site — i.e. claim it as "
             "an INVESTIGATION rather than a fix. Named in a stderr warning so the "
             "exception is countable. Does NOT waive the other two refusals (an id "
             "that is not in the store, or one that is already fixed/wont-fix).",
    )
    delegated_mode = op.add_mutually_exclusive_group()
    delegated_mode.add_argument(
        "--delegated", dest="delegated", action="store_true", default=None,
        help="mark this worktree as delegated; landing belongs to the integrator",
    )
    delegated_mode.add_argument(
        "--not-delegated", dest="delegated", action="store_false",
        help="explicitly clear the delegated mark",
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
    delegated_mode = ad.add_mutually_exclusive_group()
    delegated_mode.add_argument(
        "--delegated", dest="delegated", action="store_true", default=None,
        help="mark this worktree as delegated; landing belongs to the integrator",
    )
    delegated_mode.add_argument(
        "--not-delegated", dest="delegated", action="store_false",
        help="explicitly clear the delegated mark",
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
                        "births/landings/publishes (open/adopt/catchup/integrate/close-wave/"
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
    ga.add_argument("--gate-tier", choices=GATE_TIERS, default=DEFAULT_GATE_TIER,
                    help=("verification depth: S0 static, S1 focused, S2 affected "
                          "module, S3 cross-module, S4 release; "
                          f"default {DEFAULT_GATE_TIER}"))
    ga.add_argument("--defer-gate", action="append", default=[], metavar="GATE=TICKET",
                    help=("explicitly carry a failing S2/S3 gate with an existing "
                          "low/med backlog ticket; repeatable, e.g. "
                          "ios-test-unit=IMP-20260817-abcdef"))
    ga.add_argument("--receipt-line", action="store_true",
                    help="print ONLY the paste-ready receipt line (the normal report already ends with it)")
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

    cw = sub.add_parser(
        "close-wave",
        help="Delivery Team Integrator closure: integrate/append -> one fresh Gate "
             "-> cutover -> resolve -> anchor -> validate -> optional origin/main "
             "sync (dry-run default)",
    )
    add_common(cw)
    add_base(cw)
    cw.add_argument("--slug", required=True,
                    help="kebab-case integration slug; rerun the same slug to resume")
    cw.add_argument("--branches", nargs="+", metavar="BRANCH", default=None,
                    help="source branches for a fresh wave; omit when resuming its state")
    cw.add_argument("--commit", action="store_true",
                    help="execute the complete local closure; requires the caller's "
                         "delivery-loop develop authorization")
    cw.add_argument("--sync", action="store_true",
                    help="after local cutover and closure, push the resulting primary "
                         "main to origin/main; explicit backup leg, never deploys")
    cw.add_argument("--independent", action="store_true",
                    help="explicitly declare an independent no-ticket wave; the "
                         "manifest, registry intent marker, Gate HEAD and clean "
                         "primary must all prove this opt-in before an empty "
                         "expected-ticket set can proceed")
    cw.add_argument("--gate-tier", choices=GATE_TIERS, default=DEFAULT_GATE_TIER,
                    help=("daily closure verification depth; use S4 only for an "
                          f"explicit release checkpoint (default {DEFAULT_GATE_TIER})"))
    cw.add_argument("--defer-gate", action="append", default=[], metavar="GATE=TICKET",
                    help="carry named non-critical Gate failures with existing tickets")
    cw.set_defaults(func=cmd_close_wave)

    ig = sub.add_parser("integrate", help="batch verb: fork an integration worktree off "
                        "the local trunk, cherry-pick N branches into it in order, and "
                        "run ONE gate on the result — the only way to ask whether N "
                        "pieces of work are green TOGETHER. Use --append for a late "
                        "child before the one Gate; integrates, never lands "
                        "(dry-run default)")
    add_common(ig)
    add_base(ig)
    ig.add_argument("--slug", required=True,
                    help="kebab-case slug: names the integration worktree and branch, "
                         "AND identifies the integration for --continue / --abort")
    ig.add_argument("--status", action="store_true",
                    help="read-only projection of one in-flight integration; cannot "
                         "be combined with mutation or source-selection flags")
    source_mode = ig.add_mutually_exclusive_group()
    source_mode.add_argument("--branches", nargs="+", metavar="BRANCH", default=None,
                    help="source branches, cherry-picked IN THIS ORDER. Refused (by "
                         "name) if one does not resolve, carries a merge commit, or "
                         "has nothing to contribute")
    source_mode.add_argument("--parent", action="store_true",
                    help="consume the complete campaign child snapshot; branches are "
                         "derived atomically and cannot be supplied manually")
    ig.add_argument("--campaign", default=None, metavar="ID",
                    help="campaign id for --parent; the parent reservation is claimed "
                         "before the integration worktree is opened")
    ig.add_argument("--continue", dest="cont", action="store_true",
                    help="resume a stopped integration: conclude the suspended pick "
                         "(stage the resolved files first), apply what is left, then "
                         "gate (or use --no-gate to stop after picking)")
    ig.add_argument("--append", action="store_true",
                    help="append newly handed-back child branches to an existing "
                         "pick-only round; always stops before the round's one Gate")
    ig.add_argument("--no-gate", dest="no_gate", action="store_true",
                    help="pick only: drain the queue and STOP before the gate; the "
                         "integration state survives, so the next `--continue --commit` "
                         "runs ONLY the gate on the already-integrated tree")
    ig.add_argument("--gate-tier", choices=GATE_TIERS, default=DEFAULT_GATE_TIER,
                    help=("verification depth for the one integration Gate; persisted "
                          f"across --continue (default {DEFAULT_GATE_TIER})"))
    ig.add_argument("--defer-gate", action="append", default=[], metavar="GATE=TICKET",
                    help="carry named non-critical Gate failures with existing tickets")
    ig.add_argument("--independent", action="store_true",
                    help="persist the explicit independent no-ticket provenance "
                         "marker; --continue must repeat this opt-in")
    ig.add_argument("--allow-unhanded", action="store_true",
                    help="allow a source branch with no active hand-back stamp/seal "
                         "(legacy or imported work only); NEVER bypasses a branch-tip "
                         "mismatch or invalid seal")
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
    try:
        args = parser.parse_args(tokens)
    except SystemExit as exc:
        # argparse prints the useful usage diagnostic, but its conventional 2
        # collides with workflow results. Preserve --help's successful 0 while
        # normalizing every malformed root/subparser invocation to the shared
        # usage contract.
        return EXIT_OK if exc.code == 0 else EXIT_USAGE
    # argparse collapses an omitted --base and an explicitly supplied default;
    # status must reject the latter because its contract is slug/state/json only.
    setattr(args, "_base_explicit", any(
        token == "--base" or token.startswith("--base=") for token in tokens
    ))
    if not getattr(args, "func", None):
        parser.print_help()
        return EXIT_USAGE
    return args.func(args)


orchestrator_core.bind_runtime(globals())
orchestrator_lifecycle.bind_runtime(globals())
orchestrator_delivery.bind_runtime(globals())
orchestrator_gate.bind_runtime(globals())
orchestrator_commands.bind_runtime(globals())
orchestrator_claims.bind_runtime(globals())


if __name__ == "__main__":
    sys.exit(main())
