"""Integration state machine for the worktree delivery tool.

This seam owns source hand-back validation, cherry-pick queue state, and resumable
integration transitions.  The compatibility composition root re-exports its private
helpers so historical tests and callers keep the same patch points.
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


def bind_runtime(namespace: dict[str, object]) -> None:
    """Bind the runtime namespace used by extracted delivery functions."""
    for name, value in namespace.items():
        if not name.startswith("__"):
            globals()[name] = value
    if namespace.get("__file__"):
        globals()["__file__"] = namespace["__file__"]


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

    try:
        gate_tier = normalize_gate_tier(getattr(args, "gate_tier", None))
    except GateTierError as exc:
        _emit({"schema": INTEGRATE_SCHEMA, "step": "integrate", "slug": args.slug,
               "error": str(exc)}, args.json, f"✗ integrate refused: {exc}")
        return EXIT_USAGE
    total = sum(len(p["commits"]) for p in plan)
    if not args.commit:
        action = ("pick only and stop before the gate" if args.no_gate
                  else "pick the commits, then run ONE gate")
        _emit({"schema": INTEGRATE_SCHEMA, "step": "integrate", "mode": "dry-run",
               "slug": args.slug, "trunk": trunk, "branches": list(args.branches),
               "plan": plan, "commits": total, "handoff": handoff,
               "gate_tier": gate_tier,
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
        "gate_tier": gate_tier,
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
    try:
        requested_tier = normalize_gate_tier(getattr(args, "gate_tier", None))
        persisted_tier = normalize_gate_tier(st.get("gate_tier"))
    except GateTierError as exc:
        _emit({"schema": INTEGRATE_SCHEMA, "step": "integrate", "operation": "append",
               "mode": "refused", "slug": args.slug, "error": str(exc)}, args.json,
              f"✗ integrate --append refused: {exc}")
        return EXIT_USAGE
    if requested_tier != persisted_tier:
        _emit({
            "schema": INTEGRATE_SCHEMA, "step": "integrate", "operation": "append",
            "mode": "refused", "slug": args.slug,
            "error": "gate tier must match the persisted integration state",
            "persisted_gate_tier": persisted_tier,
            "requested_gate_tier": requested_tier,
        }, args.json,
            "✗ integrate --append refused: repeat the original --gate-tier exactly")
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
        "gate_tier": st.get("gate_tier", DEFAULT_GATE_TIER),
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

    gate_tier = normalize_gate_tier(st.get("gate_tier"))
    grc, gpay = _land_step(
        cmd_gate, state=args.state, json=True, base=args.base, worktree=wt,
        gate_tier=gate_tier, receipt_line=False, plan_only=False,
    )
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
        "gate_tier": gate_tier,
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
    try:
        requested_tier = normalize_gate_tier(getattr(args, "gate_tier", None))
        persisted_tier = normalize_gate_tier(st.get("gate_tier"))
    except GateTierError as exc:
        _emit({"schema": INTEGRATE_SCHEMA, "step": "integrate", "mode": "refused",
               "slug": args.slug, "state_file": str(spath), "error": str(exc)},
              args.json, f"✗ integrate --continue refused: {exc}")
        return EXIT_USAGE
    if requested_tier != persisted_tier:
        _emit({
            "schema": INTEGRATE_SCHEMA, "step": "integrate", "mode": "refused",
            "slug": args.slug, "state_file": str(spath),
            "error": "gate tier must match the persisted integration state",
            "persisted_gate_tier": persisted_tier,
            "requested_gate_tier": requested_tier,
        }, args.json,
            "✗ integrate --continue refused: repeat the original --gate-tier exactly")
        return EXIT_USAGE
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
    gate_tier_suffix = (f" --gate-tier {persisted_tier}"
                        if persisted_tier != DEFAULT_GATE_TIER else "")
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
                        f"--continue{independent_suffix}{gate_tier_suffix}; or "
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
               "next_step": teardown, "gate_tier": st.get("gate_tier", DEFAULT_GATE_TIER)}, args.json,
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
