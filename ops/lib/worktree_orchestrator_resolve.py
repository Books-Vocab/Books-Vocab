"""Resolve target identity, audit integrated commits, and teardown worktrees."""

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
from lib.exit_codes import EXIT_BLOCK, EXIT_OK, EXIT_TOOL_ERROR, EXIT_USAGE, EXIT_WARN  # noqa: E402


def bind_runtime(namespace: dict[str, object]) -> None:
    """Bind the runtime namespace used by extracted lifecycle functions."""
    for name, value in namespace.items():
        if not name.startswith("__"):
            globals()[name] = value
    if namespace.get("__file__"):
        globals()["__file__"] = namespace["__file__"]


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

    refusal = operator_refusal(
        command="resolve --via-integration",
        operator=getattr(args, "operator", "manager"),
        commit=args.commit and bool(getattr(args, "via_integration", None)),
        manager_only=True,
    )
    if refusal:
        _emit({"schema": SCHEMA, "step": "resolve", "error": "operator refused",
               "worktree": worktree, **refusal}, args.json,
              "✗ resolve --via-integration refused: only Manager may resolve landed sources")
        return EXIT_BLOCK

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
