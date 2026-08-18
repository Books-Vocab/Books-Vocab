"""Primary worktree command handlers.

This module contains preflight/open/adopt/freeze/sync/deploy command sequencing.  Shared
helpers are injected after the runtime composition root is defined.
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
    """Bind the runtime namespace used by extracted command handlers."""
    for name, value in namespace.items():
        if not name.startswith("__"):
            globals()[name] = value
    if namespace.get("__file__"):
        globals()["__file__"] = namespace["__file__"]

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

        # Backlog writers use store -> ledger ordering.  Keep the store lock
        # across the snapshot and registry reservation so admission cannot
        # publish a ticket set from a moving backlog.
        with backlog_tool._store_lock(store):
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


def cmd_campaign_abort(args: argparse.Namespace) -> int:
    """Manager-only cleanup for a campaign that never produced child closure."""
    if getattr(args, "operator", "manager") != "manager":
        _emit({"schema": SCHEMA, "step": "campaign-abort",
               "error": "operator refused", "operator": args.operator,
               "reason": "only Manager may abort campaign admission"}, args.json,
              "✗ campaign-abort refused: only Manager may abort campaign admission")
        return EXIT_BLOCK
    try:
        result = wr.abort_campaign(
            wr._state_path(args), campaign_id=args.campaign,
            reason=args.reason, commit=args.commit,
        )
    except (OSError, ValueError, TypeError) as exc:
        _emit({"schema": SCHEMA, "step": "campaign-abort",
               "error": "campaign abort failed", "detail": str(exc)}, args.json,
              f"✗ campaign-abort failed: {exc}")
        return EXIT_BLOCK
    if not result.get("ok"):
        _emit({"schema": SCHEMA, "step": "campaign-abort", **result}, args.json,
              f"✗ campaign-abort refused: {result.get('reason', result)}")
        return EXIT_BLOCK
    _emit({"schema": SCHEMA, "step": "campaign-abort", **result}, args.json,
          f"✓ campaign-abort {result['mode']}: {args.campaign} — {args.reason}")
    return EXIT_OK


def cmd_campaign_retire(args: argparse.Namespace) -> int:
    """Manager-only archival of a clean campaign whose work was not landed."""
    if getattr(args, "operator", "manager") != "manager":
        _emit({"schema": SCHEMA, "step": "campaign-retire",
               "error": "operator refused", "operator": args.operator,
               "reason": "only Manager may retire a campaign"}, args.json,
              "✗ campaign-retire refused: only Manager may retire a campaign")
        return EXIT_BLOCK
    try:
        result = wr.retire_campaign(
            wr._state_path(args), campaign_id=args.campaign,
            reason=args.reason, commit=args.commit,
        )
    except (OSError, ValueError, TypeError) as exc:
        _emit({"schema": SCHEMA, "step": "campaign-retire",
               "error": "campaign retirement failed", "detail": str(exc)}, args.json,
              f"✗ campaign-retire failed: {exc}")
        return EXIT_BLOCK
    if not result.get("ok"):
        _emit({"schema": SCHEMA, "step": "campaign-retire", **result}, args.json,
              f"✗ campaign-retire refused: {result.get('reason', result)}")
        return EXIT_BLOCK
    _emit({"schema": SCHEMA, "step": "campaign-retire", **result}, args.json,
          f"✓ campaign-retire {result['mode']}: {args.campaign} — {args.reason}")
    return EXIT_OK


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
    scope_inline = getattr(args, "scope", None)
    scope_file = getattr(args, "scope_file", None)
    codex_thread_id = getattr(args, "codex_thread_id", None)
    work_mode = getattr(args, "work_mode", None)
    scope_declared = scope_inline is not None or scope_file is not None
    if scope_declared and (args.backlog is not None or next_backlog):
        _emit({"schema": SCHEMA, "step": "open",
               "error": "direct Scope cannot be combined with a ticket claim"}, args.json,
              "✗ --scope/--scope-file is only for a direct worktree; ticketed Scope comes from tickets")
        return EXIT_USAGE
    if scope_declared and (getattr(args, "campaign", None) or getattr(args, "partition", None)):
        _emit({"schema": SCHEMA, "step": "open",
               "error": "direct Scope cannot be combined with a campaign claim"}, args.json,
              "✗ campaign worktrees derive Scope from their tickets")
        return EXIT_USAGE
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
    if next_backlog and args.backlog is not None:
        _emit({"schema": SCHEMA, "step": "open",
               "error": "--backlog and --next-backlog are mutually exclusive"}, args.json,
              "✗ --backlog and --next-backlog are mutually exclusive")
        return EXIT_USAGE
    if campaign_id and not next_backlog and args.backlog is None:
        _emit({"schema": SCHEMA, "step": "open",
               "error": "campaign claims require --backlog or --next-backlog"}, args.json,
              "✗ campaign claims require --backlog or --next-backlog")
        return EXIT_USAGE
    if campaign_id and args.backlog is not None and len(args.backlog) != 1:
        _emit({"schema": SCHEMA, "step": "open",
               "error": "campaign named claims require exactly one ticket"}, args.json,
              "✗ campaign named claims require exactly one ticket")
        return EXIT_USAGE

    mode_error = validate_work_mode(
        work_mode,
        has_scope=scope_declared,
        has_ticket_claim=bool(args.backlog) or next_backlog
                         or (bool(campaign_id) and args.backlog is not None),
        has_campaign=bool(campaign_id),
    )
    if mode_error:
        _emit({"schema": SCHEMA, "step": "open", "error": "invalid-work-mode",
               "reason": "invalid-work-mode",
               "detail": mode_error, "work_mode": work_mode}, args.json,
              f"✗ open refused: {mode_error}")
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
        claim_fn = (_claim_named_campaign_backlog
                    if args.backlog is not None
                    else _claim_next_campaign_backlog)
        claim_kwargs = {
            "root": root, "state_arg": args.state, "path": path,
            "branch": branch, "intent": args.intent, "base": base,
            "campaign_id": campaign_id, "partition_id": partition_id,
            "delegated": delegated, "codex_thread_id": codex_thread_id,
            "work_mode": work_mode,
        }
        if args.backlog is not None:
            claim_kwargs["ticket_id"] = args.backlog[0]
        reg_rc, reg_payload, wanted, selection = claim_fn(**claim_kwargs)
        if reg_rc == EXIT_OK:
            campaign_claim = {"campaign_id": campaign_id, "partition": partition_id,
                              "ticket": wanted[0], "branch": branch,
                              "reservation": (reg_payload or {}).get("reservation")}
    elif next_backlog:
        reg_rc, reg_payload, wanted, selection = _claim_next_backlog(
            root=root, state_arg=args.state, path=path, branch=branch,
            intent=args.intent, base=base, delegated=delegated,
            codex_thread_id=codex_thread_id,
            work_mode=work_mode,
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
             *( ["--scope", scope_inline] if scope_inline is not None else
                ["--scope-file", scope_file] if scope_file is not None else [] ),
             *( ["--codex-thread-id", codex_thread_id] if codex_thread_id is not None else [] ),
             *( ["--work-mode", work_mode] if work_mode is not None else [] ),
             *claim_argv, "--exclusive", "--json"])
    if reg_rc != EXIT_OK:
        conflicts = (reg_payload or {}).get("conflicts", [])
        held = ", ".join(
            f"{','.join(c.get('backlog') or [])} by [{c.get('branch')}] at {c.get('path')}"
            for c in conflicts) or (reg_payload or {}).get("reason", "register refused")
        error = ((reg_payload or {}).get("reason")
                 if (next_backlog or campaign_id) else "claim refused")
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
               "scope_declared": scope_declared,
               "codex_thread_id": codex_thread_id,
               "work_mode": work_mode,
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
    scope_inline = getattr(args, "scope", None)
    scope_file = getattr(args, "scope_file", None)
    codex_thread_id = getattr(args, "codex_thread_id", None)
    work_mode = getattr(args, "work_mode", None)
    scope_declared = scope_inline is not None or scope_file is not None
    if scope_declared and args.backlog is not None:
        _emit({"schema": SCHEMA, "step": "adopt",
               "error": "direct Scope cannot be combined with a ticket claim"}, args.json,
              "✗ --scope/--scope-file is only for a direct worktree; ticketed Scope comes from tickets")
        return EXIT_USAGE
    mode_error = validate_work_mode(
        work_mode,
        has_scope=scope_declared,
        has_ticket_claim=bool(wanted),
        has_campaign=False,
    )
    if mode_error:
        _emit({"schema": SCHEMA, "step": "adopt", "error": "invalid-work-mode",
               "reason": "invalid-work-mode",
               "detail": mode_error, "work_mode": work_mode}, args.json,
              f"✗ adopt refused: {mode_error}")
        return EXIT_USAGE
    if _refuse_unclaimable(Path(primary_root()), wanted, args, "adopt",
                           branch) is not None:
        return EXIT_BLOCK
    claim_argv = ["--backlog", *wanted] if args.backlog is not None else []  # see cmd_open
    reg_rc, reg_payload = _registry(
        ["register", "--state", state, "--path", worktree, "--branch", branch,
         "--intent", args.intent, "--base", args.base,
         *( ["--scope", scope_inline] if scope_inline is not None else
            ["--scope-file", scope_file] if scope_file is not None else [] ),
         *( ["--codex-thread-id", codex_thread_id] if codex_thread_id is not None else [] ),
         *( ["--work-mode", work_mode] if work_mode is not None else [] ),
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
               "backlog": wanted, "scope_declared": scope_declared,
               "codex_thread_id": codex_thread_id, "work_mode": work_mode,
               "conflicts": conflicts, "registered": ok}
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
    refusal = operator_refusal(
        command="sync-main", operator=getattr(args, "operator", "manager"),
        commit=args.commit, manager_only=True,
    )
    if refusal:
        _emit({"schema": SCHEMA, "step": "sync-main", "verdict": "refused",
               **refusal}, args.json,
              "✗ sync-main refused: only Manager may move primary main")
        return EXIT_BLOCK
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
    refusal = operator_refusal(
        command="sync", operator=getattr(args, "operator", "manager"),
        commit=args.commit, manager_only=True,
    )
    if refusal:
        _emit({"schema": SCHEMA, "step": "sync", "verdict": "refused",
               **refusal}, args.json,
              "✗ sync refused: only Manager may update origin/main")
        return EXIT_BLOCK
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
    refusal = operator_refusal(
        command="deploy", operator=getattr(args, "operator", "manager"),
        commit=args.commit, manager_only=True,
    )
    if refusal:
        _emit({"schema": SCHEMA, "step": "deploy", "verdict": "refused",
               **refusal}, args.json,
              "✗ deploy refused: only Manager may publish the release plane")
        return EXIT_BLOCK
    dest = _dest_from_upstream(args.upstream, "deploy", args.json)
    if dest is None:
        return EXIT_USAGE
    return _guarded_advance(src_branch=BASE_DEFAULT, dest_branch=dest, production=True,
                            step="deploy", commit=args.commit, as_json=args.json, state=args.state)
