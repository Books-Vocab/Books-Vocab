"""Delivery lifecycle orchestration for the worktree tool.

This seam owns integrate/close-wave state machines and their receipts.  It deliberately
binds the shared operational namespace after the command runtime is fully defined so
the historical private helper names and test patch points remain stable.
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
