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

# Keep the legacy runtime namespace stable while the pure planner lives in its own
# module.  The façade propagates monkeypatches across both namespaces.
for _planning_name, _planning_value in vars(planning).items():
    if not _planning_name.startswith("__"):
        globals()[_planning_name] = _planning_value
for _core_name, _core_value in vars(orchestrator_core).items():
    if not _core_name.startswith("__"):
        globals()[_core_name] = _core_value

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
    state_path = Path(args.state).resolve() if getattr(args, "state", None) else None
    blockers = _unclaimable(root / BACKLOG_STORE_DIR, wanted, state_path=state_path)
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


def _active_worktree_files(
    repo: Path, *, exclude_tickets: Iterable[str] = (), state_path: Path | None = None,
) -> set[str]:
    """Read active worktree diffs for claim-time overlap detection."""
    if repo.resolve() != backlog_tool.ROOT.resolve():
        return set()
    try:
        state = wr.load_state(state_path or wr.default_state_path())
    except (OSError, ValueError, KeyError) as exc:
        raise RuntimeError(f"active registry unreadable: {exc}") from exc
    changed: set[str] = set()
    excluded = set(str(ticket) for ticket in exclude_tickets)
    for record in state.get("records") or []:
        if not isinstance(record, dict) or record.get("status") != wr.STATUS_ACTIVE:
            continue
        if excluded.intersection(str(ticket) for ticket in (record.get("backlog") or [])):
            continue
        worktree = Path(str(record.get("path") or ""))
        if not worktree.is_dir():
            raise RuntimeError(f"active worktree missing: {worktree}")
        for args in (
            ["diff", "--name-only"],
            ["diff", "--name-only", "--cached"],
            ["ls-files", "--others", "--exclude-standard"],
        ):
            rc, output = _git(args, cwd=worktree)
            if rc != 0:
                raise RuntimeError(f"active worktree probe failed: {worktree} ({args!r})")
            changed.update(line.strip() for line in output.splitlines() if line.strip())
        branch = str(record.get("branch") or "")
        base = str(record.get("base") or "main")
        if branch:
            rc, output = _git(["diff", "--name-only", f"{base}...{branch}"], cwd=repo)
            if rc != 0:
                raise RuntimeError(f"active branch probe failed: {branch}")
            changed.update(line.strip() for line in output.splitlines() if line.strip())
    return changed


def _unclaimable(
    store_dir: Path, ids: list[str], *, state_path: Path | None = None,
) -> list[dict]:
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
    entries = list(backlog_tool._iter_entries(Path(store_dir)))
    unresolved = {
        str(entry.get("id")) for entry in entries
        if entry.get("status") not in RESOLVED_STATUSES
    }
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
                          f"already groomed, unresolved, unclaimed and unblocked — "
                          f"i.e. the ones you can take right now without grooming "
                          f"anything"})
        else:
            blockers = [ticket for ticket in backlog_tool._blocking_ids(payload)
                        if ticket in unresolved]
            if blockers:
                problems.append({
                    "id": entry_id, "kind": "blocked-by-unresolved",
                    "blockers": blockers,
                    "repair": "finish or explicitly re-plan the unresolved "
                              f"blocked_by ticket(s) first: {', '.join(blockers)}. "
                    "`ops/backlog.py dispatch` already excludes this "
                    "entry; explicit --backlog cannot bypass that edge.",
                })
            # `store_dir` is <repo>/docs/runbook/backlog on real claims and the
            # same relative shape in scratch claim tests; derive the checkout
            # instead of reaching for the caller's cwd.
            repo = backlog_tool.owning_repo_for_store(store_dir)
            contract_problems = backlog_tool.contract_preflight(payload, repo=repo)
            if contract_problems:
                problems.append({
                    "id": entry_id, "kind": "contract-blocked",
                    "contract_problems": contract_problems,
                    "repair": "record a contract check with `contract_status=ready`, "
                    "`contract_baseline=red`, existing fix_site and acceptance "
                    "dependencies; use `status=contract-blocked` with typed "
                    "evidence when the contract cannot be made executable.",
                })
            try:
                active_files = _active_worktree_files(
                    repo, exclude_tickets=ids, state_path=state_path,
                )
            except RuntimeError as exc:
                problems.append({
                    "id": entry_id,
                    "kind": "preflight-read-failed",
                    "repair": f"repair the active registry/worktree probe, then retry: {exc}",
                })
                active_files = set()
            compiled = dispatch_preflight.compile_static(
                payload,
                repo=repo,
                contract_problems=contract_problems,
                unresolved_blockers=blockers,
                active_files=active_files,
            )
            if compiled.classification != "executable":
                for issue in compiled.problems:
                    issue_kind = issue.get("kind")
                    if issue_kind in {
                            "baseline-green", "environment-blocked", "active-overlap",
                    } and not any(
                            problem.get("id") == entry_id
                            and problem.get("kind") == issue_kind
                            for problem in problems
                    ):
                        problems.append({
                            "id": entry_id,
                            "kind": issue_kind,
                            "preflight": compiled.to_dict(),
                            "repair": "; ".join(compiled.repair_hints),
                        })
                existing = next(
                    (problem for problem in problems
                     if problem.get("id") == entry_id
                     and problem.get("kind") in {
                         "contract-blocked", "dependency-blocked", "blocked-by-unresolved",
                     }),
                    None,
                )
                has_classification = any(
                    problem.get("id") == entry_id
                    and problem.get("kind") == compiled.classification
                    for problem in problems
                )
                if existing is not None:
                    existing["preflight"] = compiled.to_dict()
                    existing["repair"] += " " + "; ".join(compiled.repair_hints)
                elif not has_classification:
                    problems.append({
                        "id": entry_id,
                        "kind": compiled.classification,
                        "preflight": compiled.to_dict(),
                        "repair": "; ".join(compiled.repair_hints),
                    })
    return problems


def _held_from_registry_state(state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Project active registry claims into the shape backlog.list_entries accepts."""
    held: dict[str, dict[str, Any]] = {}
    for record in state.get("records") or []:
        if not isinstance(record, dict) or record.get("status") != wr.STATUS_ACTIVE:
            continue
        for ticket in record.get("backlog") or []:
            held[str(ticket)] = {
                "branch": record.get("branch"),
                "path": record.get("path"),
                "claimed_at": record.get("claimed_at"),
            }
    for reservation in state.get("campaign_reservations") or []:
        if not isinstance(reservation, dict):
            continue
        for ticket in reservation.get("ticket_ids") or []:
            claimed = False
            for partition in (reservation.get("partitions") or {}).values():
                if ticket in (partition.get("claimed") or {}):
                    claimed = True
                    break
            # Reserved tickets remain unavailable to ordinary dispatch even
            # after a child transition: the active registry record is the
            # second, independent owner of that ticket.
            held.setdefault(str(ticket), {
                "branch": f"campaign/{reservation.get('campaign_id')}",
                "path": reservation.get("manifest_path"),
                "claimed_at": reservation.get("claimed_at"),
                "campaign_id": reservation.get("campaign_id"),
                "partition_claimed": claimed,
            })
    return held


class _CampaignPreflightRefusal(RuntimeError):
    def __init__(self, problems: list[dict]):
        super().__init__("dispatch preflight refused campaign ticket")
        self.problems = problems


def _claim_next_backlog(
    *, root: Path, state_arg: str | None, path: Path, branch: str,
    intent: str, base: str, delegated: bool | None = None,
) -> tuple[int, dict[str, Any], list[str], dict[str, Any]]:
    """Atomically select dispatch's head and register its worktree claim.

    `backlog.py dispatch` followed by `open --backlog <id>` is safe but not
    convergent for two coordinators: both can read the same head, then one loses the
    later registry race and has to start selection over. Holding the registry lock
    across BOTH the dispatch read and `cmd_register` turns "take the next ticket"
    into one operation. The registry still owns the claim invariant; backlog.py
    still owns dispatch ordering and eligibility.

    `cmd_register` is called directly because `wr.main()` would take the same flock
    a second time through a fresh fd and deadlock. worktree_registry documents this
    exact outer-lock/direct-call route as valid.
    """
    state_path = Path(state_arg).resolve() if state_arg else wr.default_state_path()
    store = root / BACKLOG_STORE_DIR
    with wr._ledger_lock(state_path):
        state = wr.load_state(state_path)
        held = _held_from_registry_state(state)
        # One definition of dispatch, not a local approximation. The unheld view
        # provides the skipped count that makes contention visible to the caller.
        repo = backlog_tool.owning_repo_for_store(store)
        ranked = backlog_tool.list_entries(store, dispatch=True, held={}, repo=repo)
        available = backlog_tool.list_entries(store, dispatch=True, held=held, repo=repo)
        if not available:
            return (
                EXIT_BLOCK,
                {"reason": "dispatch queue has no unclaimed ticket", "conflicts": []},
                [],
                {"mode": "dispatch-head", "eligible": len(ranked),
                 "available": 0, "skipped_claimed": len(ranked)},
            )
        chosen = available[0]
        ticket = str(chosen["id"])
        blockers = _unclaimable(store, [ticket], state_path=state_path)
        if blockers:
            return (
                EXIT_BLOCK,
                {"reason": "dispatch preflight refused", "problems": blockers},
                [],
                {"mode": "dispatch-head", "eligible": len(ranked),
                 "available": len(available), "skipped_claimed": 0},
            )
        rank = next((i for i, item in enumerate(ranked)
                     if item.get("id") == ticket), 0)
        register_args = argparse.Namespace(
            state=str(state_path), at=None, path=str(path), branch=branch,
            intent=intent, base=base, repo_root=str(root), backlog=[ticket],
            exclusive=True, json=True, delegated=delegated,
        )
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = wr.cmd_register(register_args)
        try:
            payload = json.loads(buf.getvalue())
        except json.JSONDecodeError:
            payload = {"reason": "registry returned unreadable claim output"}
        return rc, payload, [ticket], {
            "mode": "dispatch-head",
            "eligible": len(ranked),
            "available": len(available),
            "skipped_claimed": rank,
        }


def _claim_next_campaign_backlog(
    *, root: Path, state_arg: str | None, path: Path, branch: str,
    intent: str, base: str, campaign_id: str, partition_id: str,
    delegated: bool | None = None,
) -> tuple[int, dict[str, Any], list[str], dict[str, Any]]:
    """Atomically move one reserved ticket in one campaign partition to a child."""
    state_path = Path(state_arg).resolve() if state_arg else wr.default_state_path()

    def read_locked_base() -> str:
        state = wr.load_state(state_path)
        reservation = next(
            (item for item in state.get("campaign_reservations") or []
             if item.get("campaign_id") == campaign_id),
            None,
        )
        partition = ((reservation or {}).get("partitions") or {}).get(partition_id)
        ticket_ids = list((partition or {}).get("ticket_ids") or [])
        claimed = (partition or {}).get("claimed") or {}
        ticket = next((item for item in ticket_ids if item not in claimed), None)
        if ticket is not None:
            blockers = _unclaimable(
                root / BACKLOG_STORE_DIR, [str(ticket)], state_path=state_path,
            )
            if blockers:
                raise _CampaignPreflightRefusal(blockers)
        rc, output = _git(["rev-parse", base], cwd=root)
        return output.strip() if rc == EXIT_OK else ""

    try:
        result = wr.claim_campaign_ticket(
            state_path,
            campaign_id=campaign_id,
            partition_id=partition_id,
            branch=branch,
            path=str(path),
            intent=intent,
            base=base,
            base_reader=read_locked_base,
            delegated=delegated,
        )
    except _CampaignPreflightRefusal as exc:
        return EXIT_BLOCK, {
            "ok": False, "reason": "dispatch preflight refused", "problems": exc.problems,
        }, [], {"mode": "campaign-partition", "campaign": campaign_id,
                "partition": partition_id}
    selection = {"mode": "campaign-partition", "campaign": campaign_id,
                 "partition": partition_id}
    if not result.get("ok"):
        return EXIT_BLOCK, result, [], selection
    reservation = result["reservation"]
    selection.update({
        "quota": (reservation.get("partitions") or {}).get(partition_id, {}).get("quota"),
        "used": (reservation.get("partitions") or {}).get(partition_id, {}).get("used"),
        "remaining": (reservation.get("partitions") or {}).get(partition_id, {}).get("remaining"),
        "base": reservation.get("base"), "ticket": result["ticket"],
    })
    return EXIT_OK, result, [result["ticket"]], selection



# ============================================================================
# IO layer — git + subprocess to the real gate tools.
# ============================================================================
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
def cmd_campaign_reserve(args: argparse.Namespace) -> int:
    """Validate or atomically persist a complete campaign reservation manifest."""
    request_path = Path(args.request_file).resolve()
    try:
        request = json.loads(request_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        _emit({"schema": SCHEMA, "step": "campaign-reserve",
               "error": "request file unreadable", "path": str(request_path),
               "detail": str(exc)}, args.json,
              f"✗ cannot read campaign request {request_path}: {exc}")
        return EXIT_USAGE
    root = primary_root()
    base_rc, current_base = _git(["rev-parse", args.base_ref], cwd=root)
    if base_rc != EXIT_OK:
        _emit({"schema": SCHEMA, "step": "campaign-reserve",
               "error": "base ref unreadable", "base_ref": args.base_ref,
               "detail": current_base}, args.json,
              f"✗ cannot resolve base ref {args.base_ref}: {current_base}")
        return EXIT_BLOCK
    store = root / BACKLOG_STORE_DIR
    try:
        def read_locked_base() -> str:
            rc, output = _git(["rev-parse", args.base_ref], cwd=root)
            return output.strip() if rc == EXIT_OK else ""

        result = wr.reserve_campaign(
            wr._state_path(args), request,
            current_base=current_base.strip(),
            backlog_reader=lambda: list(backlog_tool._iter_entries(store)),
            base_reader=read_locked_base,
            commit=args.commit,
        )
    except (OSError, ValueError, TypeError) as exc:
        _emit({"schema": SCHEMA, "step": "campaign-reserve",
               "error": "campaign reservation failed", "detail": str(exc)}, args.json,
              f"✗ campaign reservation failed: {exc}")
        return EXIT_BLOCK
    payload = {"schema": SCHEMA, "step": "campaign-reserve", **result,
               "base_ref": args.base_ref}
    human = ("✓ campaign reservation " if result.get("ok") else "✗ campaign reservation ")
    human += (f"{result.get('campaign_id') or request.get('campaign_id')} "
              f"({result.get('mode')})")
    if not result.get("ok"):
        human += ": " + "; ".join(
            str(problem.get("message") or problem.get("kind"))
            for problem in result.get("conflicts") or [])
    _emit(payload, args.json, human)
    return EXIT_OK if result.get("ok") else EXIT_BLOCK


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

    branch = branch_for(args.intent, args.slug, getattr(args, "type", None))
    root = primary_root()
    path = root / ".claude" / "worktrees" / args.slug
    base = args.base

    # local-centric: fork from the LOCAL trunk (default `main`) — offline, no fetch.
    # origin is a deploy target, not the fork point.
    if path.exists():
        _emit({"schema": SCHEMA, "step": "open", "error": "worktree path exists",
               "path": str(path)}, args.json, f"✗ worktree path already exists: {path}")
        return EXIT_USAGE
    next_backlog = bool(getattr(args, "next_backlog", False))
    if next_backlog and args.allow_ungroomed:
        _emit({"schema": SCHEMA, "step": "open",
               "error": "--next-backlog only selects groomed dispatch entries; "
                        "--allow-ungroomed cannot change that queue"},
              args.json,
              "✗ --next-backlog and --allow-ungroomed are mutually exclusive")
        return EXIT_USAGE
    campaign_id = getattr(args, "campaign", None)
    partition_id = getattr(args, "partition", None)
    delegated = getattr(args, "delegated", None)
    if bool(campaign_id) != bool(partition_id):
        _emit({"schema": SCHEMA, "step": "open",
               "error": "--campaign and --partition must be supplied together"},
              args.json,
              "✗ --campaign and --partition must be supplied together")
        return EXIT_USAGE
    if campaign_id and not next_backlog:
        _emit({"schema": SCHEMA, "step": "open",
               "error": "campaign claims require --next-backlog"}, args.json,
              "✗ campaign claims require --next-backlog")
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
    selection = None
    campaign_claim = None
    if campaign_id:
        reg_rc, reg_payload, wanted, selection = _claim_next_campaign_backlog(
            root=root, state_arg=args.state, path=path, branch=branch,
            intent=args.intent, base=base, campaign_id=campaign_id,
            partition_id=partition_id,
            delegated=delegated,
        )
        if reg_rc == EXIT_OK:
            campaign_claim = {"campaign_id": campaign_id, "partition": partition_id,
                              "ticket": wanted[0], "branch": branch,
                              "reservation": (reg_payload or {}).get("reservation")}
    elif next_backlog:
        reg_rc, reg_payload, wanted, selection = _claim_next_backlog(
            root=root, state_arg=args.state, path=path, branch=branch,
            intent=args.intent, base=base, delegated=delegated,
        )
    else:
        if _refuse_unclaimable(root, wanted, args, "open", branch) is not None:
            return EXIT_BLOCK
        claim_argv = ["--backlog", *wanted] if args.backlog is not None else []
        reg_rc, reg_payload = _registry(
            ["register", *_state_arg(args.state), "--path", str(path),
             "--repo-root", str(root), "--branch", branch,
             "--intent", args.intent, "--base", base,
             *_delegated_arg(delegated),
             *claim_argv, "--exclusive", "--json"])
    if reg_rc != EXIT_OK:
        conflicts = (reg_payload or {}).get("conflicts", [])
        held = ", ".join(
            f"{','.join(c.get('backlog') or [])} by [{c.get('branch')}] at {c.get('path')}"
            for c in conflicts) or (reg_payload or {}).get("reason", "register refused")
        error = ((reg_payload or {}).get("reason")
                 if next_backlog else "claim refused")
        preflight_problems = (reg_payload or {}).get("problems", [])
        details = ""
        if preflight_problems:
            details = "\n" + "\n".join(
                f"  {problem.get('kind', 'preflight')}: "
                f"{problem.get('repair', problem)}"
                for problem in preflight_problems
            )
        _emit({"schema": SCHEMA, "step": "open", "error": error,
               "branch": branch, "backlog": wanted, "conflicts": conflicts,
               "selection": selection, "registry_rc": reg_rc,
               "problems": preflight_problems}, args.json,
              f"✗ cannot open [{branch}] — {held}{details}")
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
        if campaign_claim:
            released = wr.release_campaign_claim(
                Path(args.state).resolve() if args.state else wr.default_state_path(),
                campaign_id=campaign_claim["campaign_id"],
                partition_id=campaign_claim["partition"],
                ticket_id=campaign_claim["ticket"], branch=branch,
            )
            rel_rc = EXIT_OK if released.get("ok") else EXIT_BLOCK
        else:
            rel_rc, _ = _registry(["resolve", *_state_arg(args.state), "--branch", branch,
                                   "--status", "abandoned"])
        _emit({"schema": SCHEMA, "step": "open", "error": "worktree add failed",
               "detail": out, "backlog": wanted, "claim_released": rel_rc == EXIT_OK},
              args.json,
              f"✗ git worktree add failed:\n{out}\n"
              f"  {'claim released' if rel_rc == EXIT_OK else '⚠ COULD NOT release the claim — run: '
                 f'ops/worktree_registry.py resolve --branch {branch} --status abandoned'}")
        return EXIT_BLOCK

    scratch = worktree_scratch_path(path)
    try:
        scratch.mkdir(parents=True, exist_ok=False)
    except OSError as exc:
        cleanup_rc, cleanup_out = _git_mutation(
            ["worktree", "remove", "--force", str(path)],
            cwd=root,
            label="open-scratch-cleanup",
        )
        rel_rc = EXIT_BLOCK
        if cleanup_rc == EXIT_OK:
            if campaign_claim:
                released = wr.release_campaign_claim(
                    Path(args.state).resolve() if args.state else wr.default_state_path(),
                    campaign_id=campaign_claim["campaign_id"],
                    partition_id=campaign_claim["partition"],
                    ticket_id=campaign_claim["ticket"], branch=branch,
                )
                rel_rc = EXIT_OK if released.get("ok") else EXIT_BLOCK
            else:
                rel_rc, _ = _registry(["resolve", *_state_arg(args.state),
                                       "--branch", branch, "--status", "abandoned"])
        _emit({"schema": SCHEMA, "step": "open", "error": "scratch setup failed",
               "detail": str(exc), "scratch_dir": str(scratch),
               "worktree_cleanup_rc": cleanup_rc, "claim_released": rel_rc == EXIT_OK,
               "cleanup_detail": cleanup_out}, args.json,
              f"✗ cannot create isolated scratch directory {scratch}: {exc}\n"
              f"  worktree cleanup rc={cleanup_rc}, claim released={rel_rc == EXIT_OK}")
        return EXIT_BLOCK

    # A non-ignored scratch directory would appear as a source change and could
    # enter a gate or a commit. Refuse the birth rather than creating a second,
    # untracked coordination surface.
    ignore_rc, ignore_out = _git(["check-ignore", "-q", "--", str(WORKTREE_SCRATCH_REL)],
                                 cwd=path)
    if ignore_rc != EXIT_OK:
        cleanup_rc, cleanup_detail = _git_mutation(
            ["worktree", "remove", "--force", str(path)],
            cwd=root,
            label="open-scratch-ignore-cleanup",
        )
        rel_rc = EXIT_BLOCK
        if cleanup_rc == EXIT_OK:
            if campaign_claim:
                released = wr.release_campaign_claim(
                    Path(args.state).resolve() if args.state else wr.default_state_path(),
                    campaign_id=campaign_claim["campaign_id"],
                    partition_id=campaign_claim["partition"],
                    ticket_id=campaign_claim["ticket"], branch=branch,
                )
                rel_rc = EXIT_OK if released.get("ok") else EXIT_BLOCK
            else:
                rel_rc, _ = _registry(["resolve", *_state_arg(args.state),
                                       "--branch", branch, "--status", "abandoned"])
        _emit({"schema": SCHEMA, "step": "open", "error": "scratch is not ignored",
               "scratch_dir": str(scratch), "check_ignore_rc": ignore_rc,
               "check_ignore_detail": ignore_out, "worktree_cleanup_rc": cleanup_rc,
               "claim_released": rel_rc == EXIT_OK, "cleanup_detail": cleanup_detail},
              args.json,
              f"✗ scratch directory is not gitignored: {scratch}\n"
              f"  add an ignore rule before opening worktrees; cleanup rc={cleanup_rc}")
        return EXIT_BLOCK

    payload = {"schema": SCHEMA, "step": "open", "branch": branch, "path": str(path),
               "base": base, "intent": args.intent, "backlog": wanted,
               "selection": selection, "campaign": campaign_claim,
               "scratch_dir": str(scratch), "registered": True}
    human = (f"✓ opened worktree [{branch}] (base {base})\n"
             f"  path: {path}\n"
             f"  scratch: {scratch}\n"
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
    delegated = getattr(args, "delegated", None)
    if _refuse_unclaimable(Path(primary_root()), wanted, args, "adopt",
                           branch) is not None:
        return EXIT_BLOCK
    claim_argv = ["--backlog", *wanted] if args.backlog is not None else []  # see cmd_open
    reg_rc, reg_payload = _registry(
        ["register", "--state", state, "--path", worktree, "--branch", branch,
         "--intent", args.intent, "--base", args.base,
         *_delegated_arg(delegated), *claim_argv, "--json"])
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
    """Serialize the complete origin->local primary fast-forward transition."""
    primary = primary_root()
    with _main_advance_lock(primary):
        return _cmd_sync_main_locked(args, primary)


def _cmd_sync_main_locked(args: argparse.Namespace, primary: Path) -> int:
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
    """Serialize a trunk publish against local cutover and other sync operations."""
    with _main_advance_lock(primary_root()):
        return _guarded_advance_locked(
            src_branch=src_branch, dest_branch=dest_branch, production=production,
            step=step, commit=commit, as_json=as_json, state=state,
        )


def _guarded_advance_locked(*, src_branch: str, dest_branch: str, production: bool,
                            step: str, commit: bool, as_json: bool,
                            state: str | None) -> int:
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

    # Snapshot the HEAD BEFORE resolving input scopes. A concurrent commit in this
    # worktree between the diff/fingerprint probe and the record write would otherwise
    # let a reused result acquire the wrong HEAD identity; cutover's later check cannot
    # tell that the fingerprint belonged to the earlier tree.
    head = _head_sha(worktree)
    changed = _changed_vs_base(worktree, args.base)
    no_changed_files = not changed
    # anchor test-existence at the WORKTREE so a test file added in this very diff
    # is seen (the primary checkout may not have it yet)
    plan = plan_gates(changed,
                      ops_test_exists=lambda rel: (Path(worktree) / rel).is_file(),
                      base=args.base,
                      ops_tests_dir_exists=lambda: (Path(worktree) / "ops/tests").is_dir(),
                      path_exists=lambda rel: (Path(worktree) / rel).is_file())
    results: list[dict[str, Any]] = []
    rec_path = _gate_record_path(args.state, worktree)
    progress_path = _gate_progress_path(args.state, worktree)
    progress_started = time.monotonic()
    run_id = f"{head[:12]}-{os.getpid()}-{time.monotonic_ns()}"
    print(f"[worktree][gate] phase=plan gates={len(plan)} progress={progress_path} "
          f"run_id={run_id}", file=sys.stderr, flush=True)
    completed: list[dict[str, str]] = []
    progress_generation: int | None = None

    def publish_progress(*, claim: bool = False, terminal: bool = False) -> None:
        nonlocal progress_generation
        done = len(completed)
        current = None if terminal or done >= len(plan) else plan[done]["name"]
        progress = {
            "schema": GATE_PROGRESS_SCHEMA,
            "run_id": run_id,
            "worktree": worktree,
            "head_sha": head,
            "plan_total": len(plan),
            "done": done,
            "current": current,
            "elapsed": round(time.monotonic() - progress_started, 3),
            "completed": list(completed),
        }
        try:
            with _gate_progress_lock(args.state):
                existing = _read_gate_progress(progress_path)
                if claim:
                    previous_generation = (existing or {}).get("generation", 0)
                    if (not isinstance(previous_generation, int)
                            or isinstance(previous_generation, bool)
                            or previous_generation < 0):
                        previous_generation = 0
                    progress_generation = previous_generation + 1
                elif (progress_generation is None
                      or not existing
                      or existing.get("run_id") != run_id
                      or existing.get("generation") != progress_generation):
                    owner = (existing or {}).get("run_id", "unknown")
                    generation = (existing or {}).get("generation", "unknown")
                    print(f"[worktree][gate] phase=progress progress={progress_path} "
                          f"write=skipped reason=stale-run owner_run_id={owner} "
                          f"owner_generation={generation} run_id={run_id}",
                          file=sys.stderr, flush=True)
                    return
                progress["generation"] = progress_generation
                _write_atomic(progress_path,
                              json.dumps(progress, indent=2, ensure_ascii=False) + "\n")
        except OSError as exc:
            # Progress is observational, not a verdict input. Keep the gate running but
            # name a broken progress surface instead of silently losing the live view.
            print(f"[worktree][gate] phase=progress progress={progress_path} "
                  f"write=failed error={type(exc).__name__}: {exc}",
                  file=sys.stderr, flush=True)

    if not args.plan_only:
        publish_progress(claim=True)
        previous, previous_error = _read_gate_record(rec_path)
        tracked = _tracked_paths(worktree)
        for spec in plan:
            current_input = _gate_input_scope(spec, worktree, changed, tracked)
            now = _head_sha(worktree)
            if now != head:
                payload = {"schema": GATE_SCHEMA, "step": "gate",
                           "error": (f"worktree HEAD moved while preparing gate inputs "
                                     f"({head[:8]} -> {now[:8]}) — re-run gate"),
                           "worktree": worktree, "initial_head": head, "current_head": now}
                _emit(payload, args.json, f"✗ gate refused: {payload['error']}")
                return EXIT_BLOCK
            reused, reason = _reuse_gate(spec, current_input, previous, previous_error, orch,
                                         args.base)
            if reused is not None:
                result = reused
            else:
                result = _run_gate(spec, worktree, record_path=rec_path, state=args.state)
                result["reused"] = False
                result["reused_from_head"] = None
                result["reuse"] = {
                    "decision": "rerun",
                    "source_head": previous.get("head_sha") if previous else None,
                    "reason": reason,
                }
                result["input"] = current_input
            results.append(result)
            completed.append({"name": result["name"], "status": result["status"]})
            publish_progress()
            print(f"[worktree][gate] phase=gate gate={result['name']} "
                  f"status={result['status']} done={len(completed)}/{len(plan)} "
                  f"elapsed={time.monotonic() - progress_started:.1f}s "
                  f"progress={progress_path}", file=sys.stderr, flush=True)
            if spec.get("preflight") and result.get("status") != "pass":
                # A preflight result must prove the prerequisite, not merely avoid a
                # hard block. Stop on block, warn, or inconclusive so tag races and
                # other typed uncertainty cannot launch expensive gates.
                publish_progress(terminal=True)
                print(f"[worktree][gate] phase=stop reason=preflight-nonpass "
                      f"gate={result['name']} status={result['status']} "
                      f"remaining={len(plan) - len(results)} "
                      f"progress={progress_path}", file=sys.stderr, flush=True)
                break
    verdict = aggregate_verdict(results) if not args.plan_only else "planned"

    now = _head_sha(worktree)
    if not args.plan_only and now != head:
        payload = {"schema": GATE_SCHEMA, "step": "gate",
                   "error": (f"worktree HEAD moved while gates ran "
                             f"({head[:8]} -> {now[:8]}) — discard this run and re-run gate"),
                   "worktree": worktree, "initial_head": head, "current_head": now}
        _emit(payload, args.json, f"✗ gate refused: {payload['error']}")
        return EXIT_BLOCK
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

    primary = None
    primary_dirty: list[str] = []
    primary_dirty_error: str | None = None
    if not args.plan_only:
        primary = primary_root()
    if (not args.plan_only and primary is not None
            and Path(primary).resolve() != Path(worktree).resolve()):
        try:
            primary_rc, primary_status = _git(
                ["status", "--porcelain", "--untracked-files=no"], cwd=primary
            )
        except Exception as exc:  # noqa: BLE001 — observation must not fail the gate
            primary_rc, primary_status = 127, str(exc)
        if primary_rc != 0:
            primary_dirty_error = (primary_status[:200]
                                   or f"git status failed with rc={primary_rc}")
        else:
            primary_dirty = _porcelain_paths(primary_status)

    record = {"schema": GATE_SCHEMA, "worktree": worktree, "base": args.base,
              "head_sha": head, "orchestrator": orch, "changed_files": changed,
              "no_changed_files": no_changed_files,
              "plan": [{"name": g["name"], "level": g["level"], "category": g["category"],
                        "cmd": g.get("cmd")} for g in plan],
              "gates": results, "verdict": verdict,
              "gate_reuse": _reuse_summary(results)}
    if not args.plan_only:
        record.update({"primary": str(primary), "primary_dirty": primary_dirty,
                       "primary_dirty_error": primary_dirty_error})
        # Non-blocking, but never silent: a permanently unwritable journal must not be
        # indistinguishable from a machine that simply has no history yet.
        record["history_error"] = history_error
        rec_path.parent.mkdir(parents=True, exist_ok=True)
        rec_path.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n")

    # A receipt line the agent PASTES rather than recalls. Structured receipt
    # fields that an agent types from memory are exactly as trustworthy as prose
    # — a fabricated digest is no harder to produce than "tests passed". This
    # line cannot be produced without having run the gate, and the reader can
    # `cat` the record path to check it. Keep one renderer for both output modes;
    # otherwise the two surfaces can silently drift apart.
    counts = {}
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    breakdown = " ".join(f"{k}={v}" for k, v in sorted(counts.items()))
    reuse = record.get("gate_reuse", {})
    no_changes = (" no-changes"
                  if record.get("no_changed_files") and not args.plan_only else "")
    record_ref = (str(_gate_record_path(args.state, worktree))
                  if not args.plan_only else "<not recorded>")
    executed_count = _executed_gate_count(results)
    receipt_line = (f"gate={verdict} record={record_ref} "
                    f"head={head[:8]} orch={_orch_token(record)} gates={len(plan)} "
                    f"executed={executed_count} {breakdown} "
                    f"reused={len(reuse.get('reused', []))} rerun={len(reuse.get('rerun', []))}"
                    f"{no_changes}")
    if getattr(args, "receipt_line", False):
        print(receipt_line)
        return EXIT_OK if args.plan_only or verdict in ("pass", "warn") else EXIT_BLOCK

    lines = [f"# gate {verdict.upper()}  ({len(changed)} changed file(s), "
             f"{len(plan)} gate(s))  orchestrator={_orch_token(record)}"]
    if not args.plan_only and no_changed_files:
        lines.append(
            f"  ⚠ no changes in this worktree vs {args.base} — no changed files were "
            f"verified. If you have been editing, the edits may have landed in the "
            f"primary checkout instead (cwd drift); check `git -C {worktree} status` "
            "before trusting this gate result."
        )
    if not args.plan_only and primary_dirty_error:
        lines.append(
            f"  ⚠ primary working tree status unavailable: {primary_dirty_error} — "
            "inspect the primary checkout before trusting this gate result."
        )
    elif not args.plan_only and primary_dirty:
        shown = ", ".join(primary_dirty[:5])
        if len(primary_dirty) > 5:
            shown += f" … and {len(primary_dirty) - 5} more"
        lines.append(
            f"  ⚠ primary working tree has {len(primary_dirty)} uncommitted tracked "
            f"file(s): {shown} — if these are your edits, they landed in the primary "
            "checkout rather than this worktree."
        )
    for r in results:
        mark = {"pass": "✓", "warn": "⚠", "block": "✗",
                "inconclusive": "~"}.get(r["status"], "?")
        lines.append(f"  {mark} {r['name']} [{r['status']}] — {r.get('summary','')}")
    if not plan:
        lines.append("  (no impact-based gates selected for these changes)")
    if record.get("history_error"):
        lines.append(f"  ! gate history not written ({record['history_error']}) — "
                     f"never-green detection is blind until this is fixed")
    if not args.plan_only:
        lines.append(receipt_line)
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

    delegated_records = _delegated_records_for_path(args.state, worktree)
    if delegated_records:
        record = delegated_records[0]
        payload = {
            "schema": SCHEMA, "step": "cutover", "error": (
                "delegated worktree cannot cut over; the integrator must run gate/cutover"
            ), "refusal": "delegated", "delegated": True, "landed": False,
            "worktree": worktree, "branch": record.get("branch"),
        }
        _emit(payload, args.json,
              f"✗ cutover refused: delegated worktree {record.get('branch')} at {worktree}; "
              "the integrator owns landing")
        return EXIT_BLOCK

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
    gate_reuse: dict[str, Any] = {"reused": [], "rerun": []}
    if not rec_path.exists():
        refuse = "no gate verdict on record — run `gate` first"
    else:
        rec = json.loads(rec_path.read_text())
        verdict = rec.get("verdict")
        gated_head = rec.get("head_sha")
        planned_gates = rec.get("plan")
        recorded_gates = rec.get("gates")
        gate_reuse = rec.get("gate_reuse") or (
            _reuse_summary(recorded_gates)
            if isinstance(recorded_gates, list) else {"reused": [], "rerun": []}
        )
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
        elif not isinstance(planned_gates, list) or not isinstance(recorded_gates, list):
            refuse = ("gate record is malformed (plan/gates must be lists) — "
                      "re-run `gate` before cutover")
        elif len(recorded_gates) != len(planned_gates):
            # A non-pass preflight intentionally stops before expensive gates. Its
            # aggregate can still be WARN (for example a typed inconclusive result),
            # but a partial plan is never evidence for cutover: warn is landable only
            # after every planned gate has produced a row.
            refuse = (f"gate record is incomplete ({len(recorded_gates)} of "
                      f"{len(planned_gates)} planned gate results) — the preflight "
                      "stopped the run; re-run `gate` before cutover")
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
                   "warnings": warnings, "gate_reuse": gate_reuse}
        _emit(payload, args.json,
              f"# cutover (dry-run)\n  would rebase {wt_branch} onto {local}, then "
              f"ff local {local} to it (offline — no push, no deploy){warn_line}\n"
              f"  (--commit to land)")
        return EXIT_OK

    # Serialize the trunk advance; rebase onto the CURRENT local trunk INSIDE the lock
    # so a peer cutover that just advanced it is picked up (not raced past).
    with _main_advance_lock(primary):
        guard = _primary_ff_ready(primary, local, branch=wt_branch,
                                  worktree=worktree)
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
               "verdict": verdict, "warnings": warnings, "gate_reuse": gate_reuse,
               "repair": repair,
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
# repair, for a rebase to conflict on, or for a separate derived artifact to be scoped to.
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
    delegated_records = _delegated_records_for_path(args.state, worktree)
    if delegated_records:
        record = delegated_records[0]
        _emit({
            "schema": SCHEMA, "step": "land", "mode": "refused",
            "error": "delegated worktree cannot land; the integrator owns landing",
            "refusal": "delegated", "delegated": True, "landed": False,
            "worktree": worktree, "branch": record.get("branch"),
        }, args.json,
        f"✗ land refused: delegated worktree {record.get('branch')} at {worktree}; "
        "the integrator owns landing")
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
        # NOT `_current_branch(worktree)`: git discovery walks UP, so a directory
        # that has lost its `.git` answers with the ENCLOSING checkout's branch (i.e.
        # `main`), and cmd_land only checks that the path is a directory. That would
        # post an unattributable "blocked branch: main" notice — the exact thing
        # `_broadcast_cutover_block` calls worse than posting nothing.
        guard = _primary_ff_ready(primary, _local_trunk(args.base),
                                  branch=(_worktree_entry(worktree) or {}).get("branch"),
                                  worktree=worktree)
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
    body = json.dumps(st, indent=2, ensure_ascii=False) + "\n"
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(body, encoding="utf-8")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


_DELIVERY_PHASES = (
    "cutover", "resolve-source", "anchor", "validate", "resolve-integration", "sync",
)
_DELIVERY_PHASE_STATUSES = {"started", "completed", "blocked"}


def _delivery_record_phase(
    manifest_path: Path | None,
    phase: str,
    *,
    status: str,
    **fields: Any,
) -> dict[str, Any] | None:
    """Persist one monotonic close-wave phase receipt.

    The manifest is the recovery ledger, not merely a final report.  A phase may
    be replayed after a process crash, but a completed phase must never regress to
    ``started`` or be overwritten with a different operation identity.  The
    atomic ``_integrate_save`` write means the phase receipt is durable before the
    next phase mutates primary/registry state.
    """
    if manifest_path is None:
        return None
    if phase not in _DELIVERY_PHASES:
        raise ValueError(f"unknown close-wave phase: {phase}")
    if status not in _DELIVERY_PHASE_STATUSES:
        raise ValueError(f"unknown close-wave phase status: {status}")
    payload = _delivery_load_json(manifest_path)
    if payload is None:
        raise OSError(f"integration manifest is unreadable: {manifest_path}")
    marker = _delivery_update_phase_marker(
        payload.get("close_wave"), phase, status=status, **fields,
    )
    payload["close_wave"] = marker
    _integrate_save(manifest_path, payload)
    return marker


def _delivery_update_phase_marker(
    raw_marker: Any,
    phase: str,
    *,
    status: str,
    **fields: Any,
) -> dict[str, Any]:
    """Pure marker update used to batch a phase receipt with another save."""
    if phase not in _DELIVERY_PHASES:
        raise ValueError(f"unknown close-wave phase: {phase}")
    if status not in _DELIVERY_PHASE_STATUSES:
        raise ValueError(f"unknown close-wave phase status: {status}")
    if raw_marker is not None and not isinstance(raw_marker, dict):
        raise ValueError("integration manifest has malformed close_wave marker")
    marker = dict(raw_marker or {})
    phases = marker.get("phases")
    if phases is not None and not isinstance(phases, dict):
        raise ValueError("integration manifest has malformed phase ledger")
    phases = dict(phases or {})
    previous = phases.get(phase)
    if previous is not None and not isinstance(previous, dict):
        raise ValueError(f"integration manifest has malformed {phase} phase")
    previous = dict(previous or {})
    if previous.get("status") == "completed":
        # A completed receipt is immutable.  In particular, a retry after a
        # crash must not replace its operation identity with the retry's base.
        marker["phases"] = phases
        if marker.get("last_successful_phase") is None:
            marker["last_successful_phase"] = phase
        return marker
    entry = {**previous, "status": status}
    for key, value in fields.items():
        if value is not None:
            entry[key] = value
    phases[phase] = entry
    marker["phases"] = phases
    marker.setdefault("last_successful_phase", None)
    if status == "completed":
        previous_success = marker.get("last_successful_phase")
        if (previous_success not in _DELIVERY_PHASES
                or _DELIVERY_PHASES.index(phase)
                >= _DELIVERY_PHASES.index(previous_success)):
            marker["last_successful_phase"] = phase
    for key in ("operation_base", "landed_sha"):
        if key in fields and fields[key] is not None:
            marker[key] = fields[key]
    return marker


def _integrate_completed_path(spath: Path, slug: str, head_sha: str) -> Path:
    return spath.parent / "completed" / f"{slug}-{head_sha[:12]}.json"


def _unmerged_paths(worktree: str) -> list[str]:
    """The files git is waiting on. `--diff-filter=U` is git's own name for the state,
    rather than a reading of porcelain wording, and the paths are C-unquoted for the
    same reason `_porcelain_paths` unquotes: a conflict in a path with non-ASCII bytes
    must still be NAMED, and this repo's docs tree is full of them."""
    rc, out = _git(["diff", "--name-only", "--diff-filter=U"], cwd=worktree)
    if rc != 0:
        return []
    return [_c_unquote(ln) for ln in out.splitlines() if ln]


def _branch_pick_list(repo: Path, trunk: str, branch: str, *, ref: str | None = None
                      ) -> tuple[list[dict[str, Any]], list[str], str | None]:
    """(commits to pick, merge commits found, refusal). Oldest first.

    Merge commits are returned SEPARATELY rather than filtered away. `rev-list
    --no-merges` would drop them silently, and a batch verb whose whole reason for
    existing is "no piece of work goes missing" must not itself be the thing that
    loses one.
    """
    source_ref = ref or branch
    rc, _ = _git(["rev-parse", "--verify", "-q", f"{source_ref}^{{commit}}"], cwd=repo)
    if rc != 0:
        return [], [], f"{branch!r} does not resolve to a commit in this repo"
    rc, out = _git(["log", "--reverse", "--no-merges", "--format=%H%x1f%s",
                    f"{trunk}..{source_ref}"], cwd=repo)
    if rc != 0:
        return [], [], f"cannot list {trunk}..{branch}: {out[:200]}"
    commits: list[dict[str, Any]] = []
    for ln in out.splitlines():
        if "\x1f" not in ln:
            continue
        sha, subject = ln.split("\x1f", 1)
        commits.append({"branch": branch, "sha": sha, "subject": subject})
    _, mout = _git(["rev-list", "--merges", f"{trunk}..{source_ref}"], cwd=repo)
    return commits, [ln for ln in mout.splitlines() if ln], None


def _integrate_handoff_check(
    state: str | None,
    branches: list[str],
    *,
    allow_unhanded: bool,
    repo: Path,
) -> dict[str, Any]:
    """Require every source branch to have a current worker hand-back stamp.

    The registry answers who owns a branch and what tip they explicitly returned;
    the primary checkout answers what the branch points to now. These are separate
    observations on purpose. A missing stamp is optionally bypassable for imported
    or legacy branches, but a tip mismatch is never bypassable.
    """
    rc, listing = _registry(["list", *_state_arg(state), "--json"])
    if rc != EXIT_OK or not isinstance(listing, dict) or not isinstance(listing.get("records"), list):
        return {
            "checked": list(branches),
            "source_refs": {},
            "warnings": [],
            "problems": [
                "cannot inspect the worktree registry before integrating — "
                "refusing closed-loop integration"
            ],
        }

    active_by_branch: dict[str, list[dict[str, Any]]] = {}
    for record in listing["records"]:
        if record.get("status") == wr.STATUS_ACTIVE and record.get("branch"):
            active_by_branch.setdefault(record["branch"], []).append(record)

    warnings: list[dict[str, Any]] = []
    problems: list[dict[str, Any]] = []
    source_refs: dict[str, str] = {}
    for branch in branches:
        records = active_by_branch.get(branch, [])
        if len(records) != 1:
            reason = ("no active registry record" if not records else
                      "multiple active registry records")
            item = {
                "branch": branch,
                "reason": reason,
                "remedy": f"./ops/worktree_registry.py hand-back --branch {branch} --json",
            }
            if allow_unhanded and not records:
                warnings.append(item)
            else:
                problems.append(item)
            continue

        record = records[0]
        handed_back_sha = record.get("handed_back_sha")
        if not handed_back_sha:
            item = {
                "branch": branch,
                "reason": "active record has no hand-back stamp",
                "remedy": f"./ops/worktree_registry.py hand-back --branch {branch} --json",
            }
            if allow_unhanded:
                warnings.append(item)
            else:
                problems.append(item)
            continue

        source_refs[branch] = handed_back_sha

        tip_rc, current_tip = _git(
            ["rev-parse", "--verify", "-q", f"{branch}^{{commit}}"], cwd=repo
        )
        if tip_rc != 0 or not current_tip:
            problems.append({
                "branch": branch,
                "reason": "source branch tip cannot be resolved",
                "handed_back_sha": handed_back_sha,
            })
            continue
        if current_tip != handed_back_sha:
            problems.append({
                "branch": branch,
                "reason": "branch advanced after hand-back",
                "handed_back_sha": handed_back_sha,
                "current_tip_sha": current_tip,
            })
            continue

        seal_problems = wr.validate_handback_seal(
            record, repo=repo, require_seal=True,
        )
        if seal_problems:
            for problem in seal_problems:
                item = {"branch": branch, **problem}
                if allow_unhanded and problem.get("kind") == "handback-seal-missing":
                    warnings.append(item)
                else:
                    problems.append(item)

    return {"checked": list(branches), "source_refs": source_refs,
            "warnings": warnings, "problems": problems}


def _integrate_claim_sources(args: argparse.Namespace,
                             st: dict[str, Any]) -> dict[str, Any]:
    """Idempotently acquire/recover this integration's source reservations."""
    registry_state = (Path(args.state).resolve() if args.state
                      else wr.default_state_path())
    return wr.claim_integration_sources(
        registry_state,
        source_refs=(st.get("handoff") or {}).get("source_refs", {}),
        integration_branch=st["branch"],
        integration_slug=st["slug"],
        claimed_at=st["opened_at"],
    )


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
    if getattr(args, "status", False):
        mutation_flags = {
            "--branches": bool(args.branches),
            "--parent": bool(getattr(args, "parent", False)),
            "--continue": bool(args.cont),
            "--append": bool(args.append),
            "--abort": bool(args.abort),
            "--no-gate": bool(args.no_gate),
            "--allow-unhanded": bool(args.allow_unhanded),
            "--commit": bool(args.commit),
            "--independent": bool(getattr(args, "independent", False)),
            "--campaign": bool(getattr(args, "campaign", None)),
            # Even an explicit `--base main` is a source/mutation flag for
            # status.  `main` is the default only when the caller omitted it.
            "--base": bool(getattr(args, "_base_explicit", False)) or args.base != BASE_DEFAULT,
        }
        present = [flag for flag, enabled in mutation_flags.items() if enabled]
        if present:
            _emit({
                "schema": INTEGRATE_SCHEMA, "step": "integrate",
                "mode": "refused", "slug": args.slug,
                "error": "--status is read-only and cannot be combined with "
                          "mutation or source-selection flags",
                "conflicts": present,
            }, args.json, "✗ integrate --status refused: conflicting flags " + ", ".join(present))
            return EXIT_USAGE
        state_path = Path(args.state).expanduser().resolve() if args.state else wr.default_state_path()
        state_file = integrate_status.integration_state_path(state_path, args.slug)
        status_repo = primary_root()
        try:
            raw = json.loads(state_file.read_text(encoding="utf-8"))
            if isinstance(raw, dict) and raw.get("worktree"):
                status_repo = Path(str(raw["worktree"])).expanduser().resolve()
        except (OSError, UnicodeError, json.JSONDecodeError):
            # The projector emits the typed state-unreadable/missing receipt.  Keep
            # the fallback repo read-only; it is only used for those failure shapes.
            pass
        rc, payload = integrate_status.project_status(
            slug=args.slug, state_path=state_path, repo=status_repo,
        )
        phase = payload.get("phase", "unknown")
        problems = payload.get("problems") or []
        next_action = payload.get("next_action")
        summary = f"# integrate --status {args.slug}: phase={phase} next={next_action}"
        if problems:
            summary += "\n  problems: " + "; ".join(
                str(item.get("kind") or item) for item in problems
            )
        _emit(payload, args.json, summary)
        return rc

    blocked = _freeze_guard(args.state, "integrate", args.json)
    if blocked is not None:
        return blocked
    if not SLUG_RE.match(args.slug or ""):
        _emit({"schema": INTEGRATE_SCHEMA, "step": "integrate", "slug": args.slug,
               "error": "slug must be kebab-case ([a-z0-9] words joined by '-')"},
              args.json,
              f"✗ slug {args.slug!r} must be kebab-case ([a-z0-9] joined by '-')")
        return EXIT_USAGE
    if sum(bool(flag) for flag in (args.cont, args.abort, args.append)) > 1:
        _emit({"schema": INTEGRATE_SCHEMA, "step": "integrate",
               "error": "--append, --continue, and --abort are mutually exclusive"},
              args.json, "✗ integrate: --append, --continue, and --abort are mutually exclusive")
        return EXIT_USAGE

    parent_mode = bool(getattr(args, "parent", False))
    campaign_id = getattr(args, "campaign", None)
    if parent_mode and (args.cont or args.abort or args.append):
        _emit({"schema": INTEGRATE_SCHEMA, "step": "integrate",
               "error": "--parent is only valid for a fresh integration"}, args.json,
              "✗ integrate: --parent cannot be combined with --append, --continue, or --abort")
        return EXIT_USAGE
    if parent_mode and not campaign_id:
        _emit({"schema": INTEGRATE_SCHEMA, "step": "integrate",
               "error": "--parent requires --campaign <id>"}, args.json,
              "✗ integrate: --parent requires --campaign <id>")
        return EXIT_USAGE
    if campaign_id and not parent_mode and not args.cont and not args.abort and not args.append:
        _emit({"schema": INTEGRATE_SCHEMA, "step": "integrate",
               "error": "--campaign requires --parent for a fresh integration"}, args.json,
              "✗ integrate: --campaign requires --parent for a fresh integration")
        return EXIT_USAGE

    spath = _integrate_state_path(args.state, args.slug)
    # Same-name retries share one state file. Lock the whole transition so two
    # coordinators cannot both observe "missing", each open a tree, then overwrite
    # one another's queue. Different round slugs remain fully parallel; this lock
    # is intentionally narrower than the registry lock and the landing queue.
    with wr._ledger_lock(spath):
        if args.abort:
            return _integrate_abort(args, spath)
        if args.append:
            return _integrate_append(args, spath)
        if args.cont:
            return _integrate_continue(args, spath)
        if parent_mode:
            prepared = _integrate_prepare_parent(args)
            if isinstance(prepared, int):
                return prepared
            args.branches = prepared["branches"]
            args._parent_snapshot = prepared["snapshot"]
            args._parent_claimed = prepared.get("claimed", False)
        return _integrate_start(args, spath)


def _integrate_prepare_parent(args: argparse.Namespace) -> dict[str, Any] | int:
    """Resolve and (on commit) reserve the campaign child set before opening git."""
    registry_state = Path(args.state).resolve() if args.state else wr.default_state_path()
    root = primary_root()
    trunk = _local_trunk(args.base)
    rc, base_sha = _git(["rev-parse", "--verify", f"{trunk}^{{commit}}"], cwd=root)
    if rc != EXIT_OK or not base_sha:
        _emit({"schema": INTEGRATE_SCHEMA, "step": "integrate", "mode": "refused",
               "campaign_id": args.campaign, "error": "parent base is unreadable",
               "base": trunk, "detail": base_sha}, args.json,
              f"✗ integrate --parent refused: cannot resolve current {trunk}")
        return EXIT_BLOCK
    state = wr.load_state(registry_state)
    reservation = next(
        (item for item in state.get("campaign_reservations") or []
         if item.get("campaign_id") == args.campaign), None,
    )
    if not isinstance(reservation, dict):
        _emit({"schema": INTEGRATE_SCHEMA, "step": "integrate", "mode": "refused",
               "campaign_id": args.campaign,
               "problems": [{"kind": "campaign-reservation-missing",
                             "message": "campaign reservation does not exist"}]}, args.json,
              f"✗ integrate --parent refused: no campaign reservation for {args.campaign}")
        return EXIT_BLOCK

    # Dry-run still performs the complete reconciliation, but does not claim an
    # owner or create a worktree.  Commit mode upgrades the same snapshot to the
    # atomic registry reservation under its canonical lock.
    snapshot = campaign.parent_child_snapshot(
        reservation, state.get("records") or [],
        campaign_id=args.campaign, base_sha=base_sha,
    )
    if not snapshot.get("ok"):
        _emit({"schema": INTEGRATE_SCHEMA, "step": "integrate", "mode": "refused",
               "campaign_id": args.campaign, "snapshot": snapshot,
               "error": "parent child reconciliation failed"}, args.json,
              "✗ integrate --parent refused before opening worktree:\n"
              + "\n".join(f"  {item.get('kind')}: {item.get('message')}"
                           for item in snapshot.get("problems") or []))
        return EXIT_BLOCK
    claim: dict[str, Any] | None = None
    if args.commit:
        expected_branch = f"feat/{args.slug}"
        claim = wr.claim_parent_integration(
            registry_state, campaign_id=args.campaign,
            parent_branch=expected_branch, parent_slug=args.slug,
            base_sha=base_sha, request_id=args.slug,
        )
        if not claim.get("ok"):
            _emit({"schema": INTEGRATE_SCHEMA, "step": "integrate", "mode": "refused",
                   "campaign_id": args.campaign, "parent": claim,
                   "error": "parent reservation could not be acquired"}, args.json,
                  "✗ integrate --parent refused: parent reservation not acquired")
            return EXIT_BLOCK
        snapshot = claim
    return {"branches": sorted(snapshot.get("source_refs") or {}),
            "snapshot": snapshot,
            # An idempotent retry already owns the same reservation; only a fresh
            # commit needs compensation if start fails before its state is durable.
            "claimed": bool(claim and claim.get("mode") == "committed")}


def _integrate_release_parent_claim(args: argparse.Namespace, *, branch: str | None = None) -> None:
    """Compensate a parent reservation when start fails before state is durable."""
    if not (getattr(args, "parent", False) and getattr(args, "_parent_claimed", False)):
        return
    registry_state = Path(args.state).resolve() if args.state else wr.default_state_path()
    wr.release_parent_integration(
        registry_state, campaign_id=str(args.campaign),
        parent_branch=branch or f"feat/{args.slug}", parent_slug=args.slug,
    )


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
        independent_suffix = " --independent" if live.get("independent") is True else ""
        if live.get("gate_pending") and not (live.get("queue") or []):
            msg = (f"an integration named {args.slug!r} has picked all "
                   f"{len(live.get('picked') or [])} commit(s), but its gate has not "
                   f"run yet (worktree {live.get('worktree')}) — resume with "
                   f"`--continue --commit{independent_suffix}` to run ONLY the gate, or discard it with "
                   f"`--abort --commit`")
        else:
            msg = (f"an integration named {args.slug!r} is already in flight "
                   f"(worktree {live.get('worktree')}, {len(live.get('queue') or [])} "
                   f"commit(s) still queued) — resume it with `--continue --commit{independent_suffix}` after "
                   f"resolving, or discard it with `--abort --commit`. Starting over on "
                   f"top of it would strand a half-picked tree nothing points at")
        _emit({"schema": INTEGRATE_SCHEMA, "step": "integrate", "error": msg,
               "slug": args.slug, "state_file": str(spath),
               "worktree": live.get("worktree")}, args.json,
              f"✗ integrate refused: {msg}")
        _integrate_release_parent_claim(args)
        return EXIT_USAGE

    handoff = _integrate_handoff_check(
        args.state, list(args.branches), allow_unhanded=args.allow_unhanded,
        repo=primary,
    )
    if handoff["problems"]:
        _emit({"schema": INTEGRATE_SCHEMA, "step": "integrate", "slug": args.slug,
               "error": "source branches were not handed back for integration",
               "handoff": handoff, "trunk": trunk}, args.json,
              "✗ integrate refused: source branch hand-back check failed\n"
              + "\n".join(
                  f"  {p.get('branch')}: {p.get('reason')}"
                  + (f" (handed_back={p['handed_back_sha'][:12]}, "
                     f"current={p['current_tip_sha'][:12]})"
                     if p.get("handed_back_sha") and p.get("current_tip_sha") else "")
                  for p in handoff["problems"]
              ))
        _integrate_release_parent_claim(args)
        return EXIT_BLOCK

    plan: list[dict[str, Any]] = []
    problems: list[str] = []
    for branch in args.branches:
        # A stamped branch is read through the immutable returned SHA, not through
        # the moving branch ref. If the worker advances the branch after hand-back,
        # a race cannot smuggle its new commit into this batch; the recheck below
        # then refuses the run by name as well.
        source_ref = handoff.get("source_refs", {}).get(branch, branch)
        commits, merges, err = _branch_pick_list(primary, trunk, branch, ref=source_ref)
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
    # The first hand-back check protects the plan inputs; this second one closes the
    # gap while git was enumerating commits. From here on stamped sources are pinned
    # to their returned SHA, so a later branch movement cannot add unreturned work.
    handoff_recheck = _integrate_handoff_check(
        args.state, list(args.branches), allow_unhanded=args.allow_unhanded,
        repo=primary,
    )
    if handoff_recheck["problems"]:
        _emit({"schema": INTEGRATE_SCHEMA, "step": "integrate", "slug": args.slug,
               "error": "source branches changed while preparing the integration",
               "handoff": {"initial": handoff, "recheck": handoff_recheck},
               "trunk": trunk}, args.json,
              "✗ integrate refused: source branch hand-back changed during planning")
        _integrate_release_parent_claim(args)
        return EXIT_BLOCK
    handoff["recheck"] = handoff_recheck
    if problems:
        _emit({"schema": INTEGRATE_SCHEMA, "step": "integrate", "slug": args.slug,
               "error": "one or more branches cannot be integrated as given",
               "problems": problems, "trunk": trunk}, args.json,
              "✗ integrate refused:\n" + "\n".join(f"  {p}" for p in problems))
        _integrate_release_parent_claim(args)
        return EXIT_USAGE

    total = sum(len(p["commits"]) for p in plan)
    if not args.commit:
        action = ("pick only and stop before the gate" if args.no_gate
                  else "pick the commits, then run ONE gate")
        _emit({"schema": INTEGRATE_SCHEMA, "step": "integrate", "mode": "dry-run",
               "slug": args.slug, "trunk": trunk, "branches": list(args.branches),
               "plan": plan, "commits": total, "handoff": handoff,
               "would_run": [f"open --slug {args.slug}",
                             f"cherry-pick x{total}"] + ([] if args.no_gate else ["gate"])},
              args.json,
              f"# integrate (dry-run)\n"
              f"  would fork `{args.slug}` off local {trunk}, cherry-pick {total} "
              f"commit(s) from {len(plan)} branch(es), then {action}:\n"
              + "\n".join(
                  f"    {p['branch']}\n" + "\n".join(
                      f"      {c['sha'][:8]} {c['subject']}" for c in p["commits"])
                  for p in plan)
              + "\n  (--commit to execute; nothing lands — `cutover` still does that)")
        return EXIT_OK

    intent = f"integrate a batch of {len(plan)} branch(es) into {trunk}"
    if getattr(args, "independent", False):
        intent = _INDEPENDENT_NO_TICKET_INTENT + intent
    # The intent text deliberately omits branch names. The integration worktree is
    # always a feature branch, so pass that type explicitly instead of asking the
    # free-text classifier to infer it from the batch description.
    orc, opay = _land_step(cmd_open, state=args.state, json=True, base=args.base,
                           slug=args.slug, intent=intent, type="feat", backlog=None,
                           allow_ungroomed=False)
    if orc != EXIT_OK:
        _emit({"schema": INTEGRATE_SCHEMA, "step": "integrate", "slug": args.slug,
               "error": "could not open the integration worktree", "open": opay},
              args.json,
              f"✗ integrate: could not open the integration worktree — "
              f"{opay.get('error', opay)}")
        _integrate_release_parent_claim(args)
        return EXIT_BLOCK

    st = {
        "schema": INTEGRATE_SCHEMA, "slug": args.slug, "base": args.base,
        "trunk": trunk, "worktree": opay["path"], "branch": opay["branch"],
        "branches": list(args.branches),
        "independent": bool(getattr(args, "independent", False)),
        "handoff": handoff,
        "queue": [c for p in plan for c in p["commits"]],
        "planned_total": total,
        "picked": [], "skipped": [],
        "opened_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    if getattr(args, "parent", False):
        # The snapshot was reconciled before open.  Keep it beside the normal
        # handoff so completed manifests can explain every ticket without asking
        # the registry to reconstruct a moving child state later.
        st["parent"] = {
            "campaign_id": args.campaign,
            "owner": {"branch": opay["branch"], "slug": args.slug},
            "snapshot": getattr(args, "_parent_snapshot", {}),
            "ready_for_gate": True,
            "consumed_children": [],
            "ticket_map": {},
        }
    _integrate_save(spath, st)
    source_claim = _integrate_claim_sources(args, st)
    if not source_claim["ok"]:
        # The integration tree has not received a source commit yet. Remove only
        # that empty tree through the normal landed-floor path, so losing this race
        # leaves neither a live branch nor a misleading in-flight state behind.
        cleanup_rc, cleanup = _land_step(
            cmd_resolve, state=args.state, json=True, base=args.base,
            worktree=st["worktree"], branch=None, force=False,
            via_integration=None, commit=True,
        )
        if cleanup_rc == EXIT_OK:
            spath.unlink(missing_ok=True)
            if getattr(args, "parent", False) and getattr(args, "_parent_claimed", False):
                wr.release_parent_integration(
                    Path(args.state).resolve() if args.state else wr.default_state_path(),
                    campaign_id=args.campaign, parent_branch=opay.get("branch", f"feat/{args.slug}"),
                    parent_slug=args.slug,
                )
        else:
            # A failed compensation is still an integration tree with a registry
            # identity. Keep enough state for `--abort --commit`; deleting it here
            # would turn a recoverable losing race into an unattributed orphan.
            st["source_claim"] = source_claim
            st["cleanup_failed"] = cleanup
            _integrate_save(spath, st)
        _emit({
            "schema": INTEGRATE_SCHEMA, "step": "integrate", "slug": args.slug,
            "error": "source branches already belong to another integration",
            "source_claim": source_claim, "cleanup": cleanup,
            "cleanup_rc": cleanup_rc, "state_cleared": cleanup_rc == EXIT_OK,
        }, args.json,
            "✗ integrate refused: one or more source branches already belong to "
            "another integration")
        return EXIT_BLOCK
    st["source_claim"] = source_claim
    _integrate_save(spath, st)
    return _integrate_drive(args, spath, st)


def _integrate_append(args, spath: Path) -> int:
    """Fan in more handed-back child branches into an existing round.

    A Delivery Team master can start an integration round as soon as the first
    child returns. Later children are appended to that same integration tree,
    rather than forcing the master to wait for the whole fan-out or opening a
    second tree. Append is deliberately pick-only: the round's one Gate is
    meaningful only after the master declares the expected child set complete.
    """
    if not args.branches:
        _emit({"schema": INTEGRATE_SCHEMA, "step": "integrate", "operation": "append",
               "slug": args.slug,
               "error": "--append requires one or more new --branches"}, args.json,
              "integrate --append: --branches <new-child-branch> is required")
        return EXIT_USAGE
    if len(args.branches) != len(set(args.branches)):
        _emit({"schema": INTEGRATE_SCHEMA, "step": "integrate", "operation": "append",
               "slug": args.slug, "error": "duplicate source branch in --branches",
               "branches": list(args.branches)}, args.json,
              "integrate --append refused: each child branch may be appended once")
        return EXIT_USAGE

    st = _integrate_load(args, spath, "append")
    if isinstance(st, int):
        return st
    persisted_independent = st.get("independent") is True
    requested_independent = bool(getattr(args, "independent", False))
    if persisted_independent != requested_independent:
        _emit({
            "schema": INTEGRATE_SCHEMA, "step": "integrate", "operation": "append",
            "mode": "refused", "slug": args.slug,
            "error": "independent opt-in must match the persisted integration state",
            "persisted_independent": persisted_independent,
            "requested_independent": requested_independent,
        }, args.json,
        "integrate --append refused: repeat the original --independent opt-in exactly")
        return EXIT_USAGE
    independent_suffix = " --independent" if persisted_independent else ""
    wt = st.get("worktree")
    if not wt or not Path(wt).is_dir():
        _emit({"schema": INTEGRATE_SCHEMA, "step": "integrate", "operation": "append",
               "slug": args.slug, "error": f"the integration worktree is gone ({wt})"},
              args.json, f"integrate --append refused: {wt} is gone")
        return EXIT_BLOCK
    here = _current_branch(wt)
    if here != st.get("branch"):
        _emit({"schema": INTEGRATE_SCHEMA, "step": "integrate", "operation": "append",
               "slug": args.slug, "worktree": wt,
               "expected_branch": st.get("branch"), "actual_branch": here,
               "error": f"the integration worktree is on {here!r}, not "
                        f"{st.get('branch')!r}"}, args.json,
              f"integrate --append refused: {wt} is on {here!r}, not "
              f"{st.get('branch')!r}")
        return EXIT_BLOCK

    # Never put a later child in front of an unresolved earlier pick. A Gate
    # already recorded is evidence for a different child set and cannot be
    # silently invalidated by appending.
    unmerged = _unmerged_paths(wt)
    current_op = _interrupted_operation(wt)
    if unmerged or current_op:
        op = current_op or "unmerged paths"
        _emit({"schema": INTEGRATE_SCHEMA, "step": "integrate", "operation": "append",
               "slug": args.slug, "worktree": wt, "error": f"{op} is in progress",
               "conflicts": unmerged,
               "next_step": f"resolve it in {wt}, then re-run integrate --continue"
                            f"{independent_suffix}"},
              args.json,
              f"integrate --append refused: {op} is in progress in {wt}; "
              "continue the current pick first")
        return EXIT_BLOCK
    if st.get("queue"):
        _emit({"schema": INTEGRATE_SCHEMA, "step": "integrate", "operation": "append",
               "slug": args.slug, "worktree": wt, "remaining": st["queue"],
               "error": "the current integration queue is not empty",
               "next_step": f"integrate --slug {args.slug} --continue --commit "
                            f"--no-gate{independent_suffix}"}, args.json,
              f"integrate --append refused: {len(st['queue'])} existing pick(s) "
              "remain; drain them before appending")
        return EXIT_BLOCK
    if not st.get("gate_pending"):
        _emit({"schema": INTEGRATE_SCHEMA, "step": "integrate", "operation": "append",
               "slug": args.slug, "worktree": wt,
               "error": "integration is not at the appendable pick-only hand-back point",
               "next_step": f"integrate --slug {args.slug} --continue --commit "
                            f"--no-gate{independent_suffix}"}, args.json,
              "integrate --append refused: state is not marked gate_pending")
        return EXIT_BLOCK
    if st.get("gate"):
        _emit({"schema": INTEGRATE_SCHEMA, "step": "integrate", "operation": "append",
               "slug": args.slug, "worktree": wt, "gate": st["gate"],
               "error": "a Gate already judged this child set; append requires a new "
                        "round or an explicit Gate retry"}, args.json,
              "integrate --append refused: this round already has Gate evidence")
        return EXIT_BLOCK

    old_branches = list(st.get("branches") or [])
    duplicate = [branch for branch in args.branches if branch in old_branches]
    if duplicate:
        _emit({"schema": INTEGRATE_SCHEMA, "step": "integrate", "operation": "append",
               "slug": args.slug, "error": "source branch already belongs to this "
                        "integration", "branches": duplicate}, args.json,
              "integrate --append refused: " + ", ".join(duplicate)
              + " already belongs to this round")
        return EXIT_USAGE

    primary = primary_root()
    trunk = st.get("trunk") or _local_trunk(args.base)
    handoff = _integrate_handoff_check(
        args.state, list(args.branches), allow_unhanded=args.allow_unhanded,
        repo=primary,
    )
    if handoff["problems"]:
        _emit({"schema": INTEGRATE_SCHEMA, "step": "integrate", "operation": "append",
               "slug": args.slug, "error": "new source branches were not handed back",
               "handoff": handoff, "trunk": trunk}, args.json,
              "integrate --append refused: source hand-back check failed\n"
              + "\n".join(f"  {p.get('branch')}: {p.get('reason')}"
                          for p in handoff["problems"]))
        return EXIT_BLOCK

    plan: list[dict[str, Any]] = []
    problems: list[str] = []
    accounted = {
        str(item.get("sha")) for item in (st.get("picked") or [])
        if item.get("sha")
    } | {
        str(item.get("sha")) for item in (st.get("skipped") or [])
        if item.get("sha")
    }
    new_seen: set[str] = set()
    for branch in args.branches:
        source_ref = handoff.get("source_refs", {}).get(branch, branch)
        commits, merges, err = _branch_pick_list(primary, trunk, branch, ref=source_ref)
        if err:
            problems.append(err)
            continue
        if merges:
            problems.append(
                f"{branch!r} carries {len(merges)} merge commit(s) "
                f"({', '.join(s[:8] for s in merges)}) in {trunk}..{branch} — "
                "flatten the branch (catchup/rebase) first")
            continue
        if not commits:
            problems.append(
                f"{branch!r} has no commits in {trunk}..{branch} — nothing to integrate")
            continue
        duplicate_sha = [item["sha"] for item in commits
                         if item["sha"] in accounted or item["sha"] in new_seen]
        if duplicate_sha:
            problems.append(
                f"{branch!r} repeats already-accounted commit(s): "
                + ", ".join(sha[:8] for sha in duplicate_sha)
                + " — name only the new child branch or rebuild stacked work")
            continue
        new_seen.update(item["sha"] for item in commits)
        plan.append({"branch": branch, "commits": commits})

    handoff_recheck = _integrate_handoff_check(
        args.state, list(args.branches), allow_unhanded=args.allow_unhanded,
        repo=primary,
    )
    if handoff_recheck["problems"]:
        _emit({"schema": INTEGRATE_SCHEMA, "step": "integrate", "operation": "append",
               "slug": args.slug,
               "error": "source branch changed while preparing the append",
               "handoff": {"initial": handoff, "recheck": handoff_recheck},
               "trunk": trunk}, args.json,
              "integrate --append refused: source hand-back changed during planning")
        return EXIT_BLOCK
    handoff["recheck"] = handoff_recheck
    if problems:
        _emit({"schema": INTEGRATE_SCHEMA, "step": "integrate", "operation": "append",
               "slug": args.slug, "error": "one or more new branches cannot be appended",
               "problems": problems, "trunk": trunk}, args.json,
              "integrate --append refused:\n" + "\n".join(f"  {p}" for p in problems))
        return EXIT_USAGE

    total = sum(len(entry["commits"]) for entry in plan)
    if not args.commit:
        _emit({"schema": INTEGRATE_SCHEMA, "step": "integrate", "operation": "append",
               "mode": "dry-run", "slug": args.slug, "worktree": wt,
               "existing_branches": old_branches, "branches": list(args.branches),
               "plan": plan, "commits": total, "handoff": handoff,
               "head_sha": _head_sha(wt),
               "would_run": [f"cherry-pick x{total}", "stop before the Gate"]},
              args.json,
              f"# integrate --append (dry-run)\n  would cherry-pick {total} "
              f"commit(s) from {len(plan)} new child branch(es) into {wt}\n"
              "  the round Gate remains deferred until the master declares the "
              "full child set (--commit to execute)")
        return EXIT_OK

    merged_handoff = dict(st.get("handoff") or {})
    merged_handoff["checked"] = list(merged_handoff.get("checked") or []) \
        + list(args.branches)
    merged_handoff["source_refs"] = {
        **(merged_handoff.get("source_refs") or {}),
        **(handoff.get("source_refs") or {}),
    }
    merged_handoff["warnings"] = list(merged_handoff.get("warnings") or []) \
        + list(handoff.get("warnings") or [])
    merged_handoff["problems"] = list(merged_handoff.get("problems") or []) \
        + list(handoff.get("problems") or [])
    merged_handoff["append_rechecks"] = list(merged_handoff.get("append_rechecks") or []) \
        + [handoff_recheck]
    candidate = dict(st)
    candidate["branches"] = old_branches + list(args.branches)
    candidate["handoff"] = merged_handoff
    candidate["queue"] = list(st.get("queue") or []) \
        + [item for entry in plan for item in entry["commits"]]
    candidate["planned_total"] = int(st.get("planned_total") or 0) + total
    # Claim the whole candidate set atomically before saving expanded state or
    # touching the integration tree. Existing claims are idempotent.
    source_claim = _integrate_claim_sources(args, candidate)
    if not source_claim["ok"]:
        _emit({"schema": INTEGRATE_SCHEMA, "step": "integrate", "operation": "append",
               "mode": "refused", "slug": args.slug, "worktree": wt,
               "error": "new source branches already belong to another integration",
               "source_claim": source_claim}, args.json,
              "integrate --append refused: source ownership could not be acquired")
        return EXIT_BLOCK
    candidate["source_claim"] = source_claim
    candidate["gate_pending"] = True
    st.clear()
    st.update(candidate)
    _integrate_save(spath, st)

    # Append is intrinsically a partial-round operation. Even if a caller omits
    # --no-gate, never judge a tree while more children may still be returning.
    drive_args = argparse.Namespace(**vars(args))
    drive_args.no_gate = True
    return _integrate_drive(drive_args, spath, st)


def _integrate_drive(args, spath: Path, st: dict[str, Any]) -> int:
    """Pick what is left, then gate once unless the caller explicitly defers it.

    The loop is resumable because every step writes the queue back before the next
    pick can fail. ``--no-gate`` is a real handoff, not a verdict: it leaves the
    integration state alive so a later ``--continue --commit`` gates the final tree.
    """
    wt = st["worktree"]
    independent_suffix = " --independent" if st.get("independent") is True else ""
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
                       f"`--continue --commit{independent_suffix}`")
            else:
                # No unmerged paths and still a failure: an empty pick, a hook, a
                # broken index. Saying "conflicts: []" here would be the tool
                # inventing a diagnosis; hand over git's own words instead.
                why = (f"{head} with no unmerged paths — git said:\n{out[-800:]}\n"
                       f"  resolve it in {wt} by hand (`git -C {wt} cherry-pick "
                       f"--skip` is the usual answer to an empty pick), then "
                       f"`--continue --commit{independent_suffix}`; or discard with "
                       f"`--abort --commit`")
            _emit({"schema": INTEGRATE_SCHEMA, "step": "integrate", "mode": "stopped",
                   "slug": st["slug"], "worktree": wt, "branch": st["branch"],
                   "error": why, "conflicts": conflicts, "stopped": st["stopped"],
                   "picked": st["picked"], "remaining": st["queue"],
                   "state_file": str(spath)},
                  args.json, f"✗ integrate stopped: {why}")
            return EXIT_BLOCK
        st["picked"].append({**item, "new_sha": _head_sha(wt)})
        st["queue"] = st["queue"][1:]
        parent = st.get("parent")
        if isinstance(parent, dict):
            parent["consumed_children"] = sorted({
                *(parent.get("consumed_children") or []), item.get("branch"),
            })
            snapshot_map = (parent.get("snapshot") or {}).get("ticket_map") or {}
            parent_map = parent.setdefault("ticket_map", {})
            for ticket_id, detail in snapshot_map.items():
                if detail.get("source_branch") == item.get("branch"):
                    parent_map[ticket_id] = {
                        **detail,
                        "parent_sha": _head_sha(wt),
                    }
            expected_tickets = set(snapshot_map)
            parent["ready_for_gate"] = set(parent_map) == expected_tickets
        st.pop("stopped", None)
        _integrate_save(spath, st)
    if getattr(args, "no_gate", False):
        return _integrate_picked_only(args, spath, st)
    return _integrate_gate(args, spath, st)


def _integrate_picked_only(args, spath: Path, st: dict[str, Any]) -> int:
    """Persist a picked-but-ungated integration and hand control back.

    This deliberately does not infer a verdict or create a gate record. The next
    ``integrate --continue --commit`` takes the normal ``_integrate_gate`` path,
    keeping the gate independently re-runnable and bound to the final HEAD.
    """
    st["gate_pending"] = True
    _integrate_save(spath, st)
    wt = st["worktree"]
    independent_suffix = " --independent" if st.get("independent") is True else ""
    next_step = (f"{wt}/ops/worktree_orchestrate.py integrate --slug "
                 f"{st['slug']} --continue --commit{independent_suffix}")
    payload = {
        "schema": INTEGRATE_SCHEMA, "step": "integrate", "mode": "picked",
        "slug": st["slug"], "worktree": wt, "branch": st["branch"],
        "trunk": st["trunk"], "branches": st["branches"],
        "independent": st.get("independent") is True,
        "picked": st["picked"], "skipped": st.get("skipped", []),
        "remaining": st.get("queue", []), "head_sha": _head_sha(wt),
        "gated": False, "verdict": None, "landed": False,
        "state_cleared": False, "gate_pending": True, "next_step": next_step,
    }
    _emit(payload, args.json,
          f"✓ integrate {st['slug']}: picked {len(st['picked'])} commit(s), "
          f"stopped before the gate\n  next: {next_step}")
    return EXIT_OK


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
    parent = st.get("parent")
    if isinstance(parent, dict) and not parent.get("ready_for_gate"):
        msg = ("parent child queue reconciliation is incomplete — refusing to run a "
               "Gate until every campaign ticket has a source/child/parent mapping")
        _emit({"schema": INTEGRATE_SCHEMA, "step": "integrate", "mode": "refused",
               "slug": st["slug"], "worktree": wt, "error": msg,
               "parent": parent}, args.json, f"✗ integrate refused: {msg}")
        return EXIT_BLOCK
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
    runner_revision = st.get("runner_revision")
    requires_revision = "runner_revision" in st
    integration_revision = None
    if requires_revision and verdict in ("pass", "warn"):
        integration_revision = _delivery_revision(
            Path(wt) / "ops" / "worktree_orchestrate.py"
        )
        if integration_revision is None:
            _emit({
                "schema": INTEGRATE_SCHEMA, "step": "integrate",
                "mode": "refused", "slug": st["slug"],
                "worktree": wt, "head_sha": head,
                "error": "gated integration tree has no readable orchestrator revision",
            }, args.json,
                "✗ integrate refused: could not capture integration_revision")
            return EXIT_BLOCK
        revision_error = _delivery_revision_guard(
            runner_revision, integration_revision,
        )
        if revision_error:
            _emit({
                "schema": INTEGRATE_SCHEMA, "step": "integrate",
                "mode": "refused", "slug": st["slug"],
                "worktree": wt, "head_sha": head,
                "runner_revision": runner_revision,
                "integration_revision": integration_revision,
                "error": revision_error,
            }, args.json, f"✗ integrate refused: {revision_error}")
            return EXIT_BLOCK
    st["gate"] = {
        "verdict": verdict, "rc": grc, "head_sha": gpay.get("head_sha"),
        "record": str(_gate_record_path(args.state, wt)),
        **({"runner_revision": runner_revision}
           if requires_revision else {}),
        **({"integration_revision": integration_revision}
           if integration_revision is not None else {}),
        "gates": [{"name": g.get("name"), "status": g.get("status"),
                   "summary": g.get("summary")}
                  for g in (gpay.get("gates") or [])
                  if g.get("status") in ("block", "warn", "inconclusive")],
    }
    if integration_revision is not None:
        st["integration_revision"] = integration_revision
    _integrate_save(spath, st)
    next_step = (f"{wt}/ops/worktree_orchestrate.py cutover --worktree {wt} --commit"
                 if verdict in ("pass", "warn")
                 else f"fix the blocking gate(s), then run `{wt}/ops/"
                      f"worktree_orchestrate.py integrate --slug {st['slug']} "
                      f"--continue --commit"
                      f"{' --independent' if st.get('independent') is True else ''}`")
    payload = {
        "schema": INTEGRATE_SCHEMA, "step": "integrate", "mode": "committed",
        "slug": st["slug"], "worktree": wt, "branch": st["branch"],
        "trunk": st["trunk"], "branches": st["branches"],
        "independent": st.get("independent") is True,
        "handoff": st.get("handoff", {"checked": st["branches"],
                                        "warnings": [], "problems": []}),
        "source_claim": st.get("source_claim"),
        "picked": st["picked"], "skipped": st.get("skipped", []),
        "head_sha": head, "gate": st["gate"], "gate_runs": 1,
        **({"runner_revision": runner_revision}
           if requires_revision else {}),
        **({"integration_revision": integration_revision}
           if integration_revision is not None else {}),
        "verdict": verdict, "landed": False, "next_step": next_step,
        "state_cleared": verdict in ("pass", "warn"),
    }
    # The queue is drained and the gate has spoken, so there is nothing left to
    # `--continue`; keeping the file made a FINISHED integration answer the next
    # `integrate --slug <same>` with "already in flight … resume it with --continue
    # after resolving", which is false in three ways at once. It is also the residue
    # `resolve` does not know how to strike, against a module docstring that promises
    # none. A crashed run still leaves one — that case is caught by --continue's
    # "the integration worktree is gone" refusal, which names --abort.
    if verdict in ("pass", "warn"):
        completed = {
            **st,
            "status": "gated",
            "completed_at": datetime.now(timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"),
            "head_sha": head,
        }
        manifest = _integrate_completed_path(spath, st["slug"], head)
        _integrate_save(manifest, completed)
        payload["manifest"] = str(manifest)
        spath.unlink(missing_ok=True)
    else:
        # A blocking verdict is not terminal. Keep both the source ownership and
        # resumable state so the coordinator can fix the integrated tree and run
        # only the gate again, or abort and release the sources deliberately.
        st["gate_pending"] = True
        _integrate_save(spath, st)
        payload["manifest"] = None
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
    persisted_independent = st.get("independent") is True
    requested_independent = bool(getattr(args, "independent", False))
    if persisted_independent != requested_independent:
        _emit({
            "schema": INTEGRATE_SCHEMA, "step": "integrate", "mode": "refused",
            "slug": args.slug, "state_file": str(spath),
            "error": "independent opt-in must match the persisted integration state",
            "persisted_independent": persisted_independent,
            "requested_independent": requested_independent,
        }, args.json,
            "✗ integrate --continue refused: repeat the original "
            "--independent opt-in exactly")
        return EXIT_USAGE
    independent_suffix = " --independent" if persisted_independent else ""
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

    # The process may have died after atomically saving the integration state but
    # before reserving its sources. Reacquire idempotently on every continuation;
    # if another integration claimed one in the gap, stop before touching git.
    source_claim = _integrate_claim_sources(args, st)
    if not source_claim["ok"]:
        _emit({
            "schema": INTEGRATE_SCHEMA, "step": "integrate", "mode": "refused",
            "slug": args.slug, "worktree": wt,
            "error": "source branches already belong to another integration",
            "source_claim": source_claim,
        }, args.json,
            "✗ integrate --continue refused: source ownership could not be "
            "recovered")
        return EXIT_BLOCK
    st["source_claim"] = source_claim
    _integrate_save(spath, st)

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
        if st.get("gate_pending") and not st.get("queue"):
            action = ("stop before the gate (the queue is already empty)"
                      if args.no_gate else
                      "run ONLY the gate on the already-integrated tree")
        else:
            action = ("stop before the gate" if args.no_gate
                      else "apply the remaining commits, then run ONE gate")
        _emit({"schema": INTEGRATE_SCHEMA, "step": "integrate", "mode": "dry-run",
               "slug": args.slug, "worktree": wt, "picked": st["picked"],
               "remaining": st["queue"], "stopped": st.get("stopped")}, args.json,
              f"# integrate --continue (dry-run)\n"
              f"  would conclude the stopped pick and apply {len(st['queue'])} "
              f"remaining commit(s), then {action}\n  (--commit to execute)")
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
                            f"cherry-pick --skip`), then re-run "
                            f"--continue{independent_suffix}; or "
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
    registry_state = (Path(args.state).resolve() if args.state
                      else wr.default_state_path())
    released = wr.release_integration_sources(
        registry_state, integration_branch=st["branch"])
    parent = st.get("parent")
    parent_released = None
    if isinstance(parent, dict):
        parent_released = wr.release_parent_integration(
            registry_state,
            campaign_id=str(parent.get("campaign_id") or ""),
            parent_branch=st["branch"], parent_slug=st.get("slug"),
        )
    spath.unlink(missing_ok=True)
    _emit({"schema": INTEGRATE_SCHEMA, "step": "integrate", "mode": "committed",
           "slug": args.slug, "worktree": wt, "aborted": op,
           "picked": st["picked"], "abandoned": st["queue"],
           "released_sources": released,
           "released_parent": parent_released,
           "worktree_removed": False, "next_step": teardown}, args.json,
          f"✓ integrate --abort: {op or 'nothing'} aborted, integration state "
          f"forgotten\n  worktree kept ({len(st['picked'])} picked commit(s)) — "
          f"tear it down with:\n    {teardown}")
    return EXIT_OK


# ---------------------------------------------------------------------------
# close-wave — the Delivery Team's bounded batch-closure coordinator
# ---------------------------------------------------------------------------

def _delivery_json_tool(
    script: Path,
    cwd: Path,
    argv: list[str],
    *,
    label: str,
    expected_schema: str | None = None,
    required_keys: tuple[str, ...] = (),
    receipt_validator: Callable[[dict[str, Any]], str | None] | None = None,
) -> tuple[int, dict[str, Any]]:
    """Run one existing orchestrator/registry verb and decode its JSON receipt.

    ``close-wave`` coordinates existing primitives; it does not reproduce their
    gate, containment, or registry judgement.  Keeping each child as a separate
    process also means its stderr heartbeat remains visible while stdout stays a
    single machine-readable payload for the coordinator.
    """
    command = [sys.executable, str(script), *argv]
    if "--json" not in command:
        command.append("--json")
    try:
        completed = run_streamed_command(
            command,
            cwd=cwd,
            label_key="delivery",
            label=label,
            progress_prefix="[delivery]",
            heartbeat_interval=20.0,
            # Registry ledgers are machine JSON, not human log tails.  The old
            # 256 KiB ceiling truncated a measured ~276 KiB receipt and made a
            # valid close-wave look like a malformed child.  Keep a finite bound
            # for runaway tools while leaving enough room for the complete ledger.
            capture_limit=8 * 1024 * 1024,
        )
    except OSError as exc:
        return 127, {"error": f"could not start {label}: {exc}"}
    except KeyboardInterrupt:
        return EXIT_BLOCK, {
            "error": f"{label} was interrupted; resumable state was left in place",
            "interrupted": True,
        }
    diagnostic = (completed.stderr or "").strip()
    if diagnostic:
        # The streaming runner keeps child stderr separate so the coordinator's
        # stdout remains one JSON document.  Relay it after completion as well:
        # otherwise a child can fail with useful evidence that is invisible to the
        # operator who is watching the parent process.
        print(diagnostic, file=sys.stderr, flush=True)
    raw = (completed.stdout or "").strip()
    child_rc = completed.returncode if completed.returncode is not None else EXIT_BLOCK
    if not raw:
        return child_rc or EXIT_BLOCK, {
            "error": f"{label} returned no JSON payload",
            "stderr": diagnostic[-4000:],
        }
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        return child_rc or EXIT_BLOCK, {
            "error": f"{label} returned invalid JSON: {exc}",
            "stdout_tail": raw[-4000:],
            "stderr": diagnostic[-4000:],
        }
    if not isinstance(payload, dict):
        return child_rc or EXIT_BLOCK, {
            "error": f"{label} returned JSON {type(payload).__name__}, expected object",
            "payload": payload,
        }
    if child_rc == EXIT_OK:
        contract_errors: list[str] = []
        if expected_schema and payload.get("schema") != expected_schema:
            contract_errors.append(
                f"schema {payload.get('schema')!r} != {expected_schema!r}"
            )
        missing = [key for key in required_keys if key not in payload]
        if missing:
            contract_errors.append("missing keys: " + ", ".join(missing))
        if receipt_validator is not None:
            semantic_error = receipt_validator(payload)
            if semantic_error:
                contract_errors.append(semantic_error)
        if contract_errors:
            return EXIT_BLOCK, {
                "error": f"{label} returned an invalid success receipt",
                "contract_errors": contract_errors,
                "receipt": payload,
            }
    return child_rc, payload


def _delivery_require_mode(payload: dict[str, Any], expected: str) -> str | None:
    actual = payload.get("mode")
    if actual != expected:
        return f"mode {actual!r} != {expected!r}"
    return None


def _delivery_require_integrate_picked(payload: dict[str, Any]) -> str | None:
    error = _delivery_require_mode(payload, "picked")
    if error:
        return error
    if payload.get("gate_pending") is not True:
        return "picked integration receipt does not set gate_pending=true"
    if payload.get("landed") is not False:
        return "picked integration receipt must set landed=false"
    if not isinstance(payload.get("head_sha"), str) or not payload["head_sha"]:
        return "picked integration receipt has no head_sha"
    return None


def _delivery_require_integrate_gated(payload: dict[str, Any]) -> str | None:
    error = _delivery_require_mode(payload, "committed")
    if error:
        return error
    if payload.get("landed") is not False:
        return "gated integration receipt must set landed=false"
    if payload.get("verdict") not in ("pass", "warn"):
        return (f"gated integration receipt has non-landable verdict "
                f"{payload.get('verdict')!r}")
    if not isinstance(payload.get("manifest"), str) or not payload["manifest"]:
        return "gated integration receipt has no manifest"
    if not isinstance(payload.get("runner_revision"), str) \
            or not payload["runner_revision"]:
        return "gated integration receipt has no runner_revision"
    if not isinstance(payload.get("integration_revision"), str) \
            or not payload["integration_revision"]:
        return "gated integration receipt has no integration_revision"
    return None


def _delivery_require_cutover_landed(payload: dict[str, Any]) -> str | None:
    error = _delivery_require_mode(payload, "committed")
    if error:
        return error
    if payload.get("landed") is not True:
        return "cutover success receipt must set landed=true"
    if not isinstance(payload.get("sha"), str) or not payload["sha"]:
        return "cutover success receipt has no landed sha"
    return None


def _delivery_require_resolved(payload: dict[str, Any]) -> str | None:
    error = _delivery_require_mode(payload, "committed")
    if error:
        return error
    if payload.get("resolved") != "merged":
        return (f"resolve success receipt has resolved={payload.get('resolved')!r}, "
                "expected 'merged'")
    if payload.get("failures") != 0:
        return f"resolve success receipt has failures={payload.get('failures')!r}"
    return None


def _delivery_require_anchor_receipt(payload: dict[str, Any]) -> str | None:
    error = _delivery_require_mode(payload, "commit")
    if error:
        return error
    problems = payload.get("problems")
    if not isinstance(problems, list):
        return "anchor receipt has non-list problems"
    if problems:
        return f"anchor receipt has {len(problems)} problem(s)"
    unstamped = payload.get("unstamped")
    if not isinstance(unstamped, list):
        return "anchor receipt has non-list unstamped"
    if unstamped:
        return (f"anchor receipt still has {len(unstamped)} selected closure(s) "
                "without a landed sha")
    applied = payload.get("applied")
    if not isinstance(applied, list) or any(
        not isinstance(ticket_id, str) for ticket_id in applied
    ):
        return "anchor receipt has malformed applied ids"
    return None


def _delivery_require_validate_receipt(payload: dict[str, Any]) -> str | None:
    problems = payload.get("problems")
    if not isinstance(problems, list):
        return "validate receipt has non-list problems"
    if problems:
        return f"validate receipt has {len(problems)} problem(s)"
    if payload.get("ok") is not True:
        return f"validate receipt has ok={payload.get('ok')!r}"
    return None


def _delivery_require_registry_receipt(payload: dict[str, Any]) -> str | None:
    records = payload.get("records")
    if not isinstance(records, list):
        return "registry receipt has non-list records"
    allowed_statuses = {wr.STATUS_ACTIVE, "merged", "abandoned"}
    required = ("path", "branch", "base", "status")
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            return f"registry record {index} is not an object"
        missing = [key for key in required if key not in record]
        if missing:
            return f"registry record {index} missing keys: {', '.join(missing)}"
        if any(not isinstance(record[key], str) or not record[key]
               for key in ("path", "branch", "base")):
            return f"registry record {index} has malformed path/branch/base"
        if not Path(record["path"]).is_absolute():
            return f"registry record {index} has a non-absolute path"
        if record["status"] not in allowed_statuses:
            return (f"registry record {index} has unknown status "
                    f"{record['status']!r}")
    return None


def _delivery_state_paths(args: argparse.Namespace) -> tuple[Path, list[Path]]:
    state_path = _integrate_state_path(args.state, args.slug)
    completed_dir = state_path.parent / "completed"
    manifests = sorted(
        completed_dir.glob(f"{args.slug}-*.json"),
        key=lambda path: path.stat().st_mtime_ns if path.exists() else 0,
        reverse=True,
    )
    return state_path, manifests


def _delivery_load_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _delivery_revision(path: Path) -> str | None:
    """Return the content revision of one orchestrator copy, fail-closed."""
    try:
        return sha256_file(path)
    except OSError:
        return None


def _delivery_revision_guard(
    runner_revision: str | None,
    integration_revision: str | None,
) -> str | None:
    """Require the runner and gated integration tree to use one tool revision."""
    if not isinstance(runner_revision, str) or not runner_revision:
        return "runner_revision is missing"
    if not isinstance(integration_revision, str) or not integration_revision:
        return "integration_revision is missing"
    if runner_revision != integration_revision:
        return "runner_revision does not match integration_revision"
    return None


def _delivery_common_dir(worktree: Path) -> str | None:
    rc, common = _git(
        ["rev-parse", "--path-format=absolute", "--git-common-dir"],
        cwd=worktree,
    )
    return _norm(common) if rc == EXIT_OK and common else None


def _delivery_integration_error(
    payload: Any,
    *,
    label: str,
    slug: str,
    base: str,
    branches: list[str],
    require_gated: bool,
    require_live_worktree: bool,
) -> str | None:
    """Validate a persisted integration receipt before using its identity.

    A resumable coordinator must not let a stale slug borrow another run's state,
    branch, base, or worktree.  This is deliberately a schema/identity check rather
    than a best-effort ``dict.get`` chain: malformed local state is a blocked receipt,
    never an invitation to start a fresh integration with the same name.
    """
    if not isinstance(payload, dict):
        return f"{label} is not a JSON object"
    if payload.get("schema") != INTEGRATE_SCHEMA:
        return (f"{label} has schema {payload.get('schema')!r}, expected "
                f"{INTEGRATE_SCHEMA!r}")
    if payload.get("slug") != slug:
        return f"{label} belongs to slug {payload.get('slug')!r}, not {slug!r}"
    stored_base = payload.get("base")
    stored_base_is_identity = (
        isinstance(stored_base, str)
        and re.fullmatch(r"[0-9a-fA-F]{7,64}", stored_base) is not None
    )
    if (stored_base != base
            and _local_trunk(str(stored_base or "")) != _local_trunk(base)
            and not stored_base_is_identity):
        return (f"{label} was created with base {payload.get('base')!r}, not "
                f"{base!r}")
    stored_branches = payload.get("branches")
    if not isinstance(stored_branches, list) or any(
        not isinstance(branch, str) for branch in stored_branches
    ):
        return f"{label} has malformed branches"
    if stored_branches != branches:
        return (f"{label} branch list {stored_branches!r} does not match "
                f"{branches!r}")
    if not isinstance(payload.get("worktree"), str) or not payload["worktree"]:
        return f"{label} has no worktree identity"
    if not isinstance(payload.get("branch"), str) or not payload["branch"]:
        return f"{label} has no integration branch identity"
    if require_gated and payload.get("status") != "gated":
        return (f"{label} status is {payload.get('status')!r}, expected 'gated' "
                "before close-wave cutover")
    worktree = Path(payload["worktree"])
    if not worktree.is_absolute():
        return f"{label} worktree path is not absolute: {worktree}"
    if worktree.exists():
        # A path can be a perfectly valid foreign checkout (or merely a directory
        # inside this repository). `_current_branch` alone is unsafe because git
        # discovery walks upward after a linked worktree's `.git` file disappears.
        # Require both the repository's worktree registry identity and the shared
        # git-common-dir before executing any persisted child command.
        entry = _worktree_entry(str(worktree))
        if entry is None:
            return (f"{label} worktree is not a linked worktree of this repository: "
                    f"{worktree}")
        if _norm(str(entry.get("path") or "")) != _norm(str(worktree)):
            return f"{label} worktree registry path disagrees: {worktree}"
        if entry.get("branch") != payload["branch"]:
            return (f"{label} worktree registry branch is {entry.get('branch')!r}, "
                    f"expected {payload['branch']!r}")
        actual_branch = _current_branch(str(worktree))
        if actual_branch != payload["branch"]:
            return (f"{label} worktree is on {actual_branch!r}, expected "
                    f"{payload['branch']!r}")
        primary_common = _delivery_common_dir(primary_root())
        worktree_common = _delivery_common_dir(worktree)
        if primary_common is None or worktree_common is None:
            return (f"{label} cannot verify git-common-dir containment for "
                    f"{worktree}")
        if worktree_common != primary_common:
            return (f"{label} worktree belongs to a different repository "
                    f"(common-dir {worktree_common!r}, expected {primary_common!r})")
    elif require_live_worktree:
        return f"{label} worktree is missing: {worktree}"
    return None


def _delivery_state_error(
    *,
    args: argparse.Namespace,
    state_path: Path,
    manifest_path: Path | None,
    error: str,
    mode: str = "stopped",
) -> int:
    _emit({
        "schema": DELIVERY_SCHEMA,
        "step": "close-wave",
        "mode": mode,
        "slug": args.slug,
        "state_file": str(state_path) if state_path.exists() else None,
        "manifest": str(manifest_path) if manifest_path and manifest_path.exists() else None,
        "error": error,
        "next": "inspect the named state/manifest; do not delete it blindly",
    }, args.json, f"✗ close-wave refused: {error}")
    return EXIT_BLOCK


def _delivery_registry_records(
    args: argparse.Namespace, *, primary: Path | None = None
) -> tuple[int, list[dict[str, Any]]]:
    # Run the registry implementation that belongs to this coordinator.  During
    # the first delivery-loop round the coordinator can still be in an isolated
    # worktree while primary is on the previous tool version; using primary's
    # copy here would make the new close-wave protocol self-incompatible.
    repo = primary or primary_root()
    registry_script = (
        repo / "ops" / "worktree_registry.py"
        if primary is not None
        else Path(__file__).resolve().parent / "worktree_registry.py"
    )
    # `list` defaults to a human table.  The coordinator consumes the typed JSON
    # receipt; make that contract explicit instead of relying on a downstream
    # helper to append a flag after an already-built argv snapshot.
    argv = ["list", "--json"]
    if args.state:
        argv += ["--state", args.state]
    rc, payload = _delivery_json_tool(
        registry_script, repo, argv, label="registry-list",
        expected_schema="kg.worktree.registry.v1", required_keys=("records",),
        receipt_validator=_delivery_require_registry_receipt,
    )
    records = payload.get("records")
    if rc != EXIT_OK or not isinstance(records, list):
        return rc or EXIT_BLOCK, []
    semantic_error = _delivery_require_registry_receipt(payload)
    if semantic_error:
        return EXIT_BLOCK, []
    return EXIT_OK, records


def _delivery_expected_ticket_ids(
    records: list[dict[str, Any]], branches: list[str],
    *, statuses: set[str] | None = None,
    staged_ids: Iterable[str] | None = None,
) -> list[str]:
    """Derive the ticket set a named wave owes from its source reservations.

    The registry is the ownership SoT.  Reading only the explicitly named source
    branches prevents a foreign Team's active work from entering this closure, while
    the optional ``statuses`` argument lets a completed-wave recovery read the same
    reservations after ``resolve`` has marked them merged.
    """
    allowed_branches = set(branches)
    allowed_statuses = statuses or {wr.STATUS_ACTIVE}
    ticket_ids: set[str] = set()
    for record in records:
        if (record.get("status") not in allowed_statuses
                or record.get("branch") not in allowed_branches):
            continue
        backlog = record.get("backlog")
        if not isinstance(backlog, list):
            continue
        ticket_ids.update(
            ticket_id for ticket_id in backlog
            if isinstance(ticket_id, str) and ticket_id
        )
    ticket_ids.update(
        ticket_id for ticket_id in (staged_ids or ())
        if isinstance(ticket_id, str) and ticket_id
    )
    return sorted(ticket_ids)


def _delivery_staged_ticket_ids(
    primary: Path, branches: Iterable[str],
) -> list[str]:
    """Return staged closure ids owned by the explicitly named source branches.

    A stacked hand-back can be resolved before the wave resumes, so registry
    ``backlog`` lists are no longer a complete closure ledger.  The gitignored
    anchor queue is the durable per-machine evidence for those staged rows; it is
    merged only for named branches, preserving the foreign-team boundary.
    """
    allowed = {branch for branch in branches if isinstance(branch, str)}
    return sorted({
        row.get("id") for row in _read_anchor_queue(primary)
        if isinstance(row, dict)
        and row.get("branch") in allowed
        and isinstance(row.get("id"), str)
        and row.get("id")
    })


def _delivery_expected_ticket_set(
    primary: Path,
    records: list[dict[str, Any]],
    branches: list[str],
    *,
    saved_expected: Iterable[str] | None = None,
) -> list[str]:
    """Union persisted, registry, and staged ids without widening the wave."""
    ids = _delivery_expected_ticket_ids(
        records,
        branches,
        statuses={wr.STATUS_ACTIVE, "merged"},
        staged_ids=_delivery_staged_ticket_ids(primary, branches),
    )
    ids.extend(
        ticket_id for ticket_id in (saved_expected or ())
        if isinstance(ticket_id, str) and ticket_id
    )
    return sorted(set(ids))


def _delivery_expected_ticket_reservation_errors(
    records: list[dict[str, Any]], branches: list[str],
    *, statuses: set[str] | None = None,
) -> list[dict[str, str]]:
    """Fail closed when a named source reservation cannot expose its tickets."""
    allowed_branches = set(branches)
    allowed_statuses = statuses or {wr.STATUS_ACTIVE}
    errors: list[dict[str, str]] = []
    for record in records:
        if (record.get("status") not in allowed_statuses
                or record.get("branch") not in allowed_branches):
            continue
        backlog = record.get("backlog")
        if (not isinstance(backlog, list)
                or any(not isinstance(ticket_id, str) or not ticket_id
                       for ticket_id in backlog)):
            errors.append({
                "branch": str(record.get("branch")),
                "reason": "backlog must be a list of non-empty ticket ids",
            })
    return errors


def _delivery_expected_ticket_closure(
    primary: Path, expected_ticket_ids: list[str],
) -> dict[str, Any]:
    """Machine-check the exact ticket set before close-wave can report success."""
    expected = sorted(set(expected_ticket_ids))
    if not expected:
        return {
            "ok": False,
            "expected_ticket_ids": [],
            "failures": [{"reason": "expected ticket set is empty"}],
        }

    failures: list[dict[str, str]] = []
    for ticket_id in expected:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", ticket_id):
            failures.append({"id": ticket_id, "reason": "ticket id is malformed"})
            continue
        path = primary / "docs" / "runbook" / "backlog" / f"{ticket_id}.json"
        payload = _delivery_load_json(path)
        if payload is None:
            failures.append({"id": ticket_id, "reason": "entry is missing or unreadable"})
            continue
        if payload.get("status") != "fixed":
            failures.append({
                "id": ticket_id,
                "reason": f"status is {payload.get('status')!r}",
            })
            continue
        if payload.get("verdict") != "CONFIRMED-FIXED":
            failures.append({
                "id": ticket_id,
                "reason": f"verdict is {payload.get('verdict')!r}",
            })
            continue
        fixed_by = payload.get("fixed_by")
        if not isinstance(fixed_by, list) or not fixed_by:
            failures.append({"id": ticket_id, "reason": "fixed_by is empty"})
        elif any(
            not isinstance(sha, str) or not sha.strip() for sha in fixed_by
        ):
            failures.append({
                "id": ticket_id,
                "reason": "fixed_by contains an empty sha",
            })

    return {
        "ok": not failures,
        "expected_ticket_ids": expected,
        "failures": failures,
    }


def _delivery_independent_no_ticket_provenance(
    *,
    state: dict[str, Any] | None,
    manifest: dict[str, Any] | None,
    integration_record: dict[str, Any] | None,
    current_head: str,
    primary_dirty: list[str],
    queue: list[Any],
) -> dict[str, Any]:
    """Prove an explicit no-ticket close-wave opt-in without weakening defaults.

    The opt-in is deliberately recorded in three planes: integration state and
    completed manifest carry ``independent=true`` while the registry's existing
    intent field carries the typed ``independent-no-ticket:`` marker.  The Gate
    receipt must name the exact integrated HEAD and be non-blocking; primary and
    the integration queue must be clean.  This keeps an empty expected-ticket set
    auditable without adding a second registry schema or allowing a stale manifest
    to masquerade as an independent wave.
    """
    failures: list[dict[str, Any]] = []
    state_independent = (
        state.get("independent") is True if isinstance(state, dict) else
        manifest.get("independent") is True if isinstance(manifest, dict) else False
    )
    if not state_independent:
        failures.append({"reason": "integration state is not explicitly independent"})
    if not isinstance(manifest, dict) or manifest.get("independent") is not True:
        failures.append({"reason": "completed manifest is not explicitly independent"})
    if not isinstance(integration_record, dict):
        failures.append({"reason": "integration registry record is missing"})
    else:
        intent = integration_record.get("intent")
        if not isinstance(intent, str) or not intent.startswith(
                _INDEPENDENT_NO_TICKET_INTENT
        ):
            failures.append({
                "reason": "integration registry intent lacks independent-no-ticket marker",
            })
    gate = ((manifest or {}).get("gate") if isinstance(manifest, dict) else None)
    if not isinstance(gate, dict) and isinstance(state, dict):
        gate = state.get("gate")
    if not isinstance(gate, dict):
        failures.append({"reason": "independent wave has no Gate receipt"})
    else:
        if gate.get("verdict") not in {"pass", "warn"}:
            failures.append({
                "reason": "independent wave Gate is not non-block",
                "verdict": gate.get("verdict"),
            })
        if gate.get("head_sha") != current_head:
            failures.append({
                "reason": "independent wave Gate HEAD differs from current integration HEAD",
                "gate_head": gate.get("head_sha"), "current_head": current_head,
            })
    if isinstance(manifest, dict) and manifest.get("head_sha") != current_head:
        failures.append({
            "reason": "independent manifest HEAD differs from current integration HEAD",
            "manifest_head": manifest.get("head_sha"), "current_head": current_head,
        })
    if primary_dirty:
        failures.append({"reason": "primary is dirty", "dirty_files": primary_dirty})
    if queue:
        failures.append({"reason": "integration queue is not empty", "queue": queue})
    return {
        "ok": not failures,
        "mode": "independent-no-ticket",
        "failures": failures,
        "registry_marker": _INDEPENDENT_NO_TICKET_INTENT,
        "gate_head": gate.get("head_sha") if isinstance(gate, dict) else None,
        "current_head": current_head,
    }


def _delivery_saved_expected_ticket_ids(
    manifest: dict[str, Any] | None,
) -> list[str] | None:
    """Read a persisted expected set, distinguishing absent from malformed."""
    if not isinstance(manifest, dict):
        return None
    marker = manifest.get("close_wave")
    if not isinstance(marker, dict) or "expected_ticket_ids" not in marker:
        return None
    raw = marker.get("expected_ticket_ids")
    if not isinstance(raw, list) or any(
        not isinstance(ticket_id, str) or not ticket_id for ticket_id in raw
    ):
        return []
    return sorted(set(raw))


def _delivery_foreign_active(
    records: list[dict[str, Any]], allowed_branches: set[str]
) -> list[dict[str, Any]]:
    """Return active records outside the explicitly named wave boundary."""
    return [
        {
            "branch": record.get("branch"),
            "path": record.get("path"),
            "intent": record.get("intent"),
            "handed_back_sha": record.get("handed_back_sha"),
        }
        for record in records
        if record.get("status") == wr.STATUS_ACTIVE
        and record.get("branch") not in allowed_branches
    ]


def _delivery_primary_dirty(primary: Path) -> list[str]:
    rc, output = _git(["status", "--porcelain", "--untracked-files=all"], cwd=primary)
    if rc != 0:
        return [f"git status failed: {output}"]
    return [line for line in output.splitlines() if line.strip()]


_DELIVERY_ANCHOR_SUBJECT = "ops: anchor delivered backlog wave"


def _delivery_anchor_identity(
    primary: Path,
    expected_paths: set[str],
    *,
    base_sha: str | None,
    expected_sha: str | None = None,
) -> str | None:
    """Return the exact already-landed anchor commit, or None.

    The close-wave manifest is written before the anchor commit. If the process dies
    after ``git commit`` and before the manifest flips ``anchor_committed``, a retry
    must identify that one commit by parent, subject and changed paths. A
    bare "primary is clean" check is not enough: it could silently bless an unrelated
    clean commit made by another actor.
    """
    tip_rc, tip = _git(["rev-parse", "HEAD"], cwd=primary)
    if tip_rc != EXIT_OK or not tip:
        return None
    if expected_sha and tip != expected_sha:
        return None
    parents_rc, parents = _git(["rev-list", "--parents", "-n", "1", "HEAD"], cwd=primary)
    parent_tokens = parents.split()
    if parents_rc != EXIT_OK or len(parent_tokens) != 2:
        return None
    if base_sha and parent_tokens[1] != base_sha:
        return None
    subject_rc, subject = _git(["show", "-s", "--format=%s", "HEAD"], cwd=primary)
    if subject_rc != EXIT_OK or subject != _DELIVERY_ANCHOR_SUBJECT:
        return None
    paths_rc, changed = _git(
        ["diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD"], cwd=primary
    )
    if paths_rc != EXIT_OK:
        return None
    if {line for line in changed.splitlines() if line} != expected_paths:
        return None
    return tip


def _delivery_anchor_history_identity(
    primary: Path,
    expected_paths: set[str],
    *,
    base_sha: str | None,
    expected_sha: str | None = None,
) -> str | None:
    """Find a machine-repair anchor commit already contained in ``HEAD``.

    ``_delivery_anchor_identity`` intentionally requires the anchor to be the
    current tip.  Recovery is slightly wider: an unrelated primary advance may
    follow a committed anchor before the manifest receipt is flushed.  The
    commit is still accepted only when its parent, subject, and exact
    changed paths prove it is this wave's anchor.
    """
    if expected_sha:
        candidates = [expected_sha]
    else:
        rc, output = _git(["rev-list", "HEAD"], cwd=primary)
        if rc != EXIT_OK:
            return None
        candidates = [sha for sha in output.splitlines() if sha]
    for candidate in candidates:
        ancestor_rc, _ = _git(
            ["merge-base", "--is-ancestor", candidate, "HEAD"], cwd=primary
        )
        if ancestor_rc != 0:
            continue
        parents_rc, parents = _git(
            ["rev-list", "--parents", "-n", "1", candidate], cwd=primary
        )
        parent_tokens = parents.split()
        if parents_rc != EXIT_OK or len(parent_tokens) != 2:
            continue
        if base_sha and parent_tokens[1] != base_sha:
            continue
        subject_rc, subject = _git(
            ["show", "-s", "--format=%s", candidate], cwd=primary
        )
        if subject_rc != EXIT_OK or subject != _DELIVERY_ANCHOR_SUBJECT:
            continue
        paths_rc, changed = _git(
            ["diff-tree", "--no-commit-id", "--name-only", "-r", candidate],
            cwd=primary,
        )
        if paths_rc == EXIT_OK and {
            line for line in changed.splitlines() if line
        } == expected_paths:
            return candidate
    return None


def _delivery_anchor_recovery_is_safe(
    primary: Path, marker: dict[str, Any],
) -> bool:
    """Whether an interrupted anchor can be rebased onto the current primary.

    This path is deliberately narrow: the persisted phase must say that anchor
    started, no ticket may have been applied, and every expected ticket must
    still be present in the staged queue.  Anything less remains a typed guard
    refusal rather than an optimistic retry that could overwrite another wave.
    """
    phases = marker.get("phases")
    anchor_phase = phases.get("anchor") if isinstance(phases, dict) else None
    if not isinstance(anchor_phase, dict):
        return False
    if anchor_phase.get("status") not in {"started", "blocked"}:
        return False
    applied = anchor_phase.get("applied_ticket_ids", marker.get("anchor_ids", []))
    if not isinstance(applied, list) or applied:
        return False
    expected = anchor_phase.get(
        "expected_ticket_ids", marker.get("expected_ticket_ids", [])
    )
    if (not isinstance(expected, list) or not expected
            or any(not isinstance(ticket_id, str) or not ticket_id
                   for ticket_id in expected)):
        return False
    queued = {
        row.get("id") for row in _read_anchor_queue(primary)
        if isinstance(row, dict) and isinstance(row.get("id"), str)
    }
    return set(expected).issubset(queued)


def _delivery_anchor_noop_recovery_is_safe(
    primary: Path,
    marker: dict[str, Any],
    *,
    stored_base: str,
    current_head: str,
) -> bool:
    """Prove that a completed noop can survive a metadata-only primary advance.

    A noop has no anchor commit to rediscover.  Recovery is therefore allowed
    only when its durable receipt proves that the queue was consumed without
    applying tickets, the current tip descends from the recorded base, and the
    intervening commits touched backlog metadata documents only.  This keeps
    the exact-commit and foreign-path refusals for real anchors intact while
    avoiding a fabricated ``anchor_commit_sha`` for a legitimate noop.
    """
    if marker.get("anchor_noop") is not True:
        return False
    if marker.get("anchor_committed") is not False:
        return False
    if marker.get("anchor_commit_sha") is not None:
        return False
    phases = marker.get("phases")
    anchor_phase = phases.get("anchor") if isinstance(phases, dict) else None
    if not isinstance(anchor_phase, dict) or anchor_phase.get("status") != "completed":
        return False
    applied = anchor_phase.get("applied_ticket_ids", marker.get("anchor_ids", []))
    if not isinstance(applied, list) or applied:
        return False
    if anchor_phase.get("queue_state") != "consumed":
        return False
    receipt = anchor_phase.get("acceptance_receipt")
    if not isinstance(receipt, dict) or receipt.get("schema") != "kg.backlog.anchor.v1":
        return False
    if receipt.get("applied") != [] or receipt.get("problems") != []:
        return False
    expected = marker.get("expected_ticket_ids", [])
    if not isinstance(expected, list) or any(
        not isinstance(ticket_id, str)
        or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", ticket_id)
        for ticket_id in expected
    ):
        return False
    if _read_anchor_queue(primary):
        return False
    ancestor_rc, _ = _git(
        ["merge-base", "--is-ancestor", stored_base, current_head], cwd=primary,
    )
    if ancestor_rc != EXIT_OK:
        return False
    changed_rc, changed = _git(
        ["diff", "--name-only", "--no-renames", stored_base, current_head],
        cwd=primary,
    )
    if changed_rc != EXIT_OK:
        return False
    changed_paths = {path for path in changed.splitlines() if path}
    if not changed_paths:
        return False
    def is_legal_metadata_path(path: str) -> bool:
        if path == "ops/backlog_closed_unverified_baseline.txt":
            return True
        if not (path.startswith("docs/runbook/backlog/")
                and path.endswith(".json")):
            return False
        return "/" not in path[len("docs/runbook/backlog/"):]

    return all(is_legal_metadata_path(path) for path in changed_paths)


def _delivery_anchor_recovery_dirty_allowed(
    primary: Path, manifest_path: Path | None,
) -> bool:
    """Allow only expected backlog documents to survive a partial anchor crash."""
    if manifest_path is None:
        return False
    marker_payload = _delivery_load_json(manifest_path)
    marker = (marker_payload or {}).get("close_wave") if marker_payload else None
    if not isinstance(marker, dict) or not _delivery_anchor_recovery_is_safe(
            primary, marker
    ):
        # A partial anchor may have written the documents before consuming the
        # queue, so the queue proof is intentionally not required here.  The
        # phase/applied proof still must say that nothing was durably consumed.
        phases = marker.get("phases") if isinstance(marker, dict) else None
        anchor_phase = phases.get("anchor") if isinstance(phases, dict) else None
        if not isinstance(anchor_phase, dict) or anchor_phase.get("status") not in {
                "started", "blocked"}:
            return False
        applied = anchor_phase.get("applied_ticket_ids", marker.get("anchor_ids", []))
        if not isinstance(applied, list) or applied:
            return False
    expected = marker.get("expected_ticket_ids", [])
    if not isinstance(expected, list) or any(
        not isinstance(ticket_id, str) or not ticket_id for ticket_id in expected
    ):
        return False
    expected_paths = {
        f"docs/runbook/backlog/{ticket_id}.json" for ticket_id in expected
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", ticket_id)
    }
    if len(expected_paths) != len(expected):
        return False
    dirty = _delivery_primary_dirty(primary)
    paths = set(_porcelain_paths("\n".join(dirty)))
    return bool(paths) and paths.issubset(expected_paths)


def _delivery_anchor_commit(
    primary: Path,
    *,
    applied_ids: list[str],
    already_committed: bool = False,
    anchor_base_sha: str | None = None,
    already_committed_sha: str | None = None,
) -> tuple[int, dict[str, Any]]:
    """Commit only the closure rows materialized by ``anchor``.

    ``backlog.py anchor`` intentionally writes data but does not invent a git
    commit.  The coordinator is the owner of the wave's one metadata commit.  The
    path check is the safety boundary: a concurrent edit in primary must never be
    swept into this automatic commit.
    """
    expected_paths: set[str] = set()
    for ticket_id in applied_ids:
        if not isinstance(ticket_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", ticket_id):
            return EXIT_BLOCK, {
                "error": "anchor receipt contains an unsafe ticket id",
                "ticket_id": ticket_id,
            }
        expected_paths.add(f"docs/runbook/backlog/{ticket_id}.json")

    rc, changed = _git(["diff", "--name-only", "HEAD", "--"], cwd=primary)
    if rc != EXIT_OK:
        return EXIT_BLOCK, {"error": f"cannot inspect anchor diff: {changed}"}
    untracked_rc, untracked = _git(
        ["ls-files", "--others", "--exclude-standard", "--"], cwd=primary
    )
    if untracked_rc != EXIT_OK:
        return EXIT_BLOCK, {"error": f"cannot inspect untracked files: {untracked}"}
    paths = {
        line for line in (changed + "\n" + untracked).splitlines() if line
    }
    if not paths and expected_paths and already_committed:
        recovered_sha = _delivery_anchor_identity(
            primary, expected_paths, base_sha=anchor_base_sha,
            expected_sha=already_committed_sha,
        )
        if recovered_sha is None:
            recovered_sha = _delivery_anchor_history_identity(
                primary, expected_paths, base_sha=anchor_base_sha,
                expected_sha=already_committed_sha,
            )
        if recovered_sha is None:
            return EXIT_BLOCK, {
                "error": "anchor manifest claimed a committed anchor, but primary "
                         "does not contain that exact commit",
                "expected_sha": already_committed_sha,
                "anchor_base_sha": anchor_base_sha,
                "expected_paths": sorted(expected_paths),
                "paths": [],
            }
        return EXIT_OK, {
            "committed": False,
            "already_committed": True,
            "recovered": False,
            "paths": [],
            "sha": recovered_sha,
        }
    if not paths and expected_paths:
        recovered_sha = _delivery_anchor_identity(
            primary, expected_paths, base_sha=anchor_base_sha,
        )
        if recovered_sha is None and already_committed_sha:
            recovered_sha = _delivery_anchor_history_identity(
                primary, expected_paths, base_sha=anchor_base_sha,
                expected_sha=already_committed_sha,
            )
        if recovered_sha is not None:
            return EXIT_OK, {
                "committed": False,
                "already_committed": True,
                "recovered": True,
                "paths": [],
                "sha": recovered_sha,
            }
        return EXIT_BLOCK, {
            "error": "anchor receipt declared applied tickets but primary has no changes",
            "missing_paths": sorted(expected_paths),
            "paths": [],
        }
    if not paths:
        return EXIT_OK, {"committed": False, "noop": True, "paths": []}
    outside = sorted(paths - expected_paths)
    missing = sorted(expected_paths - paths)
    if outside or missing:
        return EXIT_BLOCK, {
            "error": "primary changed paths do not exactly match the anchor receipt; "
                     "refusing to commit another session's work",
            "outside_paths": outside,
            "missing_paths": missing,
            "paths": sorted(paths),
            "expected_paths": sorted(expected_paths),
        }
    add_rc, add_output = _git_mutation(
        ["add", "--", *sorted(expected_paths)],
        cwd=primary,
        label="delivery-anchor-stage",
    )
    if add_rc != EXIT_OK:
        return EXIT_BLOCK, {"error": f"could not stage anchor output: {add_output}"}
    commit_rc, commit_output = _git_mutation(
        [
            "commit",
            "-m",
            _DELIVERY_ANCHOR_SUBJECT,
        ],
        cwd=primary,
        label="delivery-anchor-commit",
    )
    if commit_rc != EXIT_OK:
        return EXIT_BLOCK, {
            "error": f"could not commit anchor output: {commit_output}",
            "paths": sorted(paths),
        }
    tip_rc, tip = _git(["rev-parse", "HEAD"], cwd=primary)
    return (EXIT_OK if tip_rc == EXIT_OK else EXIT_BLOCK), {
        "committed": True,
        "paths": sorted(paths),
        "sha": tip if tip_rc == EXIT_OK else None,
        "output": commit_output[-2000:],
    }


def _delivery_anchor_and_commit(
    args: argparse.Namespace, primary: Path, allowed: set[str], slug: str,
    manifest_path: Path | None,
) -> tuple[int, list[dict[str, Any]]]:
    """Linearize the primary-side anchor and its exact-path metadata commit."""
    steps: list[dict[str, Any]] = []
    with _main_advance_lock(primary):
        dirty_recovery_allowed = _delivery_anchor_recovery_dirty_allowed(
            primary, manifest_path,
        )
        ff_refusal = _primary_ff_ready(
            primary,
            _delivery_operation_base(getattr(args, "base", "main")),
            branch=f"close-wave:{slug}",
            worktree=str(primary),
            allow_dirty=dirty_recovery_allowed,
        )
        if ff_refusal is not None:
            reason, extra = ff_refusal
            steps.append({"name": "anchor-guard", "error": reason, **extra})
            return EXIT_BLOCK, steps
        dirty = _delivery_primary_dirty(primary)
        if dirty and not dirty_recovery_allowed:
            steps.append({
                "name": "anchor-guard",
                "error": "primary became dirty before anchor",
                "dirty_files": dirty,
            })
            return EXIT_BLOCK, steps
        rrc, records = _delivery_registry_records(args, primary=primary)
        if rrc != EXIT_OK:
            steps.append({"name": "anchor-guard", "rc": rrc,
                          "error": "could not read the worktree registry"})
            return EXIT_BLOCK, steps
        # Other Delivery Teams may still have active child/integration worktrees.
        # The finalization lock serializes their primary side effects, while this
        # wave only resolves the explicit branches in `allowed` below.

        persisted: dict[str, Any] | None = None
        marker: dict[str, Any] = {}
        saved_ids: list[str] = []
        already_committed = False
        already_committed_sha: str | None = None
        anchor_base_sha_rc, current_head = _git(["rev-parse", "HEAD"], cwd=primary)
        if anchor_base_sha_rc != EXIT_OK or not current_head:
            steps.append({"name": "anchor-guard",
                          "error": "could not capture primary HEAD before anchor"})
            return EXIT_BLOCK, steps
        anchor_base_sha = current_head
        if manifest_path is not None:
            persisted = _delivery_load_json(manifest_path)
            if persisted is None:
                steps.append({"name": "anchor-guard",
                              "error": "integration manifest disappeared before anchor receipt was saved"})
                return EXIT_BLOCK, steps
            raw_marker = persisted.get("close_wave")
            if raw_marker is not None and not isinstance(raw_marker, dict):
                steps.append({"name": "anchor-guard",
                              "error": "integration manifest has malformed close_wave marker"})
                return EXIT_BLOCK, steps
            marker = dict(raw_marker or {})
            stored_base = marker.get("anchor_base_sha")
            if stored_base is not None:
                if not isinstance(stored_base, str) or not stored_base:
                    steps.append({"name": "anchor-guard",
                                  "error": "integration manifest has malformed anchor_base_sha"})
                    return EXIT_BLOCK, steps
                anchor_base_sha = stored_base
            raw_ids = marker.get("anchor_ids")
            if raw_ids is not None:
                if not isinstance(raw_ids, list) or any(
                    not isinstance(ticket_id, str) for ticket_id in raw_ids
                ):
                    steps.append({"name": "anchor-guard",
                                  "error": "integration manifest has malformed anchor_ids"})
                    return EXIT_BLOCK, steps
                saved_ids = list(raw_ids)
            already_committed = marker.get("anchor_committed") is True
            if (stored_base is not None and stored_base != current_head
                    and not already_committed):
                phase_marker = marker.get("phases")
                anchor_phase = (phase_marker.get("anchor")
                                if isinstance(phase_marker, dict) else None)
                recovery_ids = list(saved_ids)
                if (not recovery_ids and isinstance(anchor_phase, dict)):
                    phase_ids = anchor_phase.get("applied_ticket_ids")
                    if ("applied_ticket_ids" in anchor_phase
                            and (not isinstance(phase_ids, list)
                                 or any(not isinstance(ticket_id, str)
                                        for ticket_id in phase_ids))):
                        steps.append({
                            "name": "anchor-guard",
                            "error": "integration manifest has malformed recovery ticket ids",
                            "field": "phases.anchor.applied_ticket_ids",
                        })
                        return EXIT_BLOCK, steps
                    if isinstance(phase_ids, list) and phase_ids:
                        recovery_ids = list(phase_ids)
                    elif anchor_phase.get("status") in {"started", "blocked"}:
                        expected_ids = marker.get("expected_ticket_ids", [])
                        if (not isinstance(expected_ids, list)
                                or any(not isinstance(ticket_id, str)
                                       for ticket_id in expected_ids)):
                            steps.append({
                                "name": "anchor-guard",
                                "error": "integration manifest has malformed recovery ticket ids",
                                "field": "close_wave.expected_ticket_ids",
                            })
                            return EXIT_BLOCK, steps
                        recovery_ids = list(expected_ids)
                if any(not isinstance(ticket_id, str) for ticket_id in recovery_ids):
                    steps.append({
                        "name": "anchor-guard",
                        "error": "integration manifest has malformed recovery ticket ids",
                        "field": "close_wave.recovery_ids",
                    })
                    return EXIT_BLOCK, steps
                recovery_paths = {
                    f"docs/runbook/backlog/{ticket_id}.json"
                    for ticket_id in recovery_ids
                    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", ticket_id)
                }
                recovered_sha = (
                    _delivery_anchor_history_identity(
                        primary, recovery_paths, base_sha=stored_base,
                    ) if recovery_paths else None
                )
                if recovered_sha is not None:
                    saved_ids = recovery_ids
                    already_committed_sha = recovered_sha
                elif (
                    _delivery_anchor_noop_recovery_is_safe(
                        primary, marker, stored_base=stored_base,
                        current_head=current_head,
                    )
                    or _delivery_anchor_recovery_is_safe(primary, marker)
                    or dirty_recovery_allowed
                ):
                    # The old anchor phase is durable, but its queue rows prove
                    # that no metadata was consumed.  For a completed noop,
                    # the metadata-only descendant proof above is the durable
                    # identity; for an interrupted real anchor the queue proof
                    # remains the identity. Rebase idempotently either way.
                    anchor_base_sha = current_head
                else:
                    steps.append({
                        "name": "anchor-guard",
                        "error": "primary moved after the persisted anchor base and "
                                 "does not contain the exact recoverable anchor commit",
                        "anchor_base_sha": stored_base,
                        "current_head": current_head,
                    })
                    return EXIT_BLOCK, steps
            raw_commit_sha = marker.get("anchor_commit_sha")
            if raw_commit_sha is not None:
                if not isinstance(raw_commit_sha, str) or not raw_commit_sha:
                    steps.append({"name": "anchor-guard",
                                  "error": "integration manifest has malformed anchor_commit_sha"})
                    return EXIT_BLOCK, steps
                already_committed_sha = raw_commit_sha
            if already_committed and already_committed_sha is None:
                steps.append({"name": "anchor-guard",
                              "error": "committed anchor marker has no anchor_commit_sha"})
                return EXIT_BLOCK, steps
            marker = _delivery_update_phase_marker(
                marker, "anchor", status="started",
                operation_base=anchor_base_sha, landed_sha=current_head,
                expected_ticket_ids=marker.get("expected_ticket_ids", []),
                applied_ticket_ids=saved_ids, queue_state="pending",
            )
            persisted["close_wave"] = {
                **marker,
                "anchor_base_sha": anchor_base_sha,
                "anchor_ids": saved_ids,
                "anchor_committed": already_committed,
            }
            try:
                _integrate_save(manifest_path, persisted)
            except OSError as exc:
                steps.append({"name": "anchor-guard",
                              "error": f"could not persist anchor base before anchor: {exc}"})
                return EXIT_BLOCK, steps

        anchor_rc, anchor_payload = _delivery_json_tool(
            primary / "ops" / "backlog.py",
            primary,
            [
                "anchor", "--store", str(primary / "docs" / "runbook" / "backlog"),
                "--queue", str(_anchor_queue(primary)),
                "--branches", *sorted(allowed), "--commit",
            ],
            label=f"anchor:{slug}",
            expected_schema="kg.backlog.anchor.v1",
            required_keys=("applied", "problems"),
            receipt_validator=_delivery_require_anchor_receipt,
        )
        steps.append({"name": "anchor", "rc": anchor_rc, "payload": anchor_payload})
        applied = anchor_payload.get("applied")
        if anchor_rc != EXIT_OK or anchor_payload.get("problems"):
            return anchor_rc or EXIT_BLOCK, steps
        if not isinstance(applied, list) or any(
            not isinstance(ticket_id, str) for ticket_id in applied
        ):
            steps.append({"name": "anchor-guard",
                          "error": "anchor receipt has malformed applied ids"})
            return EXIT_BLOCK, steps
        if saved_ids and applied and list(applied) != saved_ids:
            steps.append({"name": "anchor-guard",
                          "error": "anchor receipt disagrees with persisted anchor_ids",
                          "persisted_anchor_ids": saved_ids,
                          "receipt_anchor_ids": applied})
            return EXIT_BLOCK, steps
        if not applied and saved_ids:
            applied = list(saved_ids)
        if not applied and manifest_path is not None:
            # A child may have written every expected ticket and drained the queue
            # before its process died, so the retry's anchor receipt legitimately
            # has no applied list.  Only recover that narrow state when the phase
            # is durable, the queue is empty, and the tracked dirty set is exactly
            # the persisted expected ticket documents.
            recovery_marker = persisted.get("close_wave") if persisted else None
            recovery_phase = (
                recovery_marker.get("phases", {}).get("anchor")
                if isinstance(recovery_marker, dict)
                and isinstance(recovery_marker.get("phases"), dict)
                else None
            )
            expected_recovery = (
                recovery_marker.get("expected_ticket_ids", [])
                if isinstance(recovery_marker, dict) else []
            )
            expected_recovery_paths = {
                f"docs/runbook/backlog/{ticket_id}.json"
                for ticket_id in expected_recovery
                if isinstance(ticket_id, str)
                and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", ticket_id)
            }
            dirty_recovery_paths = set(_porcelain_paths(
                "\n".join(_delivery_primary_dirty(primary))
            ))
            if (
                isinstance(recovery_phase, dict)
                and recovery_phase.get("status") in {"started", "blocked"}
                and not recovery_phase.get("applied_ticket_ids")
                and expected_recovery
                and len(expected_recovery_paths) == len(expected_recovery)
                and not _read_anchor_queue(primary)
                and dirty_recovery_paths == expected_recovery_paths
            ):
                applied = list(expected_recovery)
        if manifest_path is not None:
            marker = _delivery_update_phase_marker(
                persisted.get("close_wave"), "anchor", status="started",
                operation_base=anchor_base_sha, landed_sha=anchor_base_sha,
                expected_ticket_ids=(persisted.get("close_wave") or {}).get(
                    "expected_ticket_ids", []),
                applied_ticket_ids=applied,
                acceptance_receipt=anchor_payload,
                queue_state="consumed" if applied else "pending",
            )
            persisted["close_wave"] = {
                **marker,
                "anchor_base_sha": anchor_base_sha,
                "anchor_ids": applied,
                "anchor_committed": already_committed,
            }
            try:
                _integrate_save(manifest_path, persisted)
            except OSError as exc:
                steps.append({"name": "anchor-guard",
                              "error": f"could not persist anchor receipt: {exc}"})
                return EXIT_BLOCK, steps

        anchor_commit_rc, anchor_commit = _delivery_anchor_commit(
            primary,
            applied_ids=applied,
            already_committed=already_committed,
            anchor_base_sha=anchor_base_sha,
            already_committed_sha=already_committed_sha,
        )
        steps.append({"name": "anchor-commit", "rc": anchor_commit_rc,
                      "payload": anchor_commit})
        if anchor_commit_rc == EXIT_OK and manifest_path is not None:
            committed_sha = anchor_commit.get("sha")
            if applied and (not isinstance(committed_sha, str) or not committed_sha):
                steps.append({"name": "anchor-guard",
                              "error": "anchor commit succeeded without an identifiable commit sha"})
                return EXIT_BLOCK, steps
            persisted = _delivery_load_json(manifest_path)
            if persisted is None:
                steps.append({"name": "anchor-guard",
                              "error": "integration manifest disappeared after anchor commit"})
                return EXIT_BLOCK, steps
            marker = _delivery_update_phase_marker(
                persisted.get("close_wave"), "anchor", status="completed",
                operation_base=anchor_base_sha, landed_sha=committed_sha,
                expected_ticket_ids=(persisted.get("close_wave") or {}).get(
                    "expected_ticket_ids", []),
                applied_ticket_ids=applied,
                acceptance_receipt=anchor_payload,
                queue_state="consumed", anchor_commit=committed_sha,
            )
            close_wave = {
                **marker,
                "anchor_base_sha": anchor_base_sha,
                "anchor_ids": applied,
                "anchor_committed": bool(applied),
                **({"anchor_commit_sha": committed_sha}
                   if isinstance(committed_sha, str) and committed_sha else {}),
            }
            if not applied and anchor_commit.get("noop") is True:
                close_wave["anchor_noop"] = True
                close_wave.pop("anchor_commit_sha", None)
            elif applied:
                close_wave.pop("anchor_noop", None)
            persisted["close_wave"] = close_wave
            try:
                _integrate_save(manifest_path, persisted)
            except OSError as exc:
                steps.append({"name": "anchor-guard",
                              "error": f"could not persist committed anchor receipt: {exc}"})
                return EXIT_BLOCK, steps
        return anchor_commit_rc, steps


def _delivery_sync_close_wave(
    args: argparse.Namespace,
    primary: Path,
    manifest_path: Path | None,
    steps: list[dict[str, Any]],
) -> tuple[int, dict[str, Any] | None]:
    """Complete the delivery-loop's explicit backup leg.

    The local cutover is develop; this is the separately named backup action.
    Persisting sync_status makes a push failure resumable without repeating Gate,
    cutover, resolve, or anchor.
    """
    if not getattr(args, "sync", False):
        return EXIT_OK, None
    if manifest_path is None:
        steps.append({"name": "sync", "error": "no integration manifest to mark sync"})
        return EXIT_BLOCK, None
    current = _delivery_load_json(manifest_path)
    if current is None:
        steps.append({"name": "sync", "error": "integration manifest disappeared before sync"})
        return EXIT_BLOCK, None
    marker = dict(current.get("close_wave") or {})
    if marker.get("sync_status") == "completed":
        steps.append({"name": "sync", "mode": "already-synced",
                      "sync": marker.get("sync")})
        return EXIT_OK, marker.get("sync")

    head_rc, sync_head = _git(["rev-parse", "HEAD"], cwd=primary)
    if head_rc != EXIT_OK or not sync_head:
        steps.append({"name": "sync", "error": "could not capture primary HEAD before sync"})
        return EXIT_BLOCK, None
    marker = _delivery_update_phase_marker(
        marker, "sync", status="started",
        operation_base=marker.get("operation_base") or marker.get("anchor_base_sha"),
        landed_sha=sync_head,
        expected_ticket_ids=marker.get("expected_ticket_ids", []),
        applied_ticket_ids=marker.get("anchor_ids", []),
        queue_state="consumed",
    )
    current["close_wave"] = marker
    try:
        _integrate_save(manifest_path, current)
    except OSError as exc:
        steps.append({"name": "sync", "error": f"could not persist sync start: {exc}"})
        return EXIT_BLOCK, None

    # Sync runs after cutover, so the stable primary copy is now the coordinator
    # version that produced the fresh Gate.  The caller's source worktree may have
    # been resolved and removed by this point; resolving `__file__` here would make
    # a successful local landing crash before its backup receipt is written.
    orchestrator = primary / "ops" / "worktree_orchestrate.py"
    sync_rc, sync_payload = _delivery_json_tool(
        orchestrator,
        primary,
        ["sync", "--commit", *_state_arg(args.state)],
        label=f"sync:{args.slug}",
        expected_schema=SCHEMA,
        required_keys=("verdict",),
    )
    steps.append({"name": "sync", "rc": sync_rc, "payload": sync_payload})
    if sync_rc != EXIT_OK or sync_payload.get("verdict") not in ("pushed", "noop"):
        return sync_rc or EXIT_BLOCK, sync_payload

    current = _delivery_load_json(manifest_path)
    if current is None:
        steps.append({"name": "sync", "error": "integration manifest disappeared after sync"})
        return EXIT_BLOCK, sync_payload
    current["close_wave"] = {
        **_delivery_update_phase_marker(
            current.get("close_wave"), "sync", status="completed",
            operation_base=(current.get("close_wave") or {}).get("operation_base")
            or (current.get("close_wave") or {}).get("anchor_base_sha"),
            landed_sha=sync_payload.get("to"),
            expected_ticket_ids=(current.get("close_wave") or {}).get(
                "expected_ticket_ids", []),
            applied_ticket_ids=(current.get("close_wave") or {}).get("anchor_ids", []),
            acceptance_receipt=sync_payload, queue_state="consumed",
        ),
        "sync_status": "completed",
        "sync": sync_payload,
    }
    try:
        _integrate_save(manifest_path, current)
    except OSError as exc:
        steps.append({"name": "sync",
                      "error": f"sync succeeded but receipt could not be saved: {exc}"})
        return EXIT_BLOCK, sync_payload
    return EXIT_OK, sync_payload


def cmd_close_wave(args: argparse.Namespace) -> int:
    """Run one end-to-end Delivery Team closure under the shared finalization lock."""
    if not getattr(args, "commit", False):
        return _cmd_close_wave_impl(args)
    with _delivery_loop_lock(primary_root()):
        return _cmd_close_wave_impl(args)


def _cmd_close_wave_impl(args: argparse.Namespace) -> int:
    """Run the Delivery Team's complete, resumable batch closure.

    Workers still stop at commit + hand-back. This verb belongs to the Delivery
    Team master/integrator and continues through primary cutover. With --sync it
    also mirrors the landed primary tip to origin/main. Other teams' worktrees
    are allowed to remain active: every teardown target is still an explicit
    source branch or this round's integration branch, and the finalization lock
    serializes the shared primary/remote side effects.
    """
    if not SLUG_RE.match(args.slug or ""):
        _emit({
            "schema": DELIVERY_SCHEMA,
            "step": "close-wave",
            "error": "slug must match ^[a-z0-9]+(?:-[a-z0-9]+)*$",
            "slug": args.slug,
        }, args.json, "✗ close-wave refused: invalid slug")
        return EXIT_USAGE
    if args.state:
        # All child verbs must receive the same absolute path even though they run
        # from primary, the integration tree, and source worktrees respectively.
        args.state = str(Path(args.state).expanduser().resolve())
    blocked = _freeze_guard(args.state, "close-wave", args.json)
    if blocked is not None:
        return blocked
    primary = primary_root()
    coordinator_orchestrator = Path(__file__).resolve()
    runner_revision = _delivery_revision(coordinator_orchestrator)
    if getattr(args, "commit", False) and runner_revision is None:
        _emit({
            "schema": DELIVERY_SCHEMA, "step": "close-wave",
            "mode": "stopped", "slug": args.slug,
            "runner_revision": None,
            "integration_revision": None,
            "error": "runner_revision is missing",
        }, args.json, "✗ close-wave refused: runner_revision is missing")
        return EXIT_BLOCK
    dirty = _delivery_primary_dirty(primary)
    _, early_manifests = _delivery_state_paths(args)
    early_manifest = early_manifests[0] if early_manifests else None
    if dirty and not _delivery_anchor_recovery_dirty_allowed(primary, early_manifest):
        _emit({
            "schema": DELIVERY_SCHEMA,
            "step": "close-wave",
            "error": "primary is not clean; refusing before touching the wave",
            "dirty_files": dirty,
        }, args.json, "✗ close-wave refused: primary is dirty\n" + "\n".join(
            f"  {path}" for path in dirty
        ))
        return EXIT_BLOCK

    state_path, manifests = _delivery_state_paths(args)
    manifest_path = manifests[0] if manifests else None
    state_exists = state_path.exists()
    manifest_exists = manifest_path is not None and manifest_path.exists()
    integration_state = _delivery_load_json(state_path) if state_exists else None
    manifest = (_delivery_load_json(manifest_path)
                if manifest_exists and manifest_path else None)
    if state_exists and integration_state is None:
        return _delivery_state_error(
            args=args, state_path=state_path, manifest_path=manifest_path,
            error="integration state exists but is unreadable or malformed",
        )
    if manifest_exists and manifest is None:
        return _delivery_state_error(
            args=args, state_path=state_path, manifest_path=manifest_path,
            error="completed integration manifest exists but is unreadable or malformed",
        )

    branches = list(args.branches or [])
    persisted = integration_state or manifest
    requested_independent = bool(getattr(args, "independent", False))
    persisted_independent = (
        isinstance(persisted, dict) and persisted.get("independent") is True
    )
    if persisted is not None and persisted_independent != requested_independent:
        _emit({
            "schema": DELIVERY_SCHEMA, "step": "close-wave",
            "mode": "stopped", "slug": args.slug,
            "error": "independent opt-in must match the persisted integration state",
            "persisted_independent": persisted_independent,
            "requested_independent": requested_independent,
        }, args.json,
            "✗ close-wave refused: repeat the original "
            "--independent opt-in exactly")
        return EXIT_USAGE
    if persisted is not None:
        state_branches = persisted.get("branches")
        if not isinstance(state_branches, list) or any(
            not isinstance(branch, str) for branch in state_branches
        ):
            return _delivery_state_error(
                args=args, state_path=state_path, manifest_path=manifest_path,
                error="persisted integration identity has malformed branches",
            )
        state_branches = list(state_branches)
        if branches and branches != state_branches:
            _emit({
                "schema": DELIVERY_SCHEMA, "step": "close-wave",
                "error": "--branches differs from persisted integration state",
                "expected_branches": state_branches, "received_branches": branches,
                "state_file": str(state_path),
                "manifest": str(manifest_path) if manifest_path else None,
            }, args.json,
                "✗ close-wave refused: resume with the original branch list")
            return EXIT_USAGE
        branches = state_branches
    if not branches:
        _emit({
            "schema": DELIVERY_SCHEMA, "step": "close-wave",
            "error": "fresh close-wave needs --branches; an in-flight slug may omit it",
            "slug": args.slug,
        }, args.json, "✗ close-wave: --branches <source-branch ...> is required")
        return EXIT_USAGE

    operation_base = _delivery_operation_base(args.base, manifest=manifest)
    state_identity_error = (_delivery_integration_error(
        integration_state, label="integration state", slug=args.slug,
        base=operation_base, branches=branches, require_gated=False,
        require_live_worktree=True,
    ) if integration_state is not None else None)
    if state_identity_error:
        return _delivery_state_error(
            args=args, state_path=state_path, manifest_path=manifest_path,
            error=state_identity_error,
        )
    manifest_marker = manifest.get("close_wave") if isinstance(manifest, dict) else None
    manifest_delivery_status = (
        manifest_marker.get("status") if isinstance(manifest_marker, dict) else None
    )
    manifest_identity_error = (_delivery_integration_error(
        manifest, label="completed integration manifest", slug=args.slug,
        base=operation_base, branches=branches, require_gated=True,
        require_live_worktree=manifest_delivery_status not in ("validated", "completed"),
    ) if manifest is not None else None)
    if manifest_identity_error:
        return _delivery_state_error(
            args=args, state_path=state_path, manifest_path=manifest_path,
            error=manifest_identity_error,
        )
    if integration_state is not None and manifest is not None:
        for key in ("worktree", "branch"):
            if integration_state.get(key) != manifest.get(key):
                return _delivery_state_error(
                    args=args, state_path=state_path, manifest_path=manifest_path,
                    error=f"integration state and manifest disagree on {key}",
                )
        # integrate writes the manifest before unlinking state.  In that crash
        # window the gated manifest is authoritative; never run Gate twice from
        # the older receipt.
        integration_state = None

    allowed = set(branches)
    if integration_state and integration_state.get("branch"):
        allowed.add(str(integration_state["branch"]))
    if manifest and manifest.get("branch"):
        allowed.add(str(manifest["branch"]))
    rrc, records = _delivery_registry_records(args, primary=primary)
    if rrc != EXIT_OK:
        _emit({
            "schema": DELIVERY_SCHEMA, "step": "close-wave",
            "error": "could not read the worktree registry; no closure was attempted",
        }, args.json, "✗ close-wave refused: registry-list failed")
        return EXIT_BLOCK
    if args.commit and manifest is not None and manifest_delivery_status == "completed":
        steps: list[dict[str, Any]] = []
        integration_revision = manifest.get("integration_revision")
        revision_error = _delivery_revision_guard(
            runner_revision, integration_revision,
        )
        if revision_error:
            _emit({
                "schema": DELIVERY_SCHEMA, "step": "close-wave",
                "mode": "stopped", "slug": args.slug, "branches": branches,
                "runner_revision": runner_revision,
                "integration_revision": integration_revision,
                "steps": steps, "manifest": str(manifest_path),
                "error": revision_error,
            }, args.json, f"✗ close-wave stopped: {revision_error}")
            return EXIT_BLOCK
        saved_expected = _delivery_saved_expected_ticket_ids(manifest)
        expected_ticket_ids = _delivery_expected_ticket_set(
            primary, records, branches, saved_expected=saved_expected,
        )
        reservation_errors = _delivery_expected_ticket_reservation_errors(
            records, branches, statuses={wr.STATUS_ACTIVE, "merged"}
        )
        independent_completed = (
            manifest.get("independent") is True
            and saved_expected == []
            and isinstance((manifest.get("close_wave") or {}).get(
                "independent_provenance"
            ), dict)
            and (manifest.get("close_wave") or {}).get(
                "independent_provenance", {}
            ).get("ok") is True
        )
        closure = (
            {
                "ok": False,
                "expected_ticket_ids": expected_ticket_ids,
                "failures": reservation_errors,
            }
            if reservation_errors else
            {
                "ok": True,
                "expected_ticket_ids": [],
                "failures": [],
                "mode": "independent-no-ticket",
                "provenance": (manifest.get("close_wave") or {}).get(
                    "independent_provenance"
                ),
            }
            if independent_completed else
            _delivery_expected_ticket_closure(primary, expected_ticket_ids)
        )
        steps.append({"name": "expected-ticket-closure", **closure})
        if not closure["ok"]:
            _emit({
                "schema": DELIVERY_SCHEMA, "step": "close-wave",
                "mode": "stopped", "slug": args.slug, "branches": branches,
                "steps": steps, "manifest": str(manifest_path) if manifest_path else None,
                "error": "completed close-wave has tickets that are not fixed",
            }, args.json,
                "✗ close-wave stopped: completed manifest does not prove every "
                "expected ticket is fixed")
            return EXIT_BLOCK
        sync_rc, sync_payload = _delivery_sync_close_wave(
            args, primary, manifest_path, steps,
        )
        if sync_rc != EXIT_OK:
            _emit({
                "schema": DELIVERY_SCHEMA, "step": "close-wave",
                "mode": "stopped", "slug": args.slug, "branches": branches,
                "runner_revision": runner_revision,
                "integration_revision": integration_revision,
                "steps": steps, "manifest": str(manifest_path) if manifest_path else None,
            }, args.json, "✗ close-wave stopped during remote sync")
            return sync_rc
        marker = (_delivery_load_json(manifest_path) or {}).get("close_wave", {})
        _emit({
            "schema": DELIVERY_SCHEMA, "step": "close-wave",
            "mode": "already-closed", "slug": args.slug, "branches": branches,
            "integration_branch": manifest.get("branch"),
            "manifest": str(manifest_path) if manifest_path else None,
            "runner_revision": runner_revision,
            "integration_revision": integration_revision,
            "steps": steps, "expected_ticket_ids": expected_ticket_ids,
            "sync_status": marker.get("sync_status", "not-requested"),
        }, args.json,
            f"close-wave {args.slug}: already closed"
            + (" and synced" if marker.get("sync_status") == "completed"
               else "; remote sync not requested"))
        return EXIT_OK

    if (args.commit and manifest is not None
            and manifest_delivery_status == "validated"
            and not Path(str(manifest.get("worktree"))).is_dir()):
        rrc, recovery_records = _delivery_registry_records(args, primary=primary)
        if rrc != EXIT_OK:
            return EXIT_BLOCK
        active_allowed = [
            record for record in recovery_records
            if record.get("status") == wr.STATUS_ACTIVE
            and record.get("branch") in set(branches) | {manifest.get("branch")}
        ]
        if active_allowed:
            return _delivery_state_error(
                args=args, state_path=state_path, manifest_path=manifest_path,
                error="validated close-wave lost its integration worktree while an allowed active record remains",
            )
        recovered = _delivery_load_json(manifest_path) if manifest_path else None
        if recovered is None:
            return _delivery_state_error(
                args=args, state_path=state_path, manifest_path=manifest_path,
                error="validated close-wave manifest disappeared during recovery",
            )
        integration_revision = recovered.get("integration_revision")
        revision_error = _delivery_revision_guard(
            runner_revision, integration_revision,
        )
        if revision_error:
            _emit({
                "schema": DELIVERY_SCHEMA, "step": "close-wave",
                "mode": "stopped", "slug": args.slug, "branches": branches,
                "runner_revision": runner_revision,
                "integration_revision": integration_revision,
                "steps": [], "manifest": str(manifest_path),
                "error": revision_error,
            }, args.json, f"✗ close-wave recovery stopped: {revision_error}")
            return EXIT_BLOCK
        saved_expected = _delivery_saved_expected_ticket_ids(recovered)
        expected_ticket_ids = _delivery_expected_ticket_set(
            primary, recovery_records, branches, saved_expected=saved_expected,
        )
        reservation_errors = _delivery_expected_ticket_reservation_errors(
            recovery_records, branches, statuses={wr.STATUS_ACTIVE, "merged"}
        )
        independent_recovered = (
            recovered.get("independent") is True
            and saved_expected == []
            and isinstance((recovered.get("close_wave") or {}).get(
                "independent_provenance"
            ), dict)
            and (recovered.get("close_wave") or {}).get(
                "independent_provenance", {}
            ).get("ok") is True
        )
        closure = (
            {
                "ok": False,
                "expected_ticket_ids": expected_ticket_ids,
                "failures": reservation_errors,
            }
            if reservation_errors else
            {
                "ok": True,
                "expected_ticket_ids": [],
                "failures": [],
                "mode": "independent-no-ticket",
                "provenance": (recovered.get("close_wave") or {}).get(
                    "independent_provenance"
                ),
            }
            if independent_recovered else
            _delivery_expected_ticket_closure(primary, expected_ticket_ids)
        )
        recovery_steps: list[dict[str, Any]] = [
            {"name": "expected-ticket-closure", **closure}
        ]
        if not closure["ok"]:
            _emit({
                "schema": DELIVERY_SCHEMA, "step": "close-wave",
                "mode": "stopped", "slug": args.slug, "branches": branches,
                "steps": recovery_steps, "manifest": str(manifest_path),
                "error": "validated close-wave recovery has tickets that are not fixed",
            }, args.json,
                "✗ close-wave recovery stopped: expected ticket set is not fully fixed")
            return EXIT_BLOCK
        recovered["close_wave"] = {
            **(recovered.get("close_wave") or {}),
            "status": "completed",
            "expected_ticket_ids": expected_ticket_ids,
        }
        try:
            _integrate_save(manifest_path, recovered)
        except OSError as exc:
            return _delivery_state_error(
                args=args, state_path=state_path, manifest_path=manifest_path,
                error=f"could not persist recovered close-wave completion: {exc}",
            )
        sync_rc, _sync_payload = _delivery_sync_close_wave(
            args, primary, manifest_path, recovery_steps,
        )
        if sync_rc != EXIT_OK:
            _emit({
                "schema": DELIVERY_SCHEMA, "step": "close-wave",
                "mode": "stopped", "slug": args.slug, "branches": branches,
                "runner_revision": runner_revision,
                "integration_revision": integration_revision,
                "steps": recovery_steps, "manifest": str(manifest_path),
            }, args.json, "close-wave recovered locally but remote sync stopped")
            return sync_rc
        _emit({
            "schema": DELIVERY_SCHEMA, "step": "close-wave",
            "mode": "recovered", "slug": args.slug, "branches": branches,
            "integration_branch": manifest.get("branch"),
            "manifest": str(manifest_path) if manifest_path else None,
            "runner_revision": runner_revision,
            "integration_revision": integration_revision,
            "steps": recovery_steps, "expected_ticket_ids": expected_ticket_ids,
        }, args.json,
            f"close-wave {args.slug}: recovered after teardown"
            + (" and synced" if getattr(args, "sync", False)
               else "; remote sync not requested"))
        return EXIT_OK

    if not args.commit:
        independent_suffix = " --independent" if requested_independent else ""
        plan = [
            "integrate --commit --no-gate"
            f"{independent_suffix} (fresh) or --continue --commit"
            f"{independent_suffix} (resume)",
            "integrated-tree fresh Gate",
            "cutover --commit",
            "resolve every source with --via-integration main",
            "backlog.py anchor --commit",
            "commit only docs/runbook/backlog closure metadata",
            "backlog.py validate --baseline-check",
            "resolve the integration tree",
        ]
        if getattr(args, "sync", False):
            plan.append("sync --commit -> origin/main (backup leg)")
        if integration_state:
            next_step = f"integrate --continue --commit{independent_suffix}"
        elif manifest:
            next_step = "cutover --commit"
        else:
            next_step = f"integrate --commit --no-gate{independent_suffix}"
        _emit({
            "schema": DELIVERY_SCHEMA, "step": "close-wave", "mode": "dry-run",
            "slug": args.slug, "branches": branches, "allowed_branches": sorted(allowed),
            "state_file": str(state_path) if integration_state else None,
            "manifest": str(manifest_path) if manifest else None,
            "plan": plan, "next_step": next_step,
        }, args.json,
            f"# close-wave {args.slug} (dry-run)\n  " + "\n  ".join(plan)
            + f"\n  next: {next_step}\n  (--commit to execute)")
        return EXIT_OK

    steps: list[dict[str, Any]] = []

    def record_phase(phase: str, status: str, **fields: Any) -> bool:
        """Write a durable phase receipt, turning ledger failures into a stop."""
        if manifest_path is None:
            return True
        try:
            _delivery_record_phase(
                manifest_path, phase, status=status, **fields,
            )
        except (OSError, ValueError) as exc:
            steps.append({
                "name": f"{phase}-phase",
                "status": status,
                "error": f"could not persist {phase} phase receipt: {exc}",
            })
            return False
        return True

    # Before cutover the source coordinator is required for the new protocol;
    # after cutover, all remaining steps use this stable primary copy.  A delivery
    # wave may resolve its own source worktree before anchor/sync, so any later
    # lookup through `__file__` is unsafe.
    primary_orchestrator = primary / "ops" / "worktree_orchestrate.py"
    target_base = operation_base
    integration_worktree: Path | None = None
    integration_branch: str | None = None

    if integration_state is None and manifest is None:
        integrate_rc, integrate_payload = _delivery_json_tool(
            coordinator_orchestrator,
            primary,
            [
                "integrate", "--slug", args.slug, "--branches", *branches,
                "--no-gate", "--commit", "--base", operation_base,
                *(["--independent"] if requested_independent else []),
                *_state_arg(args.state),
            ],
            label=f"integrate:{args.slug}",
            expected_schema=INTEGRATE_SCHEMA,
            required_keys=("worktree", "branch"),
            receipt_validator=_delivery_require_integrate_picked,
        )
        steps.append({"name": "integrate-pick", "rc": integrate_rc,
                      "payload": integrate_payload})
        if integrate_rc != EXIT_OK:
            _emit({"schema": DELIVERY_SCHEMA, "step": "close-wave",
                   "mode": "stopped", "slug": args.slug, "steps": steps,
                   "state_file": str(state_path) if state_path.exists() else None,
                   "next": "resolve the named conflict, then rerun close-wave with the same slug"},
                  args.json,
                  f"✗ close-wave stopped during integrate; state kept at {state_path}")
            return integrate_rc
        integration_state = _delivery_load_json(state_path)
        if integration_state is None:
            _emit({"schema": DELIVERY_SCHEMA, "step": "close-wave",
                   "error": "integrate returned success but left no resumable state",
                   "steps": steps}, args.json,
                  "✗ close-wave refused: integrate did not leave state")
            return EXIT_BLOCK
        integration_error = _delivery_integration_error(
            integration_state, label="integration state", slug=args.slug,
            base=operation_base, branches=branches, require_gated=False,
            require_live_worktree=True,
        )
        if integration_error:
            return _delivery_state_error(
                args=args, state_path=state_path, manifest_path=manifest_path,
                error=integration_error,
            )
        allowed.add(str(integration_state["branch"]))

    if integration_state is not None:
        integration_state["runner_revision"] = runner_revision
        try:
            _integrate_save(state_path, integration_state)
        except OSError as exc:
            return _delivery_state_error(
                args=args, state_path=state_path, manifest_path=manifest_path,
                error=f"could not persist runner_revision: {exc}",
            )

    if integration_state is not None:
        integration_worktree = Path(str(integration_state["worktree"]))
        integration_branch = str(integration_state.get("branch") or "")
        continue_script = integration_worktree / "ops" / "worktree_orchestrate.py"
        continue_rc, continue_payload = _delivery_json_tool(
            continue_script,
            integration_worktree,
            [
                "integrate", "--slug", args.slug, "--continue", "--commit",
                "--base", operation_base, *_state_arg(args.state),
                *(["--independent"] if requested_independent else []),
            ],
            label=f"integrate-gate:{args.slug}",
            expected_schema=INTEGRATE_SCHEMA,
            required_keys=("worktree", "branch", "manifest", "integration_revision"),
            receipt_validator=_delivery_require_integrate_gated,
        )
        steps.append({"name": "integrate-gate", "rc": continue_rc,
                      "payload": continue_payload})
        if continue_rc != EXIT_OK or continue_payload.get("verdict") not in ("pass", "warn"):
            _emit({"schema": DELIVERY_SCHEMA, "step": "close-wave",
                   "mode": "stopped", "slug": args.slug,
                   "runner_revision": runner_revision,
                   "integration_revision": continue_payload.get(
                       "integration_revision"
                   ),
                   "steps": steps,
                   "next": "fix/resume the named integrated-tree issue, then rerun close-wave"},
                  args.json, "✗ close-wave stopped: integrated-tree Gate is not non-block")
            return continue_rc or EXIT_BLOCK
        manifest_value = continue_payload.get("manifest")
        manifest_path = Path(str(manifest_value)) if manifest_value else None
        manifest = (_delivery_load_json(manifest_path)
                    if manifest_path and manifest_path.exists() else None)
        if manifest_path is None or manifest is None:
            return _delivery_state_error(
                args=args, state_path=state_path, manifest_path=manifest_path,
                error="integrate reported success but left no readable manifest",
            )
        manifest_error = _delivery_integration_error(
            manifest, label="completed integration manifest", slug=args.slug,
            base=operation_base, branches=branches, require_gated=True,
            require_live_worktree=True,
        )
        if manifest_error:
            return _delivery_state_error(
                args=args, state_path=state_path, manifest_path=manifest_path,
                error=manifest_error,
            )
        integration_revision = manifest.get("integration_revision")
        if continue_payload.get("integration_revision") != integration_revision:
            return _delivery_state_error(
                args=args, state_path=state_path, manifest_path=manifest_path,
                error="integrate gate receipt and manifest disagree on integration_revision",
            )
        revision_error = _delivery_revision_guard(
            runner_revision, integration_revision,
        )
        if revision_error:
            steps.append({
                "name": "revision-provenance", "ok": False,
                "runner_revision": runner_revision,
                "integration_revision": integration_revision,
                "error": revision_error,
            })
            _emit({
                "schema": DELIVERY_SCHEMA, "step": "close-wave",
                "mode": "stopped", "slug": args.slug,
                "runner_revision": runner_revision,
                "integration_revision": integration_revision,
                "steps": steps, "manifest": str(manifest_path),
                "error": revision_error,
            }, args.json, f"✗ close-wave stopped: {revision_error}")
            return EXIT_BLOCK
        manifest["runner_revision"] = runner_revision
        try:
            _integrate_save(manifest_path, manifest)
        except OSError as exc:
            return _delivery_state_error(
                args=args, state_path=state_path, manifest_path=manifest_path,
                error=f"could not persist runner_revision in manifest: {exc}",
            )
        integration_state = None
        allowed.add(str(manifest.get("branch")))

    if getattr(args, "commit", False) and manifest is not None:
        integration_revision = manifest.get("integration_revision")
        revision_error = _delivery_revision_guard(
            runner_revision, integration_revision,
        )
        if revision_error:
            _emit({
                "schema": DELIVERY_SCHEMA, "step": "close-wave",
                "mode": "stopped", "slug": args.slug,
                "runner_revision": runner_revision,
                "integration_revision": integration_revision,
                "steps": steps,
                "manifest": str(manifest_path) if manifest_path else None,
                "error": revision_error,
            }, args.json, f"✗ close-wave stopped: {revision_error}")
            return EXIT_BLOCK
        if manifest.get("runner_revision") != runner_revision:
            manifest["runner_revision"] = runner_revision
            try:
                _integrate_save(manifest_path, manifest)
            except OSError as exc:
                return _delivery_state_error(
                    args=args, state_path=state_path, manifest_path=manifest_path,
                    error=f"could not persist runner_revision in manifest: {exc}",
                )

    # The opening registry snapshot is not enough: a peer may start while the
    # integrated Gate is running.  Recheck before the irreversible develop step.
    rrc, records = _delivery_registry_records(args, primary=primary)
    if rrc != EXIT_OK:
        return EXIT_BLOCK
    # Other teams may have active worktrees. The shared Delivery Team lock keeps
    # their close-wave primary/sync sequence out of this critical section; their
    # source branches are not targets of this wave's resolve calls.
    saved_expected = _delivery_saved_expected_ticket_ids(manifest)
    expected_ticket_ids = _delivery_expected_ticket_set(
        primary, records, branches, saved_expected=saved_expected,
    )
    reservation_errors = _delivery_expected_ticket_reservation_errors(
        records, branches, statuses={wr.STATUS_ACTIVE, "merged"}
    )
    if manifest is not None:
        integration_worktree = integration_worktree or Path(str(manifest.get("worktree") or ""))
        integration_branch = integration_branch or str(manifest.get("branch") or "")
    elif integration_state is not None:
        integration_worktree = integration_worktree or Path(str(
            integration_state.get("worktree") or ""
        ))
        integration_branch = integration_branch or str(integration_state.get("branch") or "")
    integration_record = next(
        (record for record in records
         if record.get("status") == wr.STATUS_ACTIVE
         and record.get("branch") == integration_branch),
        None,
    )
    independent_provenance: dict[str, Any] | None = None
    if requested_independent:
        integration_head = ""
        if integration_worktree is not None and integration_worktree.is_dir():
            head_rc, integration_head = _git(
                ["rev-parse", "HEAD"], cwd=integration_worktree,
            )
            if head_rc != EXIT_OK:
                integration_head = ""
        independent_provenance = _delivery_independent_no_ticket_provenance(
            state=integration_state,
            manifest=manifest,
            integration_record=integration_record,
            current_head=integration_head,
            primary_dirty=_delivery_primary_dirty(primary),
            queue=list((integration_state or manifest or {}).get("queue") or []),
        )
    if reservation_errors or not expected_ticket_ids or (
            requested_independent
            and independent_provenance is not None
            and not independent_provenance["ok"]
    ):
        no_ticket_ok = (
            requested_independent
            and not reservation_errors
            and not expected_ticket_ids
            and independent_provenance is not None
            and independent_provenance["ok"]
        )
        expected_set_error = (
            "named source reservation has malformed backlog"
            if reservation_errors else
            "named source branches have no claimed backlog tickets"
            if not expected_ticket_ids and not no_ticket_ok else
            "independent no-ticket provenance is incomplete"
            if requested_independent else None
        )
        steps.append({
            "name": "expected-ticket-set",
            "ok": no_ticket_ok,
            "expected_ticket_ids": expected_ticket_ids,
            "errors": reservation_errors,
            "provenance": independent_provenance,
            **({"error": expected_set_error} if expected_set_error else {}),
        })
        if not no_ticket_ok:
            _emit({
                "schema": DELIVERY_SCHEMA, "step": "close-wave",
                "mode": "stopped", "slug": args.slug, "branches": branches,
                "steps": steps,
                "error": (
                    "close-wave requires valid source ticket reservations"
                    if reservation_errors else
                    "close-wave requires complete independent no-ticket provenance"
                    if requested_independent else
                    "close-wave requires a non-empty expected ticket set"
                ),
            }, args.json,
                "✗ close-wave stopped: source ticket reservation is invalid"
                if reservation_errors else
                "✗ close-wave stopped: independent no-ticket provenance is incomplete"
                if requested_independent else
                "✗ close-wave stopped: expected ticket set is empty")
            return EXIT_BLOCK
    if manifest_path is not None and saved_expected is None:
        persisted = _delivery_load_json(manifest_path)
        if persisted is None:
            return _delivery_state_error(
                args=args, state_path=state_path, manifest_path=manifest_path,
                error="integration manifest disappeared before expected ticket set was saved",
            )
        persisted["close_wave"] = {
            **(persisted.get("close_wave") or {}),
            "expected_ticket_ids": expected_ticket_ids,
            **(
                {"independent_provenance": independent_provenance}
                if independent_provenance is not None
                else {}
            ),
        }
        try:
            _integrate_save(manifest_path, persisted)
        except OSError as exc:
            return _delivery_state_error(
                args=args, state_path=state_path, manifest_path=manifest_path,
                error=f"could not persist expected ticket set: {exc}",
            )

    if manifest is not None:
        integration_worktree = integration_worktree or Path(str(manifest["worktree"]))
        integration_branch = integration_branch or str(manifest.get("branch") or "")
    if integration_worktree is None or integration_branch is None:
        _emit({"schema": DELIVERY_SCHEMA, "step": "close-wave",
               "error": "no integration worktree/branch was available after assembly",
               "steps": steps}, args.json,
              "✗ close-wave refused: integration identity is missing")
        return EXIT_BLOCK

    head_rc, phase_head = _git(["rev-parse", "HEAD"], cwd=primary)
    if head_rc != EXIT_OK or not phase_head:
        return _delivery_state_error(
            args=args, state_path=state_path, manifest_path=manifest_path,
            error="could not capture primary HEAD before close-wave phases",
        )
    phase_expected = list(expected_ticket_ids)
    if not record_phase(
        "cutover", "started", operation_base=operation_base,
        landed_sha=phase_head, expected_ticket_ids=phase_expected,
        applied_ticket_ids=[], queue_state="pending",
    ):
        return EXIT_BLOCK
    ancestor_rc, _ = _git(
        ["merge-base", "--is-ancestor", integration_branch, target_base], cwd=primary
    )
    if ancestor_rc == 0:
        landed_rc, landed_sha = _git(["rev-parse", "HEAD"], cwd=primary)
        cutover_receipt = {
            "mode": "already-landed", "branch": integration_branch,
            "landed": landed_rc == EXIT_OK, "sha": landed_sha,
        }
        steps.append({"name": "cutover", **cutover_receipt})
        if not record_phase(
            "cutover", "completed", operation_base=operation_base,
            landed_sha=landed_sha if landed_rc == EXIT_OK else phase_head,
            expected_ticket_ids=phase_expected, applied_ticket_ids=[],
            acceptance_receipt=cutover_receipt, queue_state="pending",
        ):
            return EXIT_BLOCK
    else:
        cutover_script = integration_worktree / "ops" / "worktree_orchestrate.py"
        cutover_rc, cutover_payload = _delivery_json_tool(
            cutover_script,
            integration_worktree,
            [
                "cutover", "--worktree", str(integration_worktree), "--commit",
                "--base", operation_base, *_state_arg(args.state),
            ],
                label=f"cutover:{args.slug}",
                expected_schema=SCHEMA,
                required_keys=("landed",),
                receipt_validator=_delivery_require_cutover_landed,
        )
        steps.append({"name": "cutover", "rc": cutover_rc,
                      "payload": cutover_payload})
        if cutover_rc != EXIT_OK or not cutover_payload.get("landed"):
            record_phase(
                "cutover", "blocked", operation_base=operation_base,
                landed_sha=phase_head, expected_ticket_ids=phase_expected,
                applied_ticket_ids=[], acceptance_receipt=cutover_payload,
                queue_state="pending",
            )
            _emit({"schema": DELIVERY_SCHEMA, "step": "close-wave",
                   "mode": "stopped", "slug": args.slug, "steps": steps,
                   "next": "follow cutover refusal, then rerun close-wave"}, args.json,
                  "✗ close-wave stopped: cutover did not land")
            return cutover_rc or EXIT_BLOCK
        if not record_phase(
            "cutover", "completed", operation_base=operation_base,
            landed_sha=cutover_payload.get("sha") or cutover_payload.get("landed_sha"),
            expected_ticket_ids=phase_expected, applied_ticket_ids=[],
            acceptance_receipt=cutover_payload, queue_state="pending",
        ):
            return EXIT_BLOCK

    phase_head_rc, landed_phase_head = _git(["rev-parse", "HEAD"], cwd=primary)
    if phase_head_rc == EXIT_OK and landed_phase_head:
        phase_head = landed_phase_head

    # Capture source paths after cutover too: a resumed invocation may have already
    # resolved some of them.  Resolved sources are idempotently skipped; active
    # sources are audited before removal.
    rrc, records = _delivery_registry_records(args, primary=primary)
    if rrc != EXIT_OK:
        return EXIT_BLOCK
    active_by_branch = {
        str(record.get("branch")): record for record in records
        if record.get("status") == wr.STATUS_ACTIVE
    }
    if not record_phase(
        "resolve-source", "started", operation_base=target_base,
        landed_sha=phase_head, expected_ticket_ids=phase_expected,
        applied_ticket_ids=[], queue_state="pending",
        source_branches=list(branches),
    ):
        return EXIT_BLOCK
    resolved_branches: list[str] = []
    for branch in branches:
        record = active_by_branch.get(branch)
        if record is None:
            steps.append({"name": "resolve-source", "branch": branch, "mode": "already-resolved"})
            resolved_branches.append(branch)
            continue
        source_path = Path(str(record.get("path") or ""))
        if not source_path.is_dir():
            record_phase(
                "resolve-source", "blocked", operation_base=target_base,
                landed_sha=phase_head, expected_ticket_ids=phase_expected,
                applied_ticket_ids=[], queue_state="pending",
                resolved_branches=resolved_branches,
                error="active source worktree is missing",
            )
            _emit({"schema": DELIVERY_SCHEMA, "step": "close-wave",
                   "error": "active source worktree is missing; refusing to guess its identity",
                   "branch": branch, "path": str(source_path), "steps": steps}, args.json,
                  f"✗ close-wave stopped: source worktree missing for {branch}")
            return EXIT_BLOCK
        resolve_rc, resolve_payload = _delivery_json_tool(
            primary_orchestrator,
            primary,
            [
                "resolve", "--worktree", str(source_path),
                "--base", target_base, "--via-integration", integration_branch,
                "--commit", *_state_arg(args.state),
            ],
            label=f"resolve-source:{branch}",
            expected_schema=SCHEMA,
            required_keys=("step",),
            receipt_validator=_delivery_require_resolved,
        )
        steps.append({"name": "resolve-source", "branch": branch, "rc": resolve_rc,
                      "payload": resolve_payload})
        if resolve_rc != EXIT_OK:
            record_phase(
                "resolve-source", "blocked", operation_base=target_base,
                landed_sha=phase_head, expected_ticket_ids=phase_expected,
                applied_ticket_ids=[], acceptance_receipt=resolve_payload,
                queue_state="pending", resolved_branches=resolved_branches,
            )
            _emit({"schema": DELIVERY_SCHEMA, "step": "close-wave",
                   "mode": "stopped", "slug": args.slug, "steps": steps,
                   "next": "fix the named resolve audit and rerun close-wave"}, args.json,
                  f"✗ close-wave stopped resolving source {branch}")
            return resolve_rc
        resolved_branches.append(branch)
    if not record_phase(
        "resolve-source", "completed", operation_base=target_base,
        landed_sha=phase_head, expected_ticket_ids=phase_expected,
        applied_ticket_ids=[], queue_state="pending",
        resolved_branches=resolved_branches,
    ):
        return EXIT_BLOCK

    anchor_rc, anchor_steps = _delivery_anchor_and_commit(
        args, primary, allowed, args.slug, manifest_path
    )
    steps.extend(anchor_steps)
    anchor_commit_rc = anchor_rc
    if anchor_commit_rc != EXIT_OK:
        record_phase(
            "anchor", "blocked", operation_base=phase_head,
            landed_sha=phase_head, expected_ticket_ids=phase_expected,
            applied_ticket_ids=[], queue_state="pending",
            acceptance_receipt=(anchor_steps[-1] if anchor_steps else None),
        )
        _emit({"schema": DELIVERY_SCHEMA, "step": "close-wave",
               "mode": "stopped", "slug": args.slug, "steps": steps}, args.json,
              "✗ close-wave stopped: anchor metadata was not committed")
        return EXIT_BLOCK
    closure = (
        {
            "ok": True,
            "expected_ticket_ids": [],
            "failures": [],
            "mode": "independent-no-ticket",
            "provenance": independent_provenance,
        }
        if requested_independent and not expected_ticket_ids
        else _delivery_expected_ticket_closure(primary, expected_ticket_ids)
    )
    steps.append({"name": "expected-ticket-closure", **closure})
    if not closure["ok"]:
        _emit({
            "schema": DELIVERY_SCHEMA, "step": "close-wave",
            "mode": "stopped", "slug": args.slug, "branches": branches,
            "steps": steps,
            "error": "anchor succeeded but expected ticket set is not fully fixed",
        }, args.json,
            "✗ close-wave stopped: anchor did not close every expected ticket")
        return EXIT_BLOCK

    if not record_phase(
        "validate", "started", operation_base=target_base,
        landed_sha=phase_head, expected_ticket_ids=phase_expected,
        applied_ticket_ids=expected_ticket_ids, queue_state="consumed",
    ):
        return EXIT_BLOCK
    validate_rc, validate_payload = _delivery_json_tool(
        primary / "ops" / "backlog.py",
        primary,
        ["validate", "--baseline-check"],
        label=f"validate:{args.slug}",
        expected_schema="kg.backlog.validate.v1",
        required_keys=("problems", "ok"),
        receipt_validator=_delivery_require_validate_receipt,
    )
    steps.append({"name": "validate", "rc": validate_rc,
                  "payload": validate_payload})
    if validate_rc != EXIT_OK:
        record_phase(
            "validate", "blocked", operation_base=target_base,
            landed_sha=phase_head, expected_ticket_ids=phase_expected,
            applied_ticket_ids=expected_ticket_ids,
            acceptance_receipt=validate_payload, queue_state="consumed",
        )
        _emit({"schema": DELIVERY_SCHEMA, "step": "close-wave",
               "mode": "stopped", "slug": args.slug, "steps": steps}, args.json,
              "✗ close-wave stopped: backlog validation is not green")
        return validate_rc
    if not record_phase(
        "validate", "completed", operation_base=target_base,
        landed_sha=phase_head, expected_ticket_ids=phase_expected,
        applied_ticket_ids=expected_ticket_ids,
        acceptance_receipt=validate_payload, queue_state="consumed",
    ):
        return EXIT_BLOCK

    if manifest_path is not None:
        validated_manifest = _delivery_load_json(manifest_path)
        if validated_manifest is None:
            return _delivery_state_error(
                args=args, state_path=state_path, manifest_path=manifest_path,
                error="integration manifest disappeared after validation",
            )
        validated_manifest["close_wave"] = {
            **(validated_manifest.get("close_wave") or {}),
            "status": "validated",
        }
        try:
            _integrate_save(manifest_path, validated_manifest)
        except OSError as exc:
            return _delivery_state_error(
                args=args, state_path=state_path, manifest_path=manifest_path,
                error=f"could not persist validated close-wave state: {exc}",
            )

    # Keep teardown last.  If anchor or validation stops, the integration worktree
    # and manifest remain available for the same slug to resume; deleting them first
    # would leave a successful landing with no way to finish the lifecycle.
    rrc, records = _delivery_registry_records(args, primary=primary)
    if rrc != EXIT_OK:
        return EXIT_BLOCK
    integration_record = next(
        (record for record in records
         if record.get("status") == wr.STATUS_ACTIVE
         and record.get("branch") == integration_branch),
        None,
    )
    if not record_phase(
        "resolve-integration", "started", operation_base=target_base,
        landed_sha=phase_head, expected_ticket_ids=phase_expected,
        applied_ticket_ids=expected_ticket_ids, queue_state="consumed",
        integration_branch=integration_branch,
    ):
        return EXIT_BLOCK
    if integration_record is None:
        steps.append({"name": "resolve-integration", "mode": "already-resolved",
                      "branch": integration_branch})
        resolve_integration_receipt = {
            "mode": "already-resolved", "branch": integration_branch,
            "resolved": "merged", "failures": 0,
        }
    else:
        resolve_rc, resolve_payload = _delivery_json_tool(
            primary_orchestrator,
            primary,
            [
                "resolve", "--worktree", str(integration_worktree),
                "--base", target_base, "--via-integration", integration_branch,
                "--commit", *_state_arg(args.state),
            ],
            label=f"resolve-integration:{args.slug}",
            expected_schema=SCHEMA,
            required_keys=("step",),
            receipt_validator=_delivery_require_resolved,
        )
        steps.append({"name": "resolve-integration", "rc": resolve_rc,
                      "payload": resolve_payload})
        if resolve_rc != EXIT_OK:
            record_phase(
                "resolve-integration", "blocked", operation_base=target_base,
                landed_sha=phase_head, expected_ticket_ids=phase_expected,
                applied_ticket_ids=expected_ticket_ids,
                acceptance_receipt=resolve_payload, queue_state="consumed",
                integration_branch=integration_branch,
            )
            _emit({"schema": DELIVERY_SCHEMA, "step": "close-wave",
                   "mode": "stopped", "slug": args.slug, "steps": steps,
                   "next": "fix the named integration resolve issue and rerun close-wave"}, args.json,
                  "✗ close-wave stopped resolving the integration tree")
            return resolve_rc
        resolve_integration_receipt = resolve_payload
    if not record_phase(
        "resolve-integration", "completed", operation_base=target_base,
        landed_sha=phase_head, expected_ticket_ids=phase_expected,
        applied_ticket_ids=expected_ticket_ids,
        acceptance_receipt=resolve_integration_receipt, queue_state="consumed",
        integration_branch=integration_branch,
    ):
        return EXIT_BLOCK

    if manifest_path is not None:
        completed_manifest = _delivery_load_json(manifest_path)
        if completed_manifest is None:
            return _delivery_state_error(
                args=args, state_path=state_path, manifest_path=manifest_path,
                error="integration manifest disappeared after resolve",
            )
        completed_manifest["close_wave"] = {
            **(completed_manifest.get("close_wave") or {}),
            "status": "completed",
            "sync_status": (
                "pending" if getattr(args, "sync", False) else "not-requested"
            ),
        }
        try:
            _integrate_save(manifest_path, completed_manifest)
        except OSError as exc:
            return _delivery_state_error(
                args=args, state_path=state_path, manifest_path=manifest_path,
                error=f"could not persist completed close-wave state: {exc}",
            )

    sync_rc, _sync_payload = _delivery_sync_close_wave(
        args, primary, manifest_path, steps,
    )
    if sync_rc != EXIT_OK:
        _emit({
            "schema": DELIVERY_SCHEMA, "step": "close-wave",
            "mode": "stopped", "slug": args.slug, "steps": steps,
            "runner_revision": runner_revision,
            "integration_revision": (
                (manifest or {}).get("integration_revision")
                if isinstance(manifest, dict) else None
            ),
            "manifest": str(manifest_path) if manifest_path else None,
        }, args.json, "close-wave landed locally but remote sync stopped")
        return sync_rc

    final_manifest = _delivery_load_json(manifest_path) if manifest_path else None
    final_marker = ((final_manifest or {}).get("close_wave")
                    if isinstance(final_manifest, dict) else {}) or {}
    final_integration_revision = None
    for candidate in (final_manifest, manifest):
        if isinstance(candidate, dict) and candidate.get("integration_revision"):
            final_integration_revision = candidate["integration_revision"]
            break
    _emit({
        "schema": DELIVERY_SCHEMA, "step": "close-wave", "mode": "committed",
        "slug": args.slug, "branches": branches, "integration_branch": integration_branch,
        "runner_revision": runner_revision,
        "integration_revision": final_integration_revision,
        "steps": steps, "primary_dirty": _delivery_primary_dirty(primary),
        "expected_ticket_ids": expected_ticket_ids,
        "sync_status": final_marker.get("sync_status", "not-requested"),
    }, args.json,
        f"✓ close-wave {args.slug}: integrated, gated, cut over, sources resolved, "
        "anchored, validated, integration tree resolved"
        + (" and synced to origin/main" if final_marker.get("sync_status") == "completed"
           else " (remote sync not requested)"))
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
    "`backlog.py reanchor --docs --commit` 從既有資料重新推導的。"
)


def _ledger_dirty(primary: Path, paths: tuple[str, ...] = LEDGER_PATHS) -> tuple[int, str]:
    """Tracked-only dirtiness of the ledger paths.

    `--untracked-files=no` on purpose, matching `_primary_ff_ready`: an untracked
    entry JSON in the primary is a LEGAL and common state (an agent filed one and
    has not committed it), and it does not block anybody's cutover. Counting it as
    dirt is what led the repair to sweep other people's unfinished work into a
    commit that claimed every changed path was tool-derived.
    """
    return _git(["status", "--porcelain", "--untracked-files=no", "--", *paths],
                cwd=primary)


def _repair_restore(
    primary: Path, out: dict[str, Any], paths: tuple[str, ...] = LEDGER_PATHS,
) -> None:
    """Put the repair's tracked paths back to HEAD after failure, and VERIFY it.

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
    else's unfinished work, and this function's job is to undo its own edits.  The
    default set is the ledger; a successful/failed docs reanchor extends it with the
    exact markdown paths reported by the child command.
    """
    _git(["reset", "-q", "--", *paths], cwd=primary)
    _git(["checkout", "HEAD", "--", *paths], cwd=primary)
    rc, dirty = _ledger_dirty(primary, paths)
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

    The repair now also covers document `verified_against` anchors. The generated
    markdown view is no longer tracked, so there is no second render step; only
    the ledger files and the exact documents reported by `reanchor --docs` enter
    the repair commit.

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
    # `reanchor` is the single repair primitive. The rebase inside cutover rewrites
    # the branch's commit shas, which can orphan both `fixed_by` and
    # `verified_against` anchors. Ask for JSON so the exact document paths it
    # rewrote can join the same tracked path set as the backlog ledger.
    repair_paths = list(LEDGER_PATHS)
    for sub, label in (("reanchor", "ledger-reanchor"),):
        argv = [sys.executable, str(tool), sub, "--docs", "--commit", "--json"]
        rc, text = _tool_mutation(argv,
                                  cwd=primary, label=label)
        payload = {}
        for line in reversed((text or "").splitlines()):
            try:
                candidate = json.loads(line)
            except (TypeError, json.JSONDecodeError):
                continue
            if isinstance(candidate, dict):
                payload = candidate
                break
        # A successful reanchor reports `doc_landed`; a failed transactional
        # reanchor reports the complete planned set as `doc_paths` after it has
        # rolled back.  Keep both paths in the restore set: the latter is the
        # only machine-readable way to recover an arbitrary document when the
        # child command exits before its success payload.
        doc_paths = payload.get("doc_landed") or payload.get("doc_paths") or []
        if not doc_paths:
            doc_paths = [item.get("path") for item in payload.get("doc_plan", [])
                         if isinstance(item, dict) and item.get("path")]
        for path in doc_paths:
            if isinstance(path, str) and path not in repair_paths:
                repair_paths.append(path)
        out["repair_paths"] = repair_paths
        out["steps"].append({"step": sub, "rc": rc})
        if rc != 0:
            out["ok"] = False
            out["error"] = f"{sub} exited {rc}: {text.strip()[:300]}"
            _repair_restore(primary, out, tuple(repair_paths))
            return out
    rc, dirty = _ledger_dirty(primary, tuple(repair_paths))
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
    # uncommitted filing got swept into a commit whose message claimed "everything here
    # was re-derived by a tool" even though it also contained that filing.
    # Measured: the repair commit contained COTENANT.json; without the add, it
    # contains only the file `reanchor` actually rewrote.
    crc, ctext = _git_mutation(["commit", "-m", _REPAIR_MESSAGE, "--", *repair_paths],
                               cwd=primary, label="ledger-repair-commit")
    if crc != 0:
        out["ok"] = False
        out["error"] = f"repair commit failed: {ctext.strip()[:300]}"
        _repair_restore(primary, out, tuple(repair_paths))
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


def _delegated_records_for_path(state: str | None, worktree: str) -> list[dict[str, Any]]:
    """Return active delegated records for a normalized worktree path.

    Ledger read failures are treated as no delegation marker: this helper is an
    authority lookup, not a second registry parser, and cutover's other guards still
    fail closed on stale or untrusted worktree state.
    """
    path = Path(state).resolve() if state else wr.default_state_path()
    try:
        data = wr.load_state(path)
    except (OSError, ValueError, json.JSONDecodeError):
        return []
    target = _norm(worktree)
    return [
        r for r in data.get("records", [])
        if r.get("status") == wr.STATUS_ACTIVE
        and r.get("delegated") is True
        and r.get("path")
        and _norm(r["path"]) == target
    ]


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
    "integration-ref-unresolvable": EXIT_BLOCK,
    "integration-ref-not-landed": EXIT_BLOCK,
    "integration-sources-active": EXIT_BLOCK,
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


def _close_registry_for_teardown(
    state: str | None, branch: str,
) -> tuple[list[str], list[str], int, dict[str, Any]]:
    """Atomically recheck integration dependencies and close the target record.

    The earlier read-only guard makes dry-run useful, but it cannot authorize a
    destructive commit: a source reservation can appear after that read. This is
    the linearization point shared with `claim_integration_sources`. Once this
    returns success, the integration record is terminal, and new source claims
    reject it as an owner before any git path is removed.
    """
    state_path = Path(state).resolve() if state else wr.default_state_path()
    with wr._ledger_lock(state_path):
        ledger = wr.load_state(state_path)
        active = [r for r in ledger.get("records") or []
                  if r.get("status") == wr.STATUS_ACTIVE]
        owned = sorted(
            str(r.get("branch")) for r in active
            if (r.get("integration_owner") or {}).get("branch") == branch
        )
        if owned:
            return owned, [], EXIT_BLOCK, {"reason": "integration sources active"}
        targets = [r for r in active if r.get("branch") == branch]
        claimed = sorted({str(ticket) for r in targets
                          for ticket in (r.get("backlog") or [])})
        if not targets:
            # Idempotent retry after ledger closure but before git teardown finished.
            return [], claimed, EXIT_OK, {"action": "already-closed"}
        ns = argparse.Namespace(
            state=str(state_path), at=None, branch=branch, path=None,
            status="merged", json=True,
        )
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = wr.cmd_resolve(ns)
        try:
            payload = json.loads(buf.getvalue())
        except json.JSONDecodeError:
            payload = {"reason": "registry returned unreadable resolve output"}
        return [], claimed, rc, payload


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

    registry_state = (Path(args.state).resolve() if args.state
                      else wr.default_state_path())
    owned_sources = wr.integration_sources_owned_by(registry_state, branch)
    if owned_sources:
        return _refuse(
            "integration-sources-active",
            f"integration branch {branch!r} still owns {len(owned_sources)} active "
            "source branch(es). Resolve those sources after the final integration "
            "has landed in the trunk, or abort the integration to release them; "
            "deleting this tree first would erase the only durable ownership edge.",
            branch=branch, source_branches=owned_sources,
        )

    # nit2 LANDED FLOOR: resolve is a force-discard (worktree remove --force + branch -D).
    # Called out of order (before cutover) it would vaporize unlanded work. Refuse a
    # branch whose net change is NOT already in base — using the registry's tree-diff
    # containment (never git cherry; same authority the sweep trusts). --force overrides.
    root = primary_root()
    audit = None
    integrated_closures: list[str] = []
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
                landed_rc, _ = _git(
                    ["merge-base", "--is-ancestor", args.via_integration, args.base],
                    cwd=root,
                )
                if landed_rc != EXIT_OK:
                    return _refuse(
                        "integration-ref-not-landed",
                        f"integration ref {args.via_integration!r} is not an ancestor "
                        f"of {args.base!r}. It may contain matching patches without "
                        "having landed them in the trunk, so it cannot authorize "
                        "source teardown. Land the final integration first, then use "
                        f"`--via-integration {args.base}`.",
                        branch=branch, integration_ref=args.via_integration,
                        base=args.base,
                    )
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

    # An explicit integration REF is the batch model's equivalent of cutover: it
    # proves this source branch reached the named integration/trunk ref after
    # cherry-pick or conflict resolution. Preserve the hunter's staged evidence
    # before teardown, using that ref's actual tip just as ordinary cutover stamps
    # its landed trunk tip. This must also run when the source is already an
    # ancestor of the base (the normal no-diff path), because resolve otherwise
    # deletes the only branch identity that can connect the queue row to the
    # landed work and anchor leaves it unstamped forever (IMP-20260808-b6f69d).
    if args.commit and args.via_integration:
        landed_ref_rc, _ = _git(
            ["merge-base", "--is-ancestor", args.via_integration, args.base],
            cwd=root,
        )
        if landed_ref_rc != EXIT_OK:
            return _refuse(
                "integration-ref-not-landed",
                f"integration ref {args.via_integration!r} is not an ancestor "
                f"of {args.base!r}; refusing to stamp staged closures before "
                "the batch identity is on the target trunk",
                branch=branch, integration_ref=args.via_integration,
                base=args.base,
            )
        rc, integrated_sha = _git(["rev-parse", f"{args.via_integration}^{{commit}}"],
                                  cwd=root)
        if rc != 0 or not integrated_sha.strip():
            return _refuse(
                "integration-ref-unresolvable",
                f"integration audit passed but {args.via_integration!r} no longer "
                "resolves to a commit; refusing teardown before losing the staged "
                "closure's branch identity",
                branch=branch,
            )
        # A source resolver is invoked with the integration branch as its
        # corroborating REF by close-wave.  The staged row belongs to that
        # integration branch, not to the source branch being torn down.  Keep
        # stamping the source identity for the direct/legacy path, and stamp
        # the explicit integration identity as well; dedupe so a resolver of
        # the integration branch itself remains idempotent.
        stamp_branches = [branch]
        if args.via_integration != args.base:
            stamp_branches.append(args.via_integration)
        for stamp_branch in dict.fromkeys(stamp_branches):
            integrated_closures.extend(
                _stamp_anchor_queue(root, stamp_branch, integrated_sha.strip())
            )

    # teardown MUST run from the primary root: step 1 removes the target worktree,
    # which may be the very directory this process was invoked from. For the same
    # reason the gate-cache path is resolved NOW — its default-state branch derives
    # the ledger anchor from the process cwd, which teardown may be about to remove.
    gate_cache = _gate_record_path(args.state, worktree)
    gate_progress = _gate_progress_path(args.state, worktree)
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
    newly_owned, claimed_at_teardown, registry_rc, registry_payload = \
        _close_registry_for_teardown(args.state, branch)
    if newly_owned:
        return _refuse(
            "integration-sources-active",
            f"integration branch {branch!r} gained {len(newly_owned)} active "
            "source branch(es) while resolve was preparing. Nothing was deleted; "
            "resolve those sources after the final integration lands, then retry.",
            branch=branch, source_branches=newly_owned,
        )
    if registry_rc != EXIT_OK:
        return _refuse(
            "unsafe-step",
            f"registry refused to close {branch!r} before git teardown: "
            f"{registry_payload.get('reason', registry_payload)}",
            branch=branch, registry=registry_payload,
        )
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

    # The live progress sidecar follows the verdict's lifecycle. Use the same short
    # lock as publishers so a concurrent gate cannot interleave its atomic replace
    # with this cleanup.
    gate_progress_removed = False
    try:
        with _gate_progress_lock(args.state):
            if gate_progress.exists():
                gate_progress.unlink()
                gate_progress_removed = True
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
               "gate_progress_removed": gate_progress_removed,
               "gate_logs_removed": gate_logs_removed,
               "staged_closures": integrated_closures,
               "pending_anchor": pending_anchor,
               "claimed_without_closure": claimed_open}
    human = ["# resolve (committed): ledger -> merged"]
    for r in results:
        human.append(f"  {'✓' if r['ok'] else '✗'} {r['cmd']}   # {r['label']}")
    if gate_cache_removed:
        human.append("  ✓ dropped gate-record cache")
    if gate_progress_removed:
        human.append("  ✓ dropped gate-progress sidecar")
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


if __name__ == "__main__":
    sys.exit(main())
