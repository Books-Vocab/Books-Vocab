"""Gate and cutover command orchestration.

Low-level gate execution lives in worktree_orchestrator_core; this module owns the
CLI-level gate/cutover sequencing and binds shared helpers after runtime import.
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

from lib import worktree_gate_tiers as gate_tiers

def bind_runtime(namespace: dict[str, object]) -> None:
    """Bind the runtime namespace used by extracted gate commands."""
    for name, value in namespace.items():
        if not name.startswith("__"):
            globals()[name] = value
    if namespace.get("__file__"):
            globals()["__file__"] = namespace["__file__"]


def _gate_plan_projection(plan: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return the JSON-stable gate definitions used for plan identity checks."""
    return [json.loads(json.dumps(spec, ensure_ascii=False, sort_keys=True)) for spec in plan]


def _gate_plan_digest(plan: list[dict[str, Any]]) -> str:
    projected = _gate_plan_projection(plan)
    return hashlib.sha256(
        json.dumps(projected, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _current_full_gate_plan(
    worktree: str, changed_files: list[str], gate_tier: str, base: str | None = None,
) -> list[dict[str, Any]]:
    """Rebuild the canonical plan at cutover instead of trusting record contents."""
    full_plan = plan_gates(
        changed_files,
        ops_test_exists=lambda rel: (Path(worktree) / rel).is_file(),
        base=base or "main",
        ops_tests_dir_exists=lambda: (Path(worktree) / "ops/tests").is_dir(),
        path_exists=lambda rel: (Path(worktree) / rel).is_file(),
    )
    if gate_tier == "S4":
        full_plan = [*full_plan, *gate_tiers.release_gate_plan()]
    return full_plan


def _deferral_store_candidates(worktree: str | Path) -> list[Path]:
    """Return the worktree and primary backlog stores, without duplicating a path."""
    candidates = [
        Path(worktree) / "docs" / "runbook" / "backlog",
        Path(primary_root()) / "docs" / "runbook" / "backlog",
    ]
    unique: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved not in seen:
            seen.add(resolved)
            unique.append(resolved)
    return unique


def _load_deferral_ticket(worktree: str | Path, ticket_id: str) -> tuple[dict[str, Any] | None, str | None]:
    """Load one existing ticket from the candidate stores.

    Deferral admission is deliberately fail-closed: a missing or malformed ticket is
    not a reason to turn a red gate into a warning.  The lookup is read-only and does
    not invoke backlog lifecycle commands, so this feature does not create a second
    ticket/status model.
    """
    for store in _deferral_store_candidates(worktree):
        try:
            payload = backlog_tool.load_entry(store, ticket_id)
        except backlog_tool.EntryNotFound:
            continue
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            return None, f"ticket {ticket_id} could not be read from {store}: {exc}"
        if not isinstance(payload, dict):
            return None, f"ticket {ticket_id} is not a JSON object"
        if payload.get("id") != ticket_id:
            return None, f"ticket {ticket_id} has mismatched payload id {payload.get('id')!r}"
        return payload, None
    return None, f"backlog ticket {ticket_id} was not found"


def _validate_gate_deferrals(
    raw_requests: Iterable[str] | None,
    full_plan: list[dict[str, Any]],
    selected_plan: list[dict[str, Any]],
    worktree: str | Path,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Admit explicit ``gate=ticket`` exceptions before any expensive gate runs."""
    admitted: list[dict[str, Any]] = []
    problems: list[str] = []
    requests = list(raw_requests or [])
    full_by_name = {str(spec.get("name")): spec for spec in full_plan}
    selected_names = {str(spec.get("name")) for spec in selected_plan}
    seen_gates: set[str] = set()
    for raw in requests:
        try:
            gate_name, ticket_id = gate_tiers.parse_deferral(raw)
        except gate_tiers.GateTierError as exc:
            problems.append(str(exc))
            continue
        if gate_name in seen_gates:
            problems.append(f"gate {gate_name!r} has more than one deferral request")
            continue
        seen_gates.add(gate_name)
        spec = full_by_name.get(gate_name)
        if spec is None:
            problems.append(f"deferral names unknown gate {gate_name!r}")
            continue
        if gate_name not in selected_names:
            problems.append(
                f"gate {gate_name!r} was not selected at this tier; raise --gate-tier "
                "or remove the deferral"
            )
            continue
        ticket, error = _load_deferral_ticket(worktree, ticket_id)
        if error:
            problems.append(error)
            continue
        assert ticket is not None
        status = str(ticket.get("status") or "")
        severity = str(ticket.get("severity") or "")
        if status not in {"open", "triaged", "contract-blocked"}:
            problems.append(
                f"ticket {ticket_id} status={status} cannot defer a failing gate"
            )
            continue
        allowed, reason = gate_tiers.deferral_allowed(spec, severity)
        if not allowed:
            problems.append(
                f"ticket {ticket_id} cannot defer gate {gate_name!r}: {reason}"
            )
            continue
        admitted.append({
            "gate": gate_name,
            "ticket_id": ticket_id,
            "status": status,
            "severity": severity,
            "tier": spec.get("tier", "S2"),
        })
    return admitted, problems


def _validate_recorded_deferrals(
    worktree: str | Path,
    failures: object,
    full_plan: list[dict[str, Any]],
) -> str | None:
    """Recheck carried tickets at cutover; gate-time admission is not permanent."""
    if not isinstance(failures, list):
        return "gate record deferred_failures is malformed — re-run gate"
    specs = {str(spec.get("name")): spec for spec in full_plan}
    failure_names: set[str] = set()
    for item in failures:
        if not isinstance(item, dict):
            return "gate record contains a malformed deferred failure — re-run gate"
        gate_name = str(item.get("gate") or "")
        ticket_id = str(item.get("ticket_id") or "")
        if not gate_name or not ticket_id or gate_name in failure_names:
            return "gate record contains an invalid or duplicate deferred failure — re-run gate"
        failure_names.add(gate_name)
        spec = specs.get(gate_name)
        if spec is None:
            return f"deferred gate {gate_name!r} is absent from the current plan — re-run gate"
        ticket, error = _load_deferral_ticket(worktree, ticket_id)
        if error:
            return f"deferred ticket is no longer valid: {error}"
        assert ticket is not None
        status = str(ticket.get("status") or "")
        severity = str(ticket.get("severity") or "")
        if status not in {"open", "triaged", "contract-blocked"}:
            return (
                f"deferred ticket {ticket_id} now has status={status}; it must be reopened "
                "before cutover"
            )
        allowed, reason = gate_tiers.deferral_allowed(spec, severity)
        if not allowed:
            return f"deferred ticket {ticket_id} is no longer admissible: {reason}"
    return None


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
    refusal = operator_refusal(
        command="gate", operator=getattr(args, "operator", "manager"),
        commit=not getattr(args, "plan_only", False), manager_only=True,
    )
    if refusal:
        _emit({"schema": GATE_SCHEMA, "step": "gate", "error": "operator refused",
               **refusal}, args.json,
              "✗ gate refused: only Manager may create a Gate verdict")
        return EXIT_BLOCK
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
    full_plan = plan_gates(
        changed,
        ops_test_exists=lambda rel: (Path(worktree) / rel).is_file(),
        base=args.base,
        ops_tests_dir_exists=lambda: (Path(worktree) / "ops/tests").is_dir(),
        path_exists=lambda rel: (Path(worktree) / rel).is_file(),
    )
    try:
        gate_tier = normalize_gate_tier(getattr(args, "gate_tier", None))
    except GateTierError as exc:
        _emit({"schema": GATE_SCHEMA, "step": "gate", "error": str(exc),
               "worktree": worktree}, args.json, f"✗ gate refused: {exc}")
        return EXIT_USAGE
    if gate_tier == "S4":
        full_plan = [*full_plan, *gate_tiers.release_gate_plan()]
    plan, deferred_plan = select_gate_plan(full_plan, gate_tier)
    deferral_requests, deferral_problems = _validate_gate_deferrals(
        getattr(args, "defer_gate", None), full_plan, plan, worktree,
    )
    if deferral_problems:
        payload = {
            "schema": GATE_SCHEMA,
            "step": "gate",
            "error": "gate deferral admission failed",
            "problems": deferral_problems,
            "gate_tier": gate_tier,
            "worktree": worktree,
        }
        _emit(payload, args.json,
              "✗ gate refused: gate deferral admission failed\n"
              + "\n".join(f"  - {problem}" for problem in deferral_problems))
        return EXIT_USAGE
    deferrals_by_gate = {item["gate"]: item for item in deferral_requests}
    required_tier = required_cutover_tier(changed, full_plan)
    results: list[dict[str, Any]] = []
    deferred_failures: list[dict[str, Any]] = []
    rec_path = _gate_record_path(args.state, worktree)
    progress_path = _gate_progress_path(args.state, worktree)
    progress_started = time.monotonic()
    run_id = f"{head[:12]}-{os.getpid()}-{time.monotonic_ns()}"
    print(f"[worktree][gate] phase=plan gates={len(plan)} tier={gate_tier} "
          f"deferred={len(deferred_plan)} progress={progress_path} "
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
            deferral = deferrals_by_gate.get(result.get("name"))
            if deferral is not None:
                original_status = result.get("status")
                disposition = "deferred" if original_status == "block" else "not-applied"
                result["deferral"] = {**deferral, "disposition": disposition}
                if original_status == "block":
                    result["original_status"] = original_status
                    result["status"] = "warn"
                    result["summary"] = (
                        f"deferred under {deferral['ticket_id']} "
                        f"(severity={deferral['severity']}); original failure: "
                        f"{result.get('summary', '')}"
                    )
                    deferred_failures.append({
                        **deferral,
                        "original_status": original_status,
                        "summary": result.get("summary", ""),
                    })
            results.append(result)
            result["tier"] = spec.get("tier", "S2")
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
              "gate_tier": gate_tier, "required_tier": required_tier,
              "canonical_plan_digest": _gate_plan_digest(full_plan),
              "selected_plan_digest": _gate_plan_digest(plan),
              "plan": _gate_plan_projection(plan),
              "deferred_plan": _gate_plan_projection(deferred_plan),
              "deferral_requests": deferral_requests,
              "deferred_failures": deferred_failures,
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
    receipt_line = (f"gate={verdict} tier={gate_tier} required={required_tier} "
                    f"deferred={len(deferred_plan)} carried={len(deferred_failures)} "
                    f"record={record_ref} "
                    f"head={head[:8]} orch={_orch_token(record)} gates={len(plan)} "
                    f"executed={executed_count} {breakdown} "
                    f"reused={len(reuse.get('reused', []))} rerun={len(reuse.get('rerun', []))}"
                    f"{no_changes}")
    if getattr(args, "receipt_line", False):
        print(receipt_line)
        return EXIT_OK if args.plan_only or verdict in ("pass", "warn") else EXIT_BLOCK

    lines = [f"# gate {verdict.upper()} tier={gate_tier} required={required_tier} "
             f"({len(changed)} changed file(s), {len(plan)} gate(s), "
             f"{len(deferred_plan)} deferred)  orchestrator={_orch_token(record)}"]
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
    if deferred_plan:
        lines.append("  ↷ deferred by tier: " + ", ".join(
            f"{g['name']}[{g.get('tier', 'S2')}]" for g in deferred_plan
        ))
    if deferred_failures:
        lines.append("  ↷ carried with backlog tickets: " + ", ".join(
            f"{item['gate']}→{item['ticket_id']}" for item in deferred_failures
        ))
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
    refusal = operator_refusal(
        command="cutover", operator=getattr(args, "operator", "manager"),
        commit=args.commit, manager_only=True,
    )
    if refusal:
        _emit({"schema": SCHEMA, "step": "cutover", "error": "operator refused",
               "landed": False, **refusal}, args.json,
              "✗ cutover refused: only Manager may land primary main")
        return EXIT_BLOCK
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
    gate_tier: str | None = None
    required_tier: str | None = None
    if not rec_path.exists():
        refuse = "no gate verdict on record — run `gate` first"
    else:
        try:
            rec = json.loads(rec_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            payload = {
                "schema": SCHEMA,
                "step": "cutover",
                "error": f"gate record is unreadable: {type(exc).__name__}: {exc} — re-run gate",
                "worktree": worktree,
                "landed": False,
            }
            _emit(payload, args.json, f"✗ cutover refused: {payload['error']}")
            return EXIT_BLOCK
        if not isinstance(rec, dict):
            payload = {
                "schema": SCHEMA,
                "step": "cutover",
                "error": "gate record must be a JSON object — re-run gate",
                "worktree": worktree,
                "landed": False,
            }
            _emit(payload, args.json, f"✗ cutover refused: {payload['error']}")
            return EXIT_BLOCK
        verdict = rec.get("verdict")
        gated_head = rec.get("head_sha")
        planned_gates = rec.get("plan")
        deferred_planned_gates = rec.get("deferred_plan")
        changed_for_scope = rec.get("changed_files")
        plan_shape_ok = (
            isinstance(planned_gates, list)
            and all(isinstance(spec, dict) for spec in planned_gates)
            and isinstance(deferred_planned_gates, list)
            and all(isinstance(spec, dict) for spec in deferred_planned_gates)
        )
        changed_shape_ok = (
            isinstance(changed_for_scope, list)
            and all(isinstance(path, str) for path in changed_for_scope)
        )
        all_planned_gates = (
            [*planned_gates, *deferred_planned_gates]
            if plan_shape_ok else None
        )
        computed_required_tier: str | None = None
        if not changed_shape_ok:
            refuse = "gate record changed_files is malformed — re-run gate"
        elif not plan_shape_ok:
            refuse = "gate record is malformed (plan/deferred plan) — re-run gate"
        else:
            try:
                computed_required_tier = required_cutover_tier(
                    changed_for_scope, all_planned_gates
                )
            except (AttributeError, TypeError, ValueError) as exc:
                refuse = f"gate record plan metadata is malformed: {exc} — re-run gate"
        try:
            gate_tier = normalize_gate_tier(rec.get("gate_tier"))
            required_tier = normalize_gate_tier(
                rec.get("required_tier") or computed_required_tier
            )
            if (computed_required_tier is not None
                    and rec.get("required_tier") is not None
                    and required_tier != computed_required_tier):
                refuse = ("gate record required tier does not match its changed-file scope "
                           f"and available plan ({required_tier} != {computed_required_tier}) "
                           "— re-run `gate`")
        except GateTierError as exc:
            refuse = f"gate record has invalid tier metadata: {exc} — re-run `gate`"
        recorded_gates = rec.get("gates")
        gate_reuse = rec.get("gate_reuse") or (
            _reuse_summary(recorded_gates)
            if isinstance(recorded_gates, list) else {"reused": [], "rerun": []}
        )
        recorded_orchestrator = rec.get("orchestrator")
        if not isinstance(recorded_orchestrator, dict):
            refuse = refuse or "gate record orchestrator is malformed — re-run gate"
            rec_orch = None
        else:
            rec_orch = recorded_orchestrator.get("sha256")
        wt_orch = orch["worktree_copy_sha256"]
        # Every current receipt must be bound to the current scope and plan.  A
        # missing digest is not a backwards-compatible shortcut: allowing it
        # would turn a legacy-shaped JSON edit into a landable verdict.
        if not refuse:
            recorded_digest = rec.get("canonical_plan_digest")
            changed_for_plan = rec.get("changed_files")
            if not isinstance(recorded_digest, str) or not recorded_digest:
                refuse = "gate record has no canonical plan digest — re-run gate"
            elif not isinstance(planned_gates, list) or not isinstance(deferred_planned_gates, list):
                refuse = "gate record is malformed (plan/deferred plan) — re-run gate"
            elif not isinstance(changed_for_plan, list) or any(
                    not isinstance(path, str) for path in changed_for_plan):
                refuse = "gate record changed_files is malformed — re-run gate"
            else:
                try:
                    actual_changed = _changed_vs_base(worktree, args.base)
                    if actual_changed != changed_for_plan:
                        raise ValueError(
                            "gate record changed_files does not match the current worktree"
                        )
                    current_full_plan = _current_full_gate_plan(
                        worktree, changed_for_plan, gate_tier, args.base,
                    )
                    current_digest = _gate_plan_digest(current_full_plan)
                    current_selected_plan, current_deferred_plan = select_gate_plan(
                        current_full_plan, gate_tier,
                    )
                except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
                    refuse = f"could not rebuild canonical gate plan: {type(exc).__name__}: {exc}"
                else:
                    if current_digest != recorded_digest:
                        refuse = (
                            "gate record canonical plan differs from the current orchestrator "
                            "plan — re-run gate"
                        )
                    elif _gate_plan_digest(planned_gates) != _gate_plan_digest(current_selected_plan):
                        refuse = "gate record selected plan differs from the current plan — re-run gate"
                    elif _gate_plan_digest(deferred_planned_gates) != _gate_plan_digest(current_deferred_plan):
                        refuse = "gate record deferred plan differs from the current plan — re-run gate"
                    elif {str(spec.get("name")) for spec in planned_gates} != {
                            str(spec.get("name")) for spec in current_selected_plan
                    }:
                        refuse = "gate record selected gates do not match the current plan — re-run gate"
                    elif {str(spec.get("name")) for spec in deferred_planned_gates} != {
                            str(spec.get("name")) for spec in current_deferred_plan
                    }:
                        refuse = "gate record deferred gates do not match the current plan — re-run gate"
                    elif gate_tier == "S4" and not isinstance(
                            rec.get("selected_plan_digest"), str
                    ):
                        refuse = "S4 gate record has no selected plan digest — re-run gate"
                    elif gate_tier == "S4" and current_deferred_plan:
                        refuse = "S4 gate record has deferred gates — re-run gate"
                    elif gate_tier == "S4":
                        release_names = {spec["name"] for spec in gate_tiers.release_gate_plan()}
                        actual_names = {str(spec.get("name")) for spec in current_selected_plan}
                        missing_release = sorted(release_names - actual_names)
                        if missing_release:
                            refuse = (
                                "S4 gate record is missing release gates: "
                                + ", ".join(missing_release) + " — re-run gate"
                            )
                    if (not refuse and isinstance(rec.get("selected_plan_digest"), str)
                            and rec["selected_plan_digest"]
                            != _gate_plan_digest(planned_gates)):
                        refuse = "gate record selected plan digest is inconsistent — re-run gate"
                    if not refuse:
                        refuse = _validate_recorded_deferrals(
                            worktree, rec.get("deferred_failures"), current_full_plan,
                        )
        if refuse:
            pass
        elif TIER_RANK[gate_tier] < TIER_RANK[required_tier]:
            refuse = (f"gate tier {gate_tier} is below the required {required_tier} "
                      "for this change set — re-run gate at the required tier")
        elif rec.get("head_sha") != head:
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
        elif gate_tier == "S4" and verdict != "pass":
            refuse = ("S4 release gate must be fully green (pass); it cannot land with "
                      f"verdict {verdict!r} — resolve warnings and re-run `gate`")
        elif gate_tier == "S4" and rec.get("deferred_failures"):
            refuse = "S4 release gate has deferred failures — release checks cannot be carried"
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
        elif any(not isinstance(gate, dict) for gate in recorded_gates):
            refuse = "gate record contains a non-object gate result — re-run gate"
        elif len({str(gate.get("name")) for gate in recorded_gates}) != len(recorded_gates):
            refuse = "gate record contains duplicate gate results — re-run gate"
        elif {str(gate.get("name")) for gate in recorded_gates} != {
                str(gate.get("name")) for gate in planned_gates}:
            refuse = "gate results do not match the canonical plan — re-run gate"
        elif any(
                gate.get("status") == "warn" and gate.get("original_status") == "block"
                and not any(item.get("gate") == gate.get("name")
                            for item in rec.get("deferred_failures", [])
                            if isinstance(item, dict))
                for gate in recorded_gates
        ):
            refuse = "a deferred warning has no current ticket evidence — re-run gate"
        elif any(
                item.get("gate") not in {
                    gate.get("name") for gate in recorded_gates
                    if gate.get("status") == "warn"
                    and gate.get("original_status") == "block"
                }
                for item in rec.get("deferred_failures", [])
                if isinstance(item, dict)
        ):
            refuse = "a deferred failure has no matching blocked gate result — re-run gate"
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
                   "warnings": warnings, "gate_reuse": gate_reuse,
                   "gate_tier": gate_tier, "required_tier": required_tier}
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
               "gate_tier": gate_tier, "required_tier": required_tier,
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
