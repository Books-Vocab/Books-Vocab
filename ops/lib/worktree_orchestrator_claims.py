"""Backlog claim and campaign reservation helpers.

The registry/backlog claim rules remain private-name compatible while moving out of the
CLI composition root.  Shared tool modules and constants are bound after import.
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
    """Bind the runtime namespace used by extracted claim helpers."""
    for name, value in namespace.items():
        if not name.startswith("__"):
            globals()[name] = value
    if namespace.get("__file__"):
        globals()["__file__"] = namespace["__file__"]

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
                # set by separate brief/Scope ratchets; a repair line that omits them teaches
                # a command whose result is refused, which is worse than no hint —
                # the agent believes it followed the tool.
                "repair": f"groom it first: `ops/backlog.py update {entry_id} --plan "
                          f"… --acceptance … --fix-site … --acceptance-cmd … "
                          f"--brief … --scope … "
                          f"--groomed-at <today> --groomed-by <you> --commit` "
                          f"(--scope must be a structured JSON file claim with "
                          f"files[] and add|modify; --brief remains one plain "
                          f"sentence for whoever SORTS the board: what breaks "
                          f"and who feels it). "
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
                          f"already groomed, unresolved, unclaimed, unblocked, "
                          f"and contract-ready — i.e. the ones you can take right "
                          f"now without grooming or repairing the contract "
                          f"first"})
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
    codex_thread_id: str | None = None, work_mode: str | None = None,
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
            scope=None, scope_file=None, codex_thread_id=codex_thread_id,
            work_mode=work_mode,
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
    delegated: bool | None = None, codex_thread_id: str | None = None,
    work_mode: str | None = None,
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
            codex_thread_id=codex_thread_id,
            work_mode=work_mode,
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
